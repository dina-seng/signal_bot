"""Liquidity-Sweep Backtest Package."""

from app.services.sweep.backtest.models import (
    TradePosition,
    CandidateSetupRecord,
    SliceMetrics,
    BacktestReport,
)
from app.services.sweep.backtest.engine import run_walk_forward_backtest
from app.services.sweep.backtest.metrics import calculate_slice_metrics, compute_monthly_equity
from app.services.sweep.backtest.baseline import run_random_baseline
from app.services.sweep.backtest.tuning import (
    make_purged_time_splits,
    generate_preregistered_grid,
    compile_split_report,
)
from app.services.sweep.backtest.formatter import format_backtest_report_markdown

__all__ = [
    "TradePosition",
    "CandidateSetupRecord",
    "SliceMetrics",
    "BacktestReport",
    "run_walk_forward_backtest",
    "calculate_slice_metrics",
    "compute_monthly_equity",
    "run_random_baseline",
    "make_purged_time_splits",
    "generate_preregistered_grid",
    "compile_split_report",
    "format_backtest_report_markdown",
]
