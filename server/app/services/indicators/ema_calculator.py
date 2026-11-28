"""Exponential Moving Average (EMA 20, 50, 200) Calculation Engine."""

from typing import List, Optional, Sequence
from app.schemas.indicators import EMASnapshot


def classify_ema_trend(
    price: Optional[float],
    ema_fast: Optional[float],
    ema_mid: Optional[float],
    ema_slow: Optional[float] = None,
) -> str:
    """Classify the EMA trend from the fast (20) / mid (50) alignment and price.

    Definitions (fast = EMA20, mid = EMA50, slow = EMA200):

    * BULLISH_STACK: EMA20 > EMA50 AND price > EMA20
    * BEARISH_STACK: EMA20 < EMA50 AND price < EMA20
    * BULLISH_BIAS / BEARISH_BIAS: fast/mid agree but price has not confirmed
    * NEUTRAL: any required input is missing or the EMAs are flat

    EMA200 is deliberately *not* required for the STACK labels — requiring it
    made a clearly aligned EMA20/EMA50 pair render as a mere BIAS and produced
    contradictory labels when the chart (different timeframe) showed EMA20
    above EMA50 while the card showed BEARISH_STACK.
    """
    if price is None or ema_fast is None or ema_mid is None:
        return "NEUTRAL"
    try:
        price_f, fast_f, mid_f = float(price), float(ema_fast), float(ema_mid)
    except (TypeError, ValueError):
        return "NEUTRAL"

    if fast_f > mid_f and price_f > fast_f:
        return "BULLISH_STACK"
    if fast_f < mid_f and price_f < fast_f:
        return "BEARISH_STACK"
    if fast_f > mid_f:
        return "BULLISH_BIAS"
    if fast_f < mid_f:
        return "BEARISH_BIAS"
    return "NEUTRAL"


class EMACalculator:
    """Calculates Exponential Moving Averages (EMA 20/50/200), Trend Stacks, and Crosses."""

    @staticmethod
    def calculate_ema_series(values: Sequence[float], period: int) -> List[Optional[float]]:
        """Calculate standard Exponential Moving Average series using smoothing multiplier alpha = 2 / (period + 1).

        Args:
            values: Sequence of closing prices.
            period: Smoothing window period.

        Returns:
            List of EMA values matching length of input values (None for initial warmup periods).
        """
        n = len(values)
        if n < period or period < 1:
            return [None] * n

        ema_series: List[Optional[float]] = [None] * n
        alpha = 2.0 / (period + 1)

        # Initialize first EMA with Simple Moving Average of first 'period' values
        sma_init = sum(values[:period]) / period
        ema_series[period - 1] = sma_init

        # Recursive calculation
        prev_ema = sma_init
        for i in range(period, n):
            current_ema = (values[i] * alpha) + (prev_ema * (1.0 - alpha))
            ema_series[i] = current_ema
            prev_ema = current_ema

        return ema_series

    def calculate_ema_snapshot(
        self,
        closes: Sequence[float],
        fast_period: int = 20,
        mid_period: int = 50,
        slow_period: int = 200,
    ) -> tuple[EMASnapshot, List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
        """Calculate full EMA series and generate current EMASnapshot.

        Returns:
            Tuple of (EMASnapshot, ema_fast_series, ema_mid_series, ema_slow_series)
        """
        if not closes:
            return EMASnapshot(), [], [], []

        ema_fast = self.calculate_ema_series(closes, fast_period)
        ema_mid = self.calculate_ema_series(closes, mid_period)
        ema_slow = self.calculate_ema_series(closes, slow_period)

        latest_price = closes[-1]
        curr_fast = ema_fast[-1]
        curr_mid = ema_mid[-1]
        curr_slow = ema_slow[-1]

        # Determine Trend Stack using the explicit EMA20/EMA50/price rule.
        # EMA200 is still reported via `price_vs_ema200`, but no longer gates
        # the stack label (see classify_ema_trend).
        trend = classify_ema_trend(latest_price, curr_fast, curr_mid, curr_slow)

        # Check Crosses (over last 5 bars)
        golden_cross = False
        death_cross = False

        if len(ema_mid) >= 2 and len(ema_slow) >= 2:
            prev_mid = ema_mid[-2]
            prev_slow = ema_slow[-2]
            if prev_mid is not None and prev_slow is not None and curr_mid is not None and curr_slow is not None:
                if prev_mid <= prev_slow and curr_mid > curr_slow:
                    golden_cross = True
                elif prev_mid >= prev_slow and curr_mid < curr_slow:
                    death_cross = True

        price_vs_200 = None
        if curr_slow is not None:
            price_vs_200 = "ABOVE" if latest_price >= curr_slow else "BELOW"

        snapshot = EMASnapshot(
            ema_fast=round(curr_fast, 5) if curr_fast is not None else None,
            ema_mid=round(curr_mid, 5) if curr_mid is not None else None,
            ema_slow=round(curr_slow, 5) if curr_slow is not None else None,
            ema_trend=trend,
            golden_cross=golden_cross,
            death_cross=death_cross,
            price_vs_ema200=price_vs_200,
        )

        return snapshot, ema_fast, ema_mid, ema_slow
