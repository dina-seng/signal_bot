"""Entry-timeframe-locked structural Stop Loss and dynamic 1:3 Take Profit.

This module is deliberately narrow: it takes candles (or already-detected
swings) from ONE timeframe and derives protective levels from that data only.
It never queries a database and never reads a higher timeframe, so a 15m entry
can only ever receive a 15m structural stop.
"""

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from app.core.config import settings
from app.schemas.signal import SignalDirection
from app.schemas.structure import SwingType
from app.services.structure.swing_detector import SwingDetector


@dataclass(frozen=True)
class StructuralLevels:
    """Resolved levels for a single entry timeframe."""

    timeframe: str
    direction: str
    entry_price: float
    structural_sl: float
    sl_distance: float
    take_profit_1: float
    take_profit_2: float
    rr_multiple: float
    source: str
    swing_count: int

    @property
    def stop_loss(self) -> float:
        """Alias used by callers that speak in terms of a plain stop price."""
        return self.structural_sl

    @property
    def tp_distance(self) -> float:
        return self.sl_distance * self.rr_multiple


class StructuralLevelEngine:
    """Derive SL/TP from the entry timeframe's structure only.

    Rules:
      * BUY  -> nearest confirmed swing LOW below entry (order-block low / 15m
                low as fallbacks). SL sits exactly on that structural price.
      * SELL -> nearest confirmed swing HIGH above entry (order-block high /
                15m high as fallbacks). SL sits exactly on that structural price.
      * sl_distance = abs(entry - structural_sl)
      * tp_distance = sl_distance * rr_multiple (1:3 by default)
      * TP is placed exactly tp_distance from the entry.

    No HTF candles, no ATR caps, no database access, no lot sizing.
    """

    def __init__(
        self,
        swing_lookback: Optional[int] = None,
        rr_multiple: Optional[float] = None,
    ) -> None:
        self.swing_lookback = (
            swing_lookback if swing_lookback is not None else settings.SWING_LOOKBACK
        )
        # RR is read from configuration, never hard-coded here.
        self.rr_multiple = (
            rr_multiple if rr_multiple is not None else float(settings.MIN_RR_TP1)
        )
        self._detector = SwingDetector(default_lookback=self.swing_lookback)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _value(candle: Any, field: str, default: float = 0.0) -> float:
        if isinstance(candle, dict):
            return float(candle.get(field, default) or default)
        return float(getattr(candle, field, default) or default)

    @staticmethod
    def _direction_value(direction: Any) -> str:
        value = getattr(direction, "value", direction)
        return str(value).upper().strip()

    def _order_block_level(
        self,
        candles: Sequence[Any],
        direction: str,
        entry_price: float,
    ) -> Optional[float]:
        """Most recent same-timeframe order-block extreme on the correct side.

        A bullish order block is the last down-close candle immediately before a
        bullish displacement; a bearish order block is the mirror image.
        """
        if len(candles) < 2:
            return None

        for i in range(len(candles) - 2, -1, -1):
            prev, cur = candles[i], candles[i + 1]
            prev_open = self._value(prev, "open")
            prev_close = self._value(prev, "close")
            cur_open = self._value(cur, "open")
            cur_close = self._value(cur, "close")

            if direction == "BUY":
                is_displacement = prev_close < prev_open and cur_close > cur_open and cur_close > prev_open
                level = self._value(prev, "low")
                if is_displacement and level > 0 and level < entry_price:
                    return level
            else:
                is_displacement = prev_close > prev_open and cur_close < cur_open and cur_close < prev_open
                level = self._value(prev, "high")
                if is_displacement and level > 0 and level > entry_price:
                    return level
        return None

    @staticmethod
    def _extreme_level(
        candles: Sequence[Any],
        direction: str,
        entry_price: float,
        pip_size: float,
    ) -> float:
        """Last-resort structural extreme from the SAME timeframe candles."""
        if candles:
            lows = [StructuralLevelEngine._value(c, "low") for c in candles]
            highs = [StructuralLevelEngine._value(c, "high") for c in candles]
            if direction == "BUY":
                candidate = min(lows) if lows else 0.0
                return candidate if 0.0 < candidate < entry_price else entry_price - pip_size
            candidate = max(highs) if highs else 0.0
            return candidate if candidate > entry_price > 0 else entry_price + pip_size
        return entry_price - pip_size if direction == "BUY" else entry_price + pip_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def resolve(
        self,
        *,
        candles: Sequence[Any],
        direction: Any,
        entry_price: float,
        timeframe: str,
        pip_size: float,
        swings: Optional[Sequence[Any]] = None,
    ) -> StructuralLevels:
        """Resolve a structural SL and an exact 1:3 TP from one timeframe."""
        side = self._direction_value(direction)
        if side not in ("BUY", "SELL"):
            raise ValueError(f"Structural levels require BUY or SELL, got {side!r}.")
        if entry_price <= 0:
            raise ValueError("Structural levels require a positive entry price.")
        if pip_size <= 0:
            raise ValueError("Structural levels require a positive pip size.")

        timeframe = str(timeframe or "").lower().strip()
        bar_swings: List[Any] = list(swings) if swings is not None else list(
            self._detector.detect_swings(candles, lookback=self.swing_lookback)
        )

        if side == "BUY":
            candidates = [
                s.price
                for s in bar_swings
                if getattr(s, "swing_type", None) == SwingType.SWING_LOW
                and 0.0 < float(s.price) < entry_price
            ]
            source = f"{timeframe}_swing_low"
            structural_sl = max(candidates) if candidates else None
            if structural_sl is None:
                structural_sl = self._order_block_level(candles, side, entry_price)
                source = f"{timeframe}_order_block_low"
            if structural_sl is None:
                structural_sl = self._extreme_level(candles, side, entry_price, pip_size)
                source = f"{timeframe}_low"
        else:
            candidates = [
                s.price
                for s in bar_swings
                if getattr(s, "swing_type", None) == SwingType.SWING_HIGH
                and float(s.price) > entry_price > 0
            ]
            source = f"{timeframe}_swing_high"
            structural_sl = min(candidates) if candidates else None
            if structural_sl is None:
                structural_sl = self._order_block_level(candles, side, entry_price)
                source = f"{timeframe}_order_block_high"
            if structural_sl is None:
                structural_sl = self._extreme_level(candles, side, entry_price, pip_size)
                source = f"{timeframe}_high"

        structural_sl = round(float(structural_sl), 5)
        sl_distance = abs(round(entry_price, 5) - structural_sl)
        if sl_distance <= 0:
            # Degenerate structure (entry exactly on the level): use one pip of
            # the instrument's own pip size so the stop stays on the right side.
            sl_distance = pip_size
            structural_sl = round(
                entry_price - pip_size if side == "BUY" else entry_price + pip_size, 5
            )

        if side == "BUY":
            tp1 = round(entry_price + sl_distance * self.rr_multiple, 5)
        else:
            tp1 = round(entry_price - sl_distance * self.rr_multiple, 5)

        return StructuralLevels(
            timeframe=timeframe,
            direction=side,
            entry_price=round(entry_price, 5),
            structural_sl=structural_sl,
            sl_distance=sl_distance,
            take_profit_1=tp1,
            take_profit_2=tp1,
            rr_multiple=self.rr_multiple,
            source=source,
            swing_count=len(bar_swings),
        )
