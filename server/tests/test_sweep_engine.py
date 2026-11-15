"""Comprehensive unit tests for Liquidity-Sweep SMC engine.

Tests:
1. Synthetic concept fixtures:
   - clean sweep
   - fake-out breakout
   - equal-highs sweep
   - late rejection (4 bars)
   - no MSS
   - expired zone
   - invalidation by extreme breach
   - RR too low
2. Determinism test.
3. PREFIX INVARIANCE test: for 300 bar indices t, outputs at t are identical
   when candles after t are removed or replaced with random garbage.
"""

from datetime import datetime, timedelta, timezone
import random
from typing import List
import pytest

from app.schemas.candle import CandleCreate
from app.services.sweep import (
    SweepConfig,
    SweepSetup,
    SetupState,
    evaluate_sweep_market,
    detect_pivots,
    calculate_atr,
    identify_liquidity_pools,
    find_valid_sweep,
)
from app.services.sweep.detector import find_mss_and_displacement, construct_entry_zone, calculate_sl_tp_and_rr
from app.services.sweep.pools import LiquidityPool


def _create_bar(ts: datetime, o: float, h: float, l: float, c: float, v: float = 100.0) -> CandleCreate:
    return CandleCreate(
        symbol="XAU/USD",
        timeframe="15m",
        timestamp=ts,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=v,
    )


def _warmup_bars(base_time: datetime, count: int = 15, price: float = 2600.0) -> List[CandleCreate]:
    return [
        _create_bar(base_time + timedelta(minutes=15 * i), price, price + 1.0, price - 1.0, price)
        for i in range(count)
    ]


# ==============================================================================
# 1. Hand-Built Synthetic Concept Fixtures
# ==============================================================================

def test_clean_bearish_sweep_fixture():
    """Verify clean sweep of a swing high with rejection, MSS, FVG, and RR >= 1.5 produces CONFIRMED setup."""
    base = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    config = SweepConfig(pivot_n_15m=2, min_rr_tp1=1.5)
    bars = _warmup_bars(base, 15, 2600.0)
    t = base + timedelta(minutes=15 * 15)

    # Bar 15: Opposing low support target at 2550
    bars.append(_create_bar(t + timedelta(minutes=15 * 0), 2600, 2602, 2550, 2580))
    bars.append(_create_bar(t + timedelta(minutes=15 * 1), 2580, 2600, 2575, 2595))
    bars.append(_create_bar(t + timedelta(minutes=15 * 2), 2595, 2615, 2590, 2610))  # Low 2550 confirmed
    # Build Swing High at bar 19 (high 2650)
    bars.append(_create_bar(t + timedelta(minutes=15 * 3), 2610, 2630, 2608, 2625))
    bars.append(_create_bar(t + timedelta(minutes=15 * 4), 2625, 2650, 2620, 2645))  # Swing high peak 2650
    bars.append(_create_bar(t + timedelta(minutes=15 * 5), 2645, 2646, 2628, 2630))
    bars.append(_create_bar(t + timedelta(minutes=15 * 6), 2630, 2632, 2618, 2620))  # Confirmed
    # Pullback establishing swing low at bar 22 (low 2615)
    bars.append(_create_bar(t + timedelta(minutes=15 * 7), 2620, 2625, 2615, 2622))
    bars.append(_create_bar(t + timedelta(minutes=15 * 8), 2622, 2635, 2620, 2630))
    bars.append(_create_bar(t + timedelta(minutes=15 * 9), 2630, 2642, 2628, 2640))  # Low 2615 confirmed
    # Sweep Bar (bar 25): wicks to 2654 (> 2650 + 0.05*ATR), closes at 2646 (< 2650)
    bars.append(_create_bar(t + timedelta(minutes=15 * 10), 2640, 2654, 2638, 2646))
    # Rejection confirmed
    bars.append(_create_bar(t + timedelta(minutes=15 * 11), 2646, 2648, 2638, 2640))
    # Displacement candle down: breaks swing low 2615, closes at 2605
    bars.append(_create_bar(t + timedelta(minutes=15 * 12), 2640, 2641, 2604, 2605))
    # Consolidation leaving FVG
    bars.append(_create_bar(t + timedelta(minutes=15 * 13), 2605, 2615, 2602, 2610))

    setups = evaluate_sweep_market(bars, config=config)
    confirmed = [s for s in setups if s.state == SetupState.CONFIRMED]
    assert len(confirmed) >= 1
    s = confirmed[0]
    assert s.direction == "SHORT"
    assert s.grade in ("A", "B", "C")
    assert s.plan is not None
    assert s.plan.stop_loss > 2654.0
    assert s.plan.take_profit_1 <= 2620.0
    assert s.plan.risk_reward_tp1 >= 1.5


