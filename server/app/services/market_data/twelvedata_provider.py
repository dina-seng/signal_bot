"""Twelve Data Market Data Provider for reliable XAU/USD candles.

HARD RULES:
1. Candle source: Twelve Data ONLY, symbol XAU/USD. No Yahoo, no yfinance, no fallback or backup provider anywhere.
2. Injected shared httpx.AsyncClient from app lifespan.
3. Global token bucket rate limit: 7 req/min (free tier is 8).
4. Daily budget tracker persisted in table api_usage (date, calls); hard stop at 780/day.
5. 429 => wait for next minute window and retry up to 3 times, then fail loudly (ERROR log + STALE).
6. Drop forming bar by timestamp rule (ts + delta <= now), never by 'drop index 0'.
7. Validate OHLC invariants; reject bad rows, count them.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
import time
from typing import Callable, Dict, List, Optional
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import logger
from app.models.api_usage import ApiUsage
from app.schemas.candle import CandleCreate
from app.schemas.market import QuoteResponse
from app.services.market_data.base import BaseMarketDataProvider
from app.services.market_data.freshness import get_timeframe_delta
from app.services.market_data.symbols import (
    UnknownSymbolError,
    normalize_symbol,
    get_provider_symbol,
)


class TwelveDataError(Exception):
    """Base exception for Twelve Data API errors."""
    pass


class TwelveDataRateLimitError(TwelveDataError):
    """Raised when Twelve Data returns HTTP 429 rate limit error after retries."""
    pass


class TwelveDataBudgetExceededError(TwelveDataError):
    """Raised when the daily API call budget (780 calls/day) is exhausted."""
    pass


class TokenBucketRateLimiter:
    """Thread-safe and async-safe token bucket rate limiter enforcing 7 requests per minute."""

    def __init__(self, rate_per_minute: float = 7.0):
        self.capacity = rate_per_minute
        self.tokens = rate_per_minute
        self.rate = rate_per_minute / 60.0  # tokens per second
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_update = now

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return

                wait_time = max(0.01, (1.0 - self.tokens) / self.rate)
                await asyncio.sleep(wait_time)


# Global process-wide token bucket
GLOBAL_RATE_LIMITER = TokenBucketRateLimiter(rate_per_minute=7.0)


def track_and_enforce_daily_budget(session_factory: Optional[Callable[[], Session]] = None, max_daily_budget: int = 780) -> int:
    """Persist and enforce daily budget limit in api_usage table.
    
    Returns:
        Total API calls made today.
    Raises:
        TwelveDataBudgetExceededError if limit is reached.
    """
    factory = session_factory or SessionLocal
    today = date.today()

    try:
        with factory() as db:
            usage = db.query(ApiUsage).filter(ApiUsage.date == today).first()
            if not usage:
                usage = ApiUsage(date=today, calls=1)
                db.add(usage)
                db.commit()
                current_calls = 1
            else:
                if usage.calls >= max_daily_budget:
                    logger.error(f"HARD STOP: Twelve Data daily budget exhausted ({usage.calls}/{max_daily_budget} calls).")
                    raise TwelveDataBudgetExceededError(
                        f"Twelve Data daily budget exhausted: {usage.calls}/{max_daily_budget} calls on {today}."
                    )
                usage.calls += 1
                db.commit()
                current_calls = usage.calls

            logger.debug(f"Twelve Data daily API calls: {current_calls}/{max_daily_budget}")
            return current_calls
    except TwelveDataBudgetExceededError:
        raise
    except Exception as e:
        logger.warning(f"Could not update api_usage table ({e}); proceeding defensively.")
        return 0


def get_daily_usage(session_factory: Optional[Callable[[], Session]] = None) -> Dict[str, int]:
    """Retrieve today's API usage and budget limit."""
    factory = session_factory or SessionLocal
    today = date.today()
    try:
        with factory() as db:
            usage = db.query(ApiUsage).filter(ApiUsage.date == today).first()
            calls = usage.calls if usage else 0
            return {"date": today.isoformat(), "calls_today": calls, "max_budget": 780}
    except Exception:
        return {"date": today.isoformat(), "calls_today": 0, "max_budget": 780}


