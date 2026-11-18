"""Market data and OHLCV query endpoints."""

from datetime import datetime, timezone
import time
from typing import List, Optional, Dict, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, desc
from app.core.database import get_db
from app.core.logging import logger
from app.core.config import ACTIVE_SYMBOLS, settings
from app.api.deps import get_ingestion_service, get_provider
from app.models.candle import Candle
from app.schemas.candle import CandleResponse, IngestionReport
from app.schemas.market import MarketSymbolInfo, IngestionRequest, QuoteResponse
from app.services.market_data.base import BaseMarketDataProvider
from app.services.market_data.ingestion import IngestionService

from app.services.market_data.symbols import (
    INSTRUMENT_SPECS,
    UnknownSymbolError,
    get_instrument_spec,
    normalize_symbol,
)

router = APIRouter(prefix="/market", tags=["Market Data"])


@router.get("/symbols", response_model=List[MarketSymbolInfo])
def get_supported_symbols():
    """Retrieve list of supported Forex & Commodity symbols from centralized specifications."""
    active_symbols = list(ACTIVE_SYMBOLS)
    results: List[MarketSymbolInfo] = []
    for sym in active_symbols:
        try:
            spec = get_instrument_spec(sym)
            results.append(
                MarketSymbolInfo(
                    symbol=spec.canonical,
                    base_currency=spec.base_currency,
                    quote_currency=spec.quote_currency,
                    pip_size=spec.pip_size,
                    description=spec.description,
                )
            )
        except UnknownSymbolError:
            pass
    return results


_quote_cache: Dict[Tuple[str, str], Tuple[float, QuoteResponse]] = {}

# Timestamp (time.time()) of the most recent dashboard heartbeat. Presence gating:
# active viewers refresh on QUOTE_CACHE_TTL_SECONDS, idle deployments on the much
# slower QUOTE_IDLE_CACHE_TTL_SECONDS. There is no background quote loop; refresh
# is lazy and only happens when something requests the quote.
_presence_last_beat: float = 0.0


def _presence_is_active(now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    return _presence_last_beat > 0.0 and (now - _presence_last_beat) < settings.QUOTE_PRESENCE_TTL_SECONDS


def _effective_cache_ttl(now: Optional[float] = None) -> float:
    if _presence_is_active(now):
        return float(settings.QUOTE_CACHE_TTL_SECONDS)
    return float(settings.QUOTE_IDLE_CACHE_TTL_SECONDS)


async def _resolve_quote(
    symbol: str,
    provider: BaseMarketDataProvider,
    db: Optional[Session] = None,
) -> QuoteResponse:
    try:
        canonical_symbol = normalize_symbol(symbol)
    except UnknownSymbolError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown market symbol: '{symbol}'. Must be one of {list(INSTRUMENT_SPECS.keys())}.",
        )

    provider_name = getattr(provider, "name", None) or provider.__class__.__name__.lower().replace("provider", "")
    cache_key = (provider_name, canonical_symbol)
    now = time.time()
    now_utc = datetime.now(timezone.utc)

    # 1. In-memory cache keyed by (provider, canonical_symbol). TTL is presence-gated:
    #    60s while a dashboard is watching, 300s when idle.
    cached = _quote_cache.get(cache_key)
    if cached and (now - cached[0] < _effective_cache_ttl(now)):
        cache_age_ms = round((now - cached[0]) * 1000, 1)
        cached_quote = cached[1].model_copy()
        cached_quote.cached = True
        cached_quote.cache_age_ms = cache_age_ms
        return cached_quote

    # 2. Fetch fresh quote from provider
    try:
        quote = await provider.fetch_quote(canonical_symbol)
    except Exception as e:
        logger.warning(f"Error fetching quote for {canonical_symbol} from {provider_name}: {e}")
        quote = None

    # Never cache 503 / error responses; fail loudly if quote is unavailable
    if not quote or quote.price <= 0:
        logger.error(f"All market data provider lookups failed for {canonical_symbol}.")
        raise HTTPException(
            status_code=503,
            detail=f"Real-time market quote currently unavailable for {canonical_symbol}",
        )

    # 3. Staleness check
    quote_age_sec = max(0.0, (now_utc - quote.timestamp).total_seconds()) if quote.timestamp else 0.0
    quote.age_seconds = round(quote_age_sec, 2)
    if quote_age_sec > settings.QUOTE_MAX_AGE_SECONDS:
        quote.is_stale = True
        quote.degraded = True
        stale_msg = f"Quote is stale ({quote_age_sec:.0f}s > {settings.QUOTE_MAX_AGE_SECONDS}s)"
        quote.fallback_reason = (
            f"{quote.fallback_reason}; {stale_msg}" if quote.fallback_reason else stale_msg
        )

    # 4. Relative deviation sanity cross-check against last closed candle
    if db is not None:
        try:
            last_candle = db.scalars(
                select(Candle)
                .where(Candle.symbol == canonical_symbol)
                .order_by(desc(Candle.timestamp))
                .limit(1)
            ).first()
            if last_candle and last_candle.close > 0:
                deviation_pct = abs(quote.price - float(last_candle.close)) / float(last_candle.close)
                if deviation_pct > settings.QUOTE_MAX_DEVIATION_PCT:
                    quote.degraded = True
                    dev_msg = (
                        f"Price deviates by {deviation_pct*100:.1f}% from last candle close ({last_candle.close})"
                    )
                    quote.fallback_reason = (
                        f"{quote.fallback_reason}; {dev_msg}" if quote.fallback_reason else dev_msg
                    )
                    logger.warning(f"Quote sanity flag for {canonical_symbol}: {dev_msg}")
        except Exception as db_err:
            logger.debug(f"Could not cross-check candle deviation for {canonical_symbol}: {db_err}")

    # 5. Handle mock provider flags
    if quote.provider == "mock" or "mock" in provider_name:
        quote.provider = "mock"
        quote.degraded = True

    # Cache successful quote
    quote.cached = False
    quote.cache_age_ms = 0.0
    _quote_cache[cache_key] = (now, quote.model_copy())
    return quote


