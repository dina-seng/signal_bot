"""Abstract base class and contract for market data providers."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
from app.schemas.candle import CandleCreate


class BaseMarketDataProvider(ABC):
    """Abstract interface for all Forex/Commodity market data providers."""

    @abstractmethod
    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 200,
    ) -> List[CandleCreate]:
        """Fetch historical OHLCV candles for a given symbol and timeframe.

        Args:
            symbol: Standard instrument identifier (e.g. 'EUR/USD', 'XAU/USD')
            timeframe: Standard timeframe string (e.g. '15m', '1h', '4h')
            start_time: Optional starting datetime in UTC
            end_time: Optional ending datetime in UTC
            limit: Maximum number of candles to fetch

        Returns:
            List of validated CandleCreate instances sorted in ascending chronological order.
        """
        pass

    @abstractmethod
    async def fetch_latest(
        self,
        symbol: str,
        timeframe: str,
        count: int = 50,
    ) -> List[CandleCreate]:
        """Fetch the most recent candles for a given symbol and timeframe.

        Args:
            symbol: Standard instrument identifier
            timeframe: Standard timeframe string
            count: Number of recent candles to fetch

        Returns:
            List of validated CandleCreate instances sorted chronologically.
        """
        pass

    @abstractmethod
    def is_symbol_supported(self, symbol: str) -> bool:
        """Check if the provider supports the requested symbol."""
        pass
