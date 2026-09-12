"""Price Action Candlestick Patterns and Fair Value Gap (FVG) Detection Engine."""

from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Union
from app.schemas.candle import CandleBase
from app.schemas.indicators import FairValueGap, FVGType, PatternType, PriceActionPattern


class PriceActionDetector:
    """Detects Pin Bars, Engulfing Bars, Inside Bars, and Fair Value Gaps (FVGs)."""

    @staticmethod
    def _extract_candle_data(candle: Any) -> tuple[datetime, float, float, float, float]:
        """Extract timestamp, open, high, low, close from candle object."""
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
        """Pip multiplier."""
        s = symbol.upper()
        if "JPY" in s or "XAU" in s or "GOLD" in s:
            return 0.01
        return 0.0001

    def detect_candlestick_patterns(
        self,
        candles: Sequence[Union[CandleBase, Any]],
        symbol: str = "XAU/USD",
    ) -> List[PriceActionPattern]:
        """Identify classic price-action candlestick patterns."""
        if len(candles) < 2:
            return []

        parsed = [self._extract_candle_data(c) for c in candles]
        patterns: List[PriceActionPattern] = []
        
        # ✅ FIX: Calculate dynamic tolerance based on pip size (e.g., 2 pips)
        pip_size = self._get_pip_size(symbol)
        overlap_tolerance = pip_size * 2.0

        for i in range(len(parsed)):
            # ✅ EXTRACT CURRENT CANDLE DATA FIRST
            ts, o, h, l, c = parsed[i]
            tr = max(1e-6, h - l)
            body = abs(c - o)
            upper_wick = h - max(o, c)
            lower_wick = min(o, c) - l

            # 1. Bullish Pin Bar (Hammer)
            # Long lower wick >= 55% of range, small upper wick <= 20%, small body <= 35%
            if lower_wick >= 0.55 * tr and upper_wick <= 0.20 * tr and body <= 0.35 * tr:
                patterns.append(
                    PriceActionPattern(
                        index=i,
                        timestamp=ts,
                        pattern_type=PatternType.BULLISH_PIN_BAR,
                        confidence=round(min(1.0, lower_wick / tr), 2),
                        description="Bullish Pin Bar / Hammer showing aggressive lower price rejection",
                    )
                )

            # 2. Bearish Pin Bar (Shooting Star)
            # Long upper wick >= 55% of range, small lower wick <= 20%, small body <= 35%
            elif upper_wick >= 0.55 * tr and lower_wick <= 0.20 * tr and body <= 0.35 * tr:
                patterns.append(
                    PriceActionPattern(
                        index=i,
                        timestamp=ts,
                        pattern_type=PatternType.BEARISH_PIN_BAR,
                        confidence=round(min(1.0, upper_wick / tr), 2),
                        description="Bearish Pin Bar / Shooting Star showing aggressive higher price rejection",
                    )
                )

            # Multi-bar patterns (requires i >= 1)
            if i >= 1:
                prev_ts, prev_o, prev_h, prev_l, prev_c = parsed[i - 1]
                prev_body = abs(prev_c - prev_o)

                # 3. Bullish Engulfing
                # Prev bar red, current bar green, current body engulfs prev body
                if prev_c < prev_o and c > o and c > prev_o and o <= (prev_c + overlap_tolerance) and body >= prev_body:
                    patterns.append(
                        PriceActionPattern(
                            index=i,
                            timestamp=ts,
                            pattern_type=PatternType.BULLISH_ENGULFING,
                            confidence=round(min(1.0, body / max(1e-6, prev_body)), 2),
                            description="Bullish Engulfing bar overwhelming previous selling momentum",
                        )
                    )

                # 4. Bearish Engulfing
                # Prev bar green, current bar red, current body engulfs prev body
                elif prev_c > prev_o and c < o and c < prev_o and o >= (prev_c - overlap_tolerance) and body >= prev_body:
                    patterns.append(
                        PriceActionPattern(
                            index=i,
                            timestamp=ts,
                            pattern_type=PatternType.BEARISH_ENGULFING,
                            confidence=round(min(1.0, body / max(1e-6, prev_body)), 2),
                            description="Bearish Engulfing bar overwhelming previous buying momentum",
                        )
                    )

                # 5. Inside Bar
                # Current bar range completely inside previous bar range
                elif h < prev_h and l > prev_l:
                    patterns.append(
                        PriceActionPattern(
                            index=i,
                            timestamp=ts,
                            pattern_type=PatternType.INSIDE_BAR,
                            confidence=0.8,
                            description="Inside Bar consolidation forming inside mother candle range",
                        )
                    )

        return patterns

    def detect_fair_value_gaps(
        self,
        candles: Sequence[Union[CandleBase, Any]],
        symbol: str = "XAU/USD",
        min_gap_pips: float = 1.0,
    ) -> List[FairValueGap]:
        """Detect Bullish and Bearish Fair Value Gaps (FVG / Imbalances) and track mitigation.

        - Bullish FVG: Low[i] > High[i-2]
        - Bearish FVG: High[i] < Low[i-2]
        """
        if len(candles) < 3:
            return []

        parsed = [self._extract_candle_data(c) for c in candles]
        pip_size = self._get_pip_size(symbol)
        fvgs: List[FairValueGap] = []

        for i in range(2, len(parsed)):
            curr_ts, curr_o, curr_h, curr_l, curr_c = parsed[i]
            prev2_ts, prev2_o, prev2_h, prev2_l, prev2_c = parsed[i - 2]

            # 1. Bullish FVG (Imbalance between bar i-2 high and bar i low)
            if curr_l > prev2_h:
                gap_size = curr_l - prev2_h
                gap_pips = round(gap_size / pip_size, 1)

                if gap_pips >= min_gap_pips:
                    # Check mitigation in subsequent candles
                    is_mitigated = False
                    mitigated_ts = None

                    for k in range(i + 1, len(parsed)):
                        sub_ts, sub_o, sub_h, sub_l, sub_c = parsed[k]
                        if sub_l <= prev2_h:
                            is_mitigated = True
                            mitigated_ts = sub_ts
                            break

                    fvgs.append(
                        FairValueGap(
                            index=i,
                            timestamp=curr_ts,
                            fvg_type=FVGType.BULLISH_FVG,
                            top_price=round(curr_l, 5),
                            bottom_price=round(prev2_h, 5),
                            gap_size=round(gap_size, 5),
                            gap_pips=gap_pips,
                            is_mitigated=is_mitigated,
                            mitigated_timestamp=mitigated_ts,
                        )
                    )

            # 2. Bearish FVG (Imbalance between bar i-2 low and bar i high)
            elif curr_h < prev2_l:
                gap_size = prev2_l - curr_h
                gap_pips = round(gap_size / pip_size, 1)

                if gap_pips >= min_gap_pips:
                    is_mitigated = False
                    mitigated_ts = None

                    for k in range(i + 1, len(parsed)):
                        sub_ts, sub_o, sub_h, sub_l, sub_c = parsed[k]
                        if sub_h >= prev2_l:
                            is_mitigated = True
                            mitigated_ts = sub_ts
                            break

                    fvgs.append(
                        FairValueGap(
                            index=i,
                            timestamp=curr_ts,
                            fvg_type=FVGType.BEARISH_FVG,
                            top_price=round(prev2_l, 5),
                            bottom_price=round(curr_h, 5),
                            gap_size=round(gap_size, 5),
                            gap_pips=gap_pips,
                            is_mitigated=is_mitigated,
                            mitigated_timestamp=mitigated_ts,
                        )
                    )

        return fvgs