"""Unit tests for Telegram Bot, Message Formatters, Command Handlers, and Background Scanner."""

import pytest
from datetime import datetime, timezone, timedelta

from app.models.candle import Candle
from app.models.signal import Signal
from app.schemas.news import NewsEventResponse
from app.schemas.paper_trading import PaperPortfolioPerformance, VirtualAccountResponse
from app.schemas.signal import (
    MarketScanResponse,
    MarketScanSymbolResult,
    RiskParameters,
    ScoreBreakdown,
    SignalDirection,
    SignalResponse,
    SignalStatus,
)
from app.schemas.telegram import TelegramCommandRequest, TelegramMessageRequest
from app.services.paper_trading import PaperTradingService
from app.services.telegram.client import MockTelegramClient
from app.services.telegram.command_handler import TelegramCommandHandler
from app.services.telegram.message_formatter import TelegramMessageFormatter
from app.services.telegram.scanner import AutomatedMarketScanner
from app.services.telegram.telegram_service import TelegramBotService


def _seed_candles(db, symbol="EUR/USD", count=40):
    """Seed test candles."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(count):
        c = Candle(
            symbol=symbol,
            timeframe="1h",
            timestamp=now + timedelta(hours=i),
            open=1.1000 + (i * 0.0005),
            high=1.1020 + (i * 0.0005),
            low=1.0990 + (i * 0.0005),
            close=1.1010 + (i * 0.0005),
            volume=500.0,
        )
        db.add(c)
    db.commit()


# -------------------------------------------------------------
# 1. Message Formatter Tests
# -------------------------------------------------------------
def test_telegram_message_formatter():
    """Verify Markdown formatting across signals, TP/SL alerts, news, and portfolio."""
    formatter = TelegramMessageFormatter()
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    # 1. Signal Alert Formatting
    rp = RiskParameters(
        entry_price=1.1000,
        stop_loss=1.0960,
        take_profit_1=1.1080,
        take_profit_2=1.1120,
        risk_pips=40.0,
        reward_pips_tp1=80.0,
        reward_pips_tp2=120.0,
        risk_reward_tp1=2.0,
        risk_reward_tp2=3.0,
        account_balance=10000.0,
        risk_percent=0.5,
        risk_amount_usd=50.0,
        suggested_lot_size=0.13,
    )
    bd = ScoreBreakdown(
        structure_score=30.0,
        liquidity_score=25.0,
        indicators_score=20.0,
        price_action_score=15.0,
        total_score=90.0,
        is_qualified=True,
    )
    sig = SignalResponse(
        symbol="EUR/USD",
        timeframe="1h",
        direction=SignalDirection.BUY,
        setup_score=90.0,
        entry_price=1.1000,
        stop_loss=1.0960,
        take_profit_1=1.1080,
        take_profit_2=1.1120,
        risk_reward=2.0,
        fingerprint="fp123",
        reasons=["Bullish BOS Continuation", "EMA Stack"],
        status=SignalStatus.ACTIVE,
        timestamp=now,
        score_breakdown=bd,
        risk_parameters=rp,
    )

    alert_text = formatter.format_signal_alert(sig)
    assert "EUR/USD" in alert_text
    assert "STRONG BUY" in alert_text
    assert "90.0 / 100" in alert_text
    assert "1.10000" in alert_text
    assert "1.09600" in alert_text

    # 2. TP/SL Alerts
    tp1_text = formatter.format_tp1_hit("EUR/USD", 1.1080, 260.0, 1.1000)
    assert "TAKE PROFIT 1 REACHED" in tp1_text
    assert "+$260.00" in tp1_text

    tp2_text = formatter.format_tp2_hit("EUR/USD", 1.1120, 520.0, 3.0)
    assert "TAKE PROFIT 2 TARGET HIT" in tp2_text
    assert "+$520.00" in tp2_text

    sl_text = formatter.format_sl_hit("EUR/USD", 1.0960, -50.0, is_be=False)
    assert "STOP LOSS HIT" in sl_text

    # 3. Help Menu
    help_text = formatter.format_help_menu()
    assert "/scan" in help_text
    assert "/signal" in help_text
    assert "/news" in help_text


def test_telegram_message_formatter_escaping():
    """Verify sanitization of special characters (underscores, asterisks, brackets, dots)."""
    formatter = TelegramMessageFormatter()

    # Test escape_markdown v1
    assert formatter.escape_markdown("USD_JPY") == r"USD\_JPY"
    assert formatter.escape_markdown("[FVG] *Trigger*") == r"\[FVG\] \*Trigger\*"
    assert formatter.escape_markdown(r"C:\test") == r"C:\\test"

    # Test escape_markdown_v2
    v2_escaped = formatter.escape_markdown_v2("Price > 20.5 (1.5%) - [Test] #1")
    assert r"\>" in v2_escaped
    assert r"\." in v2_escaped
    assert r"\(" in v2_escaped
    assert r"\)" in v2_escaped
    assert r"\-" in v2_escaped
    assert r"\[" in v2_escaped
    assert r"\]" in v2_escaped
    assert r"\#" in v2_escaped

    # Test escape_code
    assert formatter.escape_code("test`code`span") == "test'code'span"

    # Test escape_html
    assert formatter.escape_html("<b>Test & 'Score'</b>") == "&lt;b&gt;Test &amp; 'Score'&lt;/b&gt;"

    # Test signal formatting with special characters in reasons and symbol
    sig = SignalResponse(
        symbol="USD_JPY",
        timeframe="15m",
        direction=SignalDirection.BUY,
        setup_score=85.0,
        entry_price=150.123,
        stop_loss=149.500,
        take_profit_1=151.369,
        fingerprint="fp_special_123",
        reasons=[
            "Candlestick Trigger: BULLISH_PIN_BAR",
            "Fair Value Gap [FVG] filled (150.00)",
            "Price > 20 > 50 > 200 EMA *Bullish*",
        ],
        status=SignalStatus.ACTIVE,
        timestamp=datetime.now(timezone.utc),
    )

    alert = formatter.format_signal_alert(sig)
    assert r"BULLISH\_PIN\_BAR" in alert
    assert r"\[FVG\]" in alert
    assert r"\*Bullish\*" in alert
    assert "`USD_JPY`" in alert  # symbol inside code span


# -------------------------------------------------------------
# 2. Mock Telegram Client Tests
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_mock_telegram_client():
    """Verify MockTelegramClient records messages into history queue."""
    client = MockTelegramClient()
    res = await client.send_message(text="Hello Telegram!", chat_id="12345")
    assert res.success is True
    assert res.chat_id == "12345"
    assert len(client.sent_messages) == 1

    status = client.get_status()
    assert status.mode == "MOCK"
    assert status.total_messages_sent == 1


from app.services.news.mock_provider import MockNewsProvider


# -------------------------------------------------------------
# 3. Command Handler Tests
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_telegram_command_handler(test_db_session):
    """Verify handling interactive bot commands (/help, /scan, /news, /account)."""
    _seed_candles(test_db_session, symbol="EUR/USD", count=40)
    mock_client = MockTelegramClient()
    mock_news = MockNewsProvider(reference_time=datetime.now(timezone.utc))
    handler = TelegramCommandHandler(
        telegram_client=mock_client,
        news_provider=mock_news,
    )

    # 1. /help
    res_help = await handler.handle_command(test_db_session, TelegramCommandRequest(command="/help"))
    assert res_help.handled_successfully is True
    assert "/scan" in res_help.reply_text

    # 2. /scan
    res_scan = await handler.handle_command(test_db_session, TelegramCommandRequest(command="/scan"))
    assert res_scan.handled_successfully is True
    assert "UNIFIED SCANNER" in res_scan.reply_text or "MULTI-MARKET SCANNER" in res_scan.reply_text

    # 3. /news
    res_news = await handler.handle_command(test_db_session, TelegramCommandRequest(command="/news"))
    assert res_news.handled_successfully is True
    assert "ECONOMIC CALENDAR" in res_news.reply_text

    # 4. /account
    res_acc = await handler.handle_command(test_db_session, TelegramCommandRequest(command="/account"))
    assert res_acc.handled_successfully is True
    assert "VIRTUAL TRADING PORTFOLIO" in res_acc.reply_text


# -------------------------------------------------------------
# 4. Automated Market Scanner Tests
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_automated_market_scanner_deduplication(test_db_session):
    """Verify background scanner evaluates markets and deduplicates alerts."""
    _seed_candles(test_db_session, symbol="EUR/USD", count=40)
    mock_client = MockTelegramClient()
    paper_service = PaperTradingService()
    scanner = AutomatedMarketScanner(
        paper_service=paper_service,
        telegram_client=mock_client,
    )

    # Run Scan Cycle 1
    res1 = await scanner.run_scan_cycle(
        db=test_db_session,
        symbols=["EUR/USD"],
        timeframe="1h",
        broadcast_to_telegram=True,
        auto_paper_trade=True,
    )
    assert res1.symbols_scanned == ["EUR/USD"]
    assert res1.execution_time_seconds >= 0.0

    # Run Scan Cycle 2 (deduplication check)
    res2 = await scanner.run_scan_cycle(
        db=test_db_session,
        symbols=["EUR/USD"],
        timeframe="1h",
        broadcast_to_telegram=True,
        auto_paper_trade=True,
    )
    assert res2.signals_broadcast_count == 0  # Deduplicated!

    # Check status
    status = scanner.get_status()
    assert status.total_scans_completed == 2
