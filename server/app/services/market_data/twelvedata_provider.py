"""Twelve Data Market Data Provider for reliable Forex and Commodity candles."""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
import httpx

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

    def __init__(self, api_key: str, timeout: float = 12.0):
        self.api_key = api_key
        self.base_url = "https://api.twelvedata.com"
        self.timeout = timeout
        self._last_call_time: float = 0.0

    def _map_timeframe(self, timeframe: str) -> str:
        """Map standard timeframes to Twelve Data interval strings."""
        return self.INTERVAL_MAP.get(timeframe.lower(), timeframe)

    def is_symbol_supported(self, symbol: str) -> bool:
        """Check if symbol is supported."""
        clean = (symbol or "").replace(" ", "").upper()
        return clean in self.SUPPORTED_SYMBOLS

    async def _rate_limit(self, min_interval: float = 7.5) -> None:
        """Enforce spacing only when necessary, preventing redundant blocking sleeps."""
        loop = asyncio.get_event_loop()
        now = loop.time()
        elapsed = now - self._last_call_time
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._last_call_time = loop.time()

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        drop_unclosed: bool = True,
    ) -> List[CandleCreate]:
        """Fetch historical candles from Twelve Data in verified UTC."""
        interval = self._map_timeframe(timeframe)
        url = f"{self.base_url}/time_series"

        # Request extra bar if dropping the active in-progress candle
        fetch_limit = limit + 1 if drop_unclosed else limit

        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": fetch_limit,
            "timezone": "UTC",
            "apikey": self.api_key,
            "format": "JSON",
        }

        if start_time:
            params["start_date"] = start_time.strftime("%Y-%m-%d %H:%M:%S")
        if end_time:
            params["end_date"] = end_time.strftime("%Y-%m-%d %H:%M:%S")

        try:
            await self._rate_limit(min_interval=7.5)

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params)
                data = response.json()

                if data.get("status") == "error" or ("code" in data and data["code"] != 200):
                    logger.error(f"Twelve Data API Error [{symbol} {timeframe}]: {data.get('message')}")
                    return []

                raw_values = data.get("values", [])
                if not raw_values:
                    return []

                # Twelve Data returns newest first. 
                # If drop_unclosed is True, drop the active in-progress candle at index 0.
                if drop_unclosed and len(raw_values) > 1:
                    raw_values = raw_values[1:]

                # Reverse so earliest is first (chronological order)
                raw_values.reverse()

                # Slice to requested limit
                if len(raw_values) > limit:
                    raw_values = raw_values[-limit:]

                candles: List[CandleCreate] = []
                for v in raw_values:
                    try:
                        ts_str = v.get("datetime")
                        if len(ts_str) == 10:
                            ts = datetime.strptime(ts_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        else:
                            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

                        candles.append(
                            CandleCreate(
                                symbol=symbol,
                                timeframe=timeframe,
                                timestamp=ts,
                                open=float(v["open"]),
                                high=float(v["high"]),
                                low=float(v["low"]),
                                close=float(v["close"]),
                                volume=float(v.get("volume", 0)),
                            )
                        )
                    except Exception as parse_err:
                        logger.warning(f"Failed to parse candle for {symbol}: {parse_err}")

                logger.info(f"Successfully fetched {len(candles)} closed candles for {symbol} [{timeframe}] in UTC.")
                return candles

        except Exception as e:
            logger.error(f"Twelve Data fetch failed for {symbol} [{timeframe}]: {e}")
            return []

    async def fetch_latest(
        self, symbol: str, timeframe: str, count: int = 50
    ) -> List[CandleCreate]:
        """Fetch the most recent closed candles for a given symbol and timeframe."""
        return await self.fetch_candles(symbol, timeframe, limit=count, drop_unclosed=True)