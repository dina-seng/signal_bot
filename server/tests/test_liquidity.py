"""Unit tests for Liquidity Sweeps (BSL/SSL), S/R Zones, and Liquidity Service."""

from datetime import datetime, timedelta, timezone
import pytest
from app.models.liquidity import LiquidityEvent
from app.models.structure import StructureEvent
from app.schemas.candle import CandleCreate
from app.schemas.liquidity import (
    BOSCHOCHType,
    LiquidityEventType,
    ZoneType,
)
from app.schemas.structure import StructureLabel, SwingPoint, SwingType, TrendDirection
from app.services.liquidity.sweep_detector import LiquiditySweepDetector
from app.services.liquidity.sr_detector import SupportResistanceDetector
from app.services.liquidity.liquidity_service import LiquidityService


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


def test_buy_side_liquidity_sweep():
    """Test Buy-Side Liquidity (BSL) Sweep / Turtle Soup Reversal (wick above resistance, close below)."""
    # Key swing high at 1.1500
    # Next bar spikes to 1.1540 (sweeps by 40 pips) but closes back down at 1.1480 with a long upper wick
    prices = [
        (1.1000, 1.1200, 1.0900, 1.1100),  # 0
        (1.1100, 1.1500, 1.1000, 1.1450),  # 1: SH = 1.1500
        (1.1450, 1.1460, 1.1300, 1.1350),  # 2
        (1.1350, 1.1540, 1.1320, 1.1480),  # 3: High 1.1540 > 1.1500, but Close 1.1480 <= 1.1500 (Upper wick = 0.0060, range = 0.0220 -> 27%)
    ]
    candles = generate_candles(prices)
    detector = LiquiditySweepDetector(min_wick_ratio=0.20)

    sh = SwingPoint(
        index=1,
        timestamp=candles[1].timestamp,
        price=1.1500,
        swing_type=SwingType.SWING_HIGH,
        structure_label=StructureLabel.HH,
        confirmed=True,
        bar_high=1.1500,
        bar_low=1.1000,
    )

    sweeps = detector.detect_sweeps(candles, swings=[sh], symbol="EUR/USD")

    assert len(sweeps) == 1
    assert sweeps[0].sweep_type == LiquidityEventType.BUY_SIDE_SWEEP
    assert sweeps[0].swept_level == 1.1500
    assert sweeps[0].sweep_extreme == 1.1540
    assert sweeps[0].close_price == 1.1480
    assert sweeps[0].pips_swept == 40.0
    assert sweeps[0].wick_ratio >= 0.20


def test_sell_side_liquidity_sweep():
    """Test Sell-Side Liquidity (SSL) Sweep (wick below support, close above)."""
    # Key swing low at 1.1000
    # Next bar dips to 1.0960 (sweeps by 40 pips) but closes back up at 1.1020 with a long lower wick
    prices = [
        (1.1200, 1.1300, 1.1100, 1.1150),  # 0
        (1.1150, 1.1200, 1.1000, 1.1050),  # 1: SL = 1.1000
        (1.1050, 1.1100, 1.1020, 1.1080),  # 2
        (1.1080, 1.1100, 1.0960, 1.1020),  # 3: Low 1.0960 < 1.1000, but Close 1.1020 >= 1.1000 (Lower wick = 0.0060, range = 0.0140 -> 43%)
    ]
    candles = generate_candles(prices)
    detector = LiquiditySweepDetector(min_wick_ratio=0.20)

    sl = SwingPoint(
        index=1,
        timestamp=candles[1].timestamp,
        price=1.1000,
        swing_type=SwingType.SWING_LOW,
        structure_label=StructureLabel.LL,
        confirmed=True,
        bar_high=1.1200,
        bar_low=1.1000,
    )

    sweeps = detector.detect_sweeps(candles, swings=[sl], symbol="EUR/USD")

    assert len(sweeps) == 1
    assert sweeps[0].sweep_type == LiquidityEventType.SELL_SIDE_SWEEP
    assert sweeps[0].swept_level == 1.1000
    assert sweeps[0].sweep_extreme == 1.0960
    assert sweeps[0].close_price == 1.1020
    assert sweeps[0].pips_swept == 40.0


