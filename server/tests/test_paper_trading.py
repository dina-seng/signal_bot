"""Unit tests for Virtual Account, Paper Order Execution, Position Management, and SL/TP Monitoring."""

import pytest
from datetime import datetime, timezone

from app.models.candle import Candle
from app.models.paper import VirtualAccount, PaperTrade, AccountTransaction
from app.models.signal import Signal
from app.schemas.paper_trading import (
    AccountDepositRequest,
    AccountResetRequest,
    AutoTradeSignalRequest,
    PaperOrderCreate,
    PaperPositionCloseRequest,
    PaperPositionModifyRequest,
    VirtualAccountCreate,
)
from app.schemas.signal import SignalDirection
from app.services.paper_trading.account_manager import VirtualAccountManager
from app.services.paper_trading.order_executor import PaperOrderExecutor
from app.services.paper_trading.position_manager import PaperPositionManager
from app.services.paper_trading.paper_service import PaperTradingService


def _seed_candle(db, symbol="EUR/USD", close=1.1000):
    """Seed single candle for pricing."""
    c = Candle(
        symbol=symbol,
        timeframe="1h",
        timestamp=datetime.now(timezone.utc),
        open=close,
        high=close + 0.0010,
        low=close - 0.0010,
        close=close,
        volume=100.0,
    )
    db.add(c)
    db.commit()


# -------------------------------------------------------------
# 1. Virtual Account & Margin Tests
# -------------------------------------------------------------
def test_virtual_account_lifecycle(test_db_session):
    """Test virtual account creation, deposit, and reset."""
    manager = VirtualAccountManager()
    acc = manager.get_or_create_default_account(test_db_session)
    assert acc.balance == 10000.0
    assert acc.equity == 10000.0
    assert acc.free_margin == 10000.0
    assert acc.is_active is True

    # Deposit
    manager.deposit_funds(test_db_session, acc.id, 5000.0, "Deposit $5K")
    assert acc.balance == 15000.0
    assert acc.equity == 15000.0

    # Margin calculation
    fx_margin = manager.calculate_required_margin("EUR/USD", lots=1.0, price=1.1000, leverage=100)
    assert fx_margin == 1100.0  # 1.0 * 100,000 * 1.10 / 100

    gold_margin = manager.calculate_required_margin("XAU/USD", lots=1.0, price=2000.0, leverage=100)
    assert gold_margin == 2000.0  # 1.0 * 100 * 2000 / 100


# -------------------------------------------------------------
# 2. Paper Order Execution Tests
# -------------------------------------------------------------
def test_paper_order_execution_and_margin(test_db_session):
    """Test placing a MARKET BUY order and validating margin allocation."""
    _seed_candle(test_db_session, symbol="EUR/USD", close=1.1000)
    service = PaperTradingService()

    order = PaperOrderCreate(
        symbol="EUR/USD",
        direction=SignalDirection.BUY,
        order_type="MARKET",
        position_size=1.0,
        stop_loss=1.0950,
        take_profit_1=1.1100,
        take_profit_2=1.1150,
    )

    trade = service.place_order(test_db_session, order)
    assert trade.status == "OPEN"
    assert trade.symbol == "EUR/USD"
    assert trade.initial_position_size == 1.0
    assert trade.remaining_position_size == 1.0
    assert trade.margin_used > 0.0

    # Verify Account Updated
    acc_summary = service.get_account_summary(test_db_session)
    assert acc_summary.margin_used == trade.margin_used
    assert acc_summary.free_margin == round(acc_summary.equity - trade.margin_used, 2)
    assert acc_summary.open_positions_count == 1


def test_paper_order_insufficient_margin(test_db_session):
    """Test that placing an order exceeding free margin raises ValueError."""
    _seed_candle(test_db_session, symbol="EUR/USD", close=1.1000)
    service = PaperTradingService()

    order = PaperOrderCreate(
        symbol="EUR/USD",
        direction=SignalDirection.BUY,
        order_type="MARKET",
        position_size=50.0,  # 50 standard lots requires $55,000 margin on $10,000 balance!
        stop_loss=1.0950,
        take_profit_1=1.1100,
    )

    with pytest.raises(ValueError, match="Insufficient Free Margin"):
        service.place_order(test_db_session, order)


