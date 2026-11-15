"""Time-split management and pre-registered hyperparameter tuning grid."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from itertools import product
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.schemas.candle import CandleCreate
from app.services.sweep.config import SweepConfig
from app.services.sweep.backtest.baseline import run_random_baseline
from app.services.sweep.backtest.engine import run_walk_forward_backtest
from app.services.sweep.backtest.metrics import calculate_slice_metrics, compute_monthly_equity
from app.services.sweep.backtest.models import BacktestReport, SliceMetrics, TradePosition


@dataclass
class SplitData:
    name: str
    candles_15m: List[CandleCreate]
    start_time: datetime
    end_time: datetime


def make_purged_time_splits(
    candles_15m: Sequence[CandleCreate],
    train_pct: float = 0.60,
    val_pct: float = 0.20,
    test_pct: float = 0.20,
    purge_bars: int = 16,
    embargo_bars: int = 8,
) -> Tuple[SplitData, SplitData, SplitData]:
    """Create 60% Train / 20% Validation / 20% Test splits with purged & embargo boundary buffers.

    Rules (ml4t-purging-embargo):
    - Purge boundary: 16 bars before split boundary (max entry zone expiry).
    - Embargo buffer: 8 bars after split boundary.
    - Test split is evaluated strictly once.
    """
    n = len(candles_15m)
    train_end_raw = int(n * train_pct)
    val_end_raw = int(n * (train_pct + val_pct))

    # Train: [0 .. train_end_raw - purge_bars]
    train_end = max(50, train_end_raw - purge_bars)
    train_candles = list(candles_15m[:train_end])

    # Validation: [train_end_raw + embargo_bars .. val_end_raw - purge_bars]
    val_start = train_end_raw + embargo_bars
    val_end = max(val_start + 50, val_end_raw - purge_bars)
    val_candles = list(candles_15m[val_start:val_end])

    # Test: [val_end_raw + embargo_bars .. n]
    test_start = val_end_raw + embargo_bars
    test_candles = list(candles_15m[test_start:])

    train_data = SplitData(
        name="train",
        candles_15m=train_candles,
        start_time=train_candles[0].timestamp,
        end_time=train_candles[-1].timestamp,
    )
    val_data = SplitData(
        name="validation",
        candles_15m=val_candles,
        start_time=val_candles[0].timestamp,
        end_time=val_candles[-1].timestamp,
    )
    test_data = SplitData(
        name="test",
        candles_15m=test_candles,
        start_time=test_candles[0].timestamp,
        end_time=test_candles[-1].timestamp,
    )

    return train_data, val_data, test_data


def generate_preregistered_grid() -> List[SweepConfig]:
    """Pre-registered tuning grid of at most 24 parameter combinations.

    Grid:
    - pivot_n_15m in {2, 3, 4} (3 values)
    - max_rejection_bars in {1, 2, 3} (3 values)
    - min_rr_tp1 in {1.5, 2.0} (2 values)
    Total = 3 * 3 * 2 = 18 combinations (<= 24).
    All other parameters remain frozen at default values.
    """
    pivot_ns = [2, 3, 4]
    rejection_bars = [1, 2, 3]
    min_rrs = [1.5, 2.0]

    grid: List[SweepConfig] = []
    base_config = SweepConfig()

    for p_n, r_bar, m_rr in product(pivot_ns, rejection_bars, min_rrs):
        cfg = replace(
            base_config,
            pivot_n_15m=p_n,
            max_rejection_bars=r_bar,
            min_rr_tp1=m_rr,
        )
        grid.append(cfg)

    return grid


def compile_split_report(
    split_name: str,
    candles_15m: Sequence[CandleCreate],
    config: SweepConfig,
) -> BacktestReport:
    """Run walk-forward simulation on a split and compile comprehensive institutional report."""
    executed_trades, candidates = run_walk_forward_backtest(
        candles_15m=candles_15m,
        config=config,
    )

    overall = calculate_slice_metrics("overall", executed_trades, n_signals=len(candidates))

    # Grade breakdown
    grade_breakdown: Dict[str, SliceMetrics] = {}
    for grade in ["A", "B", "C"]:
        t_grade = [t for t in executed_trades if t.grade == grade]
        c_grade = [c for c in candidates if c.grade == grade]
        grade_breakdown[f"Grade_{grade}"] = calculate_slice_metrics(f"Grade_{grade}", t_grade, n_signals=len(c_grade))

    # Session breakdown
    session_breakdown: Dict[str, SliceMetrics] = {}
    for sess in ["Asia", "London", "NY", "Other"]:
        t_sess = [t for t in executed_trades if t.session == sess]
        session_breakdown[sess] = calculate_slice_metrics(sess, t_sess, n_signals=len(t_sess))

    # HTF Alignment breakdown
    htf_aligned_trades = [t for t in executed_trades if t.htf_aligned]
    htf_counter_trades = [t for t in executed_trades if not t.htf_aligned]
    htf_alignment_breakdown = {
        "HTF_Aligned": calculate_slice_metrics("HTF_Aligned", htf_aligned_trades, len(htf_aligned_trades)),
        "Counter_Trend": calculate_slice_metrics("Counter_Trend", htf_counter_trades, len(htf_counter_trades)),
    }

    # Pool Type breakdown
    pool_type_breakdown: Dict[str, SliceMetrics] = {}
    pool_types = sorted({t.pool_type for t in executed_trades} | {c.pool_type for c in candidates})
    for p_type in pool_types:
        t_p = [t for t in executed_trades if t.pool_type == p_type]
        c_p = [c for c in candidates if c.pool_type == p_type]
        pool_type_breakdown[p_type] = calculate_slice_metrics(p_type, t_p, n_signals=len(c_p))

    # Day of Week breakdown
    day_breakdown: Dict[str, SliceMetrics] = {}
    for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
        t_d = [t for t in executed_trades if t.day_of_week == day]
        day_breakdown[day] = calculate_slice_metrics(day, t_d, n_signals=len(t_d))

    # Monthly Equity
    monthly_equity = compute_monthly_equity(executed_trades)

    # Random Baseline
    baseline_metrics = run_random_baseline(executed_trades, candles_15m)

    return BacktestReport(
        split_name=split_name,
        start_date=candles_15m[0].timestamp,
        end_date=candles_15m[-1].timestamp,
        total_bars=len(candles_15m),
        overall_metrics=overall,
        grade_breakdown=grade_breakdown,
        session_breakdown=session_breakdown,
        htf_alignment_breakdown=htf_alignment_breakdown,
        pool_type_breakdown=pool_type_breakdown,
        day_of_week_breakdown=day_breakdown,
        monthly_equity=monthly_equity,
        random_baseline_metrics=baseline_metrics,
        executed_trades=executed_trades,
        candidates=candidates,
        raw_config=config.to_dict(),
    )
