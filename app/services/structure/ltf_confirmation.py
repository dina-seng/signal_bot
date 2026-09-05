"""Lower Timeframe (LTF) Confirmation Engine for Multi-Timeframe Entry Validation."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Union
from app.schemas.candle import CandleBase
from app.schemas.liquidity import LiquidityEventType
from app.schemas.structure import SwingPoint, SwingType, TrendDirection
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
        primary_candles: Sequence[Union[CandleBase, any]],
        ltf_candles: Sequence[Union[CandleBase, any]],
        max_bars_ago: int = 5,
    ) -> tuple[bool, str]:
        """
        Check if Lower Timeframe confirms the Higher Timeframe signal.
        
        Args:
            primary_timeframe: The main signal timeframe (e.g., "1h", "4h")
            primary_direction: Signal direction (BULLISH or BEARISH)
            primary_candles: Primary timeframe candles
            ltf_candles: Lower timeframe candles (e.g., 15m for 1H signals)
            max_bars_ago: How many recent LTF bars to check for confirmation
            
        Returns:
            Tuple of (is_confirmed: bool, reason: str)
        """
        if not ltf_candles or len(ltf_candles) < 20:
            return False, "Insufficient LTF data for confirmation"

        # Get recent LTF candles (last max_bars_ago + buffer)
        recent_ltf = list(ltf_candles[-(max_bars_ago + 5):])
        
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