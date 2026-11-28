"""Average Directional Index (ADX 14) calculation engine.

Pure-Python implementation using Wilder smoothing, matching the conventions of
``atr_calculator.py``. ADX measures trend *strength* (not direction) and is used
by the BTC momentum strategy as a regime gate: values below 25 indicate a
ranging market where breakout-style triggers are unreliable.
"""

from typing import Any, List, Optional, Sequence

from app.services.indicators.atr_calculator import ATRCalculator


class ADXCalculator:
    """Calculate Wilder's smoothed ADX series from OHLC candles."""

    @staticmethod
    def calculate_directional_movement(
        highs: Sequence[float], lows: Sequence[float]
    ) -> tuple[List[float], List[float]]:
        """Return (+DM, -DM) series for each bar (first bar is zero)."""
        n = min(len(highs), len(lows))
        plus_dm = [0.0] * n
        minus_dm = [0.0] * n
        for i in range(1, n):
            up_move = highs[i] - highs[i - 1]
            down_move = lows[i - 1] - lows[i]
            plus_dm[i] = up_move if up_move > down_move and up_move > 0.0 else 0.0
            minus_dm[i] = down_move if down_move > up_move and down_move > 0.0 else 0.0
        return plus_dm, minus_dm

    @staticmethod
    def _directional_index(sm_tr: float, sm_plus: float, sm_minus: float) -> float:
        """DX from smoothed TR/+DM/-DM; degenerate denominators yield 0.0."""
        if sm_tr <= 0.0:
            return 0.0
        plus_di = 100.0 * sm_plus / sm_tr
        minus_di = 100.0 * sm_minus / sm_tr
        total = plus_di + minus_di
        if total <= 0.0:
            return 0.0
        return 100.0 * abs(plus_di - minus_di) / total

    def calculate_adx_series(
        self,
        highs: Sequence[float],
        lows: Sequence[float],
        closes: Sequence[float],
        period: int = 14,
    ) -> List[Optional[float]]:
        """Calculate the Wilder-smoothed ADX series (None during warm-up)."""
        n = min(len(highs), len(lows), len(closes))
        if period < 1 or n < 2 * period:
            return [None] * n

        highs, lows, closes = highs[:n], lows[:n], closes[:n]
        tr = ATRCalculator.calculate_true_range(highs, lows, closes)
        plus_dm, minus_dm = self.calculate_directional_movement(highs, lows)

        # Wilder seed: simple average of the first `period` values.
        sm_tr = sum(tr[:period]) / period
        sm_plus = sum(plus_dm[:period]) / period
        sm_minus = sum(minus_dm[:period]) / period

        dx: List[Optional[float]] = [None] * n
        dx[period - 1] = self._directional_index(sm_tr, sm_plus, sm_minus)
        for i in range(period, n):
            sm_tr = (sm_tr * (period - 1) + tr[i]) / period
            sm_plus = (sm_plus * (period - 1) + plus_dm[i]) / period
            sm_minus = (sm_minus * (period - 1) + minus_dm[i]) / period
            dx[i] = self._directional_index(sm_tr, sm_plus, sm_minus)

        adx: List[Optional[float]] = [None] * n
        seed_start = period - 1
        seed_end = 2 * period - 1  # first ADX lands on index 2*period-2
        seed = [value for value in dx[seed_start:seed_end] if value is not None]
        if len(seed) < period:
            return adx
        previous = sum(seed) / len(seed)
        adx[seed_end - 1] = previous
        for i in range(seed_end, n):
            dx_value = dx[i] if dx[i] is not None else 0.0
            previous = (previous * (period - 1) + dx_value) / period
            adx[i] = previous
        return adx

    def calculate_adx(
        self,
        highs: Sequence[float],
        lows: Sequence[float],
        closes: Sequence[float],
        period: int = 14,
    ) -> Optional[float]:
        """Return the latest ADX value (None when the series is too short)."""
        series = self.calculate_adx_series(highs, lows, closes, period=period)
        for value in reversed(series):
            if value is not None:
                return value
        return None

    @staticmethod
    def _candle_field(candle: Any, field: str) -> Any:
        if isinstance(candle, dict):
            return candle.get(field)
        return getattr(candle, field, None)

    def calculate_adx_from_candles(
        self, candles: Sequence[Any], period: int = 14
    ) -> Optional[float]:
        """Convenience: extract OHLC from candle objects/mappings and return ADX."""
        if not candles:
            return None
        try:
            highs = [float(self._candle_field(c, "high")) for c in candles]
            lows = [float(self._candle_field(c, "low")) for c in candles]
            closes = [float(self._candle_field(c, "close")) for c in candles]
        except (TypeError, ValueError):
            return None
        return self.calculate_adx(highs, lows, closes, period=period)
