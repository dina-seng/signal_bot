"""Twelve Data Market Data Provider for reliable Forex and Commodity candles."""

import asyncio
import httpx
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.logging import logger
from app.schemas.candle import CandleCreate
from app.services.market_data.base import BaseMarketDataProvider


class TwelveDataProvider(BaseMarketDataProvider):
    """Fetches OHLCV data using the Twelve Data API."""

    INTERVAL_MAP: Dict[str, str] = {
        "15m": "15min",
        "30m": "30min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1day",
    }

    SUPPORTED_SYMBOLS: List[str] = [
        "XAU/USD", "USD/JPY",
        "XAUUSD", "USDJPY",
    ]

    def __init__(self, api_key: str, timeout: float = 10.0):
        self.api_key = api_key
        self.base_url = "https://api.twelvedata.com"
        self.timeout = timeout

    def _map_timeframe(self, timeframe: str) -> str:
        """Map standard timeframes to Twelve Data interval strings."""
        return self.INTERVAL_MAP.get(timeframe.lower(), timeframe)

    def is_symbol_supported(self, symbol: str) -> bool:
        """Check if symbol is supported."""
        clean = (symbol or "").replace(" ", "").upper()
        return clean in self.SUPPORTED_SYMBOLS

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[CandleCreate]:
        """Fetch historical candles from Twelve Data."""
        interval = self._map_timeframe(timeframe)
        url = f"{self.base_url}/time_series"
        
        # Twelve Data accepts standard symbols like "EUR/USD" and "XAU/USD" natively!
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": limit,
            "apikey": self.api_key,
            "format": "JSON",
        }
        if start_time:
            params["start_date"] = start_time.strftime("%Y-%m-%d %H:%M:%S")
        if end_time:
            params["end_date"] = end_time.strftime("%Y-%m-%d %H:%M:%S")

        try:
            # Small sleep to respect the free tier rate limit (8 requests/minute)
            await asyncio.sleep(0.5)

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params)
                data = response.json()

                # Check for API errors
                if "code" in data and data["code"] != 200:
                    logger.error(f"Twelve Data API Error [{symbol} {timeframe}]: {data.get('message')}")
                    return []

                candles: List[CandleCreate] = []
                # Twelve Data returns newest first; our ingestion expects oldest first
                values = data.get("values", [])
                values.reverse()

                for v in values:
                    try:
                        # Parse timestamp (Twelve Data returns "YYYY-MM-DD HH:MM:SS" in UTC)
                        ts_str = v.get("datetime")
                        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        
                        candles.append(CandleCreate(
                            symbol=symbol,
                            timeframe=timeframe,
                            timestamp=ts,
                            open=float(v["open"]),
                            high=float(v["high"]),
                            low=float(v["low"]),
                            close=float(v["close"]),
                            volume=float(v.get("volume", 0)),
                        ))
                    except Exception as e:
                        logger.warning(f"Failed to parse candle for {symbol}: {e}")
                
                logger.info(f"Successfully fetched {len(candles)} candles for {symbol} [{timeframe}] from Twelve Data.")
                return candles

        except Exception as e:
            logger.error(f"Twelve Data fetch failed for {symbol} [{timeframe}]: {e}")
            return []

    async def fetch_latest(
        self, symbol: str, timeframe: str, count: int = 50
    ) -> List[CandleCreate]:
        """Fetch the most recent candles for a given symbol and timeframe."""
        return await self.fetch_candles(symbol, timeframe, limit=count)