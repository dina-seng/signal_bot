"""Abstract base class and contract for market data providers."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
from app.schemas.candle import CandleCreate
from app.schemas.market import QuoteResponse


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
        """Fetch historical OHLCV candles for a given symbol and timeframe."""
        pass

    @abstractmethod
    async def fetch_latest(
        self,
        symbol: str,
        timeframe: str,
        count: int = 50,
    ) -> List[CandleCreate]:
        """Fetch the most recent candles for a given symbol and timeframe."""
        pass

    async def fetch_quote(
        self,
        symbol: str,
    ) -> Optional[QuoteResponse]:
        """Fetch real-time price quote for a symbol. Default fallback returns latest candle close."""
        try:
            candles = await self.fetch_latest(symbol, "15m", count=1)
            if candles:
                c = candles[-1]
                return QuoteResponse(
                    symbol=symbol,
                    price=c.close,
                    high=c.high,
                    low=c.low,
                    volume=c.volume,
                    timestamp=c.timestamp,
                    source="candle_fallback",
                )
        except Exception:
            pass
        return None

    @abstractmethod
    def is_symbol_supported(self, symbol: str) -> bool:
        """Check if the provider supports the requested symbol."""
        pass
