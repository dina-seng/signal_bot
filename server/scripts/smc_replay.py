"""Bar-by-bar SMC replay with zero lookahead through the production analysis path.

Standalone CLI diagnostic. It is NOT imported by the test suite and never writes
to the application database: the SQLite connection is opened read-only and
``SMCStrategy`` has no dedup / persistence path at all.

What it does
------------
1. Loads XAU/USD 15m candles from a SQLite database (Twelve Data rows only) and
   applies the production market-calendar filter.
2. Resamples 1h and 4h with the production ``resample_ohlc`` (incomplete buckets
   omitted).
3. Walks the 15m series forward. At each closed 15m bar it builds the candle sets
   that were *knowable at that instant* using the timestamp rule
   (``bar.timestamp + timeframe_delta <= decision_time``) and runs the production
   ``ConfluenceEngine._prepare_market_data`` + ``SMCStrategy.analyze`` path.
4. Because ``SMCStrategy`` returns no price levels (it delegates geometry), the
   stop/targets are produced with the production ``RiskManager`` exactly as
   ``ConfluenceEngine._build_signal_response`` does for a market entry.
5. Records, for every evaluated bar, the derived rejection gate, then simulates
   the accepted trade and a counterfactual trade for every near-miss rejection
   with the shared CRT ``simulate_outcome`` friction model.

Design notes / deliberate deviations from ``crt_replay.py``
-----------------------------------------------------------
- ``SMCStrategy`` has no ``enable_dedup`` argument and no sweep / setup metadata.
  Gate names are therefore **derived** here from ``ScoreBreakdown`` +
  ``metadata`` + reasons; they are not emitted by the strategy. The derivation is
  documented in ``_classify_smc``.
- Evaluation repeats on every 15m bar (the LTF confirmation filter reads the last
  10 closed 15m bars, so it genuinely changes per bar). Aggregates therefore
  de-duplicate by ``opportunity_key`` = (symbol, timeframe, direction, last closed
  1h candle) so one 1h opportunity is not counted four times.
- Friction: a single round-trip cost in price units is charged per completed
  trade by the shared ``simulate_outcome``.

Live parameters are read directly from ``smc_strategy.py`` and ``evaluators.py``
(DEFAULT_MIN_SCORE, LTF_UNCONFIRMED_PENALTY, DIRECTIONAL_CONFLICT_PENALTY).

Usage
-----
    cd server
    python scripts/smc_replay.py --max-chunks 3
    python scripts/smc_replay.py --full-range --no-resume
"""

from __future__ import annotations

import argparse
import json
import math
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
SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from app.schemas.candle import CandleCreate  # noqa: E402
from app.schemas.signal import SignalDirection  # noqa: E402
from app.services.signals.confluence_engine import ConfluenceEngine  # noqa: E402
from app.services.signals.evaluators import DIRECTIONAL_CONFLICT_PENALTY  # noqa: E402
from app.services.signals.risk_manager import RiskManager  # noqa: E402
from app.services.strategies.smc_strategy import (  # noqa: E402
    DEFAULT_MIN_SCORE,
    LTF_UNCONFIRMED_PENALTY,
    SMCStrategy,
)

# Reuse the proven CRT harness primitives. Importing does not modify the module.
from crt_replay import (  # noqa: E402
    SignalRecord,
    _bootstrap_ci,
    _parse_start_date,
    _parse_ts,
    _signal_to_dict,
    _write_csv,
    build_timeframe_series,
    load_full_15m_candles,
    month_keys,
    simulate_outcome,
    trade_metrics,
    walk_forward_bounds,
)

def split_of(ts: datetime, bounds: Tuple[datetime, datetime]) -> str:
    b1, b2 = bounds
    if ts <= b1:
        return "calibration"
    if ts < b2:
        return "validation"
    return "test"

TF_15M = timedelta(minutes=15)
PRIMARY_TIMEFRAME = "1h"

# Production evaluator floors, mirrored read-only from ``evaluators.py``:
#   Price Action floor  -> evaluators.py:526  (raw_pa < 10.0)
#   Confluence floor    -> evaluators.py:544  (struct + liq < 20.0)
PA_FLOOR = 10.0
CONFLUENCE_FLOOR = 20.0

CONFIRMED_STATE = "CONFIRMED_SETUP"
NO_SETUP_STATE = "NO_SETUP"

# Counterfactual near-miss windows (documented, not tuned).
NEAR_SCORE_POINTS = 5.0      # SCORE_BELOW_THRESHOLD within 5 pts of the floor
NEAR_PA_POINTS = 2.0         # PA floor missed by < 2 pts
NEAR_CONFLUENCE_POINTS = 5.0  # Confluence floor missed by < 5 pts


@dataclass
class SmcRecord:
    """One evaluated 15m decision bar."""

    decision_time: str
    month: str
    split: str
    index: int
    gate: str
    setup_state: str
    direction: str
    score: float
    pre_ltf_score: float
    ltf_penalized: bool
    opportunity_key: str
    accepted: bool
    pa_score: float
    struct_liq_score: float
    is_qualified_pre_ltf: bool
    detail: str = ""
    accepted_trade: Optional[Dict[str, Any]] = None
    cf_candidate: bool = False
    counterfactual_trade: Optional[Dict[str, Any]] = None
    cf_error: str = ""
    ema_trend: str = ""


