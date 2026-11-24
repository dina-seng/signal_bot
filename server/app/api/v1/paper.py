"""Paper Trading, Virtual Accounts, and Position Management API Endpoints."""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.api.deps import get_paper_trading_service
from app.models.candle import Candle
from app.models.paper import PaperTrade, VirtualAccount
from app.services.signals.risk_manager import RiskManager
from app.schemas.paper_trading import (
    AccountDepositRequest,
    AccountResetRequest,
    AutoTradeSignalRequest,
    PaperOrderCreate,
    PaperPortfolioPerformance,
    PaperPositionCloseRequest,
    PaperPositionModifyRequest,
    PaperTradeResponse,
    PositionSyncReport,
    VirtualAccountCreate,
    VirtualAccountResponse,
)
from app.services.paper_trading import PaperTradingService

router = APIRouter(prefix="/paper", tags=["Paper Trading & Virtual Accounts"])

_OPEN_TRADE_STATUSES = {"OPEN", "PARTIALLY_CLOSED"}


class PaperSummaryResponse(BaseModel):
    """Account and open positions computed from one shared live price tick."""
    account: VirtualAccountResponse
    positions: List[PaperTradeResponse]
    tick_price: Optional[float]
    tick_source: str
    as_of: datetime


def _resolve_live_tick(db: Session) -> Tuple[Optional[float], str]:
    """Resolve one price tick: live quote cache first, last closed candle as fallback."""
    from app.api.v1.market import get_cached_quote

    quote = get_cached_quote("XAU/USD")
    if quote and quote.price and quote.price > 0 and not quote.is_stale:
        return float(quote.price), "quote"

    last_candle = db.scalars(
        select(Candle)
        .where(Candle.symbol == "XAU/USD")
        .order_by(desc(Candle.timestamp))
        .limit(1)
    ).first()
    if last_candle is not None and float(last_candle.close) > 0:
        return float(last_candle.close), "candle"
    return None, "stored"


def _mark_trade_entities_to_tick(trades: List[PaperTrade], price: float) -> None:
    """Write the shared tick into the ORM entities that feed account equity."""
    pip_size = RiskManager.get_pip_size("XAU/USD")
    pip_value = RiskManager.get_pip_value_per_lot("XAU/USD")
    for t in trades:
        if t.symbol != "XAU/USD" or t.status not in _OPEN_TRADE_STATUSES:
            continue
        t.current_price = price
        direction = getattr(t.direction, "value", t.direction)
        pips = (
            (price - t.entry_price) / pip_size
            if direction == "BUY"
            else (t.entry_price - price) / pip_size
        )
        t.pnl_pips = round(pips, 1)
        t.unrealized_pnl = round(pips * pip_value * t.remaining_position_size, 2)


def _sync_paper_state_to_live_tick(
    db: Session, service: PaperTradingService, account_id: Optional[int] = None
) -> Tuple[VirtualAccount, List[PaperTrade], Optional[float], str]:
    """Mark all open trades with one tick, persist it, then recompute account equity.

    Both /paper/account and /paper/summary use this so equity and floating P&L can
    never disagree with the positions list by a price tick.
    """
    if account_id:
        account = service.account_manager.get_account(db, account_id)
    else:
        account = service.account_manager.get_or_create_default_account(db)

    trades = list(
        db.scalars(
            select(PaperTrade).where(
                PaperTrade.account_id == account.id,
                PaperTrade.status.in_(_OPEN_TRADE_STATUSES),
            )
        ).all()
    )
    tick_price, tick_source = _resolve_live_tick(db)
    if tick_price is not None:
        _mark_trade_entities_to_tick(trades, tick_price)
        db.commit()
    return account, trades, tick_price, tick_source


def _normalize_symbol(symbol: str) -> str:
    """Normalize currency pair symbol string."""
    clean_symbol = symbol.replace("%2F", "/").strip()
    if clean_symbol in settings.SUPPORTED_SYMBOLS:
        return clean_symbol
    for s in settings.SUPPORTED_SYMBOLS:
        if s.replace("/", "") == clean_symbol.replace("/", ""):
            return s
    return clean_symbol


