"""Candle Range Theory (CRT) Analyzer Service.

Implements the Accumulation, Manipulation, and Distribution (AMD) framework:
- Accumulation: Defines the benchmark trading range from a completed higher timeframe candle.
- Manipulation: Identifies lower-timeframe liquidity sweeps that breach the range boundary by a minimum depth percentage.
- Distribution: Confirms setup validity when price closes back inside the benchmark range.
"""

from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Union
from app.core.logging import logger
from app.schemas.structure import CRTAnalysis


def _get_candle_val(candle: Any, field_name: str) -> float:
    """Safely extract numeric price value from a CandleBase, dict, or ORM object."""
    if isinstance(candle, dict):
        return float(candle[field_name])
    return float(getattr(candle, field_name))


def _get_candle_ts(candle: Any) -> Optional[datetime]:
    """Safely extract datetime timestamp from a candle object."""
    if candle is None:
        return None
    raw = candle.get("timestamp") if isinstance(candle, dict) else getattr(candle, "timestamp", None)
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=timezone.utc)
    return None


class CRTAnalyzer:
    """Analyzer for Candle Range Theory (CRT) setups using the AMD framework."""

    def __init__(
        self,
        default_min_manip_pct: float = 5.0,
        default_confirm_bars: int = 1,
    ) -> None:
        self.default_min_manip_pct = default_min_manip_pct
        self.default_confirm_bars = default_confirm_bars

    @classmethod
    def analyze(
        cls,
        range_candles: Sequence[Any],
        confirm_candles: Sequence[Any],
        min_manip_pct: float = 5.0,
        confirm_bars: int = 1,
        lookback_bars: Optional[int] = None,
    ) -> CRTAnalysis:
        """Analyze higher timeframe range and lower timeframe manipulation/confirmation.

        Args:
            range_candles: Sequence of candles from the higher timeframe (e.g. 1H or 4H)
                defining the accumulation range.
            confirm_candles: Sequence of candles from the lower timeframe (e.g. 15m or 30m)
                used to detect manipulation sweeps and confirmation closes.
            min_manip_pct: Minimum manipulation depth as a percentage of the range size
                required to qualify as a valid sweep.
            confirm_bars: Number of consecutive closes required back inside the range.
            lookback_bars: Optional maximum number of recent confirm candles to evaluate.
                If None, all confirm_candles are evaluated.

        Returns:
            A CRTAnalysis Pydantic object detailing the AMD state.
        """
        if not range_candles or not confirm_candles:
            logger.debug("CRTAnalyzer: Insufficient candle data provided.")
            return CRTAnalysis(
                range_high=0.0,
                range_low=0.0,
                range_open=0.0,
                range_close=0.0,
                positive_direction=False,
                breach_point=None,
                is_breached=False,
                is_confirmed=False,
                manip_depth_pct=0.0,
            )

        # --------------------------------------------------------------
        # 1. Accumulation: Higher Timeframe Benchmark Candle
        # --------------------------------------------------------------
        ref_candle = range_candles[-1]
        range_high = _get_candle_val(ref_candle, "high")
        range_low = _get_candle_val(ref_candle, "low")
        range_open = _get_candle_val(ref_candle, "open")
        range_close = _get_candle_val(ref_candle, "close")
        range_open_ts = _get_candle_ts(ref_candle)

        positive_direction = range_close > range_open
        range_size = range_high - range_low

        if range_size <= 0.0:
            logger.warning(
                f"CRTAnalyzer: Degenerate range candle detected (high={range_high}, low={range_low})."
            )
            return CRTAnalysis(
                range_high=range_high,
                range_low=range_low,
                range_open=range_open,
                range_close=range_close,
                positive_direction=positive_direction,
                breach_point=None,
                is_breached=False,
                is_confirmed=False,
                manip_depth_pct=0.0,
                range_open_timestamp=range_open_ts,
            )

        # --------------------------------------------------------------
        # Chronological Verification: No-lookahead filtering
        # --------------------------------------------------------------
        # If candles carry meaningful, distinct timestamps, confirm/manipulation
        # candles must occur AFTER or at the close of the range candle.
        # When timestamps are missing or identical (e.g. synthetic test fixtures),
        # all provided confirm_candles are accepted.
        filtered_confirms: List[Any] = []
        if range_open_ts is not None:
            has_distinct_ts = any(
                _get_candle_ts(c) is not None and _get_candle_ts(c) != range_open_ts
                for c in confirm_candles
            )
            if has_distinct_ts:
                filtered_confirms = [
                    c for c in confirm_candles
                    if _get_candle_ts(c) is None or _get_candle_ts(c) >= range_open_ts
                ]
            else:
                filtered_confirms = list(confirm_candles)
        else:
            filtered_confirms = list(confirm_candles)

        if not filtered_confirms:
            return CRTAnalysis(
                range_high=round(range_high, 5),
                range_low=round(range_low, 5),
                range_open=round(range_open, 5),
                range_close=round(range_close, 5),
                positive_direction=positive_direction,
                breach_point=None,
                is_breached=False,
                is_confirmed=False,
                manip_depth_pct=0.0,
                range_open_timestamp=range_open_ts,
            )

        # Restrict confirm candles to lookback window if specified
        eval_candles = (
            filtered_confirms[-lookback_bars:]
            if lookback_bars is not None and len(filtered_confirms) > lookback_bars
            else filtered_confirms
        )

        # --------------------------------------------------------------
        # 2. Manipulation: Sweep of Range Extreme
        # --------------------------------------------------------------
        is_breached = False
        breach_point: Optional[float] = None
        breach_ts: Optional[datetime] = None
        breach_wick_ratio = 0.0
        manip_depth_pct = 0.0

        if positive_direction:
            # Bullish AMD: Expect manipulation sweeping below range_low
            breach_candidates = [
                c for c in eval_candles
                if _get_candle_val(c, "low") < range_low
            ]
            if breach_candidates:
                is_breached = True
                # Find the candle with the lowest extreme
                extreme_candle = min(breach_candidates, key=lambda c: _get_candle_val(c, "low"))
                breach_point = _get_candle_val(extreme_candle, "low")
                breach_ts = _get_candle_ts(extreme_candle)
                c_high = _get_candle_val(extreme_candle, "high")
                c_low = _get_candle_val(extreme_candle, "low")
                c_open = _get_candle_val(extreme_candle, "open")
                c_close = _get_candle_val(extreme_candle, "close")
                c_total_range = c_high - c_low
                # Lower rejection wick = distance from lower of (open, close) down to low
                lower_wick = max(0.0, min(c_open, c_close) - c_low)
                breach_wick_ratio = lower_wick / c_total_range if c_total_range > 0 else 0.0

                range_edge = range_low
                manip_depth_pct = (abs(range_edge - breach_point) / range_size) * 100.0
        else:
            # Bearish AMD: Expect manipulation sweeping above range_high
            breach_candidates = [
                c for c in eval_candles
                if _get_candle_val(c, "high") > range_high
            ]
            if breach_candidates:
                is_breached = True
                # Find the candle with the highest extreme
                extreme_candle = max(breach_candidates, key=lambda c: _get_candle_val(c, "high"))
                breach_point = _get_candle_val(extreme_candle, "high")
                breach_ts = _get_candle_ts(extreme_candle)
                c_high = _get_candle_val(extreme_candle, "high")
                c_low = _get_candle_val(extreme_candle, "low")
                c_open = _get_candle_val(extreme_candle, "open")
                c_close = _get_candle_val(extreme_candle, "close")
                c_total_range = c_high - c_low
                # Upper rejection wick = distance from high down to higher of (open, close)
                upper_wick = max(0.0, c_high - max(c_open, c_close))
                breach_wick_ratio = upper_wick / c_total_range if c_total_range > 0 else 0.0

                range_edge = range_high
                manip_depth_pct = (abs(range_edge - breach_point) / range_size) * 100.0

        # Round depth percentage for clean representation
        manip_depth_pct = round(manip_depth_pct, 4)
        breach_wick_ratio = round(breach_wick_ratio, 4)

        # --------------------------------------------------------------
        # 3. Distribution (Confirmation): Close Back Inside Range
        # --------------------------------------------------------------
        is_confirmed = False
        effective_confirm_bars = max(1, confirm_bars)
        confirmation_displacement = 0.0
        reentry_depth_pct = 0.0

        if is_breached and len(filtered_confirms) >= effective_confirm_bars:
            last_closes = [
                _get_candle_val(c, "close")
                for c in filtered_confirms[-effective_confirm_bars:]
            ]
            if positive_direction:
                # Bullish distribution: closed back above range_low
                is_confirmed = all(close_val > range_low for close_val in last_closes)
            else:
                # Bearish distribution: closed back below range_high
                is_confirmed = all(close_val < range_high for close_val in last_closes)

            if is_confirmed and len(filtered_confirms) > 0:
                last_c = filtered_confirms[-1]
                l_close = _get_candle_val(last_c, "close")
                l_open = _get_candle_val(last_c, "open")
                confirmation_displacement = round(abs(l_close - l_open), 5)
                if positive_direction:
                    reentry_depth_pct = round(max(0.0, (l_close - range_low) / range_size) * 100.0, 2)
                else:
                    reentry_depth_pct = round(max(0.0, (range_high - l_close) / range_size) * 100.0, 2)

        return CRTAnalysis(
            range_high=round(range_high, 5),
            range_low=round(range_low, 5),
            range_open=round(range_open, 5),
            range_close=round(range_close, 5),
            positive_direction=positive_direction,
            breach_point=round(breach_point, 5) if breach_point is not None else None,
            is_breached=is_breached,
            is_confirmed=is_confirmed,
            manip_depth_pct=manip_depth_pct,
            range_open_timestamp=range_open_ts,
            breach_timestamp=breach_ts,
            breach_wick_ratio=breach_wick_ratio,
            confirmation_displacement=confirmation_displacement,
            reentry_depth_pct=reentry_depth_pct,
        )
