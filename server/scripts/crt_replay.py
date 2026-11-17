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
import json
import math
import sqlite3
import sys
from bisect import bisect_right
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.schemas.candle import CandleCreate  # noqa: E402
from app.schemas.liquidity import LiquidityEventType  # noqa: E402
from app.schemas.signal import SignalDirection  # noqa: E402
from app.schemas.structure import CRTAnalysis  # noqa: E402
from app.services.market_data.calendar import filter_open_market_candles  # noqa: E402
from app.services.market_data.resample import resample_ohlc  # noqa: E402
from app.services.signals.confluence_engine import ConfluenceEngine  # noqa: E402
from app.services.strategies.crt.confirmation import verify_ltf_confirmation  # noqa: E402
from app.services.strategies.crt.entry import calculate_retracement_entry  # noqa: E402
from app.services.strategies.crt.targets import calculate_crt_targets  # noqa: E402
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
    # --- Full-range, chunked, resumable measurement mode (Part 3) ---
    p.add_argument("--full-range", action="store_true",
                   help="Process the entire DB range in monthly chunks (ignores --months cap)")
    p.add_argument("--checkpoint-dir", default=None,
                   help="Directory for per-month resumable checkpoints (default: <out-dir>/checkpoints)")
    p.add_argument("--no-resume", action="store_true",
                   help="Ignore existing monthly checkpoints and recompute every month")
    p.add_argument("--max-chunks", type=int, default=None,
                   help="Debug only: stop after this many monthly chunks")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if args.full_range:
        return main_full_range(args)

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


# ---------------------------------------------------------------------------
# Part 3 — Full-range, monthly-chunked, resumable measurement.
#
# Everything below is additive: it reuses the production strategy path and the
# existing simulate_outcome() logic. No strategy threshold is modified.
#
# Design notes (documented, not tuned):
# - The whole 15m series is read once (read-only SQLite) and resampled once;
#   evaluation then walks the series in calendar-month chunks. Each chunk keeps
#   the full lookback history available (no artificial window truncation), so
#   chunk boundaries do not change the production inputs.
# - Each finished month is checkpointed to JSON. Re-running skips finished
#   months unless --no-resume is given.
# - "Rejected candidate" = an evaluated bar whose CRTAnalysis has is_breached
#   True but which was not emitted. For each such bar the counterfactual uses
#   the SAME sub-functions the strategy uses (verify_ltf_confirmation,
#   calculate_retracement_entry, calculate_crt_targets) and the SAME
#   simulate_outcome() fill/TP1/TP2 logic, with the gate simply ignored.
# - Direction on rejected bars is derived from analysis.positive_direction
#   (the strategy returns WAIT); sweep_key mirrors crt_strategy.py:1003.
# ---------------------------------------------------------------------------

CALIBRATION = "calibration"   # earliest 60% — observation only
VALIDATION = "validation"     # next 20%
TEST = "test"                 # last 20% — untouched
SPLITS = (CALIBRATION, VALIDATION, TEST)


@dataclass
class BarRecord:
    decision_time: str
    month: str
    split: str
    index: int
    gate: str
    direction: str
    sweep_key: str
    is_breached: bool
    accepted: bool
    confirmation_detail: str = ""
    accepted_trade: Optional[Dict[str, Any]] = None
    counterfactual_trade: Optional[Dict[str, Any]] = None
    cf_error: str = ""


def _signal_to_dict(s: SignalRecord) -> Dict[str, Any]:
    return {
        "signal_time": s.signal_time.isoformat(),
        "direction": s.direction,
        "entry_mode": s.entry_mode,
        "crt_entry": s.crt_entry,
        "stop_loss": s.stop_loss,
        "take_profit_1": s.take_profit_1,
        "take_profit_2": s.take_profit_2,
        "risk_price": s.risk_price,
        "rr_planned": s.rr_planned,
        "filled": s.filled,
        "fill_time": s.fill_time.isoformat() if s.fill_time else None,
        "exit_reason": s.exit_reason,
        "exit_time": s.exit_time.isoformat() if s.exit_time else None,
        "r_multiple": s.r_multiple,
        "bars_held": s.bars_held,
        "spread_paid": s.spread_paid,
        "sweep_key": s.sweep_key,
    }


