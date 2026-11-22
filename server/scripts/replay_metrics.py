"""Canonical metric definitions for SMC Baseline v1.

A single source of truth for R statistics and cluster-robust inference, shared
by the replay and portfolio producers (contract §3.1 / §3.2, BT-020/BT-025).
No strategy logic lives here.
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Any, Dict, Optional, Sequence, Tuple

SEED = 12345
RESAMPLES = 2000


def compute_core_metrics(
    values: Sequence[float],
    order: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Compute the canonical R statistics.

    ``order`` supplies the drawdown ordering key (the contract uses exit time).
    Breakeven (r == 0) is counted as a loss; profit factor uses gross wins over
    absolute gross losses, with inf/0 handling for degenerate samples.
    """
    rs = [float(v) for v in values]
    n = len(rs)
    if n == 0:
        return {
            "n": 0, "win_count": 0, "loss_count": 0, "breakeven_count": 0,
            "win_rate": None, "avg_r": None, "median_r": None,
            "profit_factor": None, "total_r": None, "max_drawdown_r": None,
        }

    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    breakeven = [r for r in rs if r == 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    if gross_loss > 0:
        pf = gross_win / gross_loss
    else:
        pf = math.inf if gross_win > 0 else 0.0

    keys = list(order) if order is not None else list(range(n))
    paired = sorted(zip(keys, rs), key=lambda kv: kv[0])
    equity = peak = max_dd = 0.0
    for _, r in paired:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    return {
        "n": n,
        "win_count": len(wins),
        "loss_count": len(losses),
        "breakeven_count": len(breakeven),
        "win_rate": 100.0 * len(wins) / n,
        "avg_r": sum(rs) / n,
        "median_r": float(statistics.median(rs)),
        "profit_factor": pf,
        "total_r": sum(rs),
        "max_drawdown_r": max_dd,
    }


def _percentile_ci(means: Sequence[float], resamples: int) -> Tuple[float, float]:
    ordered = sorted(means)
    lo = ordered[int(0.025 * resamples)]
    hi = ordered[int(0.975 * resamples) - 1]
    return (lo, hi)


def iid_bootstrap_ci(
    values: Sequence[float], resamples: int = RESAMPLES, seed: int = SEED
) -> Tuple[float, float]:
    """Deterministic IID percentile bootstrap for the mean (legacy control)."""
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(values)
    means = [sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples)]
    return _percentile_ci(means, resamples)


def day_cluster_bootstrap_ci(
    values: Sequence[float],
    clusters: Sequence[Any],
    resamples: int = RESAMPLES,
    seed: int = SEED,
) -> Tuple[float, float]:
    """Deterministic percentile bootstrap resampling whole UTC-day clusters.

    Resampling clusters (rather than individual trades) preserves the
    intra-day correlation the project's own freeze measures at VIF ~= 5.1.
    """
    if not values or len(values) != len(clusters):
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    by_cluster: Dict[Any, list] = {}
    for value, cluster in zip(values, clusters):
        by_cluster.setdefault(cluster, []).append(float(value))
    keys = list(by_cluster)
    means = []
    for _ in range(resamples):
        picked = [keys[rng.randrange(len(keys))] for _ in range(len(keys))]
        sample = [v for key in picked for v in by_cluster[key]]
        means.append(sum(sample) / len(sample))
    return _percentile_ci(means, resamples)
