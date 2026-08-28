"""Fractal N-Bar Swing Detection Engine for Market Structure Analysis."""

from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Union
from app.schemas.candle import CandleBase
from app.schemas.structure import SwingPoint, SwingType


class SwingDetector:
    """Deterministic N-Bar Fractal Swing High and Swing Low Detector.
    
    Identifies confirmed local price extrema (swings) across any candle series.
    """

    def __init__(self, default_lookback: int = 2):
        if default_lookback < 1:
            raise ValueError("default_lookback must be at least 1")
        self.default_lookback = default_lookback

    @staticmethod
    def _extract_candle_data(candle: Any) -> tuple[datetime, float, float]:
        """Extract timestamp, high, and low from diverse candle formats."""
        if isinstance(candle, dict):
            ts = candle.get("timestamp")
            h = float(candle.get("high", 0.0))
            l = float(candle.get("low", 0.0))
        else:
            ts = getattr(candle, "timestamp")
            h = float(getattr(candle, "high"))
            l = float(getattr(candle, "low"))

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)

        return ts, h, l

    def detect_swings(
        self,
        candles: Sequence[Union[CandleBase, Any]],
        lookback: Optional[int] = None,
        lookback_left: Optional[int] = None,
        lookback_right: Optional[int] = None,
    ) -> List[SwingPoint]:
        """Detect all confirmed swing highs and swing lows in a candle sequence.

        A candle at index i is a Swing High if:
            High[i] >= High[i-k] for all k in 1..lookback_left
            High[i] >  High[i+k] for all k in 1..lookback_right

        A candle at index i is a Swing Low if:
            Low[i] <= Low[i-k] for all k in 1..lookback_left
            Low[i] <  Low[i+k] for all k in 1..lookback_right

        Args:
            candles: Sequence of chronologically sorted candles.
            lookback: Uniform lookback window for left and right bars.
            lookback_left: Explicit left lookback bars (overrides lookback).
            lookback_right: Explicit right lookback bars (overrides lookback).

        Returns:
            List of SwingPoint objects sorted chronologically by candle index.
        """
        n_left = lookback_left if lookback_left is not None else (lookback if lookback is not None else self.default_lookback)
        n_right = lookback_right if lookback_right is not None else (lookback if lookback is not None else self.default_lookback)

        if n_left < 1 or n_right < 1:
            raise ValueError(f"Lookback values must be >= 1 (got left={n_left}, right={n_right})")

        total_bars = len(candles)
        min_required_bars = n_left + n_right + 1

        if total_bars < min_required_bars:
            return []

        # Pre-extract candle high, low, timestamp arrays for performance
        parsed = [self._extract_candle_data(c) for c in candles]
        timestamps = [p[0] for p in parsed]
        highs = [p[1] for p in parsed]
        lows = [p[2] for p in parsed]

        swings: List[SwingPoint] = []

        # Only bars from index n_left to total_bars - n_right - 1 can have confirmed swings
        start_idx = n_left
        end_idx = total_bars - n_right

        for i in range(start_idx, end_idx):
            curr_high = highs[i]
            curr_low = lows[i]

            # 1. Check Swing High
            is_swing_high = True
            for left_k in range(1, n_left + 1):
                if curr_high < highs[i - left_k]:
                    is_swing_high = False
                    break
            if is_swing_high:
                for right_k in range(1, n_right + 1):
                    if curr_high <= highs[i + right_k]:
                        is_swing_high = False
                        break

            if is_swing_high:
                swings.append(
                    SwingPoint(
                        index=i,
                        timestamp=timestamps[i],
                        price=curr_high,
                        swing_type=SwingType.SWING_HIGH,
                        structure_label=None,
                        confirmed=True,
                        bar_high=curr_high,
                        bar_low=curr_low,
                    )
                )

            # 2. Check Swing Low
            is_swing_low = True
            for left_k in range(1, n_left + 1):
                if curr_low > lows[i - left_k]:
                    is_swing_low = False
                    break
            if is_swing_low:
                for right_k in range(1, n_right + 1):
                    if curr_low >= lows[i + right_k]:
                        is_swing_low = False
                        break

            if is_swing_low:
                swings.append(
                    SwingPoint(
                        index=i,
                        timestamp=timestamps[i],
                        price=curr_low,
                        swing_type=SwingType.SWING_LOW,
                        structure_label=None,
                        confirmed=True,
                        bar_high=curr_high,
                        bar_low=curr_low,
                    )
                )

        # Sort swings chronologically by candle index and swing type
        swings.sort(key=lambda s: (s.index, 0 if s.swing_type == SwingType.SWING_HIGH else 1))
        return swings