def test_fake_out_breakout_fixture():
    """Verify that when price keeps closing beyond the level, it is a breakout, not a sweep."""
    base = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    config = SweepConfig(pivot_n_15m=2)
    bars = _warmup_bars(base, 15, 2600.0)
    t = base + timedelta(minutes=15 * 15)

    bars.append(_create_bar(t + timedelta(minutes=15 * 0), 2600, 2610, 2595, 2605))
    bars.append(_create_bar(t + timedelta(minutes=15 * 1), 2605, 2620, 2600, 2615))
    bars.append(_create_bar(t + timedelta(minutes=15 * 2), 2615, 2650, 2610, 2645))  # Peak 2650
    bars.append(_create_bar(t + timedelta(minutes=15 * 3), 2645, 2646, 2628, 2630))
    bars.append(_create_bar(t + timedelta(minutes=15 * 4), 2630, 2632, 2618, 2620))  # Confirmed
    # Breakout: closes above 2650 on all bars
    bars.append(_create_bar(t + timedelta(minutes=15 * 5), 2620, 2655, 2620, 2652))
    bars.append(_create_bar(t + timedelta(minutes=15 * 6), 2652, 2660, 2651, 2658))
    bars.append(_create_bar(t + timedelta(minutes=15 * 7), 2658, 2665, 2655, 2662))

    atr_vals = calculate_atr(bars)
    pools = identify_liquidity_pools(bars, (), atr_vals, config)
    sweep = find_valid_sweep(20, bars, pools, atr_vals[20], config)
    assert sweep is None  # Breakout, NOT a sweep


def test_equal_highs_sweep_fixture():
    """Verify equal highs detection (>=2 pivots within 0.10*ATR) and valid sweep of equal highs pool."""
    base = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    config = SweepConfig(pivot_n_15m=2)
    bars = _warmup_bars(base, 15, 2600.0)
    t = base + timedelta(minutes=15 * 15)

    # First swing high at 2650.0
    bars.append(_create_bar(t + timedelta(minutes=15 * 0), 2600, 2615, 2598, 2610))
    bars.append(_create_bar(t + timedelta(minutes=15 * 1), 2610, 2650.0, 2608, 2645))  # High 1: 2650.0
    bars.append(_create_bar(t + timedelta(minutes=15 * 2), 2645, 2646, 2635, 2638))
    bars.append(_create_bar(t + timedelta(minutes=15 * 3), 2638, 2640, 2630, 2632))  # Confirmed High 1
    # Pullback and second swing high at 2650.1 (within 0.10*ATR)
    bars.append(_create_bar(t + timedelta(minutes=15 * 4), 2632, 2640, 2628, 2635))
    bars.append(_create_bar(t + timedelta(minutes=15 * 5), 2635, 2650.1, 2630, 2645))  # High 2: 2650.1
    bars.append(_create_bar(t + timedelta(minutes=15 * 6), 2645, 2646, 2632, 2635))
    bars.append(_create_bar(t + timedelta(minutes=15 * 7), 2635, 2638, 2625, 2628))  # Confirmed High 2
    # Sweep Bar: wicks to 2654, closes at 2646
    bars.append(_create_bar(t + timedelta(minutes=15 * 8), 2628, 2654.0, 2625, 2646.0))

    atr_vals = calculate_atr(bars)
    pools = identify_liquidity_pools(bars, (), atr_vals, config)
    eq_pools = [p for p in pools if p.pool_type == "EQUAL_HIGHS"]
    assert len(eq_pools) >= 1

    sweep = find_valid_sweep(23, bars, pools, atr_vals[23], config)
    assert sweep is not None
    assert sweep.pool.pool_type == "EQUAL_HIGHS"


