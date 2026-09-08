"""Strategy Diagnostic Script for Milestone 4.

Analyzes historical setups and backtested trades across:
1. Score brackets (60-69, 70-74, 75-79, 80-84, 85-89, 90-100)
2. Four Pillars contribution (Structure, Liquidity, Indicators, Price Action)
3. Direction (BUY vs SELL)
4. Instruments (XAUUSD, EURUSD, GBPUSD, USDJPY)
5. Market Conditions (TREND, RANGE, BREAKOUT, REVERSAL, HIGH VOLATILITY, LOW VOLATILITY)
6. Special Investigation:
   - Suspect 1: Liquidity baseline trend points (free points awarded without sweep/zone)
   - Suspect 2: Correlated / double-counted evidence across pillars
"""

import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal, init_db
from app.models.candle import Candle
from app.schemas.backtesting import BacktestConfig
from app.schemas.candle import CandleBase
from app.schemas.signal import SignalDirection
from app.schemas.structure import TrendDirection
from app.services.backtesting import BacktestEngine
from app.services.signals import SignalGenerator


def load_candles(db, symbol: str, timeframe: str):
    db_candles = (
        db.query(Candle)
        .filter_by(symbol=symbol, timeframe=timeframe)
        .order_by(Candle.timestamp.asc())
        .all()
    )
    return [
        CandleBase(
            symbol=c.symbol,
            timeframe=c.timeframe,
            timestamp=c.timestamp.replace(tzinfo=timezone.utc) if c.timestamp.tzinfo is None else c.timestamp.astimezone(timezone.utc),
            open=float(c.open),
            high=float(c.high),
            low=float(c.low),
            close=float(c.close),
            volume=float(c.volume),
        )
        for c in db_candles
    ]


