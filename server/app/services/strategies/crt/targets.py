"""CRT-Native Target Calculation and Path Validation.

BUY after low sweep:
  TP1 = Range Midpoint: (range_high + range_low) / 2.0
  TP2 = Range High: range_high
SELL after high sweep:
  TP1 = Range Midpoint: (range_high + range_low) / 2.0
  TP2 = Range Low: range_low

Obstacle capping via PathValidator and real R:R enforcement.
"""

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, TYPE_CHECKING

from app.schemas.signal import SignalDirection

if TYPE_CHECKING:
    from app.services.signals.path_validator import PathValidator, PathValidationResult


@dataclass
class CRTTargetPlan:
    """Result of CRT target determination, obstacle checks, and R:R evaluation."""
    take_profit_1: float
    take_profit_2: float
    risk_usd: float
    reward_usd_tp1: float
    reward_usd_tp2: float
    risk_reward_tp1: float
    risk_reward_tp2: float
    target_type: str  # "CRT_RANGE" or "FALLBACK_RR"
    is_valid: bool
    rejection_gate: Optional[str] = None
    rejection_reason: Optional[str] = None
    capped_by_obstacle: bool = False
    obstacle_type: Optional[str] = None
    obstacle_price: Optional[float] = None
    notes: List[str] = None


