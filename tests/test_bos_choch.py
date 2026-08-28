"""Unit tests for Break of Structure (BOS) and Change of Character (CHOCH/MSS) Detector."""

from datetime import datetime, timedelta, timezone
import pytest
from app.schemas.candle import CandleCreate
from app.schemas.liquidity import BOSCHOCHType
from app.schemas.structure import StructureLabel, SwingPoint, SwingType, TrendDirection
from app.services.structure.bos_choch_detector import BOSCHOCHDetector
from app.services.structure.structure_engine import StructureEngine


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


def test_bullish_bos_continuation():
    """Test Bullish Break of Structure (BOS) continuation when price breaks above previous Higher High."""
    # 0: O=1.00, H=1.04, L=0.98, C=1.02
    # 1: O=1.02, H=1.15, L=1.01, C=1.10  -> SH1 = 1.15
    # 2: O=1.05, H=1.08, L=0.95, C=0.97  -> SL1 = 0.95
    # 3: O=0.98, H=1.20, L=0.97, C=1.18  -> Candle body closes at 1.18 (> 1.15 SH1) -> BULLISH_BOS!
    prices = [
        (1.00, 1.04, 0.98, 1.02),  # 0
        (1.02, 1.15, 1.01, 1.10),  # 1: SH1 = 1.15
        (1.05, 1.08, 0.95, 0.97),  # 2: SL1 = 0.95
        (0.98, 1.20, 0.97, 1.18),  # 3: Closes above 1.15 -> Bullish BOS
    ]
    candles = generate_candles(prices)
    detector = BOSCHOCHDetector()

    # Pre-defined labeled swing high at index 1
    sh1 = SwingPoint(
        index=1,
        timestamp=candles[1].timestamp,
        price=1.15,
        swing_type=SwingType.SWING_HIGH,
        structure_label=StructureLabel.HH,
        confirmed=True,
        bar_high=1.15,
        bar_low=1.01,
    )
    sl1 = SwingPoint(
        index=2,
        timestamp=candles[2].timestamp,
        price=0.95,
        swing_type=SwingType.SWING_LOW,
        structure_label=StructureLabel.HL,
        confirmed=True,
        bar_high=1.08,
        bar_low=0.95,
    )

    bos_events, choch_events = detector.detect_bos_and_choch(
        candles=candles,
        swings=[sh1, sl1],
        current_trend=TrendDirection.BULLISH,
    )

    assert len(bos_events) == 1
    assert bos_events[0].event_type == BOSCHOCHType.BULLISH_BOS
    assert bos_events[0].broken_swing_price == 1.15
    assert bos_events[0].breakout_price == 1.18
    assert bos_events[0].index == 3
    assert bos_events[0].displacement_strength > 0.0


def test_bearish_bos_continuation():
    """Test Bearish Break of Structure (BOS) continuation when price breaks below previous Lower Low."""
    # 0: O=1.40, H=1.42, L=1.36, C=1.38
    # 1: O=1.38, H=1.45, L=1.37, C=1.40  -> SH1 = 1.45
    # 2: O=1.28, H=1.30, L=1.25, C=1.28  -> SL1 = 1.25
    # 3: O=1.28, H=1.29, L=1.18, C=1.20  -> Candle closes at 1.20 (< 1.25 SL1) -> BEARISH_BOS!
    prices = [
        (1.40, 1.42, 1.36, 1.38),  # 0
        (1.38, 1.45, 1.37, 1.40),  # 1: SH1 = 1.45
        (1.28, 1.30, 1.25, 1.28),  # 2: SL1 = 1.25
        (1.28, 1.29, 1.18, 1.20),  # 3: Closes below 1.25 -> Bearish BOS
    ]
    candles = generate_candles(prices)
    detector = BOSCHOCHDetector()

    sh1 = SwingPoint(
        index=1,
        timestamp=candles[1].timestamp,
        price=1.45,
        swing_type=SwingType.SWING_HIGH,
        structure_label=StructureLabel.LH,
        confirmed=True,
        bar_high=1.45,
        bar_low=1.37,
    )
    sl1 = SwingPoint(
        index=2,
        timestamp=candles[2].timestamp,
        price=1.25,
        swing_type=SwingType.SWING_LOW,
        structure_label=StructureLabel.LL,
        confirmed=True,
        bar_high=1.30,
        bar_low=1.25,
    )

    bos_events, choch_events = detector.detect_bos_and_choch(
        candles=candles,
        swings=[sh1, sl1],
        current_trend=TrendDirection.BEARISH,
    )

    assert len(bos_events) == 1
    assert bos_events[0].event_type == BOSCHOCHType.BEARISH_BOS
    assert bos_events[0].broken_swing_price == 1.25
    assert bos_events[0].breakout_price == 1.20
    assert bos_events[0].index == 3