@dataclass
class SmcStats:
    evaluated: int = 0
    warmup_skipped: int = 0
    insufficient_data: int = 0
    eval_errors: int = 0
    error_samples: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Risk geometry (mirrors ConfluenceEngine._build_signal_response market path)
# ---------------------------------------------------------------------------
def build_market_trade(
    risk_manager: RiskManager,
    symbol: str,
    direction: str,
    entry_price: float,
    atr: float,
    key_support: Optional[float],
    key_resistance: Optional[float],
    decision_time: datetime,
    opportunity_key: str,
    score: float,
) -> Tuple[Optional[SignalRecord], str]:
    """Build an SMC market-entry trade using the production RiskManager."""
    if entry_price is None or not (entry_price > 0):
        return None, "NO_ENTRY_PRICE"
    sd = SignalDirection.BUY if direction == "BUY" else SignalDirection.SELL
    try:
        params = risk_manager.calculate_trade_risk(
            symbol=symbol,
            direction=sd,
            entry_price=entry_price,
            atr_value=atr if atr and atr > 0 else None,
            key_support_low=key_support,
            key_resistance_high=key_resistance,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return None, f"RISK_ERROR:{type(exc).__name__}"

    entry = float(params.entry_price)
    sl = float(params.stop_loss)
    tp1 = float(params.take_profit_1)
    tp2 = float(params.take_profit_2)
    risk = abs(entry - sl)
    if risk <= 0 or tp1 <= 0 or tp2 <= 0:
        return None, "INVALID_RISK_GEOMETRY"
    if (direction == "BUY" and sl >= entry) or (direction == "SELL" and sl <= entry):
        return None, "INVALID_RISK_GEOMETRY"

    return (
        SignalRecord(
            signal_time=decision_time,
            direction=direction,
            tier=None,
            session=None,
            entry_mode="market",
            crt_entry=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            risk_price=risk,
            rr_planned=params.risk_reward_tp1,
            score=score,
            sweep_key=opportunity_key,
        ),
        "",
    )


def _simulate(
    rec: SignalRecord,
    bars: Sequence[CandleCreate],
    index: int,
    spread: float,
    expiry_bars: int,
    max_hold_bars: int,
) -> SignalRecord:
    simulate_outcome(
        rec,
        bars=bars,
        signal_index=index,
        spread=spread,
        expiry_bars=expiry_bars,
        max_hold_bars=max_hold_bars,
    )
    return rec


# ---------------------------------------------------------------------------
# Gate derivation
# ---------------------------------------------------------------------------
def _classify_smc(
    result: Any, meta: Dict[str, Any], threshold: float
) -> Tuple[str, str, float, float, bool, float, float, bool]:
    """Derive the SMC rejection gate from the production result.

    ``SMCStrategy`` does not emit a gate. The pipeline (``evaluators.py``) is:
        fatal conflict -> PA floor -> confluence floor -> score floor -> LTF penalty
    ``ScoreBreakdown.is_qualified`` is computed by ``ConsensusFilter.synthesize``
    BEFORE the LTF penalty (-5 pts), so it exactly identifies the LTF-only failures.
    """
    buy_final = float(meta.get("buy_score") or 0.0)
    sell_final = float(meta.get("sell_score") or 0.0)
    buy_fatal = bool(meta.get("buy_fatal"))
    sell_fatal = bool(meta.get("sell_fatal"))

    if result.direction in (SignalDirection.BUY, SignalDirection.SELL):
        bd = result.score_breakdown
        direction = result.direction.value
        return (
            CONFIRMED_STATE,
            direction,
            float(result.score),
            float(bd.total_score),
            abs(float(result.score) - float(bd.total_score)) > 1e-9,
            float(bd.price_action_score),
            float(bd.structure_score) + float(bd.liquidity_score),
            bool(bd.is_qualified),
        )

    chosen_buy = buy_final >= sell_final
    direction = "BUY" if chosen_buy else "SELL"
    chosen_final = buy_final if chosen_buy else sell_final
    chosen_fatal = buy_fatal if chosen_buy else sell_fatal

    bd = result.score_breakdown
    pa = float(bd.price_action_score)
    struct_liq = float(bd.structure_score) + float(bd.liquidity_score)
    pre_ltf = float(bd.total_score)
    ltf_penalized = abs(chosen_final - pre_ltf) > 1e-9

    if chosen_fatal:
        gate = "FATAL_CONFLICT"
    elif pa < PA_FLOOR:
        gate = "PA_FLOOR"
    elif struct_liq < CONFLUENCE_FLOOR:
        gate = "CONFLUENCE_FLOOR"
    elif pre_ltf < threshold:
        gate = "SCORE_BELOW_THRESHOLD"
    elif bool(bd.is_qualified) and ltf_penalized:
        gate = "LTF_PENALTY"
    else:
        gate = "OTHER_WAIT"

    return (
        gate,
        direction,
        chosen_final,
        pre_ltf,
        ltf_penalized,
        pa,
        struct_liq,
        bool(bd.is_qualified),
    )


def _is_near_miss(
    gate: str, pre_ltf: float, pa: float, struct_liq: float, threshold: float
) -> bool:
    """Near-miss set for the counterfactual (documented, not tuned)."""
    if gate == "LTF_PENALTY":
        return True
    if gate == "FATAL_CONFLICT":
        return True
    if gate == "SCORE_BELOW_THRESHOLD":
        return pre_ltf >= threshold - NEAR_SCORE_POINTS
    if gate == "PA_FLOOR":
        return pa >= PA_FLOOR - NEAR_PA_POINTS
    if gate == "CONFLUENCE_FLOOR":
        return struct_liq >= CONFLUENCE_FLOOR - NEAR_CONFLUENCE_POINTS
    return False


def _opportunity_key(symbol: str, timeframe: str, direction: str, primary: Sequence[Any]) -> str:
    """Stable key for one primary-candle opportunity (de-duplicates 15m repeats)."""
    bucket = primary[-1].timestamp.isoformat() if primary else "0"
    return f"{symbol}_{timeframe}_{direction}_{bucket}"


# ---------------------------------------------------------------------------
# Core replay chunk
# ---------------------------------------------------------------------------
def replay_chunk(
    bars: Sequence[CandleCreate],
    c1h: Sequence[CandleCreate],
    c1h_close: Sequence[datetime],
    c4h: Sequence[CandleCreate],
    c4h_close: Sequence[datetime],
    indices: Sequence[int],
    symbol: str,
    spread: float,
    expiry_bars: int,
    max_hold_bars: int,
    warmup_bars: int,
    bounds: Tuple[datetime, datetime],
    month: str,
    regime_filter: bool = False,
) -> Tuple[List[SmcRecord], SmcStats]:
    """Evaluate only ``indices`` but with the full precomputed series as lookback."""
    smc = SMCStrategy()
    engine = ConfluenceEngine()
    risk_manager = RiskManager()
    threshold = smc._min_score_threshold
    bar_close = [b.timestamp + TF_15M for b in bars]
    records: List[SmcRecord] = []
    stats = SmcStats()

    for i in indices:
        if i < warmup_bars:
            stats.warmup_skipped += 1
            continue
        decision_time = bar_close[i]
        n15 = bisect_right(bar_close, decision_time)
        n1h = bisect_right(c1h_close, decision_time)
        n4h = bisect_right(c4h_close, decision_time)
        c15 = list(bars[max(0, n15 - 200):n15])
        primary = list(c1h[max(0, n1h - 200):n1h])
        ht_c4h = list(c4h[max(0, n4h - 100):n4h])
        if len(primary) < 20 or len(c15) < 50:
            stats.insufficient_data += 1
            continue
        try:
            structure, indicators, mtf = engine._prepare_market_data(
                symbol=symbol,
                timeframe=PRIMARY_TIMEFRAME,
                c_prim=primary,
                c_4h=ht_c4h,
                c_15m=c15,
            )
            result = smc.analyze(
                symbol=symbol,
                timeframe=PRIMARY_TIMEFRAME,
                candles=primary,
                indicators=indicators,
                structure=structure,
                mtf=mtf,
                candles_15m=c15,
            )
        except Exception as exc:  # pragma: no cover - defensive
            stats.eval_errors += 1
            if len(stats.error_samples) < 5:
                stats.error_samples.append(f"{decision_time.isoformat()}: {type(exc).__name__}: {exc}")
            records.append(
                SmcRecord(
                    decision_time=decision_time.isoformat(),
                    month=month,
                    split=split_of(decision_time, bounds),
                    index=i,
                    gate="EVAL_ERROR",
                    setup_state=NO_SETUP_STATE,
                    direction="WAIT",
                    score=0.0,
                    pre_ltf_score=0.0,
                    ltf_penalized=False,
                    opportunity_key="",
                    accepted=False,
                    pa_score=0.0,
                    struct_liq_score=0.0,
                    is_qualified_pre_ltf=False,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        meta = result.metadata or {}
        (
            gate,
            direction,
            score,
            pre_ltf,
            ltf_penalized,
            pa,
            struct_liq,
            is_qualified_pre_ltf,
        ) = _classify_smc(result, meta, threshold)

        accepted = gate == CONFIRMED_STATE
        opp_key = _opportunity_key(symbol, PRIMARY_TIMEFRAME, direction, primary)
        detail = ""

        ema_snapshot = getattr(indicators, "ema", None)
        ema_trend = getattr(ema_snapshot, "ema_trend", "NEUTRAL") if ema_snapshot else "NEUTRAL"

        if regime_filter and accepted:
            if direction == "BUY":
                regime_ok = (ema_trend == "BULLISH_STACK")
            elif direction == "SELL":
                regime_ok = (ema_trend == "BEARISH_STACK")
            else:
                regime_ok = False

            if not regime_ok:
                accepted = False
                gate = "REGIME_FILTER_REJECT"
                detail = f"REGIME_FILTER_REJECT: {direction} requires {'BULLISH_STACK' if direction == 'BUY' else 'BEARISH_STACK'} but got {ema_trend}"

        atr_obj = getattr(indicators, "atr", None)
        atr = float(getattr(atr_obj, "atr_value", 0.0) or 0.0)
        current_price = float(getattr(indicators, "current_price", 0.0) or 0.0)
        base = getattr(structure, "base_structure", None)
        key_support = getattr(base, "key_support", None)
        key_resistance = getattr(base, "key_resistance", None)

        if gate != CONFIRMED_STATE and not detail:
            for reason in result.reasons:
                text = str(reason)
                if "LTF" in text or "Floor" in text or "Confluence" in text or "Conflict" in text:
                    detail = text
                    break

        rec = SmcRecord(
            decision_time=decision_time.isoformat(),
            month=month,
            split=split_of(decision_time, bounds),
            index=i,
            gate=gate,
            setup_state=CONFIRMED_STATE if accepted else NO_SETUP_STATE,
            direction=direction,
            score=float(score),
            pre_ltf_score=float(pre_ltf),
            ltf_penalized=bool(ltf_penalized),
            opportunity_key=opp_key,
            accepted=accepted,
            pa_score=float(pa),
            struct_liq_score=float(struct_liq),
            is_qualified_pre_ltf=bool(is_qualified_pre_ltf),
            detail=detail,
            ema_trend=ema_trend,
        )

        if accepted:
            trade, err = build_market_trade(
                risk_manager,
                symbol,
                direction,
                current_price,
                atr,
                key_support,
                key_resistance,
                decision_time,
                opp_key,
                float(score),
            )
            if trade is not None:
                _simulate(trade, bars, i, spread, expiry_bars, max_hold_bars)
                rec.accepted_trade = _signal_to_dict(trade)
            else:
                rec.cf_error = f"ACCEPTED_GEOMETRY:{err}"
        elif _is_near_miss(gate, pre_ltf, pa, struct_liq, threshold):
            rec.cf_candidate = True
            trade, err = build_market_trade(
                risk_manager,
                symbol,
                direction,
                current_price,
                atr,
                key_support,
                key_resistance,
                decision_time,
                opp_key,
                float(score),
            )
            if trade is not None:
                _simulate(trade, bars, i, spread, expiry_bars, max_hold_bars)
                rec.counterfactual_trade = _signal_to_dict(trade)
            else:
                rec.cf_error = err

        records.append(rec)
    return records, stats


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------
def _ckpt_path(ckpt_dir: Path, month: str) -> Path:
    return ckpt_dir / f"{month}.json"


def save_checkpoint(ckpt_dir: Path, month: str, records: Sequence[SmcRecord]) -> None:
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    path = _ckpt_path(ckpt_dir, month)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"month": month, "records": [asdict(r) for r in records]}),
        encoding="utf-8",
    )
    tmp.replace(path)


