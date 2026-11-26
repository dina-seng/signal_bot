"""Lifecycle locks and output guards for consumed candle setups.

A setup is consumed when its paper trade opens: the signal becomes EXECUTED and
its identity is written to ``executed_signal_setups``. When the trade closes the
signal becomes CLOSED. This module only manages that lifecycle and filters what
the output layer may show; it never generates signals or touches scoring, veto
or risk logic.
"""

from datetime import datetime, timezone
from typing import Optional, Sequence, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.models.executed_setup import ExecutedSetup
from app.models.paper import PaperTrade
from app.models.signal import Signal
from app.schemas.signal import MarketScanResponse, SignalStatus
from app.services.market_data.freshness import ensure_utc_datetime

# (symbol, timeframe, candle timestamp in whole UTC seconds, direction)
SetupKey = Tuple[str, str, int, str]

# Statuses that must never be emitted as a fresh active signal.
CONSUMED_STATUSES = {
    "EXECUTED",
    "CLOSED",
    "EXPIRED",
    "INVALIDATED",
    "SUPERSEDED",
    "TP1_HIT",
    "TP2_HIT",
    "SL_HIT",
}


def setup_key(
    symbol: object,
    timeframe: object,
    timestamp: object,
    direction: object,
) -> Optional[SetupKey]:
    candle_time = ensure_utc_datetime(timestamp)
    if candle_time is None:
        return None
    raw_direction = getattr(direction, "value", direction)
    return (
        str(symbol or "").strip().upper(),
        str(timeframe or "").strip().lower(),
        int(candle_time.timestamp()),
        str(raw_direction or "").strip().upper(),
    )


def setup_key_of(obj: object) -> Optional[SetupKey]:
    return setup_key(
        getattr(obj, "symbol", None),
        getattr(obj, "timeframe", None),
        getattr(obj, "timestamp", None),
        getattr(obj, "direction", None),
    )


def registry_key_of(row: ExecutedSetup) -> Optional[SetupKey]:
    return setup_key(row.symbol, row.timeframe, row.candle_timestamp, row.direction)


def find_executed_setup(db: Session, key: Optional[SetupKey]) -> Optional[ExecutedSetup]:
    if key is None:
        return None
    rows = db.scalars(
        select(ExecutedSetup).where(
            ExecutedSetup.symbol == key[0],
            ExecutedSetup.timeframe == key[1],
            ExecutedSetup.direction == key[3],
        )
    ).all()
    for row in rows:
        if registry_key_of(row) == key:
            return row
    return None


def is_setup_executed(db: Session, obj: object) -> bool:
    """True when this exact candle setup already opened a paper trade."""
    return find_executed_setup(db, setup_key_of(obj)) is not None


