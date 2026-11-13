"""Twelve Data Market Data Provider for reliable Forex and Commodity candles."""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
import httpx

from app.core.logging import logger
from app.schemas.candle import CandleCreate
from app.schemas.market import QuoteResponse
from app.services.market_data.base import BaseMarketDataProvider
from app.services.market_data.freshness import get_timeframe_delta
from app.services.market_data.yfinance_provider import YahooFinanceProvider


class TwelveDataProvider(BaseMarketDataProvider):
    """Fetches OHLCV data using the Twelve Data API with automatic fallback to Yahoo Finance."""

    INTERVAL_MAP: Dict[str, str] = {
        "15m": "15min",
        "30m": "30min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1day",
    }

    SUPPORTED_SYMBOLS: List[str] = [
        "XAU/USD",
        "XAUUSD",          # Twelve Data slash-free alias for gold
        # Quarantined: US100 suspended due to API paywalls
    ]

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 12.0,
        http_client: Optional[httpx.AsyncClient] = None,
        fallback_provider: Optional[BaseMarketDataProvider] = None,
    ):
        self.api_key = api_key
        self.base_url = "https://api.twelvedata.com"
        self.timeout = timeout
        self._last_call_time: float = 0.0
        self._rate_limit_lock = asyncio.Lock()
        self._http_client = http_client  # Injected shared client; falls back to per-request if None
        self._fallback_provider = fallback_provider or YahooFinanceProvider(timeout=timeout)

    def _map_timeframe(self, timeframe: str) -> str:
        """Map standard timeframes to Twelve Data interval strings."""
        return self.INTERVAL_MAP.get(timeframe.lower(), timeframe)

    def is_symbol_supported(self, symbol: str) -> bool:
        """Check if symbol is supported."""
        clean = (symbol or "").replace(" ", "").upper()
        return clean in self.SUPPORTED_SYMBOLS

    async def _rate_limit(self, min_interval: float = 7.5) -> None:
        """Enforce spacing only when necessary, preventing redundant blocking sleeps."""
        async with self._rate_limit_lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            elapsed = now - self._last_call_time
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
            self._last_call_time = loop.time()

    async def _fallback_fetch(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        limit: int,
        drop_unclosed: bool,
    ) -> List[CandleCreate]:
        """Trigger fallback to Yahoo Finance when Twelve Data fails or exhausts credits."""
        logger.warning(
            f"Twelve Data unavailable or returned 0 candles for {symbol} [{timeframe}]. "
            f"Flipping to YahooFinanceProvider fallback..."
        )
        try:
            return await self._fallback_provider.fetch_candles(
                symbol=symbol,
                timeframe=timeframe,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                drop_unclosed=drop_unclosed,
            )
        except Exception as fb_err:
            logger.error(f"YahooFinance fallback failed for {symbol} [{timeframe}]: {fb_err}")
            return []

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        drop_unclosed: bool = True,
    ) -> List[CandleCreate]:
        """Fetch historical candles from Twelve Data in verified UTC, falling back to Yahoo Finance."""
        if not self.is_symbol_supported(symbol):
            logger.warning(f"Twelve Data skipping unsupported or quarantined symbol: {symbol}")
            return []

        if not self.api_key:
            logger.warning("Twelve Data API key is missing or empty. Using YahooFinanceProvider fallback directly.")
            return await self._fallback_fetch(symbol, timeframe, start_time, end_time, limit, drop_unclosed)

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

            if self._http_client:
                # Use shared persistent client
                response = await self._http_client.get(url, params=params)
                data = response.json()
            else:
                # Fallback: create a one-shot client
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, params=params)
                    data = response.json()

            # Defensive error check for rate limits / invalid api keys / provider errors
            if data.get("status") == "error" or ("code" in data and data["code"] != 200):
                err_msg = data.get("message", "Unknown error")
                logger.warning(f"Twelve Data API Error [{symbol} {timeframe}]: {err_msg}")
                return await self._fallback_fetch(symbol, timeframe, start_time, end_time, limit, drop_unclosed)

            raw_values = data.get("values", [])
            if not raw_values:
                logger.warning(f"Twelve Data returned 0 raw values for {symbol} [{timeframe}].")
                return await self._fallback_fetch(symbol, timeframe, start_time, end_time, limit, drop_unclosed)

            now_utc = datetime.now(timezone.utc)
            tf_delta = get_timeframe_delta(timeframe)

            candles: List[CandleCreate] = []
            for v in raw_values:
                try:
                    ts_str = v.get("datetime")
                    if len(ts_str) == 10:
                        ts = datetime.strptime(ts_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    else:
                        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

                    # Keep a bar if and only if candle_open_ts + timeframe_delta <= current_utc_time (matching yahoo_finance.py)
                    if drop_unclosed and (ts + tf_delta > now_utc):
                        continue

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

            # Sort ascending chronologically
            candles.sort(key=lambda c: c.timestamp)

            # Slice to requested limit
            if limit and len(candles) > limit:
                candles = candles[-limit:]

            if candles:
                logger.info(f"Successfully fetched {len(candles)} closed candles for {symbol} [{timeframe}] via Twelve Data.")
                return candles

            return await self._fallback_fetch(symbol, timeframe, start_time, end_time, limit, drop_unclosed)

        except Exception as e:
            logger.error(f"Twelve Data fetch failed for {symbol} [{timeframe}]: {e}")
            return await self._fallback_fetch(symbol, timeframe, start_time, end_time, limit, drop_unclosed)

    async def fetch_latest(
        self, symbol: str, timeframe: str, count: int = 50
    ) -> List[CandleCreate]:
        """Fetch the most recent closed candles for a given symbol and timeframe."""
        return await self.fetch_candles(symbol, timeframe, limit=count, drop_unclosed=True)

    async def fetch_quote(self, symbol: str) -> Optional[QuoteResponse]:
        """Fetch real-time price quote from Twelve Data, with automatic fallback to Yahoo Finance."""
        if not self.is_symbol_supported(symbol):
            logger.warning(f"Twelve Data skipping unsupported symbol for quote: {symbol}")
            return None

        if not self.api_key:
            return await self._fallback_provider.fetch_quote(symbol)

        url = f"{self.base_url}/quote"
        params = {
            "symbol": symbol,
            "apikey": self.api_key,
        }

        try:
            await self._rate_limit(min_interval=7.5)

            if self._http_client:
                response = await self._http_client.get(url, params=params)
                data = response.json()
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, params=params)
                    data = response.json()

            if data.get("status") == "error" or ("code" in data and data["code"] != 200):
                logger.warning(f"Twelve Data quote error for {symbol}: {data.get('message')}. Falling back...")
                return await self._fallback_provider.fetch_quote(symbol)

            price_str = data.get("close") or data.get("price")
            if price_str and float(price_str) > 0:
                price = float(price_str)
                high = float(data["high"]) if data.get("high") else None
                low = float(data["low"]) if data.get("low") else None
                vol = float(data["volume"]) if data.get("volume") else None

                return QuoteResponse(
                    symbol=symbol,
                    price=price,
                    bid=float(data["bid"]) if data.get("bid") else None,
                    ask=float(data["ask"]) if data.get("ask") else None,
                    high=high,
                    low=low,
                    volume=vol,
                    timestamp=datetime.now(timezone.utc),
                    source="twelvedata",
                )

            return await self._fallback_provider.fetch_quote(symbol)
        except Exception as e:
            logger.warning(f"Twelve Data quote failed for {symbol}: {e}. Falling back...")
            return await self._fallback_provider.fetch_quote(symbol)
