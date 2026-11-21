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
from app.services.market_data.calendar import filter_open_market_candles
from app.services.market_data.resample import resample_ohlc

TF_15M = timedelta(minutes=15)
TF_1H = timedelta(hours=1)
TF_4H = timedelta(hours=4)

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

    # If the trade survived to the end of the simulation window, close at the last bar.
    if remaining > 0:
        last_bar = bars[min(n - 1, hard_end - 1)]
        exit_price = last_bar.close
        pnl = (exit_price - entry) if is_buy else (entry - exit_price)
        booked_price_pnl += remaining * pnl
        exit_reason = "TIME_EXPIRY" if hard_end < n else "END_OF_DATA"
        exit_time = last_bar.timestamp

    # Friction model: deduct one full round-trip spread in price units.
    net_price_pnl = booked_price_pnl - spread
    r_mult = net_price_pnl / risk

    record.exit_reason = exit_reason
    record.exit_time = exit_time
    record.r_multiple = round(r_mult, 4)
    record.bars_held = exit_idx - fill_idx
    record.spread_paid = spread


# ---------------------------------------------------------------------------
# Data Loading & Walk-Forward Partitioning
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Metrics & Reporting Helpers
# ---------------------------------------------------------------------------
def _bootstrap_ci(values: Sequence[float], resamples: int = 2000, seed: int = 12345) -> Tuple[float, float]:
    """Deterministic bootstrap 95% CI for the mean R."""
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


@dataclass
class Metrics:
    n_signals: int = 0
    n_filled: int = 0
    n_no_fill: int = 0
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
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    m.profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)

    # Peak-to-trough in R
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rs:
        eq += r
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd
    m.max_drawdown_r = max_dd
    m.total_r = sum(rs)
    m.ci_lower, m.ci_upper = _bootstrap_ci(rs)
    return m


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


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(columns))
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in columns})
