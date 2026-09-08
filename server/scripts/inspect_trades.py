"""Deep dive into trade scoring breakdown and loss analysis."""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal, init_db
from app.models.candle import Candle
from app.schemas.candle import CandleBase
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
            timestamp=c.timestamp,
            open=float(c.open),
            high=float(c.high),
            low=float(c.low),
            close=float(c.close),
            volume=float(c.volume),
        )
        for c in db_candles
    ]


def inspect_trades():
    init_db()
    db = SessionLocal()
    signal_gen = SignalGenerator()

    with open(os.path.join(os.path.dirname(__file__), "baseline_results.json")) as f:
        baseline = json.load(f)

    print("=" * 80)
    print("DETAILED TRADE BREAKDOWN & LOSS ANALYSIS")
    print("=" * 80)

    for sym, res in baseline.items():
        print(f"\n--- {sym} ---")
        c_1h = load_candles(db, sym, "1h")
        c_4h = load_candles(db, sym, "4h")
        c_15m = load_candles(db, sym, "15m")

        for t in res["trade_log"]:
            entry_time = t["entry_time"]
            # Find candle index
            idx = next((i for i, c in enumerate(c_1h) if c.timestamp.isoformat() == entry_time), None)
            if idx is None:
                continue

            eval_slice = c_1h[max(0, idx - 150) : idx + 1]
            sub_4h = [c for c in c_4h if c.timestamp <= c_1h[idx].timestamp] if c_4h else None
            sub_15m = [c for c in c_15m if c.timestamp <= c_1h[idx].timestamp] if c_15m else None

            sig = signal_gen.evaluate_market_signal(
                candles_primary=eval_slice,
                symbol=sym,
                timeframe="1h",
                candles_4h=sub_4h[-100:] if sub_4h else None,
                candles_15m=sub_15m[-100:] if sub_15m else None,
            )

            bd = sig.score_breakdown
            print(
                f"Trade #{t['id']} [{t['direction']}] @ {entry_time} | Score: {t['score']} | "
                f"Pillar Breakdown -> Struct: {bd.structure_score if bd else 0}/30, "
                f"Liq: {bd.liquidity_score if bd else 0}/25, "
                f"Ind: {bd.indicators_score if bd else 0}/25, "
                f"PA: {bd.price_action_score if bd else 0}/20 | "
                f"Outcome: {t['exit_reason']} (PnL: ${t['pnl']:.2f}, Return: {t['return_r']}R)"
            )
            print(f"   Reasons: {sig.reasons[:3]}")


if __name__ == "__main__":
    inspect_trades()