def test_bullish_choch_mss_reversal():
    """Test Bullish CHOCH/MSS (Market Structure Shift) when price breaks above a prior Lower High (LH)."""
    # Downward market where price forms a Lower High at 1.30.
    # Then price reverses with strong bullish momentum and closes above 1.30!
    prices = [
        (1.35, 1.36, 1.30, 1.32),  # 0
        (1.28, 1.30, 1.22, 1.24),  # 1: LH = 1.30
        (1.24, 1.25, 1.15, 1.18),  # 2: LL = 1.15
        (1.18, 1.35, 1.18, 1.33),  # 3: Closes at 1.33 > 1.30 LH -> BULLISH_CHOCH!
    ]
    candles = generate_candles(prices)
    detector = BOSCHOCHDetector()

    sh_lh = SwingPoint(
        index=1,
        timestamp=candles[1].timestamp,
        price=1.30,
        swing_type=SwingType.SWING_HIGH,
        structure_label=StructureLabel.LH,
        confirmed=True,
        bar_high=1.30,
        bar_low=1.22,
    )
    sl_ll = SwingPoint(
        index=2,
        timestamp=candles[2].timestamp,
        price=1.15,
        swing_type=SwingType.SWING_LOW,
        structure_label=StructureLabel.LL,
        confirmed=True,
        bar_high=1.25,
        bar_low=1.15,
    )

    bos_events, choch_events = detector.detect_bos_and_choch(
        candles=candles,
        swings=[sh_lh, sl_ll],
        current_trend=TrendDirection.BEARISH,
    )

    assert len(choch_events) == 1
    assert choch_events[0].event_type == BOSCHOCHType.BULLISH_CHOCH
    assert choch_events[0].broken_swing_price == 1.30
    assert choch_events[0].broken_swing_label == StructureLabel.LH
    assert choch_events[0].breakout_price == 1.33


def test_bearish_choch_mss_reversal():
    """Test Bearish CHOCH/MSS (Market Structure Shift) when price breaks below a prior Higher Low (HL)."""
    # Upward market where price forms a Higher Low at 1.10.
    # Then price reverses downwards and closes below 1.10!
    prices = [
        (1.05, 1.12, 1.04, 1.10),  # 0
        (1.10, 1.25, 1.08, 1.22),  # 1: HH = 1.25
        (1.22, 1.23, 1.10, 1.12),  # 2: HL = 1.10
        (1.12, 1.13, 1.02, 1.05),  # 3: Closes at 1.05 < 1.10 HL -> BEARISH_CHOCH!
    ]
    candles = generate_candles(prices)
    detector = BOSCHOCHDetector()

    sh_hh = SwingPoint(
        index=1,
        timestamp=candles[1].timestamp,
        price=1.25,
        swing_type=SwingType.SWING_HIGH,
        structure_label=StructureLabel.HH,
        confirmed=True,
        bar_high=1.25,
        bar_low=1.08,
    )
    sl_hl = SwingPoint(
        index=2,
        timestamp=candles[2].timestamp,
        price=1.10,
        swing_type=SwingType.SWING_LOW,
        structure_label=StructureLabel.HL,
        confirmed=True,
        bar_high=1.23,
        bar_low=1.10,
    )

    bos_events, choch_events = detector.detect_bos_and_choch(
        candles=candles,
        swings=[sh_hh, sl_hl],
        current_trend=TrendDirection.BULLISH,
    )

    assert len(choch_events) == 1
    assert choch_events[0].event_type == BOSCHOCHType.BEARISH_CHOCH
    assert choch_events[0].broken_swing_price == 1.10
    assert choch_events[0].broken_swing_label == StructureLabel.HL
    assert choch_events[0].breakout_price == 1.05
