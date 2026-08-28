"""Relative Strength Index (RSI 14) and Divergence Detection Engine."""

from datetime import datetime
from typing import List, Optional, Sequence
from app.schemas.indicators import DivergenceType, RSIDivergence, RSISnapshot
from app.schemas.structure import SwingPoint, SwingType


class RSICalculator:
    """Calculates Wilder's Smoothed RSI (14-period) and detects RSI Divergences."""

    @staticmethod
    def calculate_rsi_series(closes: Sequence[float], period: int = 14) -> List[Optional[float]]:
        """Calculate Wilder's Smoothed Relative Strength Index series.

        Args:
            closes: Sequence of closing prices.
            period: RSI period (standard: 14).

        Returns:
            List of RSI values (0 to 100), with None for initial warmup periods.
        """
        n = len(closes)
        if n <= period or period < 1:
            return [None] * n

        rsi_series: List[Optional[float]] = [None] * n

        gains = [0.0] * n
        losses = [0.0] * n

        for i in range(1, n):
            diff = closes[i] - closes[i - 1]
            if diff > 0:
                gains[i] = diff
            elif diff < 0:
                losses[i] = -diff

        # Initial Average Gain & Loss via Simple Average of first 'period' deltas
        avg_gain = sum(gains[1 : period + 1]) / period
        avg_loss = sum(losses[1 : period + 1]) / period

        if avg_loss == 0:
            rsi_series[period] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_series[period] = 100.0 - (100.0 / (1.0 + rs))

        # Wilder's Smoothing for subsequent values
        for i in range(period + 1, n):
            avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

            if avg_loss == 0:
                rsi_series[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi_series[i] = 100.0 - (100.0 / (1.0 + rs))

        return rsi_series

    def calculate_rsi_snapshot(
        self,
        closes: Sequence[float],
        period: int = 14,
    ) -> tuple[RSISnapshot, List[Optional[float]]]:
        """Calculate current RSISnapshot and full RSI series."""
        rsi_series = self.calculate_rsi_series(closes, period=period)

        if not rsi_series or rsi_series[-1] is None:
            return RSISnapshot(), rsi_series

        val = round(rsi_series[-1], 2)
        is_ob = val >= 70.0
        is_os = val <= 30.0

        if is_ob:
            condition = "OVERBOUGHT"
        elif is_os:
            condition = "OVERSOLD"
        elif val >= 55.0:
            condition = "BULLISH_ZONE"
        elif val <= 45.0:
            condition = "BEARISH_ZONE"
        else:
            condition = "NEUTRAL"

        snapshot = RSISnapshot(
            rsi_value=val,
            condition=condition,
            is_overbought=is_ob,
            is_oversold=is_os,
        )

        return snapshot, rsi_series

    def detect_divergences(
        self,
        swings: List[SwingPoint],
        rsi_series: List[Optional[float]],
        min_divergence_delta: float = 1.5,
    ) -> List[RSIDivergence]:
        """Detect Regular and Hidden RSI Divergences by comparing consecutive swing points.

        Args:
            swings: Labeled SwingPoints.
            rsi_series: Full calculated RSI series corresponding to candle indices.
            min_divergence_delta: Minimum RSI difference threshold to confirm divergence.

        Returns:
            List of detected RSIDivergence objects.
        """
        if len(swings) < 2 or not rsi_series:
            return []

        divergences: List[RSIDivergence] = []

        swing_highs = [s for s in swings if s.swing_type == SwingType.SWING_HIGH]
        swing_lows = [s for s in swings if s.swing_type == SwingType.SWING_LOW]

        # 1. Highs Divergence (Bearish Reversal / Hidden Bearish Continuation)
        for i in range(1, len(swing_highs)):
            prev_sh = swing_highs[i - 1]
            curr_sh = swing_highs[i]

            rsi_prev = rsi_series[prev_sh.index] if prev_sh.index < len(rsi_series) else None
            rsi_curr = rsi_series[curr_sh.index] if curr_sh.index < len(rsi_series) else None

            if rsi_prev is None or rsi_curr is None:
                continue

            price_diff = curr_sh.price - prev_sh.price
            rsi_diff = rsi_curr - rsi_prev

            # Regular Bearish Divergence: Price HH, RSI LH
            if price_diff > 0 and rsi_diff < -min_divergence_delta:
                divergences.append(
                    RSIDivergence(
                        divergence_type=DivergenceType.REGULAR_BEARISH,
                        start_index=prev_sh.index,
                        end_index=curr_sh.index,
                        start_timestamp=prev_sh.timestamp,
                        end_timestamp=curr_sh.timestamp,
                        price_start=prev_sh.price,
                        price_end=curr_sh.price,
                        rsi_start=round(rsi_prev, 2),
                        rsi_end=round(rsi_curr, 2),
                        strength=round(min(1.0, abs(rsi_diff) / 10.0), 2),
                    )
                )
            # Hidden Bearish Divergence: Price LH, RSI HH
            elif price_diff < 0 and rsi_diff > min_divergence_delta:
                divergences.append(
                    RSIDivergence(
                        divergence_type=DivergenceType.HIDDEN_BEARISH,
                        start_index=prev_sh.index,
                        end_index=curr_sh.index,
                        start_timestamp=prev_sh.timestamp,
                        end_timestamp=curr_sh.timestamp,
                        price_start=prev_sh.price,
                        price_end=curr_sh.price,
                        rsi_start=round(rsi_prev, 2),
                        rsi_end=round(rsi_curr, 2),
                        strength=round(min(1.0, abs(rsi_diff) / 10.0), 2),
                    )
                )

        # 2. Lows Divergence (Bullish Reversal / Hidden Bullish Continuation)
        for i in range(1, len(swing_lows)):
            prev_sl = swing_lows[i - 1]
            curr_sl = swing_lows[i]

            rsi_prev = rsi_series[prev_sl.index] if prev_sl.index < len(rsi_series) else None
            rsi_curr = rsi_series[curr_sl.index] if curr_sl.index < len(rsi_series) else None

            if rsi_prev is None or rsi_curr is None:
                continue

            price_diff = curr_sl.price - prev_sl.price
            rsi_diff = rsi_curr - rsi_prev

            # Regular Bullish Divergence: Price LL, RSI HL
            if price_diff < 0 and rsi_diff > min_divergence_delta:
                divergences.append(
                    RSIDivergence(
                        divergence_type=DivergenceType.REGULAR_BULLISH,
                        start_index=prev_sl.index,
                        end_index=curr_sl.index,
                        start_timestamp=prev_sl.timestamp,
                        end_timestamp=curr_sl.timestamp,
                        price_start=prev_sl.price,
                        price_end=curr_sl.price,
                        rsi_start=round(rsi_prev, 2),
                        rsi_end=round(rsi_curr, 2),
                        strength=round(min(1.0, abs(rsi_diff) / 10.0), 2),
                    )
                )
            # Hidden Bullish Divergence: Price HL, RSI LL
            elif price_diff > 0 and rsi_diff < -min_divergence_delta:
                divergences.append(
                    RSIDivergence(
                        divergence_type=DivergenceType.HIDDEN_BULLISH,
                        start_index=prev_sl.index,
                        end_index=curr_sl.index,
                        start_timestamp=prev_sl.timestamp,
                        end_timestamp=curr_sl.timestamp,
                        price_start=prev_sl.price,
                        price_end=curr_sl.price,
                        rsi_start=round(rsi_prev, 2),
                        rsi_end=round(rsi_curr, 2),
                        strength=round(min(1.0, abs(rsi_diff) / 10.0), 2),
                    )
                )

        divergences.sort(key=lambda d: d.end_timestamp)
        return divergences
