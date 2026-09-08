"""Unit tests for Market Data Providers."""

from datetime import datetime, timezone
import pytest
import pandas as pd
from app.services.market_data.mock_provider import MockMarketDataProvider
from app.services.market_data.yfinance_provider import YahooFinanceProvider
from app.services.market_data.twelvedata_provider import TwelveDataProvider


@pytest.mark.asyncio
async def test_mock_provider_generation():
    """Test synthetic candle generation from MockMarketDataProvider."""
    provider = MockMarketDataProvider()
    assert provider.is_symbol_supported("EUR/USD")
    assert provider.is_symbol_supported("XAU/USD")
    assert not provider.is_symbol_supported("INVALID_SYM")

    candles = await provider.fetch_candles("EUR/USD", "15m", limit=50)
    assert len(candles) == 50
    assert candles[0].symbol == "EUR/USD"
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


def test_yfinance_provider_mappings():
    """Test symbol and timeframe conversions in YahooFinanceProvider."""
    provider = YahooFinanceProvider()

    assert provider._get_ticker("EUR/USD") == "EURUSD=X"
    assert provider._get_ticker("GBP/USD") == "GBPUSD=X"
    assert provider._get_ticker("USD/JPY") == "JPY=X"
    assert provider._get_ticker("XAU/USD") == "GC=F"
    assert provider._get_ticker("USDCHF") == "USDCHF=X"

    assert provider._normalize_timeframe("15M") == "15m"
    assert provider._normalize_timeframe("1H") == "1h"
    assert provider._normalize_timeframe("4H") == "4h"

    with pytest.raises(ValueError):
        provider._normalize_timeframe("invalid_tf")


def test_yfinance_df_parsing():
    """Test parsing a mock pandas DataFrame from Yahoo Finance."""
    provider = YahooFinanceProvider()
    data = {
        "Open": [1.0800, 1.0820],
        "High": [1.0850, 1.0860],
        "Low": [1.0790, 1.0810],
        "Close": [1.0830, 1.0840],
        "Volume": [100.0, 150.0],
    }
    index = pd.to_datetime(["2026-08-28 10:00:00+00:00", "2026-08-28 10:15:00+00:00"])
    df = pd.DataFrame(data, index=index)

    candles = provider._parse_df_to_candles(df, "EUR/USD", "15m", limit=10)
    assert len(candles) == 2
    assert candles[0].symbol == "EUR/USD"
    assert candles[0].open == 1.0800
    assert candles[0].close == 1.0830
    assert candles[1].open == 1.0820


def test_twelve_data_mappings():
    """Test TwelveDataProvider mappings."""
    provider = TwelveDataProvider(api_key="test_key")
    assert provider.is_symbol_supported("EUR/USD")
    assert provider.INTERVAL_MAP["15m"] == "15min"
    assert provider.INTERVAL_MAP["1h"] == "1h"
    assert provider.INTERVAL_MAP["4h"] == "4h"
