"""Regression: TP breaches on a live tick must close immediately and exactly once."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.paper import AccountTransaction, PaperTrade, VirtualAccount
from app.services.paper_trading import PaperTradingService
from app.services.paper_trading.account_manager import VirtualAccountManager
from app.services.paper_trading.position_manager import PaperPositionManager


def _seed_sell_trade(db):
    account = VirtualAccountManager().get_or_create_default_account(db)
    trade = PaperTrade(
        account_id=account.id,
        symbol="XAU/USD",
        direction="SELL",
        order_type="MARKET",
        status="OPEN",
        entry_price=3572.94,
        current_price=3572.94,
        stop_loss=3575.65,
        take_profit_1=3565.04,
        take_profit_2=None,
        initial_position_size=0.01,
        remaining_position_size=0.01,
        margin_used=10.0,
        opened_at=datetime.now(timezone.utc),
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade, account


def test_live_tick_closes_tp_within_one_second(test_db_session):
    trade, _ = _seed_sell_trade(test_db_session)

    started = time.perf_counter()
    report = PaperTradingService().sync_prices(
        test_db_session, symbol_prices={"XAU/USD": 3561.31}
    )
    elapsed = time.perf_counter() - started

    test_db_session.refresh(trade)
    assert elapsed < 1.0
    assert trade.status == "CLOSED"
    assert trade.exit_reason == "TP1_FULL_EXIT"
    assert trade.realized_pnl > 0
    assert any("TP1" in event for event in report.events)


def test_concurrent_closes_do_not_double_credit(test_db_session, monkeypatch):
    trade, account = _seed_sell_trade(test_db_session)

    original = VirtualAccountManager.recalculate_account_financials

    def slow_recalc(self, db, acc):
        # Widen the race window so the second caller hits the in-process lock.
        time.sleep(0.05)
        return original(self, db, acc)

    monkeypatch.setattr(
        VirtualAccountManager, "recalculate_account_financials", slow_recalc
    )

    def attempt():
        db = SessionLocal()
        try:
            PaperPositionManager().close_position(
                db,
                trade.id,
                current_price=3565.04,
                exit_reason="TP1_FULL_EXIT",
            )
            return "ok"
        except Exception as exc:
            return str(exc)
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))

    assert results.count("ok") == 1
    test_db_session.refresh(trade)
    test_db_session.refresh(account)
    assert trade.status == "CLOSED"
    transactions = (
        test_db_session.query(AccountTransaction)
        .filter(AccountTransaction.trade_id == trade.id)
        .all()
    )
    assert len(transactions) == 1
