"""API integration tests for Liquidity, Sweeps, BOS/CHOCH, and S/R Zone endpoints."""

from datetime import datetime, timedelta, timezone
import pytest
from app.models.candle import Candle


def seed_test_candles(db, symbol="EUR/USD", timeframe="1h", count=28):
    """Seed test candles in DB forming an upward trending staircase with clear swings."""
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    base_price = 1.1000
    candles = []

    for i in range(count):
        step = i // 4
        cycle = i % 4
        if cycle == 0:
            h = base_price + (step * 0.0050) + 0.0015
            l = base_price + (step * 0.0050) - 0.0005
            o = base_price + (step * 0.0050)
            c = base_price + (step * 0.0050) + 0.0010
        elif cycle == 1:
            h = base_price + (step * 0.0050) + 0.0040
            l = base_price + (step * 0.0050) + 0.0010
            o = base_price + (step * 0.0050) + 0.0012
            c = base_price + (step * 0.0050) + 0.0035
        elif cycle == 2:
            h = base_price + (step * 0.0050) + 0.0015
            l = base_price + (step * 0.0050) - 0.0010
            o = base_price + (step * 0.0050) + 0.0010
            c = base_price + (step * 0.0050) - 0.0005
        else:
            h = base_price + (step * 0.0050) + 0.0025
            l = base_price + (step * 0.0050) + 0.0005
            o = base_price + (step * 0.0050) + 0.0006
            c = base_price + (step * 0.0050) + 0.0020

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


def test_get_liquidity_analysis_not_found(client):
    """Test 404 response when querying liquidity for symbol with no data."""
    response = client.get("/api/v1/liquidity/GBP/USD/analysis?timeframe=1h")
    assert response.status_code == 404
    assert "No candles found" in response.json()["detail"]


def test_get_liquidity_analysis_success(client, test_db_session):
    """Test full liquidity & SMC structure analysis endpoint."""
    seed_test_candles(test_db_session, symbol="EUR/USD", timeframe="1h", count=28)

    response = client.get("/api/v1/liquidity/EUR/USD/analysis?timeframe=1h&lookback=1&persist=true")
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "EUR/USD"
    assert data["timeframe"] == "1h"
    assert "market_state" in data
    assert "bos_events" in data
    assert "choch_events" in data
    assert "liquidity_sweeps" in data
    assert "sr_zones" in data
    assert "base_structure" in data


def test_get_liquidity_sweeps(client, test_db_session):
    """Test liquidity sweeps endpoint."""
    seed_test_candles(test_db_session, symbol="EUR/USD", timeframe="1h", count=28)

    response = client.get("/api/v1/liquidity/EUR/USD/sweeps?timeframe=1h&lookback=1")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_get_sr_zones_and_pools(client, test_db_session):
    """Test S/R zones and liquidity pools endpoint."""
    seed_test_candles(test_db_session, symbol="EUR/USD", timeframe="1h", count=28)

    response = client.get("/api/v1/liquidity/EUR/USD/zones?timeframe=1h&lookback=1")
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "EUR/USD"
    assert "sr_zones" in data
    assert "liquidity_pools" in data


def test_post_stateless_liquidity_analyze(client):
    """Test on-demand stateless liquidity analysis endpoint."""
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
    ]
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
        "lookback": 1,
        "tolerance_percent": 0.1,
        "candles": candles_payload,
    }

    response = client.post("/api/v1/liquidity/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "EUR/USD"
    assert data["trend"] == "BULLISH"
    assert len(data["bos_events"]) >= 1