def load_checkpoint(ckpt_dir: Path, month: str) -> List[SmcRecord]:
    data = json.loads(_ckpt_path(ckpt_dir, month).read_text(encoding="utf-8"))
    return [SmcRecord(**d) for d in data["records"]]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def _dedupe(trades: Sequence[Dict[str, Any]], key: str = "sweep_key") -> List[Dict[str, Any]]:
    """Keep the first trade per opportunity key (records are time-ordered)."""
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for t in trades:
        k = str(t.get(key) or "")
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def _metrics(trades: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    m = dict(trade_metrics(trades))
    filled = [t for t in trades if t.get("filled") and t.get("r_multiple") is not None]
    rs = [float(t["r_multiple"]) for t in filled]
    if rs:
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        gross_gain = sum(wins)
        gross_loss = abs(sum(losses))
        m["profit_factor"] = (gross_gain / gross_loss) if gross_loss > 0 else (
            math.inf if gross_gain > 0 else 0.0
        )
        m["total_r"] = sum(rs)
        ordered = sorted(filled, key=lambda t: str(t.get("signal_time") or ""))
        equity = peak = max_dd = 0.0
        for t in ordered:
            equity += float(t["r_multiple"])
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        m["max_drawdown_r"] = max_dd
        lo, hi = _bootstrap_ci(rs)
        m["ci_lower"], m["ci_upper"] = lo, hi
    else:
        m["profit_factor"] = None
        m["total_r"] = None
        m["max_drawdown_r"] = None
        m["ci_lower"], m["ci_upper"] = None, None
    return m


def build_report(
    meta: Dict[str, Any],
    records: Sequence[SmcRecord],
    bounds: Tuple[datetime, datetime],
    args: argparse.Namespace,
    gap_stats: SmcStats,
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    funnel: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(
        lambda: {"bars": 0, "BUY": 0, "SELL": 0, "opps": set()}
    )
    accepted_by_split: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    cf_trades: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    cf_candidate_opps: Dict[Tuple[str, str], set] = defaultdict(set)
    cf_candidate_bars: Dict[Tuple[str, str], int] = defaultdict(int)

    ltf_applied: Dict[str, int] = defaultdict(int)
    ltf_would_qualify: Dict[str, int] = defaultdict(int)

    for r in records:
        key = (r.split, r.gate)
        bucket = funnel[key]
        bucket["bars"] += 1
        if r.direction in ("BUY", "SELL"):
            bucket[r.direction] += 1
        if r.opportunity_key:
            bucket["opps"].add(r.opportunity_key)

        if r.ltf_penalized:
            ltf_applied[r.split] += 1
            if r.is_qualified_pre_ltf:
                ltf_would_qualify[r.split] += 1

        if r.accepted and r.accepted_trade:
            accepted_by_split[r.split].append(r.accepted_trade)
        elif r.cf_candidate:
            cf_candidate_bars[key] += 1
            if r.opportunity_key:
                cf_candidate_opps[key].add(r.opportunity_key)
            if r.counterfactual_trade:
                cf_trades[key].append(r.counterfactual_trade)

    funnel_rows: List[Dict[str, Any]] = []
    for (split, gate), d in sorted(funnel.items()):
        funnel_rows.append(
            {
                "split": split,
                "gate": gate,
                "bars": d["bars"],
                "distinct_opportunities": len(d["opps"]),
                "buy_bars": d["BUY"],
                "sell_bars": d["SELL"],
            }
        )

    cf_rows: List[Dict[str, Any]] = []
    for (split, gate) in cf_candidate_bars:
        deduped = _dedupe(cf_trades.get((split, gate), []))
        m = _metrics(deduped)
        m.update(
            {
                "split": split,
                "rejection_reason": gate,
                "candidate_bars": cf_candidate_bars[(split, gate)],
                "distinct_opportunities": len(cf_candidate_opps[(split, gate)]),
                "flagged_lt30": m["n_filled"] < 30,
            }
        )
        cf_rows.append(m)

    for split, trades in sorted(accepted_by_split.items()):
        deduped = _dedupe(trades)
        m = _metrics(deduped)
        m.update(
            {
                "split": split,
                "rejection_reason": "ACCEPTED (CONFIRMED_SETUP)",
                "candidate_bars": len(trades),
                "distinct_opportunities": len(deduped),
                "flagged_lt30": m["n_filled"] < 30,
            }
        )
        cf_rows.append(m)

    cf_rows.sort(key=lambda r: (r["split"], r["rejection_reason"]))

    def fmt(v: Any, digits: int = 4) -> str:
        if v is None:
            return "n/a"
        if isinstance(v, float):
            if math.isinf(v):
                return "inf"
            return f"{v:.{digits}f}"
        return str(v)

    def warn(n: int) -> str:
        return "  n<30" if n < 30 else ""

    lines: List[str] = []
    lines.append("# SMC Replay — Full-Range Rejection Funnel & Counterfactual")
    lines.append("")
    lines.append(
        "Production path: `resample_ohlc` → `ConfluenceEngine._prepare_market_data` → "
        "`SMCStrategy.analyze` → `RiskManager.calculate_trade_risk` (market geometry) → "
        "shared `simulate_outcome` fill/TP1/TP2 friction model. "
        "`SMCStrategy` emits no gate or price levels; gates are derived from "
        "`ScoreBreakdown` + `metadata` in `_classify_smc()`."
    )
    lines.append("")
    lines.append("## 1. Data and walk-forward split")
    lines.append("")
    lines.append("| Item | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| Database | `{meta['db_path']}` |")
    lines.append(f"| Raw rows / duplicates dropped | {meta['raw_rows']:,} / {meta['duplicates_dropped']:,} |")
    lines.append(f"| Full range | {meta['raw_first']:%Y-%m-%d %H:%M} → {meta['raw_last']:%Y-%m-%d %H:%M} UTC |")
    if meta.get("start_date"):
        lines.append(f"| Replay start date | {meta['start_date']} UTC |")
        lines.append(f"| Warm-up bars available | {meta.get('warmup_bars_count', 0):,} |")
    lines.append(f"| Open-market bars available | {meta['open_market_bars']:,} |")
    lines.append(f"| Bar records captured | {len(records):,} |")
    lines.append(f"| Warmup / insufficient-data skips | {gap_stats.warmup_skipped:,} / {gap_stats.insufficient_data:,} |")
    lines.append(f"| Evaluation errors | {gap_stats.eval_errors:,} |")
    lines.append(f"| Calibration boundary (60%) | {bounds[0]:%Y-%m-%d %H:%M} UTC |")
    lines.append(f"| Validation boundary (80%) | {bounds[1]:%Y-%m-%d %H:%M} UTC |")
    lines.append(f"| Round-trip friction | \\${args.spread:.2f} per completed trade |")
    lines.append("")
    lines.append(
        "Split windows: calibration = earliest 60% (observation only), validation = next 20%, "
        "test = last 20%. NOTE: Validation and test splits were previously observed during earlier "
        "exploratory runs (commits 4424a64, 5b88873, 2db6eb1) and are no longer clean out-of-sample data."
    )
    lines.append("")
    lines.append("### Live SMC parameters")
    lines.append("")
    lines.append("| Parameter | Value | Location in code |")
    lines.append("| :--- | :--- | :--- |")
    lines.append(f"| `DEFAULT_MIN_SCORE` | {DEFAULT_MIN_SCORE:.1f} | `server/app/services/strategies/smc_strategy.py:30` |")
    lines.append(f"| `LTF_UNCONFIRMED_PENALTY` | {LTF_UNCONFIRMED_PENALTY:.1f} pts | `server/app/services/strategies/smc_strategy.py:34` |")
    lines.append(f"| `DIRECTIONAL_CONFLICT_PENALTY` | {DIRECTIONAL_CONFLICT_PENALTY:.1f} pts | `server/app/services/signals/evaluators.py:31` |")
    lines.append(f"| `PA_FLOOR` | {PA_FLOOR:.1f} pts | `server/app/services/signals/evaluators.py:526` |")
    lines.append(f"| `CONFLUENCE_FLOOR` | {CONFLUENCE_FLOOR:.1f} pts | `server/app/services/signals/evaluators.py:544` |")
    lines.append("")
    lines.append("### Parameter history")
    lines.append("")
    lines.append("| Change | Commit | Date | Split basis cited | Evidence / Citation |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")
    lines.append("| Initial 3-pillar SMC migration from ConfluenceEngine (`MIN_SETUP_SCORE=75`, BUY LTF `* 0.9`, SELL LTF `* 0.3`, 2+ conflict hard veto) | `19d283b` | 2026-11-17 | UNVERIFIED | Commit message: `feat: add SMC strategy implementation migrated from ConfluenceEngine` |")
    lines.append("| BUY LTF multiplier updated: `* 0.9` -> `* 0.5` | `4424a64` | 2026-11-17 | UNVERIFIED | Commit message: `feat: add smc strategy replay reports and checkpoints` |")
    lines.append("| SELL LTF multiplier updated: `* 0.3` -> `* 0.5` | `5b88873` | 2026-11-17 | UNVERIFIED | Commit message: `feat: add smc replay extended reports and update smc strategy` |")
    lines.append("| Directional conflict hard veto replaced by flat -15 deduction (`DIRECTIONAL_CONFLICT_PENALTY = 15.0`) | `2db6eb1` | 2026-11-17 | Calibration | Code comment `server/app/services/signals/evaluators.py:560-569`: Counterfactual replay on calibration split (+0.15R expectancy over 3,496 opps) |")
    lines.append("| LTF unconfirmed penalty replaced 0.5x slash with flat deduction (`LTF_UNCONFIRMED_PENALTY = 5.0`) | `2db6eb1` | 2026-11-17 | UNVERIFIED | Code comment `server/app/services/strategies/smc_strategy.py:32-34`: replaces 0.5x slash; no split cited |")
    lines.append("| Minimum qualification score lowered from 75 to 60 (`DEFAULT_MIN_SCORE = 60.0`) | `2db6eb1` | 2026-11-17 | UNVERIFIED | Code comment `server/app/services/strategies/smc_strategy.py:28-30`: widens band to B-tier; no split cited |")
    lines.append("")

    lines.append("## 2. Rejection funnel — bars, opportunities and direction")
    lines.append("")
    lines.append(
        "Counts are bar-evaluations (first-failure-wins). All 15m bars inside the same closed "
        "1h candle share one `opportunity_key`, so `distinct_opportunities` removes the 15m repeat."
    )
    lines.append("")
    lines.append("| Split | Gate | Bars | BUY bars | SELL bars | Distinct opportunities |")
    lines.append("| :--- | :--- | ---: | ---: | ---: | ---: |")
    for row in funnel_rows:
        lines.append(
            f"| {row['split']} | `{row['gate']}` | {row['bars']:,} | "
            f"{row['buy_bars']:,} | {row['sell_bars']:,} | {row['distinct_opportunities']:,} |"
        )
    lines.append("")

    lines.append("## 3. Counterfactual vs accepted trades")
    lines.append("")
    lines.append(
        "For near-miss rejections the trade is re-priced as if the gate had passed, using the "
        "same `RiskManager` geometry and the same `simulate_outcome` friction. `n` counts "
        "de-duplicated trades with valid geometry; `filled` is the subset that filled. "
        "Expectancy = average R per filled trade. Near-miss set: LTF penalty (all), fatal "
        "conflict (all), score within 5 pts, PA floor within 2 pts, confluence floor within 5 pts."
    )
    lines.append("")
    lines.append(
        "| Split | Rejection reason | Candidate bars | Opportunities | n | Filled | No fill | Win rate | Avg R | Expectancy | Flag |"
    )
    lines.append("| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |")
    for row in cf_rows:
        lines.append(
            f"| {row['split']} | `{row['rejection_reason']}` | {row['candidate_bars']:,} | "
            f"{row['distinct_opportunities']:,} | {row['n_candidates']:,} | {row['n_filled']:,} | "
            f"{row['n_no_fill']:,} | {fmt(row['win_rate'], 2)}% | {fmt(row['avg_r'])} | "
            f"{fmt(row['expectancy'])} | {warn(row['n_filled'])} |"
        )
    lines.append("")
    small = sum(1 for row in cf_rows if row["flagged_lt30"])
    lines.append(
        f"> {small} of {len(cf_rows)} groups have fewer than 30 filled trades (flagged above). "
        "Treat every metric in those groups as descriptive only."
    )
    lines.append("")

    lines.append(f"## 4. LTF penalty (flat -{LTF_UNCONFIRMED_PENALTY:.1f} pts)")
    lines.append("")
    lines.append("| Split | Bars with LTF penalty applied | Bars that passed all pre-LTF gates |")
    lines.append("| :--- | ---: | ---: |")
    for split in ("calibration", "validation", "test"):
        lines.append(
            f"| {split} | {ltf_applied.get(split, 0):,} | {ltf_would_qualify.get(split, 0):,} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        f"Live SMC parameters: `DEFAULT_MIN_SCORE={DEFAULT_MIN_SCORE:.1f}`, "
        f"`LTF_UNCONFIRMED_PENALTY={LTF_UNCONFIRMED_PENALTY:.1f}`, "
        f"`DIRECTIONAL_CONFLICT_PENALTY={DIRECTIONAL_CONFLICT_PENALTY:.1f}`. "
        "As documented in the Parameter history table, these parameters were introduced in "
        "commit 2db6eb1. Prior runs observed validation and test sets; validation and test "
        "are no longer clean out-of-sample data."
    )
    return "\n".join(lines), funnel_rows, cf_rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Replay SMC bar-by-bar with zero lookahead and simulate outcomes.",
    )
    p.add_argument("--db-path", default=str(REPO_ROOT / "backtest.db"))
    p.add_argument("--symbol", default="XAU/USD")
    p.add_argument("--source", default="twelvedata")
    p.add_argument(
        "--spread",
        type=float,
        default=0.40,
        help="Round-trip spread/slippage in USD (default: 0.40 per the stated friction model)",
    )
    p.add_argument("--expiry-bars", type=int, default=8,
                   help="Informational for SMC (market entry); kept for harness parity")
    p.add_argument("--max-hold-bars", type=int, default=500)
    p.add_argument("--warmup-bars", type=int, default=100)
    p.add_argument("--start-date", default=None,
                   help="Optional start date (YYYY-MM-DD); chunks ending before this and bars before this are skipped")
    p.add_argument("--end-date", default=None,
                   help="Optional end date (YYYY-MM-DD or ISO timestamp); chunks starting after this and bars after this are skipped")
    p.add_argument("--calibration-only", action="store_true", default=False,
                   help="Run replay strictly on the CALIBRATION window (bars before 2025-05-21 08:15 UTC)")
    p.add_argument("--regime-filter", action="store_true", default=False,
                   help="Filter out counter-trend setups using 1H EMA stack (BUY requires BULLISH_STACK, SELL requires BEARISH_STACK)")
    p.add_argument("--baseline-ckpt-dir", default=str(REPO_ROOT / "reports" / "smc_replay_extended" / "checkpoints"),
                   help="Directory of baseline checkpoints to derive regime-filtered records from when available")
    p.add_argument("--full-range", action="store_true",
                   help="Process the entire DB range in monthly chunks")
    p.add_argument("--checkpoint-dir", default=None,
                   help="Directory for per-month checkpoints (default: <out-dir>/checkpoints)")
    p.add_argument("--no-resume", action="store_true")
    p.add_argument("--max-chunks", type=int, default=None,
                   help="Debug only: stop after this many monthly chunks")
    p.add_argument(
        "--out-dir",
        default=str(REPO_ROOT / "reports" / "smc_replay_extended"),
    )
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.regime_filter and args.out_dir == str(REPO_ROOT / "reports" / "smc_replay_extended"):
        args.out_dir = str(REPO_ROOT / "reports" / "smc_replay_regime_filter")

    db_path = Path(args.db_path)
    if not db_path.exists() and (SERVER_ROOT / args.db_path).exists():
        db_path = SERVER_ROOT / args.db_path
    elif not db_path.exists() and (REPO_ROOT / args.db_path).exists():
        db_path = REPO_ROOT / args.db_path

    print(f"[*] Loading {args.symbol} 15m candles from {db_path} ...")
    bars, meta = load_full_15m_candles(db_path, args.symbol, args.source)
    print(f"[*] {len(bars):,} open-market 15m bars "
          f"({meta['raw_first']} -> {meta['raw_last']})")

    if not args.full_range and not args.calibration_only:
        # Default = 3 monthly chunks, matching the CRT smoke-test ergonomics.
        args.max_chunks = args.max_chunks or 3

    c1h, c1h_close, c4h, c4h_close = build_timeframe_series(bars)
    print(f"[*] Resampled 1h={len(c1h):,}, 4h={len(c4h):,} (complete buckets)")
    print(
        f"[*] Live SMC parameters: DEFAULT_MIN_SCORE={DEFAULT_MIN_SCORE:.1f}, "
        f"LTF_UNCONFIRMED_PENALTY={LTF_UNCONFIRMED_PENALTY:.1f}, "
        f"DIRECTIONAL_CONFLICT_PENALTY={DIRECTIONAL_CONFLICT_PENALTY:.1f}"
    )
    if args.regime_filter:
        print("[*] Regime Filter: ENABLED (BUY requires 1H BULLISH_STACK, SELL requires 1H BEARISH_STACK)")
    else:
        print("[*] Regime Filter: DISABLED (Baseline SMC)")

    start_dt = _parse_start_date(args.start_date)
    warmup_bars_count = sum(1 for b in bars if b.timestamp < start_dt) if start_dt else 0
    if start_dt:
        print(f"[*] Filter --start-date={args.start_date} UTC (warm-up context: {warmup_bars_count:,} earlier 15m bars)")

    CANONICAL_CALIBRATION_END = datetime(2025, 5, 21, 8, 15, tzinfo=timezone.utc)
    CANONICAL_VALIDATION_END = datetime(2026, 2, 16, 3, 0, tzinfo=timezone.utc)
    if bars[-1].timestamp <= CANONICAL_CALIBRATION_END + timedelta(days=2):
        bounds = (CANONICAL_CALIBRATION_END, CANONICAL_VALIDATION_END)
    else:
        bounds = walk_forward_bounds(bars)

    if args.calibration_only:
        end_dt = bounds[0]
        print(f"[*] CALIBRATION-ONLY active: strictly evaluating before {end_dt.isoformat()} UTC (Zero contamination)")
    elif args.end_date:
        end_dt = _parse_start_date(args.end_date)
        print(f"[*] Filter --end-date={args.end_date} UTC")
    else:
        end_dt = None

    months = month_keys(bars)
    if start_dt:
        months = [(m, s, e) for (m, s, e) in months if e > start_dt]
    if end_dt:
        months = [(m, s, e) for (m, s, e) in months if s < end_dt]

    ckpt_dir = Path(args.checkpoint_dir) if args.checkpoint_dir else (Path(args.out_dir) / "checkpoints")
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    baseline_ckpt_dir = Path(args.baseline_ckpt_dir) if args.baseline_ckpt_dir else None

    # Precompute 1H EMA snapshot series for fast derivation if reusing baseline checkpoints
    from app.services.indicators.ema_calculator import EMACalculator
    ema_calc = EMACalculator()
    ema_trends_1h = []
    for i in range(len(c1h)):
        window = c1h[max(0, i - 199):i + 1]
        closes = [c.close for c in window]
        snap, _, _, _ = ema_calc.calculate_ema_snapshot(closes)
        ema_trends_1h.append(snap.ema_trend)

    all_records: List[SmcRecord] = []
    gap = SmcStats()
    started = datetime.now()
    for idx, (month, m_start, m_end) in enumerate(months):
        path = _ckpt_path(ckpt_dir, month)
        base_path = _ckpt_path(baseline_ckpt_dir, month) if baseline_ckpt_dir else None
        if path.exists() and not args.no_resume:
            recs = load_checkpoint(ckpt_dir, month)
            if start_dt:
                recs = [r for r in recs if _parse_ts(r.decision_time) >= start_dt]
            if end_dt:
                recs = [r for r in recs if _parse_ts(r.decision_time) < end_dt]
            print(f"[=] {month}: {len(recs):,} records (cached)")
        elif base_path and base_path.exists() and not args.no_resume:
            base_recs = load_checkpoint(baseline_ckpt_dir, month)
            if args.regime_filter:
                filtered_recs: List[SmcRecord] = []
                for r in base_recs:
                    dt = _parse_ts(r.decision_time)
                    if start_dt and dt < start_dt:
                        continue
                    idx1h = bisect_right(c1h_close, dt) - 1
                    lookup_trend = ema_trends_1h[idx1h] if 0 <= idx1h < len(ema_trends_1h) else "NEUTRAL"
                    trend = r.ema_trend if r.ema_trend else lookup_trend
                    r.ema_trend = trend
                    if r.accepted:
                        if r.direction == "BUY":
                            regime_ok = (trend == "BULLISH_STACK")
                        elif r.direction == "SELL":
                            regime_ok = (trend == "BEARISH_STACK")
                        else:
                            regime_ok = False
                        if not regime_ok:
                            r.accepted = False
                            r.gate = "REGIME_FILTER_REJECT"
                            r.setup_state = NO_SETUP_STATE
                            r.accepted_trade = None
                            r.detail = f"REGIME_FILTER_REJECT: {r.direction} requires {'BULLISH_STACK' if r.direction == 'BUY' else 'BEARISH_STACK'} but got {trend}"
                    filtered_recs.append(r)
                save_checkpoint(ckpt_dir, month, filtered_recs)
                recs = filtered_recs
                if end_dt:
                    recs = [r for r in recs if _parse_ts(r.decision_time) < end_dt]
                print(f"[+] {month}: {len(recs):,} records (derived from baseline via regime filter)")
            else:
                save_checkpoint(ckpt_dir, month, base_recs)
                recs = base_recs
                if end_dt:
                    recs = [r for r in recs if _parse_ts(r.decision_time) < end_dt]
                print(f"[=] {month}: {len(recs):,} records (reused baseline cache)")
        else:
            indices = [
                i for i, b in enumerate(bars)
                if m_start <= b.timestamp < m_end
                and (start_dt is None or b.timestamp >= start_dt)
                and (end_dt is None or b.timestamp < end_dt)
            ]
            if not indices:
                print(f"[-] {month}: 0 records (before start date)")
                continue
            recs, stats = replay_chunk(
                bars=bars, c1h=c1h, c1h_close=c1h_close, c4h=c4h,
                c4h_close=c4h_close, indices=indices, symbol=args.symbol,
                spread=args.spread, expiry_bars=args.expiry_bars,
                max_hold_bars=args.max_hold_bars, warmup_bars=args.warmup_bars,
                bounds=bounds, month=month, regime_filter=args.regime_filter,
            )
            save_checkpoint(ckpt_dir, month, recs)
            gap.warmup_skipped += stats.warmup_skipped
            gap.insufficient_data += stats.insufficient_data
            gap.eval_errors += stats.eval_errors
            gap.error_samples.extend(stats.error_samples[: max(0, 5 - len(gap.error_samples))])
            print(f"[+] {month}: {len(recs):,} records (computed)")
        all_records.extend(recs)
        if args.max_chunks is not None and idx + 1 >= args.max_chunks:
            print(f"[*] --max-chunks={args.max_chunks} reached; stopping early.")
            break

    elapsed = (datetime.now() - started).total_seconds()
    if start_dt:
        meta["start_date"] = args.start_date
        meta["warmup_bars_count"] = warmup_bars_count
    report, funnel_rows, cf_rows = build_report(
        meta, all_records, bounds, args, gap
    )
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "smc_replay_report.md"
    fun_csv = out_dir / "smc_replay_funnel.csv"
    cf_csv = out_dir / "smc_replay_counterfactual.csv"
    md_path.write_text(report + "\n", encoding="utf-8")
    _write_csv(fun_csv, funnel_rows,
               ("split", "gate", "bars", "buy_bars", "sell_bars", "distinct_opportunities"))
    _write_csv(
        cf_csv, cf_rows,
        ("split", "rejection_reason", "candidate_bars", "distinct_opportunities",
         "n_candidates", "n_filled", "n_no_fill", "win_rate", "avg_r", "expectancy",
         "profit_factor", "max_drawdown_r", "total_r", "ci_lower", "ci_upper", "flagged_lt30"),
    )
    print(f"[*] Elapsed              : {elapsed:,.0f}s")
    print(f"[*] Markdown report      : {md_path}")
    print(f"[*] Funnel CSV           : {fun_csv}")
    print(f"[*] Counterfactual CSV   : {cf_csv}")
    print(f"[*] Total bar records    : {len(all_records):,}")
    print(f"[*] Emitted bars         : {sum(1 for r in all_records if r.accepted):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
