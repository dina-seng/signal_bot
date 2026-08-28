"""Twelve Data REST API market data provider."""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
import httpx
from app.core.config import settings
from app.core.logging import logger
from app.schemas.candle import CandleCreate
from app.services.market_data.base import BaseMarketDataProvider


class TwelveDataProvider(BaseMarketDataProvider):
    """Fetches Forex/Commodity OHLCV candles from Twelve Data API."""

    BASE_URL = "https://api.twelvedata.com"

    SYMBOL_MAP: Dict[str, str] = {
        "EUR/USD": "EUR/USD",
        "GBP/USD": "GBP/USD",
        "USD/JPY": "USD/JPY",
        "XAU/USD": "XAU/USD",
        "EURUSD": "EUR/USD",
        "GBPUSD": "GBP/USD",
        "USDJPY": "USD/JPY",
        "XAUUSD": "XAU/USD",
    }

    INTERVAL_MAP: Dict[str, str] = {
        "1m": "1min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1day",
    }

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.TWELVE_DATA_API_KEY

    def is_symbol_supported(self, symbol: str) -> bool:
        normalized = symbol.replace(" ", "").upper()
        return normalized in self.SYMBOL_MAP

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 200,
    ) -> List[CandleCreate]:
        if not self.api_key:
            logger.warning("TwelveData API key is not configured. Falling back / returning empty.")
            return []

        clean_symbol = self.SYMBOL_MAP.get(symbol.replace(" ", "").upper(), symbol)
        interval = self.INTERVAL_MAP.get(timeframe.lower())
        if not interval:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        params = {
            "symbol": clean_symbol,
            "interval": interval,
            "outputsize": min(limit, 5000),
            "apikey": self.api_key,
            "format": "JSON",
        }

        if start_time:
            params["start_date"] = start_time.strftime("%Y-%m-%d %H:%M:%S")
        if end_time:
            params["end_date"] = end_time.strftime("%Y-%m-%d %H:%M:%S")

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(f"{self.BASE_URL}/time_series", params=params)
                data = response.json()

                if data.get("status") == "error":
                    logger.error(f"TwelveData API error: {data.get('message')}")
                    return []

                values = data.get("values", [])
                candles: List[CandleCreate] = []

                for item in values:
                    dt = datetime.fromisoformat(item["datetime"]).replace(tzinfo=timezone.utc)
                    candle = CandleCreate(
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=dt,
                        open=float(item["open"]),
                        high=float(item["high"]),
                        low=float(item["low"]),
                        close=float(item["close"]),
                        volume=float(item.get("volume", 0.0) or 0.0),
                    )
                    candles.append(candle)

                candles.sort(key=lambda c: c.timestamp)
                return candles
            except Exception as e:
                logger.error(f"Failed to fetch data from TwelveData: {e}")
                return []

    async def fetch_latest(
        self,
        symbol: str,
        timeframe: str,
        count: int = 50,
    ) -> List[CandleCreate]:
        return await self.fetch_candles(symbol, timeframe, limit=count)
