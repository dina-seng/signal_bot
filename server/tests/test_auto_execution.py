"""Auto-execution safety gates, DB creation, and Telegram notification."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.candle import Candle
from app.models.paper import PaperTrade
from app.models.signal import Signal
from app.schemas.paper_trading import PaperTradeResponse
from app.schemas.signal import SignalDirection, SignalResponse, SignalStatus
from app.services.market_data.mock_provider import MockMarketDataProvider
from app.services.news.mock_provider import MockNewsProvider
from app.services.paper_trading import PaperTradingService
from app.services.telegram.client import MockTelegramClient
from app.services.telegram.message_formatter import TelegramMessageFormatter
from app.services.telegram.scanner import AutomatedMarketScanner


def _seed_15m_sell_setup(db):
    """Closed 15m candles with a confirmed swing high at 3600."""
    now = datetime.now(timezone.utc)
    bars = [
        (3585, 3590, 3582),
        (3590, 3595, 3585),
        (3598, 3600, 3592),
        (3595, 3598, 3590),
        (3592, 3596, 3588),
        (3590, 3594, 3586),
    ]
    for i, (close, high, low) in enumerate(bars):
        db.add(Candle(
            symbol="XAU/USD", timeframe="15m",
            timestamp=now - timedelta(minutes=15 * (len(bars) - i)),
            open=close, high=high, low=low, close=close, volume=100.0,
        ))
    db.commit()


def _persist_signal(db, fp="auto_fp_1", timeframe="15m"):
    now = datetime.now(timezone.utc)
    sig = Signal(
        symbol="XAU/USD", timeframe=timeframe, direction="SELL", setup_score=80.0,
        entry_price=3590.0, stop_loss=3600.0, take_profit_1=3560.0,
        fingerprint=fp, reasons=[], status="ACTIVE", timestamp=now,
    )
    db.add(sig)
    db.commit()
    db.refresh(sig)
    return sig


def _signal_response(db_signal, timeframe="15m"):
    return SignalResponse(
        id=db_signal.id,
        symbol=db_signal.symbol,
        timeframe=timeframe,
        direction=SignalDirection.SELL,
        setup_score=80.0,
        entry_price=3590.0,
        stop_loss=3600.0,
        take_profit_1=3560.0,
        risk_reward=3.0,
        fingerprint=db_signal.fingerprint,
        reasons=[],
        status=SignalStatus.ACTIVE,
        timestamp=db_signal.timestamp,
    )


def _scanner(db, tg=None):
    return AutomatedMarketScanner(
        paper_service=PaperTradingService(),
        telegram_client=tg or MockTelegramClient(),
        market_provider=MockMarketDataProvider(),
        news_provider=MockNewsProvider(),
    )


def test_auto_execution_creates_trade_and_notifies_telegram(test_db_session):
    _seed_15m_sell_setup(test_db_session)
    db_signal = _persist_signal(test_db_session)
    tg = MockTelegramClient()
    scanner = _scanner(test_db_session, tg)

    trade = asyncio.run(scanner._auto_execute_signal(
        test_db_session, _signal_response(db_signal), True
    ))

    assert trade is not None
    assert test_db_session.query(PaperTrade).count() == 1
    # Ghost-trade regression: auto fills must be OPEN, not PENDING, so the
    # dashboard's ?status=OPEN query can see them.
    assert trade.status == "OPEN"
    assert test_db_session.get(PaperTrade, trade.id).status == "OPEN"
    assert any(
        p.id == trade.id
        for p in PaperTradingService().get_positions(test_db_session, status="OPEN")
    )
    assert trade.initial_position_size == pytest.approx(0.01)
    # Risk Engine anchors levels to the Signal Engine entry (3590), not the fill.
    sl_distance = abs(3590.0 - trade.stop_loss)
    assert abs(trade.take_profit_1 - 3590.0) == pytest.approx(sl_distance * 3, abs=1e-5)
    assert len(tg.sent_messages) >= 1
    assert "AUTO-EXECUTED: SELL XAU/USD" in tg.sent_messages[-1]["text"]
    assert "Lot: 0.01" in tg.sent_messages[-1]["text"]
    assert "R:R 1:3" in tg.sent_messages[-1]["text"]


def test_auto_execution_skips_non_15m_signal(test_db_session):
    _seed_15m_sell_setup(test_db_session)
    db_signal = _persist_signal(test_db_session, fp="auto_fp_non15", timeframe="1h")
    scanner = _scanner(test_db_session)

    trade = asyncio.run(scanner._auto_execute_signal(
        test_db_session, _signal_response(db_signal, timeframe="1h"), False
    ))
    assert trade is None
    assert test_db_session.query(PaperTrade).count() == 0


def test_auto_execution_respects_position_cap(test_db_session, monkeypatch, caplog):
    monkeypatch.setattr(settings, "MAX_OPEN_POSITIONS", 1)
    scanner = _scanner(test_db_session)
    # Occupy the single allowed slot.
    test_db_session.add(PaperTrade(
        account_id=scanner.paper_service.account_manager.get_or_create_default_account(
            test_db_session
        ).id,
        symbol="XAU/USD", direction="BUY", order_type="MARKET", status="OPEN",
        entry_price=3590.0, current_price=3590.0, stop_loss=3580.0,
        take_profit_1=3620.0, initial_position_size=0.01,
        remaining_position_size=0.01, margin_used=0.0,
        opened_at=datetime.now(timezone.utc),
    ))
    test_db_session.commit()
    _seed_15m_sell_setup(test_db_session)
    db_signal = _persist_signal(test_db_session, fp="auto_fp_cap")

    with caplog.at_level("WARNING"):
        trade = asyncio.run(scanner._auto_execute_signal(
            test_db_session, _signal_response(db_signal), False
        ))

    assert trade is None
    assert "Auto-execution skipped: Position cap reached." in caplog.text
    assert test_db_session.query(PaperTrade).count() == 1


def test_auto_execution_skips_wide_15m_stop(test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_EXEC_MAX_SL_POINTS", 5.0)
    _seed_15m_sell_setup(test_db_session)
    db_signal = _persist_signal(test_db_session, fp="auto_fp_wide")
    scanner = _scanner(test_db_session)

    trade = asyncio.run(scanner._auto_execute_signal(
        test_db_session, _signal_response(db_signal), False
    ))
    assert trade is None
    assert test_db_session.query(PaperTrade).count() == 0


def test_auto_execution_is_idempotent(test_db_session):
    _seed_15m_sell_setup(test_db_session)
    db_signal = _persist_signal(test_db_session, fp="auto_fp_dup")
    scanner = _scanner(test_db_session)

    first = asyncio.run(scanner._auto_execute_signal(
        test_db_session, _signal_response(db_signal), False
    ))
    second = asyncio.run(scanner._auto_execute_signal(
        test_db_session, _signal_response(db_signal), False
    ))

    assert first is not None
    assert second is None
    assert test_db_session.query(PaperTrade).count() == 1


def test_formatter_auto_execution_message():
    trade = PaperTradeResponse(
        id=1, account_id=1, symbol="XAU/USD", direction=SignalDirection.SELL,
        order_type="MARKET", status="OPEN", entry_price=3589.95, current_price=3590.0,
        stop_loss=3600.0, take_profit_1=3559.80,
        initial_position_size=0.01, remaining_position_size=0.01,
        margin_used=0.0, tp1_hit=False, realized_pnl=0.0, unrealized_pnl=0.0,
        pnl_pips=0.0, return_r=0.0, opened_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    msg = TelegramMessageFormatter.format_auto_execution(trade)
    assert msg.startswith("🤖 AUTO-EXECUTED: SELL XAU/USD @")
    assert "SL:" in msg and "TP:" in msg
    assert "Lot: 0.01" in msg and "R:R 1:3" in msg
