"""Integration tests for Telegram Bot and Automated Scanner REST API endpoints."""

from datetime import datetime, timezone, timedelta
from app.models.candle import Candle


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


def test_telegram_broadcast_endpoint(client):
    """Test POST /api/v1/telegram/broadcast."""
    payload = {
        "text": "⚡ *TEST NOTIFICATION* ⚡",
        "chat_id": "test_chat_123",
        "parse_mode": "Markdown",
    }
    res = client.post("/api/v1/telegram/broadcast", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "TEST NOTIFICATION" in data["text_sent"]


def test_telegram_command_and_webhook_endpoints(client, test_db_session):
    """Test POST /api/v1/telegram/command and POST /api/v1/telegram/webhook."""
    _seed_candles(test_db_session, symbol="EUR/USD", count=40)

    # 1. Command endpoint
    cmd_payload = {"command": "/help"}
    cmd_res = client.post("/api/v1/telegram/command", json=cmd_payload)
    assert cmd_res.status_code == 200
    cmd_data = cmd_res.json()
    assert cmd_data["handled_successfully"] is True
    assert "/scan" in cmd_data["reply_text"]

    # 2. Webhook endpoint
    webhook_payload = {
        "update_id": 99901,
        "message": {
            "message_id": 1,
            "text": "/scan",
            "chat": {"id": 123456},
            "from": {"id": 123456, "username": "trader_joe"},
        },
    }
    webhook_res = client.post("/api/v1/telegram/webhook", json=webhook_payload)
    assert webhook_res.status_code == 200
    webhook_data = webhook_res.json()
    assert webhook_data["status"] == "success"
    assert webhook_data["command"] == "/scan"


def test_telegram_status_endpoint(client):
    """Test GET /api/v1/telegram/status."""
    res = client.get("/api/v1/telegram/status")
    assert res.status_code == 200
    data = res.json()
    assert "is_configured" in data
    assert "mode" in data


def test_scanner_trigger_and_status_endpoints(client, test_db_session):
    """Test POST /api/v1/telegram/scanner/trigger and GET /api/v1/telegram/scanner/status."""
    _seed_candles(test_db_session, symbol="EUR/USD", count=40)

    # 1. Trigger Scanner
    trigger_res = client.post("/api/v1/telegram/scanner/trigger?timeframe=1h&broadcast=true&auto_trade=true")
    assert trigger_res.status_code == 200
    trigger_data = trigger_res.json()
    assert "symbols_scanned" in trigger_data
    assert "execution_time_seconds" in trigger_data

    # 2. Scanner Status
    status_res = client.get("/api/v1/telegram/scanner/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert "is_enabled" in status_data
    assert status_data["total_scans_completed"] >= 1