def calculate_crt_targets(
    direction: SignalDirection,
    entry_price: float,
    stop_loss: float,
    range_high: float,
    range_low: float,
    atr: float = 10.0,
    min_rr: float = 1.0,
    structure: Any = None,
    indicators: Any = None,
    path_validator: Optional[PathValidator] = None,
) -> CRTTargetPlan:
    """Calculate CRT-native targets, check obstacles, and enforce minimum R:R."""
    notes: List[str] = []
    if path_validator is None:
        from app.services.signals.path_validator import PathValidator
        validator = PathValidator()
    else:
        validator = path_validator

    risk_usd = abs(entry_price - stop_loss)
    if risk_usd <= 0.0:
        return CRTTargetPlan(
            take_profit_1=0.0,
            take_profit_2=0.0,
            risk_usd=0.0,
            reward_usd_tp1=0.0,
            reward_usd_tp2=0.0,
            risk_reward_tp1=0.0,
            risk_reward_tp2=0.0,
            target_type="INVALID",
            is_valid=False,
            rejection_gate="INVALID_RISK_GEOMETRY",
            rejection_reason="Stop loss equals or opposes entry price (zero risk distance).",
            notes=notes,
        )

    midpoint = (range_high + range_low) / 2.0

    # 1. Determine whether CRT Range Targets are valid
    use_range_targets = False
    if direction == SignalDirection.BUY:
        if entry_price < midpoint and range_high > entry_price:
            mid_dist = midpoint - entry_price
            if (mid_dist / risk_usd) >= min_rr:
                use_range_targets = True
    elif direction == SignalDirection.SELL:
        if entry_price > midpoint and range_low < entry_price:
            mid_dist = entry_price - midpoint
            if (mid_dist / risk_usd) >= min_rr:
                use_range_targets = True

    if use_range_targets:
        target_type = "CRT_RANGE"
        if direction == SignalDirection.BUY:
            raw_tp1 = midpoint
            raw_tp2 = range_high
        else:
            raw_tp1 = midpoint
            raw_tp2 = range_low
    else:
        target_type = "FALLBACK_RR"
        notes.append("Range targets invalid (midpoint R:R < min_rr or behind entry); using Fallback 1.5R/2.5R targets.")
        if direction == SignalDirection.BUY:
            raw_tp1 = entry_price + (risk_usd * 1.5)
            raw_tp2 = entry_price + (risk_usd * 2.5)
        else:
            raw_tp1 = entry_price - (risk_usd * 1.5)
            raw_tp2 = entry_price - (risk_usd * 2.5)

    # 2. Extract structural obstacles for PathValidator
    sr_zones = []
    if structure is not None and hasattr(structure, "sr_zones") and structure.sr_zones:
        sr_zones = list(structure.sr_zones)

    active_fvgs = []
    if indicators is not None and hasattr(indicators, "active_fvgs") and indicators.active_fvgs:
        active_fvgs = list(indicators.active_fvgs)

    liquidity_pools = []
    if structure is not None and hasattr(structure, "liquidity_pools") and structure.liquidity_pools:
        liquidity_pools = list(structure.liquidity_pools)

    # 3. Validate path to TP1 and cap before obstacle if necessary
    capped_by_obstacle = False
    obstacle_type = None
    obstacle_price = None

    pv_tp1: PathValidationResult = validator.validate_trade_path(
        direction=direction,
        entry_price=entry_price,
        target_price=raw_tp1,
        sr_zones=sr_zones,
        active_fvgs=active_fvgs,
        liquidity_pools=liquidity_pools,
    )

    cap_buffer = max(0.20, 0.05 * atr)
    final_tp1 = raw_tp1

    if not pv_tp1.is_clear and pv_tp1.nearest_obstacle_price is not None:
        capped_by_obstacle = True
        obstacle_type = pv_tp1.obstacle_type
        obstacle_price = pv_tp1.nearest_obstacle_price

        if direction == SignalDirection.BUY:
            capped_tp1 = obstacle_price - cap_buffer
            if capped_tp1 > entry_price:
                final_tp1 = min(raw_tp1, capped_tp1)
                notes.append(f"TP1 capped before opposing {obstacle_type} at {obstacle_price:.2f}.")
        else:
            capped_tp1 = obstacle_price + cap_buffer
            if capped_tp1 < entry_price:
                final_tp1 = max(raw_tp1, capped_tp1)
                notes.append(f"TP1 capped before opposing {obstacle_type} at {obstacle_price:.2f}.")

    # Validate path to TP2
    pv_tp2: PathValidationResult = validator.validate_trade_path(
        direction=direction,
        entry_price=entry_price,
        target_price=raw_tp2,
        sr_zones=sr_zones,
        active_fvgs=active_fvgs,
        liquidity_pools=liquidity_pools,
    )
    final_tp2 = raw_tp2
    if not pv_tp2.is_clear and pv_tp2.nearest_obstacle_price is not None:
        if direction == SignalDirection.BUY:
            capped_tp2 = pv_tp2.nearest_obstacle_price - cap_buffer
            if capped_tp2 > final_tp1:
                final_tp2 = min(raw_tp2, capped_tp2)
        else:
            capped_tp2 = pv_tp2.nearest_obstacle_price + cap_buffer
            if capped_tp2 < final_tp1:
                final_tp2 = max(raw_tp2, capped_tp2)

    # 4. Compute real R:R per target
    reward_usd_tp1 = abs(final_tp1 - entry_price)
    reward_usd_tp2 = abs(final_tp2 - entry_price)

    rr_tp1 = round(reward_usd_tp1 / risk_usd, 2)
    rr_tp2 = round(reward_usd_tp2 / risk_usd, 2)

    # 5. Enforce minimum acceptable R:R on TP1
    if rr_tp1 < min_rr:
        gate = "PATH_BLOCKED" if capped_by_obstacle else "INSUFFICIENT_RR"
        reason = (
            f"WAIT (Clear Path Blocked): Opposing {obstacle_type} is only {rr_tp1:.2f}R from entry (< {min_rr:.1f}R minimum clear path required)."
            if capped_by_obstacle
            else f"TP1 Risk:Reward ({rr_tp1:.2f}R) is below minimum required ({min_rr:.1f}R)."
        )
        return CRTTargetPlan(
            take_profit_1=round(final_tp1, 5),
            take_profit_2=round(final_tp2, 5),
            risk_usd=round(risk_usd, 5),
            reward_usd_tp1=round(reward_usd_tp1, 5),
            reward_usd_tp2=round(reward_usd_tp2, 5),
            risk_reward_tp1=rr_tp1,
            risk_reward_tp2=rr_tp2,
            target_type=target_type,
            is_valid=False,
            rejection_gate=gate,
            rejection_reason=reason,
            capped_by_obstacle=capped_by_obstacle,
            obstacle_type=obstacle_type,
            obstacle_price=obstacle_price,
            notes=notes,
        )

    return CRTTargetPlan(
        take_profit_1=round(final_tp1, 5),
        take_profit_2=round(final_tp2, 5),
        risk_usd=round(risk_usd, 5),
        reward_usd_tp1=round(reward_usd_tp1, 5),
        reward_usd_tp2=round(reward_usd_tp2, 5),
        risk_reward_tp1=rr_tp1,
        risk_reward_tp2=rr_tp2,
        target_type=target_type,
        is_valid=True,
        capped_by_obstacle=capped_by_obstacle,
        obstacle_type=obstacle_type,
        obstacle_price=obstacle_price,
        notes=notes,
    )
