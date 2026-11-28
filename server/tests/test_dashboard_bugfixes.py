"""Regression tests for the dashboard snapshot bugs.

1. A mis-ordered positional call to ``get_paper_summary`` made the whole paper
   section fail, leaving the header stuck at $0.00.
2. BTC/USD candles are provider-only, so the unified scanner had no data and
   the Momentum Matrix rendered "--" / "N/A" for EMA50/EMA200/RSI14/ADX14.
"""

from app.services.market_data import MockMarketDataProvider


def test_dashboard_snapshot_includes_real_paper_summary(client):
    """The header data must arrive with the single snapshot response."""
    response = client.get(
        "/api/v1/dashboard/snapshot",
        params={"symbol": "XAU/USD", "timeframe": "15m", "account_type": "MAIN"},
    )
    assert response.status_code == 200, response.text

    snap = response.json()
    assert snap.get("paper_summary") is not None

    account = snap["paper_summary"]["account"]
    assert float(account["balance"]) > 0
    assert float(account["equity"]) > 0
    assert float(account["initial_balance"]) > 0


def test_btc_snapshot_signal_carries_momentum_metadata(monkeypatch, client):
    """BTC history is backfilled and the momentum WAIT signal is preferred."""
    # Keep the snapshot's history backfill hermetic (no live Binance call).
    monkeypatch.setattr(
        "app.services.market_data.get_provider_for_symbol",
        lambda symbol, **kwargs: MockMarketDataProvider(base_price=60000.0),
    )

    response = client.get(
        "/api/v1/dashboard/snapshot",
        params={"symbol": "BTC/USD", "timeframe": "1h", "account_type": "CENT"},
    )
    assert response.status_code == 200, response.text

    snap = response.json()
    btc = next((s for s in snap.get("signals", []) if s.get("symbol") == "BTC/USD"), None)
    assert btc is not None

    assert btc.get("strategy_name") == "BTC Momentum"
    metadata = btc.get("metadata") or {}
    for key in ("ema_50", "ema_200", "ema_trend", "rsi_14", "adx_14", "current_price"):
        assert metadata.get(key) is not None, f"Missing {key} in BTC metadata: {metadata}"
    assert float(metadata["ema_50"]) > 0
    assert float(metadata["rsi_14"]) >= 0
    assert float(metadata["adx_14"]) >= 0
