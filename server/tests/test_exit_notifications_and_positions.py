"""Regressions: truthful Telegram exits and visible open paper positions."""

import asyncio
from datetime import datetime, timezone

from app.models.paper import PaperTrade
from app.schemas.signal import SignalDirection
from app.services.paper_trading import PaperTradingService
from app.services.paper_trading.order_executor import PaperOrderExecutor
from app.services.telegram.client import MockTelegramClient
from app.services.telegram.message_formatter import TelegramMessageFormatter
from app.services.telegram.scanner import AutomatedMarketScanner


def _closed_trade(**overrides) -> PaperTrade:
    now = datetime.now(timezone.utc)
    fields = dict(
        id=1,
        account_id=1,
        signal_id=99,
        symbol="XAU/USD",
        direction=SignalDirection.BUY.value,
        order_type="MARKET",
        status="CLOSED",
        entry_price=2000.0,
        current_price=2060.0,
        stop_loss=1980.0,
        take_profit_1=2060.0,
        take_profit_2=None,
        initial_position_size=0.01,
        remaining_position_size=0.0,
        margin_used=0.0,
        tp1_hit=False,
        realized_pnl=42.08,
        unrealized_pnl=0.0,
        pnl_pips=59.8,
        return_r=2.98,
        exit_price=2060.0,
        exit_reason="TP1_FULL_EXIT",
        opened_at=now,
        closed_at=now,
        created_at=now,
    )
    fields.update(overrides)
    return PaperTrade(**fields)


def _scanner(tg: MockTelegramClient) -> AutomatedMarketScanner:
    return AutomatedMarketScanner(telegram_client=tg)


def test_take_profit_template_reports_win_with_r_multiple():
    text = TelegramMessageFormatter.format_take_profit_hit(
        "XAU/USD", 2060.0, 42.08, 2.98, closed_lots=0.01
    )
    assert "TAKE PROFIT HIT" in text
    assert "STOP LOSS" not in text
    assert "+$42.08" in text
    assert "+2.98R" in text


def test_tp1_full_exit_is_announced_as_take_profit():
    tg = MockTelegramClient()
    scanner = _scanner(tg)
    trade = _closed_trade()
    event = "Position #1 (XAU/USD) hit TP1 (no TP2 set): full exit."

    sent = asyncio.run(scanner._send_trade_exit_alert(trade, event))

    assert sent is True
    text = tg.sent_messages[-1]["text"]
    assert "TAKE PROFIT HIT" in text
    assert "STOP LOSS HIT" not in text
    assert "$42.08" in text
    assert "+2.98R" in text
    assert "2060.00" in text or "2060.0" in text


def test_real_stop_loss_is_announced_as_stop_loss():
    tg = MockTelegramClient()
    scanner = _scanner(tg)
    trade = _closed_trade(
        exit_reason="SL_HIT",
        realized_pnl=-15.0,
        return_r=-1.0,
        exit_price=1980.0,
    )
    event = "Position #1 (XAU/USD) hit SL_HIT @ 1980.00000"

    asyncio.run(scanner._send_trade_exit_alert(trade, event))

    text = tg.sent_messages[-1]["text"]
    assert "STOP LOSS HIT" in text
    assert "TAKE PROFIT" not in text
    assert "-$15.00" in text
    assert "-1.00R" in text


def test_exit_classification_falls_back_to_price_and_pnl():
    scanner = _scanner(MockTelegramClient())
    assert scanner._classify_exit(_closed_trade(exit_reason=None), "") == "TP"
    assert (
        scanner._classify_exit(
            _closed_trade(
                exit_reason=None,
                exit_price=1980.0,
                realized_pnl=-15.0,
                return_r=-1.0,
            ),
            "",
        )
        == "SL"
    )


def test_open_positions_query_keeps_partially_closed_runners(test_db_session):
    service = PaperTradingService()
    account = service.account_manager.get_or_create_default_account(test_db_session)
    now = datetime.now(timezone.utc)

    for status in ("OPEN", "PARTIALLY_CLOSED", "CLOSED"):
        test_db_session.add(
            PaperTrade(
                account_id=account.id,
                symbol="XAU/USD",
                direction=SignalDirection.BUY.value,
                order_type="MARKET",
                status=status,
                entry_price=2000.0,
                current_price=2001.0,
                stop_loss=1980.0,
                take_profit_1=2060.0,
                initial_position_size=0.01,
                remaining_position_size=0.01,
                margin_used=1.0,
                opened_at=now,
            )
        )
    test_db_session.commit()

    statuses = {p.status for p in service.get_positions(test_db_session, status="OPEN")}
    assert statuses == {"OPEN", "PARTIALLY_CLOSED"}


def test_pending_market_trade_is_repaired_to_open(test_db_session):
    executor = PaperOrderExecutor()
    account = executor.account_manager.get_or_create_default_account(test_db_session)
    now = datetime.now(timezone.utc)
    trade = PaperTrade(
        account_id=account.id,
        symbol="XAU/USD",
        direction=SignalDirection.BUY.value,
        order_type="MARKET",
        status="PENDING",
        entry_price=2000.0,
        current_price=2000.0,
        stop_loss=1980.0,
        take_profit_1=2060.0,
        initial_position_size=0.01,
        remaining_position_size=0.01,
        margin_used=0.0,
        opened_at=now,
    )
    test_db_session.add(trade)
    test_db_session.commit()
    test_db_session.refresh(trade)

    fixed = executor._ensure_auto_trade_open(test_db_session, trade, 2000.0)

    assert fixed.status == "OPEN"
    assert test_db_session.get(PaperTrade, trade.id).status == "OPEN"
    assert fixed.target_entry_price is None
