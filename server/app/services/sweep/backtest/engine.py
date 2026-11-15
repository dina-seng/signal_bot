"""Walk-Forward Historical Backtest Engine for Liquidity-Sweep Strategy."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

from app.schemas.candle import CandleCreate
from app.services.market_data.calendar import filter_open_market_candles
from app.services.market_data.resample import resample_ohlc
from app.services.sweep.config import SweepConfig
from app.services.sweep.engine import evaluate_sweep_market
from app.services.sweep.state_machine import SetupState, SweepSetup
from app.services.sweep.backtest.models import (
    CandidateSetupRecord,
    TradePosition,
)

NY_TZ = ZoneInfo("America/New_York")


def get_session_name(dt_utc: datetime) -> str:
    """Classify session in America/New_York time (DST-aware)."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    dt_ny = dt_utc.astimezone(NY_TZ)
    h = dt_ny.hour
    m = dt_ny.minute

    if h >= 18 or h < 0:
        return "Asia"
    elif 3 <= h < 7:
        return "London"
    elif (h == 9 and m >= 0) or (h == 10 and m <= 30):
        return "NY"
    return "Other"


@dataclass
class PendingOrder:
    setup: SweepSetup
    placed_time: datetime
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: Optional[float]
    initial_risk_usd: float
    direction: str
    bars_pending: int = 0