def load_full_15m_candles(
    db_path: Path, symbol: str, source: str
) -> Tuple[List[CandleCreate], Dict[str, Any]]:
    """Read the entire deduplicated, open-market 15m series (read-only)."""
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT timestamp, open, high, low, close, volume, source
               FROM candles
               WHERE symbol = ? AND timeframe = '15m' AND source = ?
               ORDER BY timestamp""",
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
                symbol=symbol, timeframe="15m", timestamp=ts,
                open=float(r["open"]), high=float(r["high"]),
                low=float(r["low"]), close=float(r["close"]),
                volume=float(r["volume"] or 0.0), source=r["source"],
            )
        )
    open_market = filter_open_market_candles(deduped)
    meta = {
        "db_path": str(db_path),
        "raw_rows": len(rows),
        "duplicates_dropped": duplicates,
        "raw_first": deduped[0].timestamp,
        "raw_last": deduped[-1].timestamp,
        "bars_in_window": len(deduped),
        "open_market_bars": len(open_market),
        "closed_market_dropped": len(deduped) - len(open_market),
    }
    return open_market, meta


def walk_forward_bounds(bars: Sequence[CandleCreate]) -> Tuple[datetime, datetime]:
    """Earliest 60% / next 20% / last 20% by elapsed time across the series."""
    start, end = bars[0].timestamp, bars[-1].timestamp
    span = end - start
    return start + span * 0.60, start + span * 0.80


def split_of(ts: datetime, bounds: Tuple[datetime, datetime]) -> str:
    b1, b2 = bounds
    if ts < b1:
        return CALIBRATION
    if ts < b2:
        return VALIDATION
    return TEST


def month_keys(bars: Sequence[CandleCreate]) -> List[Tuple[str, datetime, datetime]]:
    keys = sorted({(b.timestamp.year, b.timestamp.month) for b in bars})
    out: List[Tuple[str, datetime, datetime]] = []
    for (y, m) in keys:
        start = datetime(y, m, 1, tzinfo=timezone.utc)
        end = datetime(y + (m == 12), (m % 12) + 1, 1, tzinfo=timezone.utc)
        out.append((f"{y:04d}-{m:02d}", start, end))
    return out


def _direction_of(meta: Dict[str, Any]) -> str:
    ca = meta.get("crt_analysis") or {}
    return "BUY" if bool(ca.get("positive_direction")) else "SELL"


def _sweep_key_of(meta: Dict[str, Any], symbol: str, timeframe: str = "1h") -> str:
    ca = meta.get("crt_analysis") or {}
    direction = "BUY" if ca.get("positive_direction") else "SELL"
    rot = str(ca.get("range_open_timestamp") or "0")
    bt = str(ca.get("breach_timestamp") or "0")
    return f"{symbol}_{timeframe}_{direction}_{rot}_{bt}"


def _classify_gate(result: Any, meta: Dict[str, Any]) -> Tuple[str, bool, bool]:
    ca = meta.get("crt_analysis") or {}
    is_breached = bool(ca.get("is_breached"))
    state = meta.get("setup_state")
    if state == CONFIRMED_STATE and result is not None and result.direction.value in ("BUY", "SELL"):
        return CONFIRMED_STATE, is_breached, True
    gate = meta.get("rejection_gate")
    if gate:
        return str(gate), is_breached, False
    if not is_breached:
        return "NO_SWEEP", is_breached, False
    if meta.get("trend_conflict"):
        return "TREND_CONFLICT", is_breached, False
    if state == "POTENTIAL_SETUP" and not meta.get("gatekeeper_passed", False):
        return "SCORE_BELOW_THRESHOLD", is_breached, False
    return "OTHER_WAIT", is_breached, False


def _build_trade_from_meta(
    meta: Dict[str, Any], direction: str, decision_time: datetime,
    sweep_key: str, i: int, bars: Sequence[CandleCreate], spread: float,
    expiry_bars: int, max_hold_bars: int,
) -> Optional[SignalRecord]:
    entry = float(meta.get("entry_price") or 0.0)
    sl = float(meta.get("stop_loss") or 0.0)
    tp1 = float(meta.get("take_profit_1") or 0.0)
    tp2 = float(meta.get("take_profit_2") or 0.0)
    if entry <= 0 or sl <= 0 or tp1 <= 0 or tp2 <= 0:
        return None
    rec = SignalRecord(
        signal_time=decision_time, direction=direction, tier=meta.get("quality_tier"),
        session=meta.get("session_name"), entry_mode=meta.get("entry_mode"),
        crt_entry=entry, stop_loss=sl, take_profit_1=tp1, take_profit_2=tp2,
        risk_price=abs(entry - sl), rr_planned=meta.get("risk_reward_tp1"),
        score=float(meta.get("score") or 0.0), sweep_key=sweep_key,
    )
    simulate_outcome(rec, bars=bars, signal_index=i, spread=spread,
                     expiry_bars=expiry_bars, max_hold_bars=max_hold_bars)
    return rec


def build_counterfactual(
    meta: Dict[str, Any], current_price: float, effective_atr: float,
    c15: Sequence[CandleCreate], structure: Any, indicators: Any, crt: CRTStrategy,
    decision_time: datetime, i: int, bars: Sequence[CandleCreate], spread: float,
    expiry_bars: int, max_hold_bars: int, direction: str, sweep_key: str,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Recompute the CRT trade a rejected sweep WOULD have produced, then simulate it."""
    ca = meta.get("crt_analysis")
    if not ca:
        return None, "NO_ANALYSIS"
    try:
        analysis = CRTAnalysis(**ca)
    except Exception as exc:
        return None, f"ANALYSIS_PARSE:{type(exc).__name__}"
    if analysis.breach_point is None:
        return None, "NO_BREACH_POINT"

    sd = SignalDirection.BUY if direction == "BUY" else SignalDirection.SELL
    try:
        conf = verify_ltf_confirmation(
            direction=sd, range_high=analysis.range_high, range_low=analysis.range_low,
            candles_15m=c15, breach_point=analysis.breach_point,
            manip_candle_index=analysis.manipulation_candle_index,
            breach_timestamp=analysis.breach_timestamp, atr=effective_atr,
            min_disp_atr_mult=crt.min_disp_atr_mult, structure=structure,
        )
        entry_res = calculate_retracement_entry(
            direction=sd, sweep_extreme=analysis.breach_point,
            displacement_extreme=conf.displacement_extreme, candles_15m=c15,
            current_price=current_price,
            target_tp1=(analysis.range_high + analysis.range_low) / 2.0,
            atr=effective_atr, spread=crt.spread, expiry_bars=crt.entry_expiry_bars,
        )
        eff_entry = entry_res.ideal_entry if entry_res.entry_mode == "limit_zone" else current_price

        sl_buffer = max(crt.spread, 0.10 * effective_atr) if (crt.spread > 0 or effective_atr > 0) else 0.0
        raw_sl = entry_res.stop_loss
        for pool in (getattr(structure, "liquidity_pools", None) or []):
            plevel = float(getattr(pool, "price_level", 0.0) or 0.0)
            ptype = str(getattr(pool, "pool_type", ""))
            near = abs(plevel - analysis.breach_point) <= 1.0 * (effective_atr or 5.0)
            if direction == "BUY" and "EQUAL_LOW" in ptype and plevel < current_price and near:
                raw_sl = min(raw_sl, plevel - sl_buffer)
            if direction == "SELL" and "EQUAL_HIGH" in ptype and plevel > current_price and near:
                raw_sl = max(raw_sl, plevel + sl_buffer)
        stop_loss = round(raw_sl, 5)
        if (direction == "BUY" and stop_loss >= eff_entry) or (direction == "SELL" and stop_loss <= eff_entry):
            return None, "INVALID_RISK_GEOMETRY"
        risk_distance = abs(eff_entry - stop_loss)
        if effective_atr > 0 and risk_distance > crt.max_risk_atr_mult * effective_atr:
            return None, "EXCESSIVE_RISK_DISTANCE"

        plan = calculate_crt_targets(
            direction=sd, entry_price=eff_entry, stop_loss=stop_loss,
            range_high=analysis.range_high, range_low=analysis.range_low,
            atr=effective_atr, min_rr=crt.min_rr_tp1,
            structure=structure, indicators=indicators,
        )
        if not plan.is_valid:
            return None, str(plan.rejection_gate or "TARGET_INVALID")

        rec = SignalRecord(
            signal_time=decision_time, direction=direction, tier=None, session=None,
            entry_mode=entry_res.entry_mode, crt_entry=eff_entry, stop_loss=stop_loss,
            take_profit_1=plan.take_profit_1, take_profit_2=plan.take_profit_2,
            risk_price=risk_distance, rr_planned=plan.risk_reward_tp1, score=0.0,
            sweep_key=sweep_key,
        )
        simulate_outcome(rec, bars=bars, signal_index=i, spread=spread,
                         expiry_bars=expiry_bars, max_hold_bars=max_hold_bars)
        return _signal_to_dict(rec), ""
    except Exception as exc:
        return None, f"CF_ERROR:{type(exc).__name__}:{exc}"


