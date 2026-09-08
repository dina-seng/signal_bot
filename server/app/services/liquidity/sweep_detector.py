"""Liquidity Sweep / Stop Hunt (BSL & SSL) Detection Engine."""

from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Union
from app.schemas.candle import CandleBase
from app.schemas.liquidity import LiquidityEventType, LiquiditySweep
from app.schemas.structure import SwingPoint, SwingType


class LiquiditySweepDetector:
    """Detects institutional Buy-Side Liquidity (BSL) and Sell-Side Liquidity (SSL) sweeps / stop hunts.
    
    A Liquidity Sweep occurs when price penetrates a key prior swing extreme with a wick,
    triggering resting breakout/stop orders, but rejects and closes back inside the level.
    """

    def __init__(self, min_wick_ratio: float = 0.25):
        self.min_wick_ratio = min_wick_ratio

    @staticmethod
    def _extract_candle_data(candle: Any) -> tuple[datetime, float, float, float, float]:
        """Extract timestamp, open, high, low, close from diverse candle objects."""
        if isinstance(candle, dict):
            ts = candle.get("timestamp")
            o = float(candle.get("open", 0.0))
            h = float(candle.get("high", 0.0))
            l = float(candle.get("low", 0.0))
            c = float(candle.get("close", 0.0))
        else:
            ts = getattr(candle, "timestamp")
            o = float(getattr(candle, "open"))
            h = float(getattr(candle, "high"))
            l = float(getattr(candle, "low"))
            c = float(getattr(candle, "close"))

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)

        return ts, o, h, l, c

    @staticmethod
    def _get_pip_size(symbol: str) -> float:
        """Determine pip unit multiplier based on currency pair conventions."""
        s = symbol.upper()
        if "JPY" in s or "XAU" in s or "GOLD" in s:
            return 0.01
        return 0.0001

    def detect_sweeps(
        self,
        candles: Sequence[Union[CandleBase, Any]],
        swings: List[SwingPoint],
        symbol: str = "EUR/USD",
        min_wick_ratio: Optional[float] = None,
    ) -> List[LiquiditySweep]:
        """Identify all Buy-Side Liquidity (BSL) and Sell-Side Liquidity (SSL) sweeps.

        Args:
            candles: Chronological candle sequence.
            swings: Labeled SwingPoints.
            symbol: Instrument symbol for pip scaling.
            min_wick_ratio: Minimum ratio of rejection wick to entire candle range.

        Returns:
            List of LiquiditySweep events sorted chronologically.
        """
        if not candles or not swings:
            return []

        wick_threshold = min_wick_ratio if min_wick_ratio is not None else self.min_wick_ratio
        pip_size = self._get_pip_size(symbol)
        parsed_candles = [self._extract_candle_data(c) for c in candles]
        total_bars = len(parsed_candles)

        sweeps: List[LiquiditySweep] = []

        # Keep active unbroken swing levels to check for sweeps
        active_highs: List[SwingPoint] = []
        active_lows: List[SwingPoint] = []
        swings_by_idx = {s.index: s for s in swings}
        swept_high_indices = set()
        swept_low_indices = set()

        for i in range(total_bars):
            ts, o, h, l, c = parsed_candles[i]
            candle_range = max(1e-6, h - l)

            if i in swings_by_idx:
                sw = swings_by_idx[i]
                if sw.swing_type == SwingType.SWING_HIGH:
                    active_highs.append(sw)
                elif sw.swing_type == SwingType.SWING_LOW:
                    active_lows.append(sw)

                       # 1. Check for Buy-Side Liquidity Sweep (BSL) on active swing highs
            for sh in list(active_highs):
                if i <= sh.index:
                    continue

                # If candle body closed strictly above, it's a breakout/breach, not a sweep
                if c > sh.price:
                    active_highs.remove(sh)
                    continue

                # ✅ FIX: Use strict inequality (c < sh.price) to ensure true rejection, not a doji test
                if h > sh.price and c < sh.price:
                    if sh.index in swept_high_indices:
                        continue
                    
                    upper_wick = h - max(o, c)
                    wick_ratio = round(upper_wick / candle_range, 2)

                    if wick_ratio >= wick_threshold:
                        swept_high_indices.add(sh.index)
                        pips_swept = round((h - sh.price) / pip_size, 1)
                        sweeps.append(
                            LiquiditySweep(
                                index=i,
                                timestamp=ts,
                                sweep_type=LiquidityEventType.BUY_SIDE_SWEEP,
                                swept_level=sh.price,
                                sweep_extreme=h,
                                close_price=c,
                                wick_ratio=wick_ratio,
                                pips_swept=pips_swept,
                                broken_swing_timestamp=sh.timestamp,
                            )
                        )

            # 2. Check for Sell-Side Liquidity Sweep (SSL) on active swing lows
            for sl in list(active_lows):
                if i <= sl.index:
                    continue

                # If candle body closed strictly below, it's a breakout/breach, not a sweep
                if c < sl.price:
                    active_lows.remove(sl)
                    continue

                # ✅ FIX: Use strict inequality (c > sl.price) to ensure true rejection
                if l < sl.price and c > sl.price:
                    if sl.index in swept_low_indices:
                        continue
                    
                    lower_wick = min(o, c) - l
                    wick_ratio = round(lower_wick / candle_range, 2)

                    if wick_ratio >= wick_threshold:
                        swept_low_indices.add(sl.index)
                        pips_swept = round((sl.price - l) / pip_size, 1)
                        sweeps.append(
                            LiquiditySweep(
                                index=i,
                                timestamp=ts,
                                sweep_type=LiquidityEventType.SELL_SIDE_SWEEP,
                                swept_level=sl.price,
                                sweep_extreme=l,
                                close_price=c,
                                wick_ratio=wick_ratio,
                                pips_swept=pips_swept,
                                broken_swing_timestamp=sl.timestamp,
                            )
                        )

        # Sort sweeps chronologically
        sweeps.sort(key=lambda s: s.timestamp)
        return sweeps
