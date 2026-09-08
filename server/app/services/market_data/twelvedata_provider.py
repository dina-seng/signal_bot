"""Twelve Data Market Data Provider for reliable Forex and Commodity candles."""

import asyncio
import httpx
from datetime import datetime, timezone
from typing import List

from app.core.logging import logger
from app.schemas.candle import CandleBase
from app.services.market_data.base import BaseMarketDataProvider


class TwelveDataProvider(BaseMarketDataProvider):
    """Fetches OHLCV data using the Twelve Data API."""

    def __init__(self, api_key: str, timeout: float = 10.0):
        self.api_key = api_key
        self.base_url = "https://api.twelvedata.com"
        self.timeout = timeout

    @staticmethod
    def _map_timeframe(timeframe: str) -> str:
        """Map standard timeframes to Twelve Data interval strings."""
        mapping = {
            "15m": "15min",
            "30m": "30min",
            "1h": "1h",
            "4h": "4h",
            "1d": "1day"
        }
        return mapping.get(timeframe, timeframe)

    async def fetch_candles(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> List[CandleBase]:
        """Fetch historical candles from Twelve Data."""
        interval = self._map_timeframe(timeframe)
        url = f"{self.base_url}/time_series"
        
        # Twelve Data accepts standard symbols like "EUR/USD" and "XAU/USD" natively!
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": limit,
            "apikey": self.api_key,
            "format": "JSON"
        }

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

                candles = []
                # Twelve Data returns newest first; our ingestion expects oldest first
                values = data.get("values", [])
                values.reverse()

                for v in values:
                    try:
                        # Parse timestamp (Twelve Data returns "YYYY-MM-DD HH:MM:SS" in UTC)
                        ts_str = v.get("datetime")
                        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        
                        candles.append(CandleBase(
                            timestamp=ts,
                            open=float(v["open"]),
                            high=float(v["high"]),
                            low=float(v["low"]),
                            close=float(v["close"]),
                            volume=float(v.get("volume", 0))
                        ))
                    except Exception as e:
                        logger.warning(f"Failed to parse candle for {symbol}: {e}")
                
                logger.info(f"Successfully fetched {len(candles)} candles for {symbol} [{timeframe}] from Twelve Data.")
                return candles

        except Exception as e:
            logger.error(f"Twelve Data fetch failed for {symbol} [{timeframe}]: {e}")
            return []