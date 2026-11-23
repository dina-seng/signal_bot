"""Paper Trading Order Execution and Signal-to-Trade Converter."""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.config import settings
from app.core.logging import logger
from app.models.candle import Candle
from app.models.paper import VirtualAccount, PaperTrade
from app.models.signal import Signal
from app.schemas.paper_trading import AutoTradeSignalRequest, PaperOrderCreate
from app.schemas.signal import SignalDirection
from app.services.paper_trading.account_manager import VirtualAccountManager
from app.services.paper_trading.broker_spec import BrokerSpec, get_broker_spec
from app.services.signals import RiskManager, SignalGenerator


# ---------------------------------------------------------------------------
# Timeframe → bar duration map for staleness validation
# ---------------------------------------------------------------------------
_TIMEFRAME_MINUTES: dict[str, float] = {
    "1m":  1.0,
    "3m":  3.0,
    "5m":  5.0,
    "15m": 15.0,
    "30m": 30.0,
    "1h":  60.0,
    "4h":  240.0,
    "1d":  1440.0,
}

# Upper lot bound; the minimum and step come from the selected BrokerSpec.
MAX_LOT_SIZE: float = 100.0


class InsufficientRiskBudgetError(ValueError):
    """Raised when the configured risk budget cannot fund even the minimum lot.

    Carries the affordability numbers so the Telegram rejection card can tell the
    operator exactly which lever (balance or risk %) would make the setup tradable.
    Subclasses ValueError so existing caller-level error handling keeps working.
    """

    def __init__(
        self,
        raw_lots: Decimal,
        min_lots: Decimal,
        *,
        contract_size: Optional[Decimal] = None,
        stop_points: Optional[float] = None,
        stop_pips: Optional[float] = None,
        budget: Optional[float] = None,
        per_point_risk: Optional[float] = None,
        risk_percent: Optional[float] = None,
        balance: Optional[float] = None,
    ) -> None:
        self.raw_lots = raw_lots
        self.min_lots = min_lots
        self.stop_points = stop_points
        self.stop_pips = stop_pips
        self.budget = budget
        self.per_point_risk = per_point_risk
        self.risk_percent = risk_percent
        self.balance = balance
        self.max_affordable_points = (
            budget / per_point_risk
            if budget is not None and per_point_risk and per_point_risk > 0
            else None
        )
        self.required_balance = (
            stop_points * per_point_risk / (risk_percent / 100.0)
            if stop_points is not None and per_point_risk and risk_percent and risk_percent > 0
            else None
        )
        # What the minimum lot would actually cost at this stop distance.
        self.min_lot_risk_usd = (
            float(min_lots * contract_size * Decimal(str(stop_points)))
            if contract_size is not None and stop_points is not None
            else None
        )
        self.min_lot_risk_pct = (
            self.min_lot_risk_usd / balance * 100.0
            if self.min_lot_risk_usd is not None and balance
            else None
        )

        hints: Dict[str, str] = {
            "lots": f"required {raw_lots:.6f} vs min {min_lots:.2f}"
        }
        if stop_points is not None:
            hints["stop"] = (
                f"{stop_points:.2f} points / {stop_pips:.1f} pips"
                if stop_pips is not None
                else f"{stop_points:.2f} points"
            )
        if self.max_affordable_points is not None:
            hints["max_stop"] = f"{self.max_affordable_points:.2f} points"
        if self.required_balance is not None:
            hints["required_balance"] = f"${self.required_balance:,.2f}"
        if self.min_lot_risk_usd is not None:
            pct = f" ({self.min_lot_risk_pct:.2f}%)" if self.min_lot_risk_pct is not None else ""
            hints["min_lot_risk"] = f"${self.min_lot_risk_usd:,.2f}{pct}"
        if balance is not None and risk_percent is not None:
            hints["budget_context"] = f"balance ${balance:,.2f} @ {risk_percent:.1f}%"
        self.hints = hints

        labels = {
            "stop": "Stop",
            "max_stop": "Max affordable stop",
            "required_balance": "Balance needed for this stop",
            "min_lot_risk": "Min lot would risk",
        }
        detail = " | ".join(
            f"{labels.get(k, k)}: {v}"
            for k, v in hints.items()
            if k not in ("budget_context", "lots")
        )
        message = (
            f"Trade rejected: Risk budget insufficient for minimum lot size. "
            f"Required lots: {raw_lots:.6f}, Min lots: {min_lots:.2f} | {detail}"
        )
        super().__init__(message)


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
        self.broker_spec: BrokerSpec = get_broker_spec(settings.BROKER_SPEC)

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

    def validate_signal_before_execution(
        self,
        db: Session,
        signal: Signal,
        current_price: float,
    ) -> None:
        """Run pre-execution staleness and live-price invalidation gates.

        Raises ValueError with a descriptive message if the signal is stale or
        if the live market price has already moved past the signal's SL/TP,
        preventing a guaranteed-loss order from being placed.

        Args:
            db: Active SQLAlchemy session (unused but kept for future real-time
                provider injection without breaking the method signature).
            signal: The DB Signal record to be executed.
            current_price: Live market price fetched immediately before this call.

        Raises:
            ValueError: If the signal is too old or price has invalidated the setup.
        """
        now_utc = datetime.now(timezone.utc)

        # ------------------------------------------------------------------
        # Gate 1 — Staleness Check
        # ------------------------------------------------------------------
        # Anchor age to `created_at` (wall-clock time the signal was evaluated
        # and persisted), NOT `timestamp` (candle open time of the last closed
        # bar, already up to a full bar old at persist time). Measuring from the
        # candle timestamp rejects every fresh signal once the next scanner
        # cycle runs ("candle timestamp drift" — same rationale scanner.py uses
        # created_at for the signal cooldown window).
        signal_ts = signal.created_at or signal.timestamp
        if signal_ts is not None:
            # Normalise to UTC regardless of whether tzinfo is attached
            if signal_ts.tzinfo is None:
                signal_ts = signal_ts.replace(tzinfo=timezone.utc)
            else:
                signal_ts = signal_ts.astimezone(timezone.utc)

            signal_age_minutes = (now_utc - signal_ts).total_seconds() / 60.0
            timeframe_minutes = _TIMEFRAME_MINUTES.get(
                (signal.timeframe or "").lower(), 60.0
            )

            # Clock-skew protection: reject signals timestamped more than 1 minute
            # in the future (indicates a misconfigured clock or corrupted record).
            if signal_age_minutes < -1.0:
                msg = (
                    f"STALE SIGNAL REJECTED (clock skew): Signal #{signal.id} for "
                    f"{signal.symbol} [{signal.timeframe}] is timestamped "
                    f"{abs(signal_age_minutes):.1f} minutes IN THE FUTURE "
                    f"(signal_ts={signal_ts.isoformat()}, now={now_utc.isoformat()}). "
                    "Order aborted to prevent corrupted execution."
                )
                logger.warning(msg)
                raise ValueError(msg)

            # Bar-age staleness: signal is older than one full bar of its timeframe.
            if signal_age_minutes > timeframe_minutes:
                msg = (
                    f"STALE SIGNAL REJECTED: Signal #{signal.id} for "
                    f"{signal.symbol} [{signal.timeframe}] is "
                    f"{signal_age_minutes:.1f} minutes old "
                    f"(max allowed: {timeframe_minutes:.0f} minutes for a {signal.timeframe} bar). "
                    "The market has moved since signal generation; order aborted to prevent "
                    "instant Stop Loss stop-out."
                )
                logger.warning(msg)
                raise ValueError(msg)

        # ------------------------------------------------------------------
        # Gate 2 — Live Market Price Invalidation
        # ------------------------------------------------------------------
        direction = (signal.direction or "").upper()
        sl = signal.stop_loss
        tp = signal.take_profit_1

        if sl is None or tp is None:
            # Cannot validate without risk levels; skip gate (risk manager will
            # calculate them during execution — at least staleness was checked).
            return

        # ------------------------------------------------------------------
        # Gate 3 — Minimum SL Distance Guard
        #
        # If the live market price has drifted to within 1 pip of the signal's
        # Stop Loss, the position sizing formula (Risk / SL_distance) will
        # produce an astronomically large unit count, blowing the margin.  This
        # catches the case where staleness has closed the price-to-SL gap to
        # near-zero without fully crossing the SL level.
        # ------------------------------------------------------------------
        MIN_SL_DISTANCE_PIPS = 0.0001  # 1 pip minimum clearance
        sl_distance = abs(current_price - sl)
        if sl_distance < MIN_SL_DISTANCE_PIPS:
            msg = (
                f"DEGENERATE SETUP REJECTED: Signal #{signal.id} for "
                f"{signal.symbol} [{signal.timeframe}] — live price "
                f"{current_price:.5f} is within {sl_distance:.5f} of Stop Loss "
                f"{sl:.5f} (minimum clearance: {MIN_SL_DISTANCE_PIPS} pips). "
                "Position sizing would produce infinite units; execution aborted."
            )
            logger.warning(msg)
            raise ValueError(msg)

        if direction == "SELL":
            # For a SELL setup the SL is above entry and TP is below entry.
            # Reject if price has already traded THROUGH the SL (strictly above),
            # meaning any fill will immediately be stopped out.
            # Reject if price has already traded THROUGH the TP (strictly below),
            # meaning the entry opportunity has closed.
            if current_price > sl:
                msg = (
                    f"LIVE PRICE INVALIDATION (SELL): Signal #{signal.id} for "
                    f"{signal.symbol} [{signal.timeframe}] — current price "
                    f"{current_price:.5f} is above Stop Loss {sl:.5f}. "
                    "Order would trigger an instant SL_HIT; execution aborted."
                )
                logger.warning(msg)
                raise ValueError(msg)
            if current_price < tp:
                msg = (
                    f"LIVE PRICE INVALIDATION (SELL): Signal #{signal.id} for "
                    f"{signal.symbol} [{signal.timeframe}] — current price "
                    f"{current_price:.5f} is below Take Profit {tp:.5f}. "
                    "The TP has already been reached; entry opportunity has passed."
                )
                logger.warning(msg)
                raise ValueError(msg)

        elif direction == "BUY":
            # For a BUY setup the SL is below entry and TP is above entry.
            # Reject if price has already traded THROUGH the SL (strictly below)
            # or THROUGH the TP (strictly above).
            if current_price < sl:
                msg = (
                    f"LIVE PRICE INVALIDATION (BUY): Signal #{signal.id} for "
                    f"{signal.symbol} [{signal.timeframe}] — current price "
                    f"{current_price:.5f} is below Stop Loss {sl:.5f}. "
                    "Order would trigger an instant SL_HIT; execution aborted."
                )
                logger.warning(msg)
                raise ValueError(msg)
            if current_price > tp:
                msg = (
                    f"LIVE PRICE INVALIDATION (BUY): Signal #{signal.id} for "
                    f"{signal.symbol} [{signal.timeframe}] — current price "
                    f"{current_price:.5f} is above Take Profit {tp:.5f}. "
                    "The TP has already been reached; entry opportunity has passed."
                )
                logger.warning(msg)
                raise ValueError(msg)

    def _lots_for_risk_budget(
        self,
        raw_lots: Decimal,
        symbol: str,
        *,
        stop_points: Optional[float] = None,
        pip_size: Optional[float] = None,
        budget: Optional[float] = None,
        risk_percent: Optional[float] = None,
        balance: Optional[float] = None,
        contract_size: Optional[Decimal] = None,
    ) -> float:
        """Floor raw lots onto the broker grid; reject if below the broker min lot.

        Uses Decimal throughout — no float floor — so the invariant
        lots * contract_size * distance <= risk_usd always holds.
        """
        spec = self.broker_spec
        lots = spec.floor_lots(min(raw_lots, Decimal(str(MAX_LOT_SIZE))))
        if lots < spec.min_lot:
            stop_pips = (
                stop_points / pip_size
                if stop_points is not None and pip_size and pip_size > 0
                else None
            )
            error = InsufficientRiskBudgetError(
                raw_lots,
                spec.min_lot,
                contract_size=contract_size or spec.contract_size,
                stop_points=stop_points,
                stop_pips=stop_pips,
                budget=budget,
                per_point_risk=float(spec.min_lot * (contract_size or spec.contract_size)),
                risk_percent=risk_percent,
                balance=balance,
            )
            logger.warning(f"{error} (symbol={symbol})")
            raise error
        return float(lots)

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
        # BrokerSpec profiles are XAU/USD profiles. For any legacy non-XAU
        # instrument, retain the instrument-derived contract (pip value / pip size)
        # so existing behaviour is unchanged.
        if order.symbol == "XAU/USD":
            contract_size = self.broker_spec.contract_size
        else:
            contract_size = Decimal(
                str(self.risk_manager.get_pip_value_per_lot(order.symbol) / pip_size)
            )
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

        # Broker-spec sizing from the resolved price distance (Decimal, no float floor).
        risk_pct = order.risk_percent or 0.5
        distance = abs(exec_entry - sl)
        if distance <= 0:
            raise ValueError("Invalid stop distance: entry and stop loss are equal.")
        risk_usd = account.balance * (risk_pct / 100.0)
        raw_lots = (
            Decimal(str(account.balance))
            * (Decimal(str(risk_pct)) / Decimal("100"))
            / (Decimal(str(distance)) * contract_size)
        )

        if order.position_size is not None:
            # Explicit operator override (manual order) — honour it, floored to grid.
            lots = float(self.broker_spec.floor_lots(Decimal(str(order.position_size))))
        else:
            # Auto-sizing from the signal: reject rather than force the min lot.
            lots = self._lots_for_risk_budget(
                raw_lots,
                order.symbol,
                stop_points=distance,
                pip_size=pip_size,
                budget=risk_usd,
                risk_percent=risk_pct,
                balance=account.balance,
                contract_size=contract_size,
            )
        lots = max(float(self.broker_spec.min_lot), min(MAX_LOT_SIZE, lots))

        actual_risk_usd = float(
            Decimal(str(lots)) * contract_size * Decimal(str(distance))
        )
        actual_risk_pct = (actual_risk_usd / account.balance * 100.0) if account.balance else 0.0
        logger.info(
            f"PAPER SIZING [{self.broker_spec.name}] {order.symbol}: "
            f"distance={distance:.5f} lots={lots:.4f} "
            f"risk=${actual_risk_usd:.2f} ({actual_risk_pct:.2f}%) budget=${risk_usd:.2f}"
        )

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
            broker_profile=self.broker_spec.name,
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
        """Convert a trading signal into an active virtual position.

        Executes two pre-flight validation gates before placing any order:
          1. Timestamp Staleness Gate — signal must be younger than one full bar
             of its timeframe (e.g. < 15 min old for a 15m signal).
          2. Live Price Invalidation Gate — the current market price must still
             be within the signal's SL/TP corridor. If price has already moved
             past the SL or reached the TP, the order is aborted.

        These gates prevent the class of 0-second SL_HIT losses caused by
        executing stale scanner outputs against a market that has already moved.
        """
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

        # 2. Resolve live market price NOW (before validation and order placement).
        #    Do NOT reuse target_signal.entry_price — that price was captured at
        #    signal-generation time and may be 15–60 minutes stale.
        live_price = self.get_latest_market_price(db, target_signal.symbol)

        # 3. Pre-Execution Validation Gates (staleness + live price invalidation).
        #    Raises ValueError with a descriptive message if the signal is invalid;
        #    the caller (scanner) should catch and log, but NOT place the order.
        self.validate_signal_before_execution(
            db=db,
            signal=target_signal,
            current_price=live_price,
        )

        # Log advisory warning if present on the signal without raising an exception
        reasons_list = target_signal.reasons if isinstance(target_signal.reasons, list) else []
        for r in reasons_list:
            if "Path Advisory" in str(r):
                logger.info(
                    f"Paper trade proceeding under Path Advisory on {target_signal.symbol} "
                    f"(Signal #{target_signal.id}):\n{r}"
                )
                break

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

        # 4. Execute at live market price (NOT the stale signal entry price).
        return self.execute_order(db=db, order=order, current_market_price=live_price)
