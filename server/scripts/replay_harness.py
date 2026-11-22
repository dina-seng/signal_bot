"""Shared backtesting and outcome simulation harness for historical replays.

Extracted from crt_replay.py to provide a single, strategy-neutral foundation
for SMC replay, walk-forward analysis, and portfolio simulation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv
import random
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.schemas.candle import CandleCreate
from app.services.market_data.calendar import filter_open_market_candles, is_market_open
from app.services.market_data.resample import resample_ohlc
from replay_metrics import (
    compute_core_metrics,
    day_cluster_bootstrap_ci,
    iid_bootstrap_ci,
)

TF_15M = timedelta(minutes=15)
TF_1H = timedelta(hours=1)
TF_4H = timedelta(hours=4)

# Deterministic entry-invalidation outcomes (contract §3.3 / §7.3).
VOID_ENTRY_REASONS = {"VOID_ENTRY_BEYOND_SL", "VOID_ENTRY_BEYOND_TP"}
VOID_OUTCOMES = VOID_ENTRY_REASONS | {
    "NO_FILL_SESSION_BOUNDARY", "NO_FILL_MISSING_NEXT_BAR",
    "NO_FILL_END_OF_DATA", "INVALID_RISK",
}
# Descriptive-only divergence flag threshold; never rescales R or filters trades.
GAP_RISK_DIVERGENCE_PCT = 0.20
EXECUTION_COST_BASIS = "price_units_per_position_unit_round_trip"

CALIBRATION = "calibration"
VALIDATION = "validation"
TEST = "test"


# ---------------------------------------------------------------------------
# Timestamp parsers
# ---------------------------------------------------------------------------
def _parse_start_date(val: Optional[str]) -> Optional[datetime]:
    """Parse YYYY-MM-DD into UTC datetime at midnight."""
    if not val:
        return None
    dt = datetime.strptime(val.strip(), "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)


def _parse_ts(raw: str) -> datetime:
    """Parse the timestamp formats present in the candle table into aware UTC."""
    s = str(raw).strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Timeframe resampling helpers
# ---------------------------------------------------------------------------
def build_timeframe_series(
    bars_15m: Sequence[CandleCreate],
) -> Tuple[List[CandleCreate], List[datetime], List[CandleCreate], List[datetime]]:
    """Resample 1h and 4h using the production resampler and precompute close times."""
    c1h = resample_ohlc(list(bars_15m), "1h", calendar_aware=True)
    c4h = resample_ohlc(list(bars_15m), "4h", calendar_aware=True)
    c1h_close = [c.timestamp + TF_1H for c in c1h]
    c4h_close = [c.timestamp + TF_4H for c in c4h]
    return c1h, c1h_close, c4h, c4h_close


def assign_session_ids(bars: Sequence[CandleCreate]) -> List[int]:
    """Tag each bar with a trading-session id (Baseline v1, U-6).

    A new session begins when the immediately preceding 15m slot was outside
    market hours (weekend close or the 17:00-18:00 NY maintenance break).
    Bars from the calendar-filtered series are assumed already open.
    """
    ids: List[int] = []
    current = 0
    previous: Optional[datetime] = None
    for bar in bars:
        if previous is not None and not is_market_open(bar.timestamp - TF_15M):
            current += 1
        ids.append(current)
        previous = bar.timestamp
    return ids


# ---------------------------------------------------------------------------
# Signal Record
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
    target_type: Optional[str] = None

    # --- Baseline v1 execution-contract fields (Option B) -----------------
    # Geometry is anchored to signal_price / crt_entry and is write-once.
    signal_price: Optional[float] = None       # decision-time reference (1h close)
    fill_price: Optional[float] = None          # actual executable fill (next 15m open)
    entry_time: Optional[datetime] = None      # execution timestamp (candle open)
    entry_index: Optional[int] = None
    planned_risk: Optional[float] = None        # |signal_price - structural SL| (R denominator)
    actual_risk_distance: Optional[float] = None
    intended_stop: Optional[float] = None
    actual_exit_fill: Optional[float] = None
    price_unit_realized_pnl: Optional[float] = None
    monetary_realized_loss: Optional[float] = None  # not modelled (R-only engine)
    void_reason: Optional[str] = None
    gap_risk_divergence: bool = False
    execution_convention_version: str = "optionB-v1"

    @property
    def entry(self) -> float:
        return self.crt_entry


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
        "target_type": s.target_type,
        "signal_price": s.signal_price,
        "fill_price": s.fill_price,
        "entry_time": s.entry_time.isoformat() if s.entry_time else None,
        "entry_index": s.entry_index,
        "planned_risk": s.planned_risk,
        "actual_risk_distance": s.actual_risk_distance,
        "intended_stop": s.intended_stop,
        "actual_exit_fill": s.actual_exit_fill,
        "price_unit_realized_pnl": s.price_unit_realized_pnl,
        "monetary_realized_loss": s.monetary_realized_loss,
        "void_reason": s.void_reason,
        "gap_risk_divergence": s.gap_risk_divergence,
        "execution_convention_version": s.execution_convention_version,
        "execution_cost_basis": EXECUTION_COST_BASIS,
    }


# ---------------------------------------------------------------------------
# Outcome Simulation Engine
# ---------------------------------------------------------------------------
def simulate_outcome(
    record: SignalRecord,
    bars: Sequence[CandleCreate],
    signal_index: int,
    spread: float,
    expiry_bars: int,
    max_hold_bars: int,
    session_ids: Optional[Sequence[int]] = None,
) -> None:
    """Simulate a market (or limit-zone) entry with partial TP1/TP2 exits.

    Baseline v1 Option B execution contract:

    - A signal is evaluated at the CLOSE of bar ``signal_index``. The signal
      bar's high/low occurred before that decision and is NEVER managed.
    - A market order fills at the OPEN of the NEXT eligible 15m bar. All P&L is
      measured from that actual fill, never from the signal price.
    - SL/TP levels and planned risk are fixed at signal time and are write-once;
      they are never re-derived from the fill (Option A geometry).
    - Entry beyond the structural SL or TP is a deterministic void (no trade).
    - Gaps at managed bars fill at executable market prices: adverse through SL,
      favourable through TP. Same-bar ambiguity resolves SL-first.
    - 50% is booked at TP1 with stop moved to break-even (the signal-price
      anchor); 50% runs to TP2.
    - One flat round-trip cost in price units is deducted once, and R uses the
      planned (signal-time) risk as denominator.
    """

    def _void(reason: str, fill_price: Optional[float], fill_time: Optional[datetime],
              fill_idx: Optional[int]) -> None:
        record.filled = False
        record.exit_reason = reason
        record.void_reason = reason
        record.fill_price = fill_price
        record.fill_time = fill_time
        record.entry_time = fill_time
        record.entry_index = fill_idx
        record.exit_time = None
        record.r_multiple = None
        record.bars_held = 0
        record.spread_paid = 0.0

    is_buy = record.direction == "BUY"

    # Geometry anchor: signal price (the existing 1h-close reference), frozen.
    entry = record.signal_price if record.signal_price is not None else record.crt_entry
    record.signal_price = entry
    sl = record.stop_loss
    tp1 = record.take_profit_1
    tp2 = record.take_profit_2
    risk = abs(entry - sl)  # planned risk: the ONLY R denominator
    record.planned_risk = risk
    record.intended_stop = sl

    if risk <= 0:
        record.exit_reason = "INVALID_RISK"
        record.void_reason = "INVALID_RISK"
        record.r_multiple = 0.0
        return

    n = len(bars)
    fill_idx: Optional[int] = None
    fill_price: Optional[float] = None

    if record.entry_mode == "limit_zone":
        # Fill the limit before the stop when both are touched in one bar: a
        # BUY limit above its stop must trade through the limit to reach the
        # stop (BT-002). Only a bar OPENING beyond the stop voids the order.
        last = min(n, signal_index + 1 + expiry_bars)
        for k in range(signal_index + 1, last):
            bar = bars[k]
            if (is_buy and bar.open <= sl) or ((not is_buy) and bar.open >= sl):
                _void("NO_FILL_STOPPED_OUT", None, None, None)
                return
            touched = bar.low <= entry if is_buy else bar.high >= entry
            if touched:
                fill_idx = k
                fill_price = entry
                break
        if fill_idx is None:
            _void("NO_FILL_EXPIRED", None, None, None)
            return
    else:
        j = signal_index + 1
        if j >= n:
            _void("NO_FILL_END_OF_DATA", None, None, None)
            return
        if session_ids is not None and session_ids[j] != session_ids[signal_index]:
            _void("NO_FILL_SESSION_BOUNDARY", bars[j].open, bars[j].timestamp, j)
            return
        if bars[j].timestamp - bars[signal_index].timestamp > TF_15M:
            _void("NO_FILL_MISSING_NEXT_BAR", bars[j].open, bars[j].timestamp, j)
            return
        fill_idx = j
        fill_price = bars[j].open
        # Entry invalidation: the structure is already breached or the plan
        # already achieved before a position could exist.
        if (is_buy and fill_price <= sl) or ((not is_buy) and fill_price >= sl):
            _void("VOID_ENTRY_BEYOND_SL", fill_price, bars[j].timestamp, j)
            return
        if (is_buy and fill_price >= tp1) or ((not is_buy) and fill_price <= tp1):
            _void("VOID_ENTRY_BEYOND_TP", fill_price, bars[j].timestamp, j)
            return

    assert fill_idx is not None and fill_price is not None
    record.filled = True
    record.fill_time = bars[fill_idx].timestamp
    record.entry_time = bars[fill_idx].timestamp
    record.entry_index = fill_idx
    record.fill_price = fill_price
    record.actual_risk_distance = abs(fill_price - sl)
    if abs(record.actual_risk_distance - risk) / risk >= GAP_RISK_DIVERGENCE_PCT:
        record.gap_risk_divergence = True  # descriptive only; R denominator unchanged

    remaining = 1.0
    booked_price_pnl = 0.0  # weighted, per unit of position, in price terms
    stop = sl
    tp1_done = False
    exit_reason = ""
    exit_time: Optional[datetime] = None
    exit_fill: Optional[float] = None
    exit_idx = fill_idx

    hard_end = min(n, fill_idx + max_hold_bars)
    for k in range(fill_idx, hard_end):
        bar = bars[k]
        exit_idx = k

        # 1. Stop loss first (conservative same-bar resolution, gap-aware).
        hit_stop = bar.low <= stop if is_buy else bar.high >= stop
        if hit_stop:
            stop_fill = min(bar.open, stop) if is_buy else max(bar.open, stop)
            booked_price_pnl += remaining * (
                (stop_fill - fill_price) if is_buy else (fill_price - stop_fill)
            )
            remaining = 0.0
            exit_reason = "TP1_BE_STOP" if tp1_done else "STOP_LOSS"
            exit_time = bar.timestamp
            exit_fill = stop_fill
            break

        # 2. TP1 — book half, move the stop to break-even (signal-price anchor).
        if not tp1_done:
            hit_tp1 = bar.high >= tp1 if is_buy else bar.low <= tp1
            if hit_tp1:
                tp1_fill = max(bar.open, tp1) if is_buy else min(bar.open, tp1)
                size = remaining * 0.5
                booked_price_pnl += size * (
                    (tp1_fill - fill_price) if is_buy else (fill_price - tp1_fill)
                )
                remaining -= size
                tp1_done = True
                stop = entry

        # 3. TP2 — close the runner (favourable-gap aware).
        if tp1_done and remaining > 0:
            hit_tp2 = bar.high >= tp2 if is_buy else bar.low <= tp2
            if hit_tp2:
                tp2_fill = max(bar.open, tp2) if is_buy else min(bar.open, tp2)
                booked_price_pnl += remaining * (
                    (tp2_fill - fill_price) if is_buy else (fill_price - tp2_fill)
                )
                remaining = 0.0
                exit_reason = "TP2"
                exit_time = bar.timestamp
                exit_fill = tp2_fill
                break

    # Residual position: close at the final bar's close.
    if remaining > 0:
        last_bar = bars[min(n - 1, hard_end - 1)]
        exit_price = last_bar.close
        booked_price_pnl += remaining * (
            (exit_price - fill_price) if is_buy else (fill_price - exit_price)
        )
        exit_reason = "TIME_EXPIRY" if hard_end < n else "END_OF_DATA"
        exit_time = last_bar.timestamp
        exit_fill = exit_price

    record.price_unit_realized_pnl = booked_price_pnl
    net_price_pnl = booked_price_pnl - spread  # one flat round-trip cost
    record.spread_paid = spread
    record.r_multiple = round(net_price_pnl / risk, 4)
    record.exit_reason = exit_reason
    record.exit_time = exit_time
    record.actual_exit_fill = exit_fill
    record.bars_held = exit_idx - fill_idx


# ---------------------------------------------------------------------------
# Data Loading & Walk-Forward Partitioning
# ---------------------------------------------------------------------------
def load_full_15m_candles(
    db_path: Path, symbol: str, source: str, as_of: Optional[datetime] = None
) -> Tuple[List[CandleCreate], Dict[str, Any]]:
    """Read the validated, deduplicated, open-market 15m series (read-only).

    Baseline v1 data-integrity rules (contract §7):
      - reject non-monotonic timestamps and conflicting duplicate bars;
      - reject invalid OHLC;
      - drop forming bars when ``as_of`` is supplied
        (bar close must satisfy ``timestamp + 15m <= as_of``);
      - preserve the source and market-calendar filters.
    """
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

    # The source table stores several timestamp spellings ("YYYY-MM-DD HH:MM:SS",
    # with microseconds, and ISO+offset). SQL string ordering does not match
    # chronological order across those spellings, so parse first and order by
    # the parsed UTC instant. This is interpretation, not value repair: the
    # monotonic/duplicate/conflict checks below still run on the parsed series.
    parsed_rows = [(_parse_ts(r["timestamp"]), r) for r in rows]
    parsed_rows.sort(key=lambda item: item[0])

    seen: Dict[datetime, Tuple[float, float, float, float]] = {}
    deduped: List[CandleCreate] = []
    duplicates = 0
    previous_ts: Optional[datetime] = None
    for ts, r in parsed_rows:
        if previous_ts is not None and ts < previous_ts:
            raise SystemExit(
                f"non-monotonic timestamps at {ts.isoformat()} after {previous_ts.isoformat()}"
            )
        previous_ts = ts
        o, h, l, c = (
            float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
        )
        if not (h >= max(o, c) and l <= min(o, c) and h >= l and min(o, h, l, c) > 0):
            raise SystemExit(f"invalid OHLC at {ts.isoformat()}: {(o, h, l, c)}")
        values = (o, h, l, c)
        if ts in seen:
            if seen[ts] != values:
                raise SystemExit(
                    f"conflicting duplicate at {ts.isoformat()}: {seen[ts]} vs {values}"
                )
            duplicates += 1
            continue
        seen[ts] = values
        deduped.append(
            CandleCreate(
                symbol=symbol, timeframe="15m", timestamp=ts,
                open=o, high=h, low=l, close=c,
                volume=float(r["volume"] or 0.0), source=r["source"],
            )
        )

    if as_of is not None:
        deduped = [b for b in deduped if b.timestamp + TF_15M <= as_of]

    open_market = filter_open_market_candles(deduped)
    session_ids = assign_session_ids(open_market)
    missing_intraday = sum(
        1 for a, b, sa, sb in zip(open_market, open_market[1:], session_ids, session_ids[1:])
        if b.timestamp - a.timestamp > TF_15M and sa == sb
    )
    meta = {
        "db_path": str(db_path),
        "raw_rows": len(rows),
        "duplicates_dropped": duplicates,
        "raw_first": deduped[0].timestamp,
        "raw_last": deduped[-1].timestamp,
        "bars_in_window": len(deduped),
        "open_market_bars": len(open_market),
        "closed_market_dropped": len(deduped) - len(open_market),
        "session_ids": session_ids,
        "missing_intraday_bars": missing_intraday,
        "as_of": as_of,
    }
    return open_market, meta


def walk_forward_bounds(bars: Sequence[CandleCreate]) -> Tuple[datetime, datetime]:
    """Earliest 60% / next 20% / last 20% by elapsed time across the series."""
    start, end = bars[0].timestamp, bars[-1].timestamp
    span = end - start
    return start + span * 0.60, start + span * 0.80


def split_of(ts: datetime, bounds: Tuple[datetime, datetime]) -> str:
    """Canonical split membership (matches smc_replay.split_of, N-10)."""
    b1, b2 = bounds
    if ts <= b1:
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


# ---------------------------------------------------------------------------
# Metrics & Reporting Helpers
# ---------------------------------------------------------------------------
def _bootstrap_ci(values: Sequence[float], resamples: int = 2000, seed: int = 12345) -> Tuple[float, float]:
    """Deterministic IID bootstrap 95% CI (legacy; cluster CI is canonical)."""
    return iid_bootstrap_ci(values, resamples=resamples, seed=seed)


@dataclass
class Metrics:
    n_signals: int = 0
    n_filled: int = 0
    n_no_fill: int = 0
    n_void_entry: int = 0
    void_rate: Optional[float] = None
    void_reasons: Dict[str, int] = field(default_factory=dict)
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    avg_r: Optional[float] = None
    expectancy: Optional[float] = None
    max_drawdown_r: Optional[float] = None
    total_r: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    sample_warning: str = ""


def compute_metrics(signals: Sequence[SignalRecord]) -> Metrics:
    filled = [s for s in signals if s.filled and s.r_multiple is not None]
    voids = [s for s in signals if s.void_reason]
    reasons: Dict[str, int] = {}
    for s in voids:
        reason = str(s.void_reason)
        reasons[reason] = reasons.get(reason, 0) + 1
    n_signals = len(signals)
    m = Metrics(
        n_signals=n_signals,
        n_filled=len(filled),
        n_no_fill=n_signals - len(filled) - len(voids),
        n_void_entry=len(voids),
        void_rate=(100.0 * len(voids) / n_signals) if n_signals else None,
        void_reasons=reasons,
    )
    if not filled:
        m.sample_warning = "No filled trades — sample too small for any inference."
        return m

    rs = [float(s.r_multiple) for s in filled]
    order = [
        (s.exit_time or s.signal_time).isoformat()
        for s in filled
    ]
    clusters = [
        (s.exit_time or s.signal_time).date().isoformat()
        for s in filled
    ]
    core = compute_core_metrics(rs, order=order)
    m.win_rate = core["win_rate"]
    m.avg_r = core["avg_r"]
    m.expectancy = core["avg_r"]
    m.profit_factor = core["profit_factor"]
    m.max_drawdown_r = core["max_drawdown_r"]
    m.total_r = core["total_r"]
    m.ci_lower, m.ci_upper = day_cluster_bootstrap_ci(rs, clusters)
    return m


def trade_metrics(trades: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    filled = [t for t in trades if t.get("filled") and t.get("r_multiple") is not None]
    voids = [t for t in trades if t.get("void_reason")]
    reasons: Dict[str, int] = {}
    for t in voids:
        reason = str(t.get("void_reason"))
        reasons[reason] = reasons.get(reason, 0) + 1
    rs = [float(t["r_multiple"]) for t in filled]
    order = [
        t.get("exit_time") or t.get("signal_time") or ""
        for t in filled
    ]
    clusters = [
        str(order[i])[:10] for i in range(len(filled))
    ]
    core = compute_core_metrics(rs, order=order)
    n = len(trades)
    return {
        "n_candidates": n,
        "n_filled": len(filled),
        "n_no_fill": n - len(filled) - len(voids),
        "n_void_entry": len(voids),
        "void_rate": (100.0 * len(voids) / n) if n else None,
        "void_reasons": reasons,
        "win_rate": core["win_rate"],
        "avg_r": core["avg_r"],
        "expectancy": core["avg_r"],
        "median_r": core["median_r"],
        "profit_factor": core["profit_factor"],
        "total_r": core["total_r"],
        "max_drawdown_r": core["max_drawdown_r"],
        "ci_basis": "day_cluster",
        "_clusters": clusters,
    }


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(columns))
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in columns})
