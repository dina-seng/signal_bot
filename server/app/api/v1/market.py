"""Market data and OHLCV query endpoints."""

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, desc
from app.core.database import get_db
from app.core.config import settings
from app.api.deps import get_ingestion_service
from app.models.candle import Candle
from app.schemas.candle import CandleResponse, IngestionReport
from app.schemas.market import MarketSymbolInfo, IngestionRequest
from app.services.market_data.ingestion import IngestionService

router = APIRouter(prefix="/market", tags=["Market Data"])

# Symbol Metadata
SYMBOL_METADATA = {
    "EUR/USD": MarketSymbolInfo(
        symbol="EUR/USD",
        base_currency="EUR",
        quote_currency="USD",
        pip_size=0.0001,
        description="Euro / US Dollar",
    ),
    "GBP/USD": MarketSymbolInfo(
        symbol="GBP/USD",
        base_currency="GBP",
        quote_currency="USD",
        pip_size=0.0001,
        description="British Pound / US Dollar",
    ),
    "USD/JPY": MarketSymbolInfo(
        symbol="USD/JPY",
        base_currency="USD",
        quote_currency="JPY",
        pip_size=0.01,
        description="US Dollar / Japanese Yen",
    ),
    "XAU/USD": MarketSymbolInfo(
        symbol="XAU/USD",
        base_currency="XAU",
        quote_currency="USD",
        pip_size=0.01,
        description="Gold / US Dollar (Spot / Futures)",
    ),
}


@router.get("/symbols", response_model=List[MarketSymbolInfo])
def get_supported_symbols():
    """Retrieve list of supported Forex & Commodity symbols."""
    return [
        SYMBOL_METADATA.get(
            sym,
            MarketSymbolInfo(
                symbol=sym,
                base_currency=sym.split("/")[0] if "/" in sym else sym[:3],
                quote_currency=sym.split("/")[1] if "/" in sym else sym[3:],
                pip_size=0.0001,
                description=f"Forex pair {sym}",
            ),
        )
        for sym in settings.SUPPORTED_SYMBOLS
    ]


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
