"""Single-round-trip dashboard snapshot endpoint.

All inner fetches reuse the existing endpoint logic and hit the cache/DB rather
than the upstream provider. They are gathered concurrently and isolated so one
failing section cannot fail the whole snapshot.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import (
    get_indicator_service,
    get_liquidity_service,
    get_news_filter_engine,
    get_paper_trading_service,
    get_provider,
    get_signal_generator,
    get_structure_engine,
    get_telegram_bot_service,
)
from app.api.v1 import (
    config as config_api,
    indicators as indicators_api,
    liquidity as liquidity_api,
    market as market_api,
    news as news_api,
    paper as paper_api,
    signals as signals_api,
    structure as structure_api,
    telegram as telegram_api,
)
from app.core.config import settings
from app.core.logging import logger
from app.core.metrics import metrics
from app.core.database import get_db
from app.schemas.candle import CandleResponse
from app.schemas.dashboard import DashboardSnapshotResponse
from app.schemas.news import NewsEventResponse
from app.services.market_data.cache import derived_cache
from app.services.market_data.symbols import target_account_for_symbol

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


async def _ensure_symbol_history(symbol: str) -> None:
    """Backfill provider-only instruments before DB-backed analytics run.

    The unified scanner reads closed candles from the database only. BTC/USD has
    no ingested rows on most deployments (its chart is served live from Binance),
    so the momentum card would otherwise render an empty WAIT signal with no
    EMA/RSI/ADX metadata. The ingestion service's freshness gate makes this a
    no-op once the latest bar for each timeframe is already stored.
    """
    if str(symbol or "").strip().upper() != "BTC/USD":
        return

    # Imported lazily so the dashboard module stays importable in environments
    # where the market-data package is not configured.
    from app.core.database import SessionLocal
    from app.services.market_data import get_provider_for_symbol
    from app.services.market_data.ingestion import IngestionService

    provider = get_provider_for_symbol(symbol)
    # Use a dedicated session: this coroutine can interleave with the other
    # snapshot sections, and a SQLAlchemy Session is not safe to share across
    # concurrent coroutines.
    with SessionLocal() as ingest_db:
        ingestion = IngestionService(provider, ingest_db)
        for timeframe, limit in (("15m", 320), ("1h", 320), ("4h", 220)):
            try:
                await ingestion.sync_symbol_timeframe(
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=limit,
                )
            except Exception as exc:  # never fail the whole snapshot
                logger.warning(
                    "History backfill failed for %s [%s]: %s",
                    symbol,
                    timeframe,
                    exc,
                )


async def _section(
    name: str,
    factory: Callable[[], Awaitable[Any]],
    default: Any,
    timings: Dict[str, float],
) -> Any:
    """Run one snapshot section with timing, logging and failure isolation."""
    started = time.perf_counter()
    try:
        return await factory()
    except Exception as exc:
        logger.warning("Dashboard snapshot section '%s' failed: %s", name, exc)
        return default
    finally:
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        timings[name] = elapsed_ms
        stage = "provider" if name == "quote" else "db"
        metrics.record_stage(stage, elapsed_ms)


def _filter_by_account(rows: List[Any], account_type: Optional[str]) -> List[Any]:
    """Restrict paper rows to the workspace account (MAIN=XAU, CENT=BTC)."""
    if not account_type:
        return rows
    wanted = account_type.upper().strip()
    filtered: List[Any] = []
    for row in rows:
        meta = getattr(row, "metadata", None) or {}
        account = meta.get("target_account") if isinstance(meta, dict) else None
        account = str(account or target_account_for_symbol(str(getattr(row, "symbol", "") or ""))).upper()
        if account == wanted:
            filtered.append(row)
    return filtered


def _overlay_forming_quote(candles: list, quote: Any) -> list:
    """Project the fast quote tick onto the newest cached bar.

    The cached array holds CLOSED history (30s derived cache). Only its last bar
    is re-based onto the live quote so the chart's forming close/bid equals the
    number the left panel renders. Never mutate cached objects in place: a
    snapshot must not contaminate the cache shared by later requests.
    """
    price = getattr(quote, "price", None)
    if not candles or not isinstance(price, (int, float)) or price <= 0:
        return candles

    price = float(price)
    last = candles[-1]
    if isinstance(last, BaseModel):
        updated = last.model_copy()
        updated.high = max(float(updated.high), price)
        updated.low = min(float(updated.low), price)
        updated.close = price
    elif isinstance(last, dict):
        updated = dict(last)
        updated["high"] = max(float(updated.get("high", price)), price)
        updated["low"] = min(float(updated.get("low", price)), price)
        updated["close"] = price
    else:
        return candles

    return [*candles[:-1], updated]


@router.get("/snapshot", response_model=DashboardSnapshotResponse)
async def get_dashboard_snapshot(
    symbol: str = Query("XAU/USD", description="Primary dashboard symbol"),
    account_type: Optional[str] = Query(
        None, description="Optional workspace account filter: MAIN (XAU/USD) or CENT (BTC/USD)"
    ),
    timeframe: str = Query("15m", description="Chart timeframe"),
    candle_limit: int = Query(settings.DASHBOARD_CANDLE_LIMIT, ge=1, le=500),
    derived_limit: int = Query(settings.DASHBOARD_DERIVED_LIMIT, ge=20, le=2000),
    db: Session = Depends(get_db),
    provider=Depends(get_provider),
    paper_service=Depends(get_paper_trading_service),
    indicator_service=Depends(get_indicator_service),
    structure_engine=Depends(get_structure_engine),
    liquidity_service=Depends(get_liquidity_service),
    signal_generator=Depends(get_signal_generator),
    news_filter_engine=Depends(get_news_filter_engine),
    telegram_service=Depends(get_telegram_bot_service),
):
    """Return quote, candles, analytics, trading state and status in ONE call."""
    timings: Dict[str, float] = {}

    # Persist provider-only instruments (BTC/USD) before the DB-backed
    # analytics and scanner sections read candles.
    await _ensure_symbol_history(symbol)

    async def quote_section():
        return await market_api._resolve_quote(symbol, provider, db=db)

    async def candles_section():
        # CLOSED bars only: they change on candle close, so a 30s derived cache
        # is correct here. The currently-open bar is overlaid from the fast
        # quote path after gather() (see _overlay_forming_quote).
        key = ("candles", symbol, timeframe, candle_limit)

        async def compute():
            rows = await market_api.get_candles(
                symbol, timeframe, candle_limit, True, None, None, db
            )
            return [CandleResponse.model_validate(row) for row in rows]

        return await derived_cache.get_or_fetch(
            key, settings.DERIVED_CACHE_TTL_SECONDS, compute
        )

    async def indicators_section():
        key = ("indicators", symbol, timeframe, derived_limit)

        async def compute():
            return indicators_api.get_indicator_analysis(
                symbol,
                timeframe,
                derived_limit,
                settings.EMA_FAST,
                settings.EMA_MID,
                settings.EMA_SLOW,
                settings.RSI_PERIOD,
                settings.ATR_PERIOD,
                db,
                indicator_service,
            )

        return await derived_cache.get_or_fetch(
            key, settings.DERIVED_CACHE_TTL_SECONDS, compute
        )

    async def structure_section():
        key = ("structure", symbol, timeframe, derived_limit)

        async def compute():
            return structure_api.get_symbol_structure(
                symbol,
                timeframe,
                None,
                derived_limit,
                False,
                None,
                db,
                structure_engine,
            )

        return await derived_cache.get_or_fetch(
            key, settings.DERIVED_CACHE_TTL_SECONDS, compute
        )

    async def liquidity_section():
        key = ("liquidity", symbol, timeframe, derived_limit)

        async def compute():
            return liquidity_api.get_sr_zones_and_pools(
                symbol, timeframe, None, None, derived_limit, db, liquidity_service
            )

        return await derived_cache.get_or_fetch(
            key, settings.DERIVED_CACHE_TTL_SECONDS, compute
        )

    async def paper_section():
        # Atomic snapshot: account, equity, P&L and the position ledger are all
        # derived from the SAME live tick, exactly as GET /paper/summary does.
        # Keyword arguments are mandatory here: `account_type` sits between
        # `account_id` and `db` in the endpoint signature, so a positional call
        # silently bound `db` to `account_type` and raised TypeError (the
        # section then returned None, leaving the header stuck at $0.00).
        return paper_api.get_paper_summary(
            account_id=None,
            account_type=account_type,
            db=db,
            service=paper_service,
        )

    async def trades_section():
        return paper_api.get_trade_history(
            symbol=None,
            limit=settings.DASHBOARD_TRADE_HISTORY_LIMIT,
            account_id=None,
            account_type=account_type,
            db=db,
            service=paper_service,
        )

    async def performance_section():
        return paper_api.get_portfolio_performance(
            account_id=None,
            db=db,
            service=paper_service,
        )

    async def signals_section():
        key = ("signals", symbol, timeframe)

        async def compute():
            return signals_api.get_signals(
                symbol=symbol,
                direction=None,
                status=None,
                account_type=account_type,
                unified=True,
                limit=settings.DASHBOARD_SIGNALS_LIMIT,
                db=db,
                generator=signal_generator,
            )

        return await derived_cache.get_or_fetch(
            key, settings.DERIVED_CACHE_TTL_SECONDS, compute
        )

    async def news_section():
        rows = news_api.get_economic_calendar(
            None, None, None, None, settings.DASHBOARD_NEWS_LIMIT, db
        )
        return [NewsEventResponse.model_validate(row) for row in rows]

    async def blackout_section():
        return news_api.check_news_blackout(
            symbol, None, None, None, "HIGH", db, news_filter_engine
        )

    async def telegram_section():
        return telegram_api.get_bot_status(telegram_service)

    async def scanner_section():
        return telegram_api.get_scanner_status(telegram_service)

    async def config_section():
        return config_api.get_system_config()

    (
        quote,
        candles,
        indicators,
        structure,
        liquidity,
        summary,
        trades,
        performance,
        signals,
        news,
        blackout,
        telegram_status,
        scanner_status,
        system_config,
    ) = await asyncio.gather(
        _section("quote", quote_section, None, timings),
        _section("candles", candles_section, [], timings),
        _section("indicators", indicators_section, None, timings),
        _section("structure", structure_section, None, timings),
        _section("liquidity", liquidity_section, None, timings),
        _section("paper", paper_section, None, timings),
        _section("trades", trades_section, [], timings),
        _section("performance", performance_section, None, timings),
        _section("signals", signals_section, [], timings),
        _section("news", news_section, [], timings),
        _section("blackout", blackout_section, None, timings),
        _section("telegram_status", telegram_section, None, timings),
        _section("scanner_status", scanner_section, None, timings),
        _section("config", config_section, None, timings),
    )

    # Prefer the atomic summary's ledger so header P&L and positions cannot
    # disagree with each other (same tick, same transaction state).
    positions = _filter_by_account(
        summary.positions if summary is not None else [], account_type
    )
    trades = _filter_by_account(trades, account_type)

    # Two candle layers in one response: `candles` is the 30s cached CLOSED
    # history with its newest bar projected onto the fast quote, while
    # `live_quote` is the same fast tick the left panel shows. The chart uses
    # live_quote for the forming bar and never re-derives it from stale candles.
    live_candles = _overlay_forming_quote(candles, quote)

    serialize_started = time.perf_counter()
    response = DashboardSnapshotResponse(
        symbol=symbol,
        timeframe=timeframe,
        quote=quote,
        live_quote=quote,
        candles=live_candles,
        indicators=indicators,
        structure=structure,
        liquidity=liquidity,
        paper_summary=summary,
        positions=positions,
        trades=trades,
        performance=performance,
        signals=signals,
        news=news,
        blackout=blackout,
        telegram_status=telegram_status,
        scanner_status=scanner_status,
        config=system_config,
        as_of=datetime.now(timezone.utc),
        timings_ms=timings,
    )
    serialize_ms = round((time.perf_counter() - serialize_started) * 1000.0, 2)
    timings["serialize"] = serialize_ms
    metrics.record_stage("serialize", serialize_ms)
    return response
