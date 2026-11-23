"""Paper Position Management, SL/TP Auto-monitoring, and Price Synchronization."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.config import settings
from app.core.logging import logger
from app.models.candle import Candle
from app.models.paper import VirtualAccount, PaperTrade, AccountTransaction
from app.schemas.paper_trading import PositionSyncReport
from app.schemas.signal import SignalDirection
from app.services.paper_trading.account_manager import VirtualAccountManager
from app.services.paper_trading.broker_spec import get_broker_spec
from app.services.signals import RiskManager


class PaperPositionManager:
    """Manages active paper positions, partial exits, stop-loss trailing, and live price monitoring."""

    def __init__(
        self,
        account_manager: Optional[VirtualAccountManager] = None,
        risk_manager: Optional[RiskManager] = None,
    ):
        self.account_manager = account_manager or VirtualAccountManager()
        self.risk_manager = risk_manager or RiskManager()
        self.broker_spec = get_broker_spec(settings.BROKER_SPEC)

    def modify_position(
        self,
        db: Session,
        trade_id: int,
        stop_loss: Optional[float] = None,
        take_profit_1: Optional[float] = None,
        take_profit_2: Optional[float] = None,
    ) -> PaperTrade:
        """Modify SL and TP targets on an open or pending position."""
        trade = db.get(PaperTrade, trade_id)
        if not trade:
            raise ValueError(f"Paper trade #{trade_id} not found.")
        if trade.status == "CLOSED":
            raise ValueError(f"Cannot modify closed trade #{trade_id}.")

        if stop_loss is not None:
            trade.stop_loss = round(stop_loss, 5)
        if take_profit_1 is not None:
            trade.take_profit_1 = round(take_profit_1, 5)
        if take_profit_2 is not None:
            trade.take_profit_2 = round(take_profit_2, 5)

        db.commit()
        db.refresh(trade)
        logger.info(f"MODIFIED POSITION #{trade.id}: SL={trade.stop_loss}, TP1={trade.take_profit_1}, TP2={trade.take_profit_2}")
        return trade

    def close_position(
        self,
        db: Session,
        trade_id: int,
        current_price: Optional[float] = None,
        close_ratio: float = 1.0,
        exit_reason: str = "MANUAL",
    ) -> PaperTrade:
        """Close an open position fully or partially."""
        trade = db.get(PaperTrade, trade_id)
        if not trade:
            raise ValueError(f"Paper trade #{trade_id} not found.")
        if trade.status in ("CLOSED", "CANCELLED"):
            raise ValueError(f"Position #{trade_id} is already {trade.status}.")

        account = db.get(VirtualAccount, trade.account_id)
        if not account:
            raise ValueError(f"Virtual account #{trade.account_id} not found.")

        # Resolve exit price
        pip_size = self.risk_manager.get_pip_size(trade.symbol)
        pip_val = self.risk_manager.get_pip_value_per_lot(trade.symbol)
        if current_price is None:
            stmt = select(Candle).where(Candle.symbol == trade.symbol).order_by(desc(Candle.timestamp)).limit(1)
            c = db.scalars(stmt).first()
            current_price = float(c.close) if c else trade.entry_price

        # Calculate lots to close
        close_ratio = max(0.01, min(1.0, close_ratio))
        # Floor onto the broker volume grid; never create an invalid partial lot.
        close_lots = float(
            self.broker_spec.floor_lots(
                Decimal(str(trade.remaining_position_size * close_ratio))
            )
        )
        close_lots = max(
            float(self.broker_spec.min_lot),
            min(trade.remaining_position_size, close_lots),
        )
        new_rem_lots = round(trade.remaining_position_size - close_lots, 2)

        # Calculate realized PnL
        if trade.direction == SignalDirection.BUY.value:
            pips_gain = (current_price - trade.entry_price) / pip_size
        else:
            pips_gain = (trade.entry_price - current_price) / pip_size

        realized_leg_pnl = round(pips_gain * pip_val * close_lots, 2)
        trade.realized_pnl = round(trade.realized_pnl + realized_leg_pnl, 2)
        trade.remaining_position_size = new_rem_lots
        trade.current_price = current_price
        now = datetime.now(timezone.utc)

        # Update account balance and margin
        account.balance = round(account.balance + realized_leg_pnl, 2)

        if new_rem_lots <= 0.001:
            trade.status = "CLOSED"
            trade.exit_price = current_price
            trade.exit_reason = exit_reason
            trade.closed_at = now
            trade.margin_used = 0.0
            trade.unrealized_pnl = 0.0
            # Return R-multiple
            initial_risk_pips = abs(trade.entry_price - trade.stop_loss) / pip_size
            initial_risk_usd = max(1.0, initial_risk_pips * pip_val * trade.initial_position_size)
            trade.return_r = round(trade.realized_pnl / initial_risk_usd, 2)
        else:
            trade.status = "PARTIALLY_CLOSED"
            # Update margin used proportionally
            trade.margin_used = round(
                self.account_manager.calculate_required_margin(
                    symbol=trade.symbol,
                    lots=new_rem_lots,
                    price=current_price,
                    leverage=account.leverage,
                ),
                2,
            )

        # Record Account Transaction
        tx = AccountTransaction(
            account_id=account.id,
            trade_id=trade.id,
            transaction_type="TRADE_REALIZED_PNL",
            amount=realized_leg_pnl,
            balance_after=account.balance,
            description=f"Closed {close_lots} lots of {trade.symbol} ({exit_reason})",
        )
        db.add(tx)
        db.commit()

        # Recalculate account financials
        self.account_manager.recalculate_account_financials(db, account)
        logger.info(
            f"CLOSED POSITION #{trade.id}: Closed {close_lots} Lots of {trade.symbol} @ {current_price:.5f} "
            f"(Leg PnL: ${realized_leg_pnl:+,.2f}, Total Realized: ${trade.realized_pnl:+,.2f}, Reason: {exit_reason})"
        )
        return trade

    def cancel_pending_order(self, db: Session, trade_id: int) -> PaperTrade:
        """Cancel a pending LIMIT or STOP order."""
        trade = db.get(PaperTrade, trade_id)
        if not trade:
            raise ValueError(f"Paper trade #{trade_id} not found.")
        if trade.status != "PENDING":
            raise ValueError(f"Cannot cancel trade #{trade_id} with status '{trade.status}'.")

        trade.status = "CANCELLED"
        trade.exit_reason = "CANCELLED"
        trade.closed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(trade)
        logger.info(f"CANCELLED PENDING ORDER #{trade.id} ({trade.symbol})")
        return trade

    def sync_market_prices(
        self,
        db: Session,
        symbol_prices: Optional[Dict[str, float]] = None,
    ) -> PositionSyncReport:
        """Synchronize open and pending positions against latest market prices."""
        now = datetime.now(timezone.utc)
        events: List[str] = []
        updated_count = 0
        tp1_count = 0
        tp2_count = 0
        sl_count = 0
        limit_filled_count = 0

        # Query all active or pending paper trades
        trades = list(
            db.scalars(
                select(PaperTrade).where(
                    PaperTrade.status.in_(["PENDING", "OPEN", "PARTIALLY_CLOSED"])
                )
            ).all()
        )

        if not trades:
            account = self.account_manager.get_or_create_default_account(db)
            return PositionSyncReport(
                timestamp=now,
                updated_positions_count=0,
                tp1_triggered_count=0,
                tp2_triggered_count=0,
                sl_triggered_count=0,
                limit_orders_filled_count=0,
                account_equity=account.equity,
                account_balance=account.balance,
                unrealized_pnl=0.0,
                events=["No active or pending positions to synchronize."],
            )

        # Cache symbol prices
        prices: Dict[str, float] = symbol_prices.copy() if symbol_prices else {}
        for t in trades:
            if t.symbol not in prices:
                stmt = select(Candle).where(Candle.symbol == t.symbol).order_by(desc(Candle.timestamp)).limit(1)
                c = db.scalars(stmt).first()
                if c:
                    prices[t.symbol] = float(c.close)
                else:
                    prices[t.symbol] = t.current_price

        # Process each trade
        for t in trades:
            price = prices.get(t.symbol, t.current_price)
            pip_size = self.risk_manager.get_pip_size(t.symbol)
            pip_val = self.risk_manager.get_pip_value_per_lot(t.symbol)
            account = db.get(VirtualAccount, t.account_id)

            # -------------------------------------------------------------
            # Case 1: PENDING Order Trigger Check
            # -------------------------------------------------------------
            if t.status == "PENDING":
                is_filled = False
                if t.order_type == "LIMIT":
                    if t.direction == SignalDirection.BUY.value and price <= t.target_entry_price:
                        is_filled = True
                    elif t.direction == SignalDirection.SELL.value and price >= t.target_entry_price:
                        is_filled = True
                elif t.order_type == "STOP":
                    if t.direction == SignalDirection.BUY.value and price >= t.target_entry_price:
                        is_filled = True
                    elif t.direction == SignalDirection.SELL.value and price <= t.target_entry_price:
                        is_filled = True

                if is_filled:
                    t.status = "OPEN"
                    t.entry_price = t.target_entry_price
                    t.current_price = price
                    req_margin = self.account_manager.calculate_required_margin(
                        symbol=t.symbol,
                        lots=t.remaining_position_size,
                        price=t.entry_price,
                        leverage=account.leverage if account else 100,
                    )
                    t.margin_used = req_margin
                    limit_filled_count += 1
                    events.append(f"Filled Pending {t.order_type} #{t.id} on {t.symbol} @ {t.entry_price:.5f}")
                continue

            # -------------------------------------------------------------
            # Case 2: Active OPEN / PARTIALLY_CLOSED Position Evaluation
            # -------------------------------------------------------------
            t.current_price = price
            updated_count += 1

            if t.direction == SignalDirection.BUY.value:
                pips_gain = (price - t.entry_price) / pip_size
                t.pnl_pips = round(pips_gain, 1)
                t.unrealized_pnl = round(pips_gain * pip_val * t.remaining_position_size, 2)

                # 1. Stop Loss Check
                if price <= t.stop_loss:
                    exit_reason = "BREAK_EVEN" if t.tp1_hit else "SL_HIT"
                    self.close_position(db, t.id, current_price=t.stop_loss, close_ratio=1.0, exit_reason=exit_reason)
                    sl_count += 1
                    events.append(f"Position #{t.id} ({t.symbol}) hit {exit_reason} @ {t.stop_loss:.5f}")
                    continue

                # 2. Take Profit 2 Check
                elif t.take_profit_2 and price >= t.take_profit_2:
                    self.close_position(db, t.id, current_price=t.take_profit_2, close_ratio=1.0, exit_reason="TP2_HIT")
                    tp2_count += 1
                    events.append(f"Position #{t.id} ({t.symbol}) hit TP2 @ {t.take_profit_2:.5f}")
                    continue

                # 3a. TP2 absent -> documented fallback: full exit at TP1.
                #     Keeps positions with only one target managed; no invalid partial lots.
                elif t.take_profit_1 and not t.take_profit_2 and price >= t.take_profit_1:
                    self.close_position(db, t.id, current_price=t.take_profit_1, close_ratio=1.0, exit_reason="TP1_FULL_EXIT")
                    tp1_count += 1
                    events.append(f"Position #{t.id} ({t.symbol}) hit TP1 (no TP2 set): full exit.")

                # 3b. Take Profit 1 Check (Partial close 50% + Move SL to BE)
                elif (
                    settings.PARTIAL_CLOSE_AT_TP1
                    and t.remaining_position_size > float(self.broker_spec.min_lot) + 1e-9
                    and price >= t.take_profit_1
                    and not t.tp1_hit
                ):
                    self.close_position(db, t.id, current_price=t.take_profit_1, close_ratio=0.5, exit_reason="TP1_HIT")
                    t.tp1_hit = True
                    # Auto move SL to entry price
                    t.stop_loss = t.entry_price
                    db.commit()
                    tp1_count += 1
                    events.append(f"Position #{t.id} ({t.symbol}) reached TP1: Closed 50% & moved SL to Break-Even.")

            else:  # SELL Position
                pips_gain = (t.entry_price - price) / pip_size
                t.pnl_pips = round(pips_gain, 1)
                t.unrealized_pnl = round(pips_gain * pip_val * t.remaining_position_size, 2)

                # 1. Stop Loss Check
                if price >= t.stop_loss:
                    exit_reason = "BREAK_EVEN" if t.tp1_hit else "SL_HIT"
                    self.close_position(db, t.id, current_price=t.stop_loss, close_ratio=1.0, exit_reason=exit_reason)
                    sl_count += 1
                    events.append(f"Position #{t.id} ({t.symbol}) hit {exit_reason} @ {t.stop_loss:.5f}")
                    continue

                # 2. Take Profit 2 Check
                elif t.take_profit_2 and price <= t.take_profit_2:
                    self.close_position(db, t.id, current_price=t.take_profit_2, close_ratio=1.0, exit_reason="TP2_HIT")
                    tp2_count += 1
                    events.append(f"Position #{t.id} ({t.symbol}) hit TP2 @ {t.take_profit_2:.5f}")
                    continue

                # 3a. TP2 absent -> documented fallback: full exit at TP1.
                elif t.take_profit_1 and not t.take_profit_2 and price <= t.take_profit_1:
                    self.close_position(db, t.id, current_price=t.take_profit_1, close_ratio=1.0, exit_reason="TP1_FULL_EXIT")
                    tp1_count += 1
                    events.append(f"Position #{t.id} ({t.symbol}) hit TP1 (no TP2 set): full exit.")

                # 3b. Take Profit 1 Check
                elif (
                    settings.PARTIAL_CLOSE_AT_TP1
                    and t.remaining_position_size > float(self.broker_spec.min_lot) + 1e-9
                    and price <= t.take_profit_1
                    and not t.tp1_hit
                ):
                    self.close_position(db, t.id, current_price=t.take_profit_1, close_ratio=0.5, exit_reason="TP1_HIT")
                    t.tp1_hit = True
                    t.stop_loss = t.entry_price
                    db.commit()
                    tp1_count += 1
                    events.append(f"Position #{t.id} ({t.symbol}) reached TP1: Closed 50% & moved SL to Break-Even.")

        db.commit()

        # Update and return account state
        account = self.account_manager.get_or_create_default_account(db)
        self.account_manager.recalculate_account_financials(db, account)

        open_active = list(
            db.scalars(
                select(PaperTrade).where(
                    PaperTrade.account_id == account.id,
                    PaperTrade.status.in_(["OPEN", "PARTIALLY_CLOSED"]),
                )
            ).all()
        )
        total_unrealized = sum(t.unrealized_pnl for t in open_active)

        return PositionSyncReport(
            timestamp=now,
            updated_positions_count=updated_count,
            tp1_triggered_count=tp1_count,
            tp2_triggered_count=tp2_count,
            sl_triggered_count=sl_count,
            limit_orders_filled_count=limit_filled_count,
            account_equity=account.equity,
            account_balance=account.balance,
            unrealized_pnl=round(total_unrealized, 2),
            events=events if events else ["All active positions synchronized with latest market prices."],
        )