def test_paper_trade_from_signal(test_db_session):
    """Test converting a Signal database record into an active virtual position."""
    _seed_candle(test_db_session, symbol="GBP/USD", close=1.3000)
    service = PaperTradingService()

    sig = Signal(
        symbol="GBP/USD",
        timeframe="1h",
        direction="BUY",
        setup_score=85.0,
        entry_price=1.3000,
        stop_loss=1.2950,
        take_profit_1=1.3100,
        take_profit_2=1.3150,
        risk_reward=2.0,
        fingerprint="test_sig_fp_123",
        reasons=["Test Buy Setup"],
        status="ACTIVE",
        timestamp=datetime.now(timezone.utc),
    )
    test_db_session.add(sig)
    test_db_session.commit()

    req = AutoTradeSignalRequest(signal_id=sig.id, symbol="GBP/USD")
    trade = service.trade_from_signal(test_db_session, req)
    assert trade.symbol == "GBP/USD"
    assert trade.direction == SignalDirection.BUY
    assert trade.signal_id == sig.id
    assert trade.status == "OPEN"
    assert trade.stop_loss == 1.2950
    assert trade.take_profit_1 == 1.3100


# -------------------------------------------------------------
# 3. Position Management & SL/TP Auto-Monitoring Tests
# -------------------------------------------------------------
def test_partial_close_and_full_close(test_db_session):
    """Test partial position closing (50%) and full liquidation."""
    _seed_candle(test_db_session, symbol="EUR/USD", close=1.1000)
    service = PaperTradingService()

    order = PaperOrderCreate(
        symbol="EUR/USD",
        direction=SignalDirection.BUY,
        order_type="MARKET",
        position_size=1.0,
        stop_loss=1.0950,
        take_profit_1=1.1100,
    )
    trade = service.place_order(test_db_session, order)

    # 1. Partial close 50% at 1.1050 (+50 pips)
    trade_50 = service.close_position(
        test_db_session,
        trade_id=trade.id,
        request=PaperPositionCloseRequest(close_ratio=0.5, exit_price=1.1050, exit_reason="PARTIAL_PROFIT"),
    )
    assert trade_50.status == "PARTIALLY_CLOSED"
    assert trade_50.remaining_position_size == 0.5
    assert trade_50.realized_pnl > 0.0

    # 2. Close remaining 50%
    trade_closed = service.close_position(
        test_db_session,
        trade_id=trade.id,
        request=PaperPositionCloseRequest(close_ratio=1.0, exit_price=1.1060, exit_reason="MANUAL_CLOSE"),
    )
    assert trade_closed.status == "CLOSED"
    assert trade_closed.remaining_position_size == 0.0
    assert trade_closed.margin_used == 0.0


