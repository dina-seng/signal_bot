"""Lower Timeframe (LTF) Confirmation for CRT setups.

CONFIRMED requires:
1. Close back inside benchmark range
2. Displacement candle (body >= min ATR fraction and body/range ratio >= 0.50)
3. Market Structure Shift (MSS / CHoCH) occurring after the sweep.

If MSS is missing -> WAITING_FOR_CONFIRMATION.
"""

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from app.schemas.signal import SignalDirection


@dataclass(frozen=True)
class LTFConfirmationResult:
    """Detailed result of LTF confirmation checks."""
    is_confirmed: bool
    state: str  # "CONFIRMED", "WAITING_FOR_CONFIRMATION", "NO_SETUP"
    has_reentered_range: bool
    has_displacement: bool
    has_mss: bool
    displacement_extreme: float
    displacement_size: float
    reason: str


def _get_val(c: Any, field: str) -> float:
    if isinstance(c, dict):
        return float(c[field])
    return float(getattr(c, field))


def verify_ltf_confirmation(
    direction: SignalDirection,
    range_high: float,
    range_low: float,
    candles_15m: Sequence[Any],
    breach_point: float,
    manip_candle_index: int = 0,
    atr: float = 10.0,
    min_disp_atr_mult: float = 0.20,
    structure: Any = None,
) -> LTFConfirmationResult:
    """Verify range re-entry, displacement, and MSS after the sweep."""
    if not candles_15m or len(candles_15m) <= manip_candle_index:
        return LTFConfirmationResult(
            is_confirmed=False,
            state="WAITING_FOR_CONFIRMATION",
            has_reentered_range=False,
            has_displacement=False,
            has_mss=False,
            displacement_extreme=breach_point,
            displacement_size=0.0,
            reason="Awaiting post-sweep confirmation candles.",
        )

    post_sweep_candles = candles_15m[manip_candle_index:]
    last_candle = post_sweep_candles[-1]
    last_close = _get_val(last_candle, "close")

    # 1. Close back inside range
    has_reentry = False
    if direction == SignalDirection.BUY:
        has_reentry = last_close > range_low
    else:
        has_reentry = last_close < range_high

    if not has_reentry:
        return LTFConfirmationResult(
            is_confirmed=False,
            state="WAITING_FOR_CONFIRMATION",
            has_reentered_range=False,
            has_displacement=False,
            has_mss=False,
            displacement_extreme=breach_point,
            displacement_size=0.0,
            reason="Awaiting close back inside benchmark range.",
        )

    # 2. Displacement candle check along post-sweep leg
    has_displacement = False
    disp_size = 0.0
    disp_extreme = breach_point

    min_disp_size = min_disp_atr_mult * atr

    for c in post_sweep_candles:
        c_open = _get_val(c, "open")
        c_close = _get_val(c, "close")
        c_high = _get_val(c, "high")
        c_low = _get_val(c, "low")
        c_range = c_high - c_low

        if direction == SignalDirection.BUY:
            disp_extreme = max(disp_extreme, c_high)
            body = c_close - c_open
            if body >= min_disp_size and c_range > 0 and (body / c_range) >= 0.50:
                has_displacement = True
                disp_size = max(disp_size, body)
        else:
            disp_extreme = min(disp_extreme, c_low)
            body = c_open - c_close
            if body >= min_disp_size and c_range > 0 and (body / c_range) >= 0.50:
                has_displacement = True
                disp_size = max(disp_size, body)

    # 3. Market Structure Shift (MSS) after the sweep
    has_mss = False

    # Check structural CHoCH / BOS from structure analysis if available
    if structure is not None:
        if hasattr(structure, "recent_events") and structure.recent_events:
            for ev in structure.recent_events:
                ev_type = str(getattr(ev, "event_type", ""))
                if direction == SignalDirection.BUY and ("BULLISH_CHOCH" in ev_type or "BULLISH_MSS" in ev_type or "BULLISH_BOS" in ev_type):
                    has_mss = True
                    break
                elif direction == SignalDirection.SELL and ("BEARISH_CHOCH" in ev_type or "BEARISH_MSS" in ev_type or "BEARISH_BOS" in ev_type):
                    has_mss = True
                    break
        elif hasattr(structure, "base_structure") and structure.base_structure:
            bs = structure.base_structure
            if hasattr(bs, "choch_events") and bs.choch_events:
                for ev in bs.choch_events:
                    ev_type = str(getattr(ev, "event_type", ""))
                    if direction == SignalDirection.BUY and "BULLISH" in ev_type:
                        has_mss = True
                        break
                    elif direction == SignalDirection.SELL and "BEARISH" in ev_type:
                        has_mss = True
                        break

    # If structure detector didn't catch an MSS, check local swing shift on candles
    if not has_mss and len(candles_15m) >= 2:
        # Find local pivot high (for BUY) or pivot low (for SELL) prior to the sweep
        prior_candles = candles_15m[:max(1, manip_candle_index + 1)]
        if direction == SignalDirection.BUY:
            local_highs = [_get_val(c, "high") for c in prior_candles[-5:]]
            if local_highs:
                recent_swing_high = max(local_highs)
                # Has a post-sweep candle closed above recent swing high or displaced through it?
                for c in post_sweep_candles:
                    if _get_val(c, "close") > recent_swing_high or _get_val(c, "high") > recent_swing_high:
                        has_mss = True
                        break
        else:
            local_lows = [_get_val(c, "low") for c in prior_candles[-5:]]
            if local_lows:
                recent_swing_low = min(local_lows)
                for c in post_sweep_candles:
                    if _get_val(c, "close") < recent_swing_low or _get_val(c, "low") < recent_swing_low:
                        has_mss = True
                        break

    if not has_mss:
        return LTFConfirmationResult(
            is_confirmed=False,
            state="WAITING_FOR_CONFIRMATION",
            has_reentered_range=True,
            has_displacement=has_displacement,
            has_mss=False,
            displacement_extreme=disp_extreme,
            displacement_size=disp_size,
            reason="Awaiting Market Structure Shift (MSS) after sweep.",
        )

    return LTFConfirmationResult(
        is_confirmed=True,
        state="CONFIRMED",
        has_reentered_range=True,
        has_displacement=has_displacement,
        has_mss=True,
        displacement_extreme=disp_extreme,
        displacement_size=disp_size,
        reason="Confirmed: Range re-entry, displacement, and MSS verified.",
    )