@router.post("/presence")
def record_dashboard_presence():
    """Register a dashboard heartbeat so quote polling stays on the active cadence.

    The frontend calls this every 30s while the tab is visible. Without a heartbeat
    newer than QUOTE_PRESENCE_TTL_SECONDS the quote cache stretches to the idle TTL,
    which protects the daily provider credit budget.
    """
    global _presence_last_beat
    _presence_last_beat = time.time()
    return {
        "active": True,
        "last_heartbeat_at": datetime.fromtimestamp(_presence_last_beat, tz=timezone.utc),
        "presence_ttl_seconds": settings.QUOTE_PRESENCE_TTL_SECONDS,
        "cache_ttl_seconds": settings.QUOTE_CACHE_TTL_SECONDS,
        "idle_cache_ttl_seconds": settings.QUOTE_IDLE_CACHE_TTL_SECONDS,
    }


@router.get("/quote", response_model=QuoteResponse)
async def get_market_quote_query(
    symbol: str = Query("XAU/USD", description="Symbol e.g. XAU/USD"),
    provider: BaseMarketDataProvider = Depends(get_provider),
    db: Session = Depends(get_db),
):
    """Retrieve real-time price quote for a symbol (query parameter)."""
    return await _resolve_quote(symbol, provider, db=db)


@router.get("/{symbol:path}/quote", response_model=QuoteResponse)
async def get_market_quote_path(
    symbol: str,
    provider: BaseMarketDataProvider = Depends(get_provider),
    db: Session = Depends(get_db),
):
    """Retrieve real-time price quote for a symbol (path parameter)."""
    return await _resolve_quote(symbol, provider, db=db)


from app.services.market_data import filter_closed_candles


@router.get("/{symbol:path}/candles", response_model=List[CandleResponse])
def get_candles(
    symbol: str,
    timeframe: str = Query("15m", description="Timeframe e.g. 15m, 1h, 4h"),
    limit: int = Query(200, ge=1, le=5000, description="Max candles to retrieve"),
    only_closed: bool = Query(False, description="Filter for closed candles only"),
    start_time: Optional[datetime] = Query(None, description="Start timestamp UTC"),
    end_time: Optional[datetime] = Query(None, description="End timestamp UTC"),
    db: Session = Depends(get_db),
):
    """Retrieve historical stored candles for a symbol and timeframe."""
    # Normalize symbol
    clean_symbol = symbol.replace("%2F", "/").strip()
    if clean_symbol not in settings.SUPPORTED_SYMBOLS:
        # Check without slash
        for s in settings.SUPPORTED_SYMBOLS:
            if s.replace("/", "") == clean_symbol.replace("/", ""):
                clean_symbol = s
                break

    stmt = select(Candle).where(
        Candle.symbol == clean_symbol,
        Candle.timeframe == timeframe.lower(),
    )

    if start_time:
        stmt = stmt.where(Candle.timestamp >= start_time)
    if end_time:
        stmt = stmt.where(Candle.timestamp <= end_time)

    # Order descending to get latest limit, then return sorted ascending
    stmt = stmt.order_by(desc(Candle.timestamp)).limit(limit + (5 if only_closed else 0))
    records = list(db.scalars(stmt).all())
    records.reverse()

    if only_closed and records:
        records = filter_closed_candles(records, timeframe=timeframe)
        if len(records) > limit:
            records = records[-limit:]

    return records


@router.post("/sync", response_model=List[IngestionReport])
async def sync_market_data(
    payload: Optional[IngestionRequest] = None,
    ingestion_service: IngestionService = Depends(get_ingestion_service),
):
    """Trigger manual data ingestion from market data provider into database."""
    req = payload or IngestionRequest()
    symbols = [req.symbol] if req.symbol else settings.SUPPORTED_SYMBOLS
    timeframes = [req.timeframe] if req.timeframe else settings.SUPPORTED_TIMEFRAMES

    reports: List[IngestionReport] = []

    for sym in symbols:
        for tf in timeframes:
            try:
                report = await ingestion_service.sync_symbol_timeframe(
                    symbol=sym,
                    timeframe=tf,
                    limit=req.limit,
                )
                reports.append(report)
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed syncing {sym} [{tf}]: {str(e)}",
                )

    return reports
