"""Integration tests for Backtesting and Optimization REST API endpoints."""

from datetime import datetime, timedelta, timezone
from app.models.candle import Candle


def _seed_candles(db, symbol="EUR/USD", timeframe="1h", count=60):
    """Seed test database with candles."""
    now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    for i in range(count):
        ts = now + timedelta(hours=i)
        o = 1.1000 + (i * 0.0005)
        c = Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=ts,
            open=round(o, 5),
            high=round(o + 0.0015, 5),
            low=round(o - 0.0010, 5),
            close=round(o + 0.0008, 5),
            volume=1000.0,
        )
        db.add(c)
    db.commit()


def test_stateless_backtest_endpoint(client):
    """Test POST /api/v1/backtest/execute with custom candles."""
    now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles = [
        {
            "symbol": "EUR/USD",
            "timeframe": "1h",
            "timestamp": (now + timedelta(hours=i)).isoformat(),
            "open": 1.1000 + (i * 0.0005),
            "high": 1.1015 + (i * 0.0005),
            "low": 1.0990 + (i * 0.0005),
            "close": 1.1008 + (i * 0.0005),
            "volume": 500.0,
        }
        for i in range(40)
    ]

    payload = {
        "candles": candles,
        "symbol": "EUR/USD",
        "timeframe": "1h",
        "config": {
            "initial_balance": 10000.0,
            "risk_percent": 0.5,
            "min_score_threshold": 50.0,
            "warmup_bars": 10,
        },
    }

    res = client.post("/api/v1/backtest/execute", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "EUR/USD"
    assert data["timeframe"] == "1h"
    assert "metrics" in data
    assert "equity_curve" in data
    assert data["metrics"]["initial_balance"] == 10000.0


def test_database_backtest_and_crud_endpoints(client, test_db_session):
    """Test POST /api/v1/backtest/run, GET /api/v1/backtest/runs, GET /runs/{id}, and DELETE /runs/{id}."""
    _seed_candles(test_db_session, symbol="EUR/USD", timeframe="1h", count=50)

    # 1. Run backtest and persist
    run_payload = {
        "symbol": "EUR/USD",
        "timeframe": "1h",
        "name": "EUR/USD Test Run",
        "config": {
            "initial_balance": 10000.0,
            "risk_percent": 0.5,
            "min_score_threshold": 50.0,
            "warmup_bars": 15,
        },
        "save_run": True,
    }

    res = client.post("/api/v1/backtest/run", json=run_payload)
    assert res.status_code == 200
    run_data = res.json()
    run_id = run_data["run_id"]
    assert run_id is not None
    assert run_data["name"] == "EUR/USD Test Run"
    assert "metrics" in run_data

    # 2. List runs
    list_res = client.get("/api/v1/backtest/runs?symbol=EUR/USD")
    assert list_res.status_code == 200
    runs = list_res.json()
    assert len(runs) >= 1
    assert any(r["id"] == run_id for r in runs)

    # 3. Get run details
    detail_res = client.get(f"/api/v1/backtest/runs/{run_id}")
    assert detail_res.status_code == 200
    details = detail_res.json()
    assert details["run_id"] == run_id
    assert "trades" in details

    # 4. Delete run
    del_res = client.delete(f"/api/v1/backtest/runs/{run_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "success"

    # 5. Confirm deletion
    not_found_res = client.get(f"/api/v1/backtest/runs/{run_id}")
    assert not_found_res.status_code == 404


def test_parameter_optimization_endpoint(client, test_db_session):
    """Test POST /api/v1/backtest/optimize."""
    _seed_candles(test_db_session, symbol="GBP/USD", timeframe="1h", count=50)

    payload = {
        "symbol": "GBP/USD",
        "timeframe": "1h",
        "score_thresholds": [60.0, 75.0],
        "risk_percentages": [0.5],
        "rr_targets": [2.0],
    }

    res = client.post("/api/v1/backtest/optimize", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "GBP/USD"
    assert data["tested_combinations"] == 2
    assert len(data["results"]) == 2