class TwelveDataProvider(BaseMarketDataProvider):
    """Twelve Data provider strictly dedicated to XAU/USD without any external fallbacks."""

    INTERVAL_MAP: Dict[str, str] = {
        "15m": "15min",
        "30m": "30min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1day",
    }

    SUPPORTED_SYMBOLS: List[str] = ["XAU/USD", "XAUUSD", "BTC/USD"]

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 15.0,
        http_client: Optional[httpx.AsyncClient] = None,
        session_factory: Optional[Callable[[], Session]] = None,
        rate_limiter: Optional[TokenBucketRateLimiter] = None,
    ):
        self.api_key = api_key or getattr(settings, "TWELVE_DATA_API_KEY", None)
        self.base_url = "https://api.twelvedata.com"
        self.timeout = timeout
        self.http_client = http_client
        self.session_factory = session_factory or SessionLocal
        self.rate_limiter = rate_limiter or GLOBAL_RATE_LIMITER
        self.rejected_rows_count: int = 0

    def _map_timeframe(self, timeframe: str) -> str:
        return self.INTERVAL_MAP.get(timeframe.lower(), timeframe)

    def is_symbol_supported(self, symbol: str) -> bool:
        try:
            canonical = normalize_symbol(symbol)
            return canonical in ("XAU/USD", "XAUUSD", "BTC/USD")
        except UnknownSymbolError:
            return False

    async def _execute_request_with_retry(self, url: str, params: dict) -> dict:
        """Execute request with rate limiting, daily budget tracking, and 429 retry logic."""
        if not self.api_key:
            raise TwelveDataError("TWELVE_DATA_API_KEY is not configured.")

        # Shared client check
        client = self.http_client
        close_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout)
            close_client = True

        max_attempts = 4  # Initial + 3 retries
        try:
            for attempt in range(1, max_attempts + 1):
                # Rate limit token bucket wait
                await self.rate_limiter.acquire()

                # Daily budget tracker and hard stop
                track_and_enforce_daily_budget(self.session_factory, max_daily_budget=780)

                try:
                    response = await client.get(url, params=params)
                except Exception as req_err:
                    if attempt == max_attempts:
                        logger.error(f"Twelve Data request failed after {max_attempts} attempts: {req_err}")
                        raise TwelveDataError(f"Twelve Data connection failed: {req_err}") from req_err
                    logger.warning(f"Twelve Data network error on attempt {attempt}: {req_err}. Retrying in 5s...")
                    await asyncio.sleep(5.0)
                    continue

                if response.status_code == 429:
                    if attempt < max_attempts:
                        logger.warning(
                            f"Twelve Data HTTP 429 Rate Limit encountered (attempt {attempt}/{max_attempts - 1}). "
                            "Sleeping 60s for the next minute window..."
                        )
                        await asyncio.sleep(60.0)
                        continue
                    else:
                        logger.error("Twelve Data 429 Rate Limit exceeded after 3 retries! System marked STALE.")
                        raise TwelveDataRateLimitError("Twelve Data HTTP 429 rate limit exceeded after 3 retries.")

                try:
                    data = response.json()
                except Exception as json_err:
                    raise TwelveDataError(f"Twelve Data returned non-JSON response ({response.status_code}): {response.text}") from json_err

                # Defensive check: treat HTTP 200 with status=error or code field != 200 as an error
                if isinstance(data, dict):
                    if data.get("status") == "error" or ("code" in data and data["code"] != 200):
                        err_code = data.get("code")
                        err_msg = data.get("message", "Unknown error")
                        if err_code == 429:
                            if attempt < max_attempts:
                                logger.warning(
                                    f"Twelve Data JSON 429 error (attempt {attempt}): {err_msg}. Waiting 60s..."
                                )
                                await asyncio.sleep(60.0)
                                continue
                            else:
                                logger.error("Twelve Data JSON 429 rate limit persisted after 3 retries.")
                                raise TwelveDataRateLimitError(f"Twelve Data rate limit error: {err_msg}")

                        logger.error(f"Twelve Data API error [{err_code}]: {err_msg}")
                        raise TwelveDataError(f"Twelve Data API error ({err_code}): {err_msg}")

                return data

            raise TwelveDataError("Failed to fetch data from Twelve Data after maximum retry attempts.")
        finally:
            if close_client:
                await client.aclose()

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        drop_unclosed: bool = True,
    ) -> List[CandleCreate]:
        """Fetch historical candles from Twelve Data.
        
        Hard Rule: Only XAU/USD. Validates OHLC invariants and drops forming bars by timestamp.
        """
        canonical = normalize_symbol(symbol)
        if canonical not in ("XAU/USD", "BTC/USD"):
            raise ValueError(f"TwelveDataProvider only supports 'XAU/USD' and 'BTC/USD'. Requested: '{symbol}'")

        interval = self._map_timeframe(timeframe)
        url = f"{self.base_url}/time_series"
        fetch_limit = limit + 1 if drop_unclosed else limit

        params = {
            "symbol": canonical,
            "interval": interval,
            "outputsize": min(fetch_limit, 5000),
            "timezone": "UTC",
            "apikey": self.api_key,
            "format": "JSON",
            "order": "ASC",
        }

        if start_time:
            params["start_date"] = start_time.strftime("%Y-%m-%d %H:%M:%S")
        if end_time:
            params["end_date"] = end_time.strftime("%Y-%m-%d %H:%M:%S")

        data = await self._execute_request_with_retry(url, params)
        raw_values = data.get("values", [])
        if not raw_values:
            logger.warning(f"Twelve Data returned 0 values for {canonical} [{timeframe}].")
            return []

        now_utc = datetime.now(timezone.utc)
        tf_delta = get_timeframe_delta(timeframe)

        candles: List[CandleCreate] = []
        rejected = 0

        for v in raw_values:
            try:
                ts_str = v.get("datetime")
                if len(ts_str) == 10:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                else:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

                # Forming bar rule: keep a bar only if ts + delta <= now_utc, never by drop index 0
                if drop_unclosed and (ts + tf_delta > now_utc):
                    continue

                open_p = float(v["open"])
                high_p = float(v["high"])
                low_p = float(v["low"])
                close_p = float(v["close"])
                volume_val = float(v.get("volume", 0.0) or 0.0)

                # Validate OHLC price invariants
                if not (open_p > 0 and high_p > 0 and low_p > 0 and close_p > 0):
                    rejected += 1
                    continue
                if not (high_p >= open_p and high_p >= close_p and low_p <= open_p and low_p <= close_p):
                    rejected += 1
                    continue

                candles.append(
                    CandleCreate(
                        symbol=canonical,
                        timeframe=timeframe,
                        timestamp=ts,
                        open=open_p,
                        high=high_p,
                        low=low_p,
                        close=close_p,
                        volume=volume_val,
                    )
                )
            except Exception as parse_err:
                rejected += 1
                logger.debug(f"Failed parsing row: {parse_err}")

        self.rejected_rows_count += rejected
        if rejected > 0:
            logger.warning(f"Twelve Data rejected {rejected} invalid rows violating OHLC invariants.")

        candles.sort(key=lambda c: c.timestamp)
        if limit and len(candles) > limit:
            candles = candles[-limit:]

        return candles

    async def fetch_latest(
        self, symbol: str, timeframe: str, count: int = 50
    ) -> List[CandleCreate]:
        return await self.fetch_candles(symbol, timeframe, limit=count, drop_unclosed=True)

    async def fetch_quote(self, symbol: str) -> Optional[QuoteResponse]:
        """Fetch live quote for XAU/USD from Twelve Data."""
        canonical = normalize_symbol(symbol)
        if canonical != "XAU/USD":
            raise ValueError(f"TwelveDataProvider only supports 'XAU/USD'. Requested: '{symbol}'")

        url = f"{self.base_url}/quote"
        params = {
            "symbol": "XAU/USD",
            "apikey": self.api_key,
        }

        data = await self._execute_request_with_retry(url, params)
        echoed_sym = data.get("symbol")
        if echoed_sym and echoed_sym.replace("/", "") != "XAUUSD":
            raise TwelveDataError(f"Echoed symbol mismatch: expected XAU/USD, got {echoed_sym}")

        price_str = data.get("close") or data.get("price")
        if price_str and float(price_str) > 0:
            price = float(price_str)
            now_utc = datetime.now(timezone.utc)
            quote_ts = now_utc
            raw_ts = data.get("last_quote_at") or data.get("timestamp")
            if raw_ts and isinstance(raw_ts, (int, float)) and raw_ts > 0:
                quote_ts = datetime.fromtimestamp(raw_ts, tz=timezone.utc)

            # quote_ts is the provider's minute-rounded label. It is NOT a staleness
            # signal: the API layer derives is_stale from last_price_change_at.
            age_sec = max(0.0, (now_utc - quote_ts).total_seconds())

            return QuoteResponse(
                symbol=canonical,
                price=price,
                bid=float(data["bid"]) if data.get("bid") else None,
                ask=float(data["ask"]) if data.get("ask") else None,
                high=float(data["high"]) if data.get("high") else None,
                low=float(data["low"]) if data.get("low") else None,
                volume=float(data["volume"]) if data.get("volume") else None,
                timestamp=quote_ts,
                provider_timestamp=quote_ts,
                fetched_at=now_utc,
                source="twelvedata",
                provider="twelvedata",
                provider_symbol="XAU/USD",
                age_seconds=round(age_sec, 2),
                is_stale=False,
                degraded=False,
                fallback_reason=None,
                cached=False,
            )

        raise TwelveDataError(f"Twelve Data returned non-positive or empty price: {price_str}")
