"""Unit tests for Candlestick Price Action Patterns and Fair Value Gaps (FVGs)."""

from datetime import datetime, timedelta, timezone
import pytest
from app.schemas.candle import CandleCreate
from app.schemas.indicators import FVGType, PatternType
from app.services.indicators.price_action import PriceActionDetector


def generate_candles(prices: list[tuple[float, float, float, float]], base_time: datetime = None):
    """Helper to generate valid CandleCreate objects."""
    if base_time is None:
        base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles = []
    for i, (o, h, l, c) in enumerate(prices):
        t = base_time + timedelta(hours=i)
        candles.append(
            CandleCreate(
                symbol="EUR/USD",
                timeframe="1h",
                timestamp=t,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=100.0,
            )
        )
    return candles


def test_bullish_and_bearish_pin_bars():
    """Test recognition of Bullish Pin Bar (Hammer) and Bearish Pin Bar (Shooting Star)."""
    detector = PriceActionDetector()

    # 1. Bullish Pin Bar: Open=1.1080, High=1.1100, Low=1.0900, Close=1.1090
    # Range = 0.0200, Lower wick = 0.0180 (90%), Upper wick = 0.0010 (5%), Body = 0.0010 (5%)
    # 2. Bearish Pin Bar: Open=1.1020, High=1.1200, Low=1.1000, Close=1.1010
    # Range = 0.0200, Upper wick = 0.0180 (90%), Lower wick = 0.0010 (5%), Body = 0.0010 (5%)
    prices = [
        (1.1050, 1.1080, 1.1020, 1.1060),  # 0: normal candle
        (1.1080, 1.1100, 1.0900, 1.1090),  # 1: Bullish Pin Bar
        (1.1050, 1.1080, 1.1020, 1.1060),  # 2: normal candle
        (1.1020, 1.1200, 1.1000, 1.1010),  # 3: Bearish Pin Bar
    ]
    candles = generate_candles(prices)
    patterns = detector.detect_candlestick_patterns(candles)

    types = [p.pattern_type for p in patterns]
    assert PatternType.BULLISH_PIN_BAR in types
    assert PatternType.BEARISH_PIN_BAR in types


def test_bullish_and_bearish_engulfing():
    """Test Bullish and Bearish Engulfing pattern detection."""
    detector = PriceActionDetector()

    # 1. Red candle then big Green candle engulfing
    # 2. Green candle then big Red candle engulfing
    prices = [
        (1.1050, 1.1060, 1.0990, 1.1000),  # 0: Red (O=1.1050, C=1.1000)
        (1.0990, 1.1100, 1.0980, 1.1090),  # 1: Green Bullish Engulfing (O=1.0990, C=1.1090)
        (1.1090, 1.1120, 1.1070, 1.1110),  # 2: Green (O=1.1090, C=1.1110)
        (1.1120, 1.1130, 1.0980, 1.1000),  # 3: Red Bearish Engulfing (O=1.1120, C=1.1000)
    ]
    candles = generate_candles(prices)
    patterns = detector.detect_candlestick_patterns(candles)

    types = [p.pattern_type for p in patterns]
    assert PatternType.BULLISH_ENGULFING in types
    assert PatternType.BEARISH_ENGULFING in types


def test_inside_bar():
    """Test Inside Bar pattern recognition."""
    detector = PriceActionDetector()

    prices = [
        (1.1000, 1.1200, 1.0800, 1.1100),  # 0: Mother Bar (High=1.1200, Low=1.0800)
        (1.1050, 1.1150, 1.0900, 1.1080),  # 1: Inside Bar (High=1.1150 < 1.1200, Low=1.0900 > 1.0800)
    ]
    candles = generate_candles(prices)
    patterns = detector.detect_candlestick_patterns(candles)

    types = [p.pattern_type for p in patterns]
    assert PatternType.INSIDE_BAR in types


def test_fair_value_gaps_and_mitigation():
    """Test Bullish and Bearish Fair Value Gaps (FVG / Imbalances) and mitigation tracking."""
    detector = PriceActionDetector()

    # 1. Bullish FVG:
    # Bar 0: High = 1.1020
    # Bar 1: Strong impulse (O=1.1030, H=1.1200, L=1.1025, C=1.1190)
    # Bar 2: Low = 1.1150  -> Gap between Bar 0 High (1.1020) and Bar 2 Low (1.1150) = 130 pips!
    # Bar 3: Retest/mitigation candle dipping to Low = 1.1010 <= 1.1020 (Mitigates FVG)
    prices = [
        (1.1000, 1.1020, 1.0980, 1.1010),  # 0: High = 1.1020
        (1.1030, 1.1200, 1.1025, 1.1190),  # 1: Big green impulse
        (1.1160, 1.1250, 1.1150, 1.1230),  # 2: Low = 1.1150 (FVG created)
        (1.1200, 1.1220, 1.1010, 1.1050),  # 3: Low = 1.1010 (Mitigates FVG)
    ]
    candles = generate_candles(prices)
    fvgs = detector.detect_fair_value_gaps(candles, symbol="EUR/USD", min_gap_pips=5.0)

    assert len(fvgs) == 1
    fvg = fvgs[0]
    assert fvg.fvg_type == FVGType.BULLISH_FVG
    assert fvg.bottom_price == 1.1020
    assert fvg.top_price == 1.1150
    assert fvg.gap_pips == 130.0
    assert fvg.is_mitigated is True
    assert fvg.mitigated_timestamp == candles[3].timestamp
