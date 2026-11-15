"""Liquidity-Sweep (SMC) Engine orchestrating pure analysis with strict zero lookahead."""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from app.schemas.candle import CandleCreate
from app.services.sweep.atr import calculate_atr
from app.services.sweep.config import SweepConfig
from app.services.sweep.detector import (
    calculate_sl_tp_and_rr,
    construct_entry_zone,
    detect_htf_bias,
    find_mss_and_displacement,
    find_valid_sweep,
)
from app.services.sweep.pivots import detect_pivots
from app.services.sweep.pools import identify_liquidity_pools
from app.services.sweep.state_machine import (
    SetupChecklist,
    SetupState,
    SweepSetup,
    assign_grade,
    build_setup_id,
)

MAJOR_POOL_TYPES = {
    "EQUAL_HIGHS",
    "EQUAL_LOWS",
    "PDH",
    "PDL",
    "ASIA_HIGH",
    "ASIA_LOW",
    "LONDON_HIGH",
    "LONDON_LOW",
}


def evaluate_sweep_market(
    candles_15m: Sequence[CandleCreate],
    candles_1h: Sequence[CandleCreate] = (),
    candles_4h: Sequence[CandleCreate] = (),
    as_of: Optional[datetime] = None,
    config: Optional[SweepConfig] = None,
) -> List[SweepSetup]:
    """Pure analysis engine evaluating liquidity sweep setups with strict zero lookahead.

    Hard Rule 3: No lookahead. Every detector receives only candles whose close time <= as_of.
    No wall-clock calls (datetime.now) inside analysis code; as_of is always passed in.
    """
    if config is None:
        config = SweepConfig()

    if not candles_15m:
        return []

    # 1. Enforce strict as_of prefix filtering
    if as_of is not None:
        as_of_utc = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        last_c = candles_15m[-1]
        last_c_close = (last_c.timestamp if last_c.timestamp.tzinfo else last_c.timestamp.replace(tzinfo=timezone.utc)) + timedelta(minutes=15)
        if last_c_close <= as_of_utc:
            eval_15m = list(candles_15m)
        else:
            eval_15m = [
                c for c in candles_15m
                if (c.timestamp if c.timestamp.tzinfo else c.timestamp.replace(tzinfo=timezone.utc)) + timedelta(minutes=15) <= as_of_utc
            ]

        if candles_1h:
            eval_1h = [
                c for c in candles_1h
                if (c.timestamp if c.timestamp.tzinfo else c.timestamp.replace(tzinfo=timezone.utc)) + timedelta(hours=1) <= as_of_utc
            ]
        else:
            eval_1h = []
    else:
        eval_15m = list(candles_15m)
        eval_1h = list(candles_1h)
        last_c = eval_15m[-1]
        as_of_utc = (last_c.timestamp if last_c.timestamp.tzinfo else last_c.timestamp.replace(tzinfo=timezone.utc)) + timedelta(minutes=15)

    if len(eval_15m) < 20:
        return []

    # 2. Derive ATR(14)
    atr_values = calculate_atr(eval_15m, period=config.atr_period)

    # 3. Detect 15m Pivots and resting Liquidity Pools
    pivots_15m = detect_pivots(eval_15m, n=config.pivot_n_15m)
    pools = identify_liquidity_pools(eval_15m, eval_1h, atr_values, config)
    pools = sorted(pools, key=lambda p: 0 if p.pool_type in MAJOR_POOL_TYPES else 1)

    # 4. Determine HTF Trend Bias from 1h structure
    htf_bias = detect_htf_bias(eval_1h, n=config.pivot_n_htf)

    setups: List[SweepSetup] = []
    current_bar_idx = len(eval_15m) - 1

    # Track swept pools to prevent multi-sweeps on the same pool
    swept_pool_ids = set()

    # Scan past bars looking for sweeps
    # Look back up to 50 bars to find active or recent setups
    scan_start_idx = max(config.pivot_n_15m * 2, current_bar_idx - 60)

    for bar_idx in range(scan_start_idx, current_bar_idx + 1):
        atr_at_bar = atr_values[bar_idx]
        sweep_event = find_valid_sweep(bar_idx, eval_15m, pools, atr_at_bar, config)

        if sweep_event is None:
            continue

        pool = sweep_event.pool
        if pool.id in swept_pool_ids:
            continue
        swept_pool_ids.add(pool.id)

        # Build stable setup ID
        setup_id = build_setup_id(config.symbol, sweep_event.direction, pool.id, sweep_event.sweep_bar_time)

        # Evaluate progress since sweep
        bars_since_sweep = current_bar_idx - bar_idx

        # Check for immediate breakout invalidation
        # If any subsequent candle closed beyond the sweep extreme, the sweep is invalidated
        is_extreme_broken = False
        for k in range(bar_idx + 1, current_bar_idx + 1):
            c_check = eval_15m[k]
            if sweep_event.direction == "SHORT" and c_check.close > sweep_event.sweep_extreme:
                is_extreme_broken = True
                break
            elif sweep_event.direction == "LONG" and c_check.close < sweep_event.sweep_extreme:
                is_extreme_broken = True
                break

        if is_extreme_broken:
            # Setup invalidated due to price closing beyond the sweep extreme
            setups.append(
                SweepSetup(
                    setup_id=setup_id,
                    symbol=config.symbol,
                    direction=sweep_event.direction,
                    state=SetupState.INVALIDATED,
                    grade=None,
                    quality_score=0,
                    pool_id=pool.id,
                    pool_type=pool.pool_type,
                    pool_price=pool.price,
                    sweep_bar_time=sweep_event.sweep_bar_time,
                    sweep_extreme=sweep_event.sweep_extreme,
                    as_of=as_of_utc,
                    plan=None,
                    zone=None,
                    checklist=SetupChecklist(
                        valid_sweep_penetration=True,
                        rejected_within_max_bars=True,
                        mss_displacement_confirmed=False,
                        fvg_or_ob_zone_formed=False,
                        premium_discount_satisfied=False,
                        risk_reward_ge_minimum=False,
                        htf_aligned=False,
                        is_major_pool=pool.pool_type in MAJOR_POOL_TYPES,
                        strong_displacement=False,
                        in_kill_zone=sweep_event.in_kill_zone,
                        has_clean_fvg=False,
                        risk_reward_ge_2=False,
                    ),
                    invalidation_reason="Price closed beyond sweep extreme (breakout)",
                )
            )
            continue

        # Look for MSS and displacement
        mss_result = find_mss_and_displacement(sweep_event, eval_15m, pivots_15m, atr_values, config)

        if mss_result is None:
            # No MSS yet
            if bars_since_sweep <= config.max_mss_bars:
                state = SetupState.WAITING_CONFIRMATION if sweep_event.rejection_bars_count <= config.max_rejection_bars else SetupState.POTENTIAL
                setups.append(
                    SweepSetup(
                        setup_id=setup_id,
                        symbol=config.symbol,
                        direction=sweep_event.direction,
                        state=state,
                        grade=None,
                        quality_score=0,
                        pool_id=pool.id,
                        pool_type=pool.pool_type,
                        pool_price=pool.price,
                        sweep_bar_time=sweep_event.sweep_bar_time,
                        sweep_extreme=sweep_event.sweep_extreme,
                        as_of=as_of_utc,
                        plan=None,
                        zone=None,
                        checklist=SetupChecklist(
                            valid_sweep_penetration=True,
                            rejected_within_max_bars=True,
                            mss_displacement_confirmed=False,
                            fvg_or_ob_zone_formed=False,
                            premium_discount_satisfied=False,
                            risk_reward_ge_minimum=False,
                            htf_aligned=(sweep_event.direction == "LONG" and htf_bias == "BULLISH") or (sweep_event.direction == "SHORT" and htf_bias == "BEARISH"),
                            is_major_pool=pool.pool_type in MAJOR_POOL_TYPES,
                            strong_displacement=False,
                            in_kill_zone=sweep_event.in_kill_zone,
                            has_clean_fvg=False,
                            risk_reward_ge_2=False,
                        ),
                    )
                )
            else:
                # MSS window expired without confirmation
                setups.append(
                    SweepSetup(
                        setup_id=setup_id,
                        symbol=config.symbol,
                        direction=sweep_event.direction,
                        state=SetupState.NO_SETUP,
                        grade=None,
                        quality_score=0,
                        pool_id=pool.id,
                        pool_type=pool.pool_type,
                        pool_price=pool.price,
                        sweep_bar_time=sweep_event.sweep_bar_time,
                        sweep_extreme=sweep_event.sweep_extreme,
                        as_of=as_of_utc,
                        plan=None,
                        zone=None,
                        checklist=SetupChecklist(
                            valid_sweep_penetration=True,
                            rejected_within_max_bars=True,
                            mss_displacement_confirmed=False,
                            fvg_or_ob_zone_formed=False,
                            premium_discount_satisfied=False,
                            risk_reward_ge_minimum=False,
                            htf_aligned=False,
                            is_major_pool=pool.pool_type in MAJOR_POOL_TYPES,
                            strong_displacement=False,
                            in_kill_zone=sweep_event.in_kill_zone,
                            has_clean_fvg=False,
                            risk_reward_ge_2=False,
                        ),
                        no_setup_reason="MSS confirmation not observed within 12 bars",
                    )
                )
            continue

        disp_idx, disp_extreme, is_strong_disp = mss_result

        # Construct Entry Zone (FVG or OB) with Premium / Discount Gate
        zone = construct_entry_zone(sweep_event, disp_idx, disp_extreme, eval_15m, config)
        if zone is None:
            setups.append(
                SweepSetup(
                    setup_id=setup_id,
                    symbol=config.symbol,
                    direction=sweep_event.direction,
                    state=SetupState.NO_SETUP,
                    grade=None,
                    quality_score=0,
                    pool_id=pool.id,
                    pool_type=pool.pool_type,
                    pool_price=pool.price,
                    sweep_bar_time=sweep_event.sweep_bar_time,
                    sweep_extreme=sweep_event.sweep_extreme,
                    as_of=as_of_utc,
                    plan=None,
                    zone=None,
                    checklist=SetupChecklist(
                        valid_sweep_penetration=True,
                        rejected_within_max_bars=True,
                        mss_displacement_confirmed=True,
                        fvg_or_ob_zone_formed=False,
                        premium_discount_satisfied=False,
                        risk_reward_ge_minimum=False,
                        htf_aligned=False,
                        is_major_pool=pool.pool_type in MAJOR_POOL_TYPES,
                        strong_displacement=is_strong_disp,
                        in_kill_zone=sweep_event.in_kill_zone,
                        has_clean_fvg=False,
                        risk_reward_ge_2=False,
                    ),
                    no_setup_reason="No valid FVG or OB in premium/discount zone",
                )
            )
            continue

        # Check Zone Expiry
        if current_bar_idx > zone.expiry_bar_index:
            setups.append(
                SweepSetup(
                    setup_id=setup_id,
                    symbol=config.symbol,
                    direction=sweep_event.direction,
                    state=SetupState.INVALIDATED,
                    grade=None,
                    quality_score=0,
                    pool_id=pool.id,
                    pool_type=pool.pool_type,
                    pool_price=pool.price,
                    sweep_bar_time=sweep_event.sweep_bar_time,
                    sweep_extreme=sweep_event.sweep_extreme,
                    as_of=as_of_utc,
                    plan=None,
                    zone=zone,
                    checklist=SetupChecklist(
                        valid_sweep_penetration=True,
                        rejected_within_max_bars=True,
                        mss_displacement_confirmed=True,
                        fvg_or_ob_zone_formed=True,
                        premium_discount_satisfied=True,
                        risk_reward_ge_minimum=False,
                        htf_aligned=False,
                        is_major_pool=pool.pool_type in MAJOR_POOL_TYPES,
                        strong_displacement=is_strong_disp,
                        in_kill_zone=sweep_event.in_kill_zone,
                        has_clean_fvg=zone.is_fvg,
                        risk_reward_ge_2=False,
                    ),
                    invalidation_reason="Entry zone expired after 16 bars without fill",
                )
            )
            continue

        # Calculate Stop Loss, TP1, TP2, and check RR >= 1.5
        plan = calculate_sl_tp_and_rr(sweep_event, zone, disp_extreme, pools, atr_at_bar, config)
        if plan is None:
            setups.append(
                SweepSetup(
                    setup_id=setup_id,
                    symbol=config.symbol,
                    direction=sweep_event.direction,
                    state=SetupState.NO_SETUP,
                    grade=None,
                    quality_score=0,
                    pool_id=pool.id,
                    pool_type=pool.pool_type,
                    pool_price=pool.price,
                    sweep_bar_time=sweep_event.sweep_bar_time,
                    sweep_extreme=sweep_event.sweep_extreme,
                    as_of=as_of_utc,
                    plan=None,
                    zone=zone,
                    checklist=SetupChecklist(
                        valid_sweep_penetration=True,
                        rejected_within_max_bars=True,
                        mss_displacement_confirmed=True,
                        fvg_or_ob_zone_formed=True,
                        premium_discount_satisfied=True,
                        risk_reward_ge_minimum=False,
                        htf_aligned=False,
                        is_major_pool=pool.pool_type in MAJOR_POOL_TYPES,
                        strong_displacement=is_strong_disp,
                        in_kill_zone=sweep_event.in_kill_zone,
                        has_clean_fvg=zone.is_fvg,
                        risk_reward_ge_2=False,
                    ),
                    no_setup_reason="Risk:Reward to TP1 is below minimum 1.5 or no opposing pool",
                )
            )
            continue

        # All Gates Passed => CONFIRMED SETUP!
        htf_aligned = (
            (sweep_event.direction == "LONG" and htf_bias == "BULLISH")
            or (sweep_event.direction == "SHORT" and htf_bias == "BEARISH")
        )
        is_major = pool.pool_type in MAJOR_POOL_TYPES
        rr_ge_2 = plan.risk_reward_tp1 >= config.high_rr_threshold

        checklist = SetupChecklist(
            valid_sweep_penetration=True,
            rejected_within_max_bars=True,
            mss_displacement_confirmed=True,
            fvg_or_ob_zone_formed=True,
            premium_discount_satisfied=True,
            risk_reward_ge_minimum=True,
            htf_aligned=htf_aligned,
            is_major_pool=is_major,
            strong_displacement=is_strong_disp,
            in_kill_zone=sweep_event.in_kill_zone,
            has_clean_fvg=zone.is_fvg,
            risk_reward_ge_2=rr_ge_2,
        )

        grade = assign_grade(checklist)
        quality_score = (
            int(htf_aligned)
            + int(is_major)
            + int(is_strong_disp)
            + int(sweep_event.in_kill_zone)
            + int(zone.is_fvg)
            + int(rr_ge_2)
        )

        setups.append(
            SweepSetup(
                setup_id=setup_id,
                symbol=config.symbol,
                direction=sweep_event.direction,
                state=SetupState.CONFIRMED,
                grade=grade,
                quality_score=quality_score,
                pool_id=pool.id,
                pool_type=pool.pool_type,
                pool_price=pool.price,
                sweep_bar_time=sweep_event.sweep_bar_time,
                sweep_extreme=sweep_event.sweep_extreme,
                as_of=as_of_utc,
                plan=plan,
                zone=zone,
                checklist=checklist,
            )
        )

    return setups
