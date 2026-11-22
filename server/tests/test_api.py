"""Integration tests for FastAPI endpoints."""

def test_health_endpoint(client):
    """Test health check endpoint."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    # Hermetic in-memory test DB has no candles, so health legitimately reports
    # "degraded" (STALE freshness). Both statuses prove the endpoint responds.
    assert data["status"] in {"healthy", "degraded"}
    assert data["database_connected"] is True
    assert "XAU/USD" in data["supported_symbols"]
    assert "US100" not in data["supported_symbols"]  # Quarantined
    assert "EUR/USD" not in data["supported_symbols"]


def test_symbols_endpoint(client):
    """Test market symbols listing endpoint."""
    response = client.get("/api/v1/market/symbols")
    assert response.status_code == 200
    symbols = response.json()
    assert len(symbols) == 1
    symbols_names = [s["symbol"] for s in symbols]
    assert "XAU/USD" in symbols_names
    assert "US100" not in symbols_names  # Quarantined
    assert "EUR/USD" not in symbols_names


def test_sync_and_query_candles_endpoint(client):
    """Test syncing data via API and querying the ingested candles."""
    # 1. Sync XAU/USD 15m
    sync_resp = client.post(
        "/api/v1/market/sync",
        json={"symbol": "XAU/USD", "timeframe": "15m", "limit": 20},
    )
    assert sync_resp.status_code == 200
    reports = sync_resp.json()
    assert len(reports) == 1
    assert reports[0]["symbol"] == "XAU/USD"
    assert reports[0]["timeframe"] == "15m"
    assert reports[0]["inserted_count"] == 20

    # 2. Query stored candles
    candles_resp = client.get(
        "/api/v1/market/XAU/USD/candles?timeframe=15m&limit=10"
    )
    assert candles_resp.status_code == 200
    candles = candles_resp.json()
    assert len(candles) == 10
    assert candles[0]["symbol"] == "XAU/USD"
    assert candles[0]["timeframe"] == "15m"
    assert "open" in candles[0]
    assert "high" in candles[0]
    assert "low" in candles[0]
    assert "close" in candles[0]
