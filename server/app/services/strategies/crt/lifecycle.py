"""Lifecycle State Machine and Management Alert Tracker for CRT Setups.

States:
- POTENTIAL: Preliminary breach detected, not yet confirmed.
- WAITING_FOR_CONFIRMATION: Awaiting close back inside, displacement, or MSS.
- CONFIRMED: Fully qualified institutional setup; initial entry signal.
- ENTRY_FILLED: Limit retracement zone touched / trade active.
- TP1_HIT: Primary target reached.
- TP2_HIT: Runner / secondary target reached.
- STOPPED: Stop loss hit.
- INVALIDATED: Manipulation extreme broken or structure invalidated before entry.
- EXPIRED: Entry limit zone expired unfilled after N bars.
- MISSED: Price ran >0.5R toward TP1 without filling limit entry.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from app.core.logging import logger
from app.models.crt_sweep_event import CRTSweepEvent
from app.schemas.signal import SignalDirection

UTC_TZ = timezone.utc


class CRTState:
    POTENTIAL = "POTENTIAL"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    ENTRY_FILLED = "ENTRY_FILLED"
    TP1_HIT = "TP1_HIT"
    TP2_HIT = "TP2_HIT"
    STOPPED = "STOPPED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    MISSED = "MISSED"
    NO_SETUP = "NO_SETUP"


@dataclass
class StateTransitionResult:
    """Result of state evaluation and alert decision."""
    current_state: str
    previous_state: Optional[str]
    transition_occurred: bool
    should_send_management_alert: bool
    alert_title: str
    alert_message: str


def evaluate_lifecycle_state(
    sweep_key: str,
    direction: SignalDirection,
    current_price: float,
    current_time: datetime,
    entry_price: float,
    stop_loss: float,
    tp1: float,
    tp2: float,
    zone_high: float,
    zone_low: float,
    expires_at: Optional[datetime],
    db_conn: Any = None,
    is_missed: bool = False,
    is_sweep_broken: bool = False,
    initial_state: str = CRTState.CONFIRMED,
) -> StateTransitionResult:
    """Evaluate lifecycle progression and determine if an alert should be emitted."""
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC_TZ)

    record: Optional[CRTSweepEvent] = None
    if db_conn is not None:
        try:
            record = db_conn.query(CRTSweepEvent).filter(CRTSweepEvent.sweep_key == sweep_key).first()
        except Exception as e:
            logger.debug(f"CRT Lifecycle DB query note: {e}")

    prev_state = record.current_state if (record and record.current_state) else initial_state
    last_alerted = record.last_alerted_state if record else None

    new_state = prev_state

    # 1. Invalidation checks
    if is_sweep_broken:
        new_state = CRTState.INVALIDATED
    elif is_missed and prev_state in (CRTState.POTENTIAL, CRTState.WAITING_FOR_CONFIRMATION, CRTState.CONFIRMED):
        new_state = CRTState.MISSED
    elif expires_at is not None and current_time >= expires_at and prev_state == CRTState.CONFIRMED:
        new_state = CRTState.EXPIRED

    # 2. Progression after CONFIRMED
    elif prev_state == CRTState.CONFIRMED:
        # Check if limit zone was filled
        if zone_low <= current_price <= zone_high:
            new_state = CRTState.ENTRY_FILLED
        elif direction == SignalDirection.BUY and current_price < zone_low and current_price > stop_loss:
            new_state = CRTState.ENTRY_FILLED
        elif direction == SignalDirection.SELL and current_price > zone_high and current_price < stop_loss:
            new_state = CRTState.ENTRY_FILLED

    # 3. Progression after ENTRY_FILLED
    elif prev_state == CRTState.ENTRY_FILLED:
        if direction == SignalDirection.BUY:
            if current_price <= stop_loss:
                new_state = CRTState.STOPPED
            elif current_price >= tp2 and tp2 > 0:
                new_state = CRTState.TP2_HIT
            elif current_price >= tp1 and tp1 > 0:
                new_state = CRTState.TP1_HIT
        else:
            if current_price >= stop_loss:
                new_state = CRTState.STOPPED
            elif current_price <= tp2 and tp2 > 0:
                new_state = CRTState.TP2_HIT
            elif current_price <= tp1 and tp1 > 0:
                new_state = CRTState.TP1_HIT

    # 4. Progression after TP1_HIT
    elif prev_state == CRTState.TP1_HIT:
        if direction == SignalDirection.BUY:
            if current_price <= stop_loss:
                new_state = CRTState.STOPPED
            elif current_price >= tp2 and tp2 > 0:
                new_state = CRTState.TP2_HIT
        else:
            if current_price >= stop_loss:
                new_state = CRTState.STOPPED
            elif current_price <= tp2 and tp2 > 0:
                new_state = CRTState.TP2_HIT

    # Check transition and management alert eligibility
    transition_occurred = new_state != prev_state
    alertable_states = {
        CRTState.ENTRY_FILLED,
        CRTState.TP1_HIT,
        CRTState.TP2_HIT,
        CRTState.STOPPED,
        CRTState.INVALIDATED,
        CRTState.EXPIRED,
        CRTState.MISSED,
    }

    should_alert = transition_occurred and (new_state in alertable_states) and (new_state != last_alerted)

    alert_title = f"CRT UPDATE: {new_state}"
    alert_message = f"State transition for {sweep_key}: {prev_state} -> {new_state} @ {current_price:.2f}"

    # Update or insert database record if present
    if db_conn is not None:
        try:
            cd_until = expires_at if expires_at is not None else (current_time + timedelta(hours=4))
            if record is not None:
                record.current_state = new_state
                if should_alert:
                    record.last_alerted_state = new_state
            else:
                record = CRTSweepEvent(
                    sweep_key=sweep_key,
                    symbol="XAU/USD",
                    timeframe="1h",
                    direction=direction.value,
                    emitted_at=current_time,
                    cooldown_until=cd_until,
                    current_state=new_state,
                    last_alerted_state=new_state if should_alert else None,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit_1=tp1,
                    take_profit_2=tp2,
                    zone_high=zone_high,
                    zone_low=zone_low,
                    expires_at=expires_at,
                )
                db_conn.add(record)
            db_conn.commit()
        except Exception as e:
            db_conn.rollback()
            logger.debug(f"CRT Lifecycle update error: {e}")

    return StateTransitionResult(
        current_state=new_state,
        previous_state=prev_state,
        transition_occurred=transition_occurred,
        should_send_management_alert=should_alert,
        alert_title=alert_title,
        alert_message=alert_message,
    )
