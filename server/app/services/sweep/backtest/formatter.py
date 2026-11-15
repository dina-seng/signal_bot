"""Institutional Markdown Formatter for Liquidity-Sweep Backtest Reports."""

import json
from app.services.sweep.backtest.models import BacktestReport, SliceMetrics


def _format_slice_row(s: SliceMetrics) -> str:
    n_exec = s.n_executed
    if n_exec < 30:
        return (
            f"| {s.slice_name} | {s.n_signals} | {s.n_executed} | {s.n_deduped} | "
            f"n/a (n<30) | n/a (n<30) | n/a (n<30) | n/a (n<30) | n/a (n<30) | {s.verdict} |"
        )

    wr_str = f"{s.win_rate:.1f}%" if s.win_rate is not None else "n/a"
    exp_str = f"{s.expectancy_r:+.3f} R" if s.expectancy_r is not None else "n/a"
    ci_str = f"[{s.ci_lower:+.2f}, {s.ci_upper:+.2f}]" if (s.ci_lower is not None and s.ci_upper is not None) else "n/a"
    pf_str = f"{s.profit_factor:.2f}" if s.profit_factor is not None else "n/a"
    mdd_str = f"{s.max_drawdown_r:.2f} R" if s.max_drawdown_r is not None else "n/a"

    return (
        f"| {s.slice_name} | {s.n_signals} | {s.n_executed} | {s.n_deduped} | "
        f"{wr_str} | {exp_str} | {ci_str} | {pf_str} | {mdd_str} | {s.verdict} |"
    )


def format_backtest_report_markdown(report: BacktestReport) -> str:
    """Format full backtest report into clean, auditable Markdown."""
    lines = [
        f"# Institutional Backtest Report: {report.split_name.upper()} Split",
        "",
        "## Configuration Used",
        "```json",
        json.dumps(report.raw_config, indent=2),
        "```",
        "",
        "## Simulation Parameters",
        f"- **Time Split**: `{report.split_name}`",
        f"- **Date Range**: `{report.start_date.strftime('%Y-%m-%d %H:%M UTC')}` to `{report.end_date.strftime('%Y-%m-%d %H:%M UTC')}`",
        f"- **Total 15m Bars Analyzed**: `{report.total_bars:,}`",
        f"- **News Filter**: `OFF` (News blackout filter labeled OFF for backtest simulation)",
        f"- **Friction Model**: Spread $0.30 + Slippage $0.10 USD (Roundtrip = $0.40 USD)",
        f"- **Fill Model**: Limit fills strictly when price trades through zone price (SL assumed first on same-bar touches)",
        "",
        "## Overall Strategy Performance vs Random Baseline",
        "| Metric | Strategy Overall | Random Baseline (Identical Geometry & Times) |",
        "| :--- | :--- | :--- |",
        f"| **Signals Emitted** | {report.overall_metrics.n_signals} | {report.random_baseline_metrics.n_signals if report.random_baseline_metrics else 'n/a'} |",
        f"| **Executed Trades** | {report.overall_metrics.n_executed} | {report.random_baseline_metrics.n_executed if report.random_baseline_metrics else 'n/a'} |",
        f"| **Cluster-Deduped Trades** | {report.overall_metrics.n_deduped} | {report.random_baseline_metrics.n_deduped if report.random_baseline_metrics else 'n/a'} |",
        f"| **Win Rate** | {report.overall_metrics.win_rate if report.overall_metrics.win_rate is not None else 'n/a'}% | {report.random_baseline_metrics.win_rate if report.random_baseline_metrics and report.random_baseline_metrics.win_rate is not None else 'n/a'}% |",
        f"| **Expectancy (R)** | {report.overall_metrics.expectancy_r if report.overall_metrics.expectancy_r is not None else 'n/a'} R | {report.random_baseline_metrics.expectancy_r if report.random_baseline_metrics and report.random_baseline_metrics.expectancy_r is not None else 'n/a'} R |",
        f"| **Bootstrap 95% CI** | [{report.overall_metrics.ci_lower}, {report.overall_metrics.ci_upper}] | [{report.random_baseline_metrics.ci_lower}, {report.random_baseline_metrics.ci_upper}] if report.random_baseline_metrics else 'n/a' |",
        f"| **Profit Factor** | {report.overall_metrics.profit_factor if report.overall_metrics.profit_factor is not None else 'n/a'} | {report.random_baseline_metrics.profit_factor if report.random_baseline_metrics and report.random_baseline_metrics.profit_factor is not None else 'n/a'} |",
        f"| **Max Drawdown (R)** | {report.overall_metrics.max_drawdown_r if report.overall_metrics.max_drawdown_r is not None else 'n/a'} R | {report.random_baseline_metrics.max_drawdown_r if report.random_baseline_metrics and report.random_baseline_metrics.max_drawdown_r is not None else 'n/a'} R |",
        f"| **Average Friction (R)** | {report.overall_metrics.avg_friction_r if report.overall_metrics.avg_friction_r is not None else 'n/a'} R | {report.random_baseline_metrics.avg_friction_r if report.random_baseline_metrics and report.random_baseline_metrics.avg_friction_r is not None else 'n/a'} R |",
        f"| **Statistical Edge Verdict** | **{report.overall_metrics.verdict}** | **{report.random_baseline_metrics.verdict if report.random_baseline_metrics else 'n/a'}** |",
        "",
        "## Performance Slices Breakdown",
        "| Slice | Signals | Executed | Deduped | Win Rate | Expectancy (R) | Bootstrap 95% CI | Profit Factor | Max DD (R) | Statistical Verdict |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    # Add Grade breakdown
    lines.append("| **--- By Setup Grade ---** | | | | | | | | | |")
    for g_name, s in report.grade_breakdown.items():
        lines.append(_format_slice_row(s))

    # Add Session breakdown
    lines.append("| **--- By Trading Session ---** | | | | | | | | | |")
    for sess_name, s in report.session_breakdown.items():
        lines.append(_format_slice_row(s))

    # Add HTF Alignment breakdown
    lines.append("| **--- By HTF Bias Alignment ---** | | | | | | | | | |")
    for htf_name, s in report.htf_alignment_breakdown.items():
        lines.append(_format_slice_row(s))

    # Add Pool Type breakdown
    lines.append("| **--- By Swept Pool Type ---** | | | | | | | | | |")
    for pool_name, s in report.pool_type_breakdown.items():
        lines.append(_format_slice_row(s))

    # Add Day of Week breakdown
    lines.append("| **--- By Day of Week ---** | | | | | | | | | |")
    for day_name, s in report.day_of_week_breakdown.items():
        lines.append(_format_slice_row(s))

    lines.extend([
        "",
        "## Monthly Cumulative R Returns",
        "| Month | Cumulative R |",
        "| :--- | :--- |",
    ])
    if report.monthly_equity:
        for m, r_val in report.monthly_equity.items():
            lines.append(f"| {m} | {r_val:+.2f} R |")
    else:
        lines.append("| None | 0.00 R |")

    lines.append("")
    return "\n".join(lines)
