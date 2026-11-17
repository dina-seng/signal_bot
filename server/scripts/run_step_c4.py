"""Step C4: Capacity Analysis - Where Could 2 Entries/Day Come From?

Performs:
  a) Distinct setups available per day by rejection gate (full funnel analysis):
     - Decision bars (records) per gate.
     - Distinct opportunities (sweeps) per gate.
     - Setups per trading day per split and pooled.
  b) Sensitivity of entries/day and Mean R to portfolio parameters:
     - MAX_CONCURRENT: 1, 2, 3, 4, 5.
     - MIN_ENTRY_SEPARATION: OFF, 0.5 ATR, 1.0 ATR, 2.0 ATR.
     - DAILY_LOSS_STOP: OFF, -2.0R, -3.0R, -5.0R.
  c) Gap closure analysis:
     - Current production scanner (has_active_position + 2h cooldown) -> 0.181 entries/day.
     - Removing has_active_position with MAX_CONCURRENT=3 -> 0.467 entries/day.
     - Raw accepted opportunity pool (MAX_CONCURRENT=inf) -> 1.295 entries/day.
     - Holding time capacity theorem: Max entries/day = (MAX_CONCURRENT * 24h) / Mean Hold.
     - What remains uncovered to reach 2.0 entries/day.

Output:
  - reports/smc_analysis_v2/stepC4_capacity.md
"""

from __future__ import annotations

import glob
import json
import math
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
from crt_replay import load_full_15m_candles, walk_forward_bounds


