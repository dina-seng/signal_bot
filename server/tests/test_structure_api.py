"""API integration tests for Market Structure endpoints."""

from datetime import datetime, timedelta, timezone
import pytest
from app.models.candle import Candle
from app.models.structure import StructureEvent


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
        elif cycle == 1:  # Peak (Swing High)
            h = base_price + (step * 0.0050) + 0.0040
            l = base_price + (step * 0.0050) + 0.0010
            o = base_price + (step * 0.0050) + 0.0012
            c = base_price + (step * 0.0050) + 0.0035
        elif cycle == 2:  # Trough (Swing Low)
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


def test_get_symbol_structure_not_found(client):
    """Test 404 response when querying structure for a symbol with no stored candles."""
    response = client.get("/api/v1/structure/GBP/USD?timeframe=1h")
    assert response.status_code == 404
    assert "No candles found" in response.json()["detail"]


def test_get_symbol_structure_success(client, test_db_session):
    """Test successful market structure retrieval and analysis from DB."""
    seed_test_candles(test_db_session, symbol="EUR/USD", timeframe="1h", count=28)

    response = client.get("/api/v1/structure/EUR/USD?timeframe=1h&lookback=1&persist=true")
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "EUR/USD"
    assert data["timeframe"] == "1h"
    assert data["trend"] in ("BULLISH", "BEARISH", "RANGING")
    assert data["total_swings"] > 0
    assert len(data["swing_points"]) > 0
    assert data["last_swing_high"] is not None
    assert data["last_swing_low"] is not None

    # Check persistence was executed
    events = test_db_session.query(StructureEvent).filter_by(symbol="EUR/USD", timeframe="1h").all()
    assert len(events) > 0


def test_get_multi_timeframe_structure(client, test_db_session):
    """Test multi-timeframe structure endpoint."""
    seed_test_candles(test_db_session, symbol="EUR/USD", timeframe="4h", count=20)
    seed_test_candles(test_db_session, symbol="EUR/USD", timeframe="1h", count=20)
    seed_test_candles(test_db_session, symbol="EUR/USD", timeframe="15m", count=20)

    response = client.get("/api/v1/structure/EUR/USD/multi-timeframe?timeframes=15m,1h,4h&lookback=1")
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "EUR/USD"
    assert "15m" in data["timeframes"]
    assert "1h" in data["timeframes"]
    assert "4h" in data["timeframes"]
    assert data["alignment"] in (
        "BULLISH_ALIGNED",
        "BEARISH_ALIGNED",
        "HTF_BULLISH_PULLBACK",
        "HTF_BEARISH_PULLBACK",
        "MIXED",
    )
    assert 0.0 <= data["alignment_score"] <= 1.0
    assert len(data["summary"]) > 0


def test_post_stateless_analyze_structure(client):
    """Test on-demand stateless structure analysis via POST."""
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles_payload = []
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
        "tolerance_percent": 0.05,
        "candles": candles_payload,
    }

    response = client.post("/api/v1/structure/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "EUR/USD"
    assert data["trend"] == "BULLISH"
    assert data["total_swings"] >= 4
    assert data["higher_highs_count"] == 2
    assert data["higher_lows_count"] == 2


def test_post_stateless_analyze_empty_error(client):
    """Test 400 validation error when empty candles provided to /api/v1/structure/analyze."""
    payload = {
        "symbol": "EUR/USD",
        "timeframe": "1h",
        "candles": [],
    }
    response = client.post("/api/v1/structure/analyze", json=payload)
    assert response.status_code == 400
