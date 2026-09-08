"""Unit tests for Technical Indicators (EMA 20/50/200, RSI 14, ATR 14, and Divergences)."""

from datetime import datetime, timedelta, timezone
import pytest
from app.schemas.indicators import DivergenceType
from app.schemas.structure import StructureLabel, SwingPoint, SwingType
from app.services.indicators.ema_calculator import EMACalculator
from app.services.indicators.rsi_calculator import RSICalculator
from app.services.indicators.atr_calculator import ATRCalculator


def test_ema_calculator_basic_series_and_stack():
    """Test EMA calculation series, Bullish Stack and Bearish Stack."""
    calc = EMACalculator()

    # Monotonically increasing prices from 1.00 to 2.00 (100 bars)
    prices = [1.0 + (i * 0.01) for i in range(100)]
    snapshot, fast, mid, slow = calc.calculate_ema_snapshot(
        closes=prices,
        fast_period=10,
        mid_period=20,
        slow_period=50,
    )

    assert fast[-1] is not None
    assert mid[-1] is not None
    assert slow[-1] is not None

    # In monotonic uptrend, Price > Fast > Mid > Slow
    assert prices[-1] > fast[-1] > mid[-1] > slow[-1]
    assert snapshot.ema_trend == "BULLISH_STACK"
    assert snapshot.price_vs_ema200 == "ABOVE"

    # Monotonically decreasing prices
    prices_down = [2.0 - (i * 0.01) for i in range(100)]
    snapshot_down, fast_d, mid_d, slow_d = calc.calculate_ema_snapshot(
        closes=prices_down,
        fast_period=10,
        mid_period=20,
        slow_period=50,
    )
    assert prices_down[-1] < fast_d[-1] < mid_d[-1] < slow_d[-1]
    assert snapshot_down.ema_trend == "BEARISH_STACK"
    assert snapshot_down.price_vs_ema200 == "BELOW"


def test_rsi_calculator_wilders_smoothing():
    """Test Wilder's smoothed RSI 14 calculation."""
    calc = RSICalculator()

    # Monotonic uptrend -> RSI should be high (> 80 / Overbought)
    prices_up = [1.0 + (i * 0.02) for i in range(50)]
    snap_up, rsi_up = calc.calculate_rsi_snapshot(prices_up, period=14)
    assert snap_up.rsi_value is not None
    assert snap_up.rsi_value > 80.0
    assert snap_up.is_overbought is True
    assert snap_up.condition == "OVERBOUGHT"

    # Monotonic downtrend -> RSI should be low (< 20 / Oversold)
    prices_down = [2.0 - (i * 0.02) for i in range(50)]
    snap_down, rsi_down = calc.calculate_rsi_snapshot(prices_down, period=14)
    assert snap_down.rsi_value is not None
    assert snap_down.rsi_value < 20.0
    assert snap_down.is_oversold is True
    assert snap_down.condition == "OVERSOLD"


def test_rsi_divergences_detection():
    """Test Regular Bullish and Regular Bearish RSI Divergence detection."""
    calc = RSICalculator()
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

    # 1. Test Regular Bearish Divergence (Price HH, RSI LH)
    # Swing 1: index 10, Price=1.2000, RSI=75.0
    # Swing 2: index 20, Price=1.2500 (HH), RSI=65.0 (LH)
    swings_bearish = [
        SwingPoint(
            index=10,
            timestamp=base_time + timedelta(hours=10),
            price=1.2000,
            swing_type=SwingType.SWING_HIGH,
            structure_label=StructureLabel.UNCERTAIN,
            confirmed=True,
            bar_high=1.2000,
            bar_low=1.1800,
        ),
        SwingPoint(
            index=20,
            timestamp=base_time + timedelta(hours=20),
            price=1.2500,
            swing_type=SwingType.SWING_HIGH,
            structure_label=StructureLabel.HH,
            confirmed=True,
            bar_high=1.2500,
            bar_low=1.2200,
        ),
    ]
    rsi_mock = [50.0] * 30
    rsi_mock[10] = 75.0
    rsi_mock[20] = 65.0

    divs_bearish = calc.detect_divergences(swings=swings_bearish, rsi_series=rsi_mock)
    assert len(divs_bearish) == 1
    assert divs_bearish[0].divergence_type == DivergenceType.REGULAR_BEARISH
    assert divs_bearish[0].price_end == 1.2500
    assert divs_bearish[0].rsi_end == 65.0

    # 2. Test Regular Bullish Divergence (Price LL, RSI HL)
    # Swing 1: index 10, Price=1.1000, RSI=25.0
    # Swing 2: index 20, Price=1.0500 (LL), RSI=35.0 (HL)
    swings_bullish = [
        SwingPoint(
            index=10,
            timestamp=base_time + timedelta(hours=10),
            price=1.1000,
            swing_type=SwingType.SWING_LOW,
            structure_label=StructureLabel.UNCERTAIN,
            confirmed=True,
            bar_high=1.1200,
            bar_low=1.1000,
        ),
        SwingPoint(
            index=20,
            timestamp=base_time + timedelta(hours=20),
            price=1.0500,
            swing_type=SwingType.SWING_LOW,
            structure_label=StructureLabel.LL,
            confirmed=True,
            bar_high=1.0700,
            bar_low=1.0500,
        ),
    ]
    rsi_mock_bull = [50.0] * 30
    rsi_mock_bull[10] = 25.0
    rsi_mock_bull[20] = 35.0

    divs_bullish = calc.detect_divergences(swings=swings_bullish, rsi_series=rsi_mock_bull)
    assert len(divs_bullish) == 1
    assert divs_bullish[0].divergence_type == DivergenceType.REGULAR_BULLISH
    assert divs_bullish[0].price_end == 1.0500
    assert divs_bullish[0].rsi_end == 35.0


def test_atr_calculator_and_pip_conversion():
    """Test Average True Range (ATR 14) and SL/TP buffer calculation."""
    calc = ATRCalculator()

    # Generate 30 candles with constant 20 pip ranges (0.0020 on EUR/USD)
    highs = [1.1020] * 30
    lows = [1.1000] * 30
    closes = [1.1010] * 30

    snapshot, series = calc.calculate_atr_snapshot(
        highs=highs,
        lows=lows,
        closes=closes,
        symbol="EUR/USD",
        period=14,
    )

    assert snapshot.atr_value is not None
    assert 0.0019 <= snapshot.atr_value <= 0.0021
    assert snapshot.atr_pips == 20.0
    assert snapshot.suggested_sl_distance_pips == 30.0  # 1.5x * 20 = 30 pips
    assert snapshot.suggested_tp_distance_pips == 60.0  # 3.0x * 20 = 60 pips