def test_late_rejection_after_4_bars_fails():
    """Verify that if a close returns inside the level only on bar 4 (> max_rejection_bars 3), it fails."""
    base = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    config = SweepConfig(pivot_n_15m=2, max_rejection_bars=3)
    bars = _warmup_bars(base, 15, 2600.0)
    t = base + timedelta(minutes=15 * 15)

    bars.append(_create_bar(t + timedelta(minutes=15 * 0), 2600, 2610, 2595, 2605))
    bars.append(_create_bar(t + timedelta(minutes=15 * 1), 2605, 2620, 2600, 2615))
    bars.append(_create_bar(t + timedelta(minutes=15 * 2), 2615, 2650, 2610, 2645))  # Swing High 2650
    bars.append(_create_bar(t + timedelta(minutes=15 * 3), 2645, 2646, 2628, 2630))
    bars.append(_create_bar(t + timedelta(minutes=15 * 4), 2630, 2632, 2618, 2620))  # Confirmed
    # Sweep at bar 20: wicks to 2655, closes at 2652 (above 2650)
    bars.append(_create_bar(t + timedelta(minutes=15 * 5), 2620, 2655, 2620, 2652))
    # Bar 21: closes at 2653 (above 2650)
    bars.append(_create_bar(t + timedelta(minutes=15 * 6), 2652, 2656, 2651, 2653))
    # Bar 22: closes at 2651 (above 2650)
    bars.append(_create_bar(t + timedelta(minutes=15 * 7), 2653, 2655, 2650.5, 2651))
    # Bar 23: closes at 2648 (inside level on bar 4) -> Too late!
    bars.append(_create_bar(t + timedelta(minutes=15 * 8), 2651, 2652, 2645, 2648))

    atr_vals = calculate_atr(bars)
    pools = identify_liquidity_pools(bars, (), atr_vals, config)
    sweep = find_valid_sweep(20, bars, pools, atr_vals[20], config)
    assert sweep is None  # Late rejection rejected


def test_no_mss_within_12_bars_yields_no_setup():
    """Verify that if no displacement/MSS occurs within 12 bars after sweep, setup transitions to NO_SETUP."""
    base = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    config = SweepConfig(pivot_n_15m=2, max_mss_bars=12)
    bars = _warmup_bars(base, 15, 2600.0)
    t = base + timedelta(minutes=15 * 15)

    bars.append(_create_bar(t + timedelta(minutes=15 * 0), 2600, 2610, 2590, 2605))
    bars.append(_create_bar(t + timedelta(minutes=15 * 1), 2605, 2620, 2600, 2615))
    bars.append(_create_bar(t + timedelta(minutes=15 * 2), 2615, 2650, 2610, 2645))  # Swing High 2650
    bars.append(_create_bar(t + timedelta(minutes=15 * 3), 2645, 2646, 2628, 2630))
    bars.append(_create_bar(t + timedelta(minutes=15 * 4), 2630, 2632, 2618, 2620))  # Confirmed
    bars.append(_create_bar(t + timedelta(minutes=15 * 5), 2620, 2630, 2615, 2625))
    # Sweep at bar 21
    bars.append(_create_bar(t + timedelta(minutes=15 * 6), 2625, 2655, 2620, 2645))
    # Add 15 choppy small candles
    for i in range(7, 23):
        bars.append(_create_bar(t + timedelta(minutes=15 * i), 2645, 2647, 2643, 2645))

    setups = evaluate_sweep_market(bars, config=config)
    no_setup = [s for s in setups if s.state == SetupState.NO_SETUP]
    assert len(no_setup) >= 1
    assert "MSS confirmation not observed" in (no_setup[0].no_setup_reason or "")


def test_expired_zone_fixture():
    """Verify that an entry zone expires after 16 bars without fill, transitioning setup to INVALIDATED."""
    base = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    config = SweepConfig(pivot_n_15m=2, zone_expiry_bars=16)
    bars = _warmup_bars(base, 15, 2600.0)
    t = base + timedelta(minutes=15 * 15)

    # Establish opposing low
    bars.append(_create_bar(t + timedelta(minutes=15 * 0), 2600, 2602, 2550, 2580))
    bars.append(_create_bar(t + timedelta(minutes=15 * 1), 2580, 2600, 2575, 2595))
    bars.append(_create_bar(t + timedelta(minutes=15 * 2), 2595, 2615, 2590, 2610))
    # Swing high at 2650
    bars.append(_create_bar(t + timedelta(minutes=15 * 3), 2610, 2630, 2608, 2625))
    bars.append(_create_bar(t + timedelta(minutes=15 * 4), 2625, 2650, 2620, 2645))
    bars.append(_create_bar(t + timedelta(minutes=15 * 5), 2645, 2646, 2628, 2630))
    bars.append(_create_bar(t + timedelta(minutes=15 * 6), 2630, 2632, 2618, 2620))
    # Pullback low at 2615
    bars.append(_create_bar(t + timedelta(minutes=15 * 7), 2620, 2625, 2615, 2622))
    bars.append(_create_bar(t + timedelta(minutes=15 * 8), 2622, 2635, 2620, 2630))
    bars.append(_create_bar(t + timedelta(minutes=15 * 9), 2630, 2642, 2628, 2640))
    # Sweep at bar 25
    bars.append(_create_bar(t + timedelta(minutes=15 * 10), 2640, 2654, 2638, 2646))
    bars.append(_create_bar(t + timedelta(minutes=15 * 11), 2646, 2648, 2638, 2640))
    # Displacement candle down
    bars.append(_create_bar(t + timedelta(minutes=15 * 12), 2640, 2641, 2604, 2605))
    bars.append(_create_bar(t + timedelta(minutes=15 * 13), 2605, 2615, 2602, 2610))
    # Add 18 bars without returning to entry zone (keeping price low at 2600)
    for i in range(14, 33):
        bars.append(_create_bar(t + timedelta(minutes=15 * i), 2600, 2605, 2595, 2600))

    setups = evaluate_sweep_market(bars, config=config)
    expired = [s for s in setups if s.state == SetupState.INVALIDATED and "expired" in (s.invalidation_reason or "")]
    assert len(expired) >= 1


