"""Statistical performance metrics and slice aggregations for Liquidity-Sweep Backtest."""

import math
from typing import Dict, List, Optional, Sequence
import numpy as np

from app.services.sweep.backtest.models import SliceMetrics, TradePosition


def calculate_slice_metrics(
    slice_name: str,
    trades: Sequence[TradePosition],
    n_signals: int = 0,
) -> SliceMetrics:
    """Calculate institutional R-multiple metrics with 1000-resample bootstrap 95% CI.

    Enforces:
    - If n < 30: prints "n/a (n<30)" for stats and withholds edge verdict.
    - If n >= 100 and CI lower bound > 0: has_edge = True, verdict = "EDGE CONFIRMED".
    - Otherwise verdict = "NO EDGE" or "INSUFFICIENT SAMPLE".
    """
    n_executed = len(trades)
    if n_executed == 0:
        return SliceMetrics(
            slice_name=slice_name,
            n_signals=n_signals,
            n_executed=0,
            n_deduped=0,
            win_rate=None,
            expectancy_r=None,
            ci_lower=None,
            ci_upper=None,
            profit_factor=None,
            max_drawdown_r=None,
            avg_friction_r=None,
            has_edge=False,
            verdict="n/a (n=0)",
        )

    # Cluster-deduped trades: trades with distinct setup_id and non-overlapping bars
    deduped_ids = set()
    deduped_count = 0
    for t in trades:
        if t.setup_id not in deduped_ids:
            deduped_ids.add(t.setup_id)
            deduped_count += 1

    r_multiples = [t.r_multiple for t in trades]
    wins = [r for r in r_multiples if r > 0.0]
    losses = [r for r in r_multiples if r <= 0.0]

    win_rate = (len(wins) / n_executed) * 100.0
    expectancy_r = float(np.mean(r_multiples))
    avg_friction_r = float(np.mean([t.friction_r for t in trades]))

    gross_gains = sum(wins)
    gross_losses = abs(sum(losses))
    profit_factor = (gross_gains / gross_losses) if gross_losses > 0.0 else (999.0 if gross_gains > 0 else 0.0)

    # Max Drawdown in R
    cum_r = np.cumsum(r_multiples)
    peaks = np.maximum.accumulate(cum_r)
    drawdowns = peaks - cum_r
    max_dd_r = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    # Bootstrap 95% Confidence Interval (1,000 resamples)
    rng = np.random.default_rng(seed=42)
    boot_means = []
    arr = np.array(r_multiples)
    for _ in range(1000):
        sample = rng.choice(arr, size=len(arr), replace=True)
        boot_means.append(np.mean(sample))

    ci_lower = float(np.percentile(boot_means, 2.5))
    ci_upper = float(np.percentile(boot_means, 97.5))

    # Guardrails: n < 30 => "n/a (n<30)"
    if n_executed < 30:
        verdict = f"n/a (n<30, n={n_executed})"
        has_edge = False
    elif n_executed >= 100 and ci_lower > 0.0:
        verdict = f"EDGE CONFIRMED (n={n_executed}, CI=[{ci_lower:+.2f}, {ci_upper:+.2f}])"
        has_edge = True
    elif n_executed >= 100 and ci_lower <= 0.0:
        verdict = f"NO EDGE (CI includes zero: [{ci_lower:+.2f}, {ci_upper:+.2f}])"
        has_edge = False
    else:
        verdict = f"PROMISING (30<=n<100, n={n_executed}, CI=[{ci_lower:+.2f}, {ci_upper:+.2f}])"
        has_edge = False

    return SliceMetrics(
        slice_name=slice_name,
        n_signals=n_signals,
        n_executed=n_executed,
        n_deduped=deduped_count,
        win_rate=round(win_rate, 2),
        expectancy_r=round(expectancy_r, 3),
        ci_lower=round(ci_lower, 3),
        ci_upper=round(ci_upper, 3),
        profit_factor=round(profit_factor, 2),
        max_drawdown_r=round(max_dd_r, 2),
        avg_friction_r=round(avg_friction_r, 3),
        has_edge=has_edge,
        verdict=verdict,
    )


def compute_monthly_equity(trades: Sequence[TradePosition]) -> Dict[str, float]:
    """Compute cumulative R return aggregated by month."""
    monthly: Dict[str, float] = {}
    for t in trades:
        m_key = t.entry_time.strftime("%Y-%m")
        monthly[m_key] = monthly.get(m_key, 0.0) + t.r_multiple
    return {k: round(v, 2) for k, v in sorted(monthly.items())}
