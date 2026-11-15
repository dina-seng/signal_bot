"""Script to run the Liquidity-Sweep Backtest across Train, Validation, and Test splits."""

import argparse
from datetime import datetime, timezone
import json
import os
import sys
import time
from typing import List

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.candle import Candle
from app.schemas.candle import CandleCreate
from app.services.market_data.calendar import filter_open_market_candles
from app.services.sweep.config import SweepConfig
from app.services.sweep.backtest.engine import run_walk_forward_backtest
from app.services.sweep.backtest.tuning import (
    compile_split_report,
    generate_preregistered_grid,
    make_purged_time_splits,
)
from app.services.sweep.backtest.formatter import format_backtest_report_markdown
import concurrent.futures

# Global worker state for process-pool initialization (avoids pickling candle list per task)
_worker_candles: List[CandleCreate] = []


def _init_worker(candles: List[CandleCreate]):
    global _worker_candles
    _worker_candles = candles


def _evaluate_single_combination(args_tuple):
    idx, cfg = args_tuple
    trades, cands = run_walk_forward_backtest(_worker_candles, config=cfg)
    r_vals = [t.r_multiple for t in trades]
    mean_r = sum(r_vals) / len(r_vals) if r_vals else 0.0
    n_exec = len(trades)
    wins = sum(1 for r in r_vals if r > 0)
    win_rate = (wins / n_exec * 100.0) if n_exec > 0 else 0.0
    return idx, cfg, n_exec, win_rate, mean_r


def load_candles_from_sqlite(
    db_path: str = "backtest.db",
    symbol: str = "XAU/USD",
    timeframe: str = "15m",
) -> List[CandleCreate]:
    """Load strictly aligned candles from local SQLite backtest.db, dropping closed-market bars at load time."""
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    db = Session()
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
    parser.add_argument("--db-path", default="backtest.db", help="Path to SQLite backtest DB (default: backtest.db)")
    parser.add_argument("--symbol", default="XAU/USD", help="Symbol to backtest (default: XAU/USD)")
    parser.add_argument("--output-dir", default="reports", help="Directory to save report markdown")
    args = parser.parse_args()

    print(f"Loading candles for {args.symbol} from {args.db_path}...")
    raw_candles = load_candles_from_sqlite(args.db_path, args.symbol, "15m")
    raw_count = len(raw_candles)
    candles = filter_open_market_candles(raw_candles)
    dropped_count = raw_count - len(candles)
    print(f"Loaded {raw_count:,} raw 15m candles from {args.db_path}.")
    print(f"Dropped {dropped_count:,} closed-market (weekend / daily break) placeholder bars ({dropped_count / raw_count * 100:.1f}%).")
    print(f"Retained {len(candles):,} strictly open-market 15m candles for analysis.")

    if len(candles) < 200:
        print("ERROR: Insufficient candles (< 200) to perform train/val/test backtest splits.")
        sys.exit(1)

    print(f"Date Range: {candles[0].timestamp} to {candles[-1].timestamp}")

    # 1. Purged & Embargoed Time Splits (60% Train, 20% Val, 20% Test)
    train_data, val_data, test_data = make_purged_time_splits(candles, 0.60, 0.20, 0.20)
    print(f"Split sizes: Train={len(train_data.candles_15m):,} bars, Val={len(val_data.candles_15m):,} bars, Test={len(test_data.candles_15m):,} bars")

    # 2. Evaluate Pre-registered Grid on Train Split
    grid = generate_preregistered_grid()
    print(f"\n--- Pre-Registered Grid Search on Train Split ({len(grid)} combinations in parallel) ---", flush=True)
    best_config = SweepConfig()
    best_score = -999.0
    grid_results = []

    tasks = [(idx, cfg) for idx, cfg in enumerate(grid)]
    max_workers = min(14, os.cpu_count() or 4)

    t_grid_start = time.perf_counter()
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=max_workers,
        initializer=_init_worker,
        initargs=(train_data.candles_15m,),
    ) as executor:
        for idx, cfg, n_exec, win_rate, mean_r in executor.map(_evaluate_single_combination, tasks):
            grid_results.append({
                "combination_idx": idx + 1,
                "pivot_n": cfg.pivot_n_15m,
                "max_rejection": cfg.max_rejection_bars,
                "min_rr": cfg.min_rr_tp1,
                "n_executed": n_exec,
                "win_rate": round(win_rate, 1),
                "expectancy_r": round(mean_r, 3),
            })
            print(f"[{idx+1:02d}/18] pivot_N={cfg.pivot_n_15m}, reject_within={cfg.max_rejection_bars}, min_rr={cfg.min_rr_tp1} -> {n_exec} trades, WR={win_rate:.1f}%, Exp={mean_r:+.3f} R", flush=True)

            score = mean_r if n_exec >= 10 else -999.0
            if score > best_score:
                best_score = score
                best_config = cfg

    t_grid_elapsed = time.perf_counter() - t_grid_start
    total_grid_bars = len(grid) * len(train_data.candles_15m)
    sec_per_1000 = t_grid_elapsed / (total_grid_bars / 1000.0)
    print(f"\n[Performance] Grid Search completed in {t_grid_elapsed:.2f}s ({sec_per_1000:.3f} s / 1,000 bars evaluated across {max_workers} workers)", flush=True)

    print(f"\nBest Config on Train: pivot_N={best_config.pivot_n_15m}, reject_within={best_config.max_rejection_bars}, min_rr={best_config.min_rr_tp1} (Score: {best_score:+.3f} R)", flush=True)

    # 3. Confirm on Validation Split
    print("\n--- Confirming Best Config on Validation Split ---", flush=True)
    val_report = compile_split_report("validation", val_data.candles_15m, best_config)
    print(f"Validation Result: {val_report.overall_metrics.n_executed} trades, WR={val_report.overall_metrics.win_rate}%, Exp={val_report.overall_metrics.expectancy_r} R, Verdict={val_report.overall_metrics.verdict}", flush=True)

    # 4. Evaluate Test Split EXACTLY ONCE
    print("\n--- Evaluating Test Split (Strictly Evaluated Once) ---", flush=True)
    test_report = compile_split_report("test", test_data.candles_15m, best_config)
    print(f"Test Result: {test_report.overall_metrics.n_executed} trades, WR={test_report.overall_metrics.win_rate}%, Exp={test_report.overall_metrics.expectancy_r} R, Verdict={test_report.overall_metrics.verdict}", flush=True)

    # 5. Full History Report
    print("\n--- Compiling Full History Report ---", flush=True)
    full_report = compile_split_report("full_history", candles, best_config)

    # 6. Format and Output
    os.makedirs(args.output_dir, exist_ok=True)
    full_md = format_backtest_report_markdown(full_report)

    output_path = os.path.join(args.output_dir, f"backtest_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_md)
    print(f"\nFull report written to: {output_path}", flush=True)

    # Print markdown
    print("\n" + "=" * 80, flush=True)
    print(full_md, flush=True)
    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
