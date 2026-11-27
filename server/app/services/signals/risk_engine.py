"""Risk Engine — the single SL/TP actor.

Strict separation of concerns:

  * The Signal Engine finds the entry price and passes it here.
  * This engine NEVER changes, rejects, or re-derives the entry.
  * The stop uses the nearest confirmed 15m structural swing high/low buffered
    by 0.5*ATR(14), bounded by per-instrument minimum/maximum stop distances.
    When no valid swing exists the configured fixed gap is used (see ``gap``).
  * TP is placed at exactly ``rr_multiple`` times the final stop distance.
    Raw lots come from the risk budget and are floored to the broker lot step.

Affordability is deliberately NOT evaluated here — this component is a pure
SL/TP/lot calculator.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional, Sequence

from app.core.config import settings
from app.core.logging import logger
from app.schemas.signal import RiskParameters, SignalDirection
from app.schemas.structure import SwingType
from app.services.market_data.symbols import (
    UnknownSymbolError,
    get_instrument_spec,
    normalize_symbol,
)
from app.services.structure.swing_detector import SwingDetector


@dataclass(frozen=True)
class RiskLevels:
    """Immutable SL/TP placement produced by the Risk Engine."""

    symbol: str
    direction: str
    timeframe: str
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: Optional[float]
    sl_distance: float
    tp_distance: float
    rr_multiple: float
    lot_size: float
    source: str
    swing_count: int
    risk_percent: float
    risk_amount_usd: float
    min_lot_risk_usd: float
    raw_lot_size: float = 0.0


class RiskEngine:
    """Resolve a 15m structural stop and a fixed-RR target from a given entry."""

    def __init__(
        self,
        rr_multiple: Optional[float] = None,
        lot_size: Optional[float] = None,
        gap: Optional[float] = None,
        swing_lookback: Optional[int] = None,
        broker_spec: Any = None,
    ) -> None:
        # Lazy import avoids a signals <-> paper_trading package cycle.
        from app.services.paper_trading.broker_spec import get_broker_spec

        self.rr_multiple = (
            rr_multiple if rr_multiple is not None else float(settings.MIN_RR_TP1)
        )
        self._spec = broker_spec or get_broker_spec(settings.BROKER_SPEC)
        self._explicit_lot = lot_size is not None
        self.lot_size = (
            lot_size if lot_size is not None else float(self._spec.min_lot)
        )
        # Fixed price-unit gap used only when no valid 15m swing exists.
        self.gap = gap if gap is not None else 10.0
        self.swing_lookback = (
            swing_lookback if swing_lookback is not None else settings.SWING_LOOKBACK
        )
        self._detector = SwingDetector(default_lookback=self.swing_lookback)

    @staticmethod
    def _direction_value(direction: Any) -> str:
        return str(getattr(direction, "value", direction)).upper().strip()

    @staticmethod
    def get_pip_size(symbol: str) -> float:
        """Pip size from the centralized instrument specification."""
        try:
            return get_instrument_spec(symbol).pip_size
        except UnknownSymbolError:
            clean = str(symbol or "").upper().replace("%2F", "/").strip()
            return 0.01 if "JPY" in clean else 0.0001

    @staticmethod
    def get_pip_value_per_lot(symbol: str, current_price: float = 1.0) -> float:
        """USD value per pip for one standard lot (centralized spec)."""
        try:
            return get_instrument_spec(symbol).point_value_per_lot
        except UnknownSymbolError:
            return 10.0

    @staticmethod
    def _atr(candles: Optional[Sequence[Any]], entry: float) -> float:
        """ATR(14) from true range; fallback entry*0.0015 with <15 bars."""
        if candles is None or len(candles) < 15:
            return float(entry) * 0.0015
        try:
            highs = [float(getattr(c, "high")) for c in candles]
            lows = [float(getattr(c, "low")) for c in candles]
            closes = [float(getattr(c, "close")) for c in candles]
            true_ranges = []
            for i in range(1, len(candles)):
                true_ranges.append(
                    max(
                        highs[i] - lows[i],
                        abs(highs[i] - closes[i - 1]),
                        abs(lows[i] - closes[i - 1]),
                    )
                )
            if len(true_ranges) < 14:
                return float(entry) * 0.0015
            return sum(true_ranges[-14:]) / 14.0
        except (TypeError, ValueError, IndexError, AttributeError):
            return float(entry) * 0.0015

    @staticmethod
    def _sl_distance_bounds(symbol: str) -> tuple[float, float]:
        """Minimum / maximum stop distance in price units for this instrument."""
        pip_size = RiskEngine.get_pip_size(symbol)
        try:
            canonical = normalize_symbol(symbol)
        except UnknownSymbolError:
            canonical = str(symbol or "").upper()
        if canonical == "XAU/USD":
            return 4.0, 25.0
        return 15.0 * pip_size, 100.0 * pip_size

    def calculate_trade_risk(
        self,
        symbol: str,
        direction: SignalDirection,
        entry_price: float,
        atr_value: Optional[float] = None,
        key_support_low: Optional[float] = None,
        key_resistance_high: Optional[float] = None,
        account_balance: Optional[float] = None,
        risk_percent: Optional[float] = None,
        min_rr: Optional[float] = None,
    ) -> RiskParameters:
        """Compatibility sizing API kept on the single RiskEngine source."""
        balance = account_balance or 10000.0
        risk_pct = risk_percent or settings.MAX_RISK_PERCENT
        req_rr_tp1 = min_rr or settings.MIN_RR_TP1
        req_rr_tp2 = settings.MIN_RR_TP2
        pip_size = self.get_pip_size(symbol)

        effective_atr = (
            atr_value if (atr_value is not None and atr_value > 0) else entry_price * 0.0015
        )
        try:
            canonical = normalize_symbol(symbol)
        except UnknownSymbolError:
            canonical = symbol.upper()

        if canonical == "XAU/USD":
            max_sl_pips = 2500.0
        elif canonical == "USD/JPY":
            max_sl_pips = 120.0
        else:
            max_sl_pips = 100.0
        max_structural_distance = max_sl_pips * pip_size

        if direction == SignalDirection.BUY:
            if key_support_low is not None and key_support_low < entry_price:
                if (entry_price - key_support_low) > max_structural_distance:
                    logger.warning("Structural support too far; falling back to ATR-based SL.")
                    stop_loss = entry_price - (effective_atr * 1.5)
                else:
                    stop_loss = key_support_low - (effective_atr * 0.5)
            else:
                stop_loss = entry_price - (effective_atr * 1.5)
            if stop_loss >= entry_price:
                stop_loss = entry_price - (effective_atr * 1.5)
            risk_price = entry_price - stop_loss
            tp1 = entry_price + (risk_price * req_rr_tp1)
            tp2 = entry_price + (risk_price * req_rr_tp2)
        else:
            if key_resistance_high is not None and key_resistance_high > entry_price:
                if (key_resistance_high - entry_price) > max_structural_distance:
                    logger.warning("Structural resistance too far; falling back to ATR-based SL.")
                    stop_loss = entry_price + (effective_atr * 1.5)
                else:
                    stop_loss = key_resistance_high + (effective_atr * 0.5)
            else:
                stop_loss = entry_price + (effective_atr * 1.5)
            if stop_loss <= entry_price:
                stop_loss = entry_price + (effective_atr * 1.5)
            risk_price = stop_loss - entry_price
            tp1 = entry_price - (risk_price * req_rr_tp1)
            tp2 = entry_price - (risk_price * req_rr_tp2)

        risk_pips = round(risk_price / pip_size, 1)
        reward_pips_tp1 = round(abs(tp1 - entry_price) / pip_size, 1)
        reward_pips_tp2 = round(abs(tp2 - entry_price) / pip_size, 1)
        rr_tp1 = round(reward_pips_tp1 / max(1e-6, risk_pips), 2)
        rr_tp2 = round(reward_pips_tp2 / max(1e-6, risk_pips), 2)

        from app.services.paper_trading.broker_spec import get_broker_spec

        risk_amount_usd = round(balance * (risk_pct / 100.0), 2)
        pip_val = self.get_pip_value_per_lot(symbol)
        spec = get_broker_spec(settings.BROKER_SPEC)
        contract = (
            Decimal(str(spec.contract_size))
            if canonical == "XAU/USD"
            else Decimal(str(pip_val / pip_size))
        )
        raw_lots = (
            Decimal(str(risk_amount_usd)) / (Decimal(str(risk_price)) * contract)
            if risk_price > 0
            else Decimal("0")
        )
        executable = spec.floor_lots(raw_lots)
        is_executable = executable >= spec.min_lot
        suggested_lots = float(executable) if is_executable else 0.0
        min_lot_risk_usd = float(spec.min_lot * contract * Decimal(str(risk_price)))

        return RiskParameters(
            entry_price=round(entry_price, 5),
            stop_loss=round(stop_loss, 5),
            take_profit_1=round(tp1, 5),
            take_profit_2=round(tp2, 5),
            risk_pips=risk_pips,
            reward_pips_tp1=reward_pips_tp1,
            reward_pips_tp2=reward_pips_tp2,
            risk_reward_tp1=rr_tp1,
            risk_reward_tp2=rr_tp2,
            account_balance=balance,
            risk_percent=risk_pct,
            risk_amount_usd=risk_amount_usd,
            suggested_lot_size=suggested_lots,
            raw_lot_size=float(raw_lots),
            is_executable=is_executable,
            min_lot_risk_usd=min_lot_risk_usd,
            volume_step=float(spec.lot_step),
        )

    def _contract_size(self, symbol: str) -> float:
        try:
            canonical = normalize_symbol(symbol)
        except UnknownSymbolError:
            return float(self._spec.contract_size)
        if canonical == "XAU/USD":
            return float(self._spec.contract_size)
        from app.services.market_data.symbols import get_instrument_spec
        return float(get_instrument_spec(canonical).contract_size)

    def resolve_levels(
        self,
        *,
        symbol: str,
        direction: Any,
        entry_price: float,
        timeframe: str = "15m",
        candles: Optional[Sequence[Any]] = None,
        swings: Optional[Sequence[Any]] = None,
        balance: Optional[float] = None,
        risk_percent: Optional[float] = None,
    ) -> RiskLevels:
        """Place SL/TP around the entry supplied by the Signal Engine.

        The entry is used verbatim (rounded only for display precision). The
        stop is ATR-buffered and bounded; the entry itself is never re-derived
        or rejected here.
        """
        side = self._direction_value(direction)
        if side not in ("BUY", "SELL"):
            raise ValueError(f"Risk Engine requires BUY or SELL, got {side!r}.")

        entry = round(float(entry_price), 5)
        if entry <= 0:
            raise ValueError("Risk Engine requires a positive entry price.")

        # Keep the fixed gap from producing a non-positive price on low-priced
        # instruments (the 10-unit default is XAU-scaled).
        effective_gap = min(self.gap, entry * 0.01)

        tf = str(timeframe or "15m").lower().strip()
        if tf != "15m":
            raise ValueError(
                f"Risk Engine is 15m-only; refusing to place levels on {tf!r}."
            )

        bar_swings: Sequence[Any] = (
            list(swings)
            if swings is not None
            else (self._detector.detect_swings(candles, lookback=self.swing_lookback)
                  if candles else [])
        )
        atr = self._atr(candles, entry)
        min_dist, max_dist = self._sl_distance_bounds(symbol)

        if side == "BUY":
            candidates = [
                float(s.price)
                for s in bar_swings
                if getattr(s, "swing_type", None) == SwingType.SWING_LOW
                and 0.0 < float(s.price) < entry
            ]
            structural_sl = max(candidates) if candidates else None
            source = f"{tf}_swing_low_atr_buffered"
            # A 0.5*ATR buffer keeps the stop past the wick tip, not on it.
            candidate_sl = (
                round(structural_sl - 0.5 * atr, 5)
                if structural_sl is not None
                else round(entry - effective_gap, 5)
            )
            if structural_sl is None:
                source = f"{tf}_fixed_gap_{self.gap:g}"
        else:
            candidates = [
                float(s.price)
                for s in bar_swings
                if getattr(s, "swing_type", None) == SwingType.SWING_HIGH
                and float(s.price) > entry > 0
            ]
            structural_sl = min(candidates) if candidates else None
            source = f"{tf}_swing_high_atr_buffered"
            candidate_sl = (
                round(structural_sl + 0.5 * atr, 5)
                if structural_sl is not None
                else round(entry + effective_gap, 5)
            )
            if structural_sl is None:
                source = f"{tf}_fixed_gap_{self.gap:g}"

        # Apply the minimum stop floor and the maximum stop cap in price units.
        stop_loss = float(candidate_sl)
        sl_distance = abs(entry - stop_loss)
        if sl_distance < min_dist:
            stop_loss = round(entry - min_dist if side == "BUY" else entry + min_dist, 5)
            sl_distance = round(min_dist, 5)
            source += "_min_floor"
        elif sl_distance > max_dist:
            stop_loss = round(entry - max_dist if side == "BUY" else entry + max_dist, 5)
            sl_distance = round(max_dist, 5)
            source += "_max_cap"
        else:
            sl_distance = round(sl_distance, 5)
            stop_loss = round(stop_loss, 5)
        if sl_distance <= 0:
            stop_loss = round(entry - min_dist if side == "BUY" else entry + min_dist, 5)
            sl_distance = round(min_dist, 5)

        tp_distance = round(sl_distance * self.rr_multiple, 5)
        take_profit = round(
            entry + tp_distance if side == "BUY" else entry - tp_distance, 5
        )

        rpct = (
            risk_percent if risk_percent is not None else float(settings.MAX_RISK_PERCENT)
        )
        budget = round(float(balance) * (float(rpct) / 100.0), 2) if balance is not None else 0.0
        contract = self._contract_size(symbol)
        raw_lots = (
            budget / (sl_distance * contract) if sl_distance > 0 and contract > 0 else 0.0
        )
        floored_lots = float(self._spec.floor_lots(Decimal(str(raw_lots))))
        executable_lots = max(float(self._spec.min_lot), floored_lots)
        lot_size = self.lot_size if self._explicit_lot else executable_lots
        min_lot_risk = round(float(self._spec.min_lot) * contract * sl_distance, 2)

        return RiskLevels(
            symbol=symbol,
            direction=side,
            timeframe=tf,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit_1=take_profit,
            take_profit_2=None,
            sl_distance=sl_distance,
            tp_distance=tp_distance,
            rr_multiple=self.rr_multiple,
            lot_size=lot_size,
            source=source,
            swing_count=len(bar_swings),
            risk_percent=float(rpct),
            risk_amount_usd=budget,
            min_lot_risk_usd=min_lot_risk,
            raw_lot_size=raw_lots,
        )
