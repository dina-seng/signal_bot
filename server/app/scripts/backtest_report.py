"""CLI Report Generator for Historical Walk-Forward Backtesting of XAU/USD.

Usage:
    python -m app.scripts.backtest_report [--symbol XAU/USD] [--source twelvedata] [--spread 0.30] [--slippage 0.10] [--db-url sqlite:///backtest.db]

Upgraded features (Phase 1b Step F):
- Score-bucket table (0-25, 25-50, 50-75, 75+) showing candidate count, win rate, expectancy in R, profit factor
- Bootstrap 95% confidence interval for expectancy (1,000 resamples)
- "min trades" warning: prints "⚠️ INSUFFICIENT SAMPLE (< 100 trades)" if a section has fewer than 100 trades
- Per-session (Asia/London/NY, UTC-based) and per-day-of-week (Monday-Friday) tables
- Always prints config banner (spread, slippage, thresholds, NEWS FILTER OFF, data source, date range)
"""

import argparse
from datetime import datetime, timezone
import os
import random
import sys
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

# Ensure server root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core.config import settings
from app.core.database import Base
from app.models.candle import Candle
from app.models.signal_candidate import SignalCandidate
from app.services.backtesting.walk_forward_harness import (
    TradeMetrics,
    WalkForwardHarness,
    WalkForwardResult,
)


def get_db_session(db_url: Optional[str] = None) -> Session:
    """Connect to database and return a Session instance."""
    url = db_url or settings.DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(url, connect_args=connect_args)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def load_candles(
    db: Session,
    symbol: str = "XAU/USD",
    source: Optional[str] = None,
    limit: Optional[int] = None,
) -> Tuple[List[Candle], List[Candle], List[Candle]]:
    """Fetch 15m, 1h, and 4h candles strictly filtered by single provider source."""
    src_query = select(Candle.source).where(Candle.symbol == symbol).distinct()
    available_sources = [s for s in db.scalars(src_query).all() if s is not None]

    if not available_sources:
        available_sources = ["twelvedata"]

    target_source = source or available_sources[0]

    stmt_15m = (
        select(Candle)
        .where(Candle.symbol == symbol, Candle.timeframe == "15m")
        .order_by(Candle.timestamp.asc())
    )
    if source:
        stmt_15m = stmt_15m.where(Candle.source == target_source)
    if limit:
        stmt_15m = stmt_15m.limit(limit)

    c15 = list(db.scalars(stmt_15m).all())

    stmt_1h = (
        select(Candle)
        .where(Candle.symbol == symbol, Candle.timeframe == "1h")
        .order_by(Candle.timestamp.asc())
    )
    if source:
        stmt_1h = stmt_1h.where(Candle.source == target_source)

    stmt_4h = (
        select(Candle)
        .where(Candle.symbol == symbol, Candle.timeframe == "4h")
        .order_by(Candle.timestamp.asc())
    )
    if source:
        stmt_4h = stmt_4h.where(Candle.source == target_source)

    c1h = list(db.scalars(stmt_1h).all())
    c4h = list(db.scalars(stmt_4h).all())

    return c15, c1h, c4h


