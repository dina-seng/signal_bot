"""Hermetic tests for broker-spec paper position sizing."""

import random
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.candle import Candle
from app.schemas.paper_trading import PaperOrderCreate
from app.schemas.signal import SignalDirection
from app.services.paper_trading.account_manager import VirtualAccountManager
from app.services.paper_trading.broker_spec import BROKER_SPECS, get_broker_spec
from app.services.paper_trading.order_executor import PaperOrderExecutor

MARKET = 4000.0
HALF_SPREAD = 0.05  # XAU pip_size 0.10 -> 0.5 pip = 0.05 price units


def _seed(db, price=MARKET):
    db.add(Candle(
        symbol="XAU/USD", timeframe="1h",
        timestamp=datetime.now(timezone.utc),
        open=price, high=price + 1, low=price - 1, close=price, volume=100.0,
    ))
    db.commit()


def _account(db, balance=200.0):
    account = VirtualAccountManager().get_or_create_default_account(db)
    account.balance = balance
    account.equity = balance
    account.free_margin = balance
    account.margin_used = 0.0
    db.commit()
    return account


def _executor(name):
    spec = get_broker_spec(name)
    executor = PaperOrderExecutor()
    executor.broker_spec = spec
    return executor


def _order(distance, risk_pct=5.0):
    """BUY whose *exec* stop distance (after half-spread) equals `distance`."""
    stop = MARKET + HALF_SPREAD - distance
    return PaperOrderCreate(
        symbol="XAU/USD", direction=SignalDirection.BUY, order_type="MARKET",
        stop_loss=round(stop, 5), take_profit_1=round(MARKET + distance, 5),
        risk_percent=risk_pct,
    )


def test_invariant_lots_times_contract_times_distance_within_budget():
    random.seed(20261123)
    checked = 0
    for _ in range(800):
        spec = random.choice(list(BROKER_SPECS.values()))
        distance = Decimal(str(round(random.uniform(0.01, 250.0), 5)))
        balance = Decimal(str(round(random.uniform(50.0, 100000.0), 2)))
        risk_pct = Decimal(str(random.choice([0.5, 1.0, 2.0, 5.0])))
        budget = balance * risk_pct / Decimal("100")
        raw = budget / (distance * spec.contract_size)
        lots = spec.floor_lots(raw)
        if lots < spec.min_lot:
            continue  # correctly rejected by the driver
        risk = lots * spec.contract_size * distance
        assert risk <= budget + Decimal("1e-9"), (spec.name, distance, risk, budget)
        checked += 1
    assert checked > 100


def test_distance_88_wide_stop_executes_at_profile_min_lot(test_db_session, monkeypatch):
    """Wide stops no longer reject: both profiles use their own fixed minimum lot."""
    monkeypatch.setattr(settings, "BROKER_SPEC", "exness_standard_xauusd")
    _account(test_db_session, 200.0)
    _seed(test_db_session)

    exness_trade = _executor("exness_standard_xauusd").execute_order(
        test_db_session, _order(88.0), current_market_price=MARKET
    )
    assert exness_trade.status == "OPEN"
    assert exness_trade.initial_position_size == pytest.approx(0.01)
    assert exness_trade.broker_profile == "exness_standard_xauusd"

    fractional_trade = _executor("theoretical_fractional").execute_order(
        test_db_session, _order(88.0), current_market_price=MARKET
    )
    assert fractional_trade.status == "OPEN"
    assert fractional_trade.initial_position_size == pytest.approx(0.0001)
    assert fractional_trade.broker_profile == "theoretical_fractional"


def test_distance_10_exness_accepts_001_lot_at_10_dollars(test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "BROKER_SPEC", "exness_standard_xauusd")
    _account(test_db_session, 200.0)
    _seed(test_db_session)

    trade = _executor("exness_standard_xauusd").execute_order(
        test_db_session, _order(10.0), current_market_price=MARKET
    )
    assert trade.initial_position_size == pytest.approx(0.01)
    assert trade.initial_position_size * 100.0 * 10.0 == pytest.approx(10.0)
    assert trade.broker_profile == "exness_standard_xauusd"


def test_decimal_floor_cases():
    exness = get_broker_spec("exness_standard_xauusd")
    assert exness.floor_lots(Decimal("0.29")) == Decimal("0.29")
    assert exness.floor_lots(Decimal("0.07")) == Decimal("0.07")
    assert exness.floor_lots(Decimal("0.299999")) == Decimal("0.29")
    assert exness.floor_lots(Decimal("0.079999")) == Decimal("0.07")

    fractional = get_broker_spec("theoretical_fractional")
    assert fractional.floor_lots(Decimal("0.29")) == Decimal("0.2900")
    assert fractional.floor_lots(Decimal("0.07007")) == Decimal("0.0700")


def test_default_profile_is_exness():
    assert get_broker_spec().name == "exness_standard_xauusd"
    assert get_broker_spec().contract_size == Decimal("100")
