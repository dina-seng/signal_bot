"""Fractal swing pivot detection with strict zero lookahead.

A fractal pivot at index k requires N bars to the left and N bars to the right.
Crucial no-lookahead invariant:
The pivot is NOT known or visible until bar k+N has closed.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Sequence
from app.schemas.candle import CandleCreate


@dataclass(frozen=True)
class Pivot:
    """Represents a confirmed swing high or low pivot."""
    index: int             # Bar index k where the peak/trough occurred
    confirm_index: int     # Bar index k+N when the pivot became confirmed
    timestamp: datetime    # Timestamp of bar k
    confirm_timestamp: datetime # Timestamp of bar k+N
    price: float           # High or Low price
    pivot_type: str        # 'HIGH' or 'LOW'


def detect_pivots(candles: Sequence[CandleCreate], n: int = 3) -> List[Pivot]:
    """Detect fractal swing pivots strictly without lookahead bias.

    Args:
        candles: Chronologically sorted candle sequence.
        n: Left and right window size.

    Returns:
        List of confirmed Pivot objects, ordered by confirm_index.
    """
    total = len(candles)
    if total < 2 * n + 1:
        return []

    pivots: List[Pivot] = []

    # Check candidates k where k+n < total
    for k in range(n, total - n):
        c_k = candles[k]
        h_k = c_k.high
        l_k = c_k.low

        # Check Swing High
        is_high = True
        for j in range(1, n + 1):
            if candles[k - j].high >= h_k or candles[k + j].high > h_k:
                is_high = False
                break

        if is_high:
            pivots.append(
                Pivot(
                    index=k,
                    confirm_index=k + n,
                    timestamp=c_k.timestamp,
                    confirm_timestamp=candles[k + n].timestamp,
                    price=h_k,
                    pivot_type="HIGH",
                )
            )

        # Check Swing Low
        is_low = True
        for j in range(1, n + 1):
            if candles[k - j].low <= l_k or candles[k + j].low < l_k:
                is_low = False
                break

        if is_low:
            pivots.append(
                Pivot(
                    index=k,
                    confirm_index=k + n,
                    timestamp=c_k.timestamp,
                    confirm_timestamp=candles[k + n].timestamp,
                    price=l_k,
                    pivot_type="LOW",
                )
            )

    pivots.sort(key=lambda p: (p.confirm_index, p.index))
    return pivots
