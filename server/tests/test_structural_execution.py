"""Regression tests: 15m entry = 15m SL, fixed 0.01 lot, dynamic 1:3 RR."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.candle import Candle
from app.models.paper import PaperTrade
from app.models.signal import Signal
from app.schemas.signal import SignalDirection
from app.services.signals.structural_levels import StructuralLevelEngine


def _seed(db, symbol, timeframe, bars, delta):
    """bars: list of (close, high, low); delta: minutes between candles."""
    now = datetime.now(timezone.utc)
    for i, (close, high, low) in enumerate(bars):
        db.add(Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=now - timedelta(minutes=delta * (len(bars) - i)),
            open=close,
            high=high,
            low=low,
            close=close,
            volume=100.0,
        ))
    db.commit()


def _signal(db, timeframe, direction, sl, tp):
    sig = Signal(
        symbol="XAU/USD",
        timeframe=timeframe,
        direction=direction,
        setup_score=80.0,
        entry_price=3590.0,
        stop_loss=sl,
        take_profit_1=tp,
        take_profit_2=tp,
        risk_reward=2.0,
        fingerprint=f"test_{timeframe}_{direction}_{sl}_{tp}",
        reasons=[],
        status="ACTIVE",
        timestamp=datetime.now(timezone.utc),
    )
    db.add(sig)
    db.commit()
    return sig


def test_15m_signal_uses_only_15m_swing_high(client, test_db_session):
    """A 15m SELL must not inherit the much wider 1H structural stop."""
    # 1H structure would give SL=3650 (massive stop).
    _seed(test_db_session, "XAU/USD", "1h", [
        (3640, 3645, 3635),
        (3648, 3650, 3642),
        (3640, 3644, 3636),
        (3635, 3639, 3630),
        (3590, 3595, 3585),
    ], delta=60)
    # 15m structure has the authoritative intraday swing high at 3600.
    _seed(test_db_session, "XAU/USD", "15m", [
        (3585, 3590, 3582),
        (3590, 3595, 3585),
        (3598, 3600, 3592),
        (3595, 3598, 3590),
        (3592, 3596, 3588),
        (3590, 3594, 3586),
    ], delta=15)

    sig = _signal(test_db_session, "15m", "SELL", sl=3650.0, tp=3470.0)
    res = client.post("/api/v1/paper/orders/from-signal", json={
        "signal_id": sig.id,
        "symbol": "XAU/USD",
        "timeframe": "1h",  # client lies — signal timeframe wins
        "risk_percent": 5.0,
    })

    assert res.status_code == 201, res.text
    trade = res.json()
    assert trade["stop_loss"] == pytest.approx(3600.0)  # NOT 3650 (1H)
    assert trade["initial_position_size"] == pytest.approx(0.01)
    sl_distance = abs(trade["entry_price"] - trade["stop_loss"])
    assert abs(trade["take_profit_1"] - trade["entry_price"]) == pytest.approx(
        sl_distance * 3, abs=1e-5
    )
    assert test_db_session.query(PaperTrade).count() == 1


def test_wide_15m_structural_stop_is_not_rejected(client, test_db_session):
    """Wide stops are accepted — no risk-budget / SL-distance 400."""
    _seed(test_db_session, "XAU/USD", "15m", [
        (3590, 3800, 3580),
        (3590, 3800, 3580),
        (3590, 3800, 3580),
        (3590, 3800, 3580),
        (3590, 3800, 3580),
        (3590, 3800, 3580),
    ], delta=15)

    sig = _signal(test_db_session, "15m", "BUY", sl=3000.0, tp=4000.0)
    res = client.post("/api/v1/paper/orders/from-signal", json={
        "signal_id": sig.id,
        "symbol": "XAU/USD",
        "timeframe": "15m",
        "risk_percent": 0.01,
    })

    assert res.status_code == 201, res.text
    trade = res.json()
    assert trade["initial_position_size"] == pytest.approx(0.01)
    assert trade["stop_loss"] == pytest.approx(3580.0)  # 15m swing low


def test_engine_prefers_nearest_swing_and_exact_rr():
    engine = StructuralLevelEngine(rr_multiple=3.0)
    now = datetime.now(timezone.utc)
    candles = [
        {"timestamp": now, "open": 100, "high": 102, "low": 99, "close": 101},
        {"timestamp": now, "open": 101, "high": 103, "low": 100, "close": 102},
        {"timestamp": now, "open": 102, "high": 105, "low": 101, "close": 104},  # swing high 105
        {"timestamp": now, "open": 104, "high": 106, "low": 103, "close": 105},
        {"timestamp": now, "open": 105, "high": 108, "low": 104, "close": 107},  # swing high 108
        {"timestamp": now, "open": 106, "high": 107, "low": 105, "close": 106},
        {"timestamp": now, "open": 106, "high": 106, "low": 104, "close": 105},
    ]

    levels = engine.resolve(
        candles=candles,
        direction=SignalDirection.SELL,
        entry_price=106.0,
        timeframe="15m",
        pip_size=0.1,
    )
    assert levels.structural_sl == pytest.approx(108.0)
    assert levels.sl_distance == pytest.approx(2.0)
    assert levels.take_profit_1 == pytest.approx(100.0)
    assert levels.rr_multiple == 3.0
    assert levels.source == "15m_swing_high"