def test_invalidation_when_close_beyond_sweep_extreme():
    """Verify that if a subsequent candle closes beyond the sweep extreme, the setup is INVALIDATED."""
    base = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    config = SweepConfig(pivot_n_15m=2)
    bars = _warmup_bars(base, 15, 2600.0)
    t = base + timedelta(minutes=15 * 15)

    bars.append(_create_bar(t + timedelta(minutes=15 * 0), 2600, 2610, 2590, 2605))
    bars.append(_create_bar(t + timedelta(minutes=15 * 1), 2605, 2620, 2600, 2615))
    bars.append(_create_bar(t + timedelta(minutes=15 * 2), 2615, 2650, 2610, 2645))  # Swing High 2650
    bars.append(_create_bar(t + timedelta(minutes=15 * 3), 2645, 2646, 2628, 2630))
    bars.append(_create_bar(t + timedelta(minutes=15 * 4), 2630, 2632, 2618, 2620))
    # Sweep at bar 20 (sweep extreme = 2655.0)
    bars.append(_create_bar(t + timedelta(minutes=15 * 5), 2620, 2655, 2618, 2645))
    # Bar 21: Blows past 2655 and closes at 2660 -> INVALIDATION
    bars.append(_create_bar(t + timedelta(minutes=15 * 6), 2645, 2665, 2644, 2660))

    setups = evaluate_sweep_market(bars, config=config)
    invalidated = [s for s in setups if s.state == SetupState.INVALIDATED]
    assert len(invalidated) >= 1
    assert "Price closed beyond sweep extreme" in (invalidated[0].invalidation_reason or "")


def test_rr_too_low_yields_no_setup():
    """Verify that when Risk:Reward to TP1 is < 1.5, setup is classified as NO_SETUP."""
    base = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    config = SweepConfig(pivot_n_15m=2, min_rr_tp1=1.5)
    bars = _warmup_bars(base, 15, 2635.0)
    t = base + timedelta(minutes=15 * 15)

    # Opposing low is tight at 2640.0
    bars.append(_create_bar(t + timedelta(minutes=15 * 0), 2642, 2644, 2640, 2642))  # Low 2640
    bars.append(_create_bar(t + timedelta(minutes=15 * 1), 2642, 2645, 2641, 2644))
    bars.append(_create_bar(t + timedelta(minutes=15 * 2), 2644, 2650, 2642, 2648))  # Swing High 2650
    bars.append(_create_bar(t + timedelta(minutes=15 * 3), 2648, 2649, 2643, 2645))
    bars.append(_create_bar(t + timedelta(minutes=15 * 4), 2645, 2646, 2642, 2644))
    # Pullback low at 2641.0
    bars.append(_create_bar(t + timedelta(minutes=15 * 5), 2644, 2646, 2641, 2643))
    bars.append(_create_bar(t + timedelta(minutes=15 * 6), 2643, 2648, 2642, 2646))
    bars.append(_create_bar(t + timedelta(minutes=15 * 7), 2646, 2649, 2644, 2647))
    # Sweep at bar 23 to 2660 (extreme 2660, stop 2662)
    bars.append(_create_bar(t + timedelta(minutes=15 * 8), 2647, 2660, 2646, 2654))
    # Rejection bar 24 with high at 2656, low 2650
    bars.append(_create_bar(t + timedelta(minutes=15 * 9), 2654, 2656, 2650, 2652))
    # Displacement candle down to 2630 (breaking 2641)
    bars.append(_create_bar(t + timedelta(minutes=15 * 10), 2652, 2653, 2629, 2630))
    # Bar 26 with high 2644 -> FVG formed between 2650 and 2644, midpoint = 2647 (in premium: 2647 >= mid 2645)
    bars.append(_create_bar(t + timedelta(minutes=15 * 11), 2630, 2644, 2628, 2632))

    setups = evaluate_sweep_market(bars, config=config)
    no_setup = [s for s in setups if s.state == SetupState.NO_SETUP]
    assert len(no_setup) >= 1
    assert any("Risk:Reward" in (s.no_setup_reason or "") for s in no_setup)


