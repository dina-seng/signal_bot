"""Bar-by-bar CRT replay with zero lookahead through the production analysis path.

This script is a standalone CLI diagnostic. It is NOT imported by the test suite
and it never writes to the application database: the CRT strategy is constructed
with ``enable_dedup=False`` so neither the in-memory nor the database cooldown
path is taken, and the SQLite connection is opened read-only (``mode=ro``).

What it does
------------
1. Loads XAU/USD 15m candles from a SQLite database (Twelve Data rows only).
2. Applies the production market-calendar filter, then resamples 1h and 4h with
   the production ``resample_ohlc`` (incomplete buckets are omitted).
3. Walks the 15m series forward. At each closed 15m bar it builds the candle
   sets that were *knowable at that instant* using the timestamp rule
   (``bar.timestamp + timeframe_delta <= decision_time``) and feeds them through
   the production ``ConfluenceEngine._prepare_market_data`` +
   ``StrategyManager.run_all_strategies`` path.
4. Records, for every evaluated bar, whether a sweep candidate existed and which
   gate stopped it.
5. For every emitted (CONFIRMED_SETUP) signal, simulates the trade outcome
   forward with a configurable spread assumption, limit-zone fills and expiry.

No strategy threshold is modified. Defaults are the production defaults.

Usage
-----
    cd server
    python scripts/crt_replay.py --db-path ../backtest.db --months 3

    python scripts/crt_replay.py --help

Outputs
-------
- Markdown report to stdout and to ``reports/crt_replay/crt_replay_report.md``
- Per-signal CSV to ``reports/crt_replay/crt_replay_signals.csv``
"""

from __future__ import annotations

import argparse
import csv
import math
import sqlite3
import sys
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.schemas.candle import CandleCreate  # noqa: E402
from app.services.market_data.calendar import filter_open_market_candles  # noqa: E402
from app.services.market_data.resample import resample_ohlc  # noqa: E402
from app.services.signals.confluence_engine import ConfluenceEngine  # noqa: E402
from app.services.strategies.crt_strategy import CRTStrategy  # noqa: E402
from app.services.strategies.strategy_manager import StrategyManager  # noqa: E402

TF_15M = timedelta(minutes=15)
TF_1H = timedelta(hours=1)
TF_4H = timedelta(hours=4)

# Gates that fire before a liquidity sweep has been validated. A bar blocked by
# one of these is not a sweep candidate. MICRO_RANGE / EXCESSIVE_RANGE are range
# quality gates that run before sweep validation in CRTStrategy.analyze().
PRE_SWEEP_GATES = {
    "MISSING_HTF_CANDLES",
    "OFF_SESSION",
    "MISSING_TIMESTAMPS",
    "NO_SWEEP",
    "MICRO_RANGE",
    "EXCESSIVE_RANGE",
}

# Pipeline order used to print the rejection funnel (matches CRTStrategy.analyze()).
GATE_ORDER = [
    "MISSING_HTF_CANDLES",
    "OFF_SESSION",
    "MISSING_TIMESTAMPS",
    "NO_SWEEP",
    "TREND_CONFLICT",
    "MICRO_RANGE",
    "EXCESSIVE_RANGE",
    "MICRO_SWEEP",
    "EXCESSIVE_MANIPULATION",
    "SWEEP_EXTREME_BROKEN",
    "CONFIRMATION_PENDING",
    "MISSED_SETUP",
    "INVALID_RISK_GEOMETRY",
    "EXCESSIVE_RISK_DISTANCE",
    "INSUFFICIENT_RR",
    "PATH_BLOCKED",
    "SCORE_BELOW_THRESHOLD",
    "DUPLICATE_SUPPRESSED",
    "OTHER_WAIT",
]

