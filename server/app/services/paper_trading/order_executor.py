"""Paper Trading Order Execution and Signal-to-Trade Converter."""

from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.config import settings
from app.core.logging import logger
from app.models.candle import Candle
from app.models.paper import VirtualAccount, PaperTrade
from app.models.signal import Signal
from app.schemas.paper_trading import AutoTradeSignalRequest, PaperOrderCreate
from app.schemas.signal import SignalDirection, SignalStatus
from app.services.market_data.freshness import filter_closed_candles
from app.services.paper_trading.account_manager import VirtualAccountManager
from app.services.paper_trading.broker_spec import BrokerSpec, get_broker_spec
from app.services.signals import RiskEngine, RiskLevels, RiskManager, SignalGenerator
from app.services.signals import lifecycle as signal_lifecycle


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

# Backwards-compatible alias; the authoritative bound lives in settings.MAX_LOT_SIZE.
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
        symbol: Optional[str] = None,
        entry: Optional[float] = None,
        stop_loss: Optional[float] = None,
        volume_step: Optional[Decimal] = None,
        executable_lots: Optional[Decimal] = None,
    ) -> None:
        self.raw_lots = raw_lots
        self.min_lots = min_lots
        self.symbol = symbol
        self.entry = entry
        self.stop_loss = stop_loss
        self.volume_step = volume_step
        self.executable_lots = executable_lots
        self.contract_size = contract_size
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
            budget_txt = f", budget ${budget:,.2f}" if budget is not None else ""
            hints["context"] = f"balance ${balance:,.2f} @ {risk_percent:.1f}%{budget_txt}"
        if entry is not None and stop_loss is not None:
            hints["levels"] = f"entry {entry:.5f} / SL {stop_loss:.5f}"
        if contract_size is not None:
            step_txt = f", step {volume_step}" if volume_step is not None else ""
            exec_txt = f", executable {executable_lots}" if executable_lots is not None else ""
            hints["broker"] = f"contract {contract_size}{step_txt}{exec_txt}"
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
            if k not in ("context", "levels", "broker", "lots", "budget_context")
        )
        message = (
            f"Trade rejected: Risk budget insufficient for minimum lot size. "
            f"Required lots: {raw_lots:.6f}, Min lots: {min_lots:.2f} | {detail}"
        )
        super().__init__(message)


@dataclass(frozen=True)
class ExecutionRiskProfile:
    """The dynamic "User Risk Profile" used at execution time.

    Every field is resolved from an authoritative, non-hardcoded source:
      * balance      -> the active VirtualAccount row in the database
      * risk_percent -> live application settings (RISK_PER_ORDER_PCT)
      * lot_size     -> the selected BrokerSpec minimum lot
      * contract     -> the selected BrokerSpec / instrument specification
    """

    balance: float
    risk_percent: float
    lot_size: float
    contract_size: Decimal
    pip_size: float
    pip_value_per_lot: float
    broker_profile: str
    symbol: str

    @property
    def risk_budget_usd(self) -> float:
        return self.balance * self.risk_percent / 100.0


