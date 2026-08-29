"""Paper Trading Order Execution and Signal-to-Trade Converter."""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.logging import logger
from app.models.candle import Candle
from app.models.paper import VirtualAccount, PaperTrade
from app.models.signal import Signal
from app.schemas.paper_trading import AutoTradeSignalRequest, PaperOrderCreate
from app.schemas.signal import SignalDirection
from app.services.paper_trading.account_manager import VirtualAccountManager
from app.services.signals import RiskManager, SignalGenerator


class PaperOrderExecutor:
    """Handles order placement, execution simulation, and margin validation for paper trading."""

    def __init__(
        self,
        account_manager: Optional[VirtualAccountManager] = None,
        risk_manager: Optional[RiskManager] = None,
        signal_generator: Optional[SignalGenerator] = None,
    ):
        self.account_manager = account_manager or VirtualAccountManager()
        self.risk_manager = risk_manager or RiskManager()
        self.signal_generator = signal_generator or SignalGenerator()

    def get_latest_market_price(self, db: Session, symbol: str) -> float:
        """Fetch the most recent closing price for a symbol from database."""
        stmt = (
            select(Candle)
            .where(Candle.symbol == symbol)
            .order_by(desc(Candle.timestamp))
            .limit(1)
        )
        candle = db.scalars(stmt).first()
        if candle:
            return float(candle.close)
        # Default pricing fallback if no candles in DB
        return 1.1000 if "EUR" in symbol else 1.3000

    def execute_order(
        self,
        db: Session,
        order: PaperOrderCreate,
        current_market_price: Optional[float] = None,
    ) -> PaperTrade:
        """Execute a MARKET, LIMIT, or STOP paper order."""
        # 1. Resolve Virtual Account
        if order.account_id:
            account = db.get(VirtualAccount, order.account_id)
            if not account or not account.is_active:
                raise ValueError(f"Active Virtual Account #{order.account_id} not found.")
        else:
            account = self.account_manager.get_or_create_default_account(db)

        # 2. Resolve Market Price
        mkt_price = current_market_price or self.get_latest_market_price(db, order.symbol)
        pip_size = self.risk_manager.get_pip_size(order.symbol)
        order_type = order.order_type.upper().strip()

        # 3. Determine Entry Price
        if order_type == "MARKET":
            # Apply half spread (0.5 pip) and slippage (0.2 pip)
            half_spread = 0.5 * pip_size
            if order.direction == SignalDirection.BUY:
                exec_entry = round(mkt_price + half_spread, 5)
            else:
                exec_entry = round(mkt_price - half_spread, 5)
            target_entry = None
            status = "OPEN"
        elif order_type in ("LIMIT", "STOP"):
            if not order.target_entry_price:
                raise ValueError(f"target_entry_price is required for {order_type} orders.")
            exec_entry = order.target_entry_price
            target_entry = order.target_entry_price
            status = "PENDING"
        else:
            raise ValueError(f"Unsupported order_type '{order.order_type}'. Use MARKET, LIMIT, or STOP.")

        # 4. Resolve Stop Loss & Take Profits
        sl = order.stop_loss
        tp1 = order.take_profit_1
        tp2 = order.take_profit_2

        if not sl or not tp1:
            risk_res = self.risk_manager.calculate_trade_risk(
                symbol=order.symbol,
                direction=order.direction,
                entry_price=exec_entry,
                account_balance=account.balance,
                risk_percent=order.risk_percent or 0.5,
            )
            sl = sl or risk_res.stop_loss
            tp1 = tp1 or risk_res.take_profit_1
            tp2 = tp2 or risk_res.take_profit_2
            calculated_lots = risk_res.suggested_lot_size
        else:
            # Calculate lots from user SL
            risk_pips = abs(exec_entry - sl) / pip_size
            pip_val = self.risk_manager.get_pip_value_per_lot(order.symbol)
            risk_usd = account.balance * ((order.risk_percent or 0.5) / 100.0)
            calculated_lots = round(max(0.01, min(100.0, risk_usd / max(1e-6, risk_pips * pip_val))), 2)

        lots = round(order.position_size if order.position_size else calculated_lots, 2)
        lots = max(0.01, min(100.0, lots))

        # 5. Margin Validation
        req_margin = self.account_manager.calculate_required_margin(
            symbol=order.symbol,
            lots=lots,
            price=exec_entry,
            leverage=account.leverage,
        )

        if status == "OPEN" and req_margin > account.free_margin:
            raise ValueError(
                f"Insufficient Free Margin: Required ${req_margin:,.2f}, available Free Margin: ${account.free_margin:,.2f}."
            )

        margin_allocated = req_margin if status == "OPEN" else 0.0

        # 6. Save Paper Position to DB
        now = datetime.now(timezone.utc)
        paper_trade = PaperTrade(
            account_id=account.id,
            signal_id=order.signal_id,
            symbol=order.symbol,
            direction=order.direction.value,
            order_type=order_type,
            status=status,
            target_entry_price=target_entry,
            entry_price=exec_entry,
            current_price=mkt_price,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            initial_position_size=lots,
            remaining_position_size=lots,
            margin_used=margin_allocated,
            tp1_hit=False,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            pnl_pips=0.0,
            return_r=0.0,
            opened_at=now,
        )
        db.add(paper_trade)
        db.commit()
        db.refresh(paper_trade)

        # 7. Update Account Financials
        self.account_manager.recalculate_account_financials(db, account)

        logger.info(
            f"EXECUTED PAPER ORDER #{paper_trade.id}: [{paper_trade.order_type} {paper_trade.direction}] "
            f"{paper_trade.symbol} @ {paper_trade.entry_price:.5f} ({paper_trade.initial_position_size} Lots, Margin: ${paper_trade.margin_used:,.2f})"
        )
        return paper_trade

    def open_trade_from_signal(
        self,
        db: Session,
        request: AutoTradeSignalRequest,
    ) -> PaperTrade:
        """Convert a trading signal into an active virtual position."""
        target_signal: Optional[Signal] = None

        if request.signal_id:
            target_signal = db.get(Signal, request.signal_id)
            if not target_signal:
                raise ValueError(f"Signal #{request.signal_id} not found.")
        else:
            # Find latest actionable signal for symbol
            stmt = (
                select(Signal)
                .where(
                    Signal.symbol == request.symbol,
                    Signal.status == "ACTIVE",
                    Signal.direction.in_(["BUY", "SELL"]),
                )
                .order_by(desc(Signal.timestamp))
                .limit(1)
            )
            target_signal = db.scalars(stmt).first()

        if not target_signal:
            raise ValueError(f"No active qualifying trading signal found for {request.symbol}.")

        # 1. Idempotency Check: Return existing trade if already created for this signal
        if target_signal.id:
            existing_trade_stmt = select(PaperTrade).where(
                PaperTrade.signal_id == target_signal.id
            )
            if request.account_id:
                existing_trade_stmt = existing_trade_stmt.where(
                    PaperTrade.account_id == request.account_id
                )
            existing_trade = db.scalars(existing_trade_stmt).first()
            if existing_trade:
                logger.info(
                    f"Paper trade #{existing_trade.id} already exists for Signal #{target_signal.id}. "
                    f"Returning existing position idempotently."
                )
                return existing_trade

        order = PaperOrderCreate(
            account_id=request.account_id,
            symbol=target_signal.symbol,
            direction=SignalDirection(target_signal.direction),
            order_type="MARKET",
            risk_percent=request.risk_percent,
            stop_loss=target_signal.stop_loss,
            take_profit_1=target_signal.take_profit_1,
            take_profit_2=target_signal.take_profit_2,
            signal_id=target_signal.id,
        )

        return self.execute_order(db=db, order=order, current_market_price=target_signal.entry_price)
