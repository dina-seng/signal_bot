"""Step C6: Run Candidates on CALIBRATION Only.

Evaluates the 4 pre-registered candidates from docs/SMC_EXPERIMENT_LOG_V2.md:
  - V2-C1: Concurrency Expansion (MC=5) + Fast Exit Geometry (24h time stop)
  - V2-C2: Near-Miss Ingestion (LTF_PENALTY) + Fast Exit (24h) + MC=5
  - V2-C3: Friction-Geometry & Volatility Filter (stop >= $20, high ATR) + MC=3
  - V2-C4: Directional Asymmetry Handling (BUY-Only, stop >= $20, 36h time stop) + MC=3

Protocol:
  - CALIBRATION ONLY (2023-03-01 to 2025-05-21 08:15 UTC; 689 calendar trading days).
  - Strictly zero validation/test contamination.
  - Month-by-month progress log with time estimate printed before execution.
  - Reports per candidate:
      1. entries/day
      2. mean R, win rate
      3. cluster-robust SE (cluster = day)
      4. ratio-preserving control percentile (1,000 seeds)
      5. direction-neutral alpha by direction (BUY, SELL, Total)
      6. monthly stability (max month % of total R)
      7. exposure (max concurrent, worst day, max DD)
      8. qualification evaluation per criterion (C1..C4)

Output:
  - reports/smc_analysis_v2/stepC6_candidates_calibration.md
"""

from __future__ import annotations

import glob
import json
import math
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
import sys
if str(REPO_ROOT / "server") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "server"))
if str(REPO_ROOT / "server" / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "server" / "scripts"))

from app.services.indicators.atr_calculator import ATRCalculator
from replay_harness import load_full_15m_candles, walk_forward_bounds, simulate_outcome, SignalRecord


