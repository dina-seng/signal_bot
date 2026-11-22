"""Lower Timeframe (LTF) Confirmation Engine for Multi-Timeframe Entry Validation."""

from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Sequence, Union
from app.core.logging import logger
from app.schemas.candle import CandleBase
from app.schemas.liquidity import LiquidityEventType
from app.schemas.structure import SwingPoint, SwingType, TrendDirection
from app.services.market_data.freshness import ensure_utc_datetime, get_timeframe_delta
from app.services.structure.swing_detector import SwingDetector
from app.services.structure.bos_choch_detector import BOSCHOCHDetector


class LTFConfirmationEngine:
    """Validates Higher Timeframe signals with Lower Timeframe confirmation."""

    def __init__(self):
        self.swing_detector = SwingDetector(default_lookback=2)
        self.bos_choch_detector = BOSCHOCHDetector()

    def check_ltf_confirmation(
        self,
        primary_timeframe: str,
        primary_direction: TrendDirection,
        primary_candles: Sequence[Union[CandleBase, Any]],
        ltf_candles: Sequence[Union[CandleBase, Any]],
        max_bars_ago: int = 5,
        decision_time: Optional[datetime] = None,
    ) -> tuple[bool, str]:
        """
        Check if Lower Timeframe confirms the Higher Timeframe signal.

        Args:
            primary_timeframe: The main signal timeframe (e.g., "1h", "4h")
            primary_direction: Signal direction (BULLISH or BEARISH)
            primary_candles: Primary timeframe candles
            ltf_candles: Lower timeframe candles (e.g., 15m for 1H signals)
            max_bars_ago: How many recent LTF bars to check for confirmation
            decision_time: As-of cutoff for the LTF window. When supplied by
                ``SMCStrategy`` this is the 15m decision close, so the LTF
                confirmation sees the same 15m data as the MTF alignment. When
                omitted, the legacy primary-timeframe (1h) close is used.

        Returns:
            Tuple of (is_confirmed: bool, reason: str)
        """
        if not ltf_candles:
            return False, "Insufficient LTF data for confirmation"

        # Determine the LTF window cutoff. The 15m decision close is preferred:
        # it keeps the confirmation window aligned with the 15m MTF structure
        # actually used for the decision instead of freezing it at the 1h close
        # (up to 45 minutes stale intra-hour). Candles closing after the cutoff
        # are still excluded, so this introduces no lookahead.
        primary_close_time = None
        if decision_time is not None:
            try:
                primary_close_time = ensure_utc_datetime(decision_time)
            except Exception:
                primary_close_time = None

        # Legacy fallback: derive the cutoff from the primary (1h) candle close.
        if primary_close_time is None and primary_candles:
            last_prim = primary_candles[-1]
            prim_ts = getattr(last_prim, "timestamp", None)
            if isinstance(last_prim, dict):
                prim_ts = last_prim.get("timestamp", prim_ts)
            if prim_ts is not None:
                try:
                    prim_utc = ensure_utc_datetime(prim_ts)
                    prim_delta = get_timeframe_delta(primary_timeframe)
                    primary_close_time = prim_utc + prim_delta
                except Exception:
                    primary_close_time = None

        ltf_delta = None
        try:
            first_candle = ltf_candles[0]
            ltf_tf = getattr(first_candle, "timeframe", "15m")
            if isinstance(first_candle, dict):
                ltf_tf = first_candle.get("timeframe", ltf_tf)
            ltf_delta = get_timeframe_delta(ltf_tf)
        except Exception:
            ltf_delta = timedelta(minutes=15)

        # Exclude currently forming / open candles:
        # 1. Filter out candles explicitly flagged with is_closed=False
        # 2. Filter out candles opening at or after the primary timeframe close
        closed_ltf_candles: List[Any] = []
        for c in ltf_candles:
            is_closed = getattr(c, "is_closed", None)
            if isinstance(c, dict):
                is_closed = c.get("is_closed", is_closed)
            if is_closed is False:
                continue

            if primary_close_time is not None:
                c_ts = getattr(c, "timestamp", None)
                if isinstance(c, dict):
                    c_ts = c.get("timestamp", c_ts)
                if c_ts is not None:
                    c_utc = ensure_utc_datetime(c_ts)
                    if c_utc is not None:
                        if c_utc >= primary_close_time:
                            continue
                        if ltf_delta is not None and (c_utc + ltf_delta) > primary_close_time:
                            continue

            closed_ltf_candles.append(c)

        logger.info(f"LTF Confirmation checked on {len(closed_ltf_candles)} fully closed candles.")

        if len(closed_ltf_candles) < (max_bars_ago + 5):
            return False, "Insufficient LTF data for confirmation"

        # Get recent closed LTF candles (last max_bars_ago + buffer for swing detection)
        recent_ltf = list(closed_ltf_candles[-(max_bars_ago + 5):])
        
        # Detect LTF structure
        ltf_swings = self.swing_detector.detect_swings(recent_ltf, lookback=2)
        
        if not ltf_swings:
            return False, "No LTF swings detected"

        # Detect LTF BOS/CHOCH
        ltf_bos_events, ltf_choch_events = self.bos_choch_detector.detect_bos_and_choch(
            candles=recent_ltf,
            swings=ltf_swings,
            current_trend=TrendDirection.RANGING,  # We'll check the event types directly
        )

        # Check for recent CHOCH in the same direction
        if primary_direction == TrendDirection.BULLISH:
            # Look for BULLISH_CHOCH in recent LTF bars
            recent_bullish_choch = [
                e for e in ltf_choch_events 
                if "BULLISH" in e.event_type.value
            ]
            
            if recent_bullish_choch:
                latest_choch = recent_bullish_choch[-1]
                return True, f"LTF Bullish CHOCH confirmed at {latest_choch.breakout_price:.5f}"

            # Also check for BSL (Buy-Side Liquidity) sweep as alternative confirmation
            # This would be detected in liquidity service, but we can check for bullish structure here
            recent_bullish_bos = [
                e for e in ltf_bos_events
                if "BULLISH" in e.event_type.value
            ]
            
            if recent_bullish_bos:
                latest_bos = recent_bullish_bos[-1]
                return True, f"LTF Bullish BOS confirmed at {latest_bos.breakout_price:.5f}"

        elif primary_direction == TrendDirection.BEARISH:
            # Look for BEARISH_CHOCH in recent LTF bars
            recent_bearish_choch = [
                e for e in ltf_choch_events
                if "BEARISH" in e.event_type.value
            ]
            
            if recent_bearish_choch:
                latest_choch = recent_bearish_choch[-1]
                return True, f"LTF Bearish CHOCH confirmed at {latest_choch.breakout_price:.5f}"

            # Check for SSL (Sell-Side Liquidity) sweep alternative
            recent_bearish_bos = [
                e for e in ltf_bos_events
                if "BEARISH" in e.event_type.value
            ]
            
            if recent_bearish_bos:
                latest_bos = recent_bearish_bos[-1]
                return True, f"LTF Bearish BOS confirmed at {latest_bos.breakout_price:.5f}"

        return False, f"No LTF confirmation found in last {max_bars_ago} bars"