def replay_chunk(
    bars: Sequence[CandleCreate], c1h: Sequence[CandleCreate],
    c1h_close: Sequence[datetime], c4h: Sequence[CandleCreate],
    c4h_close: Sequence[datetime], indices: Sequence[int], symbol: str,
    spread: float, expiry_bars: int, max_hold_bars: int, warmup_bars: int,
    bounds: Tuple[datetime, datetime], month: str,
) -> List[BarRecord]:
    """Evaluate only ``indices`` but with the full precomputed series as lookback."""
    crt = CRTStrategy(enable_dedup=False)
    engine = ConfluenceEngine(strategy_manager=StrategyManager([crt]))
    bar_close = [b.timestamp + TF_15M for b in bars]
    records: List[BarRecord] = []

    for i in indices:
        if i < warmup_bars:
            continue
        decision_time = bar_close[i]
        n15 = bisect_right(bar_close, decision_time)
        n1h = bisect_right(c1h_close, decision_time)
        n4h = bisect_right(c4h_close, decision_time)
        c15 = list(bars[max(0, n15 - 200):n15])
        primary = list(c1h[max(0, n1h - 200):n1h])
        ht_c4h = list(c4h[max(0, n4h - 100):n4h])
        if len(primary) < 20 or len(c15) < 50:
            continue
        try:
            structure, indicators, mtf = engine._prepare_market_data(
                symbol=symbol, timeframe="1h", c_prim=primary,
                c_4h=ht_c4h, c_15m=c15,
            )
            results = engine.strategy_manager.run_all_strategies(
                symbol=symbol, timeframe="1h", candles=primary,
                indicators=indicators, structure=structure, mtf=mtf,
                candles_15m=c15,
            )
        except Exception:
            continue

        result = results[0] if results else None
        meta = (result.metadata or {}) if result is not None else {}
        gate, is_breached, accepted = _classify_gate(result, meta)
        direction = _direction_of(meta)
        sweep_key = _sweep_key_of(meta, symbol) if is_breached else ""
        atr = float(getattr(getattr(indicators, "atr", None), "atr_value", 0.0) or 0.0)
        current_price = float(meta.get("entry_price") or 0.0) or (
            c15[-1].close if c15 else 0.0
        )

        rec = BarRecord(
            decision_time=decision_time.isoformat(), month=month,
            split=split_of(decision_time, bounds), index=i, gate=gate,
            direction=direction, sweep_key=sweep_key, is_breached=is_breached,
            accepted=accepted,
            confirmation_detail=str(meta.get("confirmation_detail") or ""),
        )
        if accepted:
            acc = _build_trade_from_meta(
                meta, direction, decision_time, sweep_key, i, bars,
                spread, expiry_bars, max_hold_bars,
            )
            if acc is not None:
                rec.accepted_trade = _signal_to_dict(acc)
        elif is_breached:
            cf, err = build_counterfactual(
                meta, current_price, atr, c15, structure, indicators, crt,
                decision_time, i, bars, spread, expiry_bars, max_hold_bars,
                direction, sweep_key,
            )
            rec.counterfactual_trade = cf
            rec.cf_error = err
        records.append(rec)
    return records


