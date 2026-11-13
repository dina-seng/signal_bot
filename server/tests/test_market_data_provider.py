"""Unit tests for Market Data Providers."""

from datetime import datetime, timezone
import pytest
import pandas as pd
from app.services.market_data.mock_provider import MockMarketDataProvider
from app.services.market_data.twelvedata_provider import TwelveDataProvider


@pytest.mark.asyncio
async def test_mock_provider_generation():
    """Test synthetic candle generation from MockMarketDataProvider."""
    provider = MockMarketDataProvider()
    assert provider.is_symbol_supported("XAU/USD")
    assert not provider.is_symbol_supported("US100")  # Quarantined
    assert not provider.is_symbol_supported("EUR/USD")
    assert not provider.is_symbol_supported("INVALID_SYM")

    candles = await provider.fetch_candles("XAU/USD", "15m", limit=50)
    assert len(candles) == 50
    assert candles[0].symbol == "XAU/USD"
    assert candles[0].timeframe == "15m"

    # Verify chronological ascending order
    for i in range(len(candles) - 1):
        assert candles[i].timestamp < candles[i + 1].timestamp

    # Verify pricing invariants
    for c in candles:
        assert c.high >= c.low
        assert c.high >= c.open
        assert c.high >= c.close
        assert c.low <= c.open
        assert c.low <= c.close


def test_twelve_data_mappings():
    """Test TwelveDataProvider mappings."""
    provider = TwelveDataProvider(api_key="test_key")
    assert provider.is_symbol_supported("XAU/USD")
    assert not provider.is_symbol_supported("US100")  # Quarantined
    assert not provider.is_symbol_supported("EUR/USD")
    assert provider.INTERVAL_MAP["15m"] == "15min"
    assert provider.INTERVAL_MAP["1h"] == "1h"
    assert provider.INTERVAL_MAP["4h"] == "4h"


@pytest.mark.asyncio
async def test_mock_provider_quote():
    """Test real-time quote generation from MockMarketDataProvider."""
    provider = MockMarketDataProvider(base_price=2685.50)
    quote = await provider.fetch_quote("XAU/USD")
    assert quote is not None
    assert quote.symbol == "XAU/USD"
    assert quote.price == 2500.00
    assert quote.bid < quote.price
    assert quote.ask > quote.price


def test_market_quote_api_endpoint(client):
    """Test GET /api/v1/market/quote endpoint."""
    response = client.get("/api/v1/market/quote?symbol=XAU/USD")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "XAU/USD"
    assert data["price"] > 0
    assert "timestamp" in data
