"""Market data module containing providers and ingestion engine."""

from app.core.config import settings  # ✅ ADDED IMPORT
from app.core.logging import logger   # ✅ ADDED IMPORT

from app.services.market_data.base import BaseMarketDataProvider
from app.services.market_data.yfinance_provider import YahooFinanceProvider
from app.services.market_data.twelvedata_provider import TwelveDataProvider
from app.services.market_data.mock_provider import MockMarketDataProvider
from app.services.market_data.ingestion import IngestionService

from app.services.market_data.freshness import (
    DEFAULT_STALENESS_THRESHOLDS,
    TIMEFRAME_DELTAS,
    StalenessCheckResult,
    check_data_staleness,
    ensure_utc_datetime,
    filter_closed_candles,
    format_candle_log_line,
    get_latest_closed_candle,
    get_timeframe_delta,
    is_candle_closed,
    is_forex_weekend,
    log_latest_candle,
)


def get_market_data_provider(provider_name: str = "yfinance") -> BaseMarketDataProvider:
    """Factory to retrieve configured market data provider instance."""
    name = provider_name.lower().strip()
    
    if name == "yfinance" or name == "yahoo":
        return YahooFinanceProvider()
        
    elif name == "twelvedata":
        api_key = getattr(settings, "TWELVEDATA_API_KEY", None)
        if not api_key:
            logger.warning("TWELVEDATA_API_KEY is missing in environment variables. Falling back to YFinance.")
            return YahooFinanceProvider()
        return TwelveDataProvider(api_key=api_key)
        
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
    "DEFAULT_STALENESS_THRESHOLDS",
    "TIMEFRAME_DELTAS",
    "StalenessCheckResult",
    "check_data_staleness",
    "ensure_utc_datetime",
    "filter_closed_candles",
    "format_candle_log_line",
    "get_latest_closed_candle",
    "get_timeframe_delta",
    "is_candle_closed",
    "is_forex_weekend",
    "log_latest_candle",
]