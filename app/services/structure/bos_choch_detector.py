"""Break of Structure (BOS) and Change of Character (CHOCH/MSS) Detection Engine."""

from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Union
from app.schemas.candle import CandleBase
from app.schemas.liquidity import BOSCHOCHType, BreakoutEvent
from app.schemas.structure import StructureLabel, SwingPoint, SwingType, TrendDirection


class BOSCHOCHDetector:
    """Detects Break of Structure (BOS) continuation and Change of Character (CHOCH/MSS) reversals.
    
    Rules:
    - Bullish BOS: Candle body closes strictly above prior major Swing High (HH) in an established uptrend.
    - Bearish BOS: Candle body closes strictly below prior major Swing Low (LL) in an established downtrend.
    - Bullish CHOCH / MSS: Candle body closes strictly above the most recent Lower High (LH) in a downtrend/range.
    - Bearish CHOCH / MSS: Candle body closes strictly below the most recent Higher Low (HL) in an uptrend/range.
    """

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

    def detect_bos_and_choch(
        self,
        candles: Sequence[Union[CandleBase, Any]],
        swings: List[SwingPoint],
        current_trend: TrendDirection = TrendDirection.RANGING,
        min_displacement_ratio: float = 0.1,
    ) -> tuple[List[BreakoutEvent], List[BreakoutEvent]]:
        """Identify all confirmed BOS and CHOCH breakout events across candle history.

        Args:
            candles: Chronologically sorted candle sequence.
            swings: Labeled SwingPoints sorted chronologically.
            current_trend: Classified trend context from StructureEngine.
            min_displacement_ratio: Minimum body breakout ratio required for valid displacement.

        Returns:
            Tuple of (bos_events_list, choch_events_list)
        """
        if not candles or not swings:
            return [], []

        parsed_candles = [self._extract_candle_data(c) for c in candles]
        total_bars = len(parsed_candles)

        bos_events: List[BreakoutEvent] = []
        choch_events: List[BreakoutEvent] = []

        # Keep track of active (unbroken) swing levels
        active_highs: List[SwingPoint] = []
        active_lows: List[SwingPoint] = []

        # Map swing start indices to swings for efficient lookahead processing
        swings_by_idx = {s.index: s for s in swings}

        # Track broken swing prices to avoid duplicate events on same swing
        broken_high_indices = set()
        broken_low_indices = set()

        for i in range(total_bars):
            ts, o, h, l, c = parsed_candles[i]
            candle_range = max(1e-6, h - l)

            # If a new confirmed swing formed at this index, activate it
            if i in swings_by_idx:
                sw = swings_by_idx[i]
                if sw.swing_type == SwingType.SWING_HIGH:
                    active_highs.append(sw)
                elif sw.swing_type == SwingType.SWING_LOW:
                    active_lows.append(sw)

            # 1. Check for Bullish Breakout above active swing highs
            for sh in list(active_highs):
                if i <= sh.index:
                    continue  # Breakout must happen after the swing bar

                # Candle body close above swing high level confirms breakout
                if c > sh.price:
                    if sh.index in broken_high_indices:
                        continue
                    broken_high_indices.add(sh.index)
                    active_highs.remove(sh)

                    # Calculate displacement momentum score
                    penetration = c - sh.price
                    displacement = round(min(1.0, max(0.1, penetration / candle_range)), 2)

                    # Determine if it's BOS (continuation) or CHOCH (reversal)
                    # Bullish BOS if broken swing was HH or market was bullish
                    # Bullish CHOCH if broken swing was LH (reversing from bearish structure)
                    is_bos = (sh.structure_label == StructureLabel.HH) or (
                        sh.structure_label != StructureLabel.LH and current_trend == TrendDirection.BULLISH
                    )

                    event_type = BOSCHOCHType.BULLISH_BOS if is_bos else BOSCHOCHType.BULLISH_CHOCH
                    breakout = BreakoutEvent(
                        index=i,
                        timestamp=ts,
                        event_type=event_type,
                        breakout_price=c,
                        broken_swing_price=sh.price,
                        broken_swing_index=sh.index,
                        broken_swing_timestamp=sh.timestamp,
                        broken_swing_label=sh.structure_label,
                        displacement_strength=displacement,
                    )

                    if is_bos:
                        bos_events.append(breakout)
                    else:
                        choch_events.append(breakout)

            # 2. Check for Bearish Breakout below active swing lows
            for sl in list(active_lows):
                if i <= sl.index:
                    continue

                # Candle body close below swing low level confirms breakout
                if c < sl.price:
                    if sl.index in broken_low_indices:
                        continue
                    broken_low_indices.add(sl.index)
                    active_lows.remove(sl)

                    penetration = sl.price - c
                    displacement = round(min(1.0, max(0.1, penetration / candle_range)), 2)

                    # Bearish BOS if broken swing was LL or market was bearish
                    # Bearish CHOCH if broken swing was HL (reversing from bullish structure)
                    is_bos = (sl.structure_label == StructureLabel.LL) or (
                        sl.structure_label != StructureLabel.HL and current_trend == TrendDirection.BEARISH
                    )

                    event_type = BOSCHOCHType.BEARISH_BOS if is_bos else BOSCHOCHType.BEARISH_CHOCH
                    breakout = BreakoutEvent(
                        index=i,
                        timestamp=ts,
                        event_type=event_type,
                        breakout_price=c,
                        broken_swing_price=sl.price,
                        broken_swing_index=sl.index,
                        broken_swing_timestamp=sl.timestamp,
                        broken_swing_label=sl.structure_label,
                        displacement_strength=displacement,
                    )

                    if is_bos:
                        bos_events.append(breakout)
                    else:
                        choch_events.append(breakout)

        return bos_events, choch_events
