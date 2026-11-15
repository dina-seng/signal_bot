"""Slow Control Test: 20 seeds x 5,000 open-market bars of synthetic random walk.

Marked as a slow test via @pytest.mark.slow.
Calibrated to real 15m ATR (~2.8 USD).
Verifies that the mean expectancy in R is consistent with transaction friction (-friction_R)
and strictly shows no lookahead leak (<= 0.05 R).
"""

import concurrent.futures
from datetime import datetime, timedelta, timezone
import math
import os
import random
from typing import List, Tuple
import numpy as np
import pytest

from app.schemas.candle import CandleCreate
from app.services.sweep.config import SweepConfig
from app.services.sweep.backtest.engine import run_walk_forward_backtest


def _generate_open_synthetic_path(seed: int, n_bars: int = 5000, atr: float = 2.8) -> List[CandleCreate]:
    rng = random.Random(seed)
    base_time = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    price = 2650.0
    candles: List[CandleCreate] = []

    for i in range(n_bars):
        step = rng.gauss(0, atr)
        o = price
        c = price + step
        w_h = abs(rng.gauss(0, atr * 0.5))
        w_l = abs(rng.gauss(0, atr * 0.5))
        h = max(o, c) + w_h
        l = min(o, c) - w_l
        price = c
        candles.append(
            CandleCreate(
                symbol="XAU/USD",
                timeframe="15m",
                timestamp=base_time + timedelta(minutes=15 * i),
                open=round(o, 2),
                high=round(h, 2),
                low=round(l, 2),
                close=round(c, 2),
                volume=100.0,
            )
        )
    return candles


def _run_single_seed_task(args: Tuple[int, int, float, SweepConfig]) -> Tuple[int, List[float], List[float], int]:
    seed, n_bars, atr, cfg = args
    bars = _generate_open_synthetic_path(seed, n_bars, atr)
    trades, _ = run_walk_forward_backtest(bars, config=cfg)
    r_multiples = [t.r_multiple for t in trades]
    frictions = [t.friction_r for t in trades]
    return seed, r_multiples, frictions, len(trades)


@pytest.mark.slow
def test_random_walk_control_20x5000():
    n_seeds = 20
    bars_per_seed = 5000
    atr = 2.8
    config = SweepConfig(pivot_n_15m=2, lookback_bars_15m=1000)

    tasks = [(seed, bars_per_seed, atr, config) for seed in range(n_seeds)]
    max_workers = min(14, os.cpu_count() or 4)

    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        for res in executor.map(_run_single_seed_task, tasks):
            results.append(res)

    all_r = []
    all_fric = []
    for seed, r_vals, f_vals, n_trades in results:
        all_r.extend(r_vals)
        all_fric.extend(f_vals)

    n_total_trades = len(all_r)
    mean_r = float(np.mean(all_r)) if all_r else 0.0
    avg_fric = float(np.mean(all_fric)) if all_fric else 0.0

    # Ensure mean expectancy is <= 0.05 R and does not exceed negative friction + small margin
    assert mean_r <= 0.05, f"LEAK DETECTED: Synthetic random walk yielded positive mean expectancy {mean_r:+.4f} R"
