"""A–F: XAUUSD sizing / risk-consistency / TP regression tests."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.candle import Candle
from app.schemas.paper_trading import PaperOrderCreate
from app.schemas.signal import RiskParameters, SignalDirection
from app.services.paper_trading.broker_spec import get_broker_spec
from app.services.paper_trading.order_executor import (
    InsufficientRiskBudgetError,
    PaperOrderExecutor,
)
from app.services.paper_trading.paper_service import PaperTradingService
from app.services.paper_trading.account_manager import VirtualAccountManager
from app.services.signals import RiskManager

MARKET = 4000.0
HALF_SPREAD = 0.05


def _seed(db, price=MARKET):
    db.add(Candle(
        symbol="XAU/USD", timeframe="1h", timestamp=datetime.now(timezone.utc),
        open=price, high=price + 1, low=price - 1, close=price, volume=100.0,
    ))
    db.commit()


def _account(db, balance=200.0):
    acc = VirtualAccountManager().get_or_create_default_account(db)
    acc.balance = balance
    acc.equity = balance
    acc.free_margin = balance
    acc.margin_used = 0.0
    db.commit()
    return acc


def _order(distance, risk_pct=None):
    """BUY with exec distance (post half-spread) == distance."""
    return PaperOrderCreate(
        symbol="XAU/USD", direction=SignalDirection.BUY, order_type="MARKET",
        stop_loss=round(MARKET + HALF_SPREAD - distance, 5),
        take_profit_1=round(MARKET + distance, 5),
        risk_percent=risk_pct,
    )


# ---------------------------------------------------------------- A
def test_a_valid_min_lot_execution(test_db_session):
    _account(test_db_session, 200.0)
    _seed(test_db_session)
    distance = 8.82

    trade = PaperOrderExecutor().execute_order(
        test_db_session, _order(distance), current_market_price=MARKET
    )
    risk = trade.initial_position_size * 100.0 * distance
    assert trade.initial_position_size == pytest.approx(0.01)
    assert risk == pytest.approx(8.82, abs=0.01)
    assert risk <= 10.0

    # Force an exact 8.82 price-unit stop via structural support (ATR default 6.0
    # contributes 0.5*ATR = 3.0 below the support level).
    rp = RiskManager().calculate_trade_risk(
        symbol="XAU/USD", direction=SignalDirection.BUY,
        entry_price=MARKET, key_support_low=MARKET - distance + 3.0,
        account_balance=200.0, risk_percent=5.0,
    )
    assert rp.raw_lot_size == pytest.approx(0.01134, abs=0.0001)
    assert rp.suggested_lot_size == pytest.approx(0.01)
    assert rp.is_executable is True


# ---------------------------------------------------------------- B
def test_b_min_lot_exceeds_budget_rejected(test_db_session):
    _account(test_db_session, 200.0)
    _seed(test_db_session)
    with pytest.raises(InsufficientRiskBudgetError):
        PaperOrderExecutor().execute_order(
            test_db_session, _order(30.38), current_market_price=MARKET
        )

    rp = RiskManager().calculate_trade_risk(
        symbol="XAU/USD", direction=SignalDirection.BUY,
        entry_price=MARKET, atr_value=30.38, account_balance=200.0,
        risk_percent=5.0,
    )
    assert rp.is_executable is False
    assert rp.suggested_lot_size == 0.0
    assert rp.min_lot_risk_usd > 10.0


# ---------------------------------------------------------------- C
def test_c_risk_config_consistency():
    assert settings.MAX_RISK_PERCENT == pytest.approx(5.0)

    # Schema default matches the authoritative setting.
    assert RiskParameters(
        entry_price=1.0, stop_loss=0.9, take_profit_1=1.2, take_profit_2=1.3,
        risk_pips=1.0, reward_pips_tp1=2.0, reward_pips_tp2=3.0,
        risk_reward_tp1=2.0, risk_reward_tp2=3.0, risk_amount_usd=1.0,
        suggested_lot_size=0.01,
    ).risk_percent == pytest.approx(5.0)

    # Signal sizing with no explicit risk resolves to the setting.
    rp = RiskManager().calculate_trade_risk(
        symbol="XAU/USD", direction=SignalDirection.BUY,
        entry_price=MARKET, atr_value=8.82, account_balance=200.0,
        risk_percent=None,
    )
    assert rp.risk_percent == pytest.approx(settings.MAX_RISK_PERCENT)


# ---------------------------------------------------------------- D
def test_d_volume_step_rounding_down():
    exness = get_broker_spec("exness_standard_xauusd")
    assert exness.floor_lots(Decimal("0.01134")) == Decimal("0.01")
    assert exness.floor_lots(Decimal("0.01999")) == Decimal("0.01")
    assert exness.floor_lots(Decimal("0.09999")) == Decimal("0.09")
    assert exness.floor_lots(Decimal("0.29")) == Decimal("0.29")
    assert exness.floor_lots(Decimal("0.07")) == Decimal("0.07")
    fractional = get_broker_spec("theoretical_fractional")
    assert fractional.floor_lots(Decimal("0.003803")) == Decimal("0.0038")


# ---------------------------------------------------------------- E
def test_e_min_lot_tp_management_no_invalid_partial(test_db_session):
    _account(test_db_session, 200.0)
    _seed(test_db_session)
    service = PaperTradingService()
    order = PaperOrderCreate(
        symbol="XAU/USD", direction=SignalDirection.BUY, order_type="MARKET",
        position_size=0.01, stop_loss=3990.0,
        take_profit_1=4010.0, take_profit_2=4015.0,
    )
    trade = service.place_order(test_db_session, order)

    report1 = service.sync_prices(test_db_session, symbol_prices={"XAU/USD": 4010.0})
    assert report1.tp1_triggered_count == 0  # no 0.005-lot partial close
    t1 = service.get_trade_by_id(test_db_session, trade.id)
    assert t1.status == "OPEN"
    assert t1.remaining_position_size == pytest.approx(0.01)
    assert t1.tp1_hit is False

    report2 = service.sync_prices(test_db_session, symbol_prices={"XAU/USD": 4015.0})
    assert report2.tp2_triggered_count == 1
    t2 = service.get_trade_by_id(test_db_session, trade.id)
    assert t2.status == "CLOSED"
    assert t2.exit_reason == "TP2_HIT"


# ---------------------------------------------------------------- F
def test_f_full_3r_exit_is_15_percent(test_db_session):
    _account(test_db_session, 200.0)
    _seed(test_db_session)
    service = PaperTradingService()

    # 3R geometry: risk $10 (0.01 lot x 100 x $10), reward $30 = 15% of $200.
    order = PaperOrderCreate(
        symbol="XAU/USD", direction=SignalDirection.BUY, order_type="MARKET",
        position_size=0.01, stop_loss=3990.05,
        take_profit_1=4030.05, take_profit_2=4030.05,
    )
    trade = service.place_order(test_db_session, order)
    report = service.sync_prices(test_db_session, symbol_prices={"XAU/USD": 4030.05})

    assert report.tp2_triggered_count == 1
    closed = service.get_trade_by_id(test_db_session, trade.id)
    assert closed.status == "CLOSED"
    assert closed.realized_pnl == pytest.approx(30.0, abs=0.01)
    assert closed.realized_pnl / 200.0 == pytest.approx(0.15, abs=0.001)

    rp = RiskManager().calculate_trade_risk(
        symbol="XAU/USD", direction=SignalDirection.BUY,
        entry_price=MARKET, atr_value=10.0, account_balance=200.0,
        risk_percent=5.0,
    )
    assert rp.risk_reward_tp1 == pytest.approx(3.0)
    assert rp.risk_reward_tp2 == pytest.approx(3.0)