# ==============================================================================
# 2. Determinism Test
# ==============================================================================

def test_engine_determinism():
    """Verify same input => identical setup_id, states, prices, and checklist fields."""
    base_time = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    config = SweepConfig()
    bars = [
        _create_bar(base_time + timedelta(minutes=15 * i), 2600 + (i % 10), 2615 + (i % 10), 2595 + (i % 10), 2605 + (i % 10))
        for i in range(80)
    ]

    run1 = evaluate_sweep_market(bars, config=config)
    run2 = evaluate_sweep_market(bars, config=config)

    assert len(run1) == len(run2)
    for s1, s2 in zip(run1, run2):
        assert s1.setup_id == s2.setup_id
        assert s1.state == s2.state
        assert s1.direction == s2.direction
        assert s1.pool_price == s2.pool_price
        assert s1.checklist == s2.checklist


# ==============================================================================
# 3. PREFIX INVARIANCE TEST (Strict No Lookahead)
# ==============================================================================

def test_prefix_invariance_300_indices():
    """Prefix Invariance: for 300 random bar indices t, outputs at t are identical

    when candles after t are removed or replaced with random garbage.
    Fail with the first differing field.
    """
    random.seed(42)
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    config = SweepConfig(pivot_n_15m=2)

    # Generate 500 realistic random walk bars
    total_bars = 500
    price = 2600.0
    candles: List[CandleCreate] = []

    for i in range(total_bars):
        step = random.uniform(-3.0, 3.0)
        o = price
        c = price + step
        h = max(o, c) + random.uniform(0.5, 4.0)
        l = min(o, c) - random.uniform(0.5, 4.0)
        price = c
        candles.append(_create_bar(base_time + timedelta(minutes=15 * i), o, h, l, c))

    # Test 300 random indices t in [50, 450]
    indices_to_test = [random.randint(50, total_bars - 20) for _ in range(300)]

    for t in indices_to_test:
        as_of = candles[t].timestamp + timedelta(minutes=15)

        # Baseline: run with all 500 candles passing as_of
        baseline_setups = evaluate_sweep_market(candles, as_of=as_of, config=config)

        # Truncated: slice candles strictly up to t (candles after t removed)
        truncated_candles = candles[: t + 1]
        truncated_setups = evaluate_sweep_market(truncated_candles, as_of=as_of, config=config)

        # Garbage: replace candles after t with random garbage numbers
        garbage_candles = list(candles[: t + 1])
        garbage_price = 50000.0
        for j in range(t + 1, total_bars):
            garbage_price += random.uniform(-100.0, 100.0)
            garbage_candles.append(
                _create_bar(
                    base_time + timedelta(minutes=15 * j),
                    garbage_price,
                    garbage_price + 50.0,
                    garbage_price - 50.0,
                    garbage_price + 10.0,
                )
            )
        garbage_setups = evaluate_sweep_market(garbage_candles, as_of=as_of, config=config)

        # Verify exact equality between baseline, truncated, and garbage
        assert len(baseline_setups) == len(truncated_setups), (
            f"Prefix invariance failed at index {t}: baseline count {len(baseline_setups)} != truncated count {len(truncated_setups)}"
        )
        assert len(baseline_setups) == len(garbage_setups), (
            f"Prefix invariance failed at index {t}: baseline count {len(baseline_setups)} != garbage count {len(garbage_setups)}"
        )

        for s_base, s_trunc, s_garb in zip(baseline_setups, truncated_setups, garbage_setups):
            assert s_base.setup_id == s_trunc.setup_id == s_garb.setup_id, (
                f"Prefix invariance diff at bar {t}: setup_id mismatch {s_base.setup_id} vs {s_trunc.setup_id}"
            )
            assert s_base.state == s_trunc.state == s_garb.state, (
                f"Prefix invariance diff at bar {t}: state mismatch {s_base.state} vs {s_trunc.state}"
            )
            assert s_base.direction == s_trunc.direction == s_garb.direction, (
                f"Prefix invariance diff at bar {t}: direction mismatch"
            )
            assert s_base.pool_price == s_trunc.pool_price == s_garb.pool_price, (
                f"Prefix invariance diff at bar {t}: pool_price mismatch"
            )
            assert s_base.checklist == s_trunc.checklist == s_garb.checklist, (
                f"Prefix invariance diff at bar {t}: checklist mismatch"
            )
