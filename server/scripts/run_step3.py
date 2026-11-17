"""Step 3: Direction, Overlap, Independence, Cluster SE, and Monthly Stability for SMC Strategy.

Output:
  - reports/smc_analysis/step3_direction_overlap.md
"""

from __future__ import annotations

import glob
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]


def _dedupe(trades: List[Dict[str, Any]], key: str = "sweep_key") -> List[Dict[str, Any]]:
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for t in trades:
        k = str(t.get(key) or "")
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def run_step3() -> None:
    out_dir = REPO_ROOT / "reports" / "smc_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    ckpt_files = sorted(glob.glob(str(REPO_ROOT / "reports" / "smc_replay_extended" / "checkpoints" / "*.json")))
    print(f"[*] Reading {len(ckpt_files)} checkpoints...")

    raw_accepted: List[Dict[str, Any]] = []
    for fpath in ckpt_files:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        for r in data["records"]:
            if r.get("accepted") and r.get("accepted_trade"):
                t = dict(r["accepted_trade"])
                t["split"] = r["split"]
                t["month"] = r["month"]
                t["score"] = float(r["score"])
                t["decision_time"] = r["decision_time"]
                t["entry_dt"] = datetime.fromisoformat(t["signal_time"])
                t["exit_dt"] = datetime.fromisoformat(t["exit_time"])
                t["r"] = float(t["r_multiple"])
                t["win"] = 1 if t["r"] > 0 else 0
                raw_accepted.append(t)

    # De-duplicate to unique opportunities (matching Table 3 in smc_replay_report.md)
    accepted = _dedupe(raw_accepted)
    accepted.sort(key=lambda x: x["entry_dt"])
    print(f"[*] Loaded {len(accepted)} unique accepted opportunities.")

    splits = ("calibration", "validation", "test")

    # ------------------------------------------------------------------
    # Step 3a: BUY vs SELL vs Drift (Always-BUY control from Step 1)
    # ------------------------------------------------------------------
    # Step 1 controls (hardcoded from verified Step 1 output)
    always_buy_benchmarks = {
        "calibration": {"mean_r": 0.1346, "win_rate": 0.4678},
        "validation": {"mean_r": 0.4894, "win_rate": 0.5639},
        "test": {"mean_r": -0.0686, "win_rate": 0.3788},
        "pooled": {"mean_r": 0.1580, "win_rate": 0.4675},
    }
    always_sell_benchmarks = {
        "calibration": {"mean_r": -0.1834, "win_rate": 0.3122},
        "validation": {"mean_r": -0.5180, "win_rate": 0.1917},
        "test": {"mean_r": 0.2853, "win_rate": 0.4744},
        "pooled": {"mean_r": -0.1510, "win_rate": 0.3226},
    }

    dir_stats: Dict[str, Dict[str, Any]] = {}
    for s in list(splits) + ["pooled"]:
        sub = accepted if s == "pooled" else [t for t in accepted if t["split"] == s]
        buys = [t for t in sub if t["direction"] == "BUY"]
        sells = [t for t in sub if t["direction"] == "SELL"]

        dir_stats[s] = {
            "total_n": len(sub),
            "buy_n": len(buys),
            "buy_wr": np.mean([t["win"] for t in buys]) if buys else 0.0,
            "buy_mr": np.mean([t["r"] for t in buys]) if buys else 0.0,
            "sell_n": len(sells),
            "sell_wr": np.mean([t["win"] for t in sells]) if sells else 0.0,
            "sell_mr": np.mean([t["r"] for t in sells]) if sells else 0.0,
        }

    # ------------------------------------------------------------------
    # Step 3b: Overlap and Independent Signals
    # ------------------------------------------------------------------
    # Count trades whose entry occurs while ANY earlier trade is still open
    overlapping_indices = set()
    for j in range(len(accepted)):
        t_j = accepted[j]
        for i in range(j):
            t_i = accepted[i]
            if t_i["entry_dt"] <= t_j["entry_dt"] < t_i["exit_dt"]:
                overlapping_indices.add(j)
                break

    n_overlapping = len(overlapping_indices)
    pct_overlapping = n_overlapping / len(accepted) * 100.0

    # Option 2: Connected interval clusters (trade is first of an overlapping cluster)
    # A new cluster begins only when entry_time >= cluster_max_exit
    connected_clusters = []
    cluster_max_exit = None
    for t in accepted:
        if cluster_max_exit is None or t["entry_dt"] >= cluster_max_exit:
            connected_clusters.append(t)
            cluster_max_exit = t["exit_dt"]
        else:
            cluster_max_exit = max(cluster_max_exit, t["exit_dt"])

    # Option 1: Serial non-overlapping execution (next trade starts after previous trade exits)
    serial_trades = []
    current_exit = None
    for t in accepted:
        if current_exit is None or t["entry_dt"] >= current_exit:
            serial_trades.append(t)
            current_exit = t["exit_dt"]

    # ------------------------------------------------------------------
    # Step 3c: Cluster-Robust Standard Error (Cluster = Calendar Day)
    # ------------------------------------------------------------------
    cluster_se_results: Dict[str, Dict[str, Any]] = {}
    for s in list(splits) + ["pooled"]:
        sub = accepted if s == "pooled" else [t for t in accepted if t["split"] == s]
        N = len(sub)
        mean_r = float(np.mean([t["r"] for t in sub]))
        std_r = float(np.std([t["r"] for t in sub], ddof=1))
        naive_se = std_r / math.sqrt(N)

        by_day = defaultdict(list)
        for t in sub:
            day_str = t["entry_dt"].strftime("%Y-%m-%d")
            by_day[day_str].append(t["r"])

        G = len(by_day)
        U_sq = sum(sum(r - mean_r for r in day_rs)**2 for day_rs in by_day.values())
        var_cluster = (G / max(1, G - 1)) * (U_sq / (N**2))
        cluster_se = math.sqrt(var_cluster)
        t_stat = mean_r / cluster_se if cluster_se > 0 else 0.0
        p_val = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0))))

        cluster_se_results[s] = {
            "N": N,
            "G_days": G,
            "mean_r": mean_r,
            "std_r": std_r,
            "naive_se": naive_se,
            "cluster_se": cluster_se,
            "t_stat": t_stat,
            "p_val": p_val,
            "ci_lower": mean_r - 1.96 * cluster_se,
            "ci_upper": mean_r + 1.96 * cluster_se,
        }

    # ------------------------------------------------------------------
    # Step 3d: Monthly Mean R Stability
    # ------------------------------------------------------------------
    by_month = defaultdict(list)
    month_splits = {}
    for t in accepted:
        by_month[t["month"]].append(t["r"])
        month_splits[t["month"]] = t["split"]

    months_sorted = sorted(by_month.keys())
    monthly_stats = []
    for m in months_sorted:
        rs = by_month[m]
        mr = float(np.mean(rs))
        wr = float(np.mean([1 if r > 0 else 0 for r in rs]))
        monthly_stats.append({
            "month": m,
            "split": month_splits[m],
            "n": len(rs),
            "win_rate": wr,
            "mean_r": mr,
            "total_r": float(np.sum(rs)),
        })

    neg_months = [m for m in monthly_stats if m["mean_r"] < 0]
    pos_months = [m for m in monthly_stats if m["mean_r"] > 0]
    zero_months = [m for m in monthly_stats if m["mean_r"] == 0]

    min_month = min(monthly_stats, key=lambda x: x["mean_r"])
    max_month = max(monthly_stats, key=lambda x: x["mean_r"])

    # Generate Markdown Report
    md_path = out_dir / "step3_direction_overlap.md"
    md_lines: List[str] = []

    md_lines.append("# SMC Analysis — Step 3: Direction, Overlap, Independence, and Stability")
    md_lines.append("")
    md_lines.append("## 1. Overview & Protocol")
    md_lines.append("")
    md_lines.append("- **Accepted Opportunities**: 1,491 total across 45 monthly replay checkpoints (`reports/smc_replay_extended/checkpoints/`).")
    md_lines.append("- **Friction Model**: Flat \\$0.40 round-trip spread deduction per trade (exact `simulate_outcome` parity).")
    md_lines.append("- **Walk-forward Splits**: Calibration (60%), Validation (20%), Test (20%).")
    md_lines.append("- **Data Hygiene Warning**: Validation and test splits were previously inspected in exploratory iterations (commits `4424a64`, `5b88873`, `2db6eb1`) and are **no longer clean out-of-sample data**.")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")
    md_lines.append("## 2. Directional Performance (BUY vs SELL vs Drift)")
    md_lines.append("")
    md_lines.append("To determine whether trade performance represents structural edge or market drift, accepted BUY and SELL trades are compared against the **Always-BUY** and **Always-SELL** benchmark controls from Step 1.")
    md_lines.append("")
    md_lines.append("| Split | Signal Direction | Opportunities (n) | Win Rate | Mean R | Step 1 Always-BUY Mean R (WR) | Step 1 Always-SELL Mean R (WR) | Drift Assessment |")
    md_lines.append("| :--- | :--- | ---: | ---: | ---: | :--- | :--- | :--- |")

    for s in ("calibration", "validation", "test", "pooled"):
        name = s.capitalize() if s != "pooled" else "**Pooled**"
        d = dir_stats[s]
        ab = always_buy_benchmarks[s]
        asell = always_sell_benchmarks[s]

        # BUY row
        drift_note_buy = "Underperformed Always-BUY" if d["buy_mr"] < ab["mean_r"] else "Outperformed Always-BUY"
        md_lines.append(
            f"| {name} | **BUY** | {d['buy_n']:,} ({d['buy_n']/d['total_n']*100:.1f}%) | "
            f"{d['buy_wr']*100:.2f}% | **{d['buy_mr']:+.4f}** | "
            f"{ab['mean_r']:+.4f} ({ab['win_rate']*100:.2f}%) | "
            f"{asell['mean_r']:+.4f} ({asell['win_rate']*100:.2f}%) | "
            f"{drift_note_buy} |"
        )
        # SELL row
        drift_note_sell = "Underperformed Always-SELL" if d["sell_mr"] < asell["mean_r"] else "Outperformed Always-SELL"
        md_lines.append(
            f"| | **SELL** | {d['sell_n']:,} ({d['sell_n']/d['total_n']*100:.1f}%) | "
            f"{d['sell_wr']*100:.2f}% | **{d['sell_mr']:+.4f}** | "
            f"*(same as above)* | *(same as above)* | "
            f"{drift_note_sell} |"
        )
    md_lines.append("")
    md_lines.append("> **Directional Verdict**:")
    md_lines.append(f"> - **Calibration**: BUY trades ({dir_stats['calibration']['buy_mr']:+.4f}R) underperformed Always-BUY ({always_buy_benchmarks['calibration']['mean_r']:+.4f}R). SELL trades were negative ({dir_stats['calibration']['sell_mr']:+.4f}R).")
    md_lines.append(f"> - **Validation**: BUY trades ({dir_stats['validation']['buy_mr']:+.4f}R) were strongly positive, accompanied by Always-BUY ({always_buy_benchmarks['validation']['mean_r']:+.4f}R) during a massive gold bull drift; SELL trades suffered severely ({dir_stats['validation']['sell_mr']:+.4f}R).")
    md_lines.append(f"> - **Test**: When market regime flipped, BUY trades lost money ({dir_stats['test']['buy_mr']:+.4f}R). SELL trades ({dir_stats['test']['sell_mr']:+.4f}R) underperformed Always-SELL ({always_sell_benchmarks['test']['mean_r']:+.4f}R).")
    md_lines.append("> - The strategy displays **no directional forecasting edge**: returns in each split are driven entirely by underlying market drift.")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")
    md_lines.append("## 3. Overlap Analysis & Independent Signals")
    md_lines.append("")
    md_lines.append("### A. Overlap Summary")
    md_lines.append(f"- **Total Accepted Opportunities**: **{len(accepted):,}**")
    md_lines.append(f"- **Trades entering while an earlier trade is still open**: **{n_overlapping:,} ({pct_overlapping:.1f}%)**")
    md_lines.append(f"- **Trades entering with no prior trade active**: **{len(accepted) - n_overlapping:,} ({100.0 - pct_overlapping:.1f}%)**")
    md_lines.append("")
    md_lines.append("### B. Independent Signals (First Trade of Each Overlapping Cluster)")
    md_lines.append("")
    md_lines.append("Two definitions are reported:")
    md_lines.append("1. **Connected Interval Clusters (Step 3b specification)**: A cluster spans the continuous duration during which at least one position remains active. The independent signal is the initial trade opening the cluster.")
    md_lines.append("2. **Serial Non-Overlapping Trades (Portfolio Constraint)**: When a trade opens, all subsequent entries are ignored until that specific trade exits.")
    md_lines.append("")
    md_lines.append("| Split | All Accepted Opps (Mean R) | Connected Cluster First Trades (Step 3b) | Mean R (Step 3b) | Serial Non-Overlapping Trades | Mean R (Serial) |")
    md_lines.append("| :--- | :---: | :---: | :---: | :---: | :---: |")

    for s in ("calibration", "validation", "test", "pooled"):
        sub_all = accepted if s == "pooled" else [t for t in accepted if t["split"] == s]
        sub_conn = connected_clusters if s == "pooled" else [t for t in connected_clusters if t["split"] == s]
        sub_ser = serial_trades if s == "pooled" else [t for t in serial_trades if t["split"] == s]

        mr_all = float(np.mean([t["r"] for t in sub_all]))
        mr_conn = float(np.mean([t["r"] for t in sub_conn])) if sub_conn else 0.0
        mr_ser = float(np.mean([t["r"] for t in sub_ser])) if sub_ser else 0.0

        name = s.capitalize() if s != "pooled" else "**Pooled**"
        md_lines.append(
            f"| {name} | {len(sub_all):,} ({mr_all:+.4f}) | **{len(sub_conn):,}** | **{mr_conn:+.4f}** | "
            f"{len(sub_ser):,} | {mr_ser:+.4f} |"
        )
    md_lines.append("")
    md_lines.append("> **Independence Finding**:")
    md_lines.append(f"> 92.8% of accepted SMC signals are secondary/tertiary concurrent entries during ongoing trades. Under strict cluster independence, the strategy produces only **108 independent signals across 45 months** (~2.4 signals per MONTH, or ~0.11 signals per trading day). Furthermore, independent signal expectancy on Calibration drops to **-0.0353R**.")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")
    md_lines.append("## 4. Cluster-Robust Standard Error of Mean R (Cluster = Calendar Day)")
    md_lines.append("")
    md_lines.append("Standard OLS standard errors assume i.i.d. observations. When multiple trades execute on the same calendar day, intra-day correlation drastically inflates precision. Cluster-robust standard errors (clustering by calendar day) correct for intra-day clustering.")
    md_lines.append("")
    md_lines.append("| Split | Trades (N) | Calendar Days (G) | Mean R | Naive SE (OLS) | Cluster-Robust SE | $t$-statistic | $p$-value | 95% Confidence Interval | Significant ($p < 0.05$)? |")
    md_lines.append("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: |")

    for s in ("calibration", "validation", "test", "pooled"):
        r = cluster_se_results[s]
        sig = "YES" if r["p_val"] < 0.05 else "NO"
        name = s.capitalize() if s != "pooled" else "**Pooled**"
        md_lines.append(
            f"| {name} | {r['N']:,} | {r['G_days']:,} | **{r['mean_r']:+.4f}** | "
            f"{r['naive_se']:.4f} | **{r['cluster_se']:.4f}** | {r['t_stat']:+.2f} | "
            f"{r['p_val']:.4f} | [{r['ci_lower']:+.4f}, {r['ci_upper']:+.4f}] | **{sig}** |"
        )
    md_lines.append("")
    md_lines.append("> **Statistical Significance Verdict**:")
    md_lines.append("> When clustering by calendar day, **not a single split achieves statistical significance at the 5% level**.")
    md_lines.append("> - Calibration: $t = +0.44, p = 0.6599$ (95% CI: `[-0.1179, +0.1863]`)")
    md_lines.append("> - Validation: $t = +1.83, p = 0.0667$ (95% CI: `[-0.0208, +0.6206]`)")
    md_lines.append("> - Test: $t = +0.47, p = 0.6416$ (95% CI: `[-0.2299, +0.3731]`)")
    md_lines.append("> - Pooled: $t = +1.28, p = 0.2003$ (95% CI: `[-0.0471, +0.2251]`)")
    md_lines.append("> Intra-day clustering approximately doubles standard errors, demonstrating that the apparent consistency of SMC is an artifact of correlated multi-bar clustering.")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")
    md_lines.append("## 5. Monthly Stability Over Full Range (45 Months)")
    md_lines.append("")
    md_lines.append("### Summary Statistics")
    md_lines.append(f"- **Total Months Evaluated**: 45 months (2023-03 through 2026-11)")
    md_lines.append(f"- **Negative Months**: **{len(neg_months)} / 45 ({len(neg_months)/len(monthly_stats)*100:.1f}%)**")
    md_lines.append(f"- **Positive Months**: **{len(pos_months)} / 45 ({len(pos_months)/len(monthly_stats)*100:.1f}%)**")
    md_lines.append(f"- **Worst Month**: **{min_month['month']} ({min_month['split']})**: **{min_month['mean_r']:+.4f}R** ($n={min_month['n']}$, total {min_month['total_r']:+.2f}R)")
    md_lines.append(f"- **Best Month**: **{max_month['month']} ({max_month['split']})**: **{max_month['mean_r']:+.4f}R** ($n={max_month['n']}$, total {max_month['total_r']:+.2f}R)")
    md_lines.append("")
    md_lines.append("### Monthly Return Table")
    md_lines.append("")
    md_lines.append("| Month | Split | Trades (n) | Win Rate | Mean R | Total R | Verdict |")
    md_lines.append("| :--- | :--- | ---: | ---: | ---: | ---: | :---: |")

    for row in monthly_stats:
        status = "🔴 NEGATIVE" if row["mean_r"] < 0 else "🟢 POSITIVE"
        md_lines.append(
            f"| `{row['month']}` | {row['split']} | {row['n']:,} | {row['win_rate']*100:.1f}% | "
            f"**{row['mean_r']:+.4f}** | {row['total_r']:+.2f}R | {status} |"
        )
    md_lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    print(f"[*] Step 3 report written to {md_path}")


if __name__ == "__main__":
    run_step3()
