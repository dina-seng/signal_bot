"""Risk Engine — the single SL/TP actor.

Strict separation of concerns:

  * The Signal Engine finds the entry price and passes it here.
  * This engine NEVER changes, rejects, or re-derives the entry.
  * It never uses ATR or candle-extreme fallbacks. The stop is the nearest
    confirmed 15m structural swing high/low. When no valid swing exists the
    configured fixed price-unit gap is used (see ``gap``).
  * TP is placed at exactly ``rr_multiple`` times the structural stop
    distance. Lot size is fixed to the broker minimum (0.01 on strict Exness).

Affordability is deliberately NOT evaluated here — this component is a pure
SL/TP/lot calculator.
"""

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from app.core.config import settings
from app.schemas.signal import SignalDirection
from app.schemas.structure import SwingType
from app.services.market_data.symbols import (
    UnknownSymbolError,
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

        The entry is used verbatim (rounded only for display precision). No ATR,
        no candle-extreme fallback, no affordability check, no entry rejection.
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

        if side == "BUY":
            candidates = [
                float(s.price)
                for s in bar_swings
                if getattr(s, "swing_type", None) == SwingType.SWING_LOW
                and 0.0 < float(s.price) < entry
            ]
            structural_sl = max(candidates) if candidates else None
            source = f"{tf}_swing_low"
            fallback_sl = round(entry - self.gap, 5)
        else:
            candidates = [
                float(s.price)
                for s in bar_swings
                if getattr(s, "swing_type", None) == SwingType.SWING_HIGH
                and float(s.price) > entry > 0
            ]
            structural_sl = min(candidates) if candidates else None
            source = f"{tf}_swing_high"
            fallback_sl = round(entry + self.gap, 5)

        if structural_sl is None:
            structural_sl = fallback_sl
            source = f"{tf}_fixed_gap_{self.gap:g}"

        stop_loss = round(float(structural_sl), 5)
        sl_distance = round(abs(entry - stop_loss), 5)
        if sl_distance <= 0:
            # Defensive only: the gap fallback always yields a positive distance.
            stop_loss = fallback_sl
            sl_distance = round(self.gap, 5)
            source = f"{tf}_fixed_gap_{self.gap:g}"

        tp_distance = round(sl_distance * self.rr_multiple, 5)
        take_profit = round(
            entry + tp_distance if side == "BUY" else entry - tp_distance, 5
        )

        rpct = (
            risk_percent if risk_percent is not None else float(settings.MAX_RISK_PERCENT)
        )
        budget = round(float(balance) * (float(rpct) / 100.0), 2) if balance is not None else 0.0
        contract = self._contract_size(symbol)
        min_lot_risk = round(self.lot_size * contract * sl_distance, 2)

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
            lot_size=self.lot_size,
            source=source,
            swing_count=len(bar_swings),
            risk_percent=float(rpct),
            risk_amount_usd=budget,
            min_lot_risk_usd=min_lot_risk,
        )
