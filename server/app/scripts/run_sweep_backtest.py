"""Script to run the Liquidity-Sweep Backtest across Train, Validation, and Test splits."""

import argparse
from datetime import datetime, timezone
import json
import os
import sys
from typing import List

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.candle import Candle
from app.schemas.candle import CandleCreate
from app.services.sweep.config import SweepConfig
from app.services.sweep.backtest.engine import run_walk_forward_backtest
from app.services.sweep.backtest.tuning import (
    compile_split_report,
    generate_preregistered_grid,
    make_purged_time_splits,
)
from app.services.sweep.backtest.formatter import format_backtest_report_markdown


def load_candles_from_db(symbol: str = "XAU/USD", timeframe: str = "15m") -> List[CandleCreate]:
    """Load strictly aligned candles from database ordered ascending by timestamp."""
    db = SessionLocal()
    try:
        stmt = (
            select(Candle)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
            .order_by(Candle.timestamp.asc())
        )
        db_rows = db.execute(stmt).scalars().all()
        candles = [
            CandleCreate(
                symbol=r.symbol,
                timeframe=r.timeframe,
                timestamp=r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc),
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=float(r.volume),
            )
            for r in db_rows
        ]
        return candles
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Run Liquidity-Sweep Backtest Harness")
    parser.add_argument("--symbol", default="XAU/USD", help="Symbol to backtest (default: XAU/USD)")
    parser.add_argument("--output-dir", default="reports", help="Directory to save report markdown")
    args = parser.parse_args()

    print(f"Loading candles for {args.symbol} from database...")
    candles = load_candles_from_db(args.symbol, "15m")
    print(f"Loaded {len(candles):,} clean 15m candles.")

    if len(candles) < 200:
        print("ERROR: Insufficient candles (< 200) to perform train/val/test backtest splits.")
        sys.exit(1)

    print(f"Date Range: {candles[0].timestamp} to {candles[-1].timestamp}")

    # 1. Purged & Embargoed Time Splits (60% Train, 20% Val, 20% Test)
    train_data, val_data, test_data = make_purged_time_splits(candles, 0.60, 0.20, 0.20)
    print(f"Split sizes: Train={len(train_data.candles_15m):,} bars, Val={len(val_data.candles_15m):,} bars, Test={len(test_data.candles_15m):,} bars")

    # 2. Evaluate Pre-registered Grid on Train Split
    grid = generate_preregistered_grid()
    print(f"\n--- Pre-Registered Grid Search on Train Split ({len(grid)} combinations) ---")
    best_config = SweepConfig()
    best_score = -999.0
    grid_results = []

    for idx, cfg in enumerate(grid):
        trades, cands = run_walk_forward_backtest(train_data.candles_15m, config=cfg)
        r_vals = [t.r_multiple for t in trades]
        mean_r = sum(r_vals) / len(r_vals) if r_vals else 0.0
        n_exec = len(trades)
        wins = sum(1 for r in r_vals if r > 0)
        win_rate = (wins / n_exec * 100.0) if n_exec > 0 else 0.0

        grid_results.append({
            "combination_idx": idx + 1,
            "pivot_n": cfg.pivot_n_15m,
            "max_rejection": cfg.max_rejection_bars,
            "min_rr": cfg.min_rr_tp1,
            "n_executed": n_exec,
            "win_rate": round(win_rate, 1),
            "expectancy_r": round(mean_r, 3),
        })
        print(f"[{idx+1:02d}/18] pivot_N={cfg.pivot_n_15m}, reject_within={cfg.max_rejection_bars}, min_rr={cfg.min_rr_tp1} -> {n_exec} trades, WR={win_rate:.1f}%, Exp={mean_r:+.3f} R")

        # Score function: prioritize positive expectancy with minimum sample
        score = mean_r if n_exec >= 10 else -999.0
        if score > best_score:
            best_score = score
            best_config = cfg

    print(f"\nBest Config on Train: pivot_N={best_config.pivot_n_15m}, reject_within={best_config.max_rejection_bars}, min_rr={best_config.min_rr_tp1} (Score: {best_score:+.3f} R)")

    # 3. Confirm on Validation Split
    print("\n--- Confirming Best Config on Validation Split ---")
    val_report = compile_split_report("validation", val_data.candles_15m, best_config)
    print(f"Validation Result: {val_report.overall_metrics.n_executed} trades, WR={val_report.overall_metrics.win_rate}%, Exp={val_report.overall_metrics.expectancy_r} R, Verdict={val_report.overall_metrics.verdict}")

    # 4. Evaluate Test Split EXACTLY ONCE
    print("\n--- Evaluating Test Split (Strictly Evaluated Once) ---")
    test_report = compile_split_report("test", test_data.candles_15m, best_config)
    print(f"Test Result: {test_report.overall_metrics.n_executed} trades, WR={test_report.overall_metrics.win_rate}%, Exp={test_report.overall_metrics.expectancy_r} R, Verdict={test_report.overall_metrics.verdict}")

    # 5. Full History Report
    print("\n--- Compiling Full History Report ---")
    full_report = compile_split_report("full_history", candles, best_config)

    # 6. Format and Output
    os.makedirs(args.output_dir, exist_ok=True)
    full_md = format_backtest_report_markdown(full_report)

    output_path = os.path.join(args.output_dir, f"backtest_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_md)
    print(f"\nFull report written to: {output_path}")

    # Print markdown
    print("\n" + "=" * 80)
    print(full_md)
    print("=" * 80)


if __name__ == "__main__":
    main()