def test_price_sync_sl_and_tp_monitoring(test_db_session, monkeypatch):
    """Legacy 2R/3R scale-out mode (explicit opt-in) still closes 50% at TP1."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "PARTIAL_CLOSE_AT_TP1", True)
    _seed_candle(test_db_session, symbol="EUR/USD", close=1.1000)
    service = PaperTradingService()

    order = PaperOrderCreate(
        symbol="EUR/USD",
        direction=SignalDirection.BUY,
        order_type="MARKET",
        position_size=1.0,
        stop_loss=1.0950,
        take_profit_1=1.1040,
        take_profit_2=1.1080,
    )
    trade = service.place_order(test_db_session, order)

    # 1. Market moves to 1.1045 (triggers TP1: close 50% & move SL to entry 1.1000)
    report1 = service.sync_prices(test_db_session, symbol_prices={"EUR/USD": 1.1045})
    assert report1.tp1_triggered_count == 1

    t1 = service.get_trade_by_id(test_db_session, trade.id)
    assert t1.tp1_hit is True
    assert t1.remaining_position_size == 0.5
    assert t1.stop_loss == t1.entry_price  # Moved to Break-Even!

    # 2. Market moves to 1.1085 (triggers TP2: closes remaining 50%)
    report2 = service.sync_prices(test_db_session, symbol_prices={"EUR/USD": 1.1085})
    assert report2.tp2_triggered_count == 1

    t2 = service.get_trade_by_id(test_db_session, trade.id)
    assert t2.status == "CLOSED"
    assert t2.exit_reason == "TP2_HIT"
    assert t2.realized_pnl > 0.0
    assert t2.return_r > 0.0

    # 3. Verify Portfolio Performance
    perf = service.get_portfolio_performance(test_db_session)
    assert perf.closed_trades == 1
    assert perf.winning_trades == 1
    assert perf.win_rate == 100.0
    assert perf.total_realized_pnl > 0.0


# -------------------------------------------------------------
# 7. Strict risk-budget enforcement (reject instead of min-lot clamp)
# -------------------------------------------------------------
def _small_account(db, balance=214.20):
    account = VirtualAccountManager().get_or_create_default_account(db)
    account.balance = balance
    account.equity = balance
    account.margin_used = 0.0
    account.free_margin = balance
    db.commit()
    return account


def test_wide_stop_is_rejected_when_risk_budget_cannot_fund_min_lot(test_db_session):
    """$214.20 / 0.5% / 77-point stop -> raw lots ~0.0001 -> REJECT, no position."""
    from app.services.paper_trading.order_executor import InsufficientRiskBudgetError

    _small_account(test_db_session)
    _seed_candle(test_db_session, symbol="XAU/USD", close=3592.79)

    order = PaperOrderCreate(
        symbol="XAU/USD", direction=SignalDirection.BUY, order_type="MARKET",
        stop_loss=3515.43, take_profit_1=3633.89, risk_percent=0.5,
    )
    with pytest.raises(InsufficientRiskBudgetError, match="Risk budget insufficient"):
        PaperOrderExecutor().execute_order(
            test_db_session, order, current_market_price=3592.79
        )

    assert test_db_session.query(PaperTrade).filter_by(symbol="XAU/USD").count() == 0


def test_small_stop_is_accepted_with_risk_compliant_lot(test_db_session):
    """5 XAU pips (0.10/pip -> $0.50) on $214.20 -> raw lots >= 0.01 -> ACCEPT."""
    _small_account(test_db_session)
    _seed_candle(test_db_session, symbol="XAU/USD", close=3592.79)

    order = PaperOrderCreate(
        symbol="XAU/USD", direction=SignalDirection.BUY, order_type="MARKET",
        stop_loss=3592.29, take_profit_1=3593.29, risk_percent=0.5,
    )
    trade = PaperOrderExecutor().execute_order(
        test_db_session, order, current_market_price=3592.79
    )

    assert trade.status == "OPEN"
    assert trade.initial_position_size >= 0.01
    risk_distance = abs(trade.entry_price - trade.stop_loss)
    actual_risk = risk_distance * 100.0 * trade.initial_position_size
    assert actual_risk <= 214.20 * 0.005 + 0.02


def test_option_c_affordable_stop_accepted_at_min_lot(test_db_session, monkeypatch):
    """5% risk on $214.20 funds a 9-point stop at 0.01 lot, within budget."""
    from app.core.config import settings
    from app.services.paper_trading.order_executor import InsufficientRiskBudgetError

    monkeypatch.setattr(settings, "MAX_RISK_PERCENT", 5.0)
    _small_account(test_db_session, 214.20)
    _seed_candle(test_db_session, symbol="XAU/USD", close=3592.79)

    order = PaperOrderCreate(
        symbol="XAU/USD", direction=SignalDirection.BUY, order_type="MARKET",
        stop_loss=3583.79, take_profit_1=3610.79, risk_percent=5.0,
    )
    trade = PaperOrderExecutor().execute_order(
        test_db_session, order, current_market_price=3592.79
    )

    budget = 214.20 * 0.05
    realized_risk = abs(trade.entry_price - trade.stop_loss) * 100.0 * trade.initial_position_size
    assert trade.status == "OPEN"
    assert trade.initial_position_size == 0.01
    assert realized_risk <= budget


def test_option_c_wide_stop_rejected_with_affordability_hints(test_db_session, monkeypatch):
    """A 20-point stop on $214.20 at 5% is rejected with both capital levers shown."""
    from app.core.config import settings
    from app.services.paper_trading.order_executor import InsufficientRiskBudgetError

    monkeypatch.setattr(settings, "MAX_RISK_PERCENT", 5.0)
    _small_account(test_db_session, 214.20)
    _seed_candle(test_db_session, symbol="XAU/USD", close=3592.79)

    order = PaperOrderCreate(
        symbol="XAU/USD", direction=SignalDirection.BUY, order_type="MARKET",
        stop_loss=3572.79, take_profit_1=3632.79, risk_percent=5.0,
    )
    with pytest.raises(InsufficientRiskBudgetError) as exc:
        PaperOrderExecutor().execute_order(
            test_db_session, order, current_market_price=3592.79
        )

    message = str(exc.value)
    assert "Max affordable stop" in message
    assert "Balance needed for this stop" in message
    assert "pips" in message
    assert exc.value.max_affordable_points is not None
    assert exc.value.required_balance > 214.20