def run_walk_forward_backtest(
    candles_15m: Sequence[CandleCreate],
    config: Optional[SweepConfig] = None,
    friction_spread: float = 0.30,
    friction_slippage: float = 0.10,
    cooldown_bars: int = 8,
    warmup_bars: int = 40,
    max_holding_bars: int = 100,
) -> Tuple[List[TradePosition], List[CandidateSetupRecord]]:
    """Execute walk-forward bar-by-bar backtest over 15m candle history.

    Rules:
    - Zero lookahead: at bar t, only closed bars up to t are visible.
    - Derived HTFs: 1h/4h resampled strictly up to as_of.
    - Fill model: limit fills only if price trades through zone price.
    - Same-bar SL & TP touch: ASSUME SL FIRST.
    - Single open position at a time; cooldown after exit.
    - Log every candidate setup (all states, including NO_SETUP) with forward outcomes.
    - News filter labeled OFF.
    """
    if config is None:
        config = SweepConfig()

    total_friction_usd = friction_spread + friction_slippage

    # Pre-resample 1h and 4h
    candles_1h = resample_ohlc(candles_15m, "1h")
    candles_4h = resample_ohlc(candles_15m, "4h")

    # Time-to-index map
    time_to_idx = {
        (c.timestamp if c.timestamp.tzinfo else c.timestamp.replace(tzinfo=timezone.utc)): i
        for i, c in enumerate(candles_15m)
    }

    executed_trades: List[TradePosition] = []
    candidates_dict: Dict[str, CandidateSetupRecord] = {}

    open_position: Optional[TradePosition] = None
    open_position_fill_idx: Optional[int] = None
    pending_orders: List[PendingOrder] = []
    bars_since_last_exit = 9999

    n_bars = len(candles_15m)

    for t in range(warmup_bars, n_bars):
        bars_since_last_exit += 1
        curr_bar = candles_15m[t]
        bar_ts = curr_bar.timestamp if curr_bar.timestamp.tzinfo else curr_bar.timestamp.replace(tzinfo=timezone.utc)
        as_of = bar_ts + timedelta(minutes=15)

        # ----------------------------------------------------------------------
        # 1. Manage Active Position (if open)
        # ----------------------------------------------------------------------
        if open_position is not None:
            open_position.bars_held += 1
            direction = open_position.direction
            sl = open_position.stop_loss
            tp = open_position.take_profit_1
            risk = open_position.initial_risk_usd

            # Update MFE / MAE
            if direction == "SHORT":
                favorable = open_position.entry_price - curr_bar.low
                adverse = curr_bar.high - open_position.entry_price
            else:
                favorable = curr_bar.high - open_position.entry_price
                adverse = open_position.entry_price - curr_bar.low

            open_position.mfe_r = max(open_position.mfe_r, favorable / risk)
            open_position.mae_r = max(open_position.mae_r, adverse / risk)

            # Check exits
            exit_occurred = False
            exit_price = None
            exit_reason = None

            if direction == "SHORT":
                hit_sl = curr_bar.high >= sl
                hit_tp = curr_bar.low <= tp
                if hit_sl and hit_tp:
                    # Same bar: SL FIRST!
                    exit_occurred = True
                    exit_price = sl
                    exit_reason = "SL"
                elif hit_sl:
                    exit_occurred = True
                    exit_price = sl
                    exit_reason = "SL"
                elif hit_tp:
                    exit_occurred = True
                    exit_price = tp
                    exit_reason = "TP1"
            else:
                hit_sl = curr_bar.low <= sl
                hit_tp = curr_bar.high >= tp
                if hit_sl and hit_tp:
                    # Same bar: SL FIRST!
                    exit_occurred = True
                    exit_price = sl
                    exit_reason = "SL"
                elif hit_sl:
                    exit_occurred = True
                    exit_price = sl
                    exit_reason = "SL"
                elif hit_tp:
                    exit_occurred = True
                    exit_price = tp
                    exit_reason = "TP1"

            # Max holding timeout exit
            if not exit_occurred and open_position.bars_held >= max_holding_bars:
                exit_occurred = True
                exit_price = curr_bar.close
                exit_reason = "TIMEOUT"

            if exit_occurred:
                open_position.exit_time = bar_ts
                open_position.exit_price = exit_price
                open_position.exit_reason = exit_reason

                if direction == "SHORT":
                    gross_r = (open_position.entry_price - exit_price) / risk
                else:
                    gross_r = (exit_price - open_position.entry_price) / risk

                net_r = gross_r - open_position.friction_r
                open_position.r_multiple = round(net_r, 3)
                open_position.pnl_usd = round(net_r * risk, 2)

                executed_trades.append(open_position)
                bars_since_last_exit = 0
                open_position = None
                open_position_fill_idx = None

        # ----------------------------------------------------------------------
        # 2. Check Pending Orders Fill Model
        # ----------------------------------------------------------------------
        if open_position is None and pending_orders:
            remaining_orders: List[PendingOrder] = []
            for order in pending_orders:
                order.bars_pending += 1
                # Check expiration (index-free: bars active > zone_expiry_bars)
                if order.bars_pending > config.zone_expiry_bars:
                    # Expired without fill
                    if order.setup.setup_id in candidates_dict:
                        candidates_dict[order.setup.setup_id].skip_reason = "ZONE_EXPIRED"
                    continue

                # Check if price trades THROUGH zone price
                # Short limit fills only if high > entry_price
                # Long limit fills only if low < entry_price
                filled = False
                if order.direction == "SHORT" and curr_bar.high > order.entry_price:
                    filled = True
                elif order.direction == "LONG" and curr_bar.low < order.entry_price:
                    filled = True

                if filled:
                    risk = order.initial_risk_usd
                    fric_r = total_friction_usd / risk if risk > 0 else 0.0
                    pos = TradePosition(
                        position_id=len(executed_trades) + 1,
                        setup_id=order.setup.setup_id,
                        symbol=config.symbol,
                        direction=order.direction,
                        grade=order.setup.grade,
                        pool_type=order.setup.pool_type,
                        session=get_session_name(bar_ts),
                        htf_aligned=order.setup.checklist.htf_aligned,
                        day_of_week=bar_ts.strftime("%A"),
                        entry_time=bar_ts,
                        entry_price=order.entry_price,
                        stop_loss=order.stop_loss,
                        take_profit_1=order.take_profit_1,
                        take_profit_2=order.take_profit_2,
                        initial_risk_usd=risk,
                        friction_usd=total_friction_usd,
                        friction_r=round(fric_r, 4),
                    )
                    open_position = pos
                    open_position_fill_idx = t
                    if order.setup.setup_id in candidates_dict:
                        candidates_dict[order.setup.setup_id].was_executed = True
                        candidates_dict[order.setup.setup_id].skip_reason = None
                    # Only one position allowed, cancel other pending orders
                    break
                else:
                    remaining_orders.append(order)

            if open_position is not None:
                pending_orders = []
            else:
                pending_orders = remaining_orders

        # ----------------------------------------------------------------------
        # 3. Evaluate Market at as_of (Windowed lookback O(window))
        # ----------------------------------------------------------------------
        w_start = max(0, t + 1 - config.lookback_bars_15m)
        w_candles_15m = candles_15m[w_start : t + 1]
        earliest_w_ts = w_candles_15m[0].timestamp
        w_candles_1h = [c for c in candles_1h if earliest_w_ts <= c.timestamp <= bar_ts]

        setups = evaluate_sweep_market(
            w_candles_15m,
            candles_1h=w_candles_1h,
            as_of=as_of,
            config=config,
        )

        for s in setups:
            # Record or update candidate setup
            if s.setup_id not in candidates_dict:
                candidates_dict[s.setup_id] = CandidateSetupRecord(
                    setup_id=s.setup_id,
                    symbol=s.symbol,
                    direction=s.direction,
                    timestamp=s.sweep_bar_time,
                    state=s.state.value if hasattr(s.state, "value") else str(s.state),
                    grade=s.grade,
                    pool_id=s.pool_id,
                    pool_type=s.pool_type,
                    pool_price=s.pool_price,
                    sweep_extreme=s.sweep_extreme,
                    skip_reason=s.no_setup_reason or s.invalidation_reason,
                    was_executed=False,
                )
            else:
                # Update state if progressed
                rec = candidates_dict[s.setup_id]
                rec.state = s.state.value if hasattr(s.state, "value") else str(s.state)
                if s.grade:
                    rec.grade = s.grade
                if s.no_setup_reason or s.invalidation_reason:
                    rec.skip_reason = s.no_setup_reason or s.invalidation_reason

            # If setup is CONFIRMED, consider for execution
            if s.state == SetupState.CONFIRMED and s.plan is not None and s.zone is not None:
                # Check if position already open
                if open_position is not None:
                    candidates_dict[s.setup_id].skip_reason = "POSITION_ALREADY_OPEN"
                    continue

                # Check if cooldown is active
                if bars_since_last_exit <= cooldown_bars:
                    candidates_dict[s.setup_id].skip_reason = "COOLDOWN_ACTIVE"
                    continue

                # Check if already pending
                already_pending = any(p.setup.setup_id == s.setup_id for p in pending_orders)
                if not already_pending:
                    pending_orders.append(
                        PendingOrder(
                            setup=s,
                            placed_time=bar_ts,
                            entry_price=s.plan.entry_price,
                            stop_loss=s.plan.stop_loss,
                            take_profit_1=s.plan.take_profit_1,
                            take_profit_2=s.plan.take_profit_2,
                            initial_risk_usd=s.plan.risk_usd,
                            direction=s.direction,
                            bars_pending=0,
                        )
                    )

    # --------------------------------------------------------------------------
    # 4. Compute Forward Outcomes for All Candidate Setups
    # --------------------------------------------------------------------------
    for s_id, cand in candidates_dict.items():
        start_idx = time_to_idx.get(cand.timestamp)
        if start_idx is None or start_idx >= n_bars - 1:
            continue

        # Forward trace up to 100 bars
        direction = cand.direction
        entry_p = cand.pool_price
        risk_p = max(1.0, abs(cand.sweep_extreme - cand.pool_price))

        if direction == "SHORT":
            sl_p = cand.sweep_extreme + (config.stop_buffer_atr * 2.0)
            tp1_p = entry_p - risk_p
            tp2_p = entry_p - (2.0 * risk_p)
        else:
            sl_p = cand.sweep_extreme - (config.stop_buffer_atr * 2.0)
            tp1_p = entry_p + risk_p
            tp2_p = entry_p + (2.0 * risk_p)

        mfe = 0.0
        mae = 0.0
        reached_1r = False
        reached_2r = False
        hit_sl = False
        res_bars = 0
        final_r = 0.0

        for f_idx in range(start_idx + 1, min(n_bars, start_idx + 101)):
            c_f = candles_15m[f_idx]
            res_bars += 1

            if direction == "SHORT":
                fav = entry_p - c_f.low
                adv = c_f.high - entry_p
                mfe = max(mfe, fav / risk_p)
                mae = max(mae, adv / risk_p)
                if c_f.low <= tp1_p:
                    reached_1r = True
                if c_f.low <= tp2_p:
                    reached_2r = True
                if c_f.high >= sl_p:
                    hit_sl = True
                    final_r = -1.0
                    break
                if reached_2r:
                    final_r = 2.0
                    break
            else:
                fav = c_f.high - entry_p
                adv = entry_p - c_f.low
                mfe = max(mfe, fav / risk_p)
                mae = max(mae, adv / risk_p)
                if c_f.high >= tp1_p:
                    reached_1r = True
                if c_f.high >= tp2_p:
                    reached_2r = True
                if c_f.low <= sl_p:
                    hit_sl = True
                    final_r = -1.0
                    break
                if reached_2r:
                    final_r = 2.0
                    break

        cand.reached_1r = reached_1r
        cand.reached_2r = reached_2r
        cand.hit_sl = hit_sl
        cand.mfe = round(mfe, 2)
        cand.mae = round(mae, 2)
        cand.bars_to_resolution = res_bars
        cand.r_multiple = round(final_r, 2)

    return executed_trades, list(candidates_dict.values())
