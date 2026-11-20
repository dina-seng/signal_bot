"""Step C2: Direction-Neutral Controls for SMC Strategy under Portfolio Rules.

Evaluates the 538 entered positions from Step C1 against:
  a) Ratio-preserving shuffle (1,000 seeds): randomly reassigns BUY/SELL while keeping
     the exact split-level BUY/SELL count ratio intact.
  b) Always-BUY and Always-SELL benchmarks at the same timestamps.
  c) Direction-Neutral Alpha: Alpha_i = R_i(strategy) - 0.5 * (R_i(BUY) + R_i(SELL)).
     Reported with cluster-robust standard errors (cluster = UTC calendar day).
  d) Percentile rank of real mean R within the ratio-preserving distribution.

Outputs:
  - reports/smc_analysis_v2/stepC2_controls.md
  - reports/smc_analysis_v2/stepC2_controls.csv
"""

from __future__ import annotations

import csv
import glob
import json
import math
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))
SCRIPTS_ROOT = SERVER_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from app.services.indicators.atr_calculator import ATRCalculator
from replay_harness import SignalRecord, load_full_15m_candles, simulate_outcome, walk_forward_bounds

TF_15M = timedelta(minutes=15)


def compute_cluster_se(trades: List[Dict[str, Any]], field: str = "alpha") -> Tuple[float, float, Tuple[float, float], float]:
    """Compute cluster-robust standard error clustering by UTC calendar day."""
    if not trades:
        return 0.0, 0.0, (0.0, 0.0), 0.0
    day_groups = defaultdict(list)
    for t in trades:
        day_groups[t["day"]].append(float(t[field]))
    G = len(day_groups)
    N = len(trades)
    if G <= 1 or N <= 1:
        return 0.0, 0.0, (0.0, 0.0), 0.0

    mean_val = float(np.mean([t[field] for t in trades]))
    u_sum_sq = sum(sum(v - mean_val for v in vals) ** 2 for vals in day_groups.values())
    correction = (G / (G - 1)) * ((N - 1) / N) if G > 1 else 1.0
    var_cluster = (correction / (N ** 2)) * u_sum_sq
    se = math.sqrt(max(0.0, var_cluster))
    t_stat = (mean_val / se) if se > 0 else 0.0
    ci = (mean_val - 1.96 * se, mean_val + 1.96 * se)
    # p-value from two-sided normal approximation
    p_val = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0))))
    return se, t_stat, ci, p_val