def _ckpt_path(ckpt_dir: Path, month: str) -> Path:
    return ckpt_dir / f"{month}.json"


def save_checkpoint(ckpt_dir: Path, month: str, records: Sequence[BarRecord]) -> None:
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    path = _ckpt_path(ckpt_dir, month)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"month": month, "records": [asdict(r) for r in records]}),
        encoding="utf-8",
    )
    tmp.replace(path)


def load_checkpoint(ckpt_dir: Path, month: str) -> List[BarRecord]:
    data = json.loads(_ckpt_path(ckpt_dir, month).read_text(encoding="utf-8"))
    return [BarRecord(**d) for d in data["records"]]


def trade_metrics(trades: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    filled = [t for t in trades if t.get("filled") and t.get("r_multiple") is not None]
    rs = [float(t["r_multiple"]) for t in filled]
    wins = [r for r in rs if r > 0]
    return {
        "n_candidates": len(trades),
        "n_filled": len(filled),
        "n_no_fill": len(trades) - len(filled),
        "win_rate": (len(wins) / len(rs) * 100.0) if rs else None,
        "avg_r": (sum(rs) / len(rs)) if rs else None,
        "expectancy": (sum(rs) / len(rs)) if rs else None,
    }


def build_extended_report(
    meta: Dict[str, Any], records: Sequence[BarRecord],
    bounds: Tuple[datetime, datetime], args: argparse.Namespace,
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (markdown, funnel rows, counterfactual rows)."""
    funnel: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(
        lambda: {"bars": 0, "BUY": 0, "SELL": 0, "sweeps": set()}
    )
    cf_trades: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    cf_candidates: Dict[Tuple[str, str], int] = defaultdict(int)
    accepted: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for r in records:
        key = (r.split, r.gate)
        funnel[key]["bars"] += 1
        if r.direction in ("BUY", "SELL"):
            funnel[key][r.direction] += 1
        if r.sweep_key:
            funnel[key]["sweeps"].add(r.sweep_key)
        if r.accepted and r.accepted_trade:
            accepted[r.split].append(r.accepted_trade)
        elif not r.accepted and r.is_breached:
            cf_candidates[key] += 1
            if r.counterfactual_trade:
                cf_trades[key].append(r.counterfactual_trade)

    funnel_rows: List[Dict[str, Any]] = []
    for (split, gate), d in sorted(funnel.items()):
        funnel_rows.append({
            "split": split, "gate": gate, "bars": d["bars"],
            "distinct_sweeps": len(d["sweeps"]),
            "buy_bars": d["BUY"], "sell_bars": d["SELL"],
        })

    cf_rows: List[Dict[str, Any]] = []
    for (split, gate), n_cand in sorted(cf_candidates.items()):
        trades = cf_trades.get((split, gate), [])
        m = trade_metrics(trades)
        m.update({
            "split": split, "rejection_reason": gate,
            "candidates": n_cand,
            "flagged_lt30": m["n_filled"] < 30,
        })
        cf_rows.append(m)
    for split, trades in sorted(accepted.items()):
        m = trade_metrics(trades)
        m.update({
            "split": split, "rejection_reason": "ACCEPTED (CONFIRMED_SETUP)",
            "candidates": len(trades), "flagged_lt30": m["n_filled"] < 30,
        })
        cf_rows.append(m)

    def fmt(v: Any, digits: int = 4) -> str:
        if v is None:
            return "n/a"
        if isinstance(v, float):
            return f"{v:.{digits}f}"
        return str(v)

    def warning(n: int) -> str:
        return "  ⚠️ n<30" if n < 30 else ""

    lines: List[str] = []
    lines.append("# CRT Replay — Full-Range Rejection Funnel & Counterfactual (No Thresholds Changed)")
    lines.append("")
    lines.append("Production path: `resample_ohlc` → `ConfluenceEngine._prepare_market_data` → "
                 "`StrategyManager.run_all_strategies` → `CRTStrategy` (dedup disabled). "
                 "Every rejected sweep is counterfactually re-priced through the same "
                 "`verify_ltf_confirmation` → `calculate_retracement_entry` → "
                 "`calculate_crt_targets` → `simulate_outcome` logic with its gate ignored.")
    lines.append("")
    lines.append("## 1. Data and walk-forward split")
    lines.append("")
    lines.append("| Item | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| Database | `{meta['db_path']}` |")
    lines.append(f"| Raw rows / duplicates dropped | {meta['raw_rows']:,} / {meta['duplicates_dropped']:,} |")
    lines.append(f"| Full range | {meta['raw_first']:%Y-%m-%d %H:%M} → {meta['raw_last']:%Y-%m-%d %H:%M} UTC |")
    lines.append(f"| Open-market bars replayed | {meta['open_market_bars']:,} |")
    lines.append(f"| Bar records captured | {len(records):,} |")
    lines.append(f"| Calibration boundary (60%) | {bounds[0]:%Y-%m-%d %H:%M} UTC |")
    lines.append(f"| Validation boundary (80%) | {bounds[1]:%Y-%m-%d %H:%M} UTC |")
    lines.append("")
    lines.append("Split windows: calibration = earliest 60% (observation only), validation = next 20%, "
                 "test = last 20% (untouched). No threshold was tuned on any split.")
    lines.append("")

    lines.append("## 2. Rejection funnel — bars and distinct sweeps by gate and direction")
    lines.append("")
    lines.append("Counts are bar-evaluations (first-failure-wins). A single sweep that survives many bars "
                 "is counted on every bar; `distinct_sweeps` de-duplicates by the production `sweep_event_key`.")
    lines.append("")
    lines.append("| Split | Gate | Bars | BUY bars | SELL bars | Distinct sweeps |")
    lines.append("| :--- | :--- | ---: | ---: | ---: | ---: |")
    for row in funnel_rows:
        lines.append(
            f"| {row['split']} | `{row['gate']}` | {row['bars']:,} | "
            f"{row['buy_bars']:,} | {row['sell_bars']:,} | {row['distinct_sweeps']:,} |"
        )
    lines.append("")

    lines.append("## 3. Counterfactual vs accepted trades")
    lines.append("")
    lines.append("For every rejected candidate with a validated sweep, the trade is re-priced as if the gate "
                 "had passed (same SL/TP/limit-zone logic, same spread). `n` counts trades with valid geometry; "
                 "`candidates` includes those that could not be re-priced. Expectancy = average R per filled trade.")
    lines.append("")
    lines.append("| Split | Rejection reason | Candidates | n | Filled | No fill | Win rate | Avg R | Expectancy | Flag |")
    lines.append("| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |")
    for row in cf_rows:
        lines.append(
            f"| {row['split']} | `{row['rejection_reason']}` | {row['candidates']:,} | "
            f"{row['n_candidates']:,} | {row['n_filled']:,} | {row['n_no_fill']:,} | "
            f"{fmt(row['win_rate'], 2)}% | {fmt(row['avg_r'])} | {fmt(row['expectancy'])} | "
            f"{warning(row['n_filled'])} |"
        )
    lines.append("")
    small = sum(1 for row in cf_rows if row["flagged_lt30"])
    lines.append(f"> {small} of {len(cf_rows)} groups have fewer than 30 filled trades (⚠️ flagged above). "
                 "Treat every metric in those groups as descriptive only.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("No strategy threshold was modified; all CRT parameters are production defaults.")
    return "\n".join(lines), funnel_rows, cf_rows


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(columns))
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in columns})


def main_full_range(args: argparse.Namespace) -> int:
    db_path = Path(args.db_path)
    print(f"[*] FULL-RANGE mode — loading {args.symbol} 15m candles from {db_path} ...")
    bars, meta = load_full_15m_candles(db_path, args.symbol, args.source)
    print(f"[*] {len(bars):,} open-market 15m bars "
          f"({meta['raw_first']} → {meta['raw_last']})")
    c1h, c1h_close, c4h, c4h_close = build_timeframe_series(bars)
    print(f"[*] Resampled 1h={len(c1h):,}, 4h={len(c4h):,} (complete buckets)")

    bounds = walk_forward_bounds(bars)
    months = month_keys(bars)
    ckpt_dir = Path(args.checkpoint_dir) if args.checkpoint_dir else (Path(args.out_dir) / "checkpoints")
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    print(f"[*] {len(months)} monthly chunks; checkpoints in {ckpt_dir}")

    all_records: List[BarRecord] = []
    for idx, (month, m_start, m_end) in enumerate(months):
        path = _ckpt_path(ckpt_dir, month)
        if path.exists() and not args.no_resume:
            recs = load_checkpoint(ckpt_dir, month)
            print(f"[=] {month}: {len(recs):,} records (cached)")
        else:
            indices = [
                i for i, b in enumerate(bars)
                if m_start <= b.timestamp < m_end
            ]
            recs = replay_chunk(
                bars=bars, c1h=c1h, c1h_close=c1h_close, c4h=c4h,
                c4h_close=c4h_close, indices=indices, symbol=args.symbol,
                spread=args.spread, expiry_bars=args.expiry_bars,
                max_hold_bars=args.max_hold_bars, warmup_bars=args.warmup_bars,
                bounds=bounds, month=month,
            )
            save_checkpoint(ckpt_dir, month, recs)
            print(f"[+] {month}: {len(recs):,} records (computed)")
        all_records.extend(recs)
        if args.max_chunks is not None and idx + 1 >= args.max_chunks:
            print(f"[*] --max-chunks={args.max_chunks} reached; stopping early.")
            break

    report, funnel_rows, cf_rows = build_extended_report(meta, all_records, bounds, args)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "crt_replay_extended_report.md"
    md_path.write_text(report + "\n", encoding="utf-8")
    funnel_csv = out_dir / "crt_replay_funnel.csv"
    cf_csv = out_dir / "crt_replay_counterfactual.csv"
    _write_csv(funnel_csv, funnel_rows,
               ("split", "gate", "bars", "buy_bars", "sell_bars", "distinct_sweeps"))
    _write_csv(cf_csv, cf_rows,
               ("split", "rejection_reason", "candidates", "n_candidates", "n_filled",
                "n_no_fill", "win_rate", "avg_r", "expectancy", "flagged_lt30"))
    print(f"[*] Markdown report : {md_path}")
    print(f"[*] Funnel CSV      : {funnel_csv}")
    print(f"[*] Counterfactual CSV: {cf_csv}")
    print(f"[*] Total bar records: {len(all_records):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
