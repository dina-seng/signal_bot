"""Random-entry baseline simulation using identical SL/TP geometry and identical bar times."""

from datetime import datetime
import random
from typing import List, Sequence

from app.schemas.candle import CandleCreate
from app.services.sweep.backtest.metrics import calculate_slice_metrics
from app.services.sweep.backtest.models import SliceMetrics, TradePosition


def run_random_baseline(
    executed_trades: Sequence[TradePosition],
    all_candles_15m: Sequence[CandleCreate],
    friction_usd: float = 0.40,
    seed: int = 42,
) -> SliceMetrics:
    """Run random-entry baseline on identical execution bar times and identical SL/TP geometry.

    For each strategy trade:
    - Flip a coin for direction ("LONG" or "SHORT").
    - Enter at the bar's close price.
    - Set SL distance = trade.initial_risk_usd.
    - Set TP distance = (trade.take_profit_1 - trade.entry_price) absolute.
    - Simulate outcome with identical conservative same-bar SL first rule.
    """
    if not executed_trades:
        return calculate_slice_metrics("random_baseline", [])

    rng = random.Random(seed)
    time_to_idx = {c.timestamp: i for i, c in enumerate(all_candles_15m)}
    baseline_trades: List[TradePosition] = []

    for trade in executed_trades:
        entry_idx = time_to_idx.get(trade.entry_time)
        if entry_idx is None or entry_idx >= len(all_candles_15m) - 1:
            continue

        c_entry = all_candles_15m[entry_idx]
        direction = rng.choice(["LONG", "SHORT"])
        entry_price = c_entry.close
        risk_dist = max(1.0, trade.initial_risk_usd)
        reward_dist = abs(trade.take_profit_1 - trade.entry_price)

        if direction == "LONG":
            sl = entry_price - risk_dist
            tp = entry_price + reward_dist
        else:
            sl = entry_price + risk_dist
            tp = entry_price - reward_dist

        friction_r = friction_usd / risk_dist

        # Simulate forward
        exit_price = None
        exit_reason = "END_OF_DATA"
        exit_time = None
        bars_held = 0

        for k in range(entry_idx + 1, min(len(all_candles_15m), entry_idx + 100)):
            c = all_candles_15m[k]
            bars_held += 1

            if direction == "LONG":
                hit_sl = c.low <= sl
                hit_tp = c.high >= tp
                if hit_sl and hit_tp:
                    # Same bar: assume SL first
                    exit_price = sl
                    exit_reason = "SL"
                    exit_time = c.timestamp
                    break
                elif hit_sl:
                    exit_price = sl
                    exit_reason = "SL"
                    exit_time = c.timestamp
                    break
                elif hit_tp:
                    exit_price = tp
                    exit_reason = "TP1"
                    exit_time = c.timestamp
                    break
            else:
                hit_sl = c.high >= sl
                hit_tp = c.low <= tp
                if hit_sl and hit_tp:
                    exit_price = sl
                    exit_reason = "SL"
                    exit_time = c.timestamp
                    break
                elif hit_sl:
                    exit_price = sl
                    exit_reason = "SL"
                    exit_time = c.timestamp
                    break
                elif hit_tp:
                    exit_price = tp
                    exit_reason = "TP1"
                    exit_time = c.timestamp
                    break

        if exit_price is None:
            last_c = all_candles_15m[min(len(all_candles_15m) - 1, entry_idx + 99)]
            exit_price = last_c.close
            exit_time = last_c.timestamp

        # Calculate R
        if direction == "LONG":
            gross_r = (exit_price - entry_price) / risk_dist
        else:
            gross_r = (entry_price - exit_price) / risk_dist

        net_r = gross_r - friction_r

        baseline_trades.append(
            TradePosition(
                position_id=len(baseline_trades) + 1,
                setup_id=f"rand_{trade.setup_id}",
                symbol=trade.symbol,
                direction=direction,
                grade=trade.grade,
                pool_type=trade.pool_type,
                session=trade.session,
                htf_aligned=False,
                day_of_week=trade.day_of_week,
                entry_time=trade.entry_time,
                entry_price=entry_price,
                stop_loss=sl,
                take_profit_1=tp,
                take_profit_2=None,
                initial_risk_usd=risk_dist,
                exit_time=exit_time,
                exit_price=exit_price,
                exit_reason=exit_reason,
                r_multiple=round(net_r, 3),
                pnl_usd=round(net_r * risk_dist, 2),
                friction_usd=friction_usd,
                friction_r=round(friction_r, 4),
                mfe_r=0.0,
                mae_r=0.0,
                bars_held=bars_held,
            )
        )

    return calculate_slice_metrics("random_baseline", baseline_trades, n_signals=len(baseline_trades))