def run_diagnostic():
    init_db()
    db = SessionLocal()
    symbols = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY"]
    signal_gen = SignalGenerator()

    # Step 1: Collect ALL scored setup opportunities across bars (score >= 50)
    all_setups = []

    for sym in symbols:
        c_1h = load_candles(db, sym, "1h")
        c_4h = load_candles(db, sym, "4h")
        c_15m = load_candles(db, sym, "15m")

        if len(c_1h) < 40:
            continue

        for i in range(30, len(c_1h)):
            eval_slice = c_1h[max(0, i - 150) : i + 1]
            bar_ts = c_1h[i].timestamp
            sub_4h = [c for c in candles_4h if c.timestamp <= bar_ts] if (candles_4h := c_4h) else None
            sub_15m = [c for c in candles_15m if c.timestamp <= bar_ts] if (candles_15m := c_15m) else None

            # Calculate ATR volatility for regime classification
            recent_atr = float(np.mean([float(c.high) - float(c.low) for c in eval_slice[-14:]]))
            hist_atr = float(np.mean([float(c.high) - float(c.low) for c in eval_slice[-50:]])) if len(eval_slice) >= 50 else recent_atr
            volatility_regime = "HIGH_VOLATILITY" if recent_atr > hist_atr * 1.25 else ("LOW_VOLATILITY" if recent_atr < hist_atr * 0.75 else "NORMAL_VOLATILITY")

            sig = signal_gen.evaluate_market_signal(
                candles_primary=eval_slice,
                symbol=sym,
                timeframe="1h",
                candles_4h=sub_4h[-100:] if sub_4h else None,
                candles_15m=sub_15m[-100:] if sub_15m else None,
                account_balance=10000.0,
                risk_percent=0.5,
            )

            # Analyze structural details
            liq_struct = signal_gen.liquidity_service.analyze_liquidity_and_structure(eval_slice, sym, "1h")
            ind_res = signal_gen.indicator_service.analyze_indicators(eval_slice, sym, "1h")

            # Determine market state / regime
            m_state = "RANGE"
            if liq_struct.trend in (TrendDirection.BULLISH, TrendDirection.BEARISH):
                m_state = "TREND"
            if liq_struct.latest_bos:
                m_state = "BREAKOUT"
            if liq_struct.latest_choch:
                m_state = "REVERSAL"

            # Check if baseline trend liquidity points were awarded
            has_real_sweep = bool(liq_struct.latest_sweep and (
                (sig.direction == SignalDirection.BUY and liq_struct.latest_sweep.sweep_type.value == "SELL_SIDE_SWEEP") or
                (sig.direction == SignalDirection.SELL and liq_struct.latest_sweep.sweep_type.value == "BUY_SIDE_SWEEP")
            ))
            has_real_zone = bool(any(
                (z.zone_type.value == "SUPPORT" and sig.direction == SignalDirection.BUY) or
                (z.zone_type.value == "RESISTANCE" and sig.direction == SignalDirection.SELL)
                for z in liq_struct.sr_zones
            ))
            has_equal_pool = bool(any(
                (p.pool_type.value == "EQUAL_LOWS" and sig.direction == SignalDirection.BUY) or
                (p.pool_type.value == "EQUAL_HIGHS" and sig.direction == SignalDirection.SELL)
                for p in liq_struct.liquidity_pools
            ))
            liquidity_is_synthetic_baseline = bool(
                sig.score_breakdown and sig.score_breakdown.liquidity_score > 0 and not (has_real_sweep or has_real_zone or has_equal_pool)
            )

            all_setups.append({
                "bar_index": i,
                "symbol": sym,
                "timestamp": bar_ts.isoformat(),
                "direction": sig.direction.value,
                "score": sig.setup_score,
                "score_breakdown": {
                    "structure": sig.score_breakdown.structure_score if sig.score_breakdown else 0,
                    "liquidity": sig.score_breakdown.liquidity_score if sig.score_breakdown else 0,
                    "indicators": sig.score_breakdown.indicators_score if sig.score_breakdown else 0,
                    "price_action": sig.score_breakdown.price_action_score if sig.score_breakdown else 0,
                },
                "reasons": sig.reasons,
                "market_regime": m_state,
                "volatility_regime": volatility_regime,
                "has_real_sweep": has_real_sweep,
                "has_real_zone": has_real_zone,
                "liquidity_is_synthetic_baseline": liquidity_is_synthetic_baseline,
            })

    # Step 2: Run simulation across multiple thresholds (60, 70, 75, 80, 85) to analyze outcome by score bracket
    thresholds = [60.0, 70.0, 75.0, 80.0, 85.0]
    bracket_results = {}
    engine = BacktestEngine(signal_generator=signal_gen)

    for min_th in thresholds:
        cfg = BacktestConfig(
            initial_balance=10000.0,
            risk_percent=0.5,
            min_score_threshold=min_th,
            take_profit_1_rr=2.0,
            take_profit_2_rr=3.0,
            partial_tp_ratio=0.5,
            move_sl_to_be_on_tp1=True,
            spread_pips=1.0,
            slippage_pips=0.5,
            max_open_trades=3,
            warmup_bars=30,
        )
        trades_for_th = []
        for sym in symbols:
            c_1h = load_candles(db, sym, "1h")
            c_4h = load_candles(db, sym, "4h")
            c_15m = load_candles(db, sym, "15m")
            res = engine.run_simulation(
                candles=c_1h,
                symbol=sym,
                timeframe="1h",
                config=cfg,
                candles_4h=c_4h,
                candles_15m=c_15m,
            )
            for t in res.trades:
                trades_for_th.append({
                    "symbol": sym,
                    "score": t.score,
                    "pnl": t.pnl,
                    "return_r": t.return_r,
                    "exit_reason": t.exit_reason,
                    "direction": t.direction.value,
                })
        bracket_results[str(min_th)] = trades_for_th

    # Group executed trades from 60+ baseline into explicit brackets:
    # 60-69, 70-74, 75-79, 80-84, 85-89, 90-100
    all_60_trades = bracket_results["60.0"]
    score_brackets = {
        "60-69": [t for t in all_60_trades if 60.0 <= t["score"] < 70.0],
        "70-74": [t for t in all_60_trades if 70.0 <= t["score"] < 75.0],
        "75-79": [t for t in all_60_trades if 75.0 <= t["score"] < 80.0],
        "80-84": [t for t in all_60_trades if 80.0 <= t["score"] < 85.0],
        "85-89": [t for t in all_60_trades if 85.0 <= t["score"] < 90.0],
        "90-100": [t for t in all_60_trades if t["score"] >= 90.0],
    }

    bracket_summary = {}
    for b_name, b_trades in score_brackets.items():
        n = len(b_trades)
        wins = sum(1 for t in b_trades if t["pnl"] > 0)
        losses = sum(1 for t in b_trades if t["pnl"] < 0)
        wr = round((wins / n) * 100.0, 1) if n > 0 else 0.0
        tot_r = round(sum(t["return_r"] for t in b_trades), 2)
        avg_r = round(tot_r / n, 2) if n > 0 else 0.0
        bracket_summary[b_name] = {
            "trades": n,
            "wins": wins,
            "losses": losses,
            "win_rate": wr,
            "total_r": tot_r,
            "average_r": avg_r,
        }

    # Step 3: Analyze Pillar correlations & Suspect #1 / Suspect #2
    setups_with_score_75 = [s for s in all_setups if s["score"] >= 75.0]
    total_75_setups = len(setups_with_score_75)
    synthetic_liq_count = sum(1 for s in setups_with_score_75 if s["liquidity_is_synthetic_baseline"])
    real_liq_count = total_75_setups - synthetic_liq_count

    # Double counting investigation:
    # Check how many setups have:
    # High Structure Score (>15) AND High Indicator Score (>15) AND Synthetic Liquidity (>5)
    double_counted_count = sum(
        1 for s in setups_with_score_75
        if s["score_breakdown"]["structure"] >= 15.0
        and s["score_breakdown"]["indicators"] >= 15.0
        and s["liquidity_is_synthetic_baseline"]
    )

    diagnostic_report = {
        "score_brackets": bracket_summary,
        "total_setups_scanned": len(all_setups),
        "setups_above_75": total_75_setups,
        "suspect_1_synthetic_liquidity": {
            "total_setups_gte_75": total_75_setups,
            "setups_with_synthetic_liquidity": synthetic_liq_count,
            "percent_synthetic": round((synthetic_liq_count / max(1, total_75_setups)) * 100.0, 1),
            "setups_with_real_sweep_or_zone": real_liq_count,
        },
        "suspect_2_double_counting": {
            "trend_double_counted_setups": double_counted_count,
            "percent_double_counted": round((double_counted_count / max(1, total_75_setups)) * 100.0, 1),
        },
        "regime_distribution_75": {
            "TREND": sum(1 for s in setups_with_score_75 if s["market_regime"] == "TREND"),
            "RANGE": sum(1 for s in setups_with_score_75 if s["market_regime"] == "RANGE"),
            "BREAKOUT": sum(1 for s in setups_with_score_75 if s["market_regime"] == "BREAKOUT"),
            "REVERSAL": sum(1 for s in setups_with_score_75 if s["market_regime"] == "REVERSAL"),
        },
        "volatility_distribution_75": {
            "HIGH_VOLATILITY": sum(1 for s in setups_with_score_75 if s["volatility_regime"] == "HIGH_VOLATILITY"),
            "NORMAL_VOLATILITY": sum(1 for s in setups_with_score_75 if s["volatility_regime"] == "NORMAL_VOLATILITY"),
            "LOW_VOLATILITY": sum(1 for s in setups_with_score_75 if s["volatility_regime"] == "LOW_VOLATILITY"),
        },
    }

    out_file = os.path.join(os.path.dirname(__file__), "diagnostic_results.json")
    with open(out_file, "w") as f:
        json.dump(diagnostic_report, f, indent=2)

    print(f"Diagnostic report written to {out_file}")
    db.close()


if __name__ == "__main__":
    run_diagnostic()