def run_step_c4() -> None:
    print("=" * 70)
    print("SMC STEP C4: CAPACITY ANALYSIS & GAP TO 2 ENTRIES/DAY")
    print("=" * 70)

    out_dir = REPO_ROOT / "reports" / "smc_analysis_v2"
    out_dir.mkdir(parents=True, exist_ok=True)

    db_path = REPO_ROOT / "backtest.db"
    print(f"[*] Loading candles from {db_path}...")
    bars, _ = load_full_15m_candles(db_path, "XAU/USD", "twelvedata")
    bounds = walk_forward_bounds(bars)

    # 1. Compute exact ATR(14, 15m) for every bar
    calc = ATRCalculator()
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    atr_series = calc.calculate_atr_series(highs, lows, closes, period=14)
    bar_close = [b.timestamp + timedelta(minutes=15) for b in bars]
    bar_close_idx_map = {bc: i for i, bc in enumerate(bar_close)}

    # 2. Identify calendar trading days per split
    trading_days_by_split: Dict[str, set[str]] = defaultdict(set)
    all_trading_days: set[str] = set()

    for b in bars:
        d_str = b.timestamp.strftime("%Y-%m-%d")
        all_trading_days.add(d_str)
        if b.timestamp < bounds[0]:
            trading_days_by_split["calibration"].add(d_str)
        elif b.timestamp < bounds[1]:
            trading_days_by_split["validation"].add(d_str)
        else:
            trading_days_by_split["test"].add(d_str)
    trading_days_by_split["pooled"] = all_trading_days

    n_days = {
        "calibration": len(trading_days_by_split["calibration"]),
        "validation": len(trading_days_by_split["validation"]),
        "test": len(trading_days_by_split["test"]),
        "pooled": len(all_trading_days),
    }
    print(f"[*] Trading days: Cal={n_days['calibration']}, Val={n_days['validation']}, Tst={n_days['test']}, Pool={n_days['pooled']}")

    # 3. Read all records from all 45 checkpoints
    ckpt_files = sorted(glob.glob(str(REPO_ROOT / "reports" / "smc_replay_extended" / "checkpoints" / "*.json")))
    print(f"[*] Scanning {len(ckpt_files)} checkpoints...")

    records_by_split_gate: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    distinct_by_split_gate: Dict[str, Dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    all_distinct_by_gate: Dict[str, set[str]] = defaultdict(set)

    raw_accepted_setups: List[Dict[str, Any]] = []

    for fpath in ckpt_files:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        for r in data["records"]:
            s = r["split"]
            g = r.get("gate", "UNKNOWN")
            k = str(r.get("opportunity_key") or "")
            records_by_split_gate[s][g] += 1
            records_by_split_gate["pooled"][g] += 1
            if k:
                distinct_by_split_gate[s][g].add(k)
                distinct_by_split_gate["pooled"][g].add(k)
                all_distinct_by_gate[g].add(k)

            if r.get("accepted") and r.get("accepted_trade"):
                t = dict(r["accepted_trade"])
                t["decision_dt"] = datetime.fromisoformat(r["decision_time"])
                t["exit_dt"] = datetime.fromisoformat(t["exit_time"])
                t["split"] = r["split"]
                t["month"] = r["month"]
                t["r"] = float(t["r_multiple"])
                t["sweep_key"] = str(t.get("sweep_key") or "")
                idx = bar_close_idx_map.get(t["decision_dt"])
                t["atr"] = float(atr_series[idx]) if (idx is not None and atr_series[idx] is not None) else 2.0
                raw_accepted_setups.append(t)

    raw_accepted_setups.sort(key=lambda x: x["decision_dt"])

    # Dedupe accepted setups to one per sweep
    seen_sweeps = set()
    distinct_accepted_opps: List[Dict[str, Any]] = []
    for t in raw_accepted_setups:
        k = t["sweep_key"]
        if k not in seen_sweeps:
            seen_sweeps.add(k)
            distinct_accepted_opps.append(t)

    print(f"[*] Total distinct accepted opportunities: {len(distinct_accepted_opps):,}")

    # =========================================================================
    # PART A: Funnel Analysis
    # =========================================================================
    gate_order = [
        ("CONFIRMED_SETUP", "Accepted Signals (Emitted by SMCStrategy)"),
        ("LTF_PENALTY", "LTF Unconfirmed Near-Miss (-5 pt penalty)"),
        ("CONFLUENCE_FLOOR", "Confluence Floor Rejection (Struct + Liq < 20)"),
        ("PA_FLOOR", "Price Action Floor Rejection (PA < 10)"),
        ("SCORE_BELOW_THRESHOLD", "Score Floor Rejection (Pre-LTF Score < 60)"),
    ]

    funnel_summary: List[Dict[str, Any]] = []
    for g, gdesc in gate_order:
        row = {
            "gate": g,
            "desc": gdesc,
            "cal_recs": records_by_split_gate["calibration"][g],
            "cal_opps": len(distinct_by_split_gate["calibration"][g]),
            "cal_epd": len(distinct_by_split_gate["calibration"][g]) / n_days["calibration"],
            "val_recs": records_by_split_gate["validation"][g],
            "val_opps": len(distinct_by_split_gate["validation"][g]),
            "val_epd": len(distinct_by_split_gate["validation"][g]) / n_days["validation"],
            "tst_recs": records_by_split_gate["test"][g],
            "tst_opps": len(distinct_by_split_gate["test"][g]),
            "tst_epd": len(distinct_by_split_gate["test"][g]) / n_days["test"],
            "pool_recs": records_by_split_gate["pooled"][g],
            "pool_opps": len(distinct_by_split_gate["pooled"][g]),
            "pool_epd": len(distinct_by_split_gate["pooled"][g]) / n_days["pooled"],
        }
        funnel_summary.append(row)

    # =========================================================================
    # PART B: Sensitivity Analysis of Portfolio Rules
    # =========================================================================
    def simulate_portfolio(
        max_concurrent: int = 3,
        min_sep_atr: Optional[float] = 1.0,
        daily_loss_stop: Optional[float] = -3.0,
    ) -> Tuple[Dict[str, Tuple[int, float, float, float]], Dict[str, Any]]:
        open_pos: List[Dict[str, Any]] = []
        entered: List[Dict[str, Any]] = []
        realized_by_day: Dict[str, List[float]] = defaultdict(list)
        hit_days: set[str] = set()
        skipped_by_dls = 0
        skipped_by_cap = 0
        skipped_by_sep = 0

        for t in distinct_accepted_opps:
            dt = t["decision_dt"]
            day_str = dt.strftime("%Y-%m-%d")
            open_pos = [p for p in open_pos if p["exit_dt"] > dt]

            if daily_loss_stop is not None and sum(realized_by_day[day_str]) <= daily_loss_stop:
                hit_days.add(day_str)
                skipped_by_dls += 1
                continue
            if len(open_pos) >= max_concurrent:
                skipped_by_cap += 1
                continue
            if min_sep_atr is not None and min_sep_atr > 0:
                sep_viol = False
                for p in open_pos:
                    if p["direction"] == t["direction"]:
                        dist = abs(float(p["crt_entry"]) - float(t["crt_entry"]))
                        time_diff = (dt - p["decision_dt"]).total_seconds() / 3600.0
                        if dist < min_sep_atr * float(t["atr"]) and time_diff < 1.0:
                            sep_viol = True
                            break
                if sep_viol:
                    skipped_by_sep += 1
                    continue

            open_pos.append(t)
            entered.append(t)
            realized_by_day[t["exit_dt"].strftime("%Y-%m-%d")].append(t["r"])

        res: Dict[str, Tuple[int, float, float, float]] = {}
        for s in ("calibration", "validation", "test", "pooled"):
            sub = [t for t in entered if (t["split"] == s if s != "pooled" else True)]
            n_ent = len(sub)
            epd = n_ent / n_days[s]
            mean_r = float(np.mean([t["r"] for t in sub])) if sub else 0.0
            win_rate = float(np.mean([t["r"] > 0 for t in sub])) * 100 if sub else 0.0
            res[s] = (n_ent, epd, mean_r, win_rate)

        meta = {
            "hit_days": len(hit_days),
            "skipped_by_dls": skipped_by_dls,
            "skipped_by_cap": skipped_by_cap,
            "skipped_by_sep": skipped_by_sep,
        }
        return res, meta

    # 1. MAX_CONCURRENT variations
    mc_results = []
    for mc in (1, 2, 3, 4, 5):
        r, meta = simulate_portfolio(max_concurrent=mc, min_sep_atr=1.0, daily_loss_stop=-3.0)
        mc_results.append((mc, r, meta))

    # 2. MIN_ENTRY_SEPARATION variations
    sep_results = []
    for sep in (0.0, 0.5, 1.0, 2.0):
        lbl = "OFF" if sep == 0.0 else f"{sep:.1f} ATR"
        r, meta = simulate_portfolio(max_concurrent=3, min_sep_atr=sep, daily_loss_stop=-3.0)
        sep_results.append((lbl, r, meta))

    # 3. DAILY_LOSS_STOP variations
    dls_results = []
    for dls in (None, -2.0, -3.0, -5.0):
        lbl = "OFF" if dls is None else f"{dls:.1f}R"
        r, meta = simulate_portfolio(max_concurrent=3, min_sep_atr=1.0, daily_loss_stop=dls)
        dls_results.append((lbl, r, meta))

    # =========================================================================
    # PART C: Gap Closure Analysis
    # =========================================================================
    # Production scanner simulation (has_active_position + 2h cooldown)
    # Already computed in Step C1: 208 entries / 0.181 epd (+0.0413R)
    # Target: 2.000 epd
    target_epd = 2.000
    prod_epd = 208 / n_days["pooled"]  # 0.1807
    total_gap = target_epd - prod_epd    # 1.8193

    # Baseline portfolio (MAX_CONCURRENT=3): 538 entries / 0.4674 epd (+0.0894R)
    base_port_epd = 538 / n_days["pooled"]  # 0.4674
    gap_closed_concurrency = base_port_epd - prod_epd  # 0.2867 (15.8% of gap)

    # Max possible with all distinct accepted setups (MAX_CONCURRENT=inf): 1491 entries / 1.2954 epd
    raw_opp_epd = len(distinct_accepted_opps) / n_days["pooled"]  # 1.2954
    raw_gap_closed = raw_opp_epd - prod_epd  # 1.1147 (61.3% of gap)
    raw_remaining_shortfall = target_epd - raw_opp_epd  # 0.7046 (38.7% of gap)

    # If LTF_PENALTY setups were incorporated:
    ltf_opps = len(distinct_by_split_gate["pooled"]["LTF_PENALTY"])
    combined_opps = len(distinct_accepted_opps) + ltf_opps
    combined_epd = combined_opps / n_days["pooled"]  # (1491 + 755)/1151 = 1.9513 epd

    # Holding time capacity analysis
    # Holding time across accepted setups: mean = 103.4h, median = 95.8h
    mean_hold_hours = 103.4
    capacity_3_slots = (3.0 * 24.0) / mean_hold_hours  # 0.696 entries/day
    required_hold_for_2epd_mc3 = (3.0 * 24.0) / 2.0     # 36.0 hours

    # =========================================================================
    # Format Markdown Report
    # =========================================================================
    lines: List[str] = []
    lines.append("# SMC Analysis v2 — Step C4: Capacity Analysis & Gap to 2 Entries/Day")
    lines.append("")
    lines.append("> [!IMPORTANT]")
    lines.append("> **Contamination Disclaimer**:")
    lines.append("> Replay data covers Calibration (60%), Validation (20%), and Test (20%).")
    lines.append("> As documented, validation and test splits were inspected in earlier rounds and are contaminated; clean forward holdout data begins strictly after 2026-11-15 15:00 UTC.")
    lines.append("")
    lines.append("## 1. Setup Availability by Funnel Rejection Gate")
    lines.append("")
    lines.append("Shows the number of distinct sweeps (opportunity keys) available at each gate of the strategy before portfolio rules are applied.")
    lines.append("")
    lines.append("| Funnel Stage / Rejection Gate | Description | Calibration ($n=689\\text{d}$) | Validation ($n=233\\text{d}$) | Test ($n=231\\text{d}$) | Pooled Total ($1,151\\text{d}$) | Distinct Setups / Day |")
    lines.append("| :--- | :--- | ---: | ---: | ---: | ---: | ---: |")
    for row in funnel_summary:
        lines.append(f"| `{row['gate']}` | {row['desc']} | {row['cal_opps']:,} ({row['cal_epd']:.2f}/d) | {row['val_opps']:,} ({row['val_epd']:.2f}/d) | {row['tst_opps']:,} ({row['tst_epd']:.2f}/d) | {row['pool_opps']:,} | **{row['pool_epd']:.3f} / day** |")
    lines.append("")
    lines.append("### Cumulative Setups Available If Upstream Gates Are Reached")
    lines.append("")
    lines.append(f"1. **`CONFIRMED_SETUP` Only (Baseline Strategy Output)**: **1,491 distinct setups** ({raw_opp_epd:.3f} setups/day).")
    lines.append(f"2. **`CONFIRMED_SETUP` + `LTF_PENALTY` (Unconfirmed Near-Miss)**: **2,246 distinct setups** ({combined_epd:.3f} setups/day).")
    lines.append(f"3. **All Filtered Setups (`PA_FLOOR` + `CONFLUENCE_FLOOR`)**: **3,628 distinct setups** ({3628/n_days['pooled']:.3f} setups/day).")
    lines.append(f"4. **Total Raw Sweeps Evaluated (`SCORE_BELOW_THRESHOLD` + all above)**: **22,378 distinct sweeps** ({22378/n_days['pooled']:.2f} sweeps/day).")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 2. Sensitivity Analysis to Portfolio Parameters")
    lines.append("")
    lines.append("> Evaluates sensitivity across all 1,491 accepted setups. Descriptive only; no winner is picked.")
    lines.append("")
    lines.append("### A. Sensitivity to `MAX_CONCURRENT` (Positions Allowed: 1 to 5)")
    lines.append("*Fixed: `MIN_ENTRY_SEPARATION = 1.0 ATR`, `DAILY_LOSS_STOP = -3.0R`*")
    lines.append("")
    lines.append("| `MAX_CONCURRENT` | Calibration Entries/Day (Mean R) | Validation Entries/Day (Mean R) | Test Entries/Day (Mean R) | Pooled Entries/Day (Mean R) | Win Rate | Skipped by Concurrency Cap |")
    lines.append("| :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for mc, r, meta in mc_results:
        lines.append(f"| **{mc}** | {r['calibration'][1]:.3f} ({r['calibration'][2]:+.4f}R) | {r['validation'][1]:.3f} ({r['validation'][2]:+.4f}R) | {r['test'][1]:.3f} ({r['test'][2]:+.4f}R) | **{r['pooled'][1]:.3f} entries/day** ({r['pooled'][2]:+.4f}R) | {r['pooled'][3]:.1f}% | {meta['skipped_by_cap']:,} setups |")
    lines.append("")
    lines.append("### B. Sensitivity to `MIN_ENTRY_SEPARATION` (OFF, 0.5 ATR, 1.0 ATR, 2.0 ATR)")
    lines.append("*Fixed: `MAX_CONCURRENT = 3`, `DAILY_LOSS_STOP = -3.0R`*")
    lines.append("")
    lines.append("| `MIN_ENTRY_SEPARATION` | Calibration Entries/Day (Mean R) | Validation Entries/Day (Mean R) | Test Entries/Day (Mean R) | Pooled Entries/Day (Mean R) | Win Rate | Skipped by Separation |")
    lines.append("| :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for lbl, r, meta in sep_results:
        lines.append(f"| **{lbl}** | {r['calibration'][1]:.3f} ({r['calibration'][2]:+.4f}R) | {r['validation'][1]:.3f} ({r['validation'][2]:+.4f}R) | {r['test'][1]:.3f} ({r['test'][2]:+.4f}R) | **{r['pooled'][1]:.3f} entries/day** ({r['pooled'][2]:+.4f}R) | {r['pooled'][3]:.1f}% | {meta['skipped_by_sep']:,} setups |")
    lines.append("")
    lines.append("### C. Sensitivity to `DAILY_LOSS_STOP` (OFF, -2.0R, -3.0R, -5.0R)")
    lines.append("*Fixed: `MAX_CONCURRENT = 3`, `MIN_ENTRY_SEPARATION = 1.0 ATR`*")
    lines.append("")
    lines.append("| `DAILY_LOSS_STOP` | Calibration Entries/Day (Mean R) | Validation Entries/Day (Mean R) | Test Entries/Day (Mean R) | Pooled Entries/Day (Mean R) | Win Rate | Trading Days Loss Stop Hit | Setups Skipped by Stop |")
    lines.append("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for lbl, r, meta in dls_results:
        lines.append(f"| **{lbl}** | {r['calibration'][1]:.3f} ({r['calibration'][2]:+.4f}R) | {r['validation'][1]:.3f} ({r['validation'][2]:+.4f}R) | {r['test'][1]:.3f} ({r['test'][2]:+.4f}R) | **{r['pooled'][1]:.3f} entries/day** ({r['pooled'][2]:+.4f}R) | {r['pooled'][3]:.1f}% | {meta['hit_days']} days | {meta['skipped_by_dls']} setups |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 3. Gap to 2 Entries/Day: Decomposition & Bottleneck Analysis")
    lines.append("")
    lines.append("The target frequency is **2.000 entries per trading day**.")
    lines.append("")
    lines.append("### A. Step-by-Step Gap Closure")
    lines.append("")
    lines.append("| Step | Configuration / Mechanism | Realized Entries/Day | Absolute Gain | Gap Closed (% of 1.819 gap) | Remaining Gap to 2.0/day |")
    lines.append("| :---: | :--- | :---: | :---: | :---: | :---: |")
    lines.append(f"| Baseline | Current production scanner (`has_active_position` + 2h cooldown) | {prod_epd:.3f} | — | 0.0% | 1.819 entries/day |")
    lines.append(f"| Step (i) | Remove `has_active_position` block, allow `MAX_CONCURRENT = 3` | {base_port_epd:.3f} | +{gap_closed_concurrency:.3f} | 15.8% | 1.533 entries/day |")
    lines.append(f"| Step (ii) | Shorten 2h cooldown (allow entries with >= 1h or 1.0 ATR separation) | {base_port_epd:.3f} | +0.000 | 0.0% | 1.533 entries/day |")
    lines.append(f"| Theoretical Max | Remove ALL concurrency & cooldown caps (`MAX_CONCURRENT = \\infty`) | {raw_opp_epd:.3f} | +{raw_gap_closed - gap_closed_concurrency:.3f} | 45.5% | 0.705 entries/day |")
    lines.append(f"| **Shortfall** | **Gap remaining even with infinite slots and zero cooldown** | — | — | — | **0.705 entries/day** |")
    lines.append("")
    lines.append("### B. The Dual Bottlenecks: Raw Frequency Deficit & Holding Time Choke")
    lines.append("")
    lines.append("Achieving 2.0 entries/day is constrained by two distinct structural barriers:")
    lines.append("")
    lines.append("#### Bottleneck 1: Raw Signal Generation Shortfall (35% Deficit)")
    lines.append(f"- The production SMC strategy logic (`DEFAULT_MIN_SCORE = 60`, `PA_FLOOR = 10`, `CONFLUENCE_FLOOR = 20`) emits exactly **1,491 distinct opportunities** across 1,151 trading days, which is **{raw_opp_epd:.3f} setups/day**.")
    lines.append("- Even if every single emitted signal were executed instantly with zero risk limits, zero cooldown, and unlimited capital, the strategy physically falls short of 2.0/day by **0.705 setups/day** (a 35.2% deficit).")
    lines.append(f"- **Where raw setups exist**: Incorporating the **755 distinct `LTF_PENALTY` near-misses** ({ltf_opps/n_days['pooled']:.3f}/day) would bring the raw pool to **2,246 setups** ({combined_epd:.3f} setups/day, within 2.4% of 2.0/day).")
    lines.append("")
    lines.append("#### Bottleneck 2: Holding Time Concurrency Choke (Mathematical Capacity Limit)")
    lines.append(f"- Under the portfolio rules (`MAX_CONCURRENT = 3`), the mathematical relationship between entries per day ($E$), concurrency ($C$), and mean holding time in hours ($H$) is:")
    lines.append("  $$E_{\\max} = \\frac{C \\times 24}{H}$$")
    lines.append(f"- With $C = 3$ and measured SMC mean holding time $H = {mean_hold_hours:.1f}\\text{{ hours}}$ (median 95.8h; 34.2% timeout after 500 bars):")
    lines.append(f"  $$E_{{\\max}} = \\frac{{3 \\times 24}}{{{mean_hold_hours:.1f}}} = \\mathbf{{{capacity_3_slots:.3f}\\text{{ entries/day}}}}$$")
    lines.append(f"- This proves that even if raw signals were unlimited, **3 concurrency slots with 103-hour holding times can physically never exceed {capacity_3_slots:.2f} entries/day**!")
    lines.append(f"- To enter **2.0 entries/day** under $C = 3$, mean holding time MUST be reduced to:")
    lines.append(f"  $$H \\le \\frac{{3 \\times 24}}{{2.0}} = \\mathbf{{{required_hold_for_2epd_mc3:.1f}\\text{{ hours}}}}$$")
    lines.append("  (A 65% reduction from the current 103.4h hold!).")
    lines.append("")
    lines.append("### C. What Remains Uncovered (Actionable Levers for Phase C2)")
    lines.append("")
    lines.append("To reach ~2 entries/day with positive net expectancy in Phase C2, any viable candidate MUST address both levers simultaneously:")
    lines.append("1. **Expand Raw Setup Ingestion**: Ingest the `LTF_PENALTY` cohort (755 setups, bringing raw pool from 1.295 to 1.951/day) or incorporate high-expectancy near-miss cohorts without loosening core floors.")
    lines.append("2. **Shorten Trade Duration**: Introduce an active time stop (e.g., exit if unresolved after 24-36h) or tighter partial TP to reduce mean holding time from 103.4h down to <= 36.0h, unchoking the 3 concurrency slots.")
    lines.append("3. **Production Scanner Refactoring Required**:")
    lines.append("   - `server/app/services/telegram/scanner.py:273`: Remove `has_active_position` global block; replace with `len(active_positions) < MAX_CONCURRENT`.")
    lines.append("   - `server/app/services/telegram/scanner.py:38`: Replace `SIGNAL_COOLDOWN_HOURS = 2` with ATR-based separation and sweep de-duplication.")

    report_path = out_dir / "stepC4_capacity.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[+] Wrote Step C4 report: {report_path}")


if __name__ == "__main__":
    run_step_c4()
