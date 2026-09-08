"""API integration tests for Technical Indicators and Price Action endpoints."""

from datetime import datetime, timedelta, timezone
import pytest
from app.models.candle import Candle


def seed_test_candles(db, symbol="EUR/USD", timeframe="1h", count=60):
    """Seed test candles in DB forming an upward trending staircase with volatility."""
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    base_price = 1.1000
    candles = []

    for i in range(count):
        step = i // 4
        cycle = i % 4
        if cycle == 0:
            h = base_price + (step * 0.0030) + 0.0015
            l = base_price + (step * 0.0030) - 0.0005
            o = base_price + (step * 0.0030)
            c = base_price + (step * 0.0030) + 0.0010
        elif cycle == 1:
            h = base_price + (step * 0.0030) + 0.0040
            l = base_price + (step * 0.0030) + 0.0010
            o = base_price + (step * 0.0030) + 0.0012
            c = base_price + (step * 0.0030) + 0.0035
        elif cycle == 2:
            h = base_price + (step * 0.0030) + 0.0015
            l = base_price + (step * 0.0030) - 0.0010
            o = base_price + (step * 0.0030) + 0.0010
            c = base_price + (step * 0.0030) - 0.0005
        else:
            h = base_price + (step * 0.0030) + 0.0025
            l = base_price + (step * 0.0030) + 0.0005
            o = base_price + (step * 0.0030) + 0.0006
            c = base_price + (step * 0.0030) + 0.0020

        t = base_time + timedelta(hours=i)

        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=t,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=500.0,
            )
        )

    db.add_all(candles)
    db.commit()


def test_get_indicators_not_found(client):
    """Test 404 response when querying indicators for symbol with no data."""
    response = client.get("/api/v1/indicators/GBP/USD?timeframe=1h")
    assert response.status_code == 404
    assert "No candles found" in response.json()["detail"]


def test_get_indicators_success(client, test_db_session):
    """Test successful indicator analysis retrieval from DB."""
    seed_test_candles(test_db_session, symbol="EUR/USD", timeframe="1h", count=60)

    response = client.get("/api/v1/indicators/EUR/USD?timeframe=1h&ema_fast=10&ema_mid=20&ema_slow=50")
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "EUR/USD"
    assert data["timeframe"] == "1h"
    assert "ema" in data
    assert "rsi" in data
    assert "atr" in data
    assert "confluence_bias" in data
    assert -100.0 <= data["confluence_score"] <= 100.0


def test_get_fair_value_gaps(client, test_db_session):
    """Test FVG endpoint."""
    seed_test_candles(test_db_session, symbol="EUR/USD", timeframe="1h", count=60)

    response = client.get("/api/v1/indicators/EUR/USD/fvg?timeframe=1h")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_get_rsi_divergences(client, test_db_session):
    """Test RSI divergences endpoint."""
    seed_test_candles(test_db_session, symbol="EUR/USD", timeframe="1h", count=60)

    response = client.get("/api/v1/indicators/EUR/USD/divergences?timeframe=1h")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_post_stateless_indicators_analyze(client):
    """Test on-demand stateless indicator calculation endpoint."""
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    prices = [
        (1.00, 1.04, 0.98, 1.02),
        (1.02, 1.15, 1.01, 1.10),
        (1.05, 1.08, 0.95, 0.97),
        (1.06, 1.25, 1.06, 1.22),
        (1.18, 1.20, 1.05, 1.08),
        (1.18, 1.35, 1.18, 1.32),
        (1.25, 1.28, 1.12, 1.16),
        (1.20, 1.45, 1.20, 1.42),
    ] * 5  # 40 candles
    candles_payload = []
    for i, (o, h, l, c) in enumerate(prices):
        t = (base_time + timedelta(hours=i)).isoformat()
        candles_payload.append(
            {
                "symbol": "EUR/USD",
                "timeframe": "1h",
                "timestamp": t,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": 100.0,
            }
        )

    payload = {
        "symbol": "EUR/USD",
        "timeframe": "1h",
        "ema_fast": 10,
        "ema_mid": 20,
        "ema_slow": 30,
        "rsi_period": 14,
        "atr_period": 14,
        "candles": candles_payload,
    }

    response = client.post("/api/v1/indicators/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "EUR/USD"
    assert data["rsi"]["rsi_value"] is not None
    assert data["atr"]["atr_pips"] is not None
