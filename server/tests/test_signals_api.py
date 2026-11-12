"""API integration tests for Signal Generation and Market Scanner endpoints."""

from datetime import datetime, timedelta, timezone
import pytest
from app.models.candle import Candle
from app.models.signal import Signal


def seed_candles(db, symbol="EUR/USD", count=50):
    """Seed candle staircase for signal tests."""
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    base_price = 1.1000
    candles = []
    for i in range(count):
        t = base_time + timedelta(hours=i)
        p = base_price + (i * 0.0005)
        candles.append(
            Candle(
                symbol=symbol,
                timeframe="1h",
                timestamp=t,
                open=p,
                high=p + 0.0010,
                low=p - 0.0005,
                close=p + 0.0008,
                volume=1000.0,
            )
        )
    db.add_all(candles)
    db.commit()


def test_get_signals_empty_and_populated(client, test_db_session):
    """Test GET /api/v1/signals endpoint."""
    res_empty = client.get("/api/v1/signals")
    assert res_empty.status_code == 200
    assert res_empty.json() == []

    # Insert mock signal
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    sig = Signal(
        symbol="EUR/USD",
        timeframe="1h",
        direction="BUY",
        setup_score=85.0,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=1.1100,
        take_profit_2=1.1150,
        risk_reward=2.0,
        fingerprint="test_fingerprint_hash_123",
        reasons=["Bullish trend", "Liquidity sweep"],
        status="ACTIVE",
        timestamp=now,
    )
    test_db_session.add(sig)
    test_db_session.commit()

    res_pop = client.get("/api/v1/signals?symbol=EUR/USD")
    assert res_pop.status_code == 200
    data = res_pop.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "EUR/USD"
    assert data[0]["direction"] == "BUY"
    assert data[0]["setup_score"] == 85.0


def test_scan_markets_endpoint(client, test_db_session):
    """Test GET /api/v1/signals/scan endpoint."""
    seed_candles(test_db_session, symbol="XAU/USD", count=50)

    response = client.get("/api/v1/signals/scan?timeframe=1h&account_balance=10000&risk_percent=0.5")
    assert response.status_code == 200
    data = response.json()

    assert "scanned_count" in data
    assert "results" in data
    assert len(data["results"]) == 2  # Strictly restricted to XAU/USD and US100


def test_post_evaluate_stateless_signal(client):
    """Test POST /api/v1/signals/evaluate endpoint with synthetic candles."""
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles_payload = []
    base_p = 1.1000

    for i in range(30):
        t = (base_time + timedelta(hours=i)).isoformat()
        p = base_p + (i * 0.0010)
        candles_payload.append(
            {
                "symbol": "EUR/USD",
                "timeframe": "1h",
                "timestamp": t,
                "open": p,
                "high": p + 0.0015,
                "low": p - 0.0005,
                "close": p + 0.0010,
                "volume": 500.0,
            }
        )

    payload = {
        "symbol": "EUR/USD",
        "timeframe": "1h",
        "account_balance": 10000.0,
        "risk_percent": 0.5,
        "candles": candles_payload,
    }

    response = client.post("/api/v1/signals/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "EUR/USD"
    assert "direction" in data
    assert "setup_score" in data
    assert "score_breakdown" in data