def register_executed_setup(
    db: Session,
    signal: object,
    trade_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> Optional[ExecutedSetup]:
    """Persist a consumed setup. Flushes only; caller owns the commit."""
    key = setup_key_of(signal)
    if key is None:
        return None
    existing = find_executed_setup(db, key)
    if existing is not None:
        if trade_id is not None and existing.trade_id is None:
            existing.trade_id = trade_id
        return existing

    row = ExecutedSetup(
        symbol=key[0],
        timeframe=key[1],
        candle_timestamp=ensure_utc_datetime(getattr(signal, "timestamp", None)),
        direction=key[3],
        signal_id=getattr(signal, "id", None),
        trade_id=trade_id,
        status=SignalStatus.EXECUTED.value,
        executed_at=now or datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


def mark_signal_executed(
    db: Session,
    signal: Signal,
    trade_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> Optional[ExecutedSetup]:
    """Lock the signal as EXECUTED and register its setup at fill time."""
    if signal is None:
        return None
    signal.status = SignalStatus.EXECUTED.value
    entry = register_executed_setup(db, signal, trade_id, now)
    logger.info(
        "SIGNAL_LIFECYCLE_EXECUTED signal=%s trade=%s setup=%s",
        signal.id,
        trade_id,
        setup_key_of(signal),
    )
    return entry


def mark_signal_closed(
    db: Session,
    signal: Signal,
    exit_reason: str,
    now: Optional[datetime] = None,
) -> None:
    """Move an executed signal to CLOSED and close its registry entry."""
    if signal is None:
        return
    stamp = now or datetime.now(timezone.utc)
    signal.status = SignalStatus.CLOSED.value
    row = find_executed_setup(db, setup_key_of(signal))
    if row is None and signal.id is not None:
        row = db.scalars(
            select(ExecutedSetup).where(ExecutedSetup.signal_id == signal.id)
        ).first()
    if row is not None and row.status != SignalStatus.CLOSED.value:
        row.status = SignalStatus.CLOSED.value
        row.closed_at = stamp
    logger.info("SIGNAL_LIFECYCLE_CLOSED signal=%s reason=%s", signal.id, exit_reason)


def executed_setup_keys(db: Session) -> Set[SetupKey]:
    keys: Set[SetupKey] = set()
    for row in db.scalars(select(ExecutedSetup)).all():
        key = registry_key_of(row)
        if key is not None:
            keys.add(key)
    return keys


def consumed_signal_ids(db: Session) -> Set[int]:
    ids: Set[int] = set()
    for value in db.scalars(select(ExecutedSetup.signal_id)).all():
        if value is not None:
            ids.add(int(value))
    stmt = select(PaperTrade.signal_id).where(
        PaperTrade.status == "CLOSED",
        PaperTrade.signal_id.is_not(None),
    )
    for value in db.scalars(stmt).all():
        if value is not None:
            ids.add(int(value))
    return ids


def consumed_setup_keys(
    db: Session,
    signal_ids: Optional[Set[int]] = None,
) -> Set[SetupKey]:
    """All consumed setup keys, including legacy closed-trade links."""
    keys = executed_setup_keys(db)
    if signal_ids is None:
        signal_ids = consumed_signal_ids(db)
    if signal_ids:
        for row in db.scalars(select(Signal).where(Signal.id.in_(signal_ids))).all():
            key = setup_key_of(row)
            if key is not None:
                keys.add(key)
    return keys


def is_consumed_signal(
    obj: object,
    keys: Set[SetupKey],
    signal_ids: Optional[Set[int]] = None,
) -> bool:
    status = getattr(obj, "status", None)
    status_value = getattr(status, "value", status)
    if status_value in CONSUMED_STATUSES:
        return True
    obj_id = getattr(obj, "id", None)
    if signal_ids and obj_id is not None:
        try:
            if int(obj_id) in signal_ids:
                return True
        except (TypeError, ValueError):
            pass
    key = setup_key_of(obj)
    return key is not None and key in keys


def filter_consumed_signals(db: Session, signals: Sequence[object]) -> list:
    keys = consumed_setup_keys(db)
    ids = consumed_signal_ids(db)
    return [sig for sig in signals if not is_consumed_signal(sig, keys, ids)]


def is_consumed_scan_result(db: Session, result: object) -> bool:
    """True when a single scan result points at an already traded candle."""
    sig = getattr(result, "signal", None)
    if sig is None:
        return False
    keys = consumed_setup_keys(db)
    ids = consumed_signal_ids(db)
    return is_consumed_signal(sig, keys, ids)


def filter_consumed_scan_results(
    db: Session, response: MarketScanResponse
) -> MarketScanResponse:
    """Strip consumed setups from scanner output before it reaches a client."""
    if response is None:
        return response
    keys = consumed_setup_keys(db)
    ids = consumed_signal_ids(db)
    results = [
        result
        for result in response.results
        if result.signal is None
        or not is_consumed_signal(result.signal, keys, ids)
    ]
    return MarketScanResponse(
        timestamp=response.timestamp,
        scanned_count=response.scanned_count,
        actionable_count=sum(1 for result in results if result.is_actionable),
        results=results,
    )
