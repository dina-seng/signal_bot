"""Deterministic Mock Market Data Provider for unit and integration testing."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from app.schemas.candle import CandleCreate
from app.services.market_data.base import BaseMarketDataProvider


class MockMarketDataProvider(BaseMarketDataProvider):
    """Generates synthetic, deterministic OHLCV candles for testing pipelines and strategies."""

    SUPPORTED_SYMBOLS = ["XAU/USD", "US100"]

    def __init__(self, base_price: float = 1.1000, volatility: float = 0.0010):
        self.base_price = base_price
        self.volatility = volatility

    def is_symbol_supported(self, symbol: str) -> bool:
        return symbol in self.SUPPORTED_SYMBOLS

    def _get_timeframe_delta(self, timeframe: str) -> timedelta:
        tf = timeframe.lower()
        if tf == "15m":
            return timedelta(minutes=15)
        elif tf == "1h":
            return timedelta(hours=1)
        elif tf == "4h":
            return timedelta(hours=4)
        elif tf == "1d":
            return timedelta(days=1)
        return timedelta(minutes=15)

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[CandleCreate]:
        delta = self._get_timeframe_delta(timeframe)
        end = end_time or datetime.now(timezone.utc)
        start = start_time or (end - delta * limit)

        candles: List[CandleCreate] = []
        current_time = start
        current_price = self.base_price

        # Specific base prices for realistic mock test data
        if "US100" in symbol or "NAS" in symbol or "NDX" in symbol:
            current_price = 20000.00
            self.volatility = 25.0
        elif "JPY" in symbol:
            current_price = 150.00
            self.volatility = 0.15
        elif "XAU" in symbol:
            current_price = 2500.00
            self.volatility = 3.50

        step = 0
        while current_time <= end and len(candles) < limit:
            # Deterministic wave pattern: slight upward bias with swings
            drift = (step % 5 - 2) * (self.volatility * 0.4)
            open_p = round(current_price, 5 if "JPY" not in symbol else 3)
            close_p = round(open_p + drift, 5 if "JPY" not in symbol else 3)
            high_p = round(max(open_p, close_p) + (self.volatility * 0.5), 5 if "JPY" not in symbol else 3)
            low_p = round(min(open_p, close_p) - (self.volatility * 0.5), 5 if "JPY" not in symbol else 3)
            vol = float(1000 + (step % 10) * 100)

            candles.append(
                CandleCreate(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=current_time,
                    open=open_p,
                    high=high_p,
                    low=low_p,
                    close=close_p,
                    volume=vol,
                )
            )
            current_price = close_p
            current_time += delta
            step += 1

        return candles

    async def fetch_latest(
        self,
        symbol: str,
        timeframe: str,
        count: int = 50,
    ) -> List[CandleCreate]:
        return await self.fetch_candles(symbol, timeframe, limit=count)
