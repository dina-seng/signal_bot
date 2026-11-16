"""Backtest Adapter plugging CRTStrategy into the Sweep Backtest & Walk-Forward Harness.

Uses the same production code path without duplicating simulation logic.
"""

from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple

from app.schemas.candle import CandleCreate
from app.schemas.signal import SignalDirection
from app.services.sweep.backtest.engine import run_walk_forward_backtest
from app.services.sweep.backtest.models import CandidateSetupRecord, TradePosition
from app.services.sweep.config import SweepConfig
from app.services.sweep.detector import EntryZone, SetupPlan
from app.services.sweep.state_machine import SetupChecklist, SetupState, SweepSetup, build_setup_id


def adapt_crt_result_to_sweep_setup(
    result: Any,
    symbol: str,
    as_of: datetime,
) -> Optional[SweepSetup]:
    """Convert a CRT StrategyResult into a SweepSetup for the backtest harness."""
    meta = result.metadata or {}
    setup_state = meta.get("setup_state", "NO_SETUP")
    if setup_state != "CONFIRMED_SETUP" and result.direction not in (SignalDirection.BUY, SignalDirection.SELL):
        return None

    direction = "LONG" if result.direction == SignalDirection.BUY else "SHORT"
    pool_type = meta.get("swept_level_type", "BENCHMARK_RANGE_EXTREME")
    pool_id = f"{symbol}_{direction}_{pool_type}_{int(as_of.timestamp())}"
    sweep_bar_time = as_of
    sweep_extreme = float(meta.get("breach_point", result.entry_price))

    setup_id = build_setup_id(symbol, direction, pool_id, sweep_bar_time)

    # Geometry & Targets
    entry_p = float(result.entry_price)
    sl_p = float(result.stop_loss)
    tp1_p = float(result.take_profit_1)
    tp2_p = float(result.take_profit_2) if result.take_profit_2 > 0 else None
    risk_usd = abs(entry_p - sl_p)
    rr_tp1 = float(meta.get("real_rr_tp1", result.risk_reward or 1.5))
    rr_tp2 = float(meta.get("real_rr_tp2", 2.5)) if tp2_p else None

    # Entry zone
    zone_h = float(meta.get("zone_high", entry_p + 0.50))
    zone_l = float(meta.get("zone_low", entry_p - 0.50))

    plan = SetupPlan(
        direction=direction,
        entry_price=entry_p,
        stop_loss=sl_p,
        take_profit_1=tp1_p,
        take_profit_2=tp2_p,
        risk_usd=risk_usd,
        reward_usd_tp1=abs(tp1_p - entry_p),
        reward_usd_tp2=abs(tp2_p - entry_p) if tp2_p else None,
        risk_reward_tp1=rr_tp1,
        risk_reward_tp2=rr_tp2,
        sweep_extreme=sweep_extreme,
        displacement_extreme=float(meta.get("displacement_extreme", entry_p)),
        in_premium_discount=True,
        tp1_pool_id=f"TP1_{pool_id}",
        tp2_pool_id=f"TP2_{pool_id}" if tp2_p else None,
    )

    zone = EntryZone(
        zone_type=meta.get("zone_type", "FVG"),
        entry_price=entry_p,
        zone_high=zone_h,
        zone_low=zone_l,
        created_time=as_of,
        is_fvg=(meta.get("zone_type") == "FVG"),
    )

    tier = meta.get("quality_tier", "A")
    grade = "A" if tier in ("A+", "A") else "B"

    checklist = SetupChecklist(
        valid_sweep_penetration=True,
        rejected_within_max_bars=True,
        mss_displacement_confirmed=True,
        fvg_or_ob_zone_formed=True,
        premium_discount_satisfied=True,
        risk_reward_ge_minimum=(rr_tp1 >= 1.0),
        htf_aligned=(meta.get("htf_trend_source") in ("mtf_1h", "mtf_4h", "explicit")),
        is_major_pool=("PD" in pool_type or "Session" in pool_type or "Equal" in pool_type),
        strong_displacement=True,
        in_kill_zone=(meta.get("session_name") in ("London Session", "New York Session")),
        has_clean_fvg=True,
        risk_reward_ge_2=(rr_tp1 >= 2.0),
    )

    return SweepSetup(
        setup_id=setup_id,
        symbol=symbol,
        direction=direction,
        state=SetupState.CONFIRMED,
        grade=grade,
        quality_score=int(result.score // 15),
        pool_id=pool_id,
        pool_type=pool_type,
        pool_price=sweep_extreme,
        sweep_bar_time=sweep_bar_time,
        sweep_extreme=sweep_extreme,
        as_of=as_of,
        plan=plan,
        zone=zone,
        checklist=checklist,
    )

