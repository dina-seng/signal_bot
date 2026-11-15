"""Pure ATR calculation in USD as volatility unit."""

from typing import List, Sequence
from app.schemas.candle import CandleCreate


def calculate_atr(candles: Sequence[CandleCreate], period: int = 14) -> List[float]:
    """Calculate Average True Range (ATR) in USD for a sequence of candles.

    Returns a list of ATR values corresponding to each candle index.
    For indices < period, returns the expanding average of true ranges available.
    """
    if not candles:
        return []

    tr_list: List[float] = []
    atr_list: List[float] = []

    for i, c in enumerate(candles):
        if i == 0:
            tr = c.high - c.low
        else:
            prev_close = candles[i - 1].close
            tr = max(
                c.high - c.low,
                abs(c.high - prev_close),
                abs(c.low - prev_close),
            )
        tr_list.append(tr)

        if i == 0:
            atr_list.append(tr)
        elif i < period:
            # Simple average while filling warmup window
            atr_list.append(sum(tr_list) / len(tr_list))
        else:
            # Wilder's smoothing: (prev_atr * (period - 1) + current_tr) / period
            prev_atr = atr_list[-1]
            atr = (prev_atr * (period - 1) + tr) / period
            atr_list.append(atr)

    return atr_list