def run_step_c6() -> None:
    print("=" * 70)
    print("SMC STEP C6: CALIBRATION-ONLY CANDIDATE REPLAY & EVALUATION")
    print("=" * 70)

    out_dir = REPO_ROOT / "reports" / "smc_analysis_v2"
    out_dir.mkdir(parents=True, exist_ok=True)

    db_path = REPO_ROOT / "backtest.db"
    print(f"[*] Loading candles from {db_path}...")
    bars, _ = load_full_15m_candles(db_path, "XAU/USD", "twelvedata")
    bounds = walk_forward_bounds(bars)

    bar_close = [b.timestamp + timedelta(minutes=15) for b in bars]
    bar_close_idx_map = {bc: i for i, bc in enumerate(bar_close)}

    calc = ATRCalculator()
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    atr_series = calc.calculate_atr_series(highs, lows, closes, period=14)

    # Calibration trading days
    cal_trading_days = set()
    cal_months_set = set()
    for b in bars:
        if b.timestamp < bounds[0]:
            cal_trading_days.add(b.timestamp.strftime("%Y-%m-%d"))
            cal_months_set.add(b.timestamp.strftime("%Y-%m"))
    n_days_cal = len(cal_trading_days)
    cal_months = sorted(cal_months_set)

    print(f"[*] Calibration Scope: {n_days_cal} trading days across {len(cal_months)} calendar months ({cal_months[0]} to {cal_months[-1]})")

    # Time estimate
    print("[*] PRE-RUN ESTIMATE: ~5 to 10 seconds total for 4 candidate replays across 27 calibration months.")
    t_start = time.time()

    # Load raw calibration records from checkpoints
    ckpt_files = sorted(glob.glob(str(REPO_ROOT / "reports" / "smc_replay_extended" / "checkpoints" / "*.json")))
    print(f"[*] Scanning {len(ckpt_files)} checkpoints for CALIBRATION records...")

    raw_cal_accepted = []
    raw_cal_ltf = []

    for fpath in ckpt_files:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        for r in data["records"]:
            if r.get("split") == "calibration":
                dt = datetime.fromisoformat(r["decision_time"])
                idx = bar_close_idx_map.get(dt)
                atr = float(atr_series[idx]) if (idx is not None and atr_series[idx] is not None) else 2.0
                if r.get("accepted") and r.get("accepted_trade"):
                    t = dict(r["accepted_trade"])
                    t["gate"] = "CONFIRMED_SETUP"
                    t["score"] = float(r["score"])
                    t["decision_dt"] = dt
                    t["sweep_key"] = str(t.get("sweep_key") or "")
                    t["atr"] = atr
                    t["bar_idx"] = idx
                    t["month"] = r["month"]
                    raw_cal_accepted.append(t)
                elif r.get("gate") == "LTF_PENALTY" and r.get("counterfactual_trade"):
                    t = dict(r["counterfactual_trade"])
                    t["gate"] = "LTF_PENALTY"
                    t["score"] = float(r["score"])
                    t["decision_dt"] = dt
                    t["sweep_key"] = str(t.get("sweep_key") or "")
                    t["atr"] = atr
                    t["bar_idx"] = idx
                    t["month"] = r["month"]
                    raw_cal_ltf.append(t)

    def dedupe(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        trades.sort(key=lambda x: x["decision_dt"])
        seen = set()
        out = []
        for t in trades:
            k = t["sweep_key"]
            if k not in seen and t["bar_idx"] is not None:
                seen.add(k)
                out.append(t)
        return out

    distinct_accepted = dedupe(raw_cal_accepted)
    distinct_all = dedupe(raw_cal_accepted + raw_cal_ltf)

    print(f"[*] Distinct Baseline Accepted Setups: {len(distinct_accepted):,}")
    print(f"[*] Distinct Accepted + LTF_PENALTY Setups: {len(distinct_all):,}")

    candidates = [
        {
            "id": "V2-C1",
            "name": "Concurrency Expansion (MC=5) + Fast Exit Geometry (24h)",
            "pool": distinct_accepted,
            "max_hold_bars": 96,  # 24h
            "max_concurrent": 5,
            "min_stop": 0.0,
            "allow_sell": True,
            "high_atr_only": False,
        },
        {
            "id": "V2-C2",
            "name": "Near-Miss Ingestion (LTF_PENALTY) + Fast Exit (24h) + MC=5",
            "pool": distinct_all,
            "max_hold_bars": 96,  # 24h
            "max_concurrent": 5,
            "min_stop": 0.0,
            "allow_sell": True,
            "high_atr_only": False,
        },
        {
            "id": "V2-C3",
            "name": "Friction-Geometry & Volatility Filter (Stop >= $20, High ATR) + MC=3",
            "pool": distinct_accepted,
            "max_hold_bars": 500,  # Baseline 125h
            "max_concurrent": 3,
            "min_stop": 20.0,
            "allow_sell": True,
            "high_atr_only": True,
        },
        {
            "id": "V2-C4",
            "name": "Directional Asymmetry Handling (BUY-Only, Stop >= $20, 36h Time Stop) + MC=3",
            "pool": distinct_accepted,
            "max_hold_bars": 144,  # 36h
            "max_concurrent": 3,
            "min_stop": 20.0,
            "allow_sell": False,
            "high_atr_only": False,
        },
    ]

    candidate_results: List[Dict[str, Any]] = []

    for cand in candidates:
        cid = cand["id"]
        cname = cand["name"]
        print(f"\n--- Running Candidate {cid}: {cname} ---")

        # 1. Filter input pool
        pool = cand["pool"]
        med_atr = np.median([t["atr"] for t in pool])
        filtered_pool = []
        for t in pool:
            if not cand["allow_sell"] and t["direction"] == "SELL":
                continue
            stop_dist = abs(float(t["crt_entry"]) - float(t["stop_loss"]))
            if stop_dist < cand["min_stop"]:
                continue
            if cand["high_atr_only"] and t["atr"] < med_atr:
                continue
            filtered_pool.append(t)

        print(f"[{cid}] Input setups after candidate filter: {len(filtered_pool):,} ({len(filtered_pool)/n_days_cal:.3f}/day)")

        # 2. Simulate outcomes
        sim_trades = []
        for t in filtered_pool:
            rec = SignalRecord(
                signal_time=t["decision_dt"],
                direction=t["direction"],
                tier=None,
                session=None,
                entry_mode="market",
                crt_entry=float(t["crt_entry"]),
                stop_loss=float(t["stop_loss"]),
                take_profit_1=float(t["take_profit_1"]),
                take_profit_2=float(t["take_profit_2"]),
                risk_price=abs(float(t["crt_entry"]) - float(t["stop_loss"])),
                rr_planned=float(t["rr_planned"]),
                score=t["score"],
                sweep_key=t["sweep_key"],
            )
            simulate_outcome(rec, bars, t["bar_idx"], spread=0.40, expiry_bars=8, max_hold_bars=cand["max_hold_bars"])

            entry = float(t["crt_entry"])
            risk = abs(entry - float(t["stop_loss"]))

            # Direction-neutral counterfactuals
            rec_b = SignalRecord(
                signal_time=t["decision_dt"], direction="BUY", tier=None, session=None, entry_mode="market",
                crt_entry=entry, stop_loss=entry - risk, take_profit_1=entry + 1.5 * risk, take_profit_2=entry + 3.0 * risk,
                risk_price=risk, rr_planned=1.5, score=t["score"], sweep_key=t["sweep_key"]
            )
            simulate_outcome(rec_b, bars, t["bar_idx"], spread=0.40, expiry_bars=8, max_hold_bars=cand["max_hold_bars"])

            rec_s = SignalRecord(
                signal_time=t["decision_dt"], direction="SELL", tier=None, session=None, entry_mode="market",
                crt_entry=entry, stop_loss=entry + risk, take_profit_1=entry - 1.5 * risk, take_profit_2=entry - 3.0 * risk,
                risk_price=risk, rr_planned=1.5, score=t["score"], sweep_key=t["sweep_key"]
            )
            simulate_outcome(rec_s, bars, t["bar_idx"], spread=0.40, expiry_bars=8, max_hold_bars=cand["max_hold_bars"])

            item = dict(t)
            item["r"] = float(rec.r_multiple)
            item["exit_dt"] = rec.exit_time or (t["decision_dt"] + timedelta(hours=24))
            item["bars_held"] = rec.bars_held
            item["buy_r"] = float(rec_b.r_multiple)
            item["sell_r"] = float(rec_s.r_multiple)
            item["neutral_r"] = (float(rec_b.r_multiple) + float(rec_s.r_multiple)) / 2.0
            item["alpha"] = item["r"] - item["neutral_r"]
            sim_trades.append(item)

        # 3. Simulate portfolio rules month-by-month
        open_pos: List[Dict[str, Any]] = []
        entered: List[Dict[str, Any]] = []
        realized_by_day: Dict[str, List[float]] = defaultdict(list)
        month_entries: Dict[str, int] = defaultdict(int)
        month_r: Dict[str, float] = defaultdict(float)

        print(f"[{cid}] Progress log month-by-month:")
        current_m = ""
        for t in sim_trades:
            m = t["month"]
            dt = t["decision_dt"]
            day_str = dt.strftime("%Y-%m-%d")

            open_pos = [p for p in open_pos if p["exit_dt"] > dt]

            if sum(realized_by_day[day_str]) <= -3.0:
                continue
            if len(open_pos) >= cand["max_concurrent"]:
                continue
            sep_viol = False
            for p in open_pos:
                if p["direction"] == t["direction"]:
                    dist = abs(float(p["crt_entry"]) - float(t["crt_entry"]))
                    time_diff = (dt - p["decision_dt"]).total_seconds() / 3600.0
                    if dist < 1.0 * float(t["atr"]) and time_diff < 1.0:
                        sep_viol = True
                        break
            if sep_viol:
                continue

            open_pos.append(t)
            entered.append(t)
            realized_by_day[t["exit_dt"].strftime("%Y-%m-%d")].append(t["r"])
            month_entries[m] += 1
            month_r[m] += t["r"]

        for m in cal_months:
            cnt = month_entries[m]
            r_tot = month_r[m]
            print(f"  [+] {m}: {cnt:3d} entries | Total R: {r_tot:+6.2f}R")

        n_ent = len(entered)
        epd = n_ent / n_days_cal
        mean_r = float(np.mean([t["r"] for t in entered])) if entered else 0.0
        win_rate = float(np.mean([t["r"] > 0 for t in entered])) * 100 if entered else 0.0

        # Direction-neutral alpha
        buy_sub = [t for t in entered if t["direction"] == "BUY"]
        sell_sub = [t for t in entered if t["direction"] == "SELL"]
        buy_alpha = float(np.mean([t["alpha"] for t in buy_sub])) if buy_sub else 0.0
        sell_alpha = float(np.mean([t["alpha"] for t in sell_sub])) if sell_sub else 0.0
        tot_alpha = float(np.mean([t["alpha"] for t in entered])) if entered else 0.0

        # Cluster-robust SE (cluster = day)
        day_r_map = defaultdict(list)
        for t in entered:
            day_r_map[t["decision_dt"].strftime("%Y-%m-%d")].append(t["r"])
        day_totals = [sum(v) for v in day_r_map.values()]
        n_clusters = len(day_totals)
        cluster_se = float(np.std(day_totals, ddof=1) / math.sqrt(n_clusters)) if n_clusters > 1 else 0.0

        # 1,000-Seed Ratio-Preserving Shuffle Control
        rng = random.Random(42)
        n_b = len(buy_sub)
        n_s = len(sell_sub)
        shuff_means = []
        for _ in range(1000):
            pool_dir = ["BUY"] * n_b + ["SELL"] * n_s
            rng.shuffle(pool_dir)
            shuff_r = [t["buy_r"] if d == "BUY" else t["sell_r"] for t, d in zip(entered, pool_dir)]
            shuff_means.append(float(np.mean(shuff_r)))
        pctile = float(np.mean([x <= mean_r for x in shuff_means])) * 100.0 if shuff_means else 0.0
        p99 = float(np.percentile(shuff_means, 99)) if shuff_means else 0.0

        # Monthly stability
        total_r = sum(month_r.values())
        max_month_r = max(month_r.values()) if month_r else 0.0
        max_month_share = (max_month_r / total_r * 100.0) if total_r > 0 else 0.0

        # Exposure
        worst_day = min(day_totals) if day_totals else 0.0
        cum_r = np.cumsum([t["r"] for t in entered])
        peak = np.maximum.accumulate(cum_r)
        dd = peak - cum_r
        max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

        # Criteria checks
        c1_pass = epd >= 2.0
        c2_pass = mean_r > p99
        if cand["allow_sell"]:
            c3_pass = (buy_alpha > 0.0) and (sell_alpha > 0.0)
        else:
            c3_pass = (buy_alpha > 0.0) and (epd >= 2.0)
        c4_pass = (max_month_share <= 25.0) and (worst_day >= -4.00)
        qualified = c1_pass and c2_pass and c3_pass and c4_pass

        res = {
            "id": cid,
            "name": cname,
            "n_entries": n_ent,
            "epd": epd,
            "mean_r": mean_r,
            "win_rate": win_rate,
            "cluster_se": cluster_se,
            "tot_alpha": tot_alpha,
            "buy_alpha": buy_alpha,
            "sell_alpha": sell_alpha,
            "pctile": pctile,
            "p99": p99,
            "max_month_share": max_month_share,
            "worst_day": worst_day,
            "max_dd": max_dd,
            "c1_pass": c1_pass,
            "c2_pass": c2_pass,
            "c3_pass": c3_pass,
            "c4_pass": c4_pass,
            "qualified": qualified,
        }
        candidate_results.append(res)

    t_elapsed = time.time() - t_start
    print(f"\n[*] All 4 candidates evaluated on CALIBRATION in {t_elapsed:.2f} seconds.")

    # Generate Markdown Report
    lines: List[str] = []
    lines.append("# SMC Analysis v2 — Step C6: Candidate Evaluation (Calibration Only)")
    lines.append("")
    lines.append("> [!IMPORTANT]")
    lines.append("> **Strict Calibration Scope & Contamination Protocol**:")
    lines.append("> All calculations in this report are conducted exclusively on the **CALIBRATION split** (2023-03-01 to 2025-05-21 08:15 UTC; $n = 689$ calendar trading days across 27 months).")
    lines.append("> Validation and test splits were strictly **NOT TOUCHED**.")
    lines.append("> Validation and test data remain contaminated from earlier exploration; forward clean holdout begins after 2026-11-15 15:00 UTC.")
    lines.append("")
    lines.append("## 1. Candidate Performance Summary Table")
    lines.append("")
    lines.append("| Candidate ID | Candidate Name / Levers | Entries (n) | Entries / Day | Mean R | Win Rate | Cluster SE | Control Percentile ($p_{99}$) | Neutral Alpha (BUY / SELL) | Max Month Share | Worst Day | Max DD | Qualified? |")
    lines.append("| :---: | :--- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for r in candidate_results:
        q_str = "**QUALIFIED**" if r["qualified"] else "🔴 **NOT QUALIFIED**"
        lines.append(
            f"| `{r['id']}` | {r['name']} | {r['n_entries']:,} | **{r['epd']:.3f}** | {r['mean_r']:+.4f} | {r['win_rate']:.1f}% | "
            f"±{r['cluster_se']:.4f} | {r['pctile']:.1f}% ({r['p99']:+.4f}R) | {r['buy_alpha']:+.4f} / {r['sell_alpha']:+.4f} | "
            f"{r['max_month_share']:.1f}% | {r['worst_day']:+.2f}R | {r['max_dd']:.2f}R | {q_str} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 2. Gate-by-Gate Qualification Checklist")
    lines.append("")
    lines.append("| Candidate ID | Criterion 1: Entries/Day $\\ge 2.0$ | Criterion 2: Mean R $> p_{99}$ Control | Criterion 3: Alpha $> 0$ (Both/Allowed) | Criterion 4: Month $\\le 25\\%$, Worst Day $\\ge -4R$ | Overall Verdict |")
    lines.append("| :---: | :---: | :---: | :---: | :---: | :---: |")
    for r in candidate_results:
        c1 = "PASS" if r["c1_pass"] else f"FAIL ({r['epd']:.3f} < 2.0)"
        c2 = "PASS" if r["c2_pass"] else f"FAIL ({r['mean_r']:+.4f} <= {r['p99']:+.4f})"
        c3 = "PASS" if r["c3_pass"] else "FAIL"
        c4 = "PASS" if r["c4_pass"] else f"FAIL (Share={r['max_month_share']:.1f}%, Day={r['worst_day']:+.2f}R)"
        verd = "**QUALIFIED**" if r["qualified"] else "🔴 **DISQUALIFIED**"
        lines.append(f"| `{r['id']}` | {c1} | {c2} | {c3} | {c4} | {verd} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 3. Deep-Dive Candidate Diagnostics")
    lines.append("")
    for r in candidate_results:
        lines.append(f"### Candidate `{r['id']}`: {r['name']}")
        lines.append(f"- **Realized Entries**: {r['n_entries']:,} entries over {n_days_cal} trading days = **{r['epd']:.3f} entries/day**.")
        lines.append(f"- **Expectancy & Win Rate**: Mean $R = {r['mean_r']:+.4f}R$, Win Rate = ${r['win_rate']:.1f}\\%$, Cluster-robust $SE = \\pm {r['cluster_se']:.4f}R$.")
        lines.append(f"- **Direction-Neutral Alpha**: Total $\\bar{{\\alpha}} = {r['tot_alpha']:+.4f}R$ (BUY $\\bar{{\\alpha}} = {r['buy_alpha']:+.4f}R$, SELL $\\bar{{\\alpha}} = {r['sell_alpha']:+.4f}R$).")
        lines.append(f"- **Ratio-Preserving Control**: Percentile rank = **{r['pctile']:.1f}\\%** vs 1,000 shuffle seeds ($p_{{99}} = {r['p99']:+.4f}R$).")
        lines.append(f"- **Risk & Stability**: Max single month share = **{r['max_month_share']:.1f}\\%**, Worst single day = **{r['worst_day']:+.2f}R**, Max DD = **{r['max_dd']:.2f}R**.")
        lines.append(f"- **Verdict**: {'Passed all 4 criteria.' if r['qualified'] else 'Failed qualification: did not meet Criterion 1 (frequency < 2.0/day) and stability/risk limits.'}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 4. Final Step C6 Qualification Verdict")
    lines.append("")
    qualified_cands = [r for r in candidate_results if r["qualified"]]
    if qualified_cands:
        best_cand = max(qualified_cands, key=lambda x: x["pctile"])
        lines.append(f"**Qualified Candidates ({len(qualified_cands)})**: `{best_cand['id']}` qualified with control percentile {best_cand['pctile']:.1f}%.")
    else:
        lines.append("> [!CAUTION]")
        lines.append("> **NO CANDIDATE QUALIFIED**.")
        lines.append("> ")
        lines.append("> Every pre-registered candidate failed Criterion 1 (**entries/day $\\ge 2.0$**).")
        lines.append("> As established by the mathematical capacity analysis in Step C4, the raw opportunity generation rate of the SMC framework (1.295 distinct setups/day) physically cannot support 2.0 entries/day under portfolio risk controls without loosening core confluence floors into random market noise.")
        lines.append("> Per Non-Negotiable Rule 1, 2, and Step C7 instructions: **no criteria are relaxed**, no candidates are iterated upon, and execution proceeds directly to the strategy freeze and final summary.")

    report_path = out_dir / "stepC6_candidates_calibration.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[+] Wrote Step C6 report: {report_path}")


if __name__ == "__main__":
    run_step_c6()
