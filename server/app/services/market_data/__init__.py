"""Market data module containing Twelve Data provider and ingestion engine."""

from typing import Optional
import httpx
from app.core.config import settings
from app.core.logging import logger

from app.services.market_data.base import BaseMarketDataProvider
from app.services.market_data.twelvedata_provider import TwelveDataProvider
from app.services.market_data.mock_provider import MockMarketDataProvider
from app.services.market_data.ingestion import IngestionService
from app.services.market_data.resample import resample_ohlc

from app.services.market_data.calendar import (
    is_market_open,
    filter_open_market_candles,
    is_forex_weekend,
)
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
    log_latest_candle,
)


def get_market_data_provider(
    provider_name: str = "twelvedata",
    http_client: Optional[httpx.AsyncClient] = None,
) -> TwelveDataProvider:
    """Production provider factory.
    
    Hard Rule 1: Twelve Data ONLY, symbol XAU/USD. No Yahoo, no fallback or backup provider.
    MockMarketDataProvider is never reachable from this production factory (tests inject it explicitly).
    """
    name = (provider_name or "twelvedata").lower().strip()

    if name in ("mock", "yfinance", "yahoo", "yahoofinance"):
        raise ValueError(
            f"Provider '{provider_name}' is forbidden in production factory. "
            "Twelve Data is the ONLY allowed market data provider."
        )

    if name not in ("twelvedata", "twelve", "twelve_data"):
        raise ValueError(f"Unknown or unsupported market data provider: '{provider_name}'. Only 'twelvedata' is supported.")

    if http_client is None:
        try:
            from app.main import app
            http_client = getattr(getattr(app, "state", None), "http_client", None)
        except Exception:
            http_client = None

    api_key = getattr(settings, "TWELVE_DATA_API_KEY", None)
    return TwelveDataProvider(api_key=api_key, http_client=http_client)


__all__ = [
    "BaseMarketDataProvider",
    "TwelveDataProvider",
    "MockMarketDataProvider",
    "IngestionService",
    "resample_ohlc",
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
    "is_market_open",
    "filter_open_market_candles",
    "log_latest_candle",
]
