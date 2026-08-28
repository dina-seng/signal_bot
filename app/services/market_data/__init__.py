"""Market data module containing providers and ingestion engine."""

from app.services.market_data.base import BaseMarketDataProvider
from app.services.market_data.yfinance_provider import YahooFinanceProvider
from app.services.market_data.twelvedata_provider import TwelveDataProvider
from app.services.market_data.mock_provider import MockMarketDataProvider
from app.services.market_data.ingestion import IngestionService


def get_market_data_provider(provider_name: str = "yfinance") -> BaseMarketDataProvider:
    """Factory to retrieve configured market data provider instance."""
    name = provider_name.lower().strip()
    if name == "yfinance" or name == "yahoo":
        return YahooFinanceProvider()
    elif name == "twelvedata":
        return TwelveDataProvider()
    elif name == "mock":
        return MockMarketDataProvider()
    else:
        # Default fallback
        return YahooFinanceProvider()


__all__ = [
    "BaseMarketDataProvider",
    "YahooFinanceProvider",
    "TwelveDataProvider",
    "MockMarketDataProvider",
    "IngestionService",
    "get_market_data_provider",
]
