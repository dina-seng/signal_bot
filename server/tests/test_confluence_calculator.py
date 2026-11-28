"""Regression tests for the structured calculator shared by API and Telegram."""

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.models.candle import Candle
from app.services.indicators.confluence_calculator import (
    calculate_technical_confluence,
)
from app.services.telegram.message_formatter import TelegramMessageFormatter


def _candles(count: int = 210, trend: float = 1.0):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(count):
        base = 2000.0 + i * 0.5 * trend
        wave = (i % 5) * 0.4
        o = base + wave
        c = base + wave + 0.2
        rows.append({
            "timestamp": start + timedelta(hours=i),
            "open": o,
            "high": max(o, c) + 1.0,
            "low": min(o, c) - 1.0,
            "close": c,
            "volume": 1000.0,
        })
    return rows


def test_calculator_returns_structured_numeric_payload():
    data = calculate_technical_confluence(_candles(), symbol="XAU/USD", timeframe="1h")

    for key in ("symbol", "timeframe", "score", "ema_20", "ema_50", "ema_200",
                "rsi", "adx", "trend", "sub_scores", "confidence"):
        assert key in data
    assert data["history_sufficient"] is True
    assert isinstance(data["score"], float)
    assert 0.0 <= data["score"] <= 100.0
    for key in ("ema_20", "ema_50", "ema_200", "rsi", "adx"):
        assert data[key] is not None, f"{key} must be numeric"
        assert not math.isnan(data[key])
    assert data["trend"] in ("BULLISH_STACK", "BEARISH_STACK",
                             "BULLISH_BIAS", "BEARISH_BIAS", "NEUTRAL")
    assert 60 <= data["confidence"] <= 95


def test_calculator_handles_short_history_without_nan():
    data = calculate_technical_confluence(_candles(10), symbol="XAU/USD")
    assert data["score"] == 0.0
    assert data["rsi"] is None and data["adx"] is None
    assert data["note"]


def test_telegram_formatter_is_safe_with_missing_values():
    message = TelegramMessageFormatter.format_technical_analysis({
        "symbol": "XAU/USD", "timeframe": "1h", "price": 2030.5,
        "score": 75.0, "ema_20": None, "ema_50": None,
        "rsi": None, "adx": None, "trend": "NEUTRAL",
    })
    assert "QuantView Signal: XAU/USD" in message
    assert "75/100" in message
    assert "N/A" in message
    assert "nan" not in message.lower()
    assert "None" not in message
    assert "<b>" in message  # HTML parse_mode compatible


def test_telegram_formatter_with_full_payload():
    payload = calculate_technical_confluence(_candles(), symbol="XAU/USD")
    message = TelegramMessageFormatter.format_technical_analysis(payload)
    assert "Confluence Score" in message
    assert "RSI (14)" in message
    assert "ADX (14)" in message
    assert "AI Thesis" in message
    assert "nan" not in message.lower()


def test_confluence_endpoint_returns_payload(client, test_db_session):
    for row in _candles():
        test_db_session.add(Candle(
            symbol="XAU/USD", timeframe="1h", **row
        ))
    test_db_session.commit()

    response = client.get(
        "/api/v1/indicators/XAU/USD/confluence",
        params={"symbol": "XAU/USD", "timeframe": "1h"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert 0.0 <= data["score"] <= 100.0
    assert data["ema_20"] is not None
    assert data["rsi"] is not None
    assert data["adx"] is not None


@pytest.mark.asyncio
async def test_signal_command_includes_shared_analysis(test_db_session):
    """`python-telegram-bot` handler output must contain EMA/RSI/ADX + score."""
    from app.schemas.telegram import TelegramCommandRequest
    from app.services.market_data.mock_provider import MockMarketDataProvider
    from app.services.telegram.command_handler import TelegramCommandHandler
    from app.services.telegram.client import MockTelegramClient

    handler = TelegramCommandHandler(
        market_provider=MockMarketDataProvider(),
        telegram_client=MockTelegramClient(),
    )
    response = await handler.handle_command(
        test_db_session, TelegramCommandRequest(command="/signal XAU/USD")
    )

    assert response.handled_successfully is True
    text = response.reply_text
    assert "QuantView Signal" in text
    assert "Confluence Score" in text
    assert "RSI (14)" in text
    assert "ADX (14)" in text
    assert "AI Thesis" in text
    assert "nan" not in text.lower()
