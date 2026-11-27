"""Paper Trading Orchestration Service and Portfolio Performance Reporter."""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.config import settings
from app.core.logging import logger
from app.models.paper import VirtualAccount, PaperTrade, AccountTransaction
from app.models.signal import Signal
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
from app.schemas.signal import SignalDirection
from app.services.signals import RiskEngine
from app.services.paper_trading.account_manager import VirtualAccountManager
from app.services.paper_trading.order_executor import PaperOrderExecutor
from app.services.paper_trading.position_manager import PaperPositionManager


class PaperTradingService:
    """End-to-end service for virtual trading accounts, orders, positions, and performance statistics."""

    def __init__(
        self,
        account_manager: Optional[VirtualAccountManager] = None,
        order_executor: Optional[PaperOrderExecutor] = None,
        position_manager: Optional[PaperPositionManager] = None,
    ):
        self.account_manager = account_manager or VirtualAccountManager()
        self.order_executor = order_executor or PaperOrderExecutor(account_manager=self.account_manager)
        self.position_manager = position_manager or PaperPositionManager(account_manager=self.account_manager)

    # -------------------------------------------------------------
    # 1. Virtual Account Operations
    # -------------------------------------------------------------
    def get_execution_context(self, db: Session) -> Optional[Dict[str, float]]:
        """Authoritative balance + risk % shared by dashboard, scanner and executor.

        Returns None when no active paper account exists; callers must handle that
        explicitly instead of substituting a fictional balance.
        """
        account = self.account_manager.get_active_account(db)
        if account is None:
            return None
        return {
            "balance": float(account.balance),
            "risk_percent": float(settings.MAX_RISK_PERCENT),
        }

    def get_account_summary(self, db: Session, account_id: Optional[int] = None) -> VirtualAccountResponse:
        """Get virtual account financial summary."""
        if account_id:
            account = self.account_manager.get_account(db, account_id)
            if not account:
                raise ValueError(f"Virtual Account #{account_id} not found.")
        else:
            account = self.account_manager.get_or_create_default_account(db)
        return self.account_manager.get_account_response(db, account)

    def create_virtual_account(self, db: Session, request: VirtualAccountCreate) -> VirtualAccountResponse:
        """Create a new virtual account."""
        account = self.account_manager.create_account(db, request)
        return self.account_manager.get_account_response(db, account)

    def deposit_virtual_funds(self, db: Session, request: AccountDepositRequest, account_id: Optional[int] = None) -> VirtualAccountResponse:
        """Deposit or adjust virtual funds."""
        acc = self.account_manager.get_or_create_default_account(db) if not account_id else db.get(VirtualAccount, account_id)
        if not acc:
            raise ValueError("Virtual account not found.")
        updated_acc = self.account_manager.deposit_funds(db, acc.id, request.amount, request.description or "Deposit")
        return self.account_manager.get_account_response(db, updated_acc)

    def reset_virtual_account(self, db: Session, request: AccountResetRequest, account_id: Optional[int] = None) -> VirtualAccountResponse:
        """Reset virtual account balance and liquidate positions."""
        acc = self.account_manager.get_or_create_default_account(db) if not account_id else db.get(VirtualAccount, account_id)
        if not acc:
            raise ValueError("Virtual account not found.")
        reset_acc = self.account_manager.reset_account(db, acc.id, request.initial_balance or 10000.0)
        return self.account_manager.get_account_response(db, reset_acc)

    # -------------------------------------------------------------
    # 2. Orders and Positions Operations
    # -------------------------------------------------------------
    def place_order(self, db: Session, order: PaperOrderCreate) -> PaperTradeResponse:
        """Place manual or algorithmic paper order."""
        trade = self.order_executor.execute_order(db=db, order=order)
        return PaperTradeResponse.model_validate(trade)

    def trade_from_signal(self, db: Session, request: AutoTradeSignalRequest) -> PaperTradeResponse:
        """Auto-execute trade position directly from a signal."""
        trade = self.order_executor.open_trade_from_signal(db=db, request=request)
        return PaperTradeResponse.model_validate(trade)

    def resolve_signal_levels(
        self, db: Session, signal: Signal, entry_price: float, timeframe: str
    ):
        """Resolve the entry-timeframe structural SL/TP without placing an order.

        Used by the scanner's pre-execution safety gates so eligibility is based
        on the exact same 15m structural stop that execution will apply.
        """
        pip_size = RiskEngine.get_pip_size(signal.symbol)
        return self.order_executor.resolve_signal_levels(
            db=db,
            signal=signal,
            entry_price=entry_price,
            timeframe=timeframe,
            pip_size=pip_size,
        )

    def get_positions(
        self,
        db: Session,
        account_id: Optional[int] = None,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[PaperTradeResponse]:
        """Query active and pending paper positions."""
        acc = self.account_manager.get_or_create_default_account(db) if not account_id else db.get(VirtualAccount, account_id)
        if not acc:
            return []

        stmt = select(PaperTrade).where(PaperTrade.account_id == acc.id)
        if status:
            normalized = status.upper().strip()
            if normalized == "OPEN":
                # A partially closed runner is still a running position. The
                # dashboard asks for ?status=OPEN, so it must include both open
                # states or TP1 partials vanish from the Positions tab.
                stmt = stmt.where(PaperTrade.status.in_(["OPEN", "PARTIALLY_CLOSED"]))
            else:
                stmt = stmt.where(PaperTrade.status == normalized)
        else:
            stmt = stmt.where(PaperTrade.status.in_(["OPEN", "PARTIALLY_CLOSED", "PENDING"]))

        if symbol:
            stmt = stmt.where(PaperTrade.symbol == symbol)

        stmt = stmt.order_by(desc(PaperTrade.opened_at))
        trades = list(db.scalars(stmt).all())
        return [PaperTradeResponse.model_validate(t) for t in trades]

    def get_trade_history(
        self,
        db: Session,
        account_id: Optional[int] = None,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> List[PaperTradeResponse]:
        """Query closed historical paper trades."""
        acc = self.account_manager.get_or_create_default_account(db) if not account_id else db.get(VirtualAccount, account_id)
        if not acc:
            return []

        stmt = select(PaperTrade).where(PaperTrade.account_id == acc.id, PaperTrade.status == "CLOSED")
        if symbol:
            stmt = stmt.where(PaperTrade.symbol == symbol)

        stmt = stmt.order_by(desc(PaperTrade.closed_at)).limit(limit)
        trades = list(db.scalars(stmt).all())
        return [PaperTradeResponse.model_validate(t) for t in trades]

    def get_trade_by_id(self, db: Session, trade_id: int) -> Optional[PaperTradeResponse]:
        """Get paper trade by ID."""
        t = db.get(PaperTrade, trade_id)
        return PaperTradeResponse.model_validate(t) if t else None

    def modify_position_levels(self, db: Session, trade_id: int, request: PaperPositionModifyRequest) -> PaperTradeResponse:
        """Modify Stop Loss and Take Profit levels on active position."""
        t = self.position_manager.modify_position(
            db=db,
            trade_id=trade_id,
            stop_loss=request.stop_loss,
            take_profit_1=request.take_profit_1,
            take_profit_2=request.take_profit_2,
        )
        return PaperTradeResponse.model_validate(t)

    def close_position(self, db: Session, trade_id: int, request: PaperPositionCloseRequest) -> PaperTradeResponse:
        """Close paper position fully or partially."""
        t = self.position_manager.close_position(
            db=db,
            trade_id=trade_id,
            current_price=request.exit_price,
            close_ratio=request.close_ratio,
            exit_reason=request.exit_reason or "MANUAL",
        )
        return PaperTradeResponse.model_validate(t)

    def sync_prices(self, db: Session, symbol_prices: Optional[Dict[str, float]] = None) -> PositionSyncReport:
        """Tick all active/pending positions against latest market prices."""
        return self.position_manager.sync_market_prices(db=db, symbol_prices=symbol_prices)

    # -------------------------------------------------------------
    # 3. Virtual Portfolio Performance Statistics
    # -------------------------------------------------------------
    def get_portfolio_performance(self, db: Session, account_id: Optional[int] = None) -> PaperPortfolioPerformance:
        """Compute portfolio performance statistics for virtual account."""
        acc = self.account_manager.get_or_create_default_account(db) if not account_id else db.get(VirtualAccount, account_id)
        if not acc:
            raise ValueError("Virtual account not found.")

        self.account_manager.recalculate_account_financials(db, acc)

        all_trades = list(db.scalars(select(PaperTrade).where(PaperTrade.account_id == acc.id)).all())
        open_trades = [t for t in all_trades if t.status in ("OPEN", "PARTIALLY_CLOSED")]
        closed_trades = [t for t in all_trades if t.status == "CLOSED"]

        winning_trades = [t for t in closed_trades if t.realized_pnl > 0.0001]
        losing_trades = [t for t in closed_trades if t.realized_pnl < -0.0001]

        total_closed = len(closed_trades)
        wins = len(winning_trades)
        losses = len(losing_trades)
        win_rate = round((wins / total_closed) * 100.0, 2) if total_closed > 0 else 0.0

        gross_profit = sum(t.realized_pnl for t in winning_trades)
        gross_loss = abs(sum(t.realized_pnl for t in losing_trades))

        if gross_loss > 0.0:
            profit_factor = round(gross_profit / gross_loss, 2)
        elif gross_profit > 0.0:
            profit_factor = 99.99
        else:
            profit_factor = 0.0

        avg_win = round(gross_profit / wins, 2) if wins > 0 else 0.0
        avg_loss = round(gross_loss / losses, 2) if losses > 0 else 0.0

        total_realized = round(sum(t.realized_pnl for t in all_trades), 2)
        total_unrealized = round(sum(t.unrealized_pnl for t in open_trades), 2)
        total_return_pct = round(((acc.equity - acc.initial_balance) / acc.initial_balance) * 100.0, 2)
        margin_level = round((acc.equity / acc.margin_used) * 100.0, 2) if acc.margin_used > 0 else 999.99

        return PaperPortfolioPerformance(
            initial_balance=acc.initial_balance,
            current_balance=acc.balance,
            current_equity=acc.equity,
            total_realized_pnl=total_realized,
            total_unrealized_pnl=total_unrealized,
            total_return_pct=total_return_pct,
            margin_used=acc.margin_used,
            free_margin=acc.free_margin,
            margin_level_pct=margin_level,
            total_trades=len(all_trades),
            open_trades=len(open_trades),
            closed_trades=total_closed,
            winning_trades=wins,
            losing_trades=losses,
            win_rate=win_rate,
            profit_factor=profit_factor,
            average_win=avg_win,
            average_loss=avg_loss,
        )
