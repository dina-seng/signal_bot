"""Trading Signals, Multi-Pillar Scoring, and Market Scanner API Endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.config import settings
from app.api.deps import get_signal_generator
from app.models.signal import Signal
from app.schemas.signal import (
    MarketScanResponse,
    SignalResponse,
    StatelessSignalRequest,
)
from app.services.signals import SignalGenerator

router = APIRouter(prefix="/signals", tags=["Trading Signals & Scanner"])


def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol string."""
    clean_symbol = symbol.replace("%2F", "/").strip()
    if clean_symbol in settings.SUPPORTED_SYMBOLS:
        return clean_symbol
    for s in settings.SUPPORTED_SYMBOLS:
        if s.replace("/", "") == clean_symbol.replace("/", ""):
            return s
    return clean_symbol


@router.get("", response_model=List[SignalResponse])
def get_signals(
    symbol: Optional[str] = Query(None, description="Filter by currency pair (e.g. EUR/USD)"),
    direction: Optional[str] = Query(None, description="Filter by direction: BUY, SELL, WAIT"),
    status: Optional[str] = Query(None, description="Filter by status: ACTIVE, INVALIDATED, TP1_HIT, etc."),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Retrieve historical and active generated trading signals from database."""
    stmt = select(Signal)

    if symbol:
        stmt = stmt.where(Signal.symbol == _normalize_symbol(symbol))
    if direction:
        stmt = stmt.where(Signal.direction == direction.upper().strip())
    if status:
        stmt = stmt.where(Signal.status == status.upper().strip())

    stmt = stmt.order_by(desc(Signal.timestamp)).limit(limit)
    return list(db.scalars(stmt).all())


@router.get("/scan", response_model=MarketScanResponse)
def scan_markets(
    timeframe: str = Query("1h", description="Timeframe to scan (e.g. 15m, 1h, 4h)"),
    account_balance: float = Query(10000.0, ge=100.0),
    risk_percent: float = Query(0.5, ge=0.1, le=5.0),
    persist_qualified: bool = Query(True, description="Whether to persist qualified signals to DB"),
    db: Session = Depends(get_db),
    generator: SignalGenerator = Depends(get_signal_generator),
):
    """Scan all supported Forex and Commodity markets for high-confluence trade setups."""
    return generator.scan_all_symbols(
        db=db,
        symbols=settings.SUPPORTED_SYMBOLS,
        timeframe=timeframe.lower().strip(),
        account_balance=account_balance,
        risk_percent=risk_percent,
        persist_qualified=persist_qualified,
    )


@router.post("/evaluate", response_model=SignalResponse)
def evaluate_stateless_signal(
    request: StatelessSignalRequest,
    generator: SignalGenerator = Depends(get_signal_generator),
):
    """Stateless on-demand signal evaluation, multi-factor scoring, and risk calculation for custom candles."""
    if not request.candles or len(request.candles) < 10:
        raise HTTPException(
            status_code=400,
            detail="Candles list must contain at least 10 candles for proper indicator & structure analysis.",
        )

    return generator.evaluate_market_signal(
        candles_primary=request.candles,
        symbol=request.symbol or "EUR/USD",
        timeframe=request.timeframe or "1h",
        account_balance=request.account_balance or 10000.0,
        risk_percent=request.risk_percent or 0.5,
    )
