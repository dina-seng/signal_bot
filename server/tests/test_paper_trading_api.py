"""Integration tests for Paper Trading REST API endpoints."""

from datetime import datetime, timezone
from app.models.candle import Candle
from app.models.signal import Signal


def _seed_candle(db, symbol="EUR/USD", close=1.1000):
    """Seed candle for test database."""
    c = Candle(
        symbol=symbol,
        timeframe="1h",
        timestamp=datetime.now(timezone.utc),
        open=close,
        high=close + 0.0010,
        low=close - 0.0010,
        close=close,
        volume=100.0,
    )
    db.add(c)
    db.commit()


def test_paper_account_api_endpoints(client, test_db_session):
    """Test GET /paper/account, POST /paper/account/deposit, and POST /paper/account/reset."""
    # 1. Get Account
    res = client.get("/api/v1/paper/account")
    assert res.status_code == 200
    data = res.json()
    assert data["balance"] == 10000.0
    assert data["equity"] == 10000.0
    assert data["free_margin"] == 10000.0

    # 2. Deposit
    dep_res = client.post("/api/v1/paper/account/deposit", json={"amount": 2500.0, "description": "Bonus"})
    assert dep_res.status_code == 200
    dep_data = dep_res.json()
    assert dep_data["balance"] == 12500.0
    assert dep_data["equity"] == 12500.0

    # 3. Reset
    reset_res = client.post("/api/v1/paper/account/reset", json={"initial_balance": 10000.0})
    assert reset_res.status_code == 200
    reset_data = reset_res.json()
    assert reset_data["balance"] == 10000.0


def test_paper_orders_and_position_management_endpoints(client, test_db_session):
    """Test placing orders, querying positions, modifying SL/TP, and closing positions."""
    _seed_candle(test_db_session, symbol="EUR/USD", close=1.1000)

    # 1. Place Market Order
    order_payload = {
        "symbol": "EUR/USD",
        "direction": "BUY",
        "order_type": "MARKET",
        "position_size": 1.0,
        "stop_loss": 1.0950,
        "take_profit_1": 1.1050,
        "take_profit_2": 1.1100,
    }
    order_res = client.post("/api/v1/paper/orders", json=order_payload)
    assert order_res.status_code == 200
    trade_data = order_res.json()
    trade_id = trade_data["id"]
    assert trade_data["status"] == "OPEN"
    assert trade_data["initial_position_size"] == 1.0

    # 2. Query Positions
    pos_res = client.get("/api/v1/paper/positions")
    assert pos_res.status_code == 200
    positions = pos_res.json()
    assert len(positions) >= 1
    assert any(p["id"] == trade_id for p in positions)

    # 3. Modify Position SL/TP
    mod_res = client.put(f"/api/v1/paper/positions/{trade_id}/modify", json={"stop_loss": 1.0970})
    assert mod_res.status_code == 200
    mod_data = mod_res.json()
    assert mod_data["stop_loss"] == 1.0970

    # 4. Trigger Price Sync
    sync_res = client.post("/api/v1/paper/monitor/sync", json={"EUR/USD": 1.1020})
    assert sync_res.status_code == 200
    sync_data = sync_res.json()
    assert sync_data["updated_positions_count"] >= 1

    # 5. Close Position
    close_res = client.post(f"/api/v1/paper/positions/{trade_id}/close", json={"close_ratio": 1.0, "exit_reason": "MANUAL"})
    assert close_res.status_code == 200
    close_data = close_res.json()
    assert close_data["status"] == "CLOSED"

    # 6. Query Trade History
    hist_res = client.get("/api/v1/paper/trades")
    assert hist_res.status_code == 200
    hist = hist_res.json()
    assert len(hist) >= 1

    # 7. Portfolio Performance
    perf_res = client.get("/api/v1/paper/performance")
    assert perf_res.status_code == 200
    perf_data = perf_res.json()
    assert "win_rate" in perf_data
    assert "profit_factor" in perf_data


def test_paper_summary_is_atomic(client, test_db_session):
    """Account equity and open-position P&L are derived from one shared tick."""
    _seed_candle(test_db_session, symbol="XAU/USD", close=3592.79)
    order_res = client.post("/api/v1/paper/orders", json={
        "symbol": "XAU/USD",
        "direction": "BUY",
        "order_type": "MARKET",
        "position_size": 0.01,
        "stop_loss": 3515.43,
        "take_profit_1": 3633.89,
    })
    assert order_res.status_code == 200

    res = client.get("/api/v1/paper/summary")
    assert res.status_code == 200
    data = res.json()
    account = data["account"]
    positions = data["positions"]

    assert len(positions) == 1
    assert data["tick_price"] is not None
    assert data["tick_source"] in ("quote", "candle")
    assert all(p["price_source"] == data["tick_source"] for p in positions)
    floating = round(sum(p["unrealized_pnl"] for p in positions), 2)
    assert account["equity"] == round(account["balance"] + floating, 2)
    assert account["floating_pnl"] == floating
