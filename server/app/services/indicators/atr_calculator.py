"""Average True Range (ATR 14) and Dynamic Risk Buffer Calculation Engine."""

from typing import Any, List, Optional, Sequence, Union
from app.schemas.indicators import ATRSnapshot


class ATRCalculator:
    """Calculates Wilder's Smoothed Average True Range (ATR 14) and dynamic SL/TP buffers."""

    @staticmethod
    def _get_pip_size(symbol: str) -> float:
        """Get pip multiplier."""
        s = symbol.upper()
        if "JPY" in s or "XAU" in s or "GOLD" in s:
            return 0.01
        return 0.0001

    @staticmethod
    def calculate_true_range(
        highs: Sequence[float],
        lows: Sequence[float],
        closes: Sequence[float],
    ) -> List[float]:
        """Calculate True Range for each candle."""
        n = len(highs)
        if n == 0:
            return []

        tr = [0.0] * n
        tr[0] = highs[0] - lows[0]

        for i in range(1, n):
            h_l = highs[i] - lows[i]
            h_cp = abs(highs[i] - closes[i - 1])
            l_cp = abs(lows[i] - closes[i - 1])
            tr[i] = max(h_l, h_cp, l_cp)

        return tr

    def calculate_atr_series(
        self,
        highs: Sequence[float],
        lows: Sequence[float],
        closes: Sequence[float],
        period: int = 14,
    ) -> List[Optional[float]]:
        """Calculate Wilder's Smoothed ATR series."""
        n = len(highs)
        if n < period or period < 1:
            return [None] * n

        tr = self.calculate_true_range(highs, lows, closes)
        atr_series: List[Optional[float]] = [None] * n

        # Initial SMA of first 'period' True Ranges
        init_atr = sum(tr[:period]) / period
        atr_series[period - 1] = init_atr

        # Wilder's Smoothing
        prev_atr = init_atr
        for i in range(period, n):
            current_atr = ((prev_atr * (period - 1)) + tr[i]) / period
            atr_series[i] = current_atr
            prev_atr = current_atr

        return atr_series

    def calculate_atr_snapshot(
        self,
        highs: Sequence[float],
        lows: Sequence[float],
        closes: Sequence[float],
        symbol: str = "XAU/USD",
        period: int = 14,
    ) -> tuple[ATRSnapshot, List[Optional[float]]]:
        """Calculate ATR snapshot with pip conversion and suggested SL/TP distances."""
        atr_series = self.calculate_atr_series(highs, lows, closes, period=period)

        if not atr_series or atr_series[-1] is None:
            return ATRSnapshot(), atr_series

        val = atr_series[-1]
        pip_size = self._get_pip_size(symbol)
        atr_pips = round(val / pip_size, 1)

        # Determine Volatility State compared to longer baseline (up to last 50 bars)
        valid_atrs = [a for a in atr_series[-50:] if a is not None]
        avg_atr = sum(valid_atrs) / len(valid_atrs) if valid_atrs else val

        if val >= avg_atr * 1.3:
            vol_state = "HIGH"
        elif val <= avg_atr * 0.7:
            vol_state = "LOW"
        else:
            vol_state = "NORMAL"

        suggested_sl_pips = round(atr_pips * 1.5, 1)
        suggested_tp_pips = round(atr_pips * 3.0, 1)

        snapshot = ATRSnapshot(
            atr_value=round(val, 5),
            atr_pips=atr_pips,
            volatility_state=vol_state,
            suggested_sl_distance_pips=suggested_sl_pips,
            suggested_tp_distance_pips=suggested_tp_pips,
        )

        return snapshot, atr_series
