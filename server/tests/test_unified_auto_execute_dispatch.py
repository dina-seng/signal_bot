"""Targeted test: one auto-execute + Telegram dispatch path, no pending-fill mode."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.models.candle import Candle
from app.models.signal import Signal
from app.schemas.signal import (
    MarketScanResponse,
    MarketScanSymbolResult,
    SignalDirection,
    SignalResponse,
    SignalStatus,
)
from app.services.market_data.mock_provider import MockMarketDataProvider
from app.services.news.mock_provider import MockNewsProvider
from app.services.paper_trading import PaperTradingService
from app.services.telegram.client import MockTelegramClient
from app.services.telegram.scanner import AutomatedMarketScanner

NOW = datetime.now(timezone.utc)


def _seed_15m_bars(db):
    bars = [
        (1.1190, 1.1200, 1.1185),
        (1.1195, 1.1202, 1.1188),
        (1.1180, 1.1195, 1.1175),
        (1.1190, 1.1200, 1.1182),
        (1.1200, 1.1208, 1.1192),
        (1.1200, 1.1206, 1.1194),
    ]
    for i, (close, high, low) in enumerate(bars):
        db.add(
            Candle(
                symbol="EUR/USD",
                timeframe="15m",
                timestamp=NOW - timedelta(minutes=15 * (len(bars) - i)),
                open=close,
                high=high,
                low=low,
                close=close,
                volume=100.0,
            )
        )
    db.commit()


def _seed_signal(db, fingerprint, score=92.0, timestamp=None):
    row = Signal(
        symbol="EUR/USD",
        timeframe="15m",
        direction="BUY",
        setup_score=score,
        entry_price=1.1200,
        stop_loss=1.1170,
        take_profit_1=1.1300,
        take_profit_2=None,
        risk_reward=3.0,
        fingerprint=fingerprint,
        reasons=["test setup"],
        status="ACTIVE",
        timestamp=timestamp or NOW,
        created_at=timestamp or NOW,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _scanner(tg):
    return AutomatedMarketScanner(
        telegram_client=tg,
        market_provider=MockMarketDataProvider(base_price=1.1200, volatility=0.0001),
        news_provider=MockNewsProvider(),
    )


def _mock_scan(sig):
    return MarketScanResponse(
        timestamp=NOW,
        scanned_count=1,
        actionable_count=1,
        results=[
            MarketScanSymbolResult(
                symbol=sig.symbol,
                timeframe=sig.timeframe,
                direction=SignalDirection(sig.direction),
                setup_score=sig.setup_score,
                is_actionable=True,
                signal=SignalResponse.model_validate(sig),
                blackout_blocked=False,
                reasons=[],
            )
        ],
    )


@pytest.mark.asyncio
async def test_unified_dispatch_executes_alerts_and_skips_without_pending_fill(
    client, test_db_session
):
    settings.PAPER_TRADING = True
    settings.SCANNER_AUTO_TRADE_PAPER = True
    PaperTradingService().account_manager.get_or_create_default_account(test_db_session)
    _seed_15m_bars(test_db_session)

    first = _seed_signal(test_db_session, "unified-auto-first")
    tg = MockTelegramClient()
    scanner = _scanner(tg)
    scanner.signal_generator.scan_all_symbols = MagicMock(
        return_value=_mock_scan(first)
    )

    res = await scanner.run_scan_cycle(
        db=test_db_session,
        symbols=["EUR/USD"],
        timeframes=["15m"],
        broadcast_to_telegram=True,
        auto_paper_trade=True,
    )

    assert res.paper_trades_opened_count == 1
    assert test_db_session.get(Signal, first.id).status == "EXECUTED"
    # Exactly one Telegram message: the auto-execution fill, not a pending-fill
    # new-signal alert.
    assert len(tg.sent_messages) == 1
    alert = tg.sent_messages[0]["text"]
    assert "AUTO-EXECUTED" in alert
    assert "SL:" in alert and "Lot:" in alert

    # Second qualified signal is blocked by the single-slot cap. It must be
    # skipped rather than left behind as an ACTIVE pending fill.
    second = _seed_signal(
        test_db_session,
        "unified-auto-blocked",
        score=90.0,
        timestamp=NOW + timedelta(minutes=15),
    )
    scanner.signal_generator.scan_all_symbols = MagicMock(
        return_value=_mock_scan(second)
    )
    res2 = await scanner.run_scan_cycle(
        db=test_db_session,
        symbols=["EUR/USD"],
        timeframes=["15m"],
        broadcast_to_telegram=True,
        auto_paper_trade=True,
    )

    assert res2.paper_trades_opened_count == 0
    assert test_db_session.get(Signal, second.id).status == "EXPIRED"
    assert len(tg.sent_messages) == 1

    active = client.get("/api/v1/signals?symbol=EUR%2FUSD")
    assert active.status_code == 200
    assert active.json() == []
