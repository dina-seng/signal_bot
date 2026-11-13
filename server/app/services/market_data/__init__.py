"""Market data module containing providers and ingestion engine."""

from app.core.config import settings
from app.core.logging import logger

from app.services.market_data.base import BaseMarketDataProvider
from app.services.market_data.twelvedata_provider import TwelveDataProvider
from app.services.market_data.yfinance_provider import YahooFinanceProvider
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


def get_market_data_provider(provider_name: str = "twelvedata") -> BaseMarketDataProvider:
    """Factory to retrieve configured market data provider instance."""
    name = (provider_name or "twelvedata").lower().strip()
    
    if name in ("twelvedata", "twelve", "twelve_data"):
        api_key = getattr(settings, "TWELVE_DATA_API_KEY", None) or getattr(settings, "TWELVEDATA_API_KEY", None)
        # Even if api_key is None, TwelveDataProvider automatically falls back to YahooFinanceProvider
        return TwelveDataProvider(api_key=api_key) 
        
    elif name in ("yfinance", "yahoo", "yahoofinance"):
        return YahooFinanceProvider()

    elif name == "mock":
        return MockMarketDataProvider()
        
    else:
        # Safe default fallback
        logger.warning(f"Provider '{name}' not found or unavailable. Falling back to TwelveDataProvider with Yahoo fallback.")
        return TwelveDataProvider(api_key=getattr(settings, "TWELVE_DATA_API_KEY", None))


__all__ = [
    "BaseMarketDataProvider",
    "TwelveDataProvider",
    "YahooFinanceProvider",
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
