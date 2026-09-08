"""Out-of-Sample (OOS) Validation Script for Milestone 6.

Splits historical data into 70% Development (In-Sample) and 30% Validation (Out-of-Sample).
Tests whether the strategy maintains stable performance on unseen market data.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal, init_db
from app.models.candle import Candle
from app.schemas.backtesting import BacktestConfig
from app.schemas.candle import CandleBase
from app.services.backtesting import BacktestEngine
from app.services.signals import SignalGenerator


def load_candles(db, symbol: str, timeframe: str) -> List[CandleBase]:
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


def run_oos_validation():
    init_db()
    db = SessionLocal()
    symbols = ["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]
    signal_gen = SignalGenerator()
    engine = BacktestEngine(signal_generator=signal_gen)

    config = BacktestConfig(
        initial_balance=10000.0,
        risk_percent=0.5,
        min_score_threshold=75.0,
        take_profit_1_rr=2.0,
        take_profit_2_rr=3.0,
        partial_tp_ratio=0.5,
        move_sl_to_be_on_tp1=True,
        spread_pips=1.0,
        slippage_pips=0.5,
        max_open_trades=3,
        warmup_bars=25,
    )

    oos_report = {}

    for sym in symbols:
        c_1h = load_candles(db, sym, "1h")
        c_4h = load_candles(db, sym, "4h")
        c_15m = load_candles(db, sym, "15m")

        total_bars = len(c_1h)
        if total_bars < 100:
            print(f"Skipping {sym} - not enough candles ({total_bars})")
            continue

        split_idx = int(total_bars * 0.70)
        split_ts = c_1h[split_idx].timestamp

        # Split 1h
        is_candles_1h = c_1h[:split_idx]
        oos_candles_1h = c_1h[split_idx:]

        # Split 4h & 15m corresponding to timestamps
        is_candles_4h = [c for c in c_4h if c.timestamp < split_ts]
        oos_candles_4h = [c for c in c_4h if c.timestamp >= split_ts]

        is_candles_15m = [c for c in c_15m if c.timestamp < split_ts]
        oos_candles_15m = [c for c in c_15m if c.timestamp >= split_ts]

        # 1. Run In-Sample (70%) Backtest
        res_is = engine.run_simulation(
            candles=is_candles_1h,
            symbol=sym,
            timeframe="1h",
            config=config,
            candles_4h=is_candles_4h if is_candles_4h else None,
            candles_15m=is_candles_15m if is_candles_15m else None,
            name=f"{sym} 1H In-Sample (70%)",
        )

        # 2. Run Out-of-Sample (30% Unseen) Backtest
        res_oos = engine.run_simulation(
            candles=oos_candles_1h,
            symbol=sym,
            timeframe="1h",
            config=config,
            candles_4h=oos_candles_4h if oos_candles_4h else None,
            candles_15m=oos_candles_15m if oos_candles_15m else None,
            name=f"{sym} 1H Out-of-Sample (30% Unseen)",
        )

        m_is = res_is.metrics
        m_oos = res_oos.metrics

        tot_r_is = round(sum(t.return_r for t in res_is.trades), 2)
        tot_r_oos = round(sum(t.return_r for t in res_oos.trades), 2)

        risk_unit_usd = 10000.0 * 0.005  # $50
        max_dd_r_is = round(m_is.max_drawdown_usd / risk_unit_usd, 2)
        max_dd_r_oos = round(m_oos.max_drawdown_usd / risk_unit_usd, 2)

        oos_report[sym] = {
            "total_candles": total_bars,
            "split_date": split_ts.isoformat(),
            "in_sample_70pct": {
                "candle_count": len(is_candles_1h),
                "date_range": {
                    "start": res_is.start_date.isoformat() if res_is.start_date else None,
                    "end": res_is.end_date.isoformat() if res_is.end_date else None,
                },
                "total_trades": len(res_is.trades),
                "wins": m_is.winning_trades,
                "losses": m_is.losing_trades,
                "win_rate_pct": m_is.win_rate,
                "profit_factor": m_is.profit_factor,
                "expectancy_r": m_is.expectancy_r,
                "total_r": tot_r_is,
                "max_drawdown_pct": m_is.max_drawdown_pct,
                "max_drawdown_r": max_dd_r_is,
                "pnl_usd": m_is.total_pnl,
            },
            "out_of_sample_30pct": {
                "candle_count": len(oos_candles_1h),
                "date_range": {
                    "start": res_oos.start_date.isoformat() if res_oos.start_date else None,
                    "end": res_oos.end_date.isoformat() if res_oos.end_date else None,
                },
                "total_trades": len(res_oos.trades),
                "wins": m_oos.winning_trades,
                "losses": m_oos.losing_trades,
                "win_rate_pct": m_oos.win_rate,
                "profit_factor": m_oos.profit_factor,
                "expectancy_r": m_oos.expectancy_r,
                "total_r": tot_r_oos,
                "max_drawdown_pct": m_oos.max_drawdown_pct,
                "max_drawdown_r": max_dd_r_oos,
                "pnl_usd": m_oos.total_pnl,
            },
        }

    # Aggregate Portfolio Level
    total_is_trades = sum(oos_report[s]["in_sample_70pct"]["total_trades"] for s in oos_report)
    total_is_wins = sum(oos_report[s]["in_sample_70pct"]["wins"] for s in oos_report)
    total_is_losses = sum(oos_report[s]["in_sample_70pct"]["losses"] for s in oos_report)
    total_is_r = round(sum(oos_report[s]["in_sample_70pct"]["total_r"] for s in oos_report), 2)
    total_is_pnl = round(sum(oos_report[s]["in_sample_70pct"]["pnl_usd"] for s in oos_report), 2)

    total_oos_trades = sum(oos_report[s]["out_of_sample_30pct"]["total_trades"] for s in oos_report)
    total_oos_wins = sum(oos_report[s]["out_of_sample_30pct"]["wins"] for s in oos_report)
    total_oos_losses = sum(oos_report[s]["out_of_sample_30pct"]["losses"] for s in oos_report)
    total_oos_r = round(sum(oos_report[s]["out_of_sample_30pct"]["total_r"] for s in oos_report), 2)
    total_oos_pnl = round(sum(oos_report[s]["out_of_sample_30pct"]["pnl_usd"] for s in oos_report), 2)

    portfolio_summary = {
        "in_sample_70pct": {
            "total_trades": total_is_trades,
            "wins": total_is_wins,
            "losses": total_is_losses,
            "win_rate_pct": round((total_is_wins / max(1, total_is_trades)) * 100.0, 1),
            "total_r": total_is_r,
            "total_pnl_usd": total_is_pnl,
        },
        "out_of_sample_30pct": {
            "total_trades": total_oos_trades,
            "wins": total_oos_wins,
            "losses": total_oos_losses,
            "win_rate_pct": round((total_oos_wins / max(1, total_oos_trades)) * 100.0, 1),
            "total_r": total_oos_r,
            "total_pnl_usd": total_oos_pnl,
        },
    }

    final_report = {
        "portfolio_summary": portfolio_summary,
        "instruments": oos_report,
    }

    out_file = os.path.join(os.path.dirname(__file__), "oos_validation_results.json")
    with open(out_file, "w") as f:
        json.dump(final_report, f, indent=2)

    print(f"OOS validation results written to {out_file}")
    db.close()


if __name__ == "__main__":
    run_oos_validation()
