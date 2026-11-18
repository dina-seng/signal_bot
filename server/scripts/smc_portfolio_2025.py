"""Real (portfolio-constrained) SMC backtest for the 2025-01-01 -> latest window.

Reads the already-produced replay checkpoints in
``reports/exp_2025_smc/checkpoints`` (one record per evaluated 15m bar) and
replays ONLY the frozen portfolio rules from ``docs/SMC_FREEZE_V2.md``. Nothing
in this script changes a strategy threshold, score, gate or default: the
strategy output is taken verbatim from the checkpoints.

Frozen portfolio rules (unchanged):
  - MAX_CONCURRENT = 3 open positions
  - ONE_ENTRY_PER_SWEEP = one entry per opportunity_key (first accepted bar)
  - MIN_ENTRY_SEPARATION = a same-direction entry needs >= 1.0 x ATR(14, 15m)
    price distance from every open same-direction entry, OR >= 1h since the last
    same-direction entry (implemented exactly as the frozen code; see difference 6)
  - DAILY_LOSS_STOP = -3.0 R realized per UTC day halts new entries that day
  - Risk per position = 1.0 R; the $0.40 round-trip spread is already inside the
    checkpoint ``r_multiple`` values.

Candles are opened read-only from ``backtest.db`` (SQLite ``mode=ro``) and are
used only for (a) ATR(14, 15m) and (b) re-simulating the Step 4 controls with
the shared ``simulate_outcome`` engine.

Differences versus ``server/scripts/smc_portfolio.py`` (rule logic copied, the
original file is NOT edited):
  1. Checkpoint source is ``reports/exp_2025_smc/checkpoints`` (2025-01+ window)
     instead of ``reports/smc_replay_extended/checkpoints``.
  2. Every rule skip is counted per half-year and reported as a CRT-style funnel.
  3. Controls are re-simulated from the constrained entries using the *stored*
     TP ladder mirrored to the opposite direction instead of a nominal 2R/3R
     ladder. The two agree to float precision (see verification note).
  4. Both the ratio-preserving shuffle (the pre-registered C2 control) and a
     plain 50/50 random-direction control are run, 1,000 seeds each.
  5. Portfolio-rule attribution order is unchanged (daily stop -> concurrency ->
     separation); the accepted set is order-independent, only attribution moves.
  6. MIN_ENTRY_SEPARATION is evaluated per open same-direction position exactly as
     the frozen code does (skip only when an open entry is both <1h and <1 ATR
     away), not as a global 1h escape after the last same-direction entry. The
     difference is disclosed in the report's limits section.

Usage
-----
    cd server
    python scripts/smc_portfolio_2025.py
    python scripts/smc_portfolio_2025.py --start-date 2025-01-01 --seeds 1000
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
SCRIPTS_ROOT = SERVER_ROOT / "scripts"
for _p in (SERVER_ROOT, SCRIPTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.services.indicators.atr_calculator import ATRCalculator  # noqa: E402
from crt_replay import (  # noqa: E402
    SignalRecord,
    _parse_start_date,
    load_full_15m_candles,
    simulate_outcome,
)

TF_15M = timedelta(minutes=15)

# --- Frozen portfolio constants (docs/SMC_FREEZE_V2.md, section 2) -----------
MAX_CONCURRENT = 3
DAILY_LOSS_STOP = -3.0
ATR_PERIOD = 14
SEPARATION_ATR_MULT = 1.0
SEPARATION_MIN_HOURS = 1.0

# --- Frozen execution constants (checkpoint provenance) ----------------------
SPREAD = 0.40
EXPIRY_BARS = 8
MAX_HOLD_BARS = 500

# --- Pre-registered verification targets ------------------------------------
EXPECTED_TRADES = 688
EXPECTED_TOTAL_R = 136.45
R_CHECK_TOL = 0.005

HALF_YEARS = ("2025-H1", "2025-H2", "2026-H1", "2026-H2")
# Half-years treated as validation / test for the Step 4 pass rule (see report).
VALIDATION_PERIOD = "2026-H1"
TEST_PERIOD = "2026-H2"
PASS_PERCENTILE = 97.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def period_of(dt: datetime) -> str:
    return f"{dt.year}-H{1 if dt.month <= 6 else 2}"


def period_bounds(period: str) -> Tuple[datetime, datetime]:
    year = int(period[:4])
    if period.endswith("H1"):
        return (
            datetime(year, 1, 1, tzinfo=timezone.utc),
            datetime(year, 7, 1, tzinfo=timezone.utc),
        )
    return (
        datetime(year, 7, 1, tzinfo=timezone.utc),
        datetime(year + 1, 1, 1, tzinfo=timezone.utc),
    )


def fmt(v: Any, digits: int = 4) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        if math.isinf(v):
            return "inf"
        return f"{v:.{digits}f}"
    return str(v)


def fmt_signed(v: Any, digits: int = 4) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.{digits}f}"


def warn_flag(n: int) -> str:
    return "  n<30" if n < 30 else ""


def write_csv(path: Path, rows: Sequence[Dict[str, Any]], columns: Sequence[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in columns})


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def load_checkpoint_trades(
    ckpt_dir: Path,
    bars: Sequence[Any],
    atr_series: Sequence[Optional[float]],
    bar_close_index: Dict[datetime, int],
    start: datetime,
    end: Optional[datetime],
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Load every accepted bar in [start, end] as a flat trade dict."""
    files = sorted(glob.glob(str(ckpt_dir / "*.json")))
    if not files:
        raise SystemExit(f"No checkpoint files found in {ckpt_dir}")

    raw: List[Dict[str, Any]] = []
    total_records = 0
    for fpath in files:
        with open(fpath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        total_records += len(data["records"])
        for r in data["records"]:
            if not (r.get("accepted") and r.get("accepted_trade")):
                continue
            t = dict(r["accepted_trade"])
            decision_dt = datetime.fromisoformat(r["decision_time"])
            exit_dt = datetime.fromisoformat(t["exit_time"])
            if decision_dt < start:
                continue
            if end is not None and decision_dt >= end:
                continue
            idx = bar_close_index.get(decision_dt)
            if idx is None:
                raise SystemExit(f"Decision bar not found in candle series: {decision_dt}")
            atr_value = atr_series[idx]
            if atr_value is None or atr_value <= 0:
                raise SystemExit(f"ATR(14) unavailable at {decision_dt}")

            entry = float(t["crt_entry"])
            stop = float(t["stop_loss"])
            trade = {
                "decision_dt": decision_dt,
                "exit_dt": exit_dt,
                "day": decision_dt.strftime("%Y-%m-%d"),
                "month": r["month"],
                "split": r["split"],
                "score": float(r["score"]),
                "direction": t["direction"],
                "entry": entry,
                "stop_loss": stop,
                "take_profit_1": float(t["take_profit_1"]),
                "take_profit_2": float(t["take_profit_2"]),
                "risk_price": float(t["risk_price"]),
                "rr_planned": float(t["rr_planned"]),
                "r": float(t["r_multiple"]),
                "exit_reason": t["exit_reason"],
                "bars_held": int(t["bars_held"]),
                "wall_hours": (exit_dt - decision_dt).total_seconds() / 3600.0,
                "key": r.get("opportunity_key") or t.get("sweep_key") or "",
                "bar_idx": idx,
                "atr": float(atr_value),
                "period": period_of(decision_dt),
            }
            raw.append(trade)

    raw.sort(key=lambda x: (x["decision_dt"], x["bar_idx"]))
    return raw, len(files), total_records


def dedupe_by_key(trades: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ONE_ENTRY_PER_SWEEP: keep the first accepted bar per opportunity_key."""
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for t in trades:
        if t["key"] in seen:
            continue
        seen.add(t["key"])
        out.append(t)
    return out


# ---------------------------------------------------------------------------
# Step 1: frozen portfolio rules
# ---------------------------------------------------------------------------
def apply_portfolio_rules(
    distinct: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Dict[str, int]]]:
    """Replay the frozen rules in decision-time order (same logic as smc_portfolio.py).

    Returns (entered, skipped, skip_counts) where skip_counts["all"] and
    skip_counts[period] hold per-rule counts. The order of the three checks
    (daily stop -> concurrency -> separation) only affects attribution, never
    whether a setup is entered.
    """
    entered: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    open_positions: List[Dict[str, Any]] = []

    for t in distinct:
        dt = t["decision_dt"]
        day_str = t["day"]
        direction = t["direction"]
        price = t["entry"]
        atr = t["atr"]
        period = t["period"]

        # Close anything whose exit is at or before this decision instant.
        open_positions = [p for p in open_positions if p["exit_dt"] > dt]

        # Rule 1: DAILY_LOSS_STOP (-3.0 R realized, UTC day, exits up to now).
        realized_today = sum(
            p["r"]
            for p in entered
            if p["exit_dt"].strftime("%Y-%m-%d") == day_str and p["exit_dt"] <= dt
        )
        if realized_today <= DAILY_LOSS_STOP:
            reason = "DAILY_LOSS_STOP"
        # Rule 2: MAX_CONCURRENT.
        elif len(open_positions) >= MAX_CONCURRENT:
            reason = "CONCURRENCY_CAP"
        else:
            # Rule 3: MIN_ENTRY_SEPARATION. Skip only when an open same-direction
            # entry is both < 1h away and < 1 ATR in price (frozen implementation).
            close_conflict = any(
                (dt - p["decision_dt"]) < timedelta(hours=SEPARATION_MIN_HOURS)
                and abs(price - p["entry"]) < (SEPARATION_ATR_MULT * atr)
                for p in open_positions
                if p["direction"] == direction
            )
            reason = "SEPARATION_RULE" if close_conflict else ""

        if reason:
            counts["all"][reason] += 1
            counts[period][reason] += 1
            rec = dict(t)
            rec["skip_reason"] = reason
            skipped.append(rec)
            continue

        entered.append(t)
        open_positions.append(t)

    return entered, skipped, counts


# ---------------------------------------------------------------------------
# Step 2: metrics
# ---------------------------------------------------------------------------
def exit_ordered(trades: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(trades, key=lambda t: (t["exit_dt"], t["decision_dt"], t["key"]))


def compute_metrics(
    trades: Sequence[Dict[str, Any]],
    window_start: datetime,
) -> Dict[str, Any]:
    n = len(trades)
    rs = [t["r"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_gain = sum(wins)
    gross_loss = abs(sum(losses))

    ordered = exit_ordered(trades)
    equity = 0.0
    peak = 0.0
    peak_time = window_start
    peak_idx = -1
    in_dd = False
    max_dd = 0.0
    max_dd_days = 0.0
    max_dd_trades = 0
    max_dd_open_end = False
    curve: List[Dict[str, Any]] = []
    for i, t in enumerate(ordered):
        equity += t["r"]
        dd = peak - equity
        max_dd = max(max_dd, dd)
        if equity >= peak - 1e-12:
            if in_dd:
                days = (t["exit_dt"] - peak_time).total_seconds() / 86400.0
                if days > max_dd_days:
                    max_dd_days = days
                    max_dd_trades = i - peak_idx
                    max_dd_open_end = False
                in_dd = False
            peak = equity
            peak_time = t["exit_dt"]
            peak_idx = i
        else:
            in_dd = True
        curve.append({"exit_dt": t["exit_dt"], "cum_r": equity, "drawdown_r": dd})
    if in_dd and ordered:
        days = (ordered[-1]["exit_dt"] - peak_time).total_seconds() / 86400.0
        if days > max_dd_days:
            max_dd_days = days
            max_dd_trades = len(ordered) - 1 - peak_idx
            max_dd_open_end = True

    bars = [t["bars_held"] for t in trades]
    hours = [t["wall_hours"] for t in trades]
    exit_counts = Counter(t["exit_reason"] for t in trades)

    return {
        "n": n,
        "win_rate": (100.0 * len(wins) / n) if n else None,
        "avg_r": (sum(rs) / n) if n else None,
        "median_r": float(np.median(rs)) if n else None,
        "profit_factor": (
            (gross_gain / gross_loss) if gross_loss > 0 else (math.inf if gross_gain > 0 else 0.0)
        ) if n else None,
        "total_r": sum(rs) if n else None,
        "max_dd_r": max_dd if n else None,
        "max_dd_days": max_dd_days if n else None,
        "max_dd_trades": max_dd_trades if n else None,
        "max_dd_open_end": max_dd_open_end if n else False,
        "hold_bars_median": float(np.median(bars)) if n else None,
        "hold_bars_p90": float(np.percentile(bars, 90)) if n else None,
        "hold_hours_median": float(np.median(hours)) if n else None,
        "hold_hours_p90": float(np.percentile(hours, 90)) if n else None,
        "exit_counts": dict(exit_counts),
        "flagged_lt30": n < 30,
        "curve": curve,
    }


def compute_exposure(
    all_trades: Sequence[Dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
) -> Dict[str, Any]:
    """Time-weighted concurrency over [window_start, window_end) (wall clock)."""
    intervals: List[Tuple[datetime, datetime]] = []
    for t in all_trades:
        s = max(t["decision_dt"], window_start)
        e = min(t["exit_dt"], window_end)
        if e > s:
            intervals.append((s, e))
    if window_end <= window_start:
        return {"max": 0, "mean": 0.0, "shares": {k: 0.0 for k in range(MAX_CONCURRENT + 1)}}

    times = sorted({window_start, window_end} | {s for s, _ in intervals} | {e for _, e in intervals})
    seconds = {k: 0.0 for k in range(MAX_CONCURRENT + 1)}
    max_seen = 0
    weighted = 0.0
    total = 0.0
    for a, b in zip(times, times[1:]):
        dur = (b - a).total_seconds()
        if dur <= 0:
            continue
        count = sum(1 for s, e in intervals if s <= a and e >= b)
        max_seen = max(max_seen, count)
        bucket = min(count, MAX_CONCURRENT)
        seconds[bucket] += dur
        weighted += count * dur
        total += dur

    shares = {k: (100.0 * v / total if total > 0 else 0.0) for k, v in seconds.items()}
    return {
        "max": max_seen,
        "mean": (weighted / total) if total > 0 else 0.0,
        "shares": shares,
        "window_hours": total / 3600.0,
    }


# ---------------------------------------------------------------------------
# Step 4: controls
# ---------------------------------------------------------------------------
def simulate_control(
    trade: Dict[str, Any],
    direction: str,
    bars: Sequence[Any],
) -> float:
    """Re-simulate the entry with the same stop distance and TP geometry."""
    entry = trade["entry"]
    risk = abs(entry - trade["stop_loss"])
    tp1_dist = abs(trade["take_profit_1"] - entry)
    tp2_dist = abs(trade["take_profit_2"] - entry)
    sign = 1.0 if direction == "BUY" else -1.0
    rec = SignalRecord(
        signal_time=trade["decision_dt"],
        direction=direction,
        tier=None,
        session=None,
        entry_mode="market",
        crt_entry=entry,
        stop_loss=entry - sign * risk,
        take_profit_1=entry + sign * tp1_dist,
        take_profit_2=entry + sign * tp2_dist,
        risk_price=risk,
        rr_planned=trade["rr_planned"],
        score=trade["score"],
        sweep_key=trade["key"],
    )
    simulate_outcome(
        rec, bars, trade["bar_idx"], spread=SPREAD,
        expiry_bars=EXPIRY_BARS, max_hold_bars=MAX_HOLD_BARS,
    )
    return float(rec.r_multiple)


def attach_controls(trades: Sequence[Dict[str, Any]], bars: Sequence[Any]) -> int:
    """Attach buy_r / sell_r / alpha to each trade; return re-simulation mismatches."""
    mismatches = 0
    for t in trades:
        t["buy_r"] = simulate_control(t, "BUY", bars)
        t["sell_r"] = simulate_control(t, "SELL", bars)
        t["neutral_r"] = 0.5 * (t["buy_r"] + t["sell_r"])
        t["alpha"] = t["r"] - t["neutral_r"]
        real = t["buy_r"] if t["direction"] == "BUY" else t["sell_r"]
        if abs(real - t["r"]) > 1e-9:
            mismatches += 1
    return mismatches


def percentile_rank(dist: Sequence[float], value: float) -> float:
    return 100.0 * sum(1 for x in dist if x <= value) / len(dist) if dist else 0.0


def control_block(
    trades: Sequence[Dict[str, Any]],
    seeds: Sequence[int],
) -> Dict[str, Any]:
    """Always-BUY / Always-SELL / 50-50 coin / ratio-preserving shuffle."""
    n = len(trades)
    rs = [t["r"] for t in trades]
    coin_dist: List[float] = []
    ratio_dist: List[float] = []

    for seed in seeds:
        coin_rng = random.Random(seed)
        coin_rs = [
            t["buy_r"] if coin_rng.random() < 0.5 else t["sell_r"]
            for t in trades
        ]
        coin_dist.append(float(np.mean(coin_rs)) if coin_rs else 0.0)

        ratio_rng = random.Random(seed)
        n_buy = sum(1 for t in trades if t["direction"] == "BUY")
        pool = ["BUY"] * n_buy + ["SELL"] * (n - n_buy)
        ratio_rng.shuffle(pool)
        ratio_rs = [
            t["buy_r"] if assigned == "BUY" else t["sell_r"]
            for t, assigned in zip(trades, pool)
        ]
        ratio_dist.append(float(np.mean(ratio_rs)) if ratio_rs else 0.0)

    real_mean = float(np.mean(rs)) if rs else None
    real_wr = 100.0 * sum(1 for r in rs if r > 0) / n if n else None
    buy_rs = [t["buy_r"] for t in trades]
    sell_rs = [t["sell_r"] for t in trades]

    def stats(dist: List[float]) -> Dict[str, Any]:
        if not dist:
            return {"mean": None, "std": None, "p5": None, "p95": None, "pct": None}
        return {
            "mean": float(np.mean(dist)),
            "std": float(np.std(dist)),
            "p5": float(np.percentile(dist, 5)),
            "p95": float(np.percentile(dist, 95)),
            "pct": percentile_rank(dist, real_mean) if real_mean is not None else None,
        }

    return {
        "n": n,
        "real_mean_r": real_mean,
        "real_wr": real_wr,
        "always_buy_mean_r": float(np.mean(buy_rs)) if buy_rs else None,
        "always_buy_wr": (100.0 * sum(1 for r in buy_rs if r > 0) / n) if n else None,
        "always_sell_mean_r": float(np.mean(sell_rs)) if sell_rs else None,
        "always_sell_wr": (100.0 * sum(1 for r in sell_rs if r > 0) / n) if n else None,
        "coin": stats(coin_dist),
        "ratio": stats(ratio_dist),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Portfolio-constrained SMC replay on the 2025+ checkpoint window.",
    )
    p.add_argument("--db-path", default=str(REPO_ROOT / "backtest.db"))
    p.add_argument("--symbol", default="XAU/USD")
    p.add_argument("--source", default="twelvedata")
    p.add_argument(
        "--checkpoint-dir",
        default=str(REPO_ROOT / "reports" / "exp_2025_smc" / "checkpoints"),
    )
    p.add_argument(
        "--out-dir",
        default=str(REPO_ROOT / "reports" / "exp_2025_smc_portfolio"),
    )
    p.add_argument("--start-date", default="2025-01-01")
    p.add_argument("--end-date", default=None, help="Optional exclusive end date (YYYY-MM-DD)")
    p.add_argument("--seeds", type=int, default=1000)
    p.add_argument("--force", action="store_true", help="Overwrite an existing report.md")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    started = datetime.now()

    start = _parse_start_date(args.start_date)
    if start is None:
        raise SystemExit("--start-date is required")
    end = _parse_start_date(args.end_date) if args.end_date else None

    out_dir = Path(args.out_dir)
    report_path = out_dir / "report.md"
    if report_path.exists() and not args.force:
        raise SystemExit(f"Refusing to overwrite existing report: {report_path} (use --force)")

    print("[*] Loading candles (read-only) ...")
    bars, meta = load_full_15m_candles(Path(args.db_path), args.symbol, args.source)
    print(
        f"[*] {len(bars):,} open-market 15m bars "
        f"({meta['raw_first']:%Y-%m-%d %H:%M} -> {meta['raw_last']:%Y-%m-%d %H:%M} UTC)"
    )
    if end is None:
        end = bars[-1].timestamp + TF_15M

    calc = ATRCalculator()
    atr_series = calc.calculate_atr_series(
        [b.high for b in bars], [b.low for b in bars], [b.close for b in bars], ATR_PERIOD,
    )
    bar_close_index = {b.timestamp + TF_15M: i for i, b in enumerate(bars)}

    # ------------------------------------------------------------------
    # Verification gate: 688 trades / +136.45 R unconstrained.
    # ------------------------------------------------------------------
    raw, n_files, n_records = load_checkpoint_trades(
        Path(args.checkpoint_dir), bars, atr_series, bar_close_index, start, end,
    )
    distinct = dedupe_by_key(raw)
    total_r = sum(t["r"] for t in distinct)
    print(f"[*] Checkpoints: {n_files} files / {n_records:,} bar records")
    print(f"[*] Accepted bars: {len(raw):,}; distinct opportunity keys: {len(distinct):,}")
    print(f"[*] Unconstrained total R: {total_r:+.4f}")
    if len(distinct) != EXPECTED_TRADES:
        raise SystemExit(
            f"VERIFICATION FAILED: expected {EXPECTED_TRADES} distinct trades, got {len(distinct)}"
        )
    if abs(total_r - EXPECTED_TOTAL_R) > R_CHECK_TOL:
        raise SystemExit(
            f"VERIFICATION FAILED: expected {EXPECTED_TOTAL_R:+.2f} R, got {total_r:+.4f} R"
        )
    print("[+] Verification passed: 688 trades / +136.45 R unconstrained")

    n_buy_all = sum(1 for t in distinct if t["direction"] == "BUY")
    n_sell_all = len(distinct) - n_buy_all

    # ------------------------------------------------------------------
    # Step 1: frozen portfolio rules.
    # ------------------------------------------------------------------
    entered, skipped, skip_counts = apply_portfolio_rules(distinct)
    repeat_bars = len(raw) - len(distinct)
    print(f"[*] Portfolio entered: {len(entered):,} | skipped: {dict(skip_counts['all'])}")

    # ------------------------------------------------------------------
    # Step 4 geometry: attach controls to the constrained entries.
    # ------------------------------------------------------------------
    print(f"[*] Re-simulating BUY/SELL controls for {len(entered):,} entries ...")
    mismatches = attach_controls(entered, bars)
    if mismatches:
        raise SystemExit(
            f"VERIFICATION FAILED: {mismatches} re-simulated trades differ from checkpoint R"
        )
    print("[+] Control re-simulation reproduces every checkpoint r_multiple exactly")

    # ------------------------------------------------------------------
    # Metrics, whole window + half-years.
    # ------------------------------------------------------------------
    period_trades: Dict[str, List[Dict[str, Any]]] = {p: [] for p in HALF_YEARS}
    for t in entered:
        period_trades.setdefault(t["period"], []).append(t)
    all_periods = list(HALF_YEARS) + sorted(p for p in period_trades if p not in HALF_YEARS)

    metrics_all = compute_metrics(entered, start)
    metrics_by_period = {
        p: compute_metrics(period_trades[p], max(start, period_bounds(p)[0]))
        for p in all_periods
    }
    exposure_all = compute_exposure(entered, start, end)
    exposure_by_period = {}
    for p in all_periods:
        p_start, p_end = period_bounds(p)
        exposure_by_period[p] = compute_exposure(
            entered, max(start, p_start), min(end, p_end),
        )

    # Unconstrained metrics by period and direction.
    unconstrained_by_period = {p: [] for p in all_periods}
    for t in distinct:
        unconstrained_by_period.setdefault(t["period"], []).append(t)

    def direction_metrics(trades: Sequence[Dict[str, Any]], window_start: datetime) -> Dict[str, Any]:
        out = {}
        for direction in ("BUY", "SELL"):
            sub = [t for t in trades if t["direction"] == direction]
            out[direction] = compute_metrics(sub, window_start)
        return out

    dir_constrained = direction_metrics(entered, start)
    dir_unconstrained = direction_metrics(distinct, start)

    # ------------------------------------------------------------------
    # Step 4 controls.
    # ------------------------------------------------------------------
    seeds = list(range(1, args.seeds + 1))
    print(f"[*] Running {len(seeds):,} seeds (50/50 coin + ratio-preserving shuffle) ...")
    controls_all = control_block(entered, seeds)
    controls_by_period = {p: control_block(period_trades[p], seeds) for p in all_periods}

    # Secondary: controls on the frozen walk-forward split labels.
    split_names = ("calibration", "validation", "test")
    controls_by_split = {
        s: control_block([t for t in entered if t["split"] == s], seeds) for s in split_names
    }

    # ------------------------------------------------------------------
    # Outputs
    # ------------------------------------------------------------------
    out_dir.mkdir(parents=True, exist_ok=True)

    curve_rows: List[Dict[str, Any]] = []
    equity = 0.0
    peak = 0.0
    for t in exit_ordered(entered):
        equity += t["r"]
        peak = max(peak, equity)
        curve_rows.append({
            "exit_time": t["exit_dt"].isoformat(),
            "decision_time": t["decision_dt"].isoformat(),
            "period": t["period"],
            "direction": t["direction"],
            "r_multiple": t["r"],
            "cum_r": round(equity, 4),
            "drawdown_r": round(peak - equity, 4),
            "opportunity_key": t["key"],
        })
    write_csv(
        out_dir / "equity_curve.csv", curve_rows,
        ("exit_time", "decision_time", "period", "direction", "r_multiple",
         "cum_r", "drawdown_r", "opportunity_key"),
    )

    trade_rows = []
    for t in entered:
        trade_rows.append({
            "decision_time": t["decision_dt"].isoformat(),
            "exit_time": t["exit_dt"].isoformat(),
            "period": t["period"],
            "split": t["split"],
            "month": t["month"],
            "direction": t["direction"],
            "entry": t["entry"],
            "stop_loss": t["stop_loss"],
            "take_profit_1": t["take_profit_1"],
            "take_profit_2": t["take_profit_2"],
            "risk_price": t["risk_price"],
            "atr_14": round(t["atr"], 4),
            "r_multiple": t["r"],
            "exit_reason": t["exit_reason"],
            "bars_held": t["bars_held"],
            "wall_clock_hours": round(t["wall_hours"], 3),
            "buy_r": t["buy_r"],
            "sell_r": t["sell_r"],
            "alpha": round(t["alpha"], 4),
            "opportunity_key": t["key"],
        })
    write_csv(
        out_dir / "trades.csv", trade_rows,
        ("decision_time", "exit_time", "period", "split", "month", "direction",
         "entry", "stop_loss", "take_profit_1", "take_profit_2", "risk_price",
         "atr_14", "r_multiple", "exit_reason", "bars_held", "wall_clock_hours",
         "buy_r", "sell_r", "alpha", "opportunity_key"),
    )

    funnel_rows = [
        {"stage": "RAW_ACCEPTED_BARS", "count": len(raw),
         "note": "Every accepted 15m bar in the window"},
        {"stage": "SKIPPED_REPEAT_SWEEP", "count": repeat_bars,
         "note": "Later 15m bars from the same opportunity_key"},
        {"stage": "DISTINCT_OPPORTUNITIES", "count": len(distinct),
         "note": "ONE_ENTRY_PER_SWEEP applied"},
        {"stage": "SKIPPED_CONCURRENCY_CAP", "count": skip_counts["all"]["CONCURRENCY_CAP"],
         "note": "MAX_CONCURRENT=3 already open"},
        {"stage": "SKIPPED_SEPARATION_RULE", "count": skip_counts["all"]["SEPARATION_RULE"],
         "note": "< 1 ATR and < 1h from an open same-direction entry"},
        {"stage": "SKIPPED_DAILY_LOSS_STOP", "count": skip_counts["all"]["DAILY_LOSS_STOP"],
         "note": "Day already at or below -3.0 R realized"},
        {"stage": "SKIPPED_UNFILLED", "count": 0,
         "note": "n/a — all entries are market fills"},
        {"stage": "PORTFOLIO_ENTERED", "count": len(entered),
         "note": "Executed with $0.40 round-trip friction"},
    ]
    write_csv(out_dir / "funnel.csv", funnel_rows, ("stage", "count", "note"))

    control_rows = []
    for p in ["ALL"] + all_periods:
        c = controls_all if p == "ALL" else controls_by_period[p]
        control_rows.append({
            "period": p,
            "n": c["n"],
            "real_mean_r": c["real_mean_r"],
            "real_win_rate": c["real_wr"],
            "always_buy_mean_r": c["always_buy_mean_r"],
            "always_sell_mean_r": c["always_sell_mean_r"],
            "coin_mean_r": c["coin"]["mean"],
            "coin_std": c["coin"]["std"],
            "coin_percentile": c["coin"]["pct"],
            "shuffle_mean_r": c["ratio"]["mean"],
            "shuffle_std": c["ratio"]["std"],
            "shuffle_percentile": c["ratio"]["pct"],
            "flagged_lt30": c["n"] < 30,
        })
    write_csv(
        out_dir / "controls.csv", control_rows,
        ("period", "n", "real_mean_r", "real_win_rate", "always_buy_mean_r",
         "always_sell_mean_r", "coin_mean_r", "coin_std", "coin_percentile",
         "shuffle_mean_r", "shuffle_std", "shuffle_percentile", "flagged_lt30"),
    )

    # ------------------------------------------------------------------
    # Markdown
    # ------------------------------------------------------------------
    def pct_or_na(v: Any) -> str:
        return "n/a" if v is None else f"{v:.1f}%"

    def pass_cell(pct: Optional[float]) -> str:
        if pct is None:
            return "n/a"
        return "PASS" if pct >= PASS_PERCENTILE else "FAIL"

    lines: List[str] = []
    A = lines.append
    A("# SMC — Real (Portfolio-Constrained) Backtest, 2025-01-01 → Latest")
    A("")
    A("**Scope**: the already-produced SMC replay in `reports/exp_2025_smc/checkpoints` "
      "replayed through the frozen portfolio rules only. No threshold, score, gate or "
      "default was changed; SMC is frozen per `docs/SMC_FREEZE_V2.md`.")
    A("")
    A(f"**Window**: {start:%Y-%m-%d %H:%M} → {end - TF_15M:%Y-%m-%d %H:%M} UTC (decision times). "
      "This is the last **open-market** bar: the database's closed-market placeholder bars "
      "(Friday 22:00 → Sunday 22:00 UTC) are filtered out at load time, so the raw table "
      "extends to 2026-11-15 15:00 but the analysable window ends on the Friday close.")
    A("")
    A("**Input verification** (must hold before any metric is reported):")
    A("")
    A("| Check | Expected | Observed | Result |")
    A("| :--- | ---: | ---: | :--- |")
    A(f"| Distinct trades (one per `opportunity_key`) | {EXPECTED_TRADES:,} | {len(distinct):,} | PASS |")
    A(f"| Unconstrained total R | {EXPECTED_TOTAL_R:+.2f} | {total_r:+.4f} | PASS |")
    A(f"| Re-simulated R == checkpoint R | 0 mismatches | {mismatches} | PASS |")
    A("")
    A("Data: `backtest.db` opened read-only (`mode=ro`), Twelve Data 15m bars, "
      "open-market bars only. `$0.40` round-trip friction is already inside every "
      "checkpoint `r_multiple`; controls re-use the same friction through the shared "
      "`simulate_outcome` engine.")
    A("")
    A("---")
    A("")

    # ---- 1. Funnel -------------------------------------------------
    A("## 1. Portfolio funnel (frozen rules, decision-time order)")
    A("")
    A("| Funnel Stage | Count | Notes |")
    A("| :--- | ---: | :--- |")
    for row in funnel_rows:
        label = {
            "RAW_ACCEPTED_BARS": "Raw accepted signals (15m bars)",
            "SKIPPED_REPEAT_SWEEP": "Skipped: repeat sweep (`ONE_ENTRY_PER_SWEEP`)",
            "DISTINCT_OPPORTUNITIES": "Distinct opportunities (input to rules)",
            "SKIPPED_CONCURRENCY_CAP": "Skipped: concurrency cap (`MAX_CONCURRENT=3`)",
            "SKIPPED_SEPARATION_RULE": "Skipped: separation rule (`MIN_ENTRY_SEPARATION`)",
            "SKIPPED_DAILY_LOSS_STOP": "Skipped: daily loss stop (`DAILY_LOSS_STOP=-3.0R`)",
            "SKIPPED_UNFILLED": "Skipped: unfilled limit-zone order",
            "PORTFOLIO_ENTERED": "**Portfolio entered trades**",
        }[row["stage"]]
        A(f"| {label} | {row['count']:,} | {row['note']} |")
    A("")
    A("Rule attribution order is daily stop → concurrency → separation (frozen "
      "implementation). The accepted set is invariant to that order; only the "
      "attribution of a multi-cause skip moves.")
    A("")
    A("### Funnel by half-year")
    A("")
    A("| Period | Accepted bars | Repeat sweep | Distinct | Concurrency | Separation | Daily stop | Entered |")
    A("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for p in all_periods:
        raw_n = sum(1 for t in raw if t["period"] == p)
        dist_n = sum(1 for t in distinct if t["period"] == p)
        ent_n = sum(1 for t in entered if t["period"] == p)
        A(
            f"| {p} | {raw_n:,} | {raw_n - dist_n:,} | {dist_n:,} | "
            f"{skip_counts[p]['CONCURRENCY_CAP']:,} | {skip_counts[p]['SEPARATION_RULE']:,} | "
            f"{skip_counts[p]['DAILY_LOSS_STOP']:,} | {ent_n:,} |"
        )
    A(f"| **Total** | {len(raw):,} | {repeat_bars:,} | {len(distinct):,} | "
      f"{skip_counts['all']['CONCURRENCY_CAP']:,} | {skip_counts['all']['SEPARATION_RULE']:,} | "
      f"{skip_counts['all']['DAILY_LOSS_STOP']:,} | {len(entered):,} |")
    A("")
    A("---")
    A("")

    # ---- 2. Metrics ------------------------------------------------
    A("## 2. Constrained performance: whole window and by half-year")
    A("")
    A("Trades are assigned to a half-year by **decision time**; within each group the "
      "equity curve, drawdown and exit ordering use **exit time**, not entry time. "
      "Holding time in *market bars* counts open-market 15m bars held; wall-clock "
      "hours run from decision time to the exit bar's open time (the checkpoint's "
      "`exit_time`).")
    A("")
    A("| Period | Trades | Win rate | Avg R | Median R | Profit factor | Total R | Max DD (R) | Longest DD | Hold med (bars / h) | Hold p90 (bars / h) | Flag |")
    A("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- | :--- | :--- |")
    for p, m in [("ALL", metrics_all)] + [(p, metrics_by_period[p]) for p in all_periods]:
        label = "**Whole window**" if p == "ALL" else p
        A(
            f"| {label} | {m['n']:,} | {pct_or_na(m['win_rate'])} | {fmt_signed(m['avg_r'])} | "
            f"{fmt_signed(m['median_r'])} | {fmt(m['profit_factor'], 2)} | "
            f"{fmt_signed(m['total_r'], 2)} | {fmt(m['max_dd_r'], 2)} | "
            f"{fmt(m['max_dd_days'], 1)} d ({m['max_dd_trades']} trades"
            f"{', open' if m['max_dd_open_end'] else ''}) | "
            f"{fmt(m['hold_bars_median'], 0)} / {fmt(m['hold_hours_median'], 1)} | "
            f"{fmt(m['hold_bars_p90'], 0)} / {fmt(m['hold_hours_p90'], 1)} | "
            f"{'n<30' if m['flagged_lt30'] else ''} |"
        )
    A("")
    A("Max drawdown is peak-to-trough on the cumulative-R curve ordered by exit time. "
      "Longest drawdown is the wall-clock time from the equity peak to the first exit "
      "that regains it (or to the last exit if it never does); a duration marked "
      "`open` had not been recovered by the window end.")
    A("")

    A("### Exit-reason breakdown")
    A("")
    reasons = sorted(
        {r for m in [metrics_all] + list(metrics_by_period.values()) for r in m["exit_counts"]}
    )
    A("| Exit reason | Whole window | Share | Avg R | " + " | ".join(all_periods) + " |")
    A("| :--- | ---: | ---: | ---: | " + " | ".join("---:" for _ in all_periods) + " |")
    for reason in sorted(reasons, key=lambda r: -metrics_all["exit_counts"].get(r, 0)):
        cnt = metrics_all["exit_counts"].get(reason, 0)
        share = 100.0 * cnt / len(entered) if entered else 0.0
        sub = [t["r"] for t in entered if t["exit_reason"] == reason]
        A(
            f"| `{reason}` | {cnt:,} | {share:.1f}% | "
            f"{fmt_signed(float(np.mean(sub)) if sub else None)} | "
            + " | ".join(str(metrics_by_period[p]["exit_counts"].get(reason, 0)) for p in all_periods)
            + " |"
        )
    A("")

    A("### Concurrency exposure")
    A("")
    A("Time-weighted over wall-clock time inside each window "
      "(closed-market hours included).")
    A("")
    A("| Period | Window hours | Max concurrent | Mean concurrent | % time 0 open | % time 1 open | % time 2 open | % time 3 open |")
    A("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for p, e in [("ALL", exposure_all)] + [(p, exposure_by_period[p]) for p in all_periods]:
        label = "**Whole window**" if p == "ALL" else p
        sh = e["shares"]
        A(
            f"| {label} | {e.get('window_hours', 0.0):,.0f} | {e['max']} | {e['mean']:.2f} | "
            f"{sh[0]:.1f}% | {sh[1]:.1f}% | {sh[2]:.1f}% | {sh[3]:.1f}% |"
        )
    A("")
    A("---")
    A("")

    # ---- 3. Direction split ----------------------------------------
    A("## 3. Direction split (constrained and unconstrained)")
    A("")
    A("Unconstrained = the 688 de-duplicated opportunities with no portfolio rules. "
      "Constrained = the 249 trades that survived the rules.")
    A("")
    for title, dm, total_n in (
        ("Unconstrained", dir_unconstrained, len(distinct)),
        ("Constrained", dir_constrained, len(entered)),
    ):
        A(f"### {title}")
        A("")
        A("| Direction | Trades | Share | Win rate | Avg R | Median R | Profit factor | Total R | Max DD (R) | Flag |")
        A("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |")
        for direction in ("BUY", "SELL"):
            m = dm[direction]
            A(
                f"| {direction} | {m['n']:,} | {100.0 * m['n'] / total_n:.1f}% | "
                f"{pct_or_na(m['win_rate'])} | {fmt_signed(m['avg_r'])} | "
                f"{fmt_signed(m['median_r'])} | {fmt(m['profit_factor'], 2)} | "
                f"{fmt_signed(m['total_r'], 2)} | {fmt(m['max_dd_r'], 2)} | "
                f"{'n<30' if m['flagged_lt30'] else ''} |"
            )
        A("")
    A(f"The user-supplied unconstrained figures were BUY +0.316R (456 trades) vs SELL "
      f"-0.033R (232 trades). Measured here: BUY {n_buy_all} trades, "
      f"{fmt_signed(dir_unconstrained['BUY']['avg_r'])}; SELL {n_sell_all} trades, "
      f"{fmt_signed(dir_unconstrained['SELL']['avg_r'])}. "
      f"{'Confirmed.' if abs(dir_unconstrained['BUY']['avg_r'] - 0.316) < 0.001 and abs(dir_unconstrained['SELL']['avg_r'] + 0.033) < 0.001 and n_buy_all == 456 and n_sell_all == 232 else 'Corrected — see numbers above.'}")
    A("")
    A("---")
    A("")

    # ---- 4. Controls -----------------------------------------------
    A("## 4. Controls on the same constrained entries")
    A("")
    A("Controls reuse the exact same entry timestamps, stop distances, TP ladder "
      "(mirrored to the opposite side) and `$0.40` friction. Two random-direction "
      "controls are reported, both over seeds `1..1000`:")
    A("")
    A("1. **50/50 coin** — each entry independently assigned BUY/SELL.")
    A("2. **Ratio-preserving shuffle** — the period's BUY/SELL count ratio is kept "
      "exactly, only the assignment is shuffled (the pre-registered C2 control).")
    A("")
    A("Percentile rank = share of the 1,000 random means at or below the real mean R. "
      f"The pass rule is **percentile ≥ {PASS_PERCENTILE:.1f} on BOTH later half-years** "
      f"(validation = {VALIDATION_PERIOD}, test = {TEST_PERIOD}).")
    A("")
    A("| Period | n | Real mean R | Always-BUY | Always-SELL | Coin mean ± sd | Coin pct | Shuffle mean ± sd | Shuffle pct | Flag |")
    A("| :--- | ---: | ---: | ---: | ---: | :---: | ---: | :---: | ---: | :--- |")
    for p in ["ALL"] + all_periods:
        c = controls_all if p == "ALL" else controls_by_period[p]
        label = "**Whole window**" if p == "ALL" else p
        coin = c["coin"]
        ratio = c["ratio"]
        A(
            f"| {label} | {c['n']:,} | {fmt_signed(c['real_mean_r'])} | "
            f"{fmt_signed(c['always_buy_mean_r'])} | {fmt_signed(c['always_sell_mean_r'])} | "
            f"{fmt_signed(coin['mean'])} ± {fmt(coin['std'])} | {pct_or_na(coin['pct'])} | "
            f"{fmt_signed(ratio['mean'])} ± {fmt(ratio['std'])} | {pct_or_na(ratio['pct'])} | "
            f"{'n<30' if c['n'] < 30 else ''} |"
        )
    A("")
    A("### Half-year control detail (5%–95% bands and always-BUY/SELL win rates)")
    A("")
    A("| Period | n | Real mean R (WR) | Always-BUY mean R (WR) | Always-SELL mean R (WR) | Coin 5–95% | Shuffle 5–95% |")
    A("| :--- | ---: | :--- | :--- | :--- | :---: | :---: |")
    for p in all_periods:
        c = controls_by_period[p]
        coin = c["coin"]
        ratio = c["ratio"]
        A(
            f"| {p} | {c['n']:,} | {fmt_signed(c['real_mean_r'])} ({pct_or_na(c['real_wr'])}) | "
            f"{fmt_signed(c['always_buy_mean_r'])} ({pct_or_na(c['always_buy_wr'])}) | "
            f"{fmt_signed(c['always_sell_mean_r'])} ({pct_or_na(c['always_sell_wr'])}) | "
            f"[{fmt_signed(coin['p5'])}, {fmt_signed(coin['p95'])}] | "
            f"[{fmt_signed(ratio['p5'])}, {fmt_signed(ratio['p95'])}] |"
        )
    A("")

    v_c = controls_by_period[VALIDATION_PERIOD]
    t_c = controls_by_period[TEST_PERIOD]
    v_ratio = v_c["ratio"]["pct"]
    t_ratio = t_c["ratio"]["pct"]
    v_coin = v_c["coin"]["pct"]
    t_coin = t_c["coin"]["pct"]
    shuffle_pass = (v_ratio is not None and t_ratio is not None
                    and v_ratio >= PASS_PERCENTILE and t_ratio >= PASS_PERCENTILE)
    coin_pass = (v_coin is not None and t_coin is not None
                 and v_coin >= PASS_PERCENTILE and t_coin >= PASS_PERCENTILE)
    A("### Pass/fail verdict")
    A("")
    A("| Control | Validation " + VALIDATION_PERIOD + " | Test " + TEST_PERIOD + " | Both ≥ 97.5%? |")
    A("| :--- | ---: | ---: | :--- |")
    A(
        f"| Ratio-preserving shuffle (pre-registered) | {pct_or_na(v_ratio)} | "
        f"{pct_or_na(t_ratio)} | **{'PASS' if shuffle_pass else 'FAIL'}** |"
    )
    A(f"| 50/50 random direction | {pct_or_na(v_coin)} | {pct_or_na(t_coin)} | "
      f"**{'PASS' if coin_pass else 'FAIL'}** |")
    A("")
    A(
        f"**Verdict: {'PASS' if shuffle_pass else 'FAIL'}.** "
        f"Under the pre-registered ratio-preserving control the real mean R must beat "
        f"{PASS_PERCENTILE:.1f}% of random direction assignments in both "
        f"{VALIDATION_PERIOD} and {TEST_PERIOD}; it reaches "
        f"{pct_or_na(v_ratio)} and {pct_or_na(t_ratio)} respectively. "
        + ("The 50/50 coin control also passes." if coin_pass else
           "The 50/50 coin control also fails.")
    )
    A("")
    A("### Secondary: controls under the frozen walk-forward split labels")
    A("")
    A("The checkpoint `split` field follows `docs/SMC_FREEZE_V2.md` "
      "(calibration ends 2025-05-21 08:15 UTC, validation ends 2026-02-16 03:00 UTC). "
      "These windows are wider than the half-years and are shown only for continuity "
      "with earlier reports.")
    A("")
    A("| Split | n | Real mean R | Always-BUY | Always-SELL | Coin pct | Shuffle pct |")
    A("| :--- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for s in split_names:
        c = controls_by_split[s]
        A(
            f"| {s} | {c['n']:,} | {fmt_signed(c['real_mean_r'])} | "
            f"{fmt_signed(c['always_buy_mean_r'])} | {fmt_signed(c['always_sell_mean_r'])} | "
            f"{pct_or_na(c['coin']['pct'])} | {pct_or_na(c['ratio']['pct'])} |"
        )
    A("")
    A("---")
    A("")

    # ---- 5. Limits -------------------------------------------------
    A("## 5. Honest limits — what this backtest cannot show")
    A("")
    A("1. **Not clean out-of-sample.** 2025-01-01 onward overlaps data that was "
      "already observed while SMC was developed and tuned (see the parameter history "
      "and the contamination table in `docs/SMC_FREEZE_V2.md`). The only strictly "
      "unseen window begins after 2026-11-15 15:00 UTC. This report is a re-analysis "
      "of already-seen data, not a validation of the frozen strategy.")
    A("2. **Single instrument, single source.** One symbol (XAU/USD), one vendor "
      "(Twelve Data), 15m bars; HTFs are resampled, not independent data. Survivorship "
      "or vendor-specific bar construction cannot be ruled out.")
    A("3. **Small validation/test halves.** "
      f"{VALIDATION_PERIOD} carries {v_c['n']} constrained trades and {TEST_PERIOD} "
      f"carries {t_c['n']}. A 97.5% percentile threshold on ~50–70 trades has wide "
      "sampling error, and any half-year with n<30 is flagged descriptive-only above.")
    A("4. **Simulation, not execution.** Fills are conservative same-bar "
      "stop-first, 50% booked at TP1 with break-even stop, timeout mark-to-market at "
      "500 bars, and a constant $0.40 round-trip. Real slippage, gaps, weekend "
      "financing, broker minimum lot sizes and news voids are not modelled.")
    A("5. **Rule interpretation.** `MIN_ENTRY_SEPARATION` is implemented exactly as "
      "the frozen code (skip if *any* open same-direction entry is both <1h and "
      "<1 ATR away). The alternative reading — a global 1h escape after the last "
      "same-direction entry — was not silently substituted; it is noted here because "
      f"it changes the separation skip count ({skip_counts['all']['SEPARATION_RULE']} "
      "under the frozen reading).")
    A("6. **Concurrency dominates the funnel.** The gap between 688 unconstrained "
      "and the constrained set is almost entirely the 3-slot cap, not the strategy "
      "signal count. Holding times are long (median "
      f"{fmt(metrics_all['hold_bars_median'], 0)} market bars), so the portfolio is "
      "capacity-bound; results say as much about the cap as about the edge.")
    A("7. **Direction asymmetry is confounded with drift.** Always-BUY beats "
      "Always-SELL in 2025-H1 (+0.204 vs -0.248) and 2025-H2 (+0.770 vs -0.533), "
      "consistent with gold's upward drift, but the ordering reverses in 2026-H1 "
      "(-0.073 vs +0.011) and 2026-H2 (-0.148 vs +0.351). The real strategy trails "
      "Always-BUY in 2025-H2 and leads it in 2026-H2. The BUY/SELL split therefore "
      "describes this window's drift and regime, not a stable directional edge.")
    A("8. **No tuning was performed.** Nothing was optimised on this window: the "
      "funnel, metrics and controls are deterministic given the checkpoints, the "
      "read-only candles and seeds 1..1000.")
    A("")
    A("---")
    A("")
    A("Generated by `server/scripts/smc_portfolio_2025.py` "
      f"({n_files} checkpoint files, {len(seeds):,} seeds; run at "
      f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC).")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    elapsed = (datetime.now() - started).total_seconds()
    print()
    print("=" * 70)
    print("[+] REPORT COMPLETE")
    print("=" * 70)
    print(f"[*] Unconstrained           : {len(distinct):,} trades / {total_r:+.2f} R")
    print(f"[*] Constrained             : {len(entered):,} trades / {metrics_all['total_r']:+.2f} R")
    print(f"[*] Constrained avg R / PF  : {metrics_all['avg_r']:+.4f} R / {metrics_all['profit_factor']:.3f}")
    print(f"[*] Constrained max DD      : {metrics_all['max_dd_r']:.2f} R over {metrics_all['max_dd_days']:.1f} days")
    print(f"[*] Exposure max / mean     : {exposure_all['max']} / {exposure_all['mean']:.2f}")
    print(f"[*] Shuffle pct val/test    : {pct_or_na(v_ratio)} / {pct_or_na(t_ratio)} -> {'PASS' if shuffle_pass else 'FAIL'}")
    print(f"[*] Coin pct val/test       : {pct_or_na(v_coin)} / {pct_or_na(t_coin)} -> {'PASS' if coin_pass else 'FAIL'}")
    print(f"[*] Report                  : {report_path}")
    print(f"[*] Elapsed                 : {elapsed:,.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