def test_sr_zones_and_equal_highs_lows():
    """Test Support & Resistance Zone clustering and Equal Highs / Equal Lows pools."""
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    # 2 Swing Highs clustered near 1.2000 (1.2005 and 1.1998) -> Equal Highs pool + Resistance zone
    # 2 Swing Lows clustered near 1.0500 (1.0502 and 1.0496) -> Equal Lows pool + Support zone
    swings = [
        SwingPoint(
            index=2,
            timestamp=base_time + timedelta(hours=2),
            price=1.2005,
            swing_type=SwingType.SWING_HIGH,
            structure_label=StructureLabel.UNCERTAIN,
            confirmed=True,
            bar_high=1.2005,
            bar_low=1.1500,
        ),
        SwingPoint(
            index=5,
            timestamp=base_time + timedelta(hours=5),
            price=1.0502,
            swing_type=SwingType.SWING_LOW,
            structure_label=StructureLabel.UNCERTAIN,
            confirmed=True,
            bar_high=1.1000,
            bar_low=1.0502,
        ),
        SwingPoint(
            index=8,
            timestamp=base_time + timedelta(hours=8),
            price=1.1998,
            swing_type=SwingType.SWING_HIGH,
            structure_label=StructureLabel.EH,
            confirmed=True,
            bar_high=1.1998,
            bar_low=1.1400,
        ),
        SwingPoint(
            index=11,
            timestamp=base_time + timedelta(hours=11),
            price=1.0496,
            swing_type=SwingType.SWING_LOW,
            structure_label=StructureLabel.EL,
            confirmed=True,
            bar_high=1.0900,
            bar_low=1.0496,
        ),
    ]

    detector = SupportResistanceDetector(default_tolerance_percent=0.10)
    sr_zones, pools = detector.detect_sr_zones_and_pools(candles=[], swings=swings)

    assert len(sr_zones) == 2
    assert len(pools) == 2

    # Check Resistance Zone
    res_zone = [z for z in sr_zones if z.zone_type == ZoneType.RESISTANCE][0]
    assert res_zone.touch_count == 2
    assert 1.1990 <= res_zone.center_price <= 1.2010

    # Check Support Zone
    supp_zone = [z for z in sr_zones if z.zone_type == ZoneType.SUPPORT][0]
    assert supp_zone.touch_count == 2
    assert 1.0490 <= supp_zone.center_price <= 1.0510

    # Check Pools
    eq_highs = [p for p in pools if p.pool_type == LiquidityEventType.EQUAL_HIGHS][0]
    assert eq_highs.touch_points == 2
    assert 1.1990 <= eq_highs.price_level <= 1.2010

    eq_lows = [p for p in pools if p.pool_type == LiquidityEventType.EQUAL_LOWS][0]
    assert eq_lows.touch_points == 2
    assert 1.0490 <= eq_lows.price_level <= 1.0510


def test_liquidity_service_full_pipeline_and_db_persistence(test_db_session):
    """Test full LiquidityService analysis and DB persistence to StructureEvent and LiquidityEvent tables."""
    # Synthetic zigzag that triggers a BOS
    prices = [
        (1.00, 1.04, 0.98, 1.02),  # 0
        (1.02, 1.15, 1.01, 1.10),  # 1: SH 1.15
        (1.05, 1.08, 0.95, 0.97),  # 2: SL 0.95
        (1.06, 1.25, 1.06, 1.22),  # 3: SH 1.25 (HH) & Bullish BOS over 1.15!
        (1.18, 1.20, 1.05, 1.08),  # 4: SL 1.05 (HL)
        (1.18, 1.35, 1.18, 1.32),  # 5: SH 1.35 (HH) & Bullish BOS over 1.25!
        (1.25, 1.28, 1.12, 1.16),  # 6: SL 1.12 (HL)
        (1.20, 1.45, 1.20, 1.42),  # 7
    ]
    candles = generate_candles(prices)
    service = LiquidityService()

    analysis = service.analyze_liquidity_and_structure(
        candles=candles,
        symbol="EUR/USD",
        timeframe="1h",
        lookback=1,
    )

    assert analysis.trend == TrendDirection.BULLISH
    assert len(analysis.bos_events) >= 1
    assert "BULLISH" in analysis.market_state

    # Test DB persistence
    n_struct, n_liq = service.persist_events(
        db=test_db_session,
        symbol="EUR/USD",
        timeframe="1h",
        analysis=analysis,
    )

    assert n_struct > 0

    # Query DB tables to verify
    struct_rows = test_db_session.query(StructureEvent).filter_by(symbol="EUR/USD", timeframe="1h").all()
    assert len(struct_rows) > 0
    event_types = [r.event_type for r in struct_rows]
    assert any("BOS" in t or "SWING" in t for t in event_types)
