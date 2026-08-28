"""Unit tests for Swing Detection, Market Structure (HH/HL/LH/LL), and Trend Classification."""

from datetime import datetime, timedelta, timezone
import pytest
from app.models.candle import Candle
from app.models.structure import StructureEvent
from app.schemas.candle import CandleBase, CandleCreate
from app.schemas.structure import (
    MultiTimeframeAlignment,
    StructureLabel,
    SwingType,
    TrendDirection,
)
from app.services.structure.swing_detector import SwingDetector
from app.services.structure.structure_engine import StructureEngine
from app.services.structure.multi_timeframe import MultiTimeframeStructureEngine


def generate_synthetic_candles(prices: list[tuple[float, float, float, float]], base_time: datetime = None):
    """Helper to generate a list of CandleCreate from (open, high, low, close) tuples."""
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


def test_swing_detector_empty_or_short_series():
    """Test swing detector behavior on empty or too-short candle sequences."""
    detector = SwingDetector(default_lookback=2)
    assert detector.detect_swings([]) == []

    # 4 candles is less than min 2 + 2 + 1 = 5 candles
    short_candles = generate_synthetic_candles([(1.0, 1.1, 0.9, 1.0)] * 4)
    assert detector.detect_swings(short_candles, lookback=2) == []


def test_swing_detector_basic_peak_and_trough():
    """Test detection of a clear isolated peak (Swing High) and trough (Swing Low)."""
    # 7 candles with valid OHLC invariants:
    prices = [
        (1.00, 1.05, 0.95, 1.00),  # 0
        (1.00, 1.10, 0.98, 1.05),  # 1
        (1.05, 1.25, 1.02, 1.20),  # 2: Peak High=1.25 (SH)
        (1.10, 1.15, 0.90, 0.95),  # 3
        (0.90, 0.95, 0.80, 0.85),  # 4: Trough Low=0.80 (SL)
        (0.85, 0.95, 0.84, 0.92),  # 5
        (0.92, 1.05, 0.91, 1.00),  # 6
    ]
    candles = generate_synthetic_candles(prices)
    detector = SwingDetector(default_lookback=2)
    swings = detector.detect_swings(candles, lookback=2)

    assert len(swings) == 2
    sh = swings[0]
    sl = swings[1]

    assert sh.swing_type == SwingType.SWING_HIGH
    assert sh.index == 2
    assert sh.price == 1.25

    assert sl.swing_type == SwingType.SWING_LOW
    assert sl.index == 4
    assert sl.price == 0.80


def test_structure_engine_uptrend_higher_highs_and_higher_lows():
    """Test market structure labeling and trend classification for a classic Bullish Uptrend (HH + HL)."""
    # Upward zigzag with lookback=1:
    prices = [
        (1.00, 1.04, 0.98, 1.02),  # 0
        (1.02, 1.15, 1.01, 1.10),  # 1: SH 1.15
        (1.05, 1.08, 0.95, 0.97),  # 2: SL 0.95
        (1.06, 1.25, 1.06, 1.22),  # 3: SH 1.25 (HH)
        (1.18, 1.20, 1.05, 1.08),  # 4: SL 1.05 (HL)
        (1.18, 1.35, 1.18, 1.32),  # 5: SH 1.35 (HH)
        (1.25, 1.28, 1.12, 1.16),  # 6: SL 1.12 (HL)
        (1.20, 1.45, 1.20, 1.42),  # 7
    ]
    candles = generate_synthetic_candles(prices)
    engine = StructureEngine(default_lookback=1, default_tolerance_percent=0.05)
    analysis = engine.analyze_structure(candles, symbol="EUR/USD", timeframe="1h", lookback=1)

    assert analysis.trend == TrendDirection.BULLISH
    assert analysis.trend_strength >= 0.7
    assert analysis.higher_highs_count == 2
    assert analysis.higher_lows_count == 2
    assert analysis.lower_highs_count == 0
    assert analysis.lower_lows_count == 0
    assert analysis.last_swing_high is not None
    assert analysis.last_swing_high.structure_label == StructureLabel.HH
    assert analysis.last_swing_low is not None
    assert analysis.last_swing_low.structure_label == StructureLabel.HL
    assert analysis.key_resistance == 1.35
    assert analysis.key_support == 0.95


def test_structure_engine_downtrend_lower_highs_and_lower_lows():
    """Test market structure labeling and trend classification for a classic Bearish Downtrend (LH + LL)."""
    # Downward zigzag with lookback=1:
    prices = [
        (1.40, 1.42, 1.36, 1.38),  # 0
        (1.38, 1.45, 1.37, 1.40),  # 1: SH 1.45
        (1.28, 1.30, 1.25, 1.28),  # 2: SL 1.25
        (1.28, 1.35, 1.26, 1.33),  # 3: SH 1.35 (LH)
        (1.20, 1.24, 1.15, 1.18),  # 4: SL 1.15 (LL)
        (1.18, 1.25, 1.16, 1.22),  # 5: SH 1.25 (LH)
        (1.08, 1.12, 1.05, 1.08),  # 6: SL 1.05 (LL)
        (1.08, 1.15, 1.06, 1.12),  # 7
    ]
    candles = generate_synthetic_candles(prices)
    engine = StructureEngine(default_lookback=1, default_tolerance_percent=0.05)
    analysis = engine.analyze_structure(candles, symbol="GBP/USD", timeframe="1h", lookback=1)

    assert analysis.trend == TrendDirection.BEARISH
    assert analysis.trend_strength >= 0.7
    assert analysis.lower_highs_count == 2
    assert analysis.lower_lows_count == 2
    assert analysis.higher_highs_count == 0
    assert analysis.higher_lows_count == 0
    assert analysis.last_swing_high.structure_label == StructureLabel.LH
    assert analysis.last_swing_low.structure_label == StructureLabel.LL


