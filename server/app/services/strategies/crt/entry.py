"""Retracement Entry Zone Calculation, Expiry Tracking, and Missed Setup Detection.

Entry zone from the first valid LTF FVG/OB made by the displacement leg,
falling back to 50% equilibrium of the [sweep_extreme -> displacement_extreme] leg.
All geometry is anchored to the manipulation candle so re-analysis of the same
sweep produces the same zone and expiry.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Sequence

from app.schemas.signal import SignalDirection

UTC_TZ = timezone.utc


@dataclass(frozen=True)
class RetracementEntry:
    """Calculated retracement entry zone."""
    zone_high: float
    zone_low: float
    ideal_entry: float
    stop_loss: float
    entry_mode: str  # "limit_zone" or "market"
    zone_type: str   # "FVG", "ORDER_BLOCK", "EQUILIBRIUM_50"
    expiry_bars: int
    created_time: datetime
    expires_at: datetime
    is_missed: bool = False
    missed_reason: Optional[str] = None
    zone_invalid: bool = False


def _get_val(c: Any, field: str) -> float:
    if isinstance(c, dict):
        return float(c[field])
    return float(getattr(c, field))


def _get_ts(c: Any) -> datetime:
    if isinstance(c, dict):
        raw = c.get("timestamp")
    else:
        raw = getattr(c, "timestamp", None)
    if raw is None:
        return datetime.now(UTC_TZ)
    if raw.tzinfo is None:
        return raw.replace(tzinfo=UTC_TZ)
    return raw.astimezone(UTC_TZ)


def calculate_retracement_entry(
    direction: SignalDirection,
    sweep_extreme: float,
    displacement_extreme: float,
    candles_15m: Sequence[Any],
    current_price: float,
    target_tp1: float,
    atr: float = 10.0,
    spread: float = 0.0,
    expiry_bars: int = 8,
    sl_buffer_mult: float = 0.10,
    liquidity_pools: Optional[Sequence[Any]] = None,
    manip_candle_index: int = 0,
    tick_size: float = 0.01,
) -> RetracementEntry:
    """Calculate the entry zone, ideal entry, stop loss, and check missed status.

    ``manip_candle_index`` is the index of the sweep/manipulation bar inside
    ``candles_15m``. Every zone / expiry / missed decision uses only the bars
    at or after that index, so a re-analysis of the same sweep is stable.
    """
    sl_buffer = max(spread, sl_buffer_mult * atr) if (spread > 0 or atr > 0) else 0.0

    n = len(candles_15m)
    manip_idx = max(0, min(int(manip_candle_index or 0), n - 1)) if n else 0

    # Expiry anchored to the manipulation bar, not the last bar of a sliding
    # window; this keeps ``expires_at`` stable across re-analysis.
    created_time = _get_ts(candles_15m[manip_idx]) if n else datetime.now(UTC_TZ)
    expires_at = created_time + timedelta(minutes=15 * expiry_bars)

    # 1. Stop Loss calculation beyond sweep extreme
    if direction == SignalDirection.BUY:
        raw_sl = sweep_extreme - sl_buffer
        if liquidity_pools:
            for p in liquidity_pools:
                p_level = getattr(p, "price_level", getattr(p, "price", 0.0))
                p_type = str(getattr(p, "pool_type", ""))
                if "LOW" in p_type and p_level < current_price:
                    if abs(p_level - sweep_extreme) <= 1.0 * atr:
                        raw_sl = min(raw_sl, p_level - sl_buffer)
        stop_loss = round(raw_sl, 5)
    else:
        raw_sl = sweep_extreme + sl_buffer
        if liquidity_pools:
            for p in liquidity_pools:
                p_level = getattr(p, "price_level", getattr(p, "price", 0.0))
                p_type = str(getattr(p, "pool_type", ""))
                if "HIGH" in p_type and p_level > current_price:
                    if abs(p_level - sweep_extreme) <= 1.0 * atr:
                        raw_sl = max(raw_sl, p_level + sl_buffer)
        stop_loss = round(raw_sl, 5)

    # 2. Entry zone: FIRST valid FVG of the displacement leg (forward scan)
    zone_type = "EQUILIBRIUM_50"
    zone_high = 0.0
    zone_low = 0.0
    ideal_entry = 0.0

    leg_span = abs(displacement_extreme - sweep_extreme)
    eq_midpoint = (displacement_extreme + sweep_extreme) / 2.0 if leg_span > 0 else current_price

    found_zone = False

    if n >= 3:
        for k in range(manip_idx + 2, n):
            c_curr = candles_15m[k]
            c_prev2 = candles_15m[k - 2]
            h_curr = _get_val(c_curr, "high")
            l_curr = _get_val(c_curr, "low")
            h_prev2 = _get_val(c_prev2, "high")
            l_prev2 = _get_val(c_prev2, "low")

            if direction == SignalDirection.BUY:
                # Bullish FVG: low[k] > high[k-2]
                if l_curr > h_prev2:
                    zone_low = h_prev2
                    zone_high = l_curr
                    ideal_entry = (zone_low + zone_high) / 2.0
                    zone_type = "FVG"
                    found_zone = True
                    break
            else:
                # Bearish FVG: high[k] < low[k-2]
                if h_curr < l_prev2:
                    zone_high = l_prev2
                    zone_low = h_curr
                    ideal_entry = (zone_low + zone_high) / 2.0
                    zone_type = "FVG"
                    found_zone = True
                    break

    # 3. Fallback: Order Block in the post-sweep leg, before the first
    #    displacement bar. Body direction must be strictly opposing (no doji).
    if not found_zone and n:
        first_disp = n
        for k in range(manip_idx + 1, n):
            c = candles_15m[k]
            if direction == SignalDirection.BUY and _get_val(c, "high") >= displacement_extreme:
                first_disp = k
                break
            if direction == SignalDirection.SELL and _get_val(c, "low") <= displacement_extreme:
                first_disp = k
                break

        for k in range(first_disp - 1, manip_idx - 1, -1):
            c = candles_15m[k]
            c_o = _get_val(c, "open")
            c_c = _get_val(c, "close")
            c_h = _get_val(c, "high")
            c_l = _get_val(c, "low")
            if direction == SignalDirection.BUY and c_c < c_o:
                zone_low = c_l
                zone_high = c_h
                ideal_entry = c_o
                zone_type = "ORDER_BLOCK"
                found_zone = True
                break
            elif direction == SignalDirection.SELL and c_c > c_o:
                zone_high = c_h
                zone_low = c_l
                ideal_entry = c_o
                zone_type = "ORDER_BLOCK"
                found_zone = True
                break

    if not found_zone:
        zone_type = "EQUILIBRIUM_50"
        ideal_entry = eq_midpoint
        half_width = max(2.0 * tick_size, 0.05 * atr)
        zone_high = ideal_entry + half_width
        zone_low = ideal_entry - half_width

    # 4. Entry mode: "market" if current price is inside the entry zone, else "limit_zone"
    if zone_low <= current_price <= zone_high:
        entry_mode = "market"
    else:
        entry_mode = "limit_zone"

    # A zone that is not clear of the stop cannot be executed safely.
    zone_invalid = (
        (direction == SignalDirection.BUY and stop_loss > zone_low)
        or (direction == SignalDirection.SELL and stop_loss < zone_high)
    )

    # 5. Missed setup detection — post-sweep bars only. The sweep and
    #    displacement bars themselves can neither fill nor invalidate the zone.
    post_sweep_candles = list(candles_15m[manip_idx + 1:])
    risk = abs(ideal_entry - stop_loss)
    is_missed = False
    missed_reason = None

    if risk > 0 and entry_mode == "limit_zone" and post_sweep_candles:
        for c in post_sweep_candles:
            c_c = _get_val(c, "close")
            c_h = _get_val(c, "high")
            c_l = _get_val(c, "low")
            if direction == SignalDirection.BUY:
                if c_l <= ideal_entry:
                    break
                if c_c > zone_high + (0.50 * risk) or c_h > zone_high + (0.75 * risk):
                    is_missed = True
                    missed_reason = f"MISSED: Price ran +{(c_c - zone_high) / risk:.2f}R toward TP1 without filling limit zone."
                    break
            else:
                if c_h >= ideal_entry:
                    break
                if c_c < zone_low - (0.50 * risk) or c_l < zone_low - (0.75 * risk):
                    is_missed = True
                    missed_reason = f"MISSED: Price ran +{(zone_low - c_c) / risk:.2f}R toward TP1 without filling limit zone."
                    break

    return RetracementEntry(
        zone_high=round(zone_high, 5),
        zone_low=round(zone_low, 5),
        ideal_entry=round(ideal_entry, 5),
        stop_loss=round(stop_loss, 5),
        entry_mode=entry_mode,
        zone_type=zone_type,
        expiry_bars=expiry_bars,
        created_time=created_time,
        expires_at=expires_at,
        is_missed=is_missed,
        missed_reason=missed_reason,
        zone_invalid=zone_invalid,
    )
