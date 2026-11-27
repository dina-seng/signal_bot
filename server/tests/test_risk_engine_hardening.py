"""Targeted verification for RiskEngine consolidation and hardening."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.paper import PaperTrade, VirtualAccount
from app.models.signal import Signal
from app.schemas.liquidity import (
    LiquidityEventType,
    LiquidityPool,
    SupportResistanceZone,
    ZoneType,
)
from app.schemas.paper_trading import PaperOrderCreate
from app.schemas.signal import SignalDirection
from app.schemas.structure import SwingType
from app.services.paper_trading.order_executor import PaperOrderExecutor
from app.services.signals.confluence_engine import ConfluenceEngine
from app.services.signals.risk_engine import RiskEngine, RiskLevels
from app.services.strategies.base import StrategyResult

APP_DIR = Path(__file__).resolve().parents[1] / "app"
NOW = datetime.now(timezone.utc)


def _candles(price=2000.0, count=15):
    return [
        SimpleNamespace(high=price + 2.0, low=price - 2.0, close=price)
        for _ in range(count)
    ]


def _swing(swing_type, price):
    return SimpleNamespace(swing_type=swing_type, price=price)


def test_resolve_levels_atr_buffer_min_floor_and_max_cap():
    engine = RiskEngine()

    buffered = engine.resolve_levels(
        symbol="XAU/USD",
        direction=SignalDirection.BUY,
        entry_price=2000.0,
        candles=_candles(),
        swings=[_swing(SwingType.SWING_LOW, 1990.0)],
        balance=10000.0,
        risk_percent=1.0,
    )
    # ATR(14)=4.0 -> stop sits 0.5*ATR (2.0) beyond the swing low.
    assert buffered.stop_loss == pytest.approx(1988.0)
    assert buffered.sl_distance == pytest.approx(12.0)

    floored = engine.resolve_levels(
        symbol="XAU/USD",
        direction=SignalDirection.BUY,
        entry_price=2000.0,
        candles=_candles(),
        swings=[_swing(SwingType.SWING_LOW, 1999.5)],
        balance=10000.0,
        risk_percent=1.0,
    )
    assert floored.sl_distance == pytest.approx(4.0)
    assert floored.stop_loss == pytest.approx(1996.0)

    capped = engine.resolve_levels(
        symbol="XAU/USD",
        direction=SignalDirection.BUY,
        entry_price=2000.0,
        candles=_candles(),
        swings=[_swing(SwingType.SWING_LOW, 1900.0)],
        balance=10000.0,
        risk_percent=1.0,
    )
    assert capped.sl_distance == pytest.approx(25.0)
    assert capped.stop_loss == pytest.approx(1975.0)
    assert capped.take_profit_1 == pytest.approx(2000.0 + 25.0 * capped.rr_multiple)


def test_no_risk_manager_imports_remain_in_app():
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "risk_manager" in text or "RiskManager" in text:
            offenders.append(str(path.relative_to(APP_DIR)))
    assert offenders == []


def _levels():
    return RiskLevels(
        symbol="XAU/USD",
        direction="BUY",
        timeframe="15m",
        entry_price=2000.0,
        stop_loss=1990.0,
        take_profit_1=2030.0,
        take_profit_2=None,
        sl_distance=10.0,
        tp_distance=30.0,
        rr_multiple=3.0,
        lot_size=0.01,
        source="test",
        swing_count=1,
        risk_percent=1.0,
        risk_amount_usd=100.0,
        min_lot_risk_usd=100.0,
        raw_lot_size=1.0,
    )


def _response(engine, sr_zones, pools):
    engine.risk_engine.resolve_levels = lambda **kwargs: _levels()
    return engine._build_signal_response(
        result=StrategyResult(
            strategy_name="Test",
            direction=SignalDirection.BUY,
            score=85.0,
            reasons=[],
        ),
        symbol="XAU/USD",
        timeframe="15m",
        indicator_analysis=SimpleNamespace(
            current_price=2000.0, timestamp=NOW, active_fvgs=[]
        ),
        structure_analysis=SimpleNamespace(sr_zones=sr_zones, liquidity_pools=pools),
        account_balance=10000.0,
        risk_percent=1.0,
        candles_15m=_candles(),
    )


def test_path_block_rejects_obstacle_but_keeps_liquidity_magnet(test_db_session):
    engine = ConfluenceEngine()
    wall = [
        SupportResistanceZone(
            zone_type=ZoneType.RESISTANCE,
            price_low=2005.0,
            price_high=2005.0,
            center_price=2005.0,
            strength=0.8,
            is_fresh=True,
        )
    ]
    blocked = _response(engine, wall, [])
    assert blocked.risk_parameters is not None
    assert blocked.risk_parameters.is_executable is False
    assert "PATH_BLOCK_REJECTION" in blocked.reasons

    magnet = [
        LiquidityPool(
            pool_type=LiquidityEventType.EQUAL_HIGHS,
            price_level=2005.0,
            touch_points=2,
            first_timestamp=NOW,
            last_timestamp=NOW,
            is_swept=False,
        )
    ]
    allowed = _response(engine, [], magnet)
    assert allowed.risk_parameters is not None
    assert allowed.risk_parameters.is_executable is True
    assert "PATH_BLOCK_REJECTION" not in allowed.reasons

    # The persisted blocked signal is refused by the execution engine.
    account = VirtualAccount(name="Test", balance=10000.0, equity=10000.0)
    test_db_session.add(account)
    test_db_session.commit()
    sig = Signal(
        symbol="XAU/USD",
        timeframe="15m",
        direction="BUY",
        setup_score=85.0,
        entry_price=2000.0,
        stop_loss=1990.0,
        take_profit_1=2030.0,
        fingerprint="path-block-test",
        reasons=blocked.reasons,
        status="ACTIVE",
        timestamp=NOW,
    )
    test_db_session.add(sig)
    test_db_session.commit()
    with pytest.raises(ValueError, match="path-blocked"):
        PaperOrderExecutor().execute_order(
            test_db_session,
            PaperOrderCreate(
                signal_id=sig.id,
                symbol="XAU/USD",
                direction=SignalDirection.BUY,
                stop_loss=1990.0,
                take_profit_1=2030.0,
            ),
            current_market_price=2000.0,
        )


def test_post_sl_cooldown_blocks_and_expires_signal(test_db_session):
    account = VirtualAccount(name="Test", balance=10000.0, equity=10000.0)
    test_db_session.add(account)
    test_db_session.commit()
    test_db_session.add(
        PaperTrade(
            account_id=account.id,
            symbol="XAU/USD",
            direction="BUY",
            order_type="MARKET",
            status="CLOSED",
            entry_price=2000.0,
            current_price=1990.0,
            stop_loss=1990.0,
            take_profit_1=2030.0,
            initial_position_size=0.01,
            remaining_position_size=0.01,
            margin_used=0.0,
            opened_at=NOW - timedelta(minutes=10),
            closed_at=NOW - timedelta(minutes=5),
            exit_reason="SL_HIT",
        )
    )
    sig = Signal(
        symbol="XAU/USD",
        timeframe="15m",
        direction="BUY",
        setup_score=85.0,
        entry_price=2000.0,
        stop_loss=1990.0,
        take_profit_1=2030.0,
        fingerprint="sl-cooldown-test",
        reasons=[],
        status="ACTIVE",
        timestamp=NOW,
    )
    test_db_session.add(sig)
    test_db_session.commit()

    with pytest.raises(ValueError, match="Post-SL cooldown"):
        PaperOrderExecutor().execute_order(
            test_db_session,
            PaperOrderCreate(
                signal_id=sig.id,
                symbol="XAU/USD",
                direction=SignalDirection.BUY,
                stop_loss=1990.0,
                take_profit_1=2030.0,
            ),
            current_market_price=2000.0,
        )
    assert test_db_session.get(Signal, sig.id).status == "EXPIRED"