@router.get("/account", response_model=VirtualAccountResponse)
def get_virtual_account(
    account_id: Optional[int] = Query(None, description="Optional account ID (defaults to primary account)"),
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Retrieve virtual trading account summary, balance, equity, and margin levels.

    Open positions are first re-marked with the shared live tick so equity and
    floating P&L match the positions endpoint exactly.
    """
    try:
        _sync_paper_state_to_live_tick(db, service, account_id)
        return service.get_account_summary(db=db, account_id=account_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/summary", response_model=PaperSummaryResponse)
def get_paper_summary(
    account_id: Optional[int] = Query(None, description="Optional account ID (defaults to primary account)"),
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Atomic snapshot: account + open positions from ONE shared live price tick.

    The dashboard uses this so the header (equity / floating P&L) and the position
    ledger can never disagree due to fetch ordering or a price tick between calls.
    """
    try:
        account, trades, tick_price, tick_source = _sync_paper_state_to_live_tick(
            db, service, account_id
        )
        account_response = service.account_manager.get_account_response(db, account)
        positions = [PaperTradeResponse.model_validate(t) for t in trades]
        for pos in positions:
            pos.price_source = tick_source
        return PaperSummaryResponse(
            account=account_response,
            positions=positions,
            tick_price=tick_price,
            tick_source=tick_source,
            as_of=datetime.now(timezone.utc),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/account/create", response_model=VirtualAccountResponse)
def create_virtual_account(
    request: VirtualAccountCreate,
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Create a new virtual trading account with custom balance and leverage."""
    return service.create_virtual_account(db=db, request=request)


@router.post("/account/deposit", response_model=VirtualAccountResponse)
def deposit_virtual_funds(
    request: AccountDepositRequest,
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Deposit or adjust funds in the virtual trading account."""
    try:
        return service.deposit_virtual_funds(db=db, request=request, account_id=account_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/account/reset", response_model=VirtualAccountResponse)
def reset_virtual_account(
    request: AccountResetRequest,
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Reset virtual account to starting balance and liquidate all positions."""
    try:
        return service.reset_virtual_account(db=db, request=request, account_id=account_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/orders", response_model=PaperTradeResponse)
def place_paper_order(
    order: PaperOrderCreate,
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Place a manual or algorithmic paper order (MARKET, LIMIT, STOP)."""
    order.symbol = _normalize_symbol(order.symbol)
    try:
        return service.place_order(db=db, order=order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Order execution failed: {str(e)}")


@router.post("/orders/from-signal", response_model=PaperTradeResponse, status_code=201)
def trade_from_signal(
    request: AutoTradeSignalRequest,
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Auto-execute a paper trade from an active signal (201 Created).

    The SL is derived from the signal's own timeframe structure (15m entry =
    15m SL), TP is set dynamically at 1:3, and the lot size is the fixed value
    from the User Risk Profile. Wide structural stops are accepted.
    """
    request.symbol = _normalize_symbol(request.symbol)
    try:
        return service.trade_from_signal(db=db, request=request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Signal trade execution failed: {str(e)}")


def _mark_positions_with_quote(db: Session, positions: List[PaperTradeResponse]) -> List[PaperTradeResponse]:
    """Mark open positions from the shared quote cache, falling back to the last
    closed candle only when the cached quote is unavailable or STALE."""
    if not positions:
        return positions

    from app.api.v1.market import get_cached_quote

    open_statuses = {"OPEN", "PARTIALLY_CLOSED"}
    quote = get_cached_quote("XAU/USD")
    quote_usable = bool(quote and quote.price > 0 and not quote.is_stale)

    candle_close: Optional[float] = None
    if not quote_usable:
        last_candle = db.scalars(
            select(Candle)
            .where(Candle.symbol == "XAU/USD")
            .order_by(desc(Candle.timestamp))
            .limit(1)
        ).first()
        if last_candle is not None and float(last_candle.close) > 0:
            candle_close = float(last_candle.close)

    for pos in positions:
        pos.price_source = pos.price_source or "stored"
        if pos.symbol != "XAU/USD" or pos.status not in open_statuses:
            continue

        if quote_usable:
            price = float(quote.price)
            pos.price_source = "quote"
        elif candle_close is not None:
            price = candle_close
            pos.price_source = "candle"
        else:
            continue

        pos.current_price = price
        pip_size = RiskManager.get_pip_size(pos.symbol)
        pip_value = RiskManager.get_pip_value_per_lot(pos.symbol)
        if pip_size > 0:
            direction = getattr(pos.direction, "value", pos.direction)
            pips = (price - pos.entry_price) / pip_size if direction == "BUY" else (pos.entry_price - price) / pip_size
            pos.pnl_pips = round(pips, 1)
            pos.unrealized_pnl = round(pips * pip_value * pos.remaining_position_size, 2)
    return positions


@router.get("/positions", response_model=List[PaperTradeResponse])
def get_open_positions(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    status: Optional[str] = Query(None, description="OPEN, PARTIALLY_CLOSED, or PENDING"),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Query currently open and pending paper trading positions."""
    norm_sym = _normalize_symbol(symbol) if symbol else None
    positions = service.get_positions(db=db, account_id=account_id, symbol=norm_sym, status=status)
    return _mark_positions_with_quote(db, positions)


@router.get("/trades", response_model=List[PaperTradeResponse])
def get_trade_history(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    limit: int = Query(50, ge=1, le=500),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Query historical closed paper trades."""
    norm_sym = _normalize_symbol(symbol) if symbol else None
    return service.get_trade_history(db=db, account_id=account_id, symbol=norm_sym, limit=limit)


@router.get("/trades/{trade_id}", response_model=PaperTradeResponse)
def get_trade_by_id(
    trade_id: int,
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Retrieve specific paper trade by ID."""
    trade = service.get_trade_by_id(db=db, trade_id=trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail=f"Paper trade #{trade_id} not found.")
    return trade


@router.put("/positions/{trade_id}/modify", response_model=PaperTradeResponse)
def modify_position_levels(
    trade_id: int,
    request: PaperPositionModifyRequest,
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Modify Stop Loss and Take Profit levels on an active position."""
    try:
        return service.modify_position_levels(db=db, trade_id=trade_id, request=request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/positions/{trade_id}/close", response_model=PaperTradeResponse)
def close_position(
    trade_id: int,
    request: PaperPositionCloseRequest,
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Close an open paper position fully or partially at market price."""
    try:
        return service.close_position(db=db, trade_id=trade_id, request=request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/monitor/sync", response_model=PositionSyncReport)
def sync_market_prices(
    prices: Optional[Dict[str, float]] = None,
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Trigger price synchronization and SL/TP auto-monitoring across active positions."""
    return service.sync_prices(db=db, symbol_prices=prices)


@router.get("/performance", response_model=PaperPortfolioPerformance)
def get_portfolio_performance(
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Retrieve virtual trading portfolio performance statistics and win rate."""
    try:
        return service.get_portfolio_performance(db=db, account_id=account_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