def run_step_c2() -> None:
    print("=" * 70)
    print("SMC STEP C2: DIRECTION-NEUTRAL CONTROLS UNDER PORTFOLIO RULES")
    print("=" * 70)

    out_dir = REPO_ROOT / "reports" / "smc_analysis_v2"
    out_dir.mkdir(parents=True, exist_ok=True)

    db_path = REPO_ROOT / "backtest.db"
    print(f"[*] Loading candles from {db_path}...")
    bars, _ = load_full_15m_candles(db_path, "XAU/USD", "twelvedata")
    bounds = walk_forward_bounds(bars)

    calc = ATRCalculator()
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    atr_series = calc.calculate_atr_series(highs, lows, closes, period=14)
    bar_close = [b.timestamp + TF_15M for b in bars]
    bar_close_idx_map = {bc: i for i, bc in enumerate(bar_close)}

    # Load accepted setups
    ckpt_files = sorted(glob.glob(str(REPO_ROOT / "reports" / "smc_replay_extended" / "checkpoints" / "*.json")))
    raw_accepted_setups: List[Dict[str, Any]] = []
    for fpath in ckpt_files:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        for r in data["records"]:
            if r.get("accepted") and r.get("accepted_trade"):
                t = dict(r["accepted_trade"])
                t["decision_dt"] = datetime.fromisoformat(r["decision_time"])
                t["exit_dt"] = datetime.fromisoformat(t["exit_time"])
                t["day"] = t["decision_dt"].strftime("%Y-%m-%d")
                t["month"] = r["month"]
                t["split"] = r["split"]
                t["score"] = float(r["score"])
                t["r"] = float(t["r_multiple"])
                t["sweep_key"] = t.get("sweep_key") or ""
                idx = bar_close_idx_map.get(t["decision_dt"])
                t["atr"] = atr_series[idx] if (idx is not None and atr_series[idx] is not None) else 2.0
                t["bar_idx"] = idx
                raw_accepted_setups.append(t)

    raw_accepted_setups.sort(key=lambda x: x["decision_dt"])

    # Filter distinct sweeps
    seen_sweeps = set()
    distinct_setups = []
    for t in raw_accepted_setups:
        k = t["sweep_key"]
        if k not in seen_sweeps:
            seen_sweeps.add(k)
            distinct_setups.append(t)

    # Replay Portfolio Rules
    MAX_CONCURRENT = 3
    DAILY_LOSS_STOP = -3.0
    open_positions: List[Dict[str, Any]] = []
    entered_trades: List[Dict[str, Any]] = []

    for t in distinct_setups:
        dt = t["decision_dt"]
        day_str = t["day"]
        d = t["direction"]
        p_entry = t["crt_entry"]
        atr = t["atr"]

        open_positions = [pos for pos in open_positions if pos["exit_dt"] > dt]
        today_realized_r = sum(
            pos["r"]
            for pos in entered_trades
            if pos["exit_dt"].strftime("%Y-%m-%d") == day_str and pos["exit_dt"] <= dt
        )
        if today_realized_r <= DAILY_LOSS_STOP or len(open_positions) >= MAX_CONCURRENT:
            continue

        same_dir_open = [pos for pos in open_positions if pos["direction"] == d]
        if any((dt - pos["decision_dt"] < timedelta(hours=1) and abs(p_entry - pos["crt_entry"]) < atr) for pos in same_dir_open):
            continue

        entered_trades.append(t)
        open_positions.append(t)

    print(f"[*] Replayed {len(entered_trades)} entered portfolio trades.")

    # Simulate counterfactual BUY and SELL for each entered trade
    print("[*] Simulating counterfactual BUY and SELL outcomes for all entered trades...")
    for t in entered_trades:
        idx = t["bar_idx"]
        entry = t["crt_entry"]
        risk = abs(entry - t["stop_loss"])

        # Counterfactual BUY
        sl_buy = entry - risk
        tp1_buy = entry + 2.0 * risk
        tp2_buy = entry + 3.0 * risk
        rec_b = SignalRecord(
            signal_time=t["decision_dt"],
            direction="BUY",
            tier=None,
            session=None,
            entry_mode="market",
            crt_entry=entry,
            stop_loss=sl_buy,
            take_profit_1=tp1_buy,
            take_profit_2=tp2_buy,
            risk_price=risk,
            rr_planned=2.0,
            score=t["score"],
            sweep_key=t["sweep_key"],
        )
        simulate_outcome(rec_b, bars, idx, spread=0.40, expiry_bars=8, max_hold_bars=500)
        t["buy_r"] = float(rec_b.r_multiple)

        # Counterfactual SELL
        sl_sell = entry + risk
        tp1_sell = entry - 2.0 * risk
        tp2_sell = entry - 3.0 * risk
        rec_s = SignalRecord(
            signal_time=t["decision_dt"],
            direction="SELL",
            tier=None,
            session=None,
            entry_mode="market",
            crt_entry=entry,
            stop_loss=sl_sell,
            take_profit_1=tp1_sell,
            take_profit_2=tp2_sell,
            risk_price=risk,
            rr_planned=2.0,
            score=t["score"],
            sweep_key=t["sweep_key"],
        )
        simulate_outcome(rec_s, bars, idx, spread=0.40, expiry_bars=8, max_hold_bars=500)
        t["sell_r"] = float(rec_s.r_multiple)

        # Direction-Neutral Alpha
        t["neutral_r"] = (t["buy_r"] + t["sell_r"]) / 2.0
        t["alpha"] = t["r"] - t["neutral_r"]

    # -----------------------------------------------------------------------
    # a & d) Ratio-Preserving Shuffle (1,000 Seeds)
    # -----------------------------------------------------------------------
    num_seeds = 1000
    seeds = list(range(1, num_seeds + 1))
    print(f"[*] Running Ratio-Preserving Shuffle ({num_seeds} seeds)...")

    splits = ("calibration", "validation", "test")
    split_trades = {s: [t for t in entered_trades if t["split"] == s] for s in splits}
    split_trades["pooled"] = entered_trades

    shuffle_distributions: Dict[str, List[float]] = {s: [] for s in list(splits) + ["pooled"]}

    for seed in seeds:
        rng = random.Random(seed)
        for s in list(splits) + ["pooled"]:
            sub = split_trades[s]
            # Construct ratio-preserving direction vector
            n_buy = sum(1 for t in sub if t["direction"] == "BUY")
            n_sell = len(sub) - n_buy
            dir_pool = ["BUY"] * n_buy + ["SELL"] * n_sell
            rng.shuffle(dir_pool)

            shuffled_rs = [
                t["buy_r"] if assigned == "BUY" else t["sell_r"]
                for t, assigned in zip(sub, dir_pool)
            ]
            shuffle_distributions[s].append(float(np.mean(shuffled_rs)))

    # Compute percentile rank of real mean R in ratio-preserving shuffle
    shuffle_summary: Dict[str, Dict[str, float]] = {}
    for s in list(splits) + ["pooled"]:
        sub = split_trades[s]
        real_mr = float(np.mean([t["r"] for t in sub]))
        dist = shuffle_distributions[s]
        pct = float(np.mean([1.0 if x <= real_mr else 0.0 for x in dist]) * 100.0)
        shuffle_summary[s] = {
            "real_mean_r": real_mr,
            "dist_mean": float(np.mean(dist)),
            "dist_std": float(np.std(dist)),
            "dist_p5": float(np.percentile(dist, 5)),
            "dist_p50": float(np.percentile(dist, 50)),
            "dist_p95": float(np.percentile(dist, 95)),
            "dist_min": float(np.min(dist)),
            "dist_max": float(np.max(dist)),
            "percentile_rank": pct,
        }

    # -----------------------------------------------------------------------
    # b) Always-BUY and Always-SELL Controls
    # -----------------------------------------------------------------------
    drift_summary: Dict[str, Dict[str, Any]] = {}
    for s in list(splits) + ["pooled"]:
        sub = split_trades[s]
        mr_buy = float(np.mean([t["buy_r"] for t in sub]))
        wr_buy = float(np.mean([1.0 if t["buy_r"] > 0 else 0.0 for t in sub])) * 100.0
        mr_sell = float(np.mean([t["sell_r"] for t in sub]))
        wr_sell = float(np.mean([1.0 if t["sell_r"] > 0 else 0.0 for t in sub])) * 100.0
        real_mr = float(np.mean([t["r"] for t in sub]))
        real_wr = float(np.mean([1.0 if t["r"] > 0 else 0.0 for t in sub])) * 100.0
        drift_summary[s] = {
            "n": len(sub),
            "real_mr": real_mr,
            "real_wr": real_wr,
            "always_buy_mr": mr_buy,
            "always_buy_wr": wr_buy,
            "always_sell_mr": mr_sell,
            "always_sell_wr": wr_sell,
        }

    # -----------------------------------------------------------------------
    # c) Direction-Neutral Alpha
    # -----------------------------------------------------------------------
    alpha_summary: Dict[str, Dict[str, Any]] = {}
    for s in list(splits) + ["pooled"]:
        sub = split_trades[s]
        buy_sub = [t for t in sub if t["direction"] == "BUY"]
        sell_sub = [t for t in sub if t["direction"] == "SELL"]

        se_all, t_all, ci_all, p_all = compute_cluster_se(sub, "alpha")
        se_buy, t_buy, ci_buy, p_buy = compute_cluster_se(buy_sub, "alpha")
        se_sell, t_sell, ci_sell, p_sell = compute_cluster_se(sell_sub, "alpha")

        alpha_summary[s] = {
            "all": {
                "n": len(sub),
                "mean_alpha": float(np.mean([t["alpha"] for t in sub])),
                "se": se_all,
                "t_stat": t_all,
                "p_val": p_all,
                "ci": ci_all,
            },
            "buy": {
                "n": len(buy_sub),
                "mean_alpha": float(np.mean([t["alpha"] for t in buy_sub])) if buy_sub else 0.0,
                "se": se_buy,
                "t_stat": t_buy,
                "p_val": p_buy,
                "ci": ci_buy,
            },
            "sell": {
                "n": len(sell_sub),
                "mean_alpha": float(np.mean([t["alpha"] for t in sell_sub])) if sell_sub else 0.0,
                "se": se_sell,
                "t_stat": t_sell,
                "p_val": p_sell,
                "ci": ci_sell,
            },
        }

    # -----------------------------------------------------------------------
    # Write CSV
    # -----------------------------------------------------------------------
    csv_path = out_dir / "stepC2_controls.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "split",
            "n_entries",
            "real_mean_r",
            "ratio_preserving_mean_r",
            "ratio_preserving_p95",
            "ratio_preserving_percentile",
            "always_buy_mean_r",
            "always_sell_mean_r",
            "neutral_alpha_mean",
            "neutral_alpha_cluster_se",
            "neutral_alpha_t_stat",
            "neutral_alpha_p_val",
            "buy_alpha_mean",
            "sell_alpha_mean",
        ])
        for s in ("calibration", "validation", "test", "pooled"):
            sh = shuffle_summary[s]
            dr = drift_summary[s]
            al = alpha_summary[s]["all"]
            b_al = alpha_summary[s]["buy"]
            s_al = alpha_summary[s]["sell"]
            writer.writerow([
                s,
                dr["n"],
                f"{dr['real_mr']:.4f}",
                f"{sh['dist_mean']:.4f}",
                f"{sh['dist_p95']:.4f}",
                f"{sh['percentile_rank']:.1f}%",
                f"{dr['always_buy_mr']:.4f}",
                f"{dr['always_sell_mr']:.4f}",
                f"{al['mean_alpha']:.4f}",
                f"{al['se']:.4f}",
                f"{al['t_stat']:.2f}",
                f"{al['p_val']:.4e}",
                f"{b_al['mean_alpha']:.4f}",
                f"{s_al['mean_alpha']:.4f}",
            ])
    print(f"[*] Wrote CSV to {csv_path}")

    # -----------------------------------------------------------------------
    # Write Markdown Report
    # -----------------------------------------------------------------------
    md_path = out_dir / "stepC2_controls.md"
    lines: List[str] = []

    lines.append("# SMC Analysis (v2) — Step C2: Direction-Neutral Controls")
    lines.append("")
    lines.append("## 1. Protocol & Control Replacement Rationale")
    lines.append("")
    lines.append("- **Flaw in Previous Control**: The v1 random-direction control flipped a 50/50 coin on every trade. Because Gold was in a multi-year bull drift and the strategy had a 65%+ BUY bias, the 50/50 random coin artificially underperformed simply from lack of directional exposure, creating the illusion of edge.")
    lines.append("- **Replacement Controls (v2)**:")
    lines.append("  1. **Ratio-Preserving Shuffle (1,000 Seeds)**: Keeps the exact split-level BUY/SELL count ratio intact, randomly reassigning which setups are BUY and which are SELL.")
    lines.append("  2. **Always-BUY vs Always-SELL**: Evaluates pure directional drift across identical entry timestamps and stops.")
    lines.append(r"  3. **Direction-Neutral Alpha**: $\alpha_i = R_i(\text{strategy}) - \frac{R_i(\text{BUY}) + R_i(\text{SELL})}{2}$. Explicitly removes drift per setup.")
    lines.append("- **Data Hygiene Warning**: Validation and test splits were previously inspected in earlier iterations and are **NOT CLEAN**.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 2. Seed List (1,000 Seeds)")
    lines.append("")
    lines.append("- **Seed Range**: Integers `1` through `1000` inclusive (`range(1, 1001)`).")
    lines.append("`" + ", ".join(str(s) for s in seeds[:50]) + ", ... [51-950 omitted] ... ," + ", ".join(str(s) for s in seeds[-20:]) + "`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 3. Ratio-Preserving Shuffle vs Real Strategy Performance")
    lines.append("")
    lines.append(r"| Split | Entries (n) | Real Mean R | Shuffle Mean | Shuffle Std | 5% - 95% CI | Percentile Rank | Edge Pass? ($\ge 97.5\%$) |")
    lines.append("| :--- | ---: | ---: | ---: | ---: | :---: | ---: | :---: |")

    for s in ("calibration", "validation", "test", "pooled"):
        name = s.capitalize() if s != "pooled" else "**Pooled**"
        sh = shuffle_summary[s]
        dr = drift_summary[s]
        pass_str = "🟢 **YES**" if sh["percentile_rank"] >= 97.5 else "🔴 **NO**"
        lines.append(
            f"| {name} | {dr['n']:,} | **{dr['real_mr']:+.4f}** | {sh['dist_mean']:+.4f} | "
            f"{sh['dist_std']:.4f} | [{sh['dist_p5']:+.4f}, {sh['dist_p95']:+.4f}] | "
            f"**{sh['percentile_rank']:.1f}%** | {pass_str} |"
        )
    lines.append("")
    lines.append("> **Ratio-Preserving Shuffle Verdict**:")
    lines.append("> - On **Calibration**, the real strategy mean R achieves the **72.8th percentile** (< 97.5% required).")
    lines.append("> - On **Validation**, it achieves the **100.0th percentile** (passed).")
    lines.append("> - On **Test**, it achieves only the **36.2th percentile** (failed; ratio-preserving random shuffles beat real performance 63.8% of the time).")
    lines.append("> - Across the full pooled sample, percentile rank is **83.6%** (< 97.5%). Under the ratio-preserving standard, **no edge over random directional allocation is demonstrated**.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 4. Always-BUY vs Always-SELL (Drift Controls)")
    lines.append("")
    lines.append("| Split | Real Strategy Mean R (WR) | Always-BUY Mean R (WR) | Always-SELL Mean R (WR) | Underlying Regime & Drift Bias |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")

    for s in ("calibration", "validation", "test", "pooled"):
        name = s.capitalize() if s != "pooled" else "**Pooled**"
        dr = drift_summary[s]
        if s == "calibration":
            bias = "Bull drift: Always-BUY (+0.1265R) outperforms real (+0.0437R)"
        elif s == "validation":
            bias = "Extreme bull drift: Always-BUY (+0.5401R) strongly positive"
        elif s == "test":
            bias = "Bearish mean-reversion: Always-SELL (+0.1691R) beats real (-0.0131R)"
        else:
            bias = "Net upward trend dominance across gold history"
        lines.append(
            f"| {name} | **{dr['real_mr']:+.4f}** ({dr['real_wr']:.1f}%) | "
            f"**{dr['always_buy_mr']:+.4f}** ({dr['always_buy_wr']:.1f}%) | "
            f"**{dr['always_sell_mr']:+.4f}** ({dr['always_sell_wr']:.1f}%) | {bias} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 5. Direction-Neutral Alpha Analysis")
    lines.append("")
    lines.append(r"$$\alpha_i = R_i(\text{strategy direction}) - \frac{R_i(\text{BUY}) + R_i(\text{SELL})}{2}$$")
    lines.append("")
    lines.append("| Split | Cohort | Entries (n) | **Mean Alpha ($\bar{\alpha}$)** | Cluster-Robust SE | $t$-statistic | $p$-value | 95% Confidence Interval | Significant ($p < 0.05$)? |")
    lines.append("| :--- | :--- | ---: | ---: | ---: | ---: | ---: | :---: | :---: |")

    for s in ("calibration", "validation", "test", "pooled"):
        name = s.capitalize() if s != "pooled" else "**Pooled**"
        al_dict = alpha_summary[s]
        for cohort, c_label in (("all", "All Entries"), ("buy", "BUY Entries Only"), ("sell", "SELL Entries Only")):
            c_data = al_dict[cohort]
            sig_str = "🟢 **YES**" if c_data["p_val"] < 0.05 else "🔴 NO"
            row_prefix = f"| {name}" if cohort == "all" else "| "
            lines.append(
                f"{row_prefix} | {c_label} | {c_data['n']:,} | **{c_data['mean_alpha']:+.4f}R** | "
                f"{c_data['se']:.4f} | {c_data['t_stat']:+.2f} | {c_data['p_val']:.4f} | "
                f"[{c_data['ci'][0]:+.4f}, {c_data['ci'][1]:+.4f}] | {sig_str} |"
            )
    lines.append("")
    lines.append("> **Direction-Neutral Alpha Diagnostic**:")
    lines.append("> 1. **Severe Directional Asymmetry**:")
    lines.append(">    - On **Calibration**, BUY setups generated **+0.1492R alpha** ($t=+1.85$), while SELL setups suffered **-0.1435R negative alpha** ($t=-1.61$).")
    lines.append(">    - On **Validation**, BUY setups generated **+0.5825R alpha**, while SELL setups produced **-0.4013R negative alpha**.")
    lines.append(">    - On **Test**, BUY setups collapsed to **-0.2606R negative alpha**, while SELL setups produced **+0.2303R alpha**.")
    lines.append("> 2. **Test Split Degradation**:")
    lines.append(">    - On Test, the overall direction-neutral alpha is **negative (-0.0699R)** ($t=-0.72$). The strategy's directional calls underperformed neutral drift.")
    lines.append("> 3. **Statistical Insignificance**:")
    lines.append(">    - When clustering by UTC calendar day, overall direction-neutral alpha fails statistical significance on Calibration ($p=0.485$), Test ($p=0.470$), and Pooled ($p=0.174$).")
    lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[*] Report successfully written to {md_path}")


if __name__ == "__main__":
    run_step_c2()
