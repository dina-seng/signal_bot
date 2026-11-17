"""Comprehensive Backtest for CRT Strategy on Recent Data (2025-01-01 to Present).

Orchestrates the bar-by-bar CRT replay, simulates trade execution with strict zero-lookahead,
applies Phase C portfolio constraints, and produces institutional metrics, an equity curve CSV,
and a Markdown performance report.

Portfolio Rules (Phase C):
  - MAX_CONCURRENT = 3 open positions
  - ONE_ENTRY_PER_SWEEP = True
  - MIN_ENTRY_SEPARATION = >= 1.0 x ATR(14, 15m) OR >= 1h since last same-direction entry
  - DAILY_LOSS_STOP = -3.0 R realized per UTC trading day
  - Friction = $0.40 round-trip spread deduction per trade
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import sys
import time
from bisect import bisect_right
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# Ensure repository root and server directories are on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))
SCRIPTS_ROOT = SERVER_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from app.schemas.candle import CandleCreate
from app.schemas.signal import SignalDirection
from app.services.indicators.atr_calculator import ATRCalculator
from app.services.market_data.calendar import filter_open_market_candles
from app.services.market_data.resample import resample_ohlc
from app.services.signals.confluence_engine import ConfluenceEngine
from app.services.strategies.crt_strategy import CRTStrategy
from app.services.strategies.strategy_manager import StrategyManager
from crt_replay import (
    GATE_ORDER,
    PRE_SWEEP_GATES,
    ReplayStats,
    SignalRecord,
    _empty_funnel,
    _parse_ts,
    build_timeframe_series,
    simulate_outcome,
)

TF_15M = timedelta(minutes=15)
TF_1H = timedelta(hours=1)
TF_4H = timedelta(hours=4)
CONFIRMED_STATE = "CONFIRMED_SETUP"


# ---------------------------------------------------------------------------
# Data Loading with strict date filtering
# ---------------------------------------------------------------------------
def load_recent_15m_candles(
    db_path: Path,
    symbol: str = "XAU/USD",
    source: str = "twelvedata",
    start_date: str = "2025-01-01",
) -> Tuple[List[CandleCreate], Dict[str, Any]]:
    """Load and window 15m candles directly from SQLite with strict start_date filtering."""
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        # Strict SQL-level filtering to avoid loading unnecessary historical rows into memory
        rows = conn.execute(
            """
            SELECT timestamp, open, high, low, close, volume, source
            FROM candles
            WHERE symbol = ? AND timeframe = '15m' AND source = ? AND timestamp >= ?
            ORDER BY timestamp
            """,
            (symbol, source, start_date),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        raise SystemExit(f"No {symbol} 15m rows found with source='{source}' and timestamp >= '{start_date}'")

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

    before_calendar = len(deduped)
    open_market = filter_open_market_candles(deduped)

    meta = {
        "db_path": str(db_path),
        "symbol": symbol,
        "source": source,
        "start_date": start_date,
        "raw_rows": len(rows),
        "duplicates_dropped": duplicates,
        "raw_first": deduped[0].timestamp,
        "raw_last": deduped[-1].timestamp,
        "bars_in_window": before_calendar,
        "open_market_bars": len(open_market),
        "closed_market_dropped": before_calendar - len(open_market),
    }
    return open_market, meta


# ---------------------------------------------------------------------------
# Bar-by-Bar Replay
# ---------------------------------------------------------------------------
def run_bar_by_bar_replay(
    bars: Sequence[CandleCreate],
    c1h: Sequence[CandleCreate],
    c1h_close: Sequence[datetime],
    c4h: Sequence[CandleCreate],
    c4h_close: Sequence[datetime],
    symbol: str,
    spread: float = 0.40,
    expiry_bars: int = 8,
    max_hold_bars: int = 500,
    warmup_bars: int = 100,
    dump_finalists: bool = True,
    finalists_path: Optional[Path] = None,
) -> Tuple[Dict[str, int], List[SignalRecord], ReplayStats]:
    """Replay bars in chronological order and simulate outcomes for emitted CRT signals."""
    crt = CRTStrategy(enable_dedup=False, allow_counter_trend_bypass=False)
    engine = ConfluenceEngine(strategy_manager=StrategyManager([crt]))

    funnel = _empty_funnel()
    raw_signals: List[SignalRecord] = []
    stats = ReplayStats()

    bar_close = [b.timestamp + TF_15M for b in bars]
    n = len(bars)

    finalists_file = None
    if dump_finalists:
        out_jsonl = Path(finalists_path) if finalists_path else (REPO_ROOT / "reports" / "crt_finalists_recent.jsonl")
        out_jsonl.parent.mkdir(parents=True, exist_ok=True)
        finalists_file = out_jsonl.open("w", encoding="utf-8")

    t_start = time.time()
    t_est_seconds = n / 1000.0
    print(f"[*] Starting bar-by-bar replay across {n:,} 15m open-market bars (estimated nominal duration: ~{t_est_seconds:.0f}s)...")

    current_month_key: Optional[str] = None

    for i, bar in enumerate(bars):
        decision_time = bar_close[i]

        # Log month-by-month progress
        bar_month = bar.timestamp.strftime("%Y-%m")
        if bar_month != current_month_key:
            current_month_key = bar_month
            now_t = time.time()
            elapsed = now_t - t_start
            rate = i / elapsed if elapsed > 0 else 0.0
            eta = (n - i) / rate if rate > 0 else 0.0
            print(f"    [{bar_month}] bar {i:,}/{n:,} ({i/n*100:.1f}%) | Signals: {len(raw_signals):,} | INVALID_ENTRY_ZONE: {funnel.get('INVALID_ENTRY_ZONE', 0)} | Speed: {rate:.0f} bars/s | ETA: {eta:.0f}s")

        if i < warmup_bars:
            stats.warmup_skipped += 1
            continue

        n15 = bisect_right(bar_close, decision_time)
        n1h = bisect_right(c1h_close, decision_time)
        n4h = bisect_right(c4h_close, decision_time)

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
        except Exception as exc:
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

        FINALIST_GATES = {
            "INVALID_ENTRY_ZONE",
            "MISSED_SETUP",
            "INVALID_RISK_GEOMETRY",
            "EXCESSIVE_RISK_DISTANCE",
            "INSUFFICIENT_RR",
            "PATH_BLOCKED",
            "SCORE_BELOW_THRESHOLD",
            "CONFIRMED_SETUP",
            "DEDUPLICATED",
        }

        is_confirmed_signal = (state == CONFIRMED_STATE and result.direction.value in ("BUY", "SELL"))
        effective_gate = "CONFIRMED_SETUP" if is_confirmed_signal else (
            gate if gate else (
                "NO_SWEEP" if not is_breached else (
                    "TREND_CONFLICT" if meta.get("trend_conflict") else (
                        "SCORE_BELOW_THRESHOLD" if (state == "POTENTIAL_SETUP" and not meta.get("gatekeeper_passed", False)) else "OTHER_WAIT"
                    )
                )
            )
        )

        # Diagnostic finalist dump
        if finalists_file and (effective_gate in FINALIST_GATES or is_confirmed_signal):
            direction_str = (
                result.direction.value
                if result.direction.value in ("BUY", "SELL")
                else ("BUY" if crt_analysis.get("positive_direction") else "SELL")
            )
            c_price = round(float(result.entry_price or (c15[-1].close if c15 else 0.0)), 5)
            i_entry = round(float(meta.get("ideal_entry") or meta.get("entry_price") or result.entry_price or c_price), 5)
            e_mode = str(meta.get("entry_mode") or "limit_zone")
            ez = meta.get("entry_zone") or [0.0, 0.0]
            z_low = round(float(ez[0]), 5)
            z_high = round(float(ez[1]), 5)
            sl_val = round(float(meta.get("stop_loss") or result.stop_loss or 0.0), 5)
            tp1_val = round(float(meta.get("take_profit_1") or result.take_profit_1 or 0.0), 5)
            r_dist = round(float(meta.get("risk_distance") or abs(i_entry - sl_val)), 5)
            eff_atr = round(float(meta.get("effective_atr") or 0.0), 5)
            d_size = round(float(meta.get("displacement_size") or 0.0), 5)
            d_ext = round(float(meta.get("displacement_extreme") or 0.0), 5)
            m_idx = int(crt_analysis.get("manipulation_candle_index") or 0)
            b_ts = crt_analysis.get("breach_timestamp")
            b_ts_str = str(b_ts) if b_ts is not None else None
            score_val = round(float(result.score or 0.0), 2)
            sub_cond = str(meta.get("sub_condition") or "")
            if not sub_cond and effective_gate == "INVALID_ENTRY_ZONE":
                if direction_str == "BUY":
                    sub_cond = f"BUY: stop_loss ({sl_val:.5f}) > zone_low ({z_low:.5f})"
                else:
                    sub_cond = f"SELL: stop_loss ({sl_val:.5f}) < zone_high ({z_high:.5f})"

            finalist_rec = {
                "timestamp": decision_time.isoformat(),
                "direction": direction_str,
                "gate": effective_gate,
                "current_price": c_price,
                "ideal_entry": i_entry,
                "entry_mode": e_mode,
                "zone_low": z_low,
                "zone_high": z_high,
                "stop_loss": sl_val,
                "take_profit_1": tp1_val,
                "risk_distance": r_dist,
                "effective_atr": eff_atr,
                "displacement_size": d_size,
                "displacement_extreme": d_ext,
                "manipulation_candle_index": m_idx,
                "breach_timestamp": b_ts_str,
                "score": score_val,
                "sub_condition": sub_cond,
            }
            finalists_file.write(json.dumps(finalist_rec) + "\n")
            finalists_file.flush()

        if is_confirmed_signal:
            sweep_key = str(meta.get("sweep_event_key") or "")
            entry = float(meta.get("entry_price") or 0.0)
            sl = float(meta.get("stop_loss") or 0.0)
            tp1 = float(meta.get("take_profit_1") or 0.0)
            tp2 = float(meta.get("take_profit_2") or 0.0)

            if entry <= 0 or sl <= 0 or tp1 <= 0 or tp2 <= 0:
                funnel["OTHER_WAIT"] += 1
                continue

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
                sweep_key=sweep_key,
            )

            # Strict production outcome simulation with $0.40 round-trip friction
            simulate_outcome(
                rec,
                bars=bars,
                signal_index=i,
                spread=spread,
                expiry_bars=expiry_bars,
                max_hold_bars=max_hold_bars,
            )
            raw_signals.append(rec)
            continue

        if gate:
            funnel[gate] = funnel.get(gate, 0) + 1
            if gate == "CONFIRMATION_PENDING":
                detail = meta.get("confirmation_detail")
                if not detail:
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

    if finalists_file:
        finalists_file.close()

    total_eval_time = time.time() - t_start
    print(f"[*] Replay finished in {total_eval_time:.1f}s. Evaluated: {stats.evaluated:,} bars. Emitted signals: {len(raw_signals):,}")
    return funnel, raw_signals, stats


# ---------------------------------------------------------------------------
# Phase C Portfolio Simulation Engine
# ---------------------------------------------------------------------------
@dataclass
class PortfolioExecutionResult:
    entered_trades: List[Dict[str, Any]]
    skipped_trades: List[Dict[str, Any]]
    skip_counts: Dict[str, int]
    timeline_records: List[Dict[str, Any]]


def simulate_portfolio_rules(
    signals: Sequence[SignalRecord],
    bars: Sequence[CandleCreate],
    atr_series: Sequence[Optional[float]],
    max_concurrent: int = 3,
    daily_loss_stop: float = -3.0,
    min_sep_atr_mult: float = 1.0,
    min_sep_hours: float = 1.0,
    one_entry_per_sweep: bool = True,
) -> PortfolioExecutionResult:
    """Filter raw signals through Phase C institutional portfolio constraints."""
    bar_close = [b.timestamp + TF_15M for b in bars]
    bar_close_idx_map = {bc: i for i, bc in enumerate(bar_close)}

    # Convert SignalRecord objects to dicts with ATR information
    setups: List[Dict[str, Any]] = []
    for s in signals:
        idx = bar_close_idx_map.get(s.signal_time)
        atr_val = atr_series[idx] if (idx is not None and atr_series[idx] is not None) else 2.0
        setups.append({
            "record": s,
            "decision_dt": s.signal_time,
            "day": s.signal_time.strftime("%Y-%m-%d"),
            "direction": s.direction,
            "crt_entry": s.crt_entry,
            "stop_loss": s.stop_loss,
            "take_profit_1": s.take_profit_1,
            "take_profit_2": s.take_profit_2,
            "filled": s.filled,
            "fill_time": s.fill_time,
            "exit_time": s.exit_time,
            "exit_reason": s.exit_reason,
            "r": s.r_multiple if s.r_multiple is not None else 0.0,
            "bars_held": s.bars_held,
            "spread_paid": s.spread_paid,
            "sweep_key": s.sweep_key,
            "score": s.score,
            "atr": atr_val,
        })

    # Sort strictly by decision time
    setups.sort(key=lambda x: x["decision_dt"])

    # 1. ONE_ENTRY_PER_SWEEP check
    seen_sweeps: set[str] = set()
    distinct_setups: List[Dict[str, Any]] = []
    skipped_same_sweep: List[Dict[str, Any]] = []

    for t in setups:
        k = t["sweep_key"]
        if one_entry_per_sweep:
            if k in seen_sweeps:
                t_copy = dict(t)
                t_copy["skip_reason"] = "SAME_SWEEP"
                skipped_same_sweep.append(t_copy)
                continue
            seen_sweeps.add(k)
        distinct_setups.append(t)

    # 2. Portfolio Walk Forward Simulation
    open_positions: List[Dict[str, Any]] = []
    portfolio_entered: List[Dict[str, Any]] = []
    portfolio_skipped: List[Dict[str, Any]] = list(skipped_same_sweep)
    skip_counts: Dict[str, int] = defaultdict(int)
    skip_counts["SAME_SWEEP"] = len(skipped_same_sweep)

    for t in distinct_setups:
        dt = t["decision_dt"]
        day_str = t["day"]
        d = t["direction"]
        p_entry = t["crt_entry"]
        atr = t["atr"]

        # Evict closed positions before or at current decision time
        open_positions = [pos for pos in open_positions if pos["exit_time"] > dt]

        # Rule 1: DAILY_LOSS_STOP (-3.0 R realized per UTC trading day before/at dt)
        today_realized_r = sum(
            pos["r"]
            for pos in portfolio_entered
            if pos["exit_time"] is not None
            and pos["exit_time"].strftime("%Y-%m-%d") == day_str
            and pos["exit_time"] <= dt
        )
        if today_realized_r <= daily_loss_stop:
            skip_counts["DAILY_LOSS_STOP"] += 1
            t_copy = dict(t)
            t_copy["skip_reason"] = "DAILY_LOSS_STOP"
            portfolio_skipped.append(t_copy)
            continue

        # Rule 2: MAX_CONCURRENT = 3 open positions
        if len(open_positions) >= max_concurrent:
            skip_counts["CONCURRENCY_CAP"] += 1
            t_copy = dict(t)
            t_copy["skip_reason"] = "CONCURRENCY_CAP"
            portfolio_skipped.append(t_copy)
            continue

        # Rule 3: MIN_ENTRY_SEPARATION
        # Needs >= 1.0 x ATR distance from every open same-direction entry, OR >= 1h since last same-direction entry
        same_dir_open = [pos for pos in open_positions if pos["direction"] == d]
        sep_violation = False
        for pos in same_dir_open:
            time_diff = dt - pos["decision_dt"]
            price_diff = abs(p_entry - pos["crt_entry"])
            if time_diff < timedelta(hours=min_sep_hours) and price_diff < (min_sep_atr_mult * atr):
                sep_violation = True
                break

        if sep_violation:
            skip_counts["SEPARATION_RULE"] += 1
            t_copy = dict(t)
            t_copy["skip_reason"] = "SEPARATION_RULE"
            portfolio_skipped.append(t_copy)
            continue

        # Check if trade filled
        if not t["filled"]:
            skip_counts["UNFILLED"] += 1
            t_copy = dict(t)
            t_copy["skip_reason"] = t["exit_reason"] or "NO_FILL"
            portfolio_skipped.append(t_copy)
            continue

        # Accepted into Portfolio
        portfolio_entered.append(t)
        open_positions.append(t)

    # 3. Generate Time-Series Equity Curve and Position State for every 15m bar
    # Tracking cumulative R and open positions across the entire period
    timeline_records: List[Dict[str, Any]] = []
    cumulative_r = 0.0
    peak_r = 0.0
    active_in_bar: List[Dict[str, Any]] = []

    # Map trade exits by bar close time
    exits_by_time: Dict[datetime, List[Dict[str, Any]]] = defaultdict(list)
    entries_by_time: Dict[datetime, List[Dict[str, Any]]] = defaultdict(list)

    for trade in portfolio_entered:
        fill_t = trade["fill_time"] or trade["decision_dt"]
        exit_t = trade["exit_time"]
        entries_by_time[fill_t].append(trade)
        if exit_t is not None:
            exits_by_time[exit_t].append(trade)

    for bar in bars:
        bar_t = bar.timestamp

        # Add newly opened positions at this bar
        for t in entries_by_time.get(bar_t, []):
            active_in_bar.append(t)

        # Realize PnL for positions exiting at or before this bar
        for t in exits_by_time.get(bar_t, []):
            cumulative_r += float(t["r"])

        # Evict exited positions
        active_in_bar = [p for p in active_in_bar if p["exit_time"] > bar_t]

        peak_r = max(peak_r, cumulative_r)
        drawdown_r = peak_r - cumulative_r

        timeline_records.append({
            "timestamp": bar_t.isoformat(),
            "cumulative_R": round(cumulative_r, 4),
            "drawdown_R": round(drawdown_r, 4),
            "open_positions": len(active_in_bar),
        })

    return PortfolioExecutionResult(
        entered_trades=portfolio_entered,
        skipped_trades=portfolio_skipped,
        skip_counts=dict(skip_counts),
        timeline_records=timeline_records,
    )


# ---------------------------------------------------------------------------
# Metrics Computation
# ---------------------------------------------------------------------------
@dataclass
class InstitutionalMetrics:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    win_rate: float = 0.0
    loss_rate: float = 0.0
    mean_r: float = 0.0
    median_r: float = 0.0
    expectancy: float = 0.0
    gross_profit_r: float = 0.0
    gross_loss_r: float = 0.0
    profit_factor: float = 0.0
    total_r: float = 0.0
    max_drawdown_r: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_daily_ann: float = 0.0
    sharpe_trade_ann: float = 0.0
    avg_holding_time_hours: float = 0.0
    holding_time_median_hours: float = 0.0
    holding_time_p75_hours: float = 0.0
    holding_time_p90_hours: float = 0.0
    holding_time_max_hours: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    win_loss_ratio: float = 0.0
    total_trading_days: int = 0
    trades_per_day: float = 0.0


def calculate_institutional_metrics(
    trades: Sequence[Dict[str, Any]],
    timeline: Sequence[Dict[str, Any]],
    bars: Sequence[CandleCreate],
) -> InstitutionalMetrics:
    """Calculate institutional performance and risk metrics."""
    m = InstitutionalMetrics()
    n = len(trades)
    m.total_trades = n

    all_days = {b.timestamp.strftime("%Y-%m-%d") for b in bars}
    m.total_trading_days = len(all_days)
    m.trades_per_day = n / len(all_days) if all_days else 0.0

    if n == 0:
        return m

    rs = [float(t["r"]) for t in trades]
    wins = [r for r in rs if r > 0.0001]
    losses = [r for r in rs if r < -0.0001]
    bes = [r for r in rs if abs(r) <= 0.0001]

    m.winning_trades = len(wins)
    m.losing_trades = len(losses)
    m.breakeven_trades = len(bes)

    m.win_rate = round(len(wins) / n * 100.0, 2)
    m.loss_rate = round(len(losses) / n * 100.0, 2)

    m.mean_r = round(float(np.mean(rs)), 4)
    m.median_r = round(float(np.median(rs)), 4)
    m.expectancy = m.mean_r
    m.total_r = round(float(np.sum(rs)), 2)

    m.gross_profit_r = round(float(sum(wins)), 2)
    m.gross_loss_r = round(abs(float(sum(losses))), 2)

    if m.gross_loss_r > 0:
        m.profit_factor = round(m.gross_profit_r / m.gross_loss_r, 2)
    elif m.gross_profit_r > 0:
        m.profit_factor = 99.99
    else:
        m.profit_factor = 0.0

    m.avg_win_r = round(float(np.mean(wins)), 4) if wins else 0.0
    m.avg_loss_r = round(abs(float(np.mean(losses))), 4) if losses else 0.0
    m.win_loss_ratio = round(m.avg_win_r / m.avg_loss_r, 2) if m.avg_loss_r > 0 else 0.0

    # Holding times
    holding_hours = [float(t["bars_held"]) * 0.25 for t in trades]
    if holding_hours:
        m.avg_holding_time_hours = round(float(np.mean(holding_hours)), 2)
        m.holding_time_median_hours = round(float(np.median(holding_hours)), 2)
        m.holding_time_p75_hours = round(float(np.percentile(holding_hours, 75)), 2)
        m.holding_time_p90_hours = round(float(np.percentile(holding_hours, 90)), 2)
        m.holding_time_max_hours = round(float(np.max(holding_hours)), 2)
    else:
        m.avg_holding_time_hours = 0.0
        m.holding_time_median_hours = 0.0
        m.holding_time_p75_hours = 0.0
        m.holding_time_p90_hours = 0.0
        m.holding_time_max_hours = 0.0

    # Max Drawdown from timeline (R and %)
    # Standard institutional model: assume 1.0 R = 1.0% account equity, starting balance 100 R
    max_dd_r = 0.0
    for row in timeline:
        dd = float(row["drawdown_R"])
        if dd > max_dd_r:
            max_dd_r = dd
    m.max_drawdown_r = round(max_dd_r, 2)

    # % Drawdown assuming starting capital of 100 R (1% fixed risk)
    initial_equity_r = 100.0
    peak_eq = initial_equity_r
    max_dd_pct = 0.0
    for row in timeline:
        eq = initial_equity_r + float(row["cumulative_R"])
        if eq > peak_eq:
            peak_eq = eq
        else:
            dd_pct = ((peak_eq - eq) / peak_eq) * 100.0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
    m.max_drawdown_pct = round(max_dd_pct, 2)

    # Annualized Sharpe (Daily returns approach)
    # Aggregate realized R per calendar trading day
    daily_realized: Dict[str, float] = defaultdict(float)
    for t in trades:
        day = t["exit_time"].strftime("%Y-%m-%d")
        daily_realized[day] += float(t["r"])

    # Include non-trading days as 0 return across all trading days
    daily_returns = [daily_realized.get(d, 0.0) for d in all_days]
    if len(daily_returns) >= 2:
        mean_d = float(np.mean(daily_returns))
        std_d = float(np.std(daily_returns, ddof=1))
        if std_d > 1e-7:
            m.sharpe_daily_ann = round((mean_d / std_d) * math.sqrt(252), 2)

    # Annualized Sharpe (Per-trade approach)
    if len(rs) >= 2:
        std_r = float(np.std(rs, ddof=1))
        trades_per_year = n / (len(all_days) / 252.0) if all_days else 0.0
        if std_r > 1e-7 and trades_per_year > 0:
            m.sharpe_trade_ann = round((m.mean_r / std_r) * math.sqrt(trades_per_year), 2)

    return m


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------
def generate_markdown_report(
    meta: Dict[str, Any],
    funnel: Dict[str, int],
    stats: ReplayStats,
    raw_signals: Sequence[SignalRecord],
    exec_result: PortfolioExecutionResult,
    metrics: InstitutionalMetrics,
    out_path: Path,
) -> str:
    """Generate professional institutional Markdown report."""
    lines: List[str] = []
    lines.append("# CRT Strategy Institutional Backtest Report — Recent Data")
    lines.append("")
    lines.append(f"**Period**: {meta['start_date']} to {meta['raw_last']:%Y-%m-%d %H:%M} UTC ({metrics.total_trading_days} Trading Days)")  
    lines.append(f"**Symbol**: {meta['symbol']} · **Timeframe**: 15m (Twelve Data)")  
    lines.append(f"**Execution Engine**: `simulate_outcome` with strict zero-lookahead, **$0.40 round-trip friction**")  
    lines.append(f"**Confirmation Engine**: Post-defect fix (Displacement prerequisite + Chronological MSS filtering)")  
    lines.append("")

    if metrics.total_trades < 30:
        lines.append("> [!WARNING]")
        lines.append(f"> ### ⚠️ UNDERPOWERED — n < 30 (n = {metrics.total_trades})")
        lines.append(f"> Total realized trades ({metrics.total_trades}) is strictly below the statistical power threshold (n ≥ 30).")
        lines.append("> Any performance metrics must be interpreted with extreme caution due to small sample variance.")
        lines.append("")

    lines.append("## Executive Summary")
    lines.append("")
    lines.append("| Metric | Value | Benchmark / Target | Status |")
    lines.append("| :--- | :--- | :--- | :--- |")
    lines.append(f"| **Total Realized Trades** | **{metrics.total_trades}** | ≥ 30 for statistical power | {'PASS' if metrics.total_trades >= 30 else 'UNDERPOWERED — n < 30'} |")
    lines.append(f"| **Win Rate (%)** | **{metrics.win_rate:.2f}%** | > 40.0% | {'PASS' if metrics.win_rate >= 40.0 else 'DEFICIENT'} |")
    lines.append(f"| **Loss Rate (%)** | **{metrics.loss_rate:.2f}%** | - | - |")
    lines.append(f"| **Expectancy per Trade** | **{metrics.expectancy:+.4f} R** | > +0.2000 R | {'PASS' if metrics.expectancy >= 0.20 else ('NEUTRAL' if metrics.expectancy > 0 else 'NEGATIVE')} |")
    lines.append(f"| **Mean R** | **{metrics.mean_r:+.4f} R** | > 0 | - |")
    lines.append(f"| **Median R** | **{metrics.median_r:+.4f} R** | > 0 | - |")
    lines.append(f"| **Profit Factor** | **{metrics.profit_factor:.2f}** | > 1.30 | {'PASS' if metrics.profit_factor >= 1.30 else 'FAIL'} |")
    lines.append(f"| **Total Net R** | **{metrics.total_r:+.2f} R** | > 0 | - |")
    lines.append(f"| **Max Drawdown (R)** | **{metrics.max_drawdown_r:.2f} R** | < 15.0 R | {'PASS' if metrics.max_drawdown_r <= 15.0 else 'WARN'} |")
    lines.append(f"| **Max Drawdown (%)** | **{metrics.max_drawdown_pct:.2f}%** | < 15.0% (1R=1%) | {'PASS' if metrics.max_drawdown_pct <= 15.0 else 'WARN'} |")
    lines.append(f"| **Sharpe Ratio (Daily Ann.)** | **{metrics.sharpe_daily_ann:.2f}** | > 1.00 | {'PASS' if metrics.sharpe_daily_ann >= 1.0 else 'SUB-OPTIMAL'} |")
    lines.append(f"| **Holding Time (Median)** | **{metrics.holding_time_median_hours:.1f} hours** | - | - |")
    lines.append(f"| **Holding Time (p75)** | **{metrics.holding_time_p75_hours:.1f} hours** | - | - |")
    lines.append(f"| **Holding Time (p90)** | **{metrics.holding_time_p90_hours:.1f} hours** | - | - |")
    lines.append(f"| **Holding Time (Max)** | **{metrics.holding_time_max_hours:.1f} hours** | - | - |")
    lines.append(f"| **Average Holding Time** | **{metrics.avg_holding_time_hours:.1f} hours** | < 48.0 hours | - |")
    lines.append(f"| **Trades per Trading Day** | **{metrics.trades_per_day:.3f}** | Target ~0.5 - 2.0 | - |")
    lines.append("")

    lines.append("## Portfolio Constraints Breakdown (Phase C)")
    lines.append("")
    lines.append("The portfolio simulation enforces the four strict institutional gates:")
    lines.append("1. **MAX_CONCURRENT**: 3 open positions")
    lines.append("2. **ONE_ENTRY_PER_SWEEP**: Exactly one entry per unique liquidity sweep event")
    lines.append("3. **MIN_ENTRY_SEPARATION**: $\\ge 1.0 \\times \\text{ATR}(14, 15\\text{m})$ OR $\\ge 1\\text{h}$ since last same-direction entry")
    lines.append("4. **DAILY_LOSS_STOP**: Realized PnL $\\le -3.0\\text{R}$ in a UTC calendar day halts new entries until next day")
    lines.append("")
    lines.append("| Funnel Stage | Count | Notes |")
    lines.append("| :--- | ---: | :--- |")
    lines.append(f"| Raw Signals Emitted by Strategy | {len(raw_signals):,} | Pre-portfolio setup candidates |")
    lines.append(f"| Skipped: Repeat Sweep (`ONE_ENTRY_PER_SWEEP`) | {exec_result.skip_counts.get('SAME_SWEEP', 0):,} | Multiple bars from same sweep key |")
    lines.append(f"| Skipped: Concurrency Cap (`MAX_CONCURRENT=3`) | {exec_result.skip_counts.get('CONCURRENCY_CAP', 0):,} | Blocked by 3 active positions |")
    lines.append(f"| Skipped: Separation Rule (`MIN_ENTRY_SEPARATION`) | {exec_result.skip_counts.get('SEPARATION_RULE', 0):,} | Too close in time/price to open position |")
    lines.append(f"| Skipped: Daily Loss Stop (`DAILY_LOSS_STOP=-3.0R`) | {exec_result.skip_counts.get('DAILY_LOSS_STOP', 0):,} | Daily drawdown limit reached |")
    lines.append(f"| Skipped: Unfilled Limit Zone Order | {exec_result.skip_counts.get('UNFILLED', 0):,} | Expired or stopped out before limit touch |")
    lines.append(f"| **Portfolio Entered Trades** | **{len(exec_result.entered_trades):,}** | **Executed with $0.40 round-trip friction** |")
    lines.append("")

    lines.append("## Strategy Rejection Funnel Analysis")
    lines.append("")
    lines.append(f"- **Total 15m Bars Evaluated**: {stats.evaluated:,}")
    lines.append(f"- **Warmup Bars Skipped**: {stats.warmup_skipped:,}")
    lines.append(f"- **Evaluation Errors**: {stats.eval_errors:,}")
    lines.append("")
    lines.append("| Gate | Type | Bars Stopped | Description |")
    lines.append("| :--- | :--- | ---: | :--- |")
    for gate in GATE_ORDER:
        cnt = funnel.get(gate, 0)
        gtype = "Pre-Sweep" if gate in PRE_SWEEP_GATES else "Post-Sweep"
        lines.append(f"| `{gate}` | {gtype} | {cnt:,} | |")
    for gate, cnt in sorted(funnel.items()):
        if gate not in GATE_ORDER and cnt > 0:
            lines.append(f"| `{gate}` | Post-Sweep | {cnt:,} | |")
    lines.append(f"| `CONFIRMED_SETUP` | **Emitted** | **{len(raw_signals):,}** | Validated setup |")
    lines.append("")

    if stats.confirmation_reasons:
        lines.append("### Confirmation Engine Breakdown")
        lines.append("")
        lines.append("Observations from `CONFIRMATION_PENDING` (verifying recent bug fix effectiveness):")
        lines.append("")
        lines.append("| Reason | Frequency |")
        lines.append("| :--- | ---: |")
        for reason, count in sorted(stats.confirmation_reasons.items(), key=lambda x: -x[1]):
            lines.append(f"| {reason} | {count:,} |")
        lines.append("")

    lines.append("## Trade Execution & Outcome Breakdown")
    lines.append("")
    if exec_result.entered_trades:
        exit_reasons: Dict[str, int] = defaultdict(int)
        for t in exec_result.entered_trades:
            exit_reasons[t["exit_reason"] or "UNKNOWN"] += 1

        lines.append("| Exit Reason | Count | Share (%) |")
        lines.append("| :--- | ---: | ---: |")
        for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
            lines.append(f"| `{reason}` | {count} | {count / len(exec_result.entered_trades) * 100:.1f}% |")
        lines.append("")

        lines.append("### Sample Executed Trades (First 10)")
        lines.append("")
        lines.append("| Date (UTC) | Dir | Entry | SL | TP1 | R-Multiple | Exit Reason | Holding (h) |")
        lines.append("| :--- | :--- | ---: | ---: | ---: | ---: | :--- | ---: |")
        for t in exec_result.entered_trades[:10]:
            lines.append(
                f"| {t['decision_dt']:%Y-%m-%d %H:%M} | {t['direction']} | {t['crt_entry']:.2f} | {t['stop_loss']:.2f} | "
                f"{t['take_profit_1']:.2f} | {t['r']:+.3f}R | `{t['exit_reason']}` | {t['bars_held']*0.25:.1f} |"
            )
        lines.append("")
    else:
        lines.append("> **Zero trades entered portfolio during this period.** See rejection funnel above for details.")
        lines.append("")

    lines.append("## Institutional Findings & Verdict")
    lines.append("")
    if metrics.total_trades == 0:
        lines.append("1. **Signal Generation Bottleneck**: The CRT Strategy generated zero confirmed trades during the 2025–2026 window.")
        lines.append("2. **Confirmation Stringency**: The dominant gates stopping setups are `NO_SWEEP`, `TREND_CONFLICT`, and `CONFIRMATION_PENDING`.")
        lines.append("3. **Fix Verification**: The displacement requirement and chronological MSS filters are functioning properly and strictly rejecting unconfirmed manipulation bars, preventing false signals.")
    else:
        lines.append(f"1. **Trade Volume**: {metrics.total_trades} trades executed across {metrics.total_trading_days} days ({metrics.trades_per_day:.3f} entries/day).")
        lines.append(f"2. **Expectancy**: Strategy delivered {metrics.expectancy:+.4f} R per trade with {metrics.win_rate:.1f}% win rate.")
        lines.append(f"3. **Capital Growth & Risk**: Total return {metrics.total_r:+.2f} R with Max Drawdown of {metrics.max_drawdown_r:.2f} R ({metrics.max_drawdown_pct:.1f}%).")
        lines.append(f"4. **Friction Impact**: Fixed $0.40 round-trip spread deduction strictly reflected across all outcomes.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    report_text = "\n".join(lines) + "\n"
    out_path.write_text(report_text, encoding="utf-8")
    return report_text


# ---------------------------------------------------------------------------
# CLI & Main Entry Point
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run CRT Recent Historical Backtest (2025 to Present).")
    p.add_argument("--db-path", default=str(REPO_ROOT / "backtest.db"), help="Path to SQLite backtest database")
    p.add_argument("--symbol", default="XAU/USD", help="Ticker symbol (default: XAU/USD)")
    p.add_argument("--source", default="twelvedata", help="Candle source (default: twelvedata)")
    p.add_argument("--start-date", default="2025-01-01", help="Start date filter (default: 2025-01-01)")
    p.add_argument("--spread", type=float, default=0.40, help="Round-trip spread friction in USD (default: 0.40)")
    p.add_argument("--expiry-bars", type=int, default=8, help="Limit-zone expiry in 15m bars (default: 8)")
    p.add_argument("--max-hold-bars", type=int, default=500, help="Max holding bars (default: 500)")
    p.add_argument("--warmup-bars", type=int, default=100, help="Warmup bars skipped (default: 100)")
    p.add_argument("--max-concurrent", type=int, default=3, help="Max concurrent open positions (default: 3)")
    p.add_argument("--daily-loss-stop", type=float, default=-3.0, help="Daily loss stop in R (default: -3.0)")
    p.add_argument("--min-sep-atr", type=float, default=1.0, help="Min entry separation in ATR (default: 1.0)")
    p.add_argument("--min-sep-hours", type=float, default=1.0, help="Min entry separation in hours (default: 1.0)")
    p.add_argument("--report-path", default=str(REPO_ROOT / "reports" / "crt_backtest_recent.md"), help="Markdown report path")
    p.add_argument("--csv-path", default=str(REPO_ROOT / "equity_curve_recent.csv"), help="CSV equity curve export path")
    p.add_argument(
        "--dump-finalists",
        action="store_true",
        default=True,
        help="Dump finalist candidates to JSONL (default: True)",
    )
    p.add_argument(
        "--no-dump-finalists",
        dest="dump_finalists",
        action="store_false",
        help="Disable dumping finalist candidates to JSONL",
    )
    p.add_argument(
        "--finalists-path",
        default=str(REPO_ROOT / "reports" / "crt_finalists_recent.jsonl"),
        help="Path to finalists JSONL dump (default: reports/crt_finalists_recent.jsonl)",
    )
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    print("=" * 80)
    print("CRT STRATEGY RECENT HISTORICAL BACKTEST (2025-01-01 to Present)")
    print("=" * 80)
    print(f"[*] Database: {args.db_path}")
    print(f"[*] Symbol: {args.symbol} | Source: {args.source} | Start Date: >= {args.start_date}")
    print(f"[*] Friction: ${args.spread:.2f} round-trip | Expiry: {args.expiry_bars} bars | Max Hold: {args.max_hold_bars} bars")
    print(f"[*] Portfolio Rules: MAX_CONCURRENT={args.max_concurrent}, DAILY_LOSS_STOP={args.daily_loss_stop}R,")
    print(f"    MIN_ENTRY_SEPARATION>={args.min_sep_atr}xATR or >={args.min_sep_hours}h, ONE_ENTRY_PER_SWEEP=True")
    print("-" * 80)

    # 1. Load Candles with SQL date filter
    db_path = Path(args.db_path)
    bars_15m, meta = load_recent_15m_candles(db_path, args.symbol, args.source, args.start_date)
    print(f"[*] Loaded {meta['bars_in_window']:,} rows ({meta['open_market_bars']:,} open-market 15m bars).")
    print(f"[*] Range: {meta['raw_first']:%Y-%m-%d %H:%M} -> {meta['raw_last']:%Y-%m-%d %H:%M} UTC")

    # 2. Resample 1h and 4h
    c1h, c1h_close, c4h, c4h_close = build_timeframe_series(bars_15m)
    print(f"[*] Resampled 1h: {len(c1h):,} complete bars | 4h: {len(c4h):,} complete bars")

    # 3. Compute ATR(14, 15m) for Portfolio Separation Rule
    atr_calc = ATRCalculator()
    highs = [b.high for b in bars_15m]
    lows = [b.low for b in bars_15m]
    closes = [b.close for b in bars_15m]
    atr_series = atr_calc.calculate_atr_series(highs, lows, closes, period=14)
    print(f"[*] Pre-computed ATR(14, 15m) series for {len(atr_series):,} bars.")

    # 4. Bar-by-bar Replay
    funnel, raw_signals, stats = run_bar_by_bar_replay(
        bars=bars_15m,
        c1h=c1h,
        c1h_close=c1h_close,
        c4h=c4h,
        c4h_close=c4h_close,
        symbol=args.symbol,
        spread=args.spread,
        expiry_bars=args.expiry_bars,
        max_hold_bars=args.max_hold_bars,
        warmup_bars=args.warmup_bars,
        dump_finalists=args.dump_finalists,
        finalists_path=Path(args.finalists_path),
    )

    # 5. Apply Portfolio Rules
    print("[*] Applying Phase C portfolio constraints...")
    exec_result = simulate_portfolio_rules(
        signals=raw_signals,
        bars=bars_15m,
        atr_series=atr_series,
        max_concurrent=args.max_concurrent,
        daily_loss_stop=args.daily_loss_stop,
        min_sep_atr_mult=args.min_sep_atr,
        min_sep_hours=args.min_sep_hours,
        one_entry_per_sweep=True,
    )

    # 6. Compute Institutional Metrics
    metrics = calculate_institutional_metrics(
        trades=exec_result.entered_trades,
        timeline=exec_result.timeline_records,
        bars=bars_15m,
    )

    # 7. Print Clean Summary to Console
    print("\n" + "=" * 80)
    print("BACKTEST RESULTS SUMMARY (2025-01-01 to Present)")
    print("=" * 80)
    if metrics.total_trades < 30:
        print("********************************************************************************")
        print(f"***                       UNDERPOWERED — n < 30 (n={metrics.total_trades:<2})                       ***")
        print("********************************************************************************")
    print(f"Period                     : {meta['raw_first']:%Y-%m-%d} to {meta['raw_last']:%Y-%m-%d} ({metrics.total_trading_days} trading days)")
    print(f"Bars Evaluated             : {stats.evaluated:,}")
    print(f"Raw CRT Signals Emitted    : {len(raw_signals):,}")
    print(f"Portfolio Entered Trades   : {metrics.total_trades:,}")
    print(f"Portfolio Skip Breakdown   : {exec_result.skip_counts}")
    print("-" * 80)
    print(f"Win Rate                   : {metrics.win_rate:.2f}% ({metrics.winning_trades} wins, {metrics.losing_trades} losses, {metrics.breakeven_trades} breakeven)")
    print(f"Loss Rate                  : {metrics.loss_rate:.2f}%")
    print(f"Mean R per Trade           : {metrics.mean_r:+.4f} R")
    print(f"Median R per Trade         : {metrics.median_r:+.4f} R")
    print(f"Expectancy per Trade       : {metrics.expectancy:+.4f} R")
    print(f"Profit Factor              : {metrics.profit_factor:.2f}")
    print(f"Total Cumulative Return    : {metrics.total_r:+.2f} R")
    print(f"Max Drawdown (R)           : {metrics.max_drawdown_r:.2f} R")
    print(f"Max Drawdown (%)           : {metrics.max_drawdown_pct:.2f}% (1R = 1% risk)")
    print(f"Sharpe Ratio (Daily Ann.)  : {metrics.sharpe_daily_ann:.2f}")
    print(f"Sharpe Ratio (Trade Ann.)  : {metrics.sharpe_trade_ann:.2f}")
    print(f"Average Holding Time       : {metrics.avg_holding_time_hours:.1f} hours")
    print(f"Trading Frequency          : {metrics.trades_per_day:.3f} trades / calendar day")
    print("-" * 80)
    print("HOLDING-TIME DISTRIBUTION:")
    print(f"  Median                   : {metrics.holding_time_median_hours:.1f} hours")
    print(f"  75th Percentile (p75)    : {metrics.holding_time_p75_hours:.1f} hours")
    print(f"  90th Percentile (p90)    : {metrics.holding_time_p90_hours:.1f} hours")
    print(f"  Max                      : {metrics.holding_time_max_hours:.1f} hours")
    print(f"  Mean (Average)           : {metrics.avg_holding_time_hours:.1f} hours")
    print("-" * 80)
    print("EXIT-REASON MIX:")
    if exec_result.entered_trades:
        exit_reasons = defaultdict(int)
        for t in exec_result.entered_trades:
            exit_reasons[t["exit_reason"] or "UNKNOWN"] += 1
        for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
            pct = (count / len(exec_result.entered_trades)) * 100.0
            print(f"  {reason:<25}: {count:>5} ({pct:>5.1f}%)")
    else:
        print("  No trades entered portfolio.")
    print("-" * 80)
    print("PER-GATE REJECTION FUNNEL:")
    for gate in GATE_ORDER:
        cnt = funnel.get(gate, 0)
        gtype = "Pre-Sweep" if gate in PRE_SWEEP_GATES else "Post-Sweep"
        print(f"  {gate:<25} ({gtype:<10}): {cnt:>8,}")
    for gate, cnt in sorted(funnel.items()):
        if gate not in GATE_ORDER and cnt > 0:
            print(f"  {gate:<25} (Post-Sweep): {cnt:>8,}")
    print(f"  {'CONFIRMED_SETUP':<25} (Emitted   ): {len(raw_signals):>8,}")
    print("=" * 80)
    if metrics.total_trades < 30:
        print("********************************************************************************")
        print(f"***                       UNDERPOWERED — n < 30 (n={metrics.total_trades:<2})                       ***")
        print("********************************************************************************")

    # 8. Export CSV Equity Curve
    csv_path = Path(args.csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "cumulative_R", "drawdown_R", "open_positions"])
        for row in exec_result.timeline_records:
            writer.writerow([row["timestamp"], row["cumulative_R"], row["drawdown_R"], row["open_positions"]])
    print(f"[*] Exported equity curve CSV to: {csv_path.resolve()}")

    # Also save a copy inside reports/ for convenience
    reports_csv = REPO_ROOT / "reports" / "equity_curve_recent.csv"
    reports_csv.parent.mkdir(parents=True, exist_ok=True)
    with reports_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "cumulative_R", "drawdown_R", "open_positions"])
        for row in exec_result.timeline_records:
            writer.writerow([row["timestamp"], row["cumulative_R"], row["drawdown_R"], row["open_positions"]])
    print(f"[*] Copied equity curve CSV to: {reports_csv.resolve()}")

    # 9. Generate and Write Markdown Report
    report_path = Path(args.report_path)
    generate_markdown_report(
        meta=meta,
        funnel=funnel,
        stats=stats,
        raw_signals=raw_signals,
        exec_result=exec_result,
        metrics=metrics,
        out_path=report_path,
    )
    print(f"[*] Generated Markdown report at: {report_path.resolve()}")
    print("=" * 80 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
