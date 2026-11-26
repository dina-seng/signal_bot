"""Trading Signals, Multi-Pillar Scoring, and Market Scanner API Endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.config import settings
from app.api.deps import get_paper_trading_service, get_signal_generator
from app.models.signal import Signal
from app.schemas.signal import (
    MarketScanResponse,
    SignalResponse,
    SignalStatus,
    StatelessSignalRequest,
)
from app.services.signals import SignalGenerator
from app.services.signals.lifecycle import (
    filter_consumed_scan_results,
    filter_consumed_signals,
    is_consumed_signal,
    consumed_setup_keys,
    consumed_signal_ids,
)

router = APIRouter(prefix="/signals", tags=["Trading Signals & Scanner"])


def _authoritative_signal_context(db, service) -> tuple[float, float]:
    """Balance and risk % for signal sizing come from the paper account, never the client."""
    context = service.get_execution_context(db)
    if context is None:
        raise HTTPException(status_code=503, detail="No active paper account available for signal sizing.")
    return context["balance"], context["risk_percent"]


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
    unified: bool = Query(False, description="Return unified multi-timeframe signals across pairs"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    generator: SignalGenerator = Depends(get_signal_generator),
):
    """Retrieve active signals via Unified Multi-Timeframe Scanner or historical database signals."""
    if unified:
        target_symbols = [_normalize_symbol(symbol)] if symbol else settings.SUPPORTED_SYMBOLS
        scan_res = generator.scan_unified_all(
            db=db,
            symbols=target_symbols,
            persist_qualified=True,
        )
        unified_signals: List[SignalResponse] = []
        consumed_keys = consumed_setup_keys(db)
        consumed_ids = consumed_signal_ids(db)
        for r in scan_res.results:
            sig = r.signal
            if not sig:
                sig = SignalResponse(
                    symbol=r.symbol,
                    timeframe=r.timeframe,
                    direction=r.direction,
                    setup_score=r.setup_score,
                    entry_price=None,
                    stop_loss=None,
                    take_profit_1=None,
                    take_profit_2=None,
                    risk_reward=None,
                    fingerprint=f"UNIFIED_SCAN_{r.symbol}_{r.timeframe}",
                    reasons=r.reasons,
                    status=SignalStatus.ACTIVE if r.is_actionable else SignalStatus.EXPIRED,
                    trend_alignment=r.trend_alignment,
                    htf_trend=r.htf_trend,
                    is_broadcasted=False,
                    timestamp=scan_res.timestamp,
                )
            if direction and sig.direction.value != direction.upper().strip():
                continue
            if status and sig.status.value != status.upper().strip():
                continue
            if is_consumed_signal(sig, consumed_keys, consumed_ids):
                continue
            unified_signals.append(sig)
        return unified_signals

    # Fallback to querying historical DB records if unified=False
    stmt = select(Signal)
    if symbol:
        stmt = stmt.where(Signal.symbol == _normalize_symbol(symbol))
    if direction:
        stmt = stmt.where(Signal.direction == direction.upper().strip())
    if status:
        stmt = stmt.where(Signal.status == status.upper().strip())
    else:
        # Active feed only. EXECUTED/CLOSED/history is not an active signal.
        stmt = stmt.where(Signal.status == SignalStatus.ACTIVE.value)

    stmt = stmt.order_by(desc(Signal.timestamp)).limit(limit)
    return filter_consumed_signals(db, list(db.scalars(stmt).all()))


@router.get("/scan", response_model=MarketScanResponse)
def scan_markets(
    unified: bool = Query(True, description="Whether to use Unified Multi-Timeframe Scanner"),
    timeframe: str = Query("1h", description="Timeframe to scan if unified is False (e.g. 15m, 1h, 4h)"),
    persist_qualified: bool = Query(True, description="Whether to persist qualified signals to DB"),
    db: Session = Depends(get_db),
    generator: SignalGenerator = Depends(get_signal_generator),
    service=Depends(get_paper_trading_service),
):
    """Scan all supported Forex and Commodity markets for high-confluence trade setups.

    Balance and risk % are resolved from the active paper account; client-supplied
    values are intentionally not accepted.
    """
    account_balance, risk_percent = _authoritative_signal_context(db, service)
    if unified:
        scan_result = generator.scan_unified_all(
            db=db,
            symbols=settings.SUPPORTED_SYMBOLS,
            account_balance=account_balance,
            risk_percent=risk_percent,
            persist_qualified=persist_qualified,
        )
    else:
        scan_result = generator.scan_all_symbols(
            db=db,
            symbols=settings.SUPPORTED_SYMBOLS,
            timeframe=timeframe.lower().strip(),
            account_balance=account_balance,
            risk_percent=risk_percent,
            persist_qualified=persist_qualified,
        )
    return filter_consumed_scan_results(db, scan_result)


@router.get("/unified", response_model=MarketScanResponse)
def get_unified_signals(
    persist_qualified: bool = Query(True, description="Whether to persist qualified signals to DB"),
    db: Session = Depends(get_db),
    generator: SignalGenerator = Depends(get_signal_generator),
    service=Depends(get_paper_trading_service),
):
    """Unified Multi-Timeframe Scanner endpoint; balance/risk come from the paper account."""
    account_balance, risk_percent = _authoritative_signal_context(db, service)
    scan_result = generator.scan_unified_all(
        db=db,
        symbols=settings.SUPPORTED_SYMBOLS,
        account_balance=account_balance,
        risk_percent=risk_percent,
        persist_qualified=persist_qualified,
    )
    return filter_consumed_scan_results(db, scan_result)


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
        symbol=request.symbol or "XAU/USD",
        timeframe=request.timeframe or "1h",
        account_balance=request.account_balance or 10000.0,
        risk_percent=request.risk_percent or settings.MAX_RISK_PERCENT,
    )