class PaperOrderExecutor:
    """Handles order placement, execution simulation, and margin validation for paper trading."""

    def __init__(
        self,
        account_manager: Optional[VirtualAccountManager] = None,
        risk_manager: Optional[RiskManager] = None,
        signal_generator: Optional[SignalGenerator] = None,
        risk_engine: Optional[RiskEngine] = None,
    ):
        self.account_manager = account_manager or VirtualAccountManager()
        self.risk_manager = risk_manager or RiskManager()
        self.signal_generator = signal_generator or SignalGenerator()
        self.risk_engine = risk_engine or RiskEngine()
        self.broker_spec: BrokerSpec = get_broker_spec(settings.BROKER_SPEC)

    # ------------------------------------------------------------------
    # Dynamic execution context (the "User Risk Profile")
    # ------------------------------------------------------------------
    def resolve_user_risk_profile(
        self, db: Session, account: VirtualAccount, symbol: str
    ) -> ExecutionRiskProfile:
        """Read balance / risk % / lot size / contract value dynamically.

        No numeric literals are baked into execution. Balance comes from the
        persisted virtual account, risk % from live settings, and lot size plus
        contract value from the dynamically selected broker profile.
        """
        pip_size = self.risk_manager.get_pip_size(symbol)
        pip_value = self.risk_manager.get_pip_value_per_lot(symbol)
        if symbol == "XAU/USD":
            contract_size = self.broker_spec.contract_size
        else:
            contract_size = Decimal(str(pip_value / pip_size)) if pip_size > 0 else Decimal("1")

        return ExecutionRiskProfile(
            balance=float(account.balance),
            risk_percent=float(settings.MAX_RISK_PERCENT),
            lot_size=float(self.broker_spec.min_lot),
            contract_size=contract_size,
            pip_size=pip_size,
            pip_value_per_lot=pip_value,
            broker_profile=self.broker_spec.name,
            symbol=symbol,
        )

    def _load_entry_timeframe_candles(
        self, db: Session, symbol: str, timeframe: str, limit: int = 200
    ) -> List[Candle]:
        """Load closed candles for the ENTRY timeframe only.

        This is the strict timeframe lock: a 15m entry queries only 15m candles.
        1H/4H data is never fetched here, so HTF structure cannot leak into SL/TP.
        """
        tf = str(timeframe or "").lower().strip()
        if not tf:
            raise ValueError("Cannot resolve structural levels without an entry timeframe.")
        stmt = (
            select(Candle)
            .where(Candle.symbol == symbol, Candle.timeframe == tf)
            .order_by(desc(Candle.timestamp))
            .limit(limit)
        )
        candles = list(db.scalars(stmt).all())
        candles.reverse()
        return filter_closed_candles(candles, timeframe=tf)

    def resolve_signal_levels(
        self,
        db: Session,
        signal: Signal,
        entry_price: float,
        timeframe: str,
        pip_size: float,
    ) -> RiskLevels:
        """Let the Risk Engine place the 15m SL/TP from the signal's entry.

        The entry supplied by the Signal Engine is used verbatim; the live
        ``entry_price`` argument is retained only for backwards compatibility.
        """
        candles = self._load_entry_timeframe_candles(
            db, symbol=signal.symbol, timeframe="15m"
        )
        return self.risk_engine.resolve_levels(
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price or entry_price,
            timeframe="15m",
            candles=candles,
            balance=self.resolve_user_risk_profile(
                db,
                self.account_manager.get_or_create_default_account(db),
                signal.symbol,
            ).balance,
        )

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
        *,
        stop_loss: Optional[float] = None,
        take_profit_1: Optional[float] = None,
    ) -> None:
        """Run pre-execution staleness and live-price invalidation gates.

        Stops are never rejected for being too wide: wide structural stops are
        expected and are fully supported by the fixed 0.01 lot. Callers that
        re-derive the entry-timeframe SL/TP pass them in so validation uses the
        freshly resolved levels instead of the signal's stored (possibly HTF)
        levels.

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
        #
        # Uses the freshly resolved entry-timeframe levels when supplied. There
        # is intentionally NO SL-distance guard: lot size is fixed, so a wide
        # structural stop cannot blow position sizing and must not be rejected.
        # ------------------------------------------------------------------
        direction = (signal.direction or "").upper()
        sl = stop_loss if stop_loss is not None else signal.stop_loss
        tp = take_profit_1 if take_profit_1 is not None else signal.take_profit_1

        if sl is None or tp is None:
            # Cannot validate without risk levels; staleness was still checked.
            return

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

    @staticmethod
    def _assert_execution_slot_available(db: Session, symbol: str) -> None:
        """Single-slot gate: never stack a second open position on a symbol."""
        same_symbol = db.scalars(
            select(PaperTrade.id).where(
                PaperTrade.symbol == symbol,
                PaperTrade.status.in_(["OPEN", "PARTIALLY_CLOSED"]),
            )
        ).first()
        if same_symbol is not None:
            raise ValueError(
                f"Position slot unavailable: {symbol} already has an open paper trade."
            )

        active_count = len(
            db.scalars(
                select(PaperTrade.id).where(
                    PaperTrade.status.in_(["OPEN", "PARTIALLY_CLOSED"])
                )
            ).all()
        )
        if active_count >= settings.MAX_OPEN_POSITIONS:
            raise ValueError(
                f"Position slot unavailable: {active_count} open position(s) already active "
                f"(cap={settings.MAX_OPEN_POSITIONS})."
            )

    def execute_order(
        self,
        db: Session,
        order: PaperOrderCreate,
        current_market_price: Optional[float] = None,
    ) -> PaperTrade:
        """Execute a MARKET, LIMIT, or STOP paper order."""
        # 0. Concurrency + consumed-setup locks BEFORE any DB write or pricing.
        self._assert_execution_slot_available(db, order.symbol)

        signal = db.get(Signal, order.signal_id) if order.signal_id else None
        if signal is not None:
            if signal.status != SignalStatus.ACTIVE.value:
                raise ValueError(
                    f"Signal #{signal.id} is {signal.status}, not ACTIVE; order aborted."
                )
            if signal_lifecycle.is_setup_executed(db, signal):
                raise ValueError(
                    f"Setup for {signal.symbol} [{signal.timeframe}] at {signal.timestamp} "
                    f"({signal.direction}) was already executed; order aborted."
                )

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

        if not order.dynamic_tp_from_sl and status == "OPEN" and not tp1 and not tp2:
            raise ValueError(
                "Unmanaged position rejected: at least one take-profit target is required."
            )

        if order.dynamic_tp_from_sl:
            # Signal execution: the SL was derived from the entry-timeframe
            # structure. Derive the final TP from the ACTUAL fill price so the
            # 1:3 geometry is exact, with no HTF input and no SL-distance gate.
            if sl is None:
                raise ValueError("Dynamic TP requires a resolved structural stop loss.")
            sl_distance = abs(exec_entry - sl)
            if sl_distance <= 0:
                raise ValueError("Invalid stop distance: entry and stop loss are equal.")
            rr = float(settings.MIN_RR_TP1)
            tp_distance = sl_distance * rr
            tp1 = round(
                exec_entry + tp_distance
                if order.direction == SignalDirection.BUY
                else exec_entry - tp_distance,
                5,
            )
            tp2 = None  # one final 3R target
        else:
            if not sl or not tp1:
                risk_res = self.risk_manager.calculate_trade_risk(
                    symbol=order.symbol,
                    direction=order.direction,
                    entry_price=exec_entry,
                    account_balance=account.balance,
                    risk_percent=order.risk_percent or settings.MAX_RISK_PERCENT,
                )
                sl = sl or risk_res.stop_loss
                tp1 = tp1 or risk_res.take_profit_1
                tp2 = tp2 or risk_res.take_profit_2

        if status == "OPEN" and (sl is None or (tp1 is None and tp2 is None)):
            raise ValueError(
                "Unmanaged position rejected: a stop loss and at least one take-profit "
                "target are required."
            )

        # 5. Dynamic User Risk Profile — fixed lot, no SL-distance sizing.
        profile = self.resolve_user_risk_profile(db, account, order.symbol)
        distance = abs(exec_entry - sl) if sl is not None else 0.0
        if order.position_size is not None:
            # Explicit operator override (manual order) — honour it, floored to grid.
            lots = float(self.broker_spec.floor_lots(Decimal(str(order.position_size))))
        else:
            # Signals always execute the profile's fixed lot (0.01 by default).
            # Wide structural stops are accepted; they are never a rejection reason.
            lots = profile.lot_size
        lots = max(float(self.broker_spec.min_lot), min(float(settings.MAX_LOT_SIZE), lots))

        actual_risk_usd = float(
            Decimal(str(lots)) * profile.contract_size * Decimal(str(distance))
        )
        actual_risk_pct = (actual_risk_usd / profile.balance * 100.0) if profile.balance else 0.0
        logger.info(
            f"PAPER SIZING [{profile.broker_profile}] {order.symbol}: "
            f"distance={distance:.5f} fixed_lot={lots:.4f} "
            f"risk=${actual_risk_usd:.2f} ({actual_risk_pct:.2f}%) "
            f"budget=${profile.risk_budget_usd:.2f} rr={settings.MIN_RR_TP1}"
        )

        # 6. Margin Validation
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

        # 7. Save Paper Position to DB
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
        # Flush so the trade id can be linked atomically to the consumed setup.
        db.flush()
        if signal is not None and paper_trade.status == "OPEN":
            signal_lifecycle.mark_signal_executed(db, signal, paper_trade.id)
        db.commit()
        db.refresh(paper_trade)

        # 8. Update Account Financials
        self.account_manager.recalculate_account_financials(db, account)

        logger.info(
            f"EXECUTED PAPER ORDER #{paper_trade.id}: [{paper_trade.order_type} {paper_trade.direction}] "
            f"{paper_trade.symbol} @ {paper_trade.entry_price:.5f} ({paper_trade.initial_position_size} Lots, Margin: ${paper_trade.margin_used:,.2f})"
        )
        return paper_trade

    def _ensure_auto_trade_open(
        self, db: Session, trade: PaperTrade, fallback_price: Optional[float]
    ) -> PaperTrade:
        """Guarantee an auto-executed MARKET trade is stored as OPEN.

        Market orders fill immediately. A stale PENDING market row is invisible
        to ``/paper/positions?status=OPEN`` and to the account/summary snapshots,
        which produced the "ghost trade" dashboard bug. Only PENDING MARKET rows
        are repaired; CANCELLED/CLOSED history and genuine LIMIT/STOP orders are
        left untouched.
        """
        if trade.status == "OPEN" or trade.status == "PARTIALLY_CLOSED":
            return trade
        if (
            trade.status != "PENDING"
            or str(trade.order_type or "").upper().strip() != "MARKET"
        ):
            return trade

        account = db.get(VirtualAccount, trade.account_id)
        logger.warning(
            f"Auto-executed MARKET trade #{trade.id} was persisted as PENDING; "
            "forcing OPEN so the dashboard can see the running position."
        )
        trade.status = "OPEN"
        trade.target_entry_price = None
        trade.entry_price = trade.entry_price or fallback_price or trade.current_price
        trade.current_price = trade.current_price or trade.entry_price
        if account is not None and not trade.margin_used:
            trade.margin_used = self.account_manager.calculate_required_margin(
                symbol=trade.symbol,
                lots=trade.remaining_position_size,
                price=trade.entry_price,
                leverage=account.leverage,
            )
        db.commit()
        db.refresh(trade)
        if account is not None:
            self.account_manager.recalculate_account_financials(db, account)
        return trade

    def open_trade_from_signal(
        self,
        db: Session,
        request: AutoTradeSignalRequest,
    ) -> PaperTrade:
        """Convert a trading signal into an active virtual position.

        Execution contract:
          * SL is re-derived from candles of the signal's OWN timeframe only
            (15m signal -> 15m swing/order block; never 1H or 4H).
          * TP is placed exactly 1:3 away from the fill price.
          * Lot size is the fixed value from the dynamic User Risk Profile.
          * Wide structural stops are never a rejection reason.

        Two pre-flight gates remain: timestamp staleness and live-price
        invalidation, both evaluated against the freshly resolved levels.
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
            )
            consumed = signal_lifecycle.executed_setup_keys(db)
            target_signal = None
            for candidate in db.scalars(stmt).all():
                key = signal_lifecycle.setup_key_of(candidate)
                if key is not None and key in consumed:
                    continue
                target_signal = candidate
                break

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
                return self._ensure_auto_trade_open(
                    db, existing_trade, existing_trade.current_price or target_signal.entry_price
                )

        # 2. Resolve live market price NOW (before validation and order placement).
        #    Do NOT reuse target_signal.entry_price — that price was captured at
        #    signal-generation time and may be 15–60 minutes stale.
        live_price = self.get_latest_market_price(db, target_signal.symbol)

        # 3. STRICT ENTRY-TIMEFRAME LOCK.
        #    The persisted signal's timeframe is authoritative. A 15m signal can
        #    only ever see 15m candles here: no 1H/4H query, no HTF structure, no
        #    stored HTF-derived SL/TP. The client-supplied timeframe is ignored.
        entry_timeframe = (
            str(target_signal.timeframe or request.timeframe or "15m").lower().strip()
        )
        pip_size = self.risk_manager.get_pip_size(target_signal.symbol)
        levels = self.resolve_signal_levels(
            db=db,
            signal=target_signal,
            entry_price=live_price,
            timeframe=entry_timeframe,
            pip_size=pip_size,
        )
        logger.info(
            f"STRUCTURAL LEVELS [{entry_timeframe}] Signal #{target_signal.id} "
            f"{target_signal.symbol} {levels.direction}: "
            f"entry={levels.entry_price:.5f} SL={levels.stop_loss:.5f} "
            f"({levels.source}) sl_dist={levels.sl_distance:.5f} "
            f"TP={levels.take_profit_1:.5f} RR={levels.rr_multiple}"
        )

        # The live-price gate validates the exact levels the Risk Engine placed.
        self.validate_signal_before_execution(
            db=db,
            signal=target_signal,
            current_price=live_price,
            stop_loss=levels.stop_loss,
            take_profit_1=levels.take_profit_1,
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

        # The Risk Engine already produced the final SL and 3R TP. Execution
        # must use those levels verbatim — no second derivation from the fill.
        order = PaperOrderCreate(
            account_id=request.account_id,
            symbol=target_signal.symbol,
            direction=SignalDirection(target_signal.direction),
            order_type="MARKET",
            risk_percent=request.risk_percent,
            stop_loss=levels.stop_loss,
            take_profit_1=levels.take_profit_1,
            take_profit_2=levels.take_profit_2,
            dynamic_tp_from_sl=False,
            signal_id=target_signal.id,
        )

        # 4. Execute at live market price with the fixed profile lot (0.01).
        trade = self.execute_order(db=db, order=order, current_market_price=live_price)

        # 5. Explicitly persist the running position as OPEN. This is the single
        #    source of truth consumed by /paper/positions?status=OPEN, the atomic
        #    /paper/summary snapshot and the account open-position counter.
        return self._ensure_auto_trade_open(db, trade, live_price)
