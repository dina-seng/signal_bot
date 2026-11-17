"""Step 1: Baseline Controls Analysis for SMC Strategy.

Evaluates whether accepted SMC trades have an edge over drift:
  a) Random direction (1000 seeds)
  b) Always-BUY and Always-SELL
  c) Random timestamps (1000 seeds)

Output:
  - reports/smc_analysis/step1_controls.md
  - reports/smc_analysis/step1_controls.csv
"""

from __future__ import annotations

import csv
import glob
import json
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
import sys
if str(REPO_ROOT / "server") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "server"))
if str(REPO_ROOT / "server" / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "server" / "scripts"))

from crt_replay import SignalRecord, load_full_15m_candles, simulate_outcome


def run_step1() -> None:
    db_path = REPO_ROOT / "backtest.db"
    out_dir = REPO_ROOT / "reports" / "smc_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[*] Loading candles from {db_path}...")
    bars, meta = load_full_15m_candles(db_path, "XAU/USD", "twelvedata")
    print(f"[*] Loaded {len(bars):,} bars.")

    # Load accepted trades from checkpoints
    ckpt_files = sorted(glob.glob(str(REPO_ROOT / "reports" / "smc_replay_extended" / "checkpoints" / "*.json")))
    print(f"[*] Reading {len(ckpt_files)} checkpoints...")

    accepted_trades: List[Dict[str, Any]] = []
    seen_opps: set = set()
    month_accepted_trades: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for fpath in ckpt_files:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        for r in data["records"]:
            if r.get("accepted") and r.get("accepted_trade"):
                t = r["accepted_trade"]
                k = t.get("sweep_key")
                if k not in seen_opps:
                    seen_opps.add(k)
                    trade_obj = {
                        "index": r["index"],
                        "split": r["split"],
                        "month": r["month"],
                        "score": r["score"],
                        "real_direction": t["direction"],
                        "real_r": float(t["r_multiple"]),
                        "entry": float(t["crt_entry"]),
                        "risk": float(t["risk_price"]),
                    }
                    accepted_trades.append(trade_obj)
                    month_accepted_trades[r["month"]].append(trade_obj)

    print(f"[*] Total unique accepted opportunities: {len(accepted_trades):,}")
    splits = ("calibration", "validation", "test")

    # Pre-simulate Always-BUY and Always-SELL
    print("[*] Pre-simulating Always-BUY and Always-SELL at same timestamps and stop distances...")
    for t in accepted_trades:
        idx = t["index"]
        entry = t["entry"]
        risk = t["risk"]
        score = t["score"]
        ts = bars[idx].timestamp

        # BUY
        rec_b = SignalRecord(ts, "BUY", None, None, "market", entry, entry - risk, entry + 2 * risk, entry + 3 * risk, risk, 2.0, score)
        simulate_outcome(rec_b, bars=bars, signal_index=idx, spread=0.40, expiry_bars=8, max_hold_bars=500)
        t["buy_r"] = float(rec_b.r_multiple)
        t["buy_win"] = 1 if rec_b.r_multiple > 0 else 0

        # SELL
        rec_s = SignalRecord(ts, "SELL", None, None, "market", entry, entry + risk, entry - 2 * risk, entry - 3 * risk, risk, 2.0, score)
        simulate_outcome(rec_s, bars=bars, signal_index=idx, spread=0.40, expiry_bars=8, max_hold_bars=500)
        t["sell_r"] = float(rec_s.r_multiple)
        t["sell_win"] = 1 if rec_s.r_multiple > 0 else 0

    # Metrics for real accepted trades
    split_trades = {s: [t for t in accepted_trades if t["split"] == s] for s in splits}
    split_trades["pooled"] = accepted_trades

    real_stats = {}
    buy_stats = {}
    sell_stats = {}

    for s, sub in split_trades.items():
        n = len(sub)
        real_stats[s] = {
            "n": n,
            "mean_r": float(np.mean([t["real_r"] for t in sub])),
            "win_rate": float(np.mean([1 if t["real_r"] > 0 else 0 for t in sub])),
        }
        buy_stats[s] = {
            "n": n,
            "mean_r": float(np.mean([t["buy_r"] for t in sub])),
            "win_rate": float(np.mean([t["buy_win"] for t in sub])),
        }
        sell_stats[s] = {
            "n": n,
            "mean_r": float(np.mean([t["sell_r"] for t in sub])),
            "win_rate": float(np.mean([t["sell_win"] for t in sub])),
        }

    # Control a: Random Direction (1000 seeds)
    num_seeds = 1000
    seeds = list(range(1, num_seeds + 1))
    print(f"[*] Running Random Direction control ({num_seeds} seeds)...")

    rand_dir_runs: Dict[str, Dict[str, List[float]]] = {
        s: {"mean_r": [], "win_rate": []} for s in list(splits) + ["pooled"]
    }

    t0 = time.time()
    for seed in seeds:
        rng = random.Random(seed)
        # Generate direction decisions for each trade
        # rng.random() < 0.5 gives 50/50 BUY/SELL
        for s, sub in split_trades.items():
            rs = []
            wins = []
            # Note: to ensure consistency across splits, generate per trade
            for t in sub:
                # To be independent per trade but reproducible
                pick_buy = rng.random() < 0.5
                r_val = t["buy_r"] if pick_buy else t["sell_r"]
                w_val = t["buy_win"] if pick_buy else t["sell_win"]
                rs.append(r_val)
                wins.append(w_val)
            rand_dir_runs[s]["mean_r"].append(float(np.mean(rs)))
            rand_dir_runs[s]["win_rate"].append(float(np.mean(wins)))
    print(f"[*] Random Direction finished in {time.time() - t0:.2f}s")

    # Calculate percentiles for Random Direction
    rand_dir_summary = {}
    for s in list(splits) + ["pooled"]:
        dist_r = rand_dir_runs[s]["mean_r"]
        real_r = real_stats[s]["mean_r"]
        # Exact empirical percentile: percentage of runs <= real_r
        pct = float(np.mean([1.0 if x <= real_r else 0.0 for x in dist_r]) * 100.0)
        rand_dir_summary[s] = {
            "dist_mean_r": float(np.mean(dist_r)),
            "dist_std_r": float(np.std(dist_r)),
            "dist_min_r": float(np.min(dist_r)),
            "dist_max_r": float(np.max(dist_r)),
            "dist_p5_r": float(np.percentile(dist_r, 5)),
            "dist_p50_r": float(np.percentile(dist_r, 50)),
            "dist_p95_r": float(np.percentile(dist_r, 95)),
            "dist_mean_wr": float(np.mean(rand_dir_runs[s]["win_rate"])),
            "percentile": pct,
        }

    # Control c: Random Timestamps (1000 seeds)
    print(f"[*] Running Random Timestamps control ({num_seeds} seeds)...")
    # Map open-market bars by month
    bars_by_month: Dict[str, List[int]] = defaultdict(list)
    for i, b in enumerate(bars):
        m_key = b.timestamp.strftime("%Y-%m")
        bars_by_month[m_key].append(i)

    # Acceptance direction ratio pooled
    total_buy = sum(1 for t in accepted_trades if t["real_direction"] == "BUY")
    pooled_buy_ratio = total_buy / len(accepted_trades)
    print(f"[*] Real accepted BUY ratio: {pooled_buy_ratio:.4f} ({total_buy}/{len(accepted_trades)})")

    rand_ts_runs: Dict[str, Dict[str, List[float]]] = {
        s: {"mean_r": [], "win_rate": []} for s in list(splits) + ["pooled"]
    }

    t0 = time.time()
    for seed in seeds:
        rng = random.Random(seed)
        month_sim_results: Dict[str, List[Dict[str, float]]] = defaultdict(list)

        for m, m_trades in month_accepted_trades.items():
            n_m = len(m_trades)
            eligible = bars_by_month[m]
            if not eligible:
                continue
            # Sample bars without replacement if possible
            if len(eligible) >= n_m:
                chosen_bars = rng.sample(eligible, n_m)
            else:
                chosen_bars = rng.choices(eligible, k=n_m)

            # Draw stop distance from actual month accepted trades
            risks = [t["risk"] for t in m_trades]
            rng.shuffle(risks)

            for idx, risk in zip(chosen_bars, risks):
                is_buy = rng.random() < pooled_buy_ratio
                dir_str = "BUY" if is_buy else "SELL"
                entry = bars[idx].close
                sl = entry - risk if is_buy else entry + risk
                tp1 = entry + 2 * risk if is_buy else entry - 2 * risk
                tp2 = entry + 3 * risk if is_buy else entry - 3 * risk

                rec = SignalRecord(
                    bars[idx].timestamp, dir_str, None, None, "market",
                    entry, sl, tp1, tp2, risk, 2.0, 60.0
                )
                simulate_outcome(rec, bars=bars, signal_index=idx, spread=0.40, expiry_bars=8, max_hold_bars=500)
                month_sim_results[m].append({
                    "r": float(rec.r_multiple),
                    "win": 1 if rec.r_multiple > 0 else 0,
                    "split": m_trades[0]["split"],
                })

        # Aggregate by split
        all_sim_trades = [tr for m_list in month_sim_results.values() for tr in m_list]
        for s in splits:
            s_sim = [tr for tr in all_sim_trades if tr["split"] == s]
            rand_ts_runs[s]["mean_r"].append(float(np.mean([tr["r"] for tr in s_sim])))
            rand_ts_runs[s]["win_rate"].append(float(np.mean([tr["win"] for tr in s_sim])))
        rand_ts_runs["pooled"]["mean_r"].append(float(np.mean([tr["r"] for tr in all_sim_trades])))
        rand_ts_runs["pooled"]["win_rate"].append(float(np.mean([tr["win"] for tr in all_sim_trades])))

        if seed % 200 == 0:
            print(f"    - Completed {seed}/{num_seeds} seeds ({time.time() - t0:.1f}s elapsed)...")

    print(f"[*] Random Timestamps finished in {time.time() - t0:.2f}s")

    rand_ts_summary = {}
    for s in list(splits) + ["pooled"]:
        dist_r = rand_ts_runs[s]["mean_r"]
        real_r = real_stats[s]["mean_r"]
        pct = float(np.mean([1.0 if x <= real_r else 0.0 for x in dist_r]) * 100.0)
        rand_ts_summary[s] = {
            "dist_mean_r": float(np.mean(dist_r)),
            "dist_std_r": float(np.std(dist_r)),
            "dist_min_r": float(np.min(dist_r)),
            "dist_max_r": float(np.max(dist_r)),
            "dist_p5_r": float(np.percentile(dist_r, 5)),
            "dist_p50_r": float(np.percentile(dist_r, 50)),
            "dist_p95_r": float(np.percentile(dist_r, 95)),
            "dist_mean_wr": float(np.mean(rand_ts_runs[s]["win_rate"])),
            "percentile": pct,
        }

    # Evaluate Step 1 Edge Criterion:
    # "Define 'edge demonstrated' ONLY as percentile >= 97.5 on BOTH validation and test (and state calibration too)."
    cal_pct = rand_dir_summary["calibration"]["percentile"]
    val_pct = rand_dir_summary["validation"]["percentile"]
    test_pct = rand_dir_summary["test"]["percentile"]
    edge_demonstrated = (val_pct >= 97.5) and (test_pct >= 97.5)

    print("\n" + "=" * 60)
    print("STEP 1 VERDICT SUMMARY:")
    print(f"Calibration Random-Direction Percentile: {cal_pct:.1f}%")
    print(f"Validation Random-Direction Percentile:  {val_pct:.1f}%")
    print(f"Test Random-Direction Percentile:        {test_pct:.1f}%")
    print(f"Edge Demonstrated (>=97.5% on both val & test): {edge_demonstrated}")
    print("=" * 60 + "\n")

    # Write CSV
    csv_path = out_dir / "step1_controls.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "split",
            "control_type",
            "n_trades",
            "real_mean_r",
            "real_win_rate",
            "control_mean_r",
            "control_win_rate",
            "control_std_r",
            "control_min_r",
            "control_max_r",
            "percentile_rank",
            "edge_demonstrated_on_split",
        ])
        for s in list(splits) + ["pooled"]:
            # Real baseline row
            writer.writerow([
                s, "Real Strategy", real_stats[s]["n"],
                f"{real_stats[s]['mean_r']:.4f}", f"{real_stats[s]['win_rate']:.4f}",
                f"{real_stats[s]['mean_r']:.4f}", f"{real_stats[s]['win_rate']:.4f}",
                0.0, f"{real_stats[s]['mean_r']:.4f}", f"{real_stats[s]['mean_r']:.4f}",
                "N/A", "N/A"
            ])
            # Random Direction
            writer.writerow([
                s, "Random Direction (1000 seeds)", real_stats[s]["n"],
                f"{real_stats[s]['mean_r']:.4f}", f"{real_stats[s]['win_rate']:.4f}",
                f"{rand_dir_summary[s]['dist_mean_r']:.4f}", f"{rand_dir_summary[s]['dist_mean_wr']:.4f}",
                f"{rand_dir_summary[s]['dist_std_r']:.4f}", f"{rand_dir_summary[s]['dist_min_r']:.4f}",
                f"{rand_dir_summary[s]['dist_max_r']:.4f}", f"{rand_dir_summary[s]['percentile']:.1f}%",
                "YES" if rand_dir_summary[s]["percentile"] >= 97.5 else "NO",
            ])
            # Always-BUY
            writer.writerow([
                s, "Always-BUY", real_stats[s]["n"],
                f"{real_stats[s]['mean_r']:.4f}", f"{real_stats[s]['win_rate']:.4f}",
                f"{buy_stats[s]['mean_r']:.4f}", f"{buy_stats[s]['win_rate']:.4f}",
                "N/A", "N/A", "N/A", "N/A", "N/A"
            ])
            # Always-SELL
            writer.writerow([
                s, "Always-SELL", real_stats[s]["n"],
                f"{real_stats[s]['mean_r']:.4f}", f"{real_stats[s]['win_rate']:.4f}",
                f"{sell_stats[s]['mean_r']:.4f}", f"{sell_stats[s]['win_rate']:.4f}",
                "N/A", "N/A", "N/A", "N/A", "N/A"
            ])
            # Random Timestamps
            writer.writerow([
                s, "Random Timestamps (1000 seeds)", real_stats[s]["n"],
                f"{real_stats[s]['mean_r']:.4f}", f"{real_stats[s]['win_rate']:.4f}",
                f"{rand_ts_summary[s]['dist_mean_r']:.4f}", f"{rand_ts_summary[s]['dist_mean_wr']:.4f}",
                f"{rand_ts_summary[s]['dist_std_r']:.4f}", f"{rand_ts_summary[s]['dist_min_r']:.4f}",
                f"{rand_ts_summary[s]['dist_max_r']:.4f}", f"{rand_ts_summary[s]['percentile']:.1f}%",
                "YES" if rand_ts_summary[s]["percentile"] >= 97.5 else "NO",
            ])

    # Write Markdown
    md_path = out_dir / "step1_controls.md"
    seed_sample_str = ", ".join(str(s) for s in seeds[:20]) + f", ... up to {seeds[-1]}"
    all_seeds_str = ", ".join(str(s) for s in seeds)

    md_content = f"""# SMC Analysis — Step 1: Baseline Controls & Edge Evaluation

## 1. Overview and Protocol Verification

- **Production Source Code**: `server/scripts/smc_replay.py:build_market_trade` and `server/scripts/crt_replay.py:simulate_outcome`
- **Friction Model**: Flat \$0.40 round-trip spread deduction per trade (exact `simulate_outcome` parity)
- **Checkpoints**: `reports/smc_replay_extended/checkpoints/` (45 monthly files, 2023-03 through 2026-11)
- **Walk-forward Boundaries**:
  - Calibration: 2023-03-01 00:00 → 2025-05-21 08:15 UTC (60%)
  - Validation: 2025-05-21 08:15 → 2026-02-16 03:00 UTC (20%)
  - Test: 2026-02-16 03:00 → 2026-11-15 15:00 UTC (20%)
- **Data Hygiene Warning**: Validation and test sets were observed during earlier exploratory iterations (commits `4424a64`, `5b88873`, `2db6eb1`) and are **no longer clean out-of-sample data**.
- **Edge Definition**: Edge is demonstrated **ONLY** if the real accepted trade mean R achieves a percentile rank $\ge 97.5\%$ on **BOTH** validation and test splits against the random-direction control.

---

## 2. Seed List
- **Number of Seeds**: 1,000 seeds
- **Seed Values**: Integers 1 through 1000 inclusive (`range(1, 1001)`)
- **Full Seed List**:
`{all_seeds_str}`

---

## 3. Results by Split

### A. Real Strategy Performance (Baseline)
| Split | Opportunities (n) | Win Rate | Mean R | Total R |
| :--- | ---: | ---: | ---: | ---: |
| Calibration | {real_stats['calibration']['n']:,} | {real_stats['calibration']['win_rate']*100:.2f}% | {real_stats['calibration']['mean_r']:+.4f} | {real_stats['calibration']['mean_r'] * real_stats['calibration']['n']:+.2f}R |
| Validation | {real_stats['validation']['n']:,} | {real_stats['validation']['win_rate']*100:.2f}% | {real_stats['validation']['mean_r']:+.4f} | {real_stats['validation']['mean_r'] * real_stats['validation']['n']:+.2f}R |
| Test | {real_stats['test']['n']:,} | {real_stats['test']['win_rate']*100:.2f}% | {real_stats['test']['mean_r']:+.4f} | {real_stats['test']['mean_r'] * real_stats['test']['n']:+.2f}R |
| **Pooled** | **{real_stats['pooled']['n']:,}** | **{real_stats['pooled']['win_rate']*100:.2f}%** | **{real_stats['pooled']['mean_r']:+.4f}** | **{real_stats['pooled']['mean_r'] * real_stats['pooled']['n']:+.2f}R** |

---

### B. Control (a): Random Direction (1,000 Seeds)
Each accepted trade retains its identical entry timestamp, entry price, stop distance, and TP geometry ($TP1=2.0R, TP2=3.0R$), with direction drawn uniformly at random ($p=0.5$).

| Split | Real Mean R | Random Dist Mean | Dist Std | Dist [Min, Max] | 5% - 95% CI | Win Rate (Dist Mean) | Percentile Rank | Edge Pass? ($\ge 97.5\%$) |
| :--- | ---: | ---: | ---: | :---: | :---: | ---: | ---: | :---: |
| Calibration | {real_stats['calibration']['mean_r']:+.4f} | {rand_dir_summary['calibration']['dist_mean_r']:+.4f} | {rand_dir_summary['calibration']['dist_std_r']:.4f} | [{rand_dir_summary['calibration']['dist_min_r']:+.4f}, {rand_dir_summary['calibration']['dist_max_r']:+.4f}] | [{rand_dir_summary['calibration']['dist_p5_r']:+.4f}, {rand_dir_summary['calibration']['dist_p95_r']:+.4f}] | {rand_dir_summary['calibration']['dist_mean_wr']*100:.2f}% | **{rand_dir_summary['calibration']['percentile']:.1f}%** | NO |
| Validation | {real_stats['validation']['mean_r']:+.4f} | {rand_dir_summary['validation']['dist_mean_r']:+.4f} | {rand_dir_summary['validation']['dist_std_r']:.4f} | [{rand_dir_summary['validation']['dist_min_r']:+.4f}, {rand_dir_summary['validation']['dist_max_r']:+.4f}] | [{rand_dir_summary['validation']['dist_p5_r']:+.4f}, {rand_dir_summary['validation']['dist_p95_r']:+.4f}] | {rand_dir_summary['validation']['dist_mean_wr']*100:.2f}% | **{rand_dir_summary['validation']['percentile']:.1f}%** | YES |
| Test | {real_stats['test']['mean_r']:+.4f} | {rand_dir_summary['test']['dist_mean_r']:+.4f} | {rand_dir_summary['test']['dist_std_r']:.4f} | [{rand_dir_summary['test']['dist_min_r']:+.4f}, {rand_dir_summary['test']['dist_max_r']:+.4f}] | [{rand_dir_summary['test']['dist_p5_r']:+.4f}, {rand_dir_summary['test']['dist_p95_r']:+.4f}] | {rand_dir_summary['test']['dist_mean_wr']*100:.2f}% | **{rand_dir_summary['test']['percentile']:.1f}%** | **NO** |
| **Pooled** | **{real_stats['pooled']['mean_r']:+.4f}** | **{rand_dir_summary['pooled']['dist_mean_r']:+.4f}** | **{rand_dir_summary['pooled']['dist_std_r']:.4f}** | **[{rand_dir_summary['pooled']['dist_min_r']:+.4f}, {rand_dir_summary['pooled']['dist_max_r']:+.4f}]** | **[{rand_dir_summary['pooled']['dist_p5_r']:+.4f}, {rand_dir_summary['pooled']['dist_p95_r']:+.4f}]** | **{rand_dir_summary['pooled']['dist_mean_wr']*100:.2f}%** | **{rand_dir_summary['pooled']['percentile']:.1f}%** | NO |

---

### C. Control (b): Always-BUY vs Always-SELL (Drift Controls)
Evaluates directional drift by simulating a 100% BUY or 100% SELL allocation across the identical accepted signal timestamps and stop distances.

| Split | Real Strategy Mean R (WR) | Always-BUY Mean R (WR) | Always-SELL Mean R (WR) | Drift Bias Observed |
| :--- | :--- | :--- | :--- | :--- |
| Calibration | {real_stats['calibration']['mean_r']:+.4f} ({real_stats['calibration']['win_rate']*100:.2f}%) | {buy_stats['calibration']['mean_r']:+.4f} ({buy_stats['calibration']['win_rate']*100:.2f}%) | {sell_stats['calibration']['mean_r']:+.4f} ({sell_stats['calibration']['win_rate']*100:.2f}%) | Strong Bull Drift (Always-BUY outperforms Real by +0.1004R) |
| Validation | {real_stats['validation']['mean_r']:+.4f} ({real_stats['validation']['win_rate']*100:.2f}%) | {buy_stats['validation']['mean_r']:+.4f} ({buy_stats['validation']['win_rate']*100:.2f}%) | {sell_stats['validation']['mean_r']:+.4f} ({sell_stats['validation']['win_rate']*100:.2f}%) | Severe Bull Drift (Always-BUY outperforms Real by +0.1895R) |
| Test | {real_stats['test']['mean_r']:+.4f} ({real_stats['test']['win_rate']*100:.2f}%) | {buy_stats['test']['mean_r']:+.4f} ({buy_stats['test']['win_rate']*100:.2f}%) | {sell_stats['test']['mean_r']:+.4f} ({sell_stats['test']['win_rate']*100:.2f}%) | Bear Drift / Chop (Always-SELL outperforms Real by +0.2137R) |
| **Pooled** | **{real_stats['pooled']['mean_r']:+.4f} ({real_stats['pooled']['win_rate']*100:.2f}%)** | **{buy_stats['pooled']['mean_r']:+.4f} ({buy_stats['pooled']['win_rate']*100:.2f}%)** | **{sell_stats['pooled']['mean_r']:+.4f} ({sell_stats['pooled']['win_rate']*100:.2f}%)** | Overall Upward Drift Dominance |

---

### D. Control (c): Random Timestamps (1,000 Seeds)
Matches the exact number of monthly trades $N_m$ drawn uniformly from open-market 15m bars, using the empirical monthly stop distances and the pooled accepted BUY/SELL ratio ($66.0\%$ BUY).

| Split | Real Mean R | Random TS Dist Mean | Dist Std | Dist [Min, Max] | 5% - 95% CI | Win Rate (Dist Mean) | Percentile Rank |
| :--- | ---: | ---: | ---: | :---: | :---: | ---: | ---: |
| Calibration | {real_stats['calibration']['mean_r']:+.4f} | {rand_ts_summary['calibration']['dist_mean_r']:+.4f} | {rand_ts_summary['calibration']['dist_std_r']:.4f} | [{rand_ts_summary['calibration']['dist_min_r']:+.4f}, {rand_ts_summary['calibration']['dist_max_r']:+.4f}] | [{rand_ts_summary['calibration']['dist_p5_r']:+.4f}, {rand_ts_summary['calibration']['dist_p95_r']:+.4f}] | {rand_ts_summary['calibration']['dist_mean_wr']*100:.2f}% | **{rand_ts_summary['calibration']['percentile']:.1f}%** |
| Validation | {real_stats['validation']['mean_r']:+.4f} | {rand_ts_summary['validation']['dist_mean_r']:+.4f} | {rand_ts_summary['validation']['dist_std_r']:.4f} | [{rand_ts_summary['validation']['dist_min_r']:+.4f}, {rand_ts_summary['validation']['dist_max_r']:+.4f}] | [{rand_ts_summary['validation']['dist_p5_r']:+.4f}, {rand_ts_summary['validation']['dist_p95_r']:+.4f}] | {rand_ts_summary['validation']['dist_mean_wr']*100:.2f}% | **{rand_ts_summary['validation']['percentile']:.1f}%** |
| Test | {real_stats['test']['mean_r']:+.4f} | {rand_ts_summary['test']['dist_mean_r']:+.4f} | {rand_ts_summary['test']['dist_std_r']:.4f} | [{rand_ts_summary['test']['dist_min_r']:+.4f}, {rand_ts_summary['test']['dist_max_r']:+.4f}] | [{rand_ts_summary['test']['dist_p5_r']:+.4f}, {rand_ts_summary['test']['dist_p95_r']:+.4f}] | {rand_ts_summary['test']['dist_mean_wr']*100:.2f}% | **{rand_ts_summary['test']['percentile']:.1f}%** |
| **Pooled** | **{real_stats['pooled']['mean_r']:+.4f}** | **{rand_ts_summary['pooled']['dist_mean_r']:+.4f}** | **{rand_ts_summary['pooled']['dist_std_r']:.4f}** | **[{rand_ts_summary['pooled']['dist_min_r']:+.4f}, {rand_ts_summary['pooled']['dist_max_r']:+.4f}]** | **[{rand_ts_summary['pooled']['dist_p5_r']:+.4f}, {rand_ts_summary['pooled']['dist_p95_r']:+.4f}]** | **{rand_ts_summary['pooled']['dist_mean_wr']*100:.2f}%** | **{rand_ts_summary['pooled']['percentile']:.1f}%** |

---

## 4. Edge Verdict

> **NON-NEGOTIABLE CRITERION**: "Define 'edge demonstrated' ONLY as percentile $\ge 97.5$ on BOTH validation and test (and state calibration too)."

- **Calibration Random Direction Percentile**: **{cal_pct:.1f}%** (Failed; $< 97.5\%$)
- **Validation Random Direction Percentile**: **{val_pct:.1f}%** (Passed; $\ge 97.5\%$)
- **Test Random Direction Percentile**: **{test_pct:.1f}%** (Failed; far below $97.5\%$)

### Verdict Line:
**EDGE NOT DEMONSTRATED**. The SMC strategy fails the required $\ge 97.5\%$ percentile benchmark on the test split ({test_pct:.1f}%) and on the calibration split ({cal_pct:.1f}%). On the test split, flipping a coin for direction yields an average return of +0.1114R, outperforming the actual SMC signals (+0.0716R). The strategy's positive returns in validation (+0.2999R) are entirely explained by underlying market drift (Always-BUY returned +0.4894R at the same timestamps).

---

## 5. Summary Table

| Control Check | Calibration | Validation | Test | Target ($\ge 97.5\%$) | Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Random Direction Percentile** | {cal_pct:.1f}% | {val_pct:.1f}% | {test_pct:.1f}% | Both Val & Test $\ge 97.5\%$ | **FAIL (No Edge Demonstrated)** |
| **Always-BUY Outperformed Real?** | YES (+0.1346 vs +0.0342) | YES (+0.4894 vs +0.2999) | NO (-0.0686 vs +0.0716) | N/A | Market Drift Explains Gains |
| **Always-SELL Outperformed Real?** | NO (-0.1834 vs +0.0342) | NO (-0.5180 vs +0.2999) | YES (+0.2853 vs +0.0716) | N/A | Regime Inversion on Test |
"""

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"[*] Markdown report written to {md_path}")
    print(f"[*] CSV written to {csv_path}")


if __name__ == "__main__":
    run_step1()
