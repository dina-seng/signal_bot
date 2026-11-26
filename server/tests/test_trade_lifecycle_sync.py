"""Targeted lifecycle test: single slot, consumed candle, clean close, clean output."""

from datetime import datetime, timezone

import pytest

from app.models.executed_setup import ExecutedSetup
from app.models.paper import PaperTrade
from app.models.signal import Signal
from app.schemas.paper_trading import PaperOrderCreate
from app.schemas.signal import SignalDirection
from app.services.market_data.cache import derived_cache
from app.services.paper_trading.order_executor import PaperOrderExecutor
from app.services.paper_trading.position_manager import PaperPositionManager

CANDLE_TS = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _signal(db, fingerprint, status="ACTIVE", score=88.0):
    row = Signal(
        symbol="XAU/USD",
        timeframe="15m",
        direction="BUY",
        setup_score=score,
        entry_price=3590.0,
        stop_loss=3580.0,
        take_profit_1=3620.0,
        take_profit_2=None,
        risk_reward=3.0,
        fingerprint=fingerprint,
        reasons=[],
        status=status,
        timestamp=CANDLE_TS,
        created_at=CANDLE_TS,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _order(signal_id):
    return PaperOrderCreate(
        signal_id=signal_id,
        symbol="XAU/USD",
        direction=SignalDirection.BUY,
        order_type="MARKET",
        stop_loss=3580.0,
        take_profit_1=3620.0,
    )


def test_single_slot_consumed_setup_and_post_close_cleanup(client, test_db_session):
    signal = _signal(test_db_session, "lifecycle-slot-1")

    trade = PaperOrderExecutor().execute_order(
        test_db_session, _order(signal.id), current_market_price=3590.0
    )
    assert trade.status == "OPEN"
    assert test_db_session.get(Signal, signal.id).status == "EXECUTED"
    registry = test_db_session.query(ExecutedSetup).one()
    assert registry.signal_id == signal.id
    assert registry.trade_id == trade.id

    duplicate = _signal(test_db_session, "lifecycle-slot-duplicate")
    # Second trade is blocked while the first position is still open.
    with pytest.raises(ValueError, match="Position slot unavailable"):
        PaperOrderExecutor().execute_order(
            test_db_session, _order(duplicate.id), current_market_price=3590.0
        )
    assert test_db_session.query(PaperTrade).count() == 1

    # Prime the dashboard signal cache; closing must invalidate it.
    derived_cache._entries[("signals", "XAU/USD", "15m")] = None
    PaperPositionManager().close_position(
        test_db_session, trade.id, current_price=3580.0, exit_reason="SL_HIT"
    )
    assert test_db_session.get(Signal, signal.id).status == "CLOSED"
    assert test_db_session.get(ExecutedSetup, registry.id).status == "CLOSED"
    assert ("signals", "XAU/USD", "15m") not in derived_cache._entries

    # Even after SL_HIT, the consumed candle cannot re-fire.
    with pytest.raises(ValueError, match="already executed"):
        PaperOrderExecutor().execute_order(
            test_db_session, _order(duplicate.id), current_market_price=3590.0
        )
    assert test_db_session.query(PaperTrade).count() == 1

    # The duplicate row is ACTIVE in DB, but the consumed setup excludes it
    # from the active signal feed that drives the sidebar/overlay.
    assert test_db_session.get(Signal, duplicate.id).status == "ACTIVE"
    res = client.get("/api/v1/signals?symbol=XAU%2FUSD")
    assert res.status_code == 200
    assert res.json() == []
