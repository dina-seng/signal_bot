"""Pure detection functions for liquidity sweeps, MSS/CHoCH, FVG/OB zones, and trade geometry."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Sequence, Tuple

from app.schemas.candle import CandleCreate
from app.services.sweep.config import SweepConfig
from app.services.sweep.pivots import Pivot, detect_pivots
from app.services.sweep.pools import LiquidityPool, is_kill_zone


@dataclass(frozen=True)
class SweepEvent:
    """Represents a validated liquidity sweep."""
    pool: LiquidityPool
    sweep_bar_index: int
    sweep_bar_time: datetime
    sweep_extreme: float      # Highest high (bearish sweep) or lowest low (bullish sweep)
    direction: str            # 'SHORT' (swept high) or 'LONG' (swept low)
    penetration_atr: float    # Penetration beyond pool in ATR multiples
    rejection_bars_count: int # Bars until close returned inside level
    in_kill_zone: bool


@dataclass(frozen=True)
class EntryZone:
    """Represents the FVG or Order Block entry zone."""
    zone_type: str            # 'FVG' or 'ORDER_BLOCK'
    entry_price: float        # Limit entry price (FVG midpoint or OB open)
    zone_high: float
    zone_low: float
    created_time: datetime
    is_fvg: bool
    expiry_time: Optional[datetime] = None
    created_bar_index: Optional[int] = None
    expiry_bar_index: Optional[int] = None


@dataclass(frozen=True)
class SetupPlan:
    """Complete geometric plan for a confirmed setup."""
    direction: str
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: Optional[float]
    risk_usd: float
    reward_usd_tp1: float
    reward_usd_tp2: Optional[float]
    risk_reward_tp1: float
    risk_reward_tp2: Optional[float]
    sweep_extreme: float
    displacement_extreme: float
    in_premium_discount: bool
    tp1_pool_id: str
    tp2_pool_id: Optional[str]


def detect_htf_bias(candles_1h: Sequence[CandleCreate], n: int = 2) -> str:
    """Determine HTF trend bias from confirmed 1h swing structure.

    Returns: 'BULLISH', 'BEARISH', or 'NEUTRAL'.
    """
    if len(candles_1h) < 10:
        return "NEUTRAL"

    pivots = detect_pivots(candles_1h, n=n)
    highs = [p for p in pivots if p.pivot_type == "HIGH"]
    lows = [p for p in pivots if p.pivot_type == "LOW"]

    if len(highs) >= 2 and len(lows) >= 2:
        last_high = highs[-1].price
        prev_high = highs[-2].price
        last_low = lows[-1].price
        prev_low = lows[-2].price

        if last_high > prev_high and last_low > prev_low:
            return "BULLISH"
        elif last_high < prev_high and last_low < prev_low:
            return "BEARISH"

    return "NEUTRAL"


def find_valid_sweep(
    candle_idx: int,
    candles_15m: Sequence[CandleCreate],
    pools: Sequence[LiquidityPool],
    atr: float,
    config: SweepConfig,
) -> Optional[SweepEvent]:
    """Check if the bar at candle_idx completes a valid liquidity sweep.

    Rules:
    - Wick trades beyond pool by >= 0.05 * ATR.
    - Within max_rejection_bars (3 bars), a close returns back inside the level.
    - If price keeps closing beyond the level, it is a breakout, NOT a sweep.
    """
    curr_c = candles_15m[candle_idx]
    pen_req = config.min_sweep_penetration_atr * atr

    # Prioritize major pool types (equal levels, session pools, PDH/PDL) over individual minor swing pivots
    major_types = {"EQUAL_HIGHS", "EQUAL_LOWS", "PDH", "PDL", "ASIA_HIGH", "ASIA_LOW", "LONDON_HIGH", "LONDON_LOW"}
    sorted_pools = sorted(pools, key=lambda p: 0 if p.pool_type in major_types else 1)

    for pool in sorted_pools:
        # A pool is only eligible if it was confirmed strictly before the sweep bar
        if pool.confirm_time >= curr_c.timestamp:
            continue
        if pool.swept:
            continue

        if pool.side == "BUYSIDE":
            # Sweeping high -> Looking for short
            if curr_c.high >= pool.price + pen_req:
                # Check rejection: within max_rejection_bars, a close must be < pool.price
                rejected = False
                bars_to_reject = 0
                sweep_extreme = curr_c.high

                for step in range(config.max_rejection_bars):
                    check_idx = candle_idx + step
                    if check_idx >= len(candles_15m):
                        break
                    check_c = candles_15m[check_idx]
                    sweep_extreme = max(sweep_extreme, check_c.high)
                    if check_c.close < pool.price:
                        rejected = True
                        bars_to_reject = step + 1
                        break

                if rejected:
                    penetration = (sweep_extreme - pool.price) / atr if atr > 0 else 0.0
                    return SweepEvent(
                        pool=pool,
                        sweep_bar_index=candle_idx,
                        sweep_bar_time=curr_c.timestamp,
                        sweep_extreme=sweep_extreme,
                        direction="SHORT",
                        penetration_atr=penetration,
                        rejection_bars_count=bars_to_reject,
                        in_kill_zone=is_kill_zone(curr_c.timestamp, config),
                    )

        elif pool.side == "SELLSIDE":
            # Sweeping low -> Looking for long
            if curr_c.low <= pool.price - pen_req:
                rejected = False
                bars_to_reject = 0
                sweep_extreme = curr_c.low

                for step in range(config.max_rejection_bars):
                    check_idx = candle_idx + step
                    if check_idx >= len(candles_15m):
                        break
                    check_c = candles_15m[check_idx]
                    sweep_extreme = min(sweep_extreme, check_c.low)
                    if check_c.close > pool.price:
                        rejected = True
                        bars_to_reject = step + 1
                        break

                if rejected:
                    penetration = (pool.price - sweep_extreme) / atr if atr > 0 else 0.0
                    return SweepEvent(
                        pool=pool,
                        sweep_bar_index=candle_idx,
                        sweep_bar_time=curr_c.timestamp,
                        sweep_extreme=sweep_extreme,
                        direction="LONG",
                        penetration_atr=penetration,
                        rejection_bars_count=bars_to_reject,
                        in_kill_zone=is_kill_zone(curr_c.timestamp, config),
                    )

    return None


def find_mss_and_displacement(
    sweep: SweepEvent,
    candles_15m: Sequence[CandleCreate],
    pivots_15m: Sequence[Pivot],
    atr_values: Sequence[float],
    config: SweepConfig,
) -> Optional[Tuple[int, float, bool]]:
    """Check for Market Structure Shift (MSS) and displacement within max_mss_bars (12 bars).

    Requirements:
    1. Displacement candle:
       - body >= 0.8 * ATR
       - body >= 60% of range (high - low)
    2. Displacement candle closes beyond the most recent opposing confirmed short-term pivot.
    
    Returns:
        (displacement_bar_index, displacement_extreme, is_strong_displacement) or None
    """
    sweep_idx = sweep.sweep_bar_index
    end_idx = min(len(candles_15m), sweep_idx + config.max_mss_bars + 1)

    # Find the most recent opposing confirmed pivot prior to or at the sweep
    if sweep.direction == "SHORT":
        # Swept high => need opposing low pivot to break downwards
        opposing_pivots = [
            p for p in pivots_15m
            if p.pivot_type == "LOW" and p.confirm_index <= sweep_idx
        ]
        if not opposing_pivots:
            return None
        target_pivot = opposing_pivots[-1]

        # Scan for displacement candle closing below target_pivot.price
        for idx in range(sweep_idx + 1, end_idx):
            c = candles_15m[idx]
            body = c.open - c.close  # Bearish displacement body
            candle_range = c.high - c.low
            atr = atr_values[idx] if idx < len(atr_values) else 10.0

            if body >= config.displacement_body_atr * atr and candle_range > 0 and (body / candle_range) >= config.displacement_body_ratio:
                if c.close < target_pivot.price:
                    # Confirmed MSS!
                    is_strong = body >= config.strong_displacement_atr * atr
                    # Find lowest point of the displacement leg
                    disp_extreme = min(c.low for c in candles_15m[sweep_idx:idx + 1])
                    return idx, disp_extreme, is_strong

    elif sweep.direction == "LONG":
        # Swept low => need opposing high pivot to break upwards
        opposing_pivots = [
            p for p in pivots_15m
            if p.pivot_type == "HIGH" and p.confirm_index <= sweep_idx
        ]
        if not opposing_pivots:
            return None
        target_pivot = opposing_pivots[-1]

        for idx in range(sweep_idx + 1, end_idx):
            c = candles_15m[idx]
            body = c.close - c.open  # Bullish displacement body
            candle_range = c.high - c.low
            atr = atr_values[idx] if idx < len(atr_values) else 10.0

            if body >= config.displacement_body_atr * atr and candle_range > 0 and (body / candle_range) >= config.displacement_body_ratio:
                if c.close > target_pivot.price:
                    is_strong = body >= config.strong_displacement_atr * atr
                    disp_extreme = max(c.high for c in candles_15m[sweep_idx:idx + 1])
                    return idx, disp_extreme, is_strong

    return None


def construct_entry_zone(
    sweep: SweepEvent,
    disp_bar_idx: int,
    disp_extreme: float,
    candles_15m: Sequence[CandleCreate],
    config: SweepConfig,
) -> Optional[EntryZone]:
    """Construct Fair Value Gap (FVG) or Order Block (OB) entry zone.

    FVG rule:
    - Bullish: low[k] > high[k-2], midpoint = (high[k-2] + low[k]) / 2
    - Bearish: high[k] < low[k-2], midpoint = (high[k] + low[k-2]) / 2

    Order Block rule:
    - Last opposing candle before displacement leg. Entry = OB open.

    Premium / Discount gate:
    - Range is [sweep_extreme, disp_extreme].
    - Shorts only from premium half (>= 50% retracement).
    - Longs only from discount half (<= 50% retracement).
    """
    sweep_idx = sweep.sweep_bar_index
    direction = sweep.direction
    range_span = abs(sweep.sweep_extreme - disp_extreme)
    if range_span <= 0:
        return None
    mid_range = (sweep.sweep_extreme + disp_extreme) / 2.0

    # 1. Search for FVG along the displacement leg
    found_fvg: Optional[EntryZone] = None
    for k in range(disp_bar_idx, max(sweep_idx + 1, disp_bar_idx - 3), -1):
        if k >= 2 and k < len(candles_15m):
            if direction == "SHORT":
                # Bearish FVG: high[k] < low[k-2]
                if candles_15m[k].high < candles_15m[k - 2].low:
                    z_high = candles_15m[k - 2].low
                    z_low = candles_15m[k].high
                    midpoint = (z_high + z_low) / 2.0
                    # Premium gate: midpoint must be >= mid_range
                    if midpoint >= mid_range:
                        c_ts = candles_15m[k].timestamp
                        found_fvg = EntryZone(
                            zone_type="FVG",
                            entry_price=midpoint,
                            zone_high=z_high,
                            zone_low=z_low,
                            created_time=c_ts,
                            expiry_time=c_ts + timedelta(minutes=15 * config.zone_expiry_bars),
                            created_bar_index=k,
                            expiry_bar_index=k + config.zone_expiry_bars,
                            is_fvg=True,
                        )
                        break

            elif direction == "LONG":
                # Bullish FVG: low[k] > high[k-2]
                if candles_15m[k].low > candles_15m[k - 2].high:
                    z_low = candles_15m[k - 2].high
                    z_high = candles_15m[k].low
                    midpoint = (z_high + z_low) / 2.0
                    # Discount gate: midpoint must be <= mid_range
                    if midpoint <= mid_range:
                        c_ts = candles_15m[k].timestamp
                        found_fvg = EntryZone(
                            zone_type="FVG",
                            entry_price=midpoint,
                            zone_high=z_high,
                            zone_low=z_low,
                            created_time=c_ts,
                            expiry_time=c_ts + timedelta(minutes=15 * config.zone_expiry_bars),
                            created_bar_index=k,
                            expiry_bar_index=k + config.zone_expiry_bars,
                            is_fvg=True,
                        )
                        break

    if found_fvg:
        return found_fvg

    # 2. Fallback to Order Block (OB) if no FVG
    for k in range(disp_bar_idx - 1, sweep_idx - 1, -1):
        c = candles_15m[k]
        if direction == "SHORT":
            # Last bullish candle before drop
            if c.close >= c.open:
                entry = c.open
                if entry >= mid_range:
                    c_ts = c.timestamp
                    return EntryZone(
                        zone_type="ORDER_BLOCK",
                        entry_price=entry,
                        zone_high=c.high,
                        zone_low=c.low,
                        created_time=c_ts,
                        expiry_time=c_ts + timedelta(minutes=15 * config.zone_expiry_bars),
                        created_bar_index=k,
                        expiry_bar_index=k + config.zone_expiry_bars,
                        is_fvg=False,
                    )
        elif direction == "LONG":
            # Last bearish candle before rally
            if c.close <= c.open:
                entry = c.open
                if entry <= mid_range:
                    c_ts = c.timestamp
                    return EntryZone(
                        zone_type="ORDER_BLOCK",
                        entry_price=entry,
                        zone_high=c.high,
                        zone_low=c.low,
                        created_time=c_ts,
                        expiry_time=c_ts + timedelta(minutes=15 * config.zone_expiry_bars),
                        created_bar_index=k,
                        expiry_bar_index=k + config.zone_expiry_bars,
                        is_fvg=False,
                    )

    return None


def calculate_sl_tp_and_rr(
    sweep: SweepEvent,
    zone: EntryZone,
    disp_extreme: float,
    pools: Sequence[LiquidityPool],
    atr: float,
    config: SweepConfig,
) -> Optional[SetupPlan]:
    """Calculate Stop Loss, TP1/TP2 targets from opposing pools, and enforce RR(TP1) >= 1.5."""
    entry = zone.entry_price
    direction = sweep.direction

    # Stop Loss calculation
    # Short: sweep_high + 0.15*ATR + spread
    # Long: sweep_low - 0.15*ATR - spread
    if direction == "SHORT":
        stop_loss = sweep.sweep_extreme + (config.stop_buffer_atr * atr) + config.spread_usd
        risk = stop_loss - entry
    else:
        stop_loss = sweep.sweep_extreme - (config.stop_buffer_atr * atr) - config.spread_usd
        risk = entry - stop_loss

    if risk <= 0:
        return None

    # Find nearest opposing liquidity pools for TP1 and TP2
    opposing_pools: List[LiquidityPool] = []
    for p in pools:
        if p.confirm_time >= sweep.sweep_bar_time:
            continue
        if direction == "SHORT":
            # Short target is sell-side liquidity below entry
            if p.side == "SELLSIDE" and p.price < entry:
                opposing_pools.append(p)
        else:
            # Long target is buy-side liquidity above entry
            if p.side == "BUYSIDE" and p.price > entry:
                opposing_pools.append(p)

    if not opposing_pools:
        return None

    # Sort opposing pools by distance from entry (nearest first)
    opposing_pools.sort(key=lambda p: abs(p.price - entry))
    tp1_pool = opposing_pools[0]
    tp1 = tp1_pool.price
    tp2_pool = opposing_pools[1] if len(opposing_pools) > 1 else None
    tp2 = tp2_pool.price if tp2_pool else None

    reward_tp1 = (entry - tp1) if direction == "SHORT" else (tp1 - entry)
    rr_tp1 = reward_tp1 / risk

    # Hard gate: Require RR(TP1) >= 1.5
    if rr_tp1 < config.min_rr_tp1:
        return None

    reward_tp2 = None
    rr_tp2 = None
    if tp2 is not None:
        reward_tp2 = (entry - tp2) if direction == "SHORT" else (tp2 - entry)
        rr_tp2 = reward_tp2 / risk

    return SetupPlan(
        direction=direction,
        entry_price=round(entry, 2),
        stop_loss=round(stop_loss, 2),
        take_profit_1=round(tp1, 2),
        take_profit_2=round(tp2, 2) if tp2 else None,
        risk_usd=round(risk, 2),
        reward_usd_tp1=round(reward_tp1, 2),
        reward_usd_tp2=round(reward_tp2, 2) if reward_tp2 else None,
        risk_reward_tp1=round(rr_tp1, 2),
        risk_reward_tp2=round(rr_tp2, 2) if rr_tp2 else None,
        sweep_extreme=round(sweep.sweep_extreme, 2),
        displacement_extreme=round(disp_extreme, 2),
        in_premium_discount=True,
        tp1_pool_id=tp1_pool.id,
        tp2_pool_id=tp2_pool.id if tp2_pool else None,
    )
