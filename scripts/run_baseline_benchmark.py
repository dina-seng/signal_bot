"""Baseline Strategy Performance Benchmark.

Executes baseline historical testing on EUR/USD, GBP/USD, USD/JPY, and XAU/USD
using the exact production strategy rules without modifications.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal, init_db
from app.models.candle import Candle
from app.schemas.backtesting import BacktestConfig
from app.schemas.candle import CandleBase
from app.schemas.signal import SignalDirection
from app.services.backtesting import BacktestEngine
from app.services.market_data import IngestionService, YahooFinanceProvider
from app.services.signals import SignalGenerator


def calculate_losing_streak(trades) -> int:
    """Calculate maximum consecutive losing trades."""
    max_streak = 0
    current_streak = 0
    for t in trades:
        if t.pnl < -0.0001:
            current_streak += 1
            if current_streak > max_streak:
                max_streak = current_streak
        elif t.pnl > 0.0001:
            current_streak = 0
    return max_streak


async def ingest_market_data(db, symbols, timeframes, limit=700):
    """Ingest historical candles if needed."""
    provider = YahooFinanceProvider()
    ingestion = IngestionService(provider=provider, db=db)
    for sym in symbols:
        for tf in timeframes:
            count = db.query(Candle).filter_by(symbol=sym, timeframe=tf).count()
            if count < 150:
                print(f"Ingesting historical data for {sym} [{tf}] (current: {count})...")
                try:
                    await ingestion.sync_symbol_timeframe(symbol=sym, timeframe=tf, limit=limit)
                except Exception as e:
                    print(f"Error ingesting {sym} [{tf}]: {e}")


def load_candles(db, symbol: str, timeframe: str) -> List[CandleBase]:
    """Load candles from DB sorted chronologically."""
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


def count_bar_signals(signal_generator: SignalGenerator, candles_1h, candles_4h=None, candles_15m=None, min_score=75.0, warmup=30):
    """Count bar-by-bar signals evaluated on each closed candle."""
    buy_count = 0
    sell_count = 0
    wait_count = 0
    total_bars = len(candles_1h)

    for i in range(warmup, total_bars):
        eval_slice = candles_1h[max(0, i - 150) : i + 1]
        bar_ts = candles_1h[i].timestamp
        sub_4h = [c for c in candles_4h if c.timestamp <= bar_ts] if candles_4h else None
        sub_15m = [c for c in candles_15m if c.timestamp <= bar_ts] if candles_15m else None

        sig = signal_generator.evaluate_market_signal(
            candles_primary=eval_slice,
            symbol=candles_1h[0].symbol,
            timeframe=candles_1h[0].timeframe,
            candles_4h=sub_4h[-100:] if sub_4h else None,
            candles_15m=sub_15m[-100:] if sub_15m else None,
            account_balance=10000.0,
            risk_percent=0.5,
        )

        if sig.direction == SignalDirection.BUY and sig.setup_score >= min_score:
            buy_count += 1
        elif sig.direction == SignalDirection.SELL and sig.setup_score >= min_score:
            sell_count += 1
        else:
            wait_count += 1

    return {
        "total_evaluated_bars": total_bars - warmup,
        "buy_signals": buy_count,
        "sell_signals": sell_count,
        "wait_signals": wait_count,
        "total_actionable_signals": buy_count + sell_count,
    }


async def main():
    init_db()
    db = SessionLocal()

    symbols = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY"]
    timeframes = ["1h", "4h", "15m"]

    print("Step 1: Synchronizing Market Data...")
    await ingest_market_data(db, symbols, timeframes, limit=700)

    signal_gen = SignalGenerator()
    engine = BacktestEngine(signal_generator=signal_gen)

    config = BacktestConfig(
        initial_balance=10000.0,
        risk_percent=0.5,
        min_score_threshold=75.0,  # Strict production threshold
        take_profit_1_rr=2.0,
        take_profit_2_rr=3.0,
        partial_tp_ratio=0.5,
        move_sl_to_be_on_tp1=True,
        spread_pips=1.0,
        slippage_pips=0.5,
        max_open_trades=3,
        warmup_bars=30,
    )

    all_results = {}

    print("\nStep 2: Executing Baseline Backtests...")
    for sym in symbols:
        c_1h = load_candles(db, sym, "1h")
        c_4h = load_candles(db, sym, "4h")
        c_15m = load_candles(db, sym, "15m")

        print(f"\nEvaluating {sym} (1h: {len(c_1h)}, 4h: {len(c_4h)}, 15m: {len(c_15m)} candles)...")

        if len(c_1h) < 40:
            print(f"Skipping {sym} - insufficient candles ({len(c_1h)}).")
            continue

        # 1. Bar signal counts
        sig_counts = count_bar_signals(
            signal_generator=signal_gen,
            candles_1h=c_1h,
            candles_4h=c_4h if c_4h else None,
            candles_15m=c_15m if c_15m else None,
            min_score=75.0,
            warmup=30,
        )

        # 2. Simulation
        res = engine.run_simulation(
            candles=c_1h,
            symbol=sym,
            timeframe="1h",
            config=config,
            candles_4h=c_4h if c_4h else None,
            candles_15m=c_15m if c_15m else None,
            name=f"{sym} 1H Production Baseline",
        )

        m = res.metrics
        trades = res.trades

        # Detailed Exit Reasons
        tp1_hits = sum(1 for t in trades if "TP1" in t.exit_reason or (t.take_profit_1 and t.pnl > 0))
        tp2_hits = sum(1 for t in trades if "TP2" in t.exit_reason)
        sl_hits = sum(1 for t in trades if "SL_HIT" in t.exit_reason)
        be_exits = sum(1 for t in trades if "BREAK_EVEN" in t.exit_reason)
        eod_exits = sum(1 for t in trades if "END_OF_DATA" in t.exit_reason)

        tot_trades = len(trades)
        tp1_rate = round((tp1_hits / tot_trades) * 100.0, 1) if tot_trades > 0 else 0.0
        tp2_rate = round((tp2_hits / tot_trades) * 100.0, 1) if tot_trades > 0 else 0.0
        sl_rate = round((sl_hits / tot_trades) * 100.0, 1) if tot_trades > 0 else 0.0

        total_r = round(sum(t.return_r for t in trades), 2)
        avg_r = round(total_r / tot_trades, 2) if tot_trades > 0 else 0.0
        max_streak = calculate_losing_streak(trades)

        # Max DD in R (approximating 1R = 0.5% of balance = ~$50)
        risk_unit_usd = 10000.0 * 0.005  # $50
        max_dd_r = round(m.max_drawdown_usd / risk_unit_usd, 2) if risk_unit_usd > 0 else 0.0

        sym_result = {
            "symbol": sym,
            "timeframe": "1h",
            "date_range": {
                "start": res.start_date.isoformat() if res.start_date else None,
                "end": res.end_date.isoformat() if res.end_date else None,
                "candle_count": len(c_1h),
            },
            "signals": sig_counts,
            "trades": {
                "total": tot_trades,
                "wins": m.winning_trades,
                "losses": m.losing_trades,
                "breakeven": m.break_even_trades,
                "win_rate_pct": m.win_rate,
                "loss_rate_pct": m.loss_rate,
                "profit_factor": m.profit_factor,
                "expectancy_usd": m.expectancy_usd,
                "expectancy_r": m.expectancy_r,
                "average_r": avg_r,
                "total_r": total_r,
                "max_drawdown_pct": m.max_drawdown_pct,
                "max_drawdown_usd": m.max_drawdown_usd,
                "max_drawdown_r": max_dd_r,
                "max_losing_streak": max_streak,
                "total_pnl_usd": m.total_pnl,
                "total_pnl_pct": m.total_pnl_percent,
            },
            "exit_stats": {
                "tp1_hits": tp1_hits,
                "tp1_rate_pct": tp1_rate,
                "tp2_hits": tp2_hits,
                "tp2_rate_pct": tp2_rate,
                "sl_hits": sl_hits,
                "sl_rate_pct": sl_rate,
                "breakeven_exits": be_exits,
                "end_of_data_exits": eod_exits,
            },
            "trade_log": [
                {
                    "id": t.id,
                    "direction": t.direction.value,
                    "entry_time": t.entry_time.isoformat(),
                    "exit_time": t.exit_time.isoformat(),
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "pnl": t.pnl,
                    "return_r": t.return_r,
                    "exit_reason": t.exit_reason,
                    "score": t.score,
                }
                for t in trades
            ],
        }

        all_results[sym] = sym_result

    # Save to json
    output_path = os.path.join(os.path.dirname(__file__), "baseline_results.json")
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)

    print(f"\nBaseline results saved to {output_path}")
    db.close()


if __name__ == "__main__":
    asyncio.run(main())
