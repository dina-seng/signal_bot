"""Window Invariance Unit Tests for Liquidity-Sweep SMC Engine.

Tests:
Result at bar t with the full prefix equals result with only the last L bars
(comparing timestamps, prices, states, and setup_ids).
"""

from datetime import datetime, timedelta, timezone
import random
from typing import List
import pytest

from app.schemas.candle import CandleCreate
from app.services.sweep import (
    SweepConfig,
    evaluate_sweep_market,
)


def _create_bar(ts: datetime, o: float, h: float, l: float, c: float) -> CandleCreate:
    return CandleCreate(
        symbol="XAU/USD",
        timeframe="15m",
        timestamp=ts,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=100.0,
    )


def test_window_invariance_full_prefix_vs_last_l_bars():
    """Verify that at bar t, evaluating with the full prefix up to t yields identical

    outputs to evaluating with strictly the last L bars (lookback window).
    """
    random.seed(123)
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    lookback = 1000
    config = SweepConfig(pivot_n_15m=2, lookback_bars_15m=lookback)

    # Generate 1,800 realistic random walk bars
    total_bars = 1800
    price = 2650.0
    candles: List[CandleCreate] = []

    for i in range(total_bars):
        step = random.uniform(-3.0, 3.0)
        o = price
        c = price + step
        h = max(o, c) + random.uniform(0.5, 4.0)
        l = min(o, c) - random.uniform(0.5, 4.0)
        price = c
        candles.append(_create_bar(base_time + timedelta(minutes=15 * i), round(o, 2), round(h, 2), round(l, 2), round(c, 2)))

    # Test indices t beyond lookback window
    indices_to_test = [1050, 1200, 1450, 1600, 1750]

    for t in indices_to_test:
        as_of = candles[t].timestamp + timedelta(minutes=15)

        # 1. Full prefix up to t (t + 1 bars)
        full_prefix_candles = candles[: t + 1]
        assert len(full_prefix_candles) > lookback
        full_setups = evaluate_sweep_market(full_prefix_candles, as_of=as_of, config=config)

        # 2. Only last L bars up to t (strictly lookback bars)
        window_candles = candles[t + 1 - lookback : t + 1]
        assert len(window_candles) == lookback
        window_setups = evaluate_sweep_market(window_candles, as_of=as_of, config=config)

        # 3. Assert exact equivalence of all outputs
        assert len(full_setups) == len(window_setups), (
            f"Count mismatch at bar {t}: full prefix yielded {len(full_setups)} setups, window yielded {len(window_setups)}"
        )

        for s_full, s_win in zip(full_setups, window_setups):
            assert s_full.setup_id == s_win.setup_id, f"setup_id mismatch: {s_full.setup_id} vs {s_win.setup_id}"
            assert s_full.state == s_win.state, f"state mismatch: {s_full.state} vs {s_win.state}"
            assert s_full.direction == s_win.direction, f"direction mismatch"
            assert s_full.pool_price == s_win.pool_price, f"pool_price mismatch"
            assert s_full.sweep_bar_time == s_win.sweep_bar_time, f"sweep_bar_time mismatch"
            assert s_full.sweep_extreme == s_win.sweep_extreme, f"sweep_extreme mismatch"
            if s_full.plan and s_win.plan:
                assert s_full.plan.entry_price == s_win.plan.entry_price
                assert s_full.plan.stop_loss == s_win.plan.stop_loss
                assert s_full.plan.take_profit_1 == s_win.plan.take_profit_1
                assert s_full.plan.risk_reward_tp1 == s_win.plan.risk_reward_tp1
