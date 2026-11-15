"""Test US100 quarantine and non-blocking Telegram webhook."""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.core.config import settings
from app.models.candle import Candle
from app.schemas.candle import CandleCreate
from app.services.market_data.twelvedata_provider import TwelveDataProvider, TwelveDataError
from app.services.market_data.mock_provider import MockMarketDataProvider
from app.services.telegram.command_handler import TelegramCommandHandler
from app.schemas.telegram import TelegramCommandRequest
from app.main import app


def test_us100_quarantine_config():
    """Verify US100 is quarantined and SUPPORTED_SYMBOLS contains only XAU/USD."""
    assert "US100" not in settings.SUPPORTED_SYMBOLS
    assert settings.SUPPORTED_SYMBOLS == ["XAU/USD"]


@pytest.mark.asyncio
async def test_twelvedata_fails_loudly_no_fallback():
    """Verify TwelveDataProvider raises error without fallback when API key is missing."""
    with patch.object(settings, "TWELVE_DATA_API_KEY", ""):
        provider = TwelveDataProvider(api_key="")
        with pytest.raises(TwelveDataError, match="TWELVE_DATA_API_KEY is not configured"):
            await provider.fetch_candles("XAU/USD", "15m", limit=10)


@pytest.mark.asyncio
async def test_scan_handler_strictly_scans_single_asset(test_db_session):
    """Verify /scan scans strictly 1 market (XAU/USD) and US100 is excluded."""
    mock_prov = MockMarketDataProvider()
    handler = TelegramCommandHandler(market_provider=mock_prov)
    req = TelegramCommandRequest(command="/scan")
    
    res = await handler.handle_command(db=test_db_session, request=req)
    assert res.handled_successfully is True
    assert "Markets Scanned" in res.reply_text and "1" in res.reply_text
    assert "US100" not in res.reply_text


def test_telegram_webhook_non_blocking_instant_ack():
    """Verify POST /api/v1/telegram/webhook returns 200 OK immediately with fast ack message."""
    client = TestClient(app)

    scan_payload = {
        "update_id": 99999,
        "message": {
            "message_id": 101,
            "chat": {"id": 1234567, "type": "private"},
            "from": {"id": 1234567, "username": "quant_trader"},
            "text": "/scan",
        },
    }

    with patch("app.services.telegram.client.TelegramClient.send_message", new_callable=AsyncMock) as mock_live, \
         patch("app.services.telegram.client.MockTelegramClient.send_message", new_callable=AsyncMock) as mock_mock:
        resp = client.post("/api/v1/telegram/webhook", json=scan_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["command"] == "/scan"
        assert "⚡ Scanning XAU/USD..." in data["reply"]
        assert mock_live.called or mock_mock.called


def test_telegram_webhook_sync_ack():
    """Verify POST /api/v1/telegram/webhook for /sync returns instant ack message."""
    client = TestClient(app)

    sync_payload = {
        "update_id": 99998,
        "message": {
            "message_id": 102,
            "chat": {"id": 1234567, "type": "private"},
            "from": {"id": 1234567, "username": "quant_trader"},
            "text": "/sync",
        },
    }

    with patch("app.services.telegram.client.TelegramClient.send_message", new_callable=AsyncMock) as mock_live, \
         patch("app.services.telegram.client.MockTelegramClient.send_message", new_callable=AsyncMock) as mock_mock:
        resp = client.post("/api/v1/telegram/webhook", json=sync_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["command"] == "/sync"
        assert "🔄 Syncing fresh market data" in data["reply"]
        assert mock_live.called or mock_mock.called