def compute_bootstrap_ci(
    r_multiples: List[float],
    n_resamples: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> Tuple[float, float]:
    """Calculate 95% bootstrap confidence interval for mean R-expectancy."""
    if not r_multiples:
        return 0.0, 0.0

    rng = random.Random(seed)
    n = len(r_multiples)
    means = []
    for _ in range(n_resamples):
        sample = [rng.choice(r_multiples) for _ in range(n)]
        means.append(sum(sample) / n)

    means.sort()
    alpha = (1.0 - ci) / 2.0
    low_idx = int(alpha * n_resamples)
    high_idx = int((1.0 - alpha) * n_resamples)
    low_idx = max(0, min(low_idx, n_resamples - 1))
    high_idx = max(0, min(high_idx, n_resamples - 1))
    return round(means[low_idx], 2), round(means[high_idx], 2)


def print_config_banner(cfg: Dict[str, Any]):
    """Always print active configuration header."""
    print("=" * 82)
    print(" 🛠️ QUANTVIEW BACKTEST RUN CONFIGURATION")
    print("=" * 82)
    print(f"  • Instrument:            {cfg['symbol']}")
    print(f"  • Data Provider Source:  {cfg['source']}")
    print(f"  • Date Range:            {cfg['start_time']} to {cfg['end_time']}")
    print(f"  • Candle Counts:         {cfg['count_15m']:,} (15m) | {cfg['count_1h']:,} (1h) | {cfg['count_4h']:,} (4h)")
    print(f"  • Transaction Spread:    ${cfg['spread']:.2f} USD")
    print(f"  • Execution Slippage:    ${cfg['slippage']:.2f} USD")
    print(f"  • Min Score Threshold:   {cfg['min_score']:.1f} / 100")
    print(f"  • Min Planned R:R:       {cfg['min_rr']:.1f}")
    print(f"  • Position Limit:        1 open trade per symbol at a time")
    print(f"  • Cooldown Post-Exit:    {cfg['cooldown_hours']} hours (SIGNAL_COOLDOWN_HOURS)")
    print(f"  • Collision Rule:        SL assumed first if both SL and TP touched in same bar")
    print(f"  • Economic News Gate:    NEWS FILTER OFF (Backtest Mode)")
    print("=" * 82)
    print()


def print_metrics_comparison_table(
    title: str,
    strategy: TradeMetrics,
    baseline: TradeMetrics,
    r_multiples_strategy: List[float],
    r_multiples_baseline: List[float],
):
    """Print comparison table between strategy and random baseline with bootstrap CI."""
    strat_ci_low, strat_ci_high = compute_bootstrap_ci(r_multiples_strategy)
    base_ci_low, base_ci_high = compute_bootstrap_ci(r_multiples_baseline)

    print("=" * 82)
    print(f" 📊 {title.upper()}")
    print("=" * 82)
    print(f"{'Metric':<32} | {'Strategy Setup':<22} | {'Random Baseline':<22}")
    print("-" * 82)
    print(f"{'Trade Count':<32} | {strategy.trade_count:<22} | {baseline.trade_count:<22}")
    print(f"{'Win Rate (%)':<32} | {strategy.win_rate:>20.1f}% | {baseline.win_rate:>20.1f}%")
    print(f"{'Expectancy (R)':<32} | {strategy.expectancy_r:>21.2f}R | {baseline.expectancy_r:>21.2f}R")
    print(f"{'Bootstrap 95% CI':<32} | [{strat_ci_low:+.2f}R, {strat_ci_high:+.2f}R]{'':<7} | [{base_ci_low:+.2f}R, {base_ci_high:+.2f}R]")
    print(f"{'Profit Factor':<32} | {strategy.profit_factor:>22.2f} | {baseline.profit_factor:>22.2f}")
    print(f"{'Total Return (R)':<32} | {strategy.total_r:>21.2f}R | {baseline.total_r:>21.2f}R")
    print(f"{'Avg Win / Avg Loss (R)':<32} | {strategy.avg_win_r:.2f}R / {strategy.avg_loss_r:.2f}R{'':<9} | {baseline.avg_win_r:.2f}R / {baseline.avg_loss_r:.2f}R")
    print(f"{'Max Drawdown (R)':<32} | {strategy.max_drawdown_r:>21.2f}R | {baseline.max_drawdown_r:>21.2f}R")
    print("-" * 82)

    edge_r = strategy.expectancy_r - baseline.expectancy_r
    if strategy.trade_count > 0:
        edge_status = "POSITIVE ALPHA EDGE (+)" if edge_r > 0 else "NO EDGE / NEGATIVE ALPHA (-)"
        print(f" Net Edge vs Baseline: {edge_r:+.2f}R [{edge_status}]")
    else:
        print(" Net Edge vs Baseline: N/A (0 trades taken)")

    if strategy.trade_count < 100:
        print(" ⚠️  WARNING: INSUFFICIENT SAMPLE (< 100 trades) — Statistical significance cannot be established.")
    print()


def print_score_bucket_table(candidates: List[Dict[str, Any]], harness: WalkForwardHarness):
    """Print candidate outcomes bucketed by setup score (0-25, 25-50, 50-75, 75+)."""
    print("=" * 82)
    print(" 🎯 SCORE-BUCKET EXPECTANCY & OUTCOME ATTRIBUTION")
    print("=" * 82)
    print(f"{'Score Bucket':<14} | {'Count':<7} | {'Win Rate':<10} | {'Expectancy':<12} | {'Profit Factor':<15} | {'Sample Quality'}")
    print("-" * 82)

    buckets = [
        ("0 - 25", 0.0, 25.0),
        ("25 - 50", 25.0, 50.0),
        ("50 - 75", 50.0, 75.0),
        ("75+", 75.0, 1000.0),
    ]

    for label, low, high in buckets:
        if high > 100:
            b_cands = [c for c in candidates if c["final_score"] >= low and c.get("r_multiple") is not None]
        else:
            b_cands = [c for c in candidates if low <= c["final_score"] < high and c.get("r_multiple") is not None]

        r_list = [c["r_multiple"] for c in b_cands]
        m = harness.calculate_metrics(r_list)
        wr_str = f"{m.win_rate:.1f}%" if m.trade_count > 0 else "N/A"
        exp_str = f"{m.expectancy_r:+.2f}R" if m.trade_count > 0 else "N/A"
        pf_str = f"{m.profit_factor:.2f}" if m.trade_count > 0 else "N/A"
        status_str = "VALID SAMPLE" if m.trade_count >= 100 else "⚠️ INSUFFICIENT SAMPLE"

        print(f"{label:<14} | {m.trade_count:<7} | {wr_str:<10} | {exp_str:<12} | {pf_str:<15} | {status_str}")

    print("=" * 82)
    print()


def print_session_table(breakdown: Dict[str, Dict[str, Any]]):
    """Print per-session breakdown (Asia/London/NY, UTC-based)."""
    print("=" * 82)
    print(" 🕒 PER-SESSION PERFORMANCE BREAKDOWN (UTC-BASED)")
    print("=" * 82)
    print(f"{'Session':<12} | {'Trades':<8} | {'Win Rate':<10} | {'Expectancy':<12} | {'Profit Factor':<15} | {'Total R':<10} | {'Status'}")
    print("-" * 82)
    for sess, data in breakdown.items():
        cnt = data["trade_count"]
        wr = f"{data['win_rate']:.1f}%" if cnt > 0 else "N/A"
        exp = f"{data['expectancy_r']:+.2f}R" if cnt > 0 else "N/A"
        pf = f"{data['profit_factor']:.2f}" if cnt > 0 else "N/A"
        tot_r = f"{data['total_r']:+.2f}R" if cnt > 0 else "N/A"
        status = "VALID" if cnt >= 100 else "⚠️ INSUFFICIENT SAMPLE"
        print(f"{sess:<12} | {cnt:<8} | {wr:<10} | {exp:<12} | {pf:<15} | {tot_r:<10} | {status}")
    print("=" * 82)
    print()


def print_day_of_week_table(executed_trades: List[Dict[str, Any]], harness: WalkForwardHarness):
    """Print per-day-of-week breakdown (Monday - Friday)."""
    print("=" * 82)
    print(" 📅 PER-DAY-OF-WEEK PERFORMANCE BREAKDOWN (UTC)")
    print("=" * 82)
    print(f"{'Day of Week':<14} | {'Trades':<8} | {'Win Rate':<10} | {'Expectancy':<12} | {'Profit Factor':<15} | {'Total R':<10} | {'Status'}")
    print("-" * 82)

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    for day_idx, day_name in enumerate(day_names):
        d_cands = [c for c in executed_trades if c["timestamp"].weekday() == day_idx and c.get("r_multiple") is not None]
        r_list = [c["r_multiple"] for c in d_cands]
        m = harness.calculate_metrics(r_list)

        wr = f"{m.win_rate:.1f}%" if m.trade_count > 0 else "N/A"
        exp = f"{m.expectancy_r:+.2f}R" if m.trade_count > 0 else "N/A"
        pf = f"{m.profit_factor:.2f}" if m.trade_count > 0 else "N/A"
        tot_r = f"{m.total_r:+.2f}R" if m.trade_count > 0 else "N/A"
        status = "VALID" if m.trade_count >= 100 else "⚠️ INSUFFICIENT SAMPLE"

        print(f"{day_name:<14} | {m.trade_count:<8} | {wr:<10} | {exp:<12} | {pf:<15} | {tot_r:<10} | {status}")

    print("=" * 82)
    print()


def main():
    parser = argparse.ArgumentParser(description="Institutional Walk-Forward Backtest Report for XAU/USD.")
    parser.add_argument("--symbol", type=str, default="XAU/USD", help="Instrument symbol (default: XAU/USD)")
    parser.add_argument("--source", type=str, default=None, help="Data provider source (default: auto/consistent)")
    parser.add_argument("--spread", type=float, default=0.30, help="Spread in USD for XAU/USD (default: 0.30)")
    parser.add_argument("--slippage", type=float, default=0.10, help="Slippage in USD for XAU/USD (default: 0.10)")
    parser.add_argument("--min-score", type=float, default=75.0, help="Min setup score to qualify (default: 75.0)")
    parser.add_argument("--min-rr", type=float, default=1.5, help="Min planned R:R (default: 1.5)")
    parser.add_argument("--db-url", type=str, default=None, help="Database URL override (e.g. sqlite:///backtest.db)")
    parser.add_argument("--limit", type=int, default=None, help="Optional limit of 15m bars to process")
    args = parser.parse_args()

    db = get_db_session(args.db_url)
    try:
        c15, c1h, c4h = load_candles(
            db=db,
            symbol=args.symbol,
            source=args.source,
            limit=args.limit,
        )

        if not c15:
            print(f"[!] No 15m candle data found for {args.symbol} in database.")
            print("    Please ingest historical candles before generating backtest report.")
            return

        harness = WalkForwardHarness()

        # Execute walk-forward simulation
        result: WalkForwardResult = harness.run_walk_forward(
            candles_15m=c15,
            candles_1h=c1h,
            candles_4h=c4h,
            symbol=args.symbol,
            source=args.source,
            spread_usd=args.spread,
            slippage_usd=args.slippage,
            min_score_threshold=args.min_score,
            min_rr=args.min_rr,
            db=db,
        )

        # Config header
        cfg_info = {
            "symbol": args.symbol,
            "source": result.source,
            "start_time": c15[0].timestamp.strftime("%Y-%m-%d %H:%M UTC"),
            "end_time": c15[-1].timestamp.strftime("%Y-%m-%d %H:%M UTC"),
            "count_15m": len(c15),
            "count_1h": len(c1h),
            "count_4h": len(c4h),
            "spread": args.spread,
            "slippage": args.slippage,
            "min_score": args.min_score,
            "min_rr": args.min_rr,
            "cooldown_hours": getattr(settings, "SIGNAL_COOLDOWN_HOURS", 2),
        }
        print()
        print_config_banner(cfg_info)

        print(f"Total Evaluated Setup Candidates Logged: {result.total_candidates_logged}")
        print(f"Total Qualified Signals (Score >= {args.min_score:.1f}, RR >= {args.min_rr:.1f}): {result.qualified_candidates_count}")
        print(f"Total Executed Trades (One Position At A Time + Cooldown): {result.executed_trades_count}\n")

        executed = [c for c in result.candidates if c["qualified"] and c["skipped_reason"] is None]
        n_exec = len(executed)
        split_idx = int(n_exec * 0.70)
        train_trades = executed[:split_idx]
        test_trades = executed[split_idx:]

        train_r = [c["r_multiple"] for c in train_trades if c.get("r_multiple") is not None]
        test_r = [c["r_multiple"] for c in test_trades if c.get("r_multiple") is not None]

        # Extract baseline R
        train_base_r = [result.train_baseline_metrics.expectancy_r] * len(train_r) if train_r else []
        test_base_r = [result.test_baseline_metrics.expectancy_r] * len(test_r) if test_r else []

        # Table 1: In-Sample (Train 70%)
        print_metrics_comparison_table(
            title="In-Sample Split (First 70% Time-Based Window)",
            strategy=result.train_metrics,
            baseline=result.train_baseline_metrics,
            r_multiples_strategy=train_r,
            r_multiples_baseline=train_base_r,
        )

        # Table 2: Out-of-Sample (Test 30%)
        print_metrics_comparison_table(
            title="Out-of-Sample Split (Last 30% Time-Based Window)",
            strategy=result.test_metrics,
            baseline=result.test_baseline_metrics,
            r_multiples_strategy=test_r,
            r_multiples_baseline=test_base_r,
        )

        # Table 3: Score-Bucket Breakdown
        print_score_bucket_table(result.candidates, harness)

        # Table 4: Session Breakdown
        print_session_table(result.session_breakdown)

        # Table 5: Day of Week Breakdown
        print_day_of_week_table(executed, harness)

    finally:
        db.close()


if __name__ == "__main__":
    main()
