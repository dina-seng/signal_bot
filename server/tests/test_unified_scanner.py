"""Tests for Unified Multi-Timeframe Scanner, Trend Alignment, and Telegram/API consistency."""

import pytest
from datetime import datetime, timezone, timedelta
from app.models.candle import Candle
from app.models.signal import Signal
from app.schemas.signal import SignalDirection, SignalResponse
from app.services.signals import SignalGenerator
from app.services.telegram.command_handler import TelegramCommandHandler
from app.schemas.telegram import TelegramCommandRequest


def seed_candles_multi_tf(db, symbol="XAU/USD"):
    """Seed fresh closed candles across 15m, 30m, 1h, and 4h for testing."""
    base_time = datetime.now(timezone.utc) - timedelta(hours=20)
    for tf, count, delta_min in [("15m", 80, 15), ("30m", 60, 30), ("1h", 50, 60), ("4h", 30, 240)]:
        price = 2600.00
        for i in range(count):
            t = base_time + timedelta(minutes=i * delta_min)
            price += 0.50
            db.add(
                Candle(
                    symbol=symbol,
                    timeframe=tf,
                    timestamp=t,
                    open=price,
                    high=price + 1.00,
                    low=price - 0.50,
                    close=price + 0.50,
                    volume=100.0,
                )
            )
    db.commit()


def test_unified_scanner_fallback_to_1h(test_db_session):
    """Verify that when 15m/30m has no >75 score setup, scanner falls back to 1H."""
    seed_candles_multi_tf(test_db_session, "XAU/USD")
    generator = SignalGenerator()
    res = generator.scan_unified(db=test_db_session, symbol="XAU/USD", persist_qualified=False)

    assert res.symbol == "XAU/USD"
    # When no setup > 75 on 15m/30m, timeframe falls back to 1h
    assert res.timeframe == "1h"
    assert res.direction in (SignalDirection.WAIT, SignalDirection.BUY, SignalDirection.SELL)
    assert res.htf_trend in ("BULLISH", "BEARISH", "RANGING")


def test_telegram_scan_unified_output(test_db_session):
    """Verify Telegram /scan command returns UNIFIED SCANNER DIGEST with timeframes."""
    seed_candles_multi_tf(test_db_session, "XAU/USD")
    handler = TelegramCommandHandler()

    import asyncio
    resp = asyncio.run(handler.handle_command(test_db_session, TelegramCommandRequest(command="/scan")))

    assert "UNIFIED SCANNER DIGEST" in resp.reply_text
    assert "XAU/USD" in resp.reply_text
    assert "[1H]" in resp.reply_text or "[15m]" in resp.reply_text or "[30m]" in resp.reply_text


def test_api_signals_unified(client, test_db_session):
    """Verify API endpoint returns unified multi-timeframe signals when unified=True."""
    seed_candles_multi_tf(test_db_session, "XAU/USD")
    res = client.get("/api/v1/signals?unified=true")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    xau = next((s for s in data if s["symbol"] == "XAU/USD"), None)
    assert xau is not None
    assert "timeframe" in xau
    assert "htf_trend" in xau


def test_api_signals_scan_unified(client, test_db_session):
    """Verify /api/v1/signals/scan uses unified scanner by default."""
    seed_candles_multi_tf(test_db_session, "XAU/USD")
    res = client.get("/api/v1/signals/scan")
    assert res.status_code == 200
    data = res.json()
    assert "results" in data
    assert len(data["results"]) >= 1
    xau = next((r for r in data["results"] if r["symbol"] == "XAU/USD"), None)
    assert xau is not None
    assert xau["timeframe"] in ("1h", "15m", "30m")