def test_structure_engine_double_top_equal_highs_ranging():
    """Test equal highs (Double Top) and ranging market structure."""
    # Two identical highs at 1.2000 and lows at 1.0500 with lookback=1
    prices = [
        (1.10, 1.12, 1.08, 1.11),  # 0
        (1.11, 1.20, 1.09, 1.15),  # 1: SH 1.2000
        (1.08, 1.10, 1.05, 1.08),  # 2: SL 1.0500
        (1.08, 1.20, 1.07, 1.14),  # 3: SH 1.2000 (EH)
        (1.08, 1.10, 1.05, 1.08),  # 4: SL 1.0500 (EL)
        (1.09, 1.12, 1.08, 1.10),  # 5
    ]
    candles = generate_synthetic_candles(prices)
    engine = StructureEngine(default_lookback=1, default_tolerance_percent=0.1)
    analysis = engine.analyze_structure(candles, symbol="USD/JPY", timeframe="1h", lookback=1)

    assert analysis.trend == TrendDirection.RANGING
    assert analysis.equal_highs_count >= 1
    assert analysis.equal_lows_count >= 1


def test_multi_timeframe_alignment():
    """Test multi-timeframe engine alignment evaluation."""
    mtf_engine = MultiTimeframeStructureEngine()

    # 1. Bullish candles
    bullish_prices = [
        (1.00, 1.04, 0.98, 1.02),
        (1.02, 1.15, 1.01, 1.10),
        (1.05, 1.08, 0.95, 0.97),
        (1.06, 1.25, 1.06, 1.22),
        (1.18, 1.20, 1.05, 1.08),
        (1.18, 1.35, 1.18, 1.32),
        (1.25, 1.28, 1.12, 1.16),
        (1.20, 1.45, 1.20, 1.42),
    ]
    # 2. Bearish candles
    bearish_prices = [
        (1.40, 1.42, 1.36, 1.38),
        (1.38, 1.45, 1.37, 1.40),
        (1.28, 1.30, 1.25, 1.28),
        (1.28, 1.35, 1.26, 1.33),
        (1.20, 1.24, 1.15, 1.18),
        (1.18, 1.25, 1.16, 1.22),
        (1.08, 1.12, 1.05, 1.08),
        (1.08, 1.15, 1.06, 1.12),
    ]

    bullish_candles = generate_synthetic_candles(bullish_prices)
    bearish_candles = generate_synthetic_candles(bearish_prices)

    # Test Bullish Alignment across all TFs
    res_all_bull = mtf_engine.analyze_multi_timeframe(
        symbol="EUR/USD",
        timeframe_candles={"4h": bullish_candles, "1h": bullish_candles, "15m": bullish_candles},
        lookback=1,
    )
    assert res_all_bull.alignment == MultiTimeframeAlignment.BULLISH_ALIGNED
    assert res_all_bull.alignment_score >= 0.8
    assert "FULL BULLISH ALIGNMENT" in res_all_bull.summary

    # Test Bearish Alignment across all TFs
    res_all_bear = mtf_engine.analyze_multi_timeframe(
        symbol="EUR/USD",
        timeframe_candles={"4h": bearish_candles, "1h": bearish_candles, "15m": bearish_candles},
        lookback=1,
    )
    assert res_all_bear.alignment == MultiTimeframeAlignment.BEARISH_ALIGNED
    assert res_all_bear.alignment_score >= 0.8
    assert "FULL BEARISH ALIGNMENT" in res_all_bear.summary

    # Test HTF Bullish with LTF Pullback (4h Bullish, 15m Bearish)
    res_pullback = mtf_engine.analyze_multi_timeframe(
        symbol="EUR/USD",
        timeframe_candles={"4h": bullish_candles, "1h": bullish_candles, "15m": bearish_candles},
        lookback=1,
    )
    assert res_pullback.alignment == MultiTimeframeAlignment.HTF_BULLISH_PULLBACK
    assert "pullback" in res_pullback.summary.lower()


def test_structure_events_persistence(test_db_session):
    """Test persisting detected structure events into SQLAlchemy database."""
    engine = StructureEngine(default_lookback=1)
    prices = [
        (1.00, 1.04, 0.98, 1.02),
        (1.02, 1.15, 1.01, 1.10),
        (1.05, 1.08, 0.95, 0.97),
        (1.06, 1.25, 1.06, 1.22),
        (1.18, 1.20, 1.05, 1.08),
        (1.18, 1.35, 1.18, 1.32),
    ]
    candles = generate_synthetic_candles(prices)
    analysis = engine.analyze_structure(candles, symbol="EUR/USD", timeframe="1h", lookback=1)

    inserted_count = engine.persist_structure_events(
        db=test_db_session,
        symbol="EUR/USD",
        timeframe="1h",
        swings=analysis.swing_points,
    )

    assert inserted_count > 0

    # Query back from DB
    records = test_db_session.query(StructureEvent).filter_by(symbol="EUR/USD", timeframe="1h").all()
    assert len(records) == inserted_count

    # Test idempotency (secondary insert should skip existing)
    second_inserted = engine.persist_structure_events(
        db=test_db_session,
        symbol="EUR/USD",
        timeframe="1h",
        swings=analysis.swing_points,
    )
    assert second_inserted == 0