CONFIRMED_STATE = "CONFIRMED_SETUP"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _parse_ts(raw: str) -> datetime:
    """Parse the timestamp formats present in the candle table into aware UTC."""
    s = str(raw).strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_15m_candles(
    db_path: Path,
    symbol: str,
    source: str,
    months: float,
) -> Tuple[List[CandleCreate], Dict[str, Any]]:
    """Load, de-duplicate and window XAU/USD 15m candles from SQLite (read-only)."""
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT timestamp, open, high, low, close, volume, source
            FROM candles
            WHERE symbol = ? AND timeframe = '15m' AND source = ?
            ORDER BY timestamp
            """,
            (symbol, source),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        raise SystemExit(f"No {symbol} 15m rows with source='{source}' in {db_path}")

    seen: set[datetime] = set()
    deduped: List[CandleCreate] = []
    duplicates = 0
    for r in rows:
        ts = _parse_ts(r["timestamp"])
        if ts in seen:
            duplicates += 1
            continue
        seen.add(ts)
        deduped.append(
            CandleCreate(
                symbol=symbol,
                timeframe="15m",
                timestamp=ts,
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r["volume"] or 0.0),
                source=r["source"],
            )
        )

    if not deduped:
        raise SystemExit("No usable candles after de-duplication.")

    raw_first, raw_last = deduped[0].timestamp, deduped[-1].timestamp
    window_end = raw_last
    window_start = window_end - timedelta(days=months * 30.4375)
    windowed = [c for c in deduped if c.timestamp >= window_start]

    before_calendar = len(windowed)
    open_market = filter_open_market_candles(windowed)

    meta = {
        "db_path": str(db_path),
        "raw_rows": len(rows),
        "duplicates_dropped": duplicates,
        "raw_first": raw_first,
        "raw_last": raw_last,
        "window_start": window_start,
        "window_end": window_end,
        "bars_in_window": before_calendar,
        "open_market_bars": len(open_market),
        "closed_market_dropped": before_calendar - len(open_market),
    }
    return open_market, meta


def build_timeframe_series(
    bars_15m: Sequence[CandleCreate],
) -> Tuple[List[CandleCreate], List[datetime], List[CandleCreate], List[datetime]]:
    """Resample 1h and 4h using the production resampler and precompute close times."""
    c1h = resample_ohlc(list(bars_15m), "1h", calendar_aware=True)
    c4h = resample_ohlc(list(bars_15m), "4h", calendar_aware=True)
    c1h_close = [c.timestamp + TF_1H for c in c1h]
    c4h_close = [c.timestamp + TF_4H for c in c4h]
    return c1h, c1h_close, c4h, c4h_close


# ---------------------------------------------------------------------------
# Signal record
# ---------------------------------------------------------------------------
@dataclass
class SignalRecord:
    signal_time: datetime
    direction: str
    tier: Optional[str]
    session: Optional[str]
    entry_mode: Optional[str]
    crt_entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_price: float
    rr_planned: Optional[float]
    score: float
    production_entry: Optional[float] = None
    filled: bool = False
    fill_time: Optional[datetime] = None
    exit_reason: str = ""
    exit_time: Optional[datetime] = None
    r_multiple: Optional[float] = None
    bars_held: int = 0
    spread_paid: float = 0.0
    notes: str = ""
    sweep_key: str = ""


def _empty_funnel() -> Dict[str, int]:
    return {k: 0 for k in GATE_ORDER}


@dataclass
class ReplayStats:
    """Bookkeeping counters so nothing is silently swallowed."""
    evaluated: int = 0
    warmup_skipped: int = 0
    insufficient_data: int = 0
    eval_errors: int = 0
    error_samples: List[str] = field(default_factory=list)
    confirmation_reasons: Dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Outcome simulation
# ---------------------------------------------------------------------------
def simulate_outcome(
    record: SignalRecord,
    bars: Sequence[CandleCreate],
    signal_index: int,
    spread: float,
    expiry_bars: int,
    max_hold_bars: int,
) -> None:
    """Simulate a limit-zone (or market) entry with partial TP1/TP2 exits.

    Rules (documented, not tuned):
    - ``limit_zone``: entry fills when price trades through ``crt_entry`` within
      ``expiry_bars`` 15m bars; if the stop is touched first the order is void.
    - ``market``: filled at the signal bar close.
    - Same-bar ambiguity always resolves SL-first (conservative).
    - 50% is booked at TP1 and the stop moves to break-even; 50% runs to TP2.
    - The spread is charged once per completed trade as a round-trip cost in
      price units, then converted to R using the unadjusted risk distance.
    """
    is_buy = record.direction == "BUY"
    entry = record.crt_entry
    sl = record.stop_loss
    tp1 = record.take_profit_1
    tp2 = record.take_profit_2
    risk = abs(entry - sl)

    if risk <= 0:
        record.exit_reason = "INVALID_RISK"
        record.r_multiple = 0.0
        return

    n = len(bars)
    fill_idx: Optional[int] = None

    if record.entry_mode == "limit_zone":
        last = min(n, signal_index + 1 + expiry_bars)
        for k in range(signal_index + 1, last):
            bar = bars[k]
            # Stop invalidation before the limit is touched voids the order.
            if is_buy and bar.low <= sl:
                record.exit_reason = "NO_FILL_STOPPED_OUT"
                return
            if (not is_buy) and bar.high >= sl:
                record.exit_reason = "NO_FILL_STOPPED_OUT"
                return
            touched = bar.low <= entry if is_buy else bar.high >= entry
            if touched:
                fill_idx = k
                break
        if fill_idx is None:
            record.exit_reason = "NO_FILL_EXPIRED"
            return
    else:
        fill_idx = signal_index

    record.filled = True
    record.fill_time = bars[fill_idx].timestamp

    remaining = 1.0
    booked_price_pnl = 0.0  # weighted, per 1 unit of position, in price terms
    stop = sl
    tp1_done = False
    exit_reason = ""
    exit_time: Optional[datetime] = None
    exit_idx = fill_idx

    hard_end = min(n, fill_idx + max_hold_bars)
    for k in range(fill_idx, hard_end):
        bar = bars[k]
        exit_idx = k

        # 1. Stop loss first (conservative same-bar resolution).
        hit_stop = bar.low <= stop if is_buy else bar.high >= stop
        if hit_stop:
            pnl = (stop - entry) if is_buy else (entry - stop)
            booked_price_pnl += remaining * pnl
            remaining = 0.0
            exit_reason = "TP1_BE_STOP" if tp1_done else "STOP_LOSS"
            exit_time = bar.timestamp
            break

        # 2. TP1 — book half and move the stop to break-even.
        if not tp1_done:
            hit_tp1 = bar.high >= tp1 if is_buy else bar.low <= tp1
            if hit_tp1:
                size = remaining * 0.5
                pnl = (tp1 - entry) if is_buy else (entry - tp1)
                booked_price_pnl += size * pnl
                remaining -= size
                tp1_done = True
                stop = entry

        # 3. TP2 — close the runner.
        if tp1_done and remaining > 0:
            hit_tp2 = bar.high >= tp2 if is_buy else bar.low <= tp2
            if hit_tp2:
                pnl = (tp2 - entry) if is_buy else (entry - tp2)
                booked_price_pnl += remaining * pnl
                remaining = 0.0
                exit_reason = "TP2"
                exit_time = bar.timestamp
                break

    if remaining > 0:
        final_close = bars[exit_idx].close
        pnl = (final_close - entry) if is_buy else (entry - final_close)
        booked_price_pnl += remaining * pnl
        if not exit_reason:
            exit_reason = "TIMEOUT_MARK_TO_MARKET"
            exit_time = bars[exit_idx].timestamp

    net_price = booked_price_pnl - spread
    record.spread_paid = spread
    record.r_multiple = round(net_price / risk, 4)
    record.exit_reason = exit_reason
    record.exit_time = exit_time
    record.bars_held = (exit_idx - fill_idx) + 1


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
def replay(
    bars: Sequence[CandleCreate],
    c1h: Sequence[CandleCreate],
    c1h_close: Sequence[datetime],
    c4h: Sequence[CandleCreate],
    c4h_close: Sequence[datetime],
    symbol: str,
    spread: float,
    expiry_bars: int,
    cooldown_seconds: float,
    max_hold_bars: int,
    warmup_bars: int,
) -> Tuple[Dict[str, int], List[SignalRecord], int]:
    """Walk the 15m series and evaluate CRT at every closed bar."""
    crt = CRTStrategy(enable_dedup=False)  # no in-memory or DB cooldown side effects
    engine = ConfluenceEngine(strategy_manager=StrategyManager([crt]))

    funnel = _empty_funnel()
    signals: List[SignalRecord] = []
    last_emit: Dict[str, datetime] = {}
    stats = ReplayStats()

    bar_close = [b.timestamp + TF_15M for b in bars]
    n = len(bars)

    for i, bar in enumerate(bars):
        decision_time = bar_close[i]

        if i < warmup_bars:
            stats.warmup_skipped += 1
            continue

        # Closed-candle sets by timestamp rule, never by raw index semantics.
        n15 = bisect_right(bar_close, decision_time)
        n1h = bisect_right(c1h_close, decision_time)
        n4h = bisect_right(c4h_close, decision_time)

        # Window sizes mirror SignalGenerator.scan_unified exactly:
        # 200 x 15m, 200 x 1h, 100 x 4h.
        c15 = list(bars[max(0, n15 - 200):n15])
        primary = list(c1h[max(0, n1h - 200):n1h])
        ht_c4h = list(c4h[max(0, n4h - 100):n4h])

        if len(primary) < 20 or len(c15) < 50:
            stats.insufficient_data += 1
            continue

        stats.evaluated += 1

        try:
            structure, indicators, mtf = engine._prepare_market_data(
                symbol=symbol,
                timeframe="1h",
                c_prim=primary,
                c_4h=ht_c4h,
                c_15m=c15,
            )
            results = engine.strategy_manager.run_all_strategies(
                symbol=symbol,
                timeframe="1h",
                candles=primary,
                indicators=indicators,
                structure=structure,
                mtf=mtf,
                candles_15m=c15,
            )
        except Exception as exc:  # pragma: no cover - diagnostic resilience
            stats.eval_errors += 1
            if len(stats.error_samples) < 5:
                stats.error_samples.append(f"{decision_time.isoformat()}: {exc}")
            continue

        result = results[0] if results else None
        if result is None:
            funnel["OTHER_WAIT"] += 1
            continue

        meta = result.metadata or {}
        state = meta.get("setup_state")
        gate = meta.get("rejection_gate")
        crt_analysis = meta.get("crt_analysis") or {}
        is_breached = bool(crt_analysis.get("is_breached"))

        if state == CONFIRMED_STATE and result.direction.value in ("BUY", "SELL"):
            sweep_key = str(meta.get("sweep_event_key") or "")
            prev = last_emit.get(sweep_key)
            if prev is not None and (decision_time - prev).total_seconds() < cooldown_seconds:
                funnel["DUPLICATE_SUPPRESSED"] += 1
                continue
            last_emit[sweep_key] = decision_time

            entry = float(meta.get("entry_price") or 0.0)
            sl = float(meta.get("stop_loss") or 0.0)
            tp1 = float(meta.get("take_profit_1") or 0.0)
            tp2 = float(meta.get("take_profit_2") or 0.0)
            if entry <= 0 or sl <= 0 or tp1 <= 0 or tp2 <= 0:
                funnel["OTHER_WAIT"] += 1
                continue

            production_entry = None
            try:
                sig_resp = engine._build_signal_response(
                    result=result,
                    symbol=symbol,
                    timeframe="1h",
                    indicator_analysis=indicators,
                    structure_analysis=structure,
                    account_balance=10000.0,
                    risk_percent=0.5,
                    htf_trend=None,
                )
                production_entry = float(sig_resp.entry_price)
            except Exception:
                production_entry = None

            rec = SignalRecord(
                signal_time=decision_time,
                direction=result.direction.value,
                tier=meta.get("quality_tier"),
                session=meta.get("session_name"),
                entry_mode=meta.get("entry_mode"),
                crt_entry=entry,
                stop_loss=sl,
                take_profit_1=tp1,
                take_profit_2=tp2,
                risk_price=abs(entry - sl),
                rr_planned=meta.get("risk_reward_tp1"),
                score=float(result.score or 0.0),
                production_entry=production_entry,
                sweep_key=sweep_key,
            )
            simulate_outcome(
                rec,
                bars=bars,
                signal_index=i,
                spread=spread,
                expiry_bars=expiry_bars,
                max_hold_bars=max_hold_bars,
            )
            signals.append(rec)
            continue

        # Not emitted — classify the rejecting gate.
        if gate:
            funnel[gate] = funnel.get(gate, 0) + 1
            if gate == "CONFIRMATION_PENDING":
                detail = meta.get("confirmation_detail")
                if not detail:
                    # This branch is `not analysis.is_confirmed`: the analyzer has
                    # not yet seen a 15m close back inside the benchmark range.
                    detail = "Analyzer: no close back inside range yet"
                detail = str(detail)
                stats.confirmation_reasons[detail] = stats.confirmation_reasons.get(detail, 0) + 1
        elif not is_breached:
            funnel["NO_SWEEP"] += 1
        elif meta.get("trend_conflict"):
            funnel["TREND_CONFLICT"] += 1
        elif state == "POTENTIAL_SETUP" and not meta.get("gatekeeper_passed", False):
            funnel["SCORE_BELOW_THRESHOLD"] += 1
        else:
            funnel["OTHER_WAIT"] += 1

    return funnel, signals, stats


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
@dataclass
class Metrics:
    n_signals: int = 0
    n_filled: int = 0
    n_no_fill: int = 0
    win_rate: Optional[float] = None
    avg_r: Optional[float] = None
    expectancy: Optional[float] = None
    profit_factor: Optional[float] = None
    max_drawdown_r: Optional[float] = None
    total_r: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    sample_warning: str = ""


def _bootstrap_ci(values: Sequence[float], resamples: int = 2000, seed: int = 12345) -> Tuple[float, float]:
    """Deterministic bootstrap 95% CI for the mean R (mirrors project convention)."""
    import random

    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(values)
    means: List[float] = []
    for _ in range(resamples):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int(0.025 * resamples)]
    hi = means[int(0.975 * resamples) - 1]
    return (lo, hi)


def compute_metrics(signals: Sequence[SignalRecord]) -> Metrics:
    filled = [s for s in signals if s.filled and s.r_multiple is not None]
    m = Metrics(
        n_signals=len(signals),
        n_filled=len(filled),
        n_no_fill=len(signals) - len(filled),
    )
    if not filled:
        m.sample_warning = "No filled trades — sample too small for any inference."
        return m

    rs = [float(s.r_multiple) for s in filled]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]

    m.win_rate = len(wins) / len(rs) * 100.0
    m.avg_r = sum(rs) / len(rs)
    m.expectancy = m.avg_r
    gross_gain = sum(wins)
    gross_loss = abs(sum(losses))
    m.profit_factor = (gross_gain / gross_loss) if gross_loss > 0 else (math.inf if gross_gain > 0 else 0.0)
    m.total_r = sum(rs)

    ordered = sorted(filled, key=lambda s: s.signal_time)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for s in ordered:
        equity += float(s.r_multiple)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    m.max_drawdown_r = max_dd

    lo, hi = _bootstrap_ci(rs)
    m.ci_lower, m.ci_upper = lo, hi

    if len(rs) < 30:
        m.sample_warning = (
            f"n={len(rs)} filled trades (<30): sample is TOO SMALL for any conclusion. "
            "Treat every metric below as descriptive only."
        )
    return m


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        if math.isinf(value):
            return "inf"
        return f"{value:.{digits}f}"
    return str(value)


def build_report(
    meta: Dict[str, Any],
    funnel: Dict[str, int],
    signals: Sequence[SignalRecord],
    metrics: Metrics,
    args: argparse.Namespace,
    stats: ReplayStats,
) -> str:
    candidates = sum(
        v for k, v in funnel.items() if k not in PRE_SWEEP_GATES and k not in ("NO_SWEEP", "OTHER_WAIT")
    ) + len(signals)

    lines: List[str] = []
    lines.append("# CRT Replay — No-Lookahead Diagnostic")
    lines.append("")
    lines.append("Production path: `resample_ohlc` → `ConfluenceEngine._prepare_market_data` → "
                 "`StrategyManager.run_all_strategies` → `CRTStrategy` (dedup disabled).")
    lines.append("")
    lines.append("## 1. Data")
    lines.append("")
    lines.append("| Item | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| Database | `{meta['db_path']}` |")
    lines.append(f"| Symbol / timeframe / source | XAU/USD · 15m · twelvedata |")
    lines.append(f"| Raw rows read | {meta['raw_rows']:,} |")
    lines.append(f"| Duplicate timestamps dropped | {meta['duplicates_dropped']:,} |")
    lines.append(f"| Full DB range | {meta['raw_first']:%Y-%m-%d %H:%M} → {meta['raw_last']:%Y-%m-%d %H:%M} UTC |")
    lines.append(f"| Replay window ({args.months:g} months) | {meta['window_start']:%Y-%m-%d %H:%M} → {meta['window_end']:%Y-%m-%d %H:%M} UTC |")
    lines.append(f"| Bars in window | {meta['bars_in_window']:,} |")
    lines.append(f"| Closed-market bars dropped | {meta['closed_market_dropped']:,} |")
    lines.append(f"| Open-market bars replayed | {meta['open_market_bars']:,} |")
    lines.append("")
    lines.append("## 2. Rejection funnel")
    lines.append("")
    lines.append("Counts are **bar-evaluations**, not distinct setups: a single sweep that stays open for "
                 "many 15m bars is counted on every bar it survives.")
    lines.append("")
    lines.append(f"- Bars in window: {meta['open_market_bars']:,}")
    lines.append(f"- Warm-up bars skipped: {stats.warmup_skipped:,}")
    lines.append(f"- Insufficient data (need ≥20 1h / ≥50 15m bars): {stats.insufficient_data:,}")
    lines.append(f"- Evaluation errors: {stats.eval_errors:,}")
    lines.append(f"- Bars actually evaluated: **{stats.evaluated:,}**")
    lines.append(f"- Sweep candidates: **{candidates:,}** · emitted signals: **{len(signals):,}**")
    lines.append("")
    lines.append("| Stage | Gate | Bars |")
    lines.append("| :--- | :--- | ---: |")
    for gate in GATE_ORDER:
        lines.append(f"| {'pre-sweep' if gate in PRE_SWEEP_GATES else 'post-sweep'} | `{gate}` | {funnel.get(gate, 0):,} |")
    for gate, count in funnel.items():
        if gate not in GATE_ORDER and count:
            lines.append(f"| post-sweep | `{gate}` | {count:,} |")
    lines.append(f"| **emitted** | `CONFIRMED_SETUP` | **{len(signals):,}** |")
    lines.append("")
    if stats.error_samples:
        lines.append("Evaluation error samples:")
        lines.append("")
        for sample in stats.error_samples:
            lines.append(f"- `{sample}`")
        lines.append("")
    if stats.confirmation_reasons:
        lines.append("### Confirmation-pending sub-reasons")
        lines.append("")
        lines.append("`CONFIRMATION_PENDING` is the dominant post-sweep gate. Its internal reason breakdown:")
        lines.append("")
        lines.append("| Sub-reason | Bars |")
        lines.append("| :--- | ---: |")
        for reason, count in sorted(stats.confirmation_reasons.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {reason} | {count:,} |")
        lines.append("")
    lines.append("## 3. Signals by quality tier and session")
    lines.append("")
    by_tier: Dict[str, int] = {}
    by_session: Dict[str, int] = {}
    for s in signals:
        by_tier[str(s.tier or "unknown")] = by_tier.get(str(s.tier or "unknown"), 0) + 1
        by_session[str(s.session or "unknown")] = by_session.get(str(s.session or "unknown"), 0) + 1

    lines.append("| Tier | Signals |")
    lines.append("| :--- | ---: |")
    for k in sorted(by_tier):
        lines.append(f"| {k} | {by_tier[k]} |")
    lines.append("")
    lines.append("| Session | Signals |")
    lines.append("| :--- | ---: |")
    for k in sorted(by_session):
        lines.append(f"| {k} | {by_session[k]} |")
    lines.append("")
    lines.append("## 4. Outcome simulation")
    lines.append("")
    lines.append(f"Assumptions: spread **${args.spread:.2f}** round-trip, limit expiry "
                 f"**{args.expiry_bars}** bars, max hold **{args.max_hold_bars}** bars, "
                 "50% at TP1 → stop to break-even → 50% at TP2, same-bar SL-first.")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| :--- | ---: |")
    lines.append(f"| Signals emitted | {metrics.n_signals:,} |")
    lines.append(f"| Filled | {metrics.n_filled:,} |")
    lines.append(f"| No fill (expired / stopped before fill) | {metrics.n_no_fill:,} |")
    lines.append(f"| Win rate | {_fmt(metrics.win_rate)}% |")
    lines.append(f"| Average R | {_fmt(metrics.avg_r, 4)} |")
    lines.append(f"| Expectancy (R per trade) | {_fmt(metrics.expectancy, 4)} |")
    lines.append(f"| Profit factor | {_fmt(metrics.profit_factor)} |")
    lines.append(f"| Total R | {_fmt(metrics.total_r, 2)} |")
    lines.append(f"| Max drawdown (R) | {_fmt(metrics.max_drawdown_r, 2)} |")
    lines.append(f"| Bootstrap 95% CI of mean R | [{_fmt(metrics.ci_lower, 4)}, {_fmt(metrics.ci_upper, 4)}] |")
    lines.append("")
    if metrics.sample_warning:
        lines.append(f"> **{metrics.sample_warning}**")
        lines.append("")

    # Entry-price wiring observation
    section = 5
    deltas = [
        (s.production_entry - s.crt_entry)
        for s in signals
        if s.production_entry is not None
    ]
    if deltas:
        lines.append(f"## {section}. Entry-price wiring check")
        lines.append("")
        lines.append("`SignalResponse.entry_price` (built by `ConfluenceEngine._build_signal_response`) "
                     "versus the CRT limit entry used for the simulation:")
        lines.append("")
        lines.append(f"- Signals compared: {len(deltas)}")
        lines.append(f"- Mean |delta|: ${sum(abs(d) for d in deltas) / len(deltas):.4f}")
        lines.append(f"- Max |delta|: ${max(abs(d) for d in deltas):.4f}")
        lines.append("")
        section += 1

    # Exit reason breakdown
    exits: Dict[str, int] = {}
    for s in signals:
        exits[s.exit_reason or "UNRESOLVED"] = exits.get(s.exit_reason or "UNRESOLVED", 0) + 1
    lines.append(f"## {section}. Exit reasons")
    lines.append("")
    lines.append("| Exit reason | Count |")
    lines.append("| :--- | ---: |")
    for k in sorted(exits):
        lines.append(f"| {k} | {exits[k]} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("No strategy threshold was modified; all CRT parameters are production defaults.")
    return "\n".join(lines)


def write_csv(signals: Sequence[SignalRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "signal_time_utc", "direction", "quality_tier", "session", "entry_mode",
            "crt_entry", "production_entry", "entry_delta", "stop_loss", "take_profit_1",
            "take_profit_2", "risk_price", "rr_planned", "score",
            "filled", "fill_time_utc", "exit_time_utc", "exit_reason",
            "r_multiple", "bars_held", "spread_paid", "sweep_key",
        ])
        for s in signals:
            delta = "" if s.production_entry is None else round(s.production_entry - s.crt_entry, 5)
            w.writerow([
                s.signal_time.isoformat(),
                s.direction,
                s.tier or "",
                s.session or "",
                s.entry_mode or "",
                s.crt_entry,
                "" if s.production_entry is None else s.production_entry,
                delta,
                s.stop_loss,
                s.take_profit_1,
                s.take_profit_2,
                round(s.risk_price, 5),
                s.rr_planned if s.rr_planned is not None else "",
                s.score,
                s.filled,
                s.fill_time.isoformat() if s.fill_time else "",
                s.exit_time.isoformat() if s.exit_time else "",
                s.exit_reason,
                "" if s.r_multiple is None else s.r_multiple,
                s.bars_held,
                s.spread_paid,
                s.sweep_key,
            ])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Replay CRT bar-by-bar with zero lookahead and simulate outcomes.",
    )
    p.add_argument("--db-path", default=str(REPO_ROOT / "backtest.db"),
                   help="SQLite database containing the candles table (default: <repo>/backtest.db)")
    p.add_argument("--symbol", default="XAU/USD")
    p.add_argument("--source", default="twelvedata", help="Only this candle source is used (default: twelvedata)")
    p.add_argument("--months", type=float, default=3.0, help="Replay window in months (max 3 by policy)")
    p.add_argument("--spread", type=float, default=0.30, help="Round-trip spread in USD (default: 0.30)")
    p.add_argument("--expiry-bars", type=int, default=8, help="Limit-zone expiry in 15m bars (CRT default: 8)")
    p.add_argument("--cooldown-seconds", type=float, default=7200.0, help="Repeat-signal suppression window (CRT default: 7200)")
    p.add_argument("--max-hold-bars", type=int, default=500, help="Maximum bars to hold an open trade")
    p.add_argument("--warmup-bars", type=int, default=100, help="15m bars skipped before the first decision")
    p.add_argument("--out-dir", default=str(REPO_ROOT / "reports" / "crt_replay"),
                   help="Directory for the markdown report and CSV")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if args.months > 3.0:
        raise SystemExit("--months is capped at 3 by policy for this diagnostic.")

    db_path = Path(args.db_path)
    print(f"[*] Loading {args.symbol} 15m candles from {db_path} (source={args.source}) ...")
    bars_15m, meta = load_15m_candles(db_path, args.symbol, args.source, args.months)
    print(f"[*] {len(bars_15m):,} open-market 15m bars in the replay window")

    c1h, c1h_close, c4h, c4h_close = build_timeframe_series(bars_15m)
    print(f"[*] Resampled 1h={len(c1h):,} (complete buckets) and 4h={len(c4h):,}")

    print("[*] Replaying bar by bar (this runs the production analysis path) ...")
    funnel, signals, stats = replay(
        bars=bars_15m,
        c1h=c1h,
        c1h_close=c1h_close,
        c4h=c4h,
        c4h_close=c4h_close,
        symbol=args.symbol,
        spread=args.spread,
        expiry_bars=args.expiry_bars,
        cooldown_seconds=args.cooldown_seconds,
        max_hold_bars=args.max_hold_bars,
        warmup_bars=args.warmup_bars,
    )

    metrics = compute_metrics(signals)
    report = build_report(meta, funnel, signals, metrics, args, stats)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "crt_replay_report.md"
    csv_path = out_dir / "crt_replay_signals.csv"
    md_path.write_text(report + "\n", encoding="utf-8")
    write_csv(signals, csv_path)

    print()
    print(report)
    print()
    print(f"[*] Markdown report: {md_path}")
    print(f"[*] Signal CSV     : {csv_path}")

    if metrics.n_filled < 30:
        print()
        print(f"[!] SAMPLE TOO SMALL: {metrics.n_filled} filled trades (<30). "
              "No edge claim can be made from this replay.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
