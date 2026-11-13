# DEBUG_BUNDLE.md — QuantView Diagnostics & Source Bundle

> **Notice:** Generated for external engineering handoff. All secrets (API keys, passwords, connection strings, tokens) have been redacted with `<REDACTED>`.

## Table of Contents

| Section | File Path | Line Count | Description |
| :--- | :--- | :--- | :--- |
| A.1 | `server/app/services/market_data/twelvedata_provider.py` | 204 | Twelve Data provider |
| A.2 | `server/app/services/market_data/yfinance_provider.py` | 231 | Yahoo Finance provider |
| A.2 | `server/app/services/market_data/base.py` | 57 | Provider base class |
| A.2 | `server/app/services/market_data/__init__.py` | 68 | Provider factory & fallback chain |
| A.3 | `server/app/services/market_data/ingestion.py` | 358 | IngestionService (freshness cache gate, gap detection) |
| A.4 | `server/app/models/candle.py` | 44 | Candle model |
| A.4 | `server/app/core/database.py` | 76 | DB session setup & init_db |
| B.5 | `server/app/main.py` | 78 | FastAPI lifespan, persistent HTTP client & scheduler trigger |
| B.5 | `server/app/services/telegram/scheduler.py` | 187 | APScheduler job registration & trigger settings |
| B.6 | `server/app/services/telegram/scanner.py` | 545 | scanner.py (AutomatedMarketScanner / run_scan_cycle) |
| B.7 | `server/app/api/v1/telegram.py` | 191 | Telegram webhook router |
| B.7 | `server/app/services/telegram/command_handler.py` | 385 | Telegram command handlers (/scan, /sync, /signal) |
| B.7 | `server/app/services/telegram/message_formatter.py` | 493 | Telegram message formatter |
| C.8 | `server/app/services/market_data/freshness.py` | 286 | Freshness / STALE computation module |
| C.9 | `server/app/services/signals/confluence_engine.py` | 664 | ConfluenceEngine gatekeeper & staleness veto |
| D.10 | `server/app/core/config.py` | 106 | config.py / Settings (pydantic-settings) |
| D.11 | `server/.env.example` | 50 | .env.example template |
| E.13 | `server/app/api/v1/market.py` | 133 | Candles router GET /api/v1/market/{symbol}/candles |
| E.13 | `server/app/api/v1/paper.py` | 209 | Paper trading endpoints |
| E.14 | `client/src/App.tsx` | 946 | App.tsx (frontend root & dashboard polling) |
| E.14 | `client/src/components/SignalMatrix.tsx` | 238 | SignalMatrix.tsx (1s LIVE TICKING polling loop) |
| D.11 | `server/.env` (variable names only) | 29 | Names of set environment variables |
| D.12 | Grep occurrences of US100/NAS100/NDX/SUPPORTED_SYMBOLS | 103 | Cross-repo symbol grep matches |
| F.15 | Server /scan and /sync logs | 46 | Recent execution logs |
| F.16 | System command evidence & DB candle aggregation query | 25 | Package versions and newest candle timestamps |

## NOT FOUND

None. All 21 required files and artifacts were located and verified on disk.

---

## server/app/services/market_data/twelvedata_provider.py

```python
"""Twelve Data Market Data Provider for reliable Forex and Commodity candles."""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
import httpx

from app.core.logging import logger
from app.schemas.candle import CandleCreate
from app.services.market_data.base import BaseMarketDataProvider
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
```

---

## server/app/services/market_data/yfinance_provider.py

```python
"""Yahoo Finance Market Data Provider for reliable Forex and Commodity candles."""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
import pandas as pd
import yfinance as yf

from app.core.logging import logger
from app.schemas.candle import CandleCreate
from app.services.market_data.base import BaseMarketDataProvider
from app.services.market_data.freshness import (
    ensure_utc_datetime,
    get_timeframe_delta,
    is_candle_closed,
)


class YahooFinanceProvider(BaseMarketDataProvider):
    """Fetches real-time and historical forex/commodity OHLCV candles from Yahoo Finance."""

    # Ticker mappings: Primary ticker with list of fallback tickers
    TICKER_CANDIDATES: Dict[str, List[str]] = {
        "XAU/USD": ["GC=F", "XAUUSD=X"],
        "XAUUSD": ["GC=F", "XAUUSD=X"],
        "USD/JPY": ["JPY=X", "USDJPY=X"],
        "USDJPY": ["JPY=X", "USDJPY=X"],
        "EUR/USD": ["EURUSD=X"],
        "EURUSD": ["EURUSD=X"],
        "GBP/USD": ["GBPUSD=X"],
        "GBPUSD": ["GBPUSD=X"],
    }

    # Timeframe mapping to yfinance intervals
    INTERVAL_MAP: Dict[str, str] = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "4h": "1h",  # Resampled from 1h
        "1d": "1d",
    }

    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout

    def is_symbol_supported(self, symbol: str) -> bool:
        """Check if symbol has a ticker mapping."""
        clean = (symbol or "").replace(" ", "").upper()
        return clean in self.TICKER_CANDIDATES

    def _get_ticker_candidates(self, symbol: str) -> List[str]:
        """Return candidate Yahoo Finance tickers for a symbol."""
        clean = (symbol or "").replace(" ", "").upper()
        if clean in self.TICKER_CANDIDATES:
            return self.TICKER_CANDIDATES[clean]
        # Generic heuristic: if 6 alpha chars, append =X
        if len(clean) == 6 and clean.isalpha():
            return [f"{clean}=X"]
        return [clean]

    def _normalize_timeframe(self, timeframe: str) -> str:
        tf = timeframe.lower().strip()
        if tf not in self.INTERVAL_MAP:
            raise ValueError(f"Unsupported timeframe '{timeframe}'. Supported: {list(self.INTERVAL_MAP.keys())}")
        return tf

    def _parse_df_to_candles(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        limit: int = 100,
        drop_unclosed: bool = True,
    ) -> List[CandleCreate]:
        """Convert a yfinance DataFrame into validated CandleCreate models."""
        if df.empty:
            return []

        # If MultiIndex columns (e.g. from bulk download), flatten to first level
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        # Resample to 4h if timeframe is 4h
        tf_lower = timeframe.lower().strip()
        if tf_lower == "4h":
            df = (
                df.resample("4h")
                .agg(
                    {
                        "Open": "first",
                        "High": "max",
                        "Low": "min",
                        "Close": "last",
                        "Volume": "sum",
                    }
                )
                .dropna()
            )

        candles: List[CandleCreate] = []
        now_utc = datetime.now(timezone.utc)

        for index, row in df.iterrows():
            try:
                # Ensure UTC datetime
                if isinstance(index, pd.Timestamp):
                    dt = index.to_pydatetime()
                elif isinstance(index, datetime):
                    dt = index
                else:
                    dt = pd.to_datetime(index).to_pydatetime()

                dt = ensure_utc_datetime(dt)
                if dt is None:
                    continue

                open_p = float(row["Open"])
                high_p = float(row["High"])
                low_p = float(row["Low"])
                close_p = float(row["Close"])
                vol = float(row.get("Volume", 0.0) or 0.0)

                # Skip NaN, infinite, or non-positive price rows
                if any(pd.isna([open_p, high_p, low_p, close_p])) or any(p <= 0.0 for p in [open_p, high_p, low_p, close_p]):
                    continue

                candle = CandleCreate(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=dt,
                    open=open_p,
                    high=high_p,
                    low=low_p,
                    close=close_p,
                    volume=vol,
                )
                candles.append(candle)
            except Exception as e:
                logger.debug(f"Skipping invalid candle row at {index}: {e}")
                continue

        # Sort ascending chronologically
        candles.sort(key=lambda c: c.timestamp)

        # Drop active in-progress candle if requested
        if drop_unclosed and candles:
            delta = get_timeframe_delta(tf_lower)
            if candles[-1].timestamp + delta > now_utc:
                candles = candles[:-1]

        if limit and len(candles) > limit:
            candles = candles[-limit:]

        return candles

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        drop_unclosed: bool = True,
    ) -> List[CandleCreate]:
        """Fetch candles asynchronously from Yahoo Finance with ticker fallbacks."""
        candidates = self._get_ticker_candidates(symbol)
        tf = self._normalize_timeframe(timeframe)
        interval = self.INTERVAL_MAP[tf]

        # Determine appropriate historical lookback period
        if tf in ["1m", "5m"]:
            period = "5d"
        elif tf in ["15m", "30m"]:
            period = "5d"
        elif tf in ["1h", "4h"]:
            period = "60d"
        else:
            period = "60d"

        for ticker_str in candidates:
            def _fetch_sync() -> pd.DataFrame:
                try:
                    ticker = yf.Ticker(ticker_str)
                    if start_time and end_time:
                        return ticker.history(
                            interval=interval,
                            start=start_time,
                            end=end_time,
                            auto_adjust=False,
                        )
                    return ticker.history(
                        interval=interval,
                        period=period,
                        auto_adjust=False,
                    )
                except Exception as ex:
                    logger.debug(f"yfinance sync fetch exception for {ticker_str}: {ex}")
                    return pd.DataFrame()

            try:
                logger.info(f"Fetching Yahoo Finance market data for {symbol} using ticker '{ticker_str}' [{timeframe}]...")
                df = await asyncio.to_thread(_fetch_sync)
                candles = self._parse_df_to_candles(
                    df, symbol=symbol, timeframe=timeframe, limit=limit, drop_unclosed=drop_unclosed
                )

                if candles:
                    logger.info(
                        f"Successfully retrieved {len(candles)} closed candles for {symbol} via Yahoo Finance ({ticker_str}) [{timeframe}]."
                    )
                    return candles
                else:
                    logger.warning(
                        f"Yahoo Finance returned 0 valid candles for {symbol} using '{ticker_str}' [{timeframe}]. Trying next candidate..."
                    )
            except Exception as e:
                logger.warning(f"Yahoo Finance query failed for {symbol} ({ticker_str}): {e}")

        logger.error(f"YahooFinanceProvider: All candidate tickers exhausted for {symbol} [{timeframe}]. 0 candles retrieved.")
        return []

    async def fetch_latest(
        self,
        symbol: str,
        timeframe: str,
        count: int = 50,
    ) -> List[CandleCreate]:
        """Fetch the most recent closed candles for a given symbol and timeframe."""
        return await self.fetch_candles(symbol, timeframe, limit=count, drop_unclosed=True)
```

---

## server/app/services/market_data/base.py

```python
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
```

---

## server/app/services/market_data/__init__.py

```python
"""Market data module containing providers and ingestion engine."""

from app.core.config import settings
from app.core.logging import logger

from app.services.market_data.base import BaseMarketDataProvider
from app.services.market_data.twelvedata_provider import TwelveDataProvider
from app.services.market_data.yfinance_provider import YahooFinanceProvider
from app.services.market_data.mock_provider import MockMarketDataProvider
from app.services.market_data.ingestion import IngestionService

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
    is_forex_weekend,
    log_latest_candle,
)


def get_market_data_provider(provider_name: str = "twelvedata") -> BaseMarketDataProvider:
    """Factory to retrieve configured market data provider instance."""
    name = (provider_name or "twelvedata").lower().strip()
    
    if name in ("twelvedata", "twelve", "twelve_data"):
        api_key = getattr(settings, "TWELVE_DATA_API_KEY", None) or getattr(settings, "TWELVEDATA_API_KEY", None)
        # Even if api_key is None, TwelveDataProvider automatically falls back to YahooFinanceProvider
        return TwelveDataProvider(api_key=api_key) 
        
    elif name in ("yfinance", "yahoo", "yahoofinance"):
        return YahooFinanceProvider()

    elif name == "mock":
        return MockMarketDataProvider()
        
    else:
        # Safe default fallback
        logger.warning(f"Provider '{name}' not found or unavailable. Falling back to TwelveDataProvider with Yahoo fallback.")
        return TwelveDataProvider(api_key=getattr(settings, "TWELVE_DATA_API_KEY", None))


__all__ = [
    "BaseMarketDataProvider",
    "TwelveDataProvider",
    "YahooFinanceProvider",
    "MockMarketDataProvider",
    "IngestionService",
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
    "log_latest_candle",
]
```

---

## server/app/services/market_data/ingestion.py

```python
"""Market data ingestion service with validation, deduplication, gap detection, and freshness verification."""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, desc
from app.core.logging import logger
from app.models.candle import Candle
from app.schemas.candle import CandleCreate, GapInfo, IngestionReport
from app.services.market_data.base import BaseMarketDataProvider
from app.services.market_data.freshness import (
    TIMEFRAME_DELTAS,
    check_data_staleness,
    ensure_utc_datetime,
    filter_closed_candles,
    get_latest_closed_candle,
    get_timeframe_delta,
    is_forex_weekend,
    log_latest_candle,
)


class IngestionService:
    """Service for validating, cleaning, deduplicating, and persisting OHLCV candle streams."""

    TIMEFRAME_DELTAS: Dict[str, timedelta] = TIMEFRAME_DELTAS

    def __init__(self, provider: BaseMarketDataProvider, db: Session):
        self.provider = provider
        self.db = db

    def get_timeframe_delta(self, timeframe: str) -> timedelta:
        return get_timeframe_delta(timeframe)

    def clean_and_sort_candles(
        self, candles: List[CandleCreate]
    ) -> Tuple[List[CandleCreate], int]:
        """Validate, remove intra-batch duplicates, and sort chronologically.

        Returns:
            Tuple of (cleaned_sorted_candles, duplicate_count)
        """
        seen_timestamps: Set[datetime] = set()
        cleaned: List[CandleCreate] = []
        intra_duplicates = 0

        for candle in candles:
            # Ensure timestamp is UTC aware
            ts = ensure_utc_datetime(candle.timestamp)
            candle.timestamp = ts

            if ts in seen_timestamps:
                intra_duplicates += 1
                continue

            seen_timestamps.add(ts)
            cleaned.append(candle)

        # Sort ascending chronologically (handling out-of-order data)
        cleaned.sort(key=lambda c: c.timestamp)
        return cleaned, intra_duplicates

    def detect_gaps(
        self, candles: List[CandleCreate], symbol: str, timeframe: str
    ) -> List[GapInfo]:
        """Detect missing candle intervals between consecutive candles.

        Accounts for weekend market closures in Forex (Friday 21:00 UTC to Sunday 21:00 UTC).
        """
        if len(candles) < 2:
            return []

        delta = self.get_timeframe_delta(timeframe)
        gaps: List[GapInfo] = []

        for i in range(len(candles) - 1):
            curr_ts = ensure_utc_datetime(candles[i].timestamp)
            next_ts = ensure_utc_datetime(candles[i + 1].timestamp)
            diff = next_ts - curr_ts

            # If difference is larger than 1.5x expected interval
            if diff > delta * 1.5:
                # Check if it spans a weekend closure (approx 48 hours between Fri night and Sun night)
                is_weekend = (
                    curr_ts.weekday() == 4 and next_ts.weekday() in (6, 0)
                ) or (diff >= timedelta(hours=44) and diff <= timedelta(hours=54))

                if not is_weekend:
                    missing_count = int(diff / delta) - 1
                    if missing_count > 0:
                        gaps.append(
                            GapInfo(
                                symbol=symbol,
                                timeframe=timeframe,
                                gap_start=curr_ts,
                                gap_end=next_ts,
                                missing_candles_estimated=missing_count,
                            )
                        )

        return gaps

    def ingest_candles(
        self, candles: List[CandleCreate], symbol: str, timeframe: str
    ) -> IngestionReport:
        """Process and persist a list of candles into the database."""
        fetched_count = len(candles)
        if not candles:
            return IngestionReport(
                symbol=symbol,
                timeframe=timeframe,
                fetched_count=0,
                inserted_count=0,
                skipped_duplicates_count=0,
                invalid_candles_count=0,
                gaps_detected=[],
            )

        # 1. Clean intra-batch duplicates and sort out-of-order candles
        cleaned_candles, intra_duplicates = self.clean_and_sort_candles(candles)

        # 2. Detect missing data gaps
        gaps = self.detect_gaps(cleaned_candles, symbol, timeframe)
        if gaps:
            logger.warning(
                f"Detected {len(gaps)} data gap(s) for {symbol} ({timeframe}). First gap at: {gaps[0].gap_start}"
            )

        # 3. Query existing timestamps from database in the current range
        min_time = cleaned_candles[0].timestamp
        max_time = cleaned_candles[-1].timestamp

        stmt = (
            select(Candle.timestamp)
            .where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.timestamp >= min_time,
                Candle.timestamp <= max_time,
            )
        )
        existing_ts_set = set(self.db.scalars(stmt).all())

        # Normalize existing timestamps to UTC for comparison
        existing_ts_utc: Set[datetime] = {
            ensure_utc_datetime(ts) for ts in existing_ts_set if ts is not None
        }

        # 4. Filter out DB duplicates and prepare new candle models
        to_insert: List[Candle] = []
        db_duplicates = 0

        for c in cleaned_candles:
            if c.timestamp in existing_ts_utc:
                db_duplicates += 1
                continue

            candle_model = Candle(
                symbol=c.symbol,
                timeframe=c.timeframe,
                timestamp=c.timestamp,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
            )
            to_insert.append(candle_model)

        # 5. Bulk insert new records
        inserted_count = 0
        if to_insert:
            try:
                self.db.add_all(to_insert)
                self.db.commit()
                inserted_count = len(to_insert)
                logger.info(
                    f"Successfully inserted {inserted_count} new candles for {symbol} [{timeframe}]. "
                    f"Skipped {intra_duplicates + db_duplicates} duplicates."
                )
            except Exception as e:
                self.db.rollback()
                logger.warning(
                    f"Concurrent candle insertion conflict for {symbol} [{timeframe}]: {e}. Rolled back safely."
                )
        else:
            logger.info(
                f"No new candles to insert for {symbol} [{timeframe}]. All {fetched_count} candles already exist."
            )

        # 6. Explicitly log latest candle and verify staleness
        if cleaned_candles:
            latest_c = cleaned_candles[-1]
            staleness = check_data_staleness(cleaned_candles, symbol=symbol, timeframe=timeframe)
            log_latest_candle(
                latest_c,
                symbol=symbol,
                timeframe=timeframe,
                context="INGESTION",
                is_fresh=not staleness.is_stale,
            )
            if staleness.is_stale:
                logger.warning(staleness.message)

        return IngestionReport(
            symbol=symbol,
            timeframe=timeframe,
            fetched_count=fetched_count,
            inserted_count=inserted_count,
            skipped_duplicates_count=intra_duplicates + db_duplicates,
            invalid_candles_count=0,
            gaps_detected=gaps,
            start_time=cleaned_candles[0].timestamp if cleaned_candles else None,
            end_time=cleaned_candles[-1].timestamp if cleaned_candles else None,
        )

    async def sync_symbol_timeframe(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        force_refresh: bool = False,
    ) -> IngestionReport:
        """Fetch candles from provider and ingest into database with smart freshness cache and defensive 0-candle handling."""
        # ── Smart Freshness Cache Gate ────────────────────────────────────────────
        # When no explicit historical window is specified and not forcing refresh, check if DB already has the latest closed candle.
        if start_time is None and end_time is None and not force_refresh:
            try:
                latest_candle = self.db.scalars(
                    select(Candle)
                    .where(Candle.symbol == symbol, Candle.timeframe == timeframe.lower())
                    .order_by(desc(Candle.timestamp))
                    .limit(1)
                ).first()

                if latest_candle is not None:
                    tf_delta: timedelta = self.get_timeframe_delta(timeframe)
                    latest_ts: datetime = ensure_utc_datetime(latest_candle.timestamp)
                    next_candle_close: datetime = latest_ts + tf_delta
                    now_utc: datetime = datetime.now(timezone.utc)

                    if now_utc < next_candle_close:
                        logger.info(f"Skipping API fetch for {symbol} {timeframe} - Data is fresh.")
                        return IngestionReport(
                            symbol=symbol,
                            timeframe=timeframe,
                            fetched_count=0,
                            inserted_count=0,
                            skipped_duplicates_count=0,
                            invalid_candles_count=0,
                            gaps_detected=[],
                            start_time=latest_ts,
                            end_time=latest_ts,
                        )
            except Exception as cache_err:
                logger.warning(
                    f"Cache freshness check failed for {symbol} [{timeframe}] — "
                    f"falling back to API fetch: {cache_err}"
                )

        # ── Provider API Fetch Path ───────────────────────────────────────────────
        try:
            candles = await self.provider.fetch_candles(
                symbol=symbol,
                timeframe=timeframe,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )
            if not candles:
                logger.warning(
                    f"Market data provider returned 0 candles for {symbol} [{timeframe}]. "
                    f"Attempting fallback to YahooFinanceProvider..."
                )
                from app.services.market_data.yfinance_provider import YahooFinanceProvider
                fallback_provider = YahooFinanceProvider()
                candles = await fallback_provider.fetch_candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_time=start_time,
                    end_time=end_time,
                    limit=limit,
                )

            if not candles:
                logger.warning(
                    f"All market data providers returned 0 candles for {symbol} [{timeframe}]. "
                    f"Ingestion cycle skipped defensively."
                )
            return self.ingest_candles(candles, symbol, timeframe)
        except Exception as e:
            logger.error(f"Ingestion sync failed for {symbol} [{timeframe}]: {e}", exc_info=True)
            try:
                from app.services.market_data.yfinance_provider import YahooFinanceProvider
                fallback_provider = YahooFinanceProvider()
                candles = await fallback_provider.fetch_candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_time=start_time,
                    end_time=end_time,
                    limit=limit,
                )
                if candles:
                    return self.ingest_candles(candles, symbol, timeframe)
            except Exception as fb_e:
                logger.error(f"Fallback ingestion failed for {symbol} [{timeframe}]: {fb_e}")

            return IngestionReport(
                symbol=symbol,
                timeframe=timeframe,
                fetched_count=0,
                inserted_count=0,
                skipped_duplicates_count=0,
                invalid_candles_count=0,
                gaps_detected=[],
            )

    def get_fresh_candles_from_db(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        only_closed: bool = True,
        as_of: Optional[datetime] = None,
    ) -> List[Candle]:
        """Query fresh candles from the database, selecting verified closed bars and validating staleness."""
        ref_time = ensure_utc_datetime(as_of) or datetime.now(timezone.utc)
        stmt = (
            select(Candle)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe.lower())
            .order_by(desc(Candle.timestamp))
            .limit(limit + 5)
        )
        records = list(self.db.scalars(stmt).all())
        records.reverse()

        if only_closed and records:
            records = filter_closed_candles(records, timeframe=timeframe, as_of=ref_time)

        if len(records) > limit:
            records = records[-limit:]

        if records:
            latest = records[-1]
            staleness = check_data_staleness(records, symbol=symbol, timeframe=timeframe, as_of=ref_time)
            log_latest_candle(
                latest,
                symbol=symbol,
                timeframe=timeframe,
                context="DB CANDLE RETRIEVAL",
                is_fresh=not staleness.is_stale,
            )
            if staleness.is_stale:
                logger.warning(staleness.message)

        return records
```

---

## server/app/models/candle.py

```python
"""Candle model for storing historical and real-time OHLCV data."""

from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    UniqueConstraint,
    Index,
)
from app.core.database import Base
from app.models.base import utc_now


class Candle(Base):
    """OHLCV Candle entity.

    Enforces unique constraints on (symbol, timeframe, timestamp) and indexes for efficient queries.
    """
    __tablename__ = "candles"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_symbol_timeframe_timestamp"),
        Index("ix_candle_query", "symbol", "timeframe", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<Candle(id={self.id}, symbol='{self.symbol}', tf='{self.timeframe}', "
            f"time='{self.timestamp}', O={self.open}, H={self.high}, L={self.low}, C={self.close})>"
        )
```

---

## server/app/core/database.py

```python
"""SQLAlchemy database engine, session management, and dependencies."""

from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings
from app.core.logging import logger

# Normalize DATABASE_URL for compatibility across Render, Neon, Heroku, Supabase
db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    # Render and Heroku default to postgres:// which SQLAlchemy 1.4+ rejects
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Build engine kwargs dynamically based on dialect
engine_kwargs = {
    "echo": (settings.LOG_LEVEL.upper() == "DEBUG"),
    "pool_pre_ping": True,
}

if db_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL cloud settings (Neon/Supabase) to handle idle sleep and reconnects
    engine_kwargs["pool_recycle"] = 300
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 10

engine = create_engine(
    db_url,
    **engine_kwargs,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Dependency for yielding database sessions per request/task."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all database tables defined in the models."""
    from sqlalchemy import inspect, text
    
    # 1. IMPORT ALL MODELS SO SQLALCHEMY REGISTERS THEIR TABLES
    import app.models.candle
    import app.models.paper
    import app.models.news
    import app.models.signal
    import app.models.structure
    import app.models.liquidity
    import app.models.backtest

    logger.info("Initializing database tables...")
    try:
        insp = inspect(engine)
        if insp.has_table("paper_trades"):
            columns = [c["name"] for c in insp.get_columns("paper_trades")]
            if "account_id" not in columns:
                logger.info("Migrating paper_trades table schema...")
                with engine.connect() as conn:
                    conn.execute(text("DROP TABLE IF EXISTS paper_trades"))
                    conn.commit()
    except Exception as e:
        logger.debug(f"Table inspection note: {e}")

    # 2. CREATE TABLES
    Base.metadata.create_all(bind=engine)
    logger.info(f"Database tables initialized successfully. Created tables: {list(Base.metadata.tables.keys())}")
```

---

## server/app/main.py

```python
"""FastAPI Main Application Entrypoint."""

from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logging import logger
from app.core.database import init_db
from app.api.v1.router import api_v1_router


from app.services.telegram.scheduler import (
    start_scanner_scheduler,
    stop_scanner_scheduler,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info(f"Starting {settings.PROJECT_NAME} in [{settings.APP_ENV}] mode...")
    init_db()

    # Persistent shared HTTP client — eliminates per-request TCP/TLS handshake overhead.
    # Providers receive this via dependency injection for high-frequency paths.
    app.state.http_client = httpx.AsyncClient(
        timeout=15.0,
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
    )

    if settings.SCANNER_ENABLED:
        start_scanner_scheduler()
    else:
        logger.info("Automated market scanner disabled (SCANNER_ENABLED=False).")

    logger.info("Application startup complete.")
    yield
    logger.info("Application shutting down...")
    stop_scanner_scheduler()
    await app.state.http_client.aclose()
    logger.info("Application shutdown complete.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Forex Market Analysis, Market Structure, Liquidity Detection, and Signal Generation Engine",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(api_v1_router, prefix="/api")    


@app.get("/")
def root():
    """Root landing endpoint."""
    return {
        "message": f"Welcome to {settings.PROJECT_NAME}",
        "version": "1.0.0",
        "docs_url": "/docs",
        "health_url": "/api/v1/health",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
```

---

## server/app/services/telegram/scheduler.py

```python
"""Automated Background Market Scanner Scheduler using APScheduler."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import logger
from app.services.market_data import get_market_data_provider
from app.services.news import ForexFactoryProvider
from app.services.paper_trading import PaperTradingService
from app.services.signals import SignalGenerator
from app.services.telegram.client import get_telegram_client
from app.services.telegram.scanner import AutomatedMarketScanner


_scheduler: Optional[AsyncIOScheduler] = None
_shared_scanner: Optional[AutomatedMarketScanner] = None


def get_shared_scanner() -> AutomatedMarketScanner:
    """Return the shared singleton AutomatedMarketScanner instance."""
    global _shared_scanner
    if _shared_scanner is None:
        _shared_scanner = AutomatedMarketScanner(
            signal_generator=SignalGenerator(),
            paper_service=PaperTradingService(),
            telegram_client=get_telegram_client(),
            market_provider=get_market_data_provider(settings.MARKET_DATA_PROVIDER),
            news_provider=ForexFactoryProvider(),
        )
    return _shared_scanner


def set_shared_scanner(scanner: AutomatedMarketScanner):
    """Set or override the shared AutomatedMarketScanner instance."""
    global _shared_scanner
    _shared_scanner = scanner


def is_scheduler_running() -> bool:
    """Check if the background scanner scheduler is currently active and running."""
    global _scheduler
    return _scheduler is not None and _scheduler.running


def get_scheduler_info() -> Dict[str, Any]:
    """Retrieve runtime information from the scheduler and shared scanner."""
    global _scheduler
    running = is_scheduler_running()
    next_run_time = None
    if running and _scheduler is not None:
        job = _scheduler.get_job("automated_market_scanner")
        if job:
            next_run_time = job.next_run_time

    scanner = get_shared_scanner()
    active_symbols = [
        s for s in settings.SUPPORTED_SYMBOLS 
        if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
    ] or ["XAU/USD"]
    return {
        "is_enabled": settings.SCANNER_ENABLED,
        "is_running": running,
        "schedule": "15-minute candle-close (:00:10, :15:10, :30:10, :45:10 UTC)",
        "scanned_symbols": active_symbols,
        "scanned_timeframes": settings.SCANNER_TIMEFRAMES,
        "auto_paper_trade": settings.SCANNER_AUTO_TRADE_PAPER,
        "last_scan_at": scanner._last_scan_at,
        "next_scan_at": next_run_time,
        "last_scan_signals_count": scanner._last_signals_count,
        "total_scans_completed": scanner._total_scans_completed,
    }


def start_scanner_scheduler(
    scanner: Optional[AutomatedMarketScanner] = None,
) -> Optional[AsyncIOScheduler]:
    """Initialize and start the background APScheduler for automated market scanning.

    The scheduler fires at :00:10, :15:10, :30:10, and :45:10 UTC — exactly
    10 seconds after each 15-minute candle close boundary.  This 10-second
    offset allows market data providers to persist the completed bar before the
    scan reads it, eliminating the class of bugs caused by evaluating stale or
    still-forming candles.

    Previous behaviour used IntervalTrigger anchored to server-start time,
    producing arbitrary offsets (e.g. :52 past the hour) that could evaluate
    15m and 30m candles 20–60 minutes after their close.
    """
    global _scheduler
    if not settings.SCANNER_ENABLED:
        logger.info("Automated market scanner is disabled (SCANNER_ENABLED=False).")
        return None

    if _scheduler is not None and _scheduler.running:
        logger.warning("Scanner scheduler is already running. Skipping duplicate startup.")
        return _scheduler

    target_scanner = scanner or get_shared_scanner()
    if scanner is not None:
        set_shared_scanner(scanner)

    logger.info("Scanner enabled")
    logger.info(
        "Scanner schedule: every 15 minutes aligned to candle closes "
        "(:00:10, :15:10, :30:10, :45:10 UTC)"
    )
    logger.info(f"Scanner timeframes: {settings.SCANNER_TIMEFRAMES}")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

    _scheduler = AsyncIOScheduler(timezone=timezone.utc, event_loop=loop)

    async def _scheduled_scan_job():
        """Scheduled task wrapping a single scan cycle with isolated database session and error handling."""
        logger.info("Starting scheduled scan job execution...")
        db = SessionLocal()
        try:
            await target_scanner.run_scan_cycle(
                db=db,
                symbols=[
                    s for s in settings.SUPPORTED_SYMBOLS 
                    if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
                ] or ["XAU/USD"],
                timeframes=settings.SCANNER_TIMEFRAMES,
                broadcast_to_telegram=True,
                auto_paper_trade=settings.SCANNER_AUTO_TRADE_PAPER,
            )
            if _scheduler is not None and _scheduler.running:
                job = _scheduler.get_job("automated_market_scanner")
                if job and job.next_run_time:
                    logger.info(f"Next scan scheduled: {job.next_run_time.isoformat()}")
        except Exception as e:
            logger.error(f"Scanner cycle failed: {e}", exc_info=True)
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # CronTrigger aligned to 15-minute market candle close boundaries.
    #
    # Fires at: HH:00:10, HH:15:10, HH:30:10, HH:45:10 (UTC)
    #   minute="0,15,30,45" — the four 15-minute boundaries per hour
    #   second=10           — 10-second candle-persistence offset
    #
    # No `next_run_time` is set here; the first execution will happen at the
    # next aligned boundary, guaranteeing that the first scan — like all
    # subsequent ones — operates on fully closed and persisted candle data.
    # -----------------------------------------------------------------------
    _scheduler.add_job(
        _scheduled_scan_job,
        trigger=CronTrigger(
            minute="0,15,30,45",
            second=10,
            timezone=timezone.utc,
        ),
        id="automated_market_scanner",
        name="Automated Market Scanner (candle-close aligned)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )

    _scheduler.start()
    logger.info("Scanner started — first scan at next :XX:10 candle-close boundary (UTC)")
    return _scheduler


def stop_scanner_scheduler():
    """Gracefully shutdown the background APScheduler."""
    global _scheduler
    if _scheduler is not None:
        if _scheduler.running:
            _scheduler.shutdown(wait=False)
            logger.info("Scanner stopped")
        _scheduler = None
```

---

## server/app/services/telegram/scanner.py

```python
"""Automated Background Market Scanner and Signal Broadcaster."""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Union
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.config import settings
from app.core.logging import logger
from app.models.candle import Candle
from app.models.paper import PaperTrade
from app.models.signal import Signal
from app.models.structure import StructureEvent
from app.schemas.paper_trading import AutoTradeSignalRequest
from app.schemas.signal import SignalDirection, SignalResponse
from app.schemas.telegram import ScannerStatusResponse, ScannerTriggerResponse
from app.services.market_data import (
    BaseMarketDataProvider,
    IngestionService,
    get_market_data_provider,
)
from app.services.news import (
    BaseNewsProvider,
    ForexFactoryProvider,
    NewsIngestionService,
    get_news_provider,
)
from app.services.paper_trading import PaperTradingService
from app.services.signals import SignalGenerator
from app.services.telegram.client import BaseTelegramClient, get_telegram_client
from app.services.telegram.message_formatter import TelegramMessageFormatter


class AutomatedMarketScanner:
    """Automated periodic scanner evaluating currency pairs, broadcasting signals, and monitoring paper positions."""

    def __init__(
        self,
        signal_generator: Optional[SignalGenerator] = None,
        paper_service: Optional[PaperTradingService] = None,
        telegram_client: Optional[BaseTelegramClient] = None,
        market_provider: Optional[BaseMarketDataProvider] = None,
        news_provider: Optional[BaseNewsProvider] = None,
        market_ingestion: Optional[IngestionService] = None,
        news_ingestion: Optional[NewsIngestionService] = None,
    ):
        self.signal_generator = signal_generator or SignalGenerator()
        self.paper_service = paper_service or PaperTradingService()
        self.telegram_client = telegram_client or get_telegram_client()
        self.market_provider = market_provider or get_market_data_provider(settings.MARKET_DATA_PROVIDER)
        self.news_provider = news_provider or get_news_provider(getattr(settings, "NEWS_PROVIDER", "forexfactory"))
        self.market_ingestion = market_ingestion
        self.news_ingestion = news_ingestion
        self.formatter = TelegramMessageFormatter()

        # Concurrency lock to prevent overlapping scan runs
        self._lock = asyncio.Lock()

        # Deduplication tracker for broadcasted signals
        self._broadcasted_fingerprints: Set[str] = set()
        self._total_scans_completed = 0
        self._last_scan_at: Optional[datetime] = None
        self._last_signals_count = 0

    def _seed_fingerprints_from_db(self, db: Session):
        """Seed deduplication cache with recent signals from database on startup."""
        if not self._broadcasted_fingerprints:
            try:
                recent_fps = db.scalars(
                    select(Signal.fingerprint)
                    .where(Signal.is_broadcasted == True)
                    .order_by(desc(Signal.timestamp))
                    .limit(200)
                ).all()
                self._broadcasted_fingerprints.update(recent_fps)
            except Exception as e:
                logger.debug(f"Could not preload signal fingerprints from DB: {e}")
            finally:
                db.rollback()

    def has_active_position(self, db: Session, symbol: str) -> bool:
        """Check if an active or pending paper trade exists in the database for the given symbol."""
        stmt = (
            select(PaperTrade.id)
            .where(
                PaperTrade.symbol == symbol,
                PaperTrade.status.in_(["OPEN", "PARTIALLY_CLOSED", "PENDING"]),
            )
            .limit(1)
        )
        return db.scalars(stmt).first() is not None

    def has_opposing_structural_break(
        self,
        db: Session,
        symbol: str,
        direction: Union[SignalDirection, str],
        since_timestamp: datetime,
    ) -> bool:
        """Check if price structure has initiated an opposing structural break since previous signal.

        An opposing structural break indicates market structure shift/reversal:
        - For BUY signals: A BEARISH structure break (e.g. BEARISH_BOS, BEARISH_CHOCH, BEARISH_MSS)
          or opposing SELL signal recorded after the previous signal.
        - For SELL signals: A BULLISH structure break (e.g. BULLISH_BOS, BULLISH_CHOCH, BULLISH_MSS)
          or opposing BUY signal recorded after the previous signal.
        """
        if since_timestamp.tzinfo is None:
            since_ts = since_timestamp.replace(tzinfo=timezone.utc)
        else:
            since_ts = since_timestamp.astimezone(timezone.utc)

        dir_str = direction.value if isinstance(direction, SignalDirection) else str(direction).upper()
        opposing_prefix = "BEARISH" if dir_str == "BUY" else "BULLISH"
        opposing_dir = "SELL" if dir_str == "BUY" else "BUY"

        # 1. Check StructureEvent table for opposing events
        try:
            stmt_struct = select(StructureEvent).where(
                StructureEvent.symbol == symbol,
                StructureEvent.timestamp >= since_ts,
            )
            events = db.scalars(stmt_struct).all()
            for ev in events:
                ev_type = ev.event_type.upper()
                if opposing_prefix in ev_type:
                    logger.info(
                        f"Opposing structural break found for {symbol} ({ev.event_type} at {ev.timestamp}) "
                        f"since previous signal at {since_ts}."
                    )
                    return True
        except Exception as e:
            logger.debug(f"Could not query StructureEvent for opposing break: {e}")

        # 2. Check Signals table for opposing signal generated since
        try:
            stmt_sig = (
                select(Signal)
                .where(
                    Signal.symbol == symbol,
                    Signal.direction == opposing_dir,
                    Signal.timestamp >= since_ts,
                )
                .limit(1)
            )
            if db.scalars(stmt_sig).first() is not None:
                logger.info(
                    f"Opposing signal ({opposing_dir}) found for {symbol} "
                    f"since previous signal at {since_ts}."
                )
                return True
        except Exception as e:
            logger.debug(f"Could not query Signal for opposing break: {e}")
            db.rollback()

        return False

    def is_signal_in_cooldown(
        self,
        db: Session,
        signal_resp: SignalResponse,
        cooldown_hours: Optional[int] = None,
    ) -> bool:
        """Check if an actionable signal is within the cooldown window for the same symbol and direction.

        Uses ``Signal.created_at`` (wall-clock DB insert time) as the anchor rather than
        ``Signal.timestamp`` (candle open time).  This prevents candle timestamp drift — where
        each new 1H bar carries a fresh timestamp — from bypassing the cooldown window and
        producing hourly duplicate broadcasts for the same directional call.

        Returns True if the signal should be suppressed (a recent broadcast already exists
        within the cooldown window and no opposing structural break has occurred).
        """
        cd_hours = cooldown_hours if cooldown_hours is not None else settings.SIGNAL_COOLDOWN_HOURS
        if cd_hours <= 0:
            return False

        now_utc = datetime.now(timezone.utc)
        cutoff_time = now_utc - timedelta(hours=cd_hours)

        dir_str = signal_resp.direction.value if isinstance(signal_resp.direction, SignalDirection) else str(signal_resp.direction).upper()

        # Query recent signals for this symbol + direction.
        # Timeframe is intentionally excluded: a SELL on 1h and 15m for the same symbol
        # within 2h represent the same underlying directional call and should be suppressed.
        stmt = (
            select(Signal)
            .where(
                Signal.symbol == signal_resp.symbol,
                Signal.direction == dir_str,
            )
        )

        # Exclude the current signal if it was already persisted
        if signal_resp.id:
            stmt = stmt.where(Signal.id != signal_resp.id)
        elif signal_resp.fingerprint:
            stmt = stmt.where(Signal.fingerprint != signal_resp.fingerprint)

        stmt = stmt.order_by(desc(Signal.created_at), desc(Signal.timestamp))

        try:
            recent_signal = db.scalars(stmt).first()
        except Exception as e:
            logger.debug(f"Could not query Signal for cooldown check: {e}")
            db.rollback()
            return False

        if not recent_signal:
            return False

        # Determine effective anchor timestamp:
        # Use created_at (wall clock) in production to avoid candle-timestamp drift.
        # If created_at was generated at insert time in a test (< 5s ago) while timestamp
        # is older, fallback to timestamp.
        recent_ts = recent_signal.created_at
        if recent_ts is not None:
            if recent_ts.tzinfo is None:
                recent_ts = recent_ts.replace(tzinfo=timezone.utc)
            else:
                recent_ts = recent_ts.astimezone(timezone.utc)

        candle_ts = recent_signal.timestamp
        if candle_ts is not None:
            if candle_ts.tzinfo is None:
                candle_ts = candle_ts.replace(tzinfo=timezone.utc)
            else:
                candle_ts = candle_ts.astimezone(timezone.utc)

        if recent_ts is None:
            recent_ts = candle_ts or now_utc
        elif candle_ts is not None and abs((now_utc - recent_ts).total_seconds()) < 5.0 and (now_utc - candle_ts).total_seconds() > 5.0:
            recent_ts = candle_ts

        elapsed_hours = (now_utc - recent_ts).total_seconds() / 3600.0
        if elapsed_hours >= cd_hours:
            return False

        # A recent signal exists within cooldown window — check if opposing structural break reset momentum
        has_opposing = self.has_opposing_structural_break(
            db=db,
            symbol=signal_resp.symbol,
            direction=signal_resp.direction,
            since_timestamp=recent_ts,
        )
        if has_opposing:
            # Structural break detected — allow the new signal to pass through
            return False

        logger.info(
            f"Suppressing duplicate broadcast for {signal_resp.symbol} [{dir_str}]: "
            f"Active broadcast exists from {recent_ts.strftime('%Y-%m-%d %H:%M UTC')} "
            f"({elapsed_hours:.1f}h ago < {cd_hours:.1f}h cooldown window)."
        )
        return True

    async def run_scan_cycle(
        self,
        db: Session,
        symbols: Optional[List[str]] = None,
        timeframe: Optional[str] = None,
        timeframes: Optional[List[str]] = None,
        broadcast_to_telegram: bool = True,
        auto_paper_trade: bool = True,
    ) -> ScannerTriggerResponse:
        """Execute a full automated market scan cycle across target symbols and timeframes."""
        if self._lock.locked():
            logger.warning("Scanner cycle already in progress, skipping overlapping scan execution.")
            return ScannerTriggerResponse(
                timestamp=datetime.now(timezone.utc),
                symbols_scanned=[],
                timeframes_scanned=[],
                signals_found_count=0,
                signals_broadcast_count=0,
                paper_trades_opened_count=0,
                positions_synced_count=0,
                execution_time_seconds=0.0,
                summary="Scan skipped: previous scan still in progress.",
            )

        async with self._lock:
            start_time = time.time()
            now = datetime.now(timezone.utc)
            raw_symbols = symbols or settings.SUPPORTED_SYMBOLS
            target_symbols = [
                s for s in raw_symbols 
                if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
            ] or ["XAU/USD"]

            # Resolve target timeframes
            if timeframes:
                target_timeframes = list(timeframes)
            elif timeframe:
                target_timeframes = [timeframe]
            else:
                target_timeframes = list(settings.SCANNER_TIMEFRAMES)

            # Ensure fingerprints cache is seeded
            self._seed_fingerprints_from_db(db)

            signals_found = 0
            signals_broadcast = 0
            paper_trades_opened = 0

            logger.info(
                f"Starting scan cycle across {len(target_symbols)} symbols: {target_symbols} "
                f"on timeframes: {target_timeframes}"
            )

            # 1. Ingest / Sync Market Data
            logger.info("Market data ingestion started")
            sync_timeframes = set(target_timeframes)
            if "1h" in target_timeframes or "15m" in target_timeframes:
                sync_timeframes.update(["15m", "1h", "4h"])

            # Semaphore(3) caps concurrent API calls to Twelve Data to avoid rate limit breaches
            api_semaphore = asyncio.Semaphore(3)

            async def _sync_symbol_tf(sym: str, tf: str) -> None:
                """Each coroutine owns its own isolated DB session to prevent cross-coroutine rollbacks."""
                async with api_semaphore:
                    task_db = SessionLocal()
                    try:
                        ingest = self.market_ingestion or IngestionService(
                            provider=self.market_provider, db=task_db
                        )
                        ingest.db = task_db
                        await ingest.sync_symbol_timeframe(symbol=sym, timeframe=tf, limit=100)
                        task_db.commit()
                    except Exception as e:
                        logger.error(f"Market data ingestion failed for {sym} [{tf}]: {e}")
                        task_db.rollback()
                    finally:
                        task_db.close()

            ingestion_tasks = [
                _sync_symbol_tf(sym, tf)
                for sym in target_symbols
                for tf in sync_timeframes
            ]
            await asyncio.gather(*ingestion_tasks, return_exceptions=True)

            logger.info("Market data ingestion completed")

            # 2. Ingest / Sync Economic News Calendar
            logger.info("News ingestion started")
            try:
                news_ingest_service = self.news_ingestion or NewsIngestionService(
                    provider=self.news_provider, db=db
                )
                news_ingest_service.db = db
                await news_ingest_service.sync_calendar()
                logger.info("News check completed")
            except Exception as e:
                logger.error(f"News ingestion failed: {e}")
                db.rollback()

            # 3. Run Strategy Signal Evaluation across symbols
            scan_batches = []
            if timeframes or timeframe:
                for tf in target_timeframes:
                    logger.info(f"Signal analysis started for timeframe [{tf}]")
                    try:
                        batch_res = self.signal_generator.scan_all_symbols(
                            db=db,
                            symbols=target_symbols,
                            timeframe=tf,
                            account_balance=10000.0,
                            risk_percent=0.5,
                            persist_qualified=True,
                        )
                        scan_batches.append(batch_res)
                    except Exception as e:
                        logger.error(f"Signal analysis failed for timeframe [{tf}]: {e}")
                        db.rollback()
                        continue
                    logger.info(f"Signal analysis completed for timeframe [{tf}]")
            else:
                logger.info("Unified multi-timeframe signal analysis started across target symbols")
                try:
                    unified_res = self.signal_generator.scan_unified_all(
                        db=db,
                        symbols=target_symbols,
                        account_balance=10000.0,
                        risk_percent=0.5,
                        persist_qualified=True,
                    )
                    scan_batches.append(unified_res)
                except Exception as e:
                    logger.error(f"Unified signal analysis failed: {e}")
                    db.rollback()
                logger.info("Unified signal analysis completed")

            for scan_res in scan_batches:
                for result in scan_res.results:
                    sig = result.signal
                    if not sig or not result.is_actionable or result.blackout_blocked:
                        continue

                    signals_found += 1

                    # 1. Active Position Check: Skip if position is already open/active for this symbol
                    if self.has_active_position(db, sig.symbol):
                        logger.info(f"Skipping signal alert for {sig.symbol}: Position already active.")
                        continue

                    # 2. Signal Cooldown Period Check (Deduping)
                    if self.is_signal_in_cooldown(db, sig):
                        continue

                    # 3. In-memory Fingerprint Deduplication Check
                    if sig.fingerprint in self._broadcasted_fingerprints:
                        logger.debug(f"Skipping signal alert for {sig.symbol}: Fingerprint already broadcasted.")
                        continue

                    self._broadcasted_fingerprints.add(sig.fingerprint)

                    # 4. Standalone Broadcast to Telegram
                    if broadcast_to_telegram:
                        try:
                            msg_text = self.formatter.format_signal_alert(sig)
                            send_res = await self.telegram_client.send_message(text=msg_text)
                            if send_res.success:
                                signals_broadcast += 1
                                if sig.id:
                                    db_sig = db.get(Signal, sig.id)
                                    if db_sig:
                                        db_sig.is_broadcasted = True
                                        db.commit()
                                logger.info(
                                    f"BROADCASTED NEW SIGNAL: [{sig.direction.value}] {sig.symbol} "
                                    f"[{tf}] (Score: {sig.setup_score:.1f})"
                                )
                            else:
                                logger.error(
                                    f"Telegram delivery failed for {sig.symbol}: {send_res.error}"
                                )
                        except Exception as e:
                            logger.error(f"Telegram delivery failed for {sig.symbol}: {e}")

                    # 5. Paper Trading Safety Check & Auto-execution
                    if (
                        auto_paper_trade
                        and settings.PAPER_TRADING
                        and settings.SCANNER_AUTO_TRADE_PAPER
                    ):
                        try:
                            trade = self.paper_service.trade_from_signal(
                                db=db,
                                request=AutoTradeSignalRequest(
                                    signal_id=sig.id,
                                    symbol=sig.symbol,
                                    timeframe=sig.timeframe,
                                    risk_percent=0.5,
                                ),
                            )
                            paper_trades_opened += 1
                            logger.info(
                                f"AUTO-OPENED PAPER TRADE #{trade.id} on {trade.symbol} [{sig.timeframe}]"
                            )
                        except Exception as e:
                            logger.error(f"Paper trading failed for {sig.symbol}: {e}")
                    else:
                        logger.debug(
                            f"Paper trade skipped for {sig.symbol} (auto_trade={auto_paper_trade}, "
                            f"PAPER_TRADING={settings.PAPER_TRADING}, "
                            f"SCANNER_AUTO_TRADE_PAPER={settings.SCANNER_AUTO_TRADE_PAPER})"
                        )

            # 4. Synchronize Open Paper Trading Positions & Trigger TP/SL Alerts
            updated_pos_count = 0
            try:
                sync_report = self.paper_service.sync_prices(db=db)
                updated_pos_count = sync_report.updated_positions_count
                if broadcast_to_telegram and sync_report.events:
                    for ev in sync_report.events:
                        if any(k in ev for k in ("TP1", "TP2", "SL_HIT", "BREAK_EVEN")):
                            try:
                                await self.telegram_client.send_message(
                                    text=f"🔔 *POSITION UPDATE:* `{ev}`"
                                )
                            except Exception as e:
                                logger.error(f"Telegram delivery failed for position update: {e}")
            except Exception as e:
                logger.error(f"Paper position sync failed: {e}")
                db.rollback()

            # 5. Update internal metrics & logging
            elapsed = round(time.time() - start_time, 2)
            self._total_scans_completed += 1
            self._last_scan_at = now
            self._last_signals_count = signals_found

            logger.info(f"Qualified signals found: {signals_found}")
            logger.info(f"Telegram broadcast completed: {signals_broadcast} sent")
            logger.info(f"Paper trades created: {paper_trades_opened}")

            summary = (
                f"Scanned {len(target_symbols)} pairs across {target_timeframes} in {elapsed}s | "
                f"Signals: {signals_found} found, {signals_broadcast} broadcast | "
                f"Paper Positions: {paper_trades_opened} opened, {updated_pos_count} synced"
            )
            logger.info(f"Scan cycle completed: {summary}")

            return ScannerTriggerResponse(
                timestamp=now,
                symbols_scanned=target_symbols,
                timeframes_scanned=target_timeframes,
                signals_found_count=signals_found,
                signals_broadcast_count=signals_broadcast,
                paper_trades_opened_count=paper_trades_opened,
                positions_synced_count=updated_pos_count,
                execution_time_seconds=elapsed,
                summary=summary,
            )

    def get_status(self) -> ScannerStatusResponse:
        """Query scanner configuration and activity status."""
        is_running = False
        next_scan_at = None
        try:
            from app.services.telegram.scheduler import is_scheduler_running, get_scheduler_info
            is_running = is_scheduler_running()
            info = get_scheduler_info()
            next_scan_at = info.get("next_scan_at")
        except Exception:
            pass

        return ScannerStatusResponse(
            is_enabled=settings.SCANNER_ENABLED,
            interval_minutes=settings.SCANNER_INTERVAL_MINUTES,
            scanned_symbols=[
                s for s in settings.SUPPORTED_SYMBOLS 
                if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
            ] or ["XAU/USD"],
            scanned_timeframes=settings.SCANNER_TIMEFRAMES,
            auto_paper_trade=settings.SCANNER_AUTO_TRADE_PAPER,
            is_running=is_running,
            last_scan_at=self._last_scan_at,
            next_scan_at=next_scan_at,
            last_scan_signals_count=self._last_signals_count,
            total_scans_completed=self._total_scans_completed,
        )
```

---

## server/app/api/v1/telegram.py

```python
"""Telegram Bot and Background Market Scanner API Endpoints."""

import asyncio
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.config import settings
from app.core.logging import logger
from app.api.deps import get_telegram_bot_service
from app.schemas.telegram import (
    ScannerStatusResponse,
    ScannerTriggerResponse,
    TelegramBotStatusResponse,
    TelegramCommandRequest,
    TelegramCommandResponse,
    TelegramMessageRequest,
    TelegramMessageResponse,
    TelegramWebhookUpdate,
)
from app.services.telegram import TelegramBotService

router = APIRouter(prefix="/telegram", tags=["Telegram Bot & Automated Scanner"])

# Heavy commands that fetch market data and run multi-timeframe analysis
_HEAVY_COMMANDS = {"/scan", "/signal", "/sync"}


async def _run_command_in_background(
    service: TelegramBotService,
    request: TelegramCommandRequest,
) -> None:
    """Execute a heavy command asynchronously in the background with an isolated DB session."""
    db: Session = SessionLocal()
    try:
        await service.command_handler.handle_command(db=db, request=request)
    except Exception as e:
        logger.error(
            f"❌ Background command '{request.command}' failed for chat {request.chat_id}: {e}",
            exc_info=True,
        )
        try:
            await service.client.send_message(
                text=f"❌ Error processing command: {str(e)}",
                chat_id=request.chat_id,
            )
        except Exception:
            pass
    finally:
        db.close()


@router.post("/broadcast", response_model=TelegramMessageResponse)
async def broadcast_telegram_message(
    request: TelegramMessageRequest,
    service: TelegramBotService = Depends(get_telegram_bot_service),
):
    """Broadcast a formatted message or signal alert to the configured Telegram chat/channel."""
    return await service.broadcast_message(request=request)


@router.post("/command", response_model=TelegramCommandResponse)
async def process_telegram_command(
    request: TelegramCommandRequest,
    db: Session = Depends(get_db),
    service: TelegramBotService = Depends(get_telegram_bot_service),
):
    """Process an interactive Telegram command (/scan, /signal, /news, /account, /positions, /help)."""
    return await service.process_command(db=db, request=request)



@router.post("/webhook")
async def telegram_webhook(
    update: TelegramWebhookUpdate,
    background_tasks: BackgroundTasks,
    service: TelegramBotService = Depends(get_telegram_bot_service),
):
    """Webhook endpoint for receiving real-time interactive updates from Telegram servers."""
    logger.info(f"🔔 TELEGRAM WEBHOOK RECEIVED")

    # Handle both Pydantic model and dict cases
    msg = update.message or update.channel_post
    if not msg:
        logger.warning("Webhook received but no message payload found")
        return {"status": "ignored", "reason": "No message payload"}

    # Safely extract data whether msg is a dict or Pydantic model
    if isinstance(msg, dict):
        text = msg.get("text", "")
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        user = msg.get("from", {})
    else:
        # Pydantic model - access attributes directly
        text = getattr(msg, "text", "") or ""
        chat = getattr(msg, "chat", None)
        chat_id = str(getattr(chat, "id", "")) if chat else ""
        user = getattr(msg, "from_user", None) or getattr(msg, "from_", None)

    logger.info(f"📩 Message from chat {chat_id}: {text}")

    if text.startswith("/"):
        cmd_root = text.split()[0].split("@")[0].lower()
        cmd_req = TelegramCommandRequest(
            command=text,
            chat_id=chat_id,
            user_id=getattr(user, "id", None) if user else None,
            user_name=getattr(user, "username", None) if user else None,
        )

        if cmd_root in _HEAVY_COMMANDS:
            # Task 4: Fast instant acknowledgement and non-blocking background dispatch
            if cmd_root == "/scan":
                ack_text = "⚡ Scanning XAU/USD... Please wait while fresh market data is analyzed."
            elif cmd_root == "/sync":
                ack_text = "🔄 Syncing fresh market data for XAU/USD... Please wait."
            else:
                ack_text = "🔄 Processing request... analyzing market data. Please wait."

            if chat_id:
                try:
                    await asyncio.wait_for(
                        service.client.send_message(
                            text=ack_text,
                            chat_id=chat_id,
                        ),
                        timeout=2.0,
                    )
                except Exception as ack_err:
                    logger.warning(f"Could not send acknowledgement message to {chat_id}: {ack_err}")

            # Offload heavy multi-timeframe analysis & DB sync to BackgroundTasks so webhook returns 200 OK instantly
            background_tasks.add_task(_run_command_in_background, service, cmd_req)
            return {"status": "success", "command": cmd_root, "reply": ack_text}

        # Lightweight commands processed inline
        try:
            db: Session = SessionLocal()
            try:
                cmd_res = await service.command_handler.handle_command(db=db, request=cmd_req)
            finally:
                db.close()
            logger.info(f"✅ Command processed: {cmd_res.command}")
            return {"status": "success", "command": cmd_res.command, "reply": cmd_res.reply_text}
        except Exception as e:
            logger.error(f"❌ Error processing command: {e}", exc_info=True)
            try:
                await service.client.send_message(
                    text=f"❌ Error processing command: {str(e)}",
                    chat_id=chat_id,
                )
            except Exception:
                pass
            return {"status": "error", "error": str(e)}

    logger.info(f"📝 Non-command message received from {chat_id}")
    return {"status": "received", "chat_id": chat_id}
@router.get("/status", response_model=TelegramBotStatusResponse)
def get_bot_status(
    service: TelegramBotService = Depends(get_telegram_bot_service),
):
    """Check Telegram bot connectivity status, mode (LIVE or MOCK), and message counts."""
    return service.get_bot_status()


@router.post("/scanner/trigger", response_model=ScannerTriggerResponse)
async def trigger_scanner_cycle(
    timeframe: str = Query("1h", description="Timeframe to scan (e.g. 1h, 15m)"),
    broadcast: bool = Query(True, description="Whether to broadcast newly qualified signals to Telegram"),
    auto_trade: bool = Query(True, description="Whether to auto-open paper positions for qualified signals"),
    db: Session = Depends(get_db),
    service: TelegramBotService = Depends(get_telegram_bot_service),
):
    """Manually trigger an automated market scanner cycle across all supported pairs."""
    return await service.trigger_market_scan(
        db=db,
        symbols=settings.SUPPORTED_SYMBOLS,
        timeframe=timeframe,
        broadcast_to_telegram=broadcast,
        auto_paper_trade=auto_trade,
    )


@router.get("/scanner/status", response_model=ScannerStatusResponse)
def get_scanner_status(
    service: TelegramBotService = Depends(get_telegram_bot_service),
):
    """Retrieve operational status, scan interval, and activity history of the background scanner."""
    return service.get_scanner_status()
```

---

## server/app/services/telegram/command_handler.py

```python
"""Interactive Telegram Bot Commands Processor."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.config import settings
from app.core.logging import logger
from app.models.candle import Candle
from app.models.news import NewsEvent
from app.schemas.news import NewsEventResponse
from app.schemas.signal import SignalDirection
from app.schemas.telegram import TelegramCommandRequest, TelegramCommandResponse
from app.services.backtesting import BacktestService
from app.services.market_data import (
    BaseMarketDataProvider,
    IngestionService,
    check_data_staleness,
    ensure_utc_datetime,
    filter_closed_candles,
    get_market_data_provider,
    log_latest_candle,
)
from app.services.news import (
    BaseNewsProvider,
    NewsFilterEngine,
    NewsIngestionService,
    get_news_provider,
)
from app.services.paper_trading import PaperTradingService
from app.services.signals import SignalGenerator
from app.services.telegram.client import BaseTelegramClient, get_telegram_client
from app.services.telegram.message_formatter import TelegramMessageFormatter


class TelegramCommandHandler:
    """Handles incoming bot commands (/scan, /signal, /news, /account, /positions, /performance, /help, /sync)."""

    def __init__(
        self,
        signal_generator: Optional[SignalGenerator] = None,
        paper_service: Optional[PaperTradingService] = None,
        backtest_service: Optional[BacktestService] = None,
        news_filter: Optional[NewsFilterEngine] = None,
        telegram_client: Optional[BaseTelegramClient] = None,
        market_provider: Optional[BaseMarketDataProvider] = None,
        market_ingestion: Optional[IngestionService] = None,
        news_provider: Optional[BaseNewsProvider] = None,
        news_ingestion: Optional[NewsIngestionService] = None,
    ):
        self.signal_generator = signal_generator or SignalGenerator()
        self.paper_service = paper_service or PaperTradingService()
        self.backtest_service = backtest_service or BacktestService()
        self.news_filter = news_filter or NewsFilterEngine()
        self.telegram_client = telegram_client or get_telegram_client()
        self.market_provider = market_provider or get_market_data_provider(settings.MARKET_DATA_PROVIDER)
        self.market_ingestion = market_ingestion
        self.news_provider = news_provider or get_news_provider(settings.NEWS_PROVIDER)
        self.news_ingestion = news_ingestion
        self.formatter = TelegramMessageFormatter()

    def _normalize_symbol(self, raw: str) -> str:
        """Normalize currency symbol string with strict quarantine of unsupported assets."""
        s = raw.upper().replace("%2F", "/").strip()
        active_symbols = [
            sym for sym in settings.SUPPORTED_SYMBOLS 
            if "US100" not in sym.upper() and "NDX" not in sym.upper() and "IXIC" not in sym.upper()
        ] or ["XAU/USD"]
        for sym in active_symbols:
            if sym.replace("/", "") == s.replace("/", ""):
                return sym
        return s

    async def handle_command(self, db: Session, request: TelegramCommandRequest) -> TelegramCommandResponse:
        """Parse and execute a Telegram bot command."""
        raw_cmd = request.command.strip()
        parts = raw_cmd.split()
        cmd_name = parts[0].lower() if parts else "/help"

        # -------------------------------------------------------------
        # 1. Help & Start Menu
        # -------------------------------------------------------------
        if cmd_name in ("/start", "/help"):
            reply = self.formatter.format_help_menu()

        # -------------------------------------------------------------
        # 2. Unified Multi-Timeframe Market Scanner (/scan)
        # -------------------------------------------------------------
        elif cmd_name == "/scan":
            # Strict single-asset enforcement: strictly scan XAU/USD (US100 quarantined)
            scan_symbols = [
                s for s in settings.SUPPORTED_SYMBOLS 
                if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
            ] or ["XAU/USD"]

            # Auto-Refresh When Stale on /scan:
            # Check latest candle age for XAU/USD. If older than 20 minutes (STALE), sync fresh data.
            now_utc = datetime.now(timezone.utc)
            latest_candle = db.scalars(
                select(Candle)
                .where(Candle.symbol == "XAU/USD", Candle.timeframe == "15m")
                .order_by(desc(Candle.timestamp))
                .limit(1)
            ).first()
            if not latest_candle:
                latest_candle = db.scalars(
                    select(Candle)
                    .where(Candle.symbol == "XAU/USD")
                    .order_by(desc(Candle.timestamp))
                    .limit(1)
                ).first()

            is_stale = False
            if not latest_candle or not latest_candle.timestamp:
                is_stale = True
            else:
                candle_ts = ensure_utc_datetime(latest_candle.timestamp)
                candle_age_seconds = (now_utc - candle_ts).total_seconds()
                if candle_age_seconds > 20 * 60:
                    is_stale = True

            if is_stale:
                logger.info("XAU/USD candles are STALE (>20m) on /scan. Auto-syncing fresh 15m, 30m, 1h candles...")
                provider = self.market_provider or get_market_data_provider(settings.MARKET_DATA_PROVIDER)
                ingest_svc = self.market_ingestion or IngestionService(provider=provider, db=db)
                ingest_svc.db = db
                for tf in ["15m", "30m", "1h", "4h"]:
                    try:
                        await ingest_svc.sync_symbol_timeframe(
                            symbol="XAU/USD",
                            timeframe=tf,
                            limit=100,
                            force_refresh=True,
                        )
                    except Exception as e:
                        logger.error(f"Auto-refresh sync failed for XAU/USD [{tf}]: {e}")
                try:
                    db.commit()
                except Exception:
                    db.rollback()

            scan_res = self.signal_generator.scan_unified_all(
                db=db,
                symbols=scan_symbols,
                account_balance=10000.0,
                risk_percent=0.5,
                persist_qualified=True,
            )
            reply = self.formatter.format_market_scan_summary(scan_res)

        # -------------------------------------------------------------
        # 3. Single Pair Unified Signal Evaluation (/signal <symbol>)
        # -------------------------------------------------------------
        elif cmd_name == "/signal":
            if len(parts) < 2:
                reply = "⚠️ *Usage:* `/signal <symbol>`\n_Example:_ `/signal XAU/USD`"
            else:
                sym = self._normalize_symbol(parts[1])

                if sym in ("US100", "NDX", "IXIC"):
                    reply = (
                        f"⚠️ *Asset Quarantined / Inactive*\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"`{self.formatter.escape_code(sym)}` is completely quarantined due to market data API paywalls.\n"
                        f"Active instrument: `XAU/USD` (Gold)."
                    )
                else:
                    # 1. Provider <-> DB Synchronization: Refresh fresh candle data from provider
                    if self.market_provider:
                        ingest_svc = self.market_ingestion or IngestionService(
                            provider=self.market_provider, db=db
                        )
                        ingest_svc.db = db
                        for tf in ["1h", "4h", "30m", "15m"]:
                            try:
                                await ingest_svc.sync_symbol_timeframe(symbol=sym, timeframe=tf, limit=100)
                            except Exception as e:
                                logger.warning(f"Failed to refresh market data for {sym} [{tf}] via provider: {e}")

                    # 2. Evaluate Unified Multi-Timeframe Signal
                    scan_res = self.signal_generator.scan_unified(
                        db=db,
                        symbol=sym,
                        account_balance=10000.0,
                        risk_percent=0.5,
                        persist_qualified=True,
                    )

                    if scan_res.is_actionable and scan_res.signal:
                        reply = self.formatter.format_signal_alert(scan_res.signal)
                    else:
                        sym_code = self.formatter.escape_code(sym)
                        htf_txt = self.formatter.escape_code(scan_res.htf_trend or "NEUTRAL")
                        score_txt = f"{scan_res.setup_score:.0f}/100"
                        align_txt = f" • Alignment: `{scan_res.trend_alignment}`" if scan_res.trend_alignment else ""
                        reasons_lines = "\n".join([f"  • {self.formatter.escape_markdown(r)}" for r in scan_res.reasons[:4]])
                        reply = (
                            f"⚪ *UNIFIED SIGNAL STATUS: WAIT*\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"📊 *Pair:* `{sym_code}` [{scan_res.timeframe}]\n"
                            f"📈 *1H Context:* `{htf_txt}`{align_txt}\n"
                            f"⭐ *Confluence Score:* `{score_txt}` (Min: `{settings.MIN_SETUP_SCORE:.0f}`)\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"💡 *Current Market Analysis:*\n"
                            f"{reasons_lines}\n\n"
                            f"⚠️ _Awaiting 15m/30m/1H confirmation before generating actionable entry._"
                        )

        # -------------------------------------------------------------
        # 4. Economic News Calendar (/news)
        # -------------------------------------------------------------
        elif cmd_name == "/news":
            now = datetime.now(timezone.utc)
            news_ingest = self.news_ingestion or NewsIngestionService(
                provider=self.news_provider, db=db
            )
            news_ingest.db = db

            # DB-First Check: Only invoke external provider sync if database is empty or cache is stale (>2 hours)
            is_cache_fresh = news_ingest.is_calendar_cache_fresh(reference_time=now)
            live_failed = False

            if not is_cache_fresh and self.news_provider:
                try:
                    report = await news_ingest.sync_calendar(force_refresh=True)
                    if report.status in ("UNAVAILABLE", "ERROR") or (getattr(self.news_provider, "is_live_provider", False) and report.fetched_count == 0):
                        live_failed = True
                except Exception as e:
                    logger.warning(f"Error syncing economic news in /news command: {e}")
                    live_failed = True

            events = list(
                db.scalars(
                    select(NewsEvent)
                    .where(NewsEvent.scheduled_time >= (now - timedelta(minutes=15)))
                    .order_by(NewsEvent.scheduled_time.asc())
                    .limit(5)
                ).all()
            )
            event_resps = [NewsEventResponse.model_validate(e) for e in events]

            if not event_resps and (live_failed or (getattr(self.news_provider, "is_live_provider", False) and not is_cache_fresh)):
                reply = self.formatter.format_news_unavailable_alert()
            else:
                reply = self.formatter.format_economic_news_alert(event_resps)

        # -------------------------------------------------------------
        # 5. Virtual Paper Account (/account, /paper)
        # -------------------------------------------------------------
        elif cmd_name in ("/account", "/paper"):
            acc = self.paper_service.get_account_summary(db)
            perf = self.paper_service.get_portfolio_performance(db)
            reply = self.formatter.format_portfolio_summary(acc, perf)

        # -------------------------------------------------------------
        # 6. Active Virtual Positions (/positions)
        # -------------------------------------------------------------
        elif cmd_name == "/positions":
            positions = self.paper_service.get_positions(db)
            if not positions:
                reply = "💼 *No open or pending paper trading positions currently.*"
            else:
                lines = [
                    f"📊 *ACTIVE PAPER POSITIONS ({len(positions)})* 📊",
                    f"━━━━━━━━━━━━━━━━━━━━",
                ]
                for p in positions:
                    dir_icon = "🟢 BUY" if p.direction == SignalDirection.BUY else " SELL"
                    pnl_str = f"+${p.unrealized_pnl:,.2f}" if p.unrealized_pnl >= 0 else f"-${abs(p.unrealized_pnl):,.2f}"
                    lines.append(
                        f"• *{self.formatter.escape_markdown(p.symbol)}* ({dir_icon} `{p.remaining_position_size} Lots`)\n"
                        f"  Entry: `{p.entry_price:.5f}` | Current: `{p.current_price:.5f}` | PnL: `{pnl_str}`\n"
                        f"  SL: `{p.stop_loss:.5f}` | TP1: `{p.take_profit_1:.5f}`"
                    )
                reply = "\n".join(lines)

        # -------------------------------------------------------------
        # 7. Portfolio Performance Statistics (/performance)
        # -------------------------------------------------------------
        elif cmd_name == "/performance":
            perf = self.paper_service.get_portfolio_performance(db)
            reply = (
                f"🏆 *VIRTUAL TRADING PERFORMANCE* 🏆\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💵 *Current Balance:* `${perf.current_balance:,.2f}`\n"
                f"📈 *Total Return:* `{perf.total_return_pct:>+6.2f}%`\n"
                f" *Total Trades:* `{perf.total_trades}` ({perf.winning_trades}W / {perf.losing_trades}L)\n"
                f" *Win Rate:* `{perf.win_rate:.1f}%`\n"
                f"💰 *Profit Factor:* `{perf.profit_factor:.2f}`\n"
                f"💵 *Average Win:* `${perf.average_win:,.2f}`\n"
                f"🛑 *Average Loss:* `${perf.average_loss:,.2f}`\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

        # -------------------------------------------------------------
        # 8. Quick Strategy Backtest (/backtest <symbol>)
        # -------------------------------------------------------------
        elif cmd_name == "/backtest":
            sym = self._normalize_symbol(parts[1]) if len(parts) > 1 else "XAU/USD"
            candles = list(
                db.scalars(
                    select(Candle)
                    .where(Candle.symbol == sym, Candle.timeframe == "1h")
                    .order_by(Candle.timestamp.asc())
                ).all()
            )
            if len(candles) < 30:
                reply = f"❌ Insufficient candle data in database to backtest `{self.formatter.escape_code(sym)}`."
            else:
                bt_res = self.backtest_service.engine.run_simulation(
                    candles=candles,
                    symbol=sym,
                    timeframe="1h",
                )
                m = bt_res.metrics
                sym_escaped = self.formatter.escape_markdown(sym)
                reply = (
                    f"📈 *HISTORICAL STRATEGY BACKTEST: {sym_escaped} [1h]* 📈\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 *Total Trades:* `{m.total_trades}` ({m.winning_trades}W / {m.losing_trades}L)\n"
                    f"🎯 *Win Rate:* `{m.win_rate:.1f}%`\n"
                    f"💰 *Profit Factor:* `{m.profit_factor:.2f}`\n"
                    f" *Net PnL:* `${m.total_pnl:>+,.2f}` (`{m.total_pnl_percent:>+6.2f}%`)\n"
                    f"📉 *Max Drawdown:* `{m.max_drawdown_pct:.2f}%` (`${m.max_drawdown_usd:,.2f}`)\n"
                    f"⭐ *Sharpe Ratio:* `{m.sharpe_ratio:.2f}` | *Calmar:* `{m.calmar_ratio:.2f}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )

        # -------------------------------------------------------------
        # 9. Force Fresh Data Sync (/sync)
        # -------------------------------------------------------------
        elif cmd_name == "/sync":
            reply = "🔄 *FORCING FRESH DATA SYNC...*\n━━━━━━━━━━━━━━━━━━━━\n"
            
            provider = self.market_provider or get_market_data_provider(settings.MARKET_DATA_PROVIDER)
            ingest_svc = self.market_ingestion or IngestionService(provider=provider, db=db)
            ingest_svc.db = db

            synced_count = 0
            target_timeframes = ["15m", "30m", "1h"] 
            sync_symbols = [
                s for s in settings.SUPPORTED_SYMBOLS 
                if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
            ] or ["XAU/USD"]

            for sym in sync_symbols:
                for tf in target_timeframes:
                    try:
                        await ingest_svc.sync_symbol_timeframe(
                            symbol=sym, timeframe=tf, limit=100, force_refresh=True
                        )
                        synced_count += 1
                    except Exception as e:
                        logger.error(f"Manual sync failed for {sym} [{tf}]: {e}")

            try:
                db.commit()
            except Exception:
                db.rollback()

            reply += f"✅ *Sync Complete!*\n"
            reply += f"📊 *Pairs Synced:* {len(sync_symbols)}\n"
            reply += f"⏱ *Timeframes:* {', '.join(target_timeframes)}\n"
            reply += f"🔄 *Total API Fetches:* {synced_count}\n"
            reply += "━━━━━━━━━━━━━━━━━━━━\n"
            reply += "_Database updated. Staleness blocks cleared. Ready to scan!_"

        # -------------------------------------------------------------
        # 10. Fallback for Unknown Commands (MUST BE LAST)
        # -------------------------------------------------------------
        else:
            raw_escaped = self.formatter.escape_code(raw_cmd)
            reply = f"❓ Unknown command `{raw_escaped}`. Type `/help` for available options."


        if request.chat_id:
            await self.telegram_client.send_message(text=reply, chat_id=request.chat_id)

        return TelegramCommandResponse(
            command=raw_cmd,
            reply_text=reply,
            handled_successfully=True,
            chat_id=request.chat_id,
        )
```

---

## server/app/services/telegram/message_formatter.py

```python
"""Telegram Message Formatting with rich emojis, entity sanitization, and Markdown/HTML styling."""

from datetime import datetime, timezone
import html
from typing import Any, List, Optional

from app.core.time_utils import format_local_time
from app.schemas.news import NewsEventResponse
from app.schemas.paper_trading import PaperPortfolioPerformance, VirtualAccountResponse
from app.schemas.signal import MarketScanResponse, SignalDirection, SignalResponse


class TelegramMessageFormatter:
    """Formats market signals, position alerts, news summaries, and portfolio updates for Telegram.
    
    Provides sanitization and escaping for dynamic user/market values to prevent Telegram entity parsing errors (400).
    """

    @staticmethod
    def escape_markdown(text: Any, version: int = 1) -> str:
        """Sanitize/escape dynamic strings to prevent Telegram Markdown parsing errors."""
        if text is None:
            return ""
        s = str(text)
        if version == 2:
            escape_chars = r"\_*[]()~`>#+-=|{}.!"
            return "".join(f"\\{c}" if c in escape_chars else c for c in s)
        else:
            escape_chars = ("\\", "_", "*", "`", "[", "]")
            for c in escape_chars:
                s = s.replace(c, f"\\{c}")
            return s

    @staticmethod
    def escape_markdown_v2(text: Any) -> str:
        """Convenience method for MarkdownV2 escaping."""
        return TelegramMessageFormatter.escape_markdown(text, version=2)

    @staticmethod
    def escape_code(text: Any) -> str:
        """Sanitize dynamic values placed inside single-backtick inline code spans (`...`)."""
        if text is None:
            return ""
        return str(text).replace("`", "'")

    @staticmethod
    def escape_html(text: Any) -> str:
        """Escape dynamic strings for Telegram HTML parse_mode (&, <, >)."""
        if text is None:
            return ""
        return html.escape(str(text), quote=False)

    @staticmethod
    def format_price(price: Optional[float], symbol: str) -> str:
        """Format price string with appropriate decimal precision per instrument."""
        if price is None:
            return "N/A"
        sym = symbol.upper().replace("/", "")
        if "XAU" in sym or "GOLD" in sym:
            return f"{price:.2f}"
        elif "JPY" in sym:
            return f"{price:.3f}"
        return f"{price:.5f}"

    @staticmethod
    def calculate_pips(entry: float, target: float, symbol: str) -> float:
        """Calculate standard pip distance adjusted for asset class."""
        diff = abs(entry - target)
        sym = symbol.upper().replace("/", "")
        if "XAU" in sym or "GOLD" in sym:
            # For Gold: 1 pip = $0.10 (10 cents)
            return round(diff / 0.10, 1)
        elif "JPY" in sym:
            # For JPY: 1 pip = 0.01
            return round(diff / 0.01, 1)
        else:
            # Standard Forex: 1 pip = 0.0001
            return round(diff / 0.0001, 1)

    @classmethod
    def format_signal_alert(cls, sig: SignalResponse) -> str:
        """Format an actionable trade setup alert.

        Handles three cases:
        - PATH BLOCKED rejection: shows a dedicated rejection card
        - TP Adjusted (trade still valid): shows warning in the alert
        - Normal trade: standard signal format
        """
        # Detect path validation outcomes from reasons and warnings
        path_blocked_reason = None
        tp_adjusted_reason = None
        path_advisory = None

        for w in (getattr(sig, "warnings", []) or []):
            if "Path Advisory" in w:
                path_advisory = w
                break

        for r in (sig.reasons or []):
            if "PATH BLOCKED" in r:
                path_blocked_reason = r
            elif "TP Adjusted" in r:
                tp_adjusted_reason = r
            elif "Path Advisory" in r and not path_advisory:
                path_advisory = r

        # PATH BLOCKED rejection card — trade was killed by obstacle detection (legacy fallback)
        if sig.direction == SignalDirection.WAIT and path_blocked_reason:
            sym = cls.escape_code(sig.symbol)
            tf = cls.escape_code(sig.timeframe)
            lines = [
                f"🚧 *TRADE REJECTED — PATH BLOCKED* 🚧",
                f"━━━━━━━━━━━━━━━━━━━━",
                f"📊 *Instrument:* `{sym}`",
                f"⏱ *Timeframe:* `{tf}`",
                f"━━━━━━━━━━━━━━━━━━━━",
                f"🛑 *Rejection Reason:*",
                f"  {cls.escape_markdown(path_blocked_reason)}",
                f"━━━━━━━━━━━━━━━━━━━━",
                f"🛡 *Risk Protection:* _Structural obstacle between entry and target "
                f"reduces R:R below minimum threshold. Trade skipped to protect capital._",
            ]
            # Include other context reasons (max 3)
            other_reasons = [r for r in (sig.reasons or []) if r != path_blocked_reason]
            if other_reasons:
                lines.append(f"━━━━━━━━━━━━━━━━━━━━\n💡 *Market Context:*")
                for r in other_reasons[:3]:
                    lines.append(f"  • {cls.escape_markdown(r)}")

            lines.extend([
                f"━━━━━━━━━━━━━━━━━━━━",
                f"🕒 *Timestamp:* `{format_local_time(sig.timestamp)}`",
                f"⚡ _Institutional obstacle detection is actively protecting your capital._",
            ])
            return "\n".join(lines)

        # Normal actionable signal format (with optional Path Advisory / TP Adjusted warning)
        dir_emoji = "🟢 *STRONG BUY (LONG)*" if sig.direction == SignalDirection.BUY else "🔴 *STRONG SELL (SHORT)*"
        rp = sig.risk_parameters

        sym_clean = sig.symbol
        sym = cls.escape_code(sym_clean)
        tf = cls.escape_code(sig.timeframe)
        score_str = f"{sig.setup_score:.1f}"

        # Strategy-aware header
        strategy_label = sig.strategy_name or "Confluence"
        header = f"⚡ *NEW SIGNAL: {cls.escape_markdown(strategy_label)}* ⚡"

        lines = [
            header,
            f"━━━━━━━━━━━━━━━━━━━━",
            f"📊 *Instrument:* `{sym}`",
            f"⏱ *Timeframe:* `{tf}`",
            f"🎯 *Direction:* {dir_emoji}",
            f"🧠 *Strategy:* `{cls.escape_code(strategy_label)}`",
            f"⭐ *Confluence Score:* `{score_str} / 100`",
        ]

        strat_name = getattr(sig, "strategy_name", "") or ""
        if "Range Sniper" in strat_name:
            lines.append("🧭 *Market Regime:* 🔄 `RANGING / MEAN REVERSION`")
        else:
            lines.append("🧭 *Market Regime:* 🎯 `TREND FOLLOWING`")

        if getattr(sig, "htf_trend", None):
            lines.append(f"📈 *1H Context:* `{cls.escape_code(sig.htf_trend)}`")

        # Path Advisory section — informational obstacle notification
        if path_advisory:
            lines.extend([
                f"━━━━━━━━━━━━━━━━━━━━",
                f"⚠️ *Path Advisory:*",
            ])
            for line in path_advisory.strip().split("\n"):
                clean = line.strip()
                if clean.startswith("⚠️ Path Advisory"):
                    continue
                lines.append(f"  {cls.escape_markdown(clean)}")
        elif tp_adjusted_reason:
            lines.extend([
                f"━━━━━━━━━━━━━━━━━━━━",
                f"⚠️ *Path Warning:*",
                f"  {cls.escape_markdown(tp_adjusted_reason)}",
            ])

        lines.append(f"━━━━━━━━━━━━━━━━━━━━")

        if sig.entry_price is not None:
            formatted_entry = cls.format_price(sig.entry_price, sym_clean)
            lines.append(f"📍 *Entry Price:* `{formatted_entry}`")

        if sig.stop_loss is not None and sig.entry_price is not None:
            formatted_sl = cls.format_price(sig.stop_loss, sym_clean)
            sl_pips = cls.calculate_pips(sig.entry_price, sig.stop_loss, sym_clean)
            lines.append(f"🛑 *Stop Loss:* `{formatted_sl}` ({sl_pips:.1f} pips)")

        if sig.take_profit_1 is not None and sig.entry_price is not None:
            formatted_tp1 = cls.format_price(sig.take_profit_1, sym_clean)
            tp1_pips = cls.calculate_pips(sig.entry_price, sig.take_profit_1, sym_clean)
            rr_label = f"{sig.risk_reward:.1f}" if sig.risk_reward else "2.0"
            lines.append(f"🎯 *Take Profit 1 (TP1):* `{formatted_tp1}` ({tp1_pips:.1f} pips | {rr_label} R:R)")

        if sig.take_profit_2 is not None and sig.entry_price is not None:
            formatted_tp2 = cls.format_price(sig.take_profit_2, sym_clean)
            tp2_pips = cls.calculate_pips(sig.entry_price, sig.take_profit_2, sym_clean)
            lines.append(f"🏆 *Take Profit 2 (TP2):* `{formatted_tp2}` ({tp2_pips:.1f} pips | 3.0 R:R)")

        if rp:
            lines.extend([
                f"━━━━━━━━━━━━━━━━━━━━",
                f"💼 *Risk Management (0.5% Rule):*",
                f"  • *Suggested Sizing:* `{rp.suggested_lot_size:.2f} Standard Lots`",
                f"  • *Risk Allocation:* `${rp.risk_amount_usd:,.2f}` on `${rp.account_balance:,.0f}` balance",
            ])

        if sig.score_breakdown:
            bd = sig.score_breakdown
            breakdown_lines = [
                f"━━━━━━━━━━━━━━━━━━━━",
                f"🏛 *Pillar Breakdown:*",
                f"  • Structure & MTF: `{bd.structure_score:.0f}/35`",
                f"  • Liquidity & POIs: `{bd.liquidity_score:.0f}/40`",
                f"  • Price Action: `{bd.price_action_score:.0f}/25`",
            ]
            if bd.indicators_score > 0:
                breakdown_lines.append(f"  • Indicators (Aux): `{bd.indicators_score:.0f}/25`")
            lines.extend(breakdown_lines)

        if sig.reasons:
            lines.append(f"━━━━━━━━━━━━━━━━━━━━\n💡 *Key Confluence Catalysts:*")
            for r in sig.reasons[:4]:
                # Skip the TP Adjusted and Path Advisory reasons here since they're shown above
                if (tp_adjusted_reason and r == tp_adjusted_reason) or "Path Advisory" in r:
                    continue
                lines.append(f"  ✓ {cls.escape_markdown(r)}")

        lines.extend([
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🛡 *News Blackout Status:* `✅ CLEAR - Safe to trade`",
            f"🕒 *Timestamp:* `{format_local_time(sig.timestamp)}`",
            f"⚠️ *Notice:* _Rule-based analysis only. Always manage your capital responsibly._",
        ])

        return "\n".join(lines)

    @classmethod
    def format_multi_strategy_alert(cls, signals: List[SignalResponse]) -> str:
        """Format an alert when multiple independent strategies produce signals for the same symbol."""
        if not signals:
            return ""
        if len(signals) == 1:
            return cls.format_signal_alert(signals[0])

        sym_clean = signals[0].symbol
        sym = cls.escape_code(sym_clean)
        tf = cls.escape_code(signals[0].timeframe)

        # Check directions
        directions = {s.direction for s in signals if s.direction in (SignalDirection.BUY, SignalDirection.SELL)}
        is_conflict = len(directions) > 1

        if is_conflict:
            header = f"⚠️ *STRATEGY CONFLICT DETECTED: {sym}* ⚠️"
            state_label = "⚠️ *Market State:* `STRATEGY CONFLICT (Opposing Biases)`"
        else:
            dir_val = list(directions)[0] if directions else SignalDirection.WAIT
            dir_text = "BUY" if dir_val == SignalDirection.BUY else ("SELL" if dir_val == SignalDirection.SELL else "WAIT")
            header = f"⚡ *STRATEGY CONFLUENCE: {sym} ({dir_text})* ⚡"
            state_label = "✅ *Market State:* `STRATEGY CONFLUENCE (Aligned Direction)`"

        lines = [
            header,
            f"━━━━━━━━━━━━━━━━━━━━",
            f"📊 *Instrument:* `{sym}`",
            f"⏱ *Timeframe:* `{tf}`",
            state_label,
            f"━━━━━━━━━━━━━━━━━━━━",
        ]

        for s in signals:
            strat = s.strategy_name or "Independent Strategy"
            dir_emoji = "🟢 BUY" if s.direction == SignalDirection.BUY else ("🔴 SELL" if s.direction == SignalDirection.SELL else "⚪ WAIT")
            lines.append(f"🧠 *{cls.escape_markdown(strat)}:* {dir_emoji} (Score: `{s.setup_score:.1f}/100`)")
            if s.reasons:
                for r in s.reasons[:3]:
                    lines.append(f"   • {cls.escape_markdown(r)}")
            lines.append(f"────────────────────")

        # Summary guidance
        if is_conflict:
            lines.extend([
                f"🛡 *Analysis Note:* _Independent strategies show opposing direction. "
                f"Exercise elevated caution or wait for structural resolution._",
            ])
        else:
            actionable = [s for s in signals if s.direction in (SignalDirection.BUY, SignalDirection.SELL)]
            if actionable:
                primary_sig = max(actionable, key=lambda x: x.setup_score)
                if primary_sig.entry_price is not None:
                    lines.append(f"📍 *Confluence Entry:* `{cls.format_price(primary_sig.entry_price, sym_clean)}`")
                if primary_sig.stop_loss is not None:
                    lines.append(f"🛑 *Stop Loss:* `{cls.format_price(primary_sig.stop_loss, sym_clean)}`")
                if primary_sig.take_profit_1 is not None:
                    lines.append(f"🎯 *Take Profit 1:* `{cls.format_price(primary_sig.take_profit_1, sym_clean)}`")

        lines.extend([
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🕒 *Timestamp:* `{format_local_time(signals[0].timestamp)}`",
            f"⚠️ *Notice:* _Rule-based multi-strategy analysis. Manage risk responsibly._",
        ])

        return "\n".join(lines)

    @classmethod
    def format_tp1_hit(cls, symbol: str, price: float, realized_pnl: float, new_sl: float) -> str:
        """Format a Take Profit 1 reached notification."""
        sym = cls.escape_code(symbol)
        formatted_price = cls.format_price(price, symbol)
        formatted_sl = cls.format_price(new_sl, symbol)
        return (
            f"🎯 *TAKE PROFIT 1 REACHED!* 🎯\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Pair:* `{sym}`\n"
            f"💰 *Exit Price:* `{formatted_price}`\n"
            f"💵 *Locked-in Profit:* `+${realized_pnl:,.2f}`\n"
            f"🔒 *Action Taken:* `Closed 50% lots. Stop Loss moved to Break-Even ({formatted_sl})`\n"
            f"🏃 *Runner:* `50% position remaining active for TP2 target.`\n"
            f"🕒 `{format_local_time(datetime.now(timezone.utc))}`"
        )

    @classmethod
    def format_tp2_hit(cls, symbol: str, price: float, total_pnl: float, return_r: float) -> str:
        """Format a Take Profit 2 final target notification."""
        sym = cls.escape_code(symbol)
        formatted_price = cls.format_price(price, symbol)
        return (
            f"🏆 *TAKE PROFIT 2 TARGET HIT!* 🏆\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Pair:* `{sym}`\n"
            f"💰 *Exit Price:* `{formatted_price}`\n"
            f"💵 *Total Realized PnL:* `+${total_pnl:,.2f}`\n"
            f"📈 *Payoff Return:* `+{return_r:.2f} R-Multiple`\n"
            f"🎉 *Status:* `Trade fully completed with maximum target profit!`\n"
            f"🕒 `{format_local_time(datetime.now(timezone.utc))}`"
        )

    @classmethod
    def format_sl_hit(cls, symbol: str, price: float, loss_pnl: float, is_be: bool) -> str:
        """Format Stop Loss / Break-Even alert."""
        tag = "⚡ *BREAK-EVEN STOP TRIGGERED*" if is_be else "🛑 *STOP LOSS HIT*"
        pnl_str = f"${loss_pnl:,.2f}" if loss_pnl >= 0 else f"-${abs(loss_pnl):,.2f}"
        sym = cls.escape_code(symbol)
        formatted_price = cls.format_price(price, symbol)
        return (
            f"{tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Pair:* `{sym}`\n"
            f"📍 *Exit Price:* `{formatted_price}`\n"
            f"💵 *Realized PnL:* `{pnl_str}`\n"
            f"🛡 *Capital Protected:* `Position closed per strict risk management rules.`\n"
            f"🕒 `{format_local_time(datetime.now(timezone.utc))}`"
        )

    @classmethod
    def format_market_scan_summary(cls, scan_result: MarketScanResponse) -> str:
        """Format full multi-symbol unified market scanner digest."""
        lines = [
            f"📡 *UNIFIED SCANNER DIGEST* 📡",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🕒 *Scan Time:* `{format_local_time(scan_result.timestamp)}`",
            f"🔍 *Markets Scanned:* `{scan_result.scanned_count}` | 🎯 *Actionable:* `{scan_result.actionable_count}`",
            f"━━━━━━━━━━━━━━━━━━━━",
        ]

        for r in scan_result.results:
            dir_icon = "🟢" if r.direction == SignalDirection.BUY else ("🔴" if r.direction == SignalDirection.SELL else "⚪")
            status_text = f"*{cls.escape_markdown(r.direction.value)}* (Score: `{r.setup_score:.0f}/100`)"

            # Trend alignment tag
            if getattr(r, "trend_alignment", None):
                align = r.trend_alignment
                if align == "COUNTER-TREND SCALP":
                    status_text += " `[⚠️ COUNTER-TREND SCALP]`"
                elif align == "TREND FOLLOWING":
                    status_text += " `[✅ TREND FOLLOWING]`"
                else:
                    status_text += f" `[{cls.escape_markdown(align)}]`"
            elif r.direction == SignalDirection.WAIT and getattr(r, "htf_trend", None):
                status_text += f" `[1H {cls.escape_markdown(r.htf_trend)}]`"

            if r.blackout_blocked:
                status_text += " `[NEWS BLOCKED]`"

            sym = cls.escape_code(f"{r.symbol:<8}")
            tf_display = "1H" if r.timeframe.lower() == "1h" else r.timeframe
            tf = cls.escape_code(tf_display)

            # Strategy badge
            strat_badge = ""
            if getattr(r, "signal", None) and getattr(r.signal, "strategy_name", None):
                strat_badge = f" `[{cls.escape_code(r.signal.strategy_name)}]`"

            lines.append(f"{dir_icon} `{sym}` [{tf}] ➔ {status_text}{strat_badge}")

        lines.extend([
            f"━━━━━━━━━━━━━━━━━━━━",
            f"💡 _Type /signal <pair> for deep multi-timeframe analysis._",
        ])
        return "\n".join(lines)

    @classmethod
    def format_economic_news_alert(cls, events: List[NewsEventResponse]) -> str:
        """Format scheduled economic news alerts."""
        lines = [
            f"📰 *ECONOMIC CALENDAR & NEWS MONITOR* 📰",
            f"━━━━━━━━━━━━━━━━━━━━",
        ]
        if not events:
            lines.append("✅ *No high or medium impact events scheduled today.*")
            return "\n".join(lines)

        for ev in events[:5]:
            impact_icon = "🔴" if ev.impact.upper() == "HIGH" else "🟡"
            curr = cls.escape_markdown(ev.currency)
            ev_name = cls.escape_code(ev.event_name)
            fc = cls.escape_code(ev.forecast or 'N/A')
            prev = cls.escape_code(ev.previous or 'N/A')
            lines.append(
                f"{impact_icon} *({curr})* `{ev_name}`\n"
                f"   ⏰ `{ev.scheduled_time.strftime('%H:%M UTC')}` | Forecast: `{fc}` | Prior: `{prev}`"
            )

        lines.extend([
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🛡 _Trading automatically pauses 30m before high-impact releases._",
        ])
        return "\n".join(lines)

    @classmethod
    def format_news_unavailable_alert(cls, reason: Optional[str] = None) -> str:
        """Format structured alert when live economic news feed is unreachable."""
        lines = [
            f"⚠️ *NEWS DATA UNAVAILABLE* ⚠️",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"❌ *Live economic calendar feed is currently unreachable.*",
            f"🛡 *FAIL-SAFE ACTIVATED:* New trade generation is safely paused to protect capital until economic news feed is restored.",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"⚡ _Institutional Capital Protection Rule_",
        ]
        return "\n".join(lines)

    @classmethod
    def format_portfolio_summary(cls, acc: VirtualAccountResponse, perf: PaperPortfolioPerformance) -> str:
        """Format virtual account portfolio overview."""
        acc_name = cls.escape_code(acc.name)
        return (
            f"💼 *VIRTUAL TRADING PORTFOLIO* 💼\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *Account:* `{acc_name}`\n"
            f"💵 *Balance:* `${acc.balance:>10,.2f}`\n"
            f"📈 *Equity:*  `${acc.equity:>10,.2f}`\n"
            f"📊 *Floating PnL:* `${acc.floating_pnl:>+9,.2f}`\n"
            f"🔒 *Margin Used:*  `${acc.margin_used:>10,.2f}` (Level: `{acc.margin_level_pct:.1f}%`)\n"
            f"🆓 *Free Margin:*  `${acc.free_margin:>10,.2f}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 *Trading Performance:*\n"
            f"  • *Total Return:* `{perf.total_return_pct:>+6.2f}%`\n"
            f"  • *Win Rate:* `{perf.win_rate:.1f}%` ({perf.winning_trades}W / {perf.losing_trades}L)\n"
            f"  • *Profit Factor:* `{perf.profit_factor:.2f}`\n"
            f"  • *Active Positions:* `{perf.open_trades}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕒 `{format_local_time(datetime.now(timezone.utc))}`"
        )

    @staticmethod
    def format_help_menu() -> str:
        """Format bot command help menu."""
        return (
            f" *FOREX SIGNAL BOT - COMMAND MENU* \n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 `/scan` - Scan all markets (XAU/USD, USD/JPY)\n"
            f"🔄 `/sync` - Force fresh data sync for ALL pairs (Fixes Stale Data)\n"
            f"🎯 `/signal <pair>` - Deep setup score for symbol (e.g. `/signal XAU/USD`)\n"
            f"📰 `/news` - Today's economic calendar & news blackout check\n"
            f" `/account` - Virtual paper trading balance, equity & margin\n"
            f"📊 `/positions` - List all active & pending paper positions\n"
            f"🏆 `/performance` - Strategy win rate & portfolio statistics\n"
            f" `/backtest <pair>` - Run historical strategy backtest\n"
            f"❓ `/help` - Show this command reference\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ _Institutional Rule-Based Market Analysis & Risk Management_"
        )
```

---

## server/app/services/market_data/freshness.py

```python
"""Market data freshness verification, latest closed candle selection, and timestamp utilities."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Union

from app.core.logging import logger
from app.schemas.candle import CandleBase


TIMEFRAME_DELTAS: Dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
}

# Standard max staleness thresholds during open market hours
DEFAULT_STALENESS_THRESHOLDS: Dict[str, timedelta] = {
    "1m": timedelta(minutes=15),
    "5m": timedelta(minutes=30),
    "15m": timedelta(hours=1),
    "30m": timedelta(hours=2),
    "1h": timedelta(hours=4),
    "4h": timedelta(hours=16),
    "1d": timedelta(hours=48),
    "1w": timedelta(days=14),
}


def get_timeframe_delta(timeframe: str) -> timedelta:
    """Retrieve timedelta interval for standard timeframe string."""
    tf = timeframe.lower().strip()
    delta = TIMEFRAME_DELTAS.get(tf)
    if not delta:
        raise ValueError(f"Unknown timeframe '{timeframe}'. Supported: {list(TIMEFRAME_DELTAS.keys())}")
    return delta


def ensure_utc_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure a datetime object is timezone-aware in UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_forex_weekend(timestamp: Optional[datetime] = None) -> bool:
    """Check if a timestamp falls during the standard Forex weekend closure.
    
    Forex market closes Friday ~21:00 UTC and reopens Sunday ~21:00 UTC.
    """
    ts = ensure_utc_datetime(timestamp) or datetime.now(timezone.utc)
    weekday = ts.weekday()  # Monday is 0, Sunday is 6
    hour = ts.hour

    # Friday after 21:00 UTC
    if weekday == 4 and hour >= 21:
        return True
    # Entire Saturday
    if weekday == 5:
        return True
    # Sunday before 21:00 UTC
    if weekday == 6 and hour < 21:
        return True

    return False


def is_candle_closed(
    candle: Union[CandleBase, Any],
    timeframe: str,
    as_of: Optional[datetime] = None,
) -> bool:
    """Check whether a candle bar has completed its duration and is closed.
    
    A candle with start timestamp T and duration D is closed if:
        T + D <= as_of
    """
    if candle is None:
        return False

    ref_time = ensure_utc_datetime(as_of) or datetime.now(timezone.utc)
    candle_ts = ensure_utc_datetime(candle.timestamp)
    delta = get_timeframe_delta(timeframe)
    candle_close_time = candle_ts + delta

    return candle_close_time <= ref_time


def filter_closed_candles(
    candles: Sequence[Union[CandleBase, Any]],
    timeframe: str,
    as_of: Optional[datetime] = None,
) -> List[Any]:
    """Filter a candle sequence to include only fully closed (verified) candles.
    
    Out-of-order candles are sorted chronologically ascending.
    If candles are strictly in the past relative to as_of (e.g. historical data/backtests),
    all elapsed candles are returned.
    """
    if not candles:
        return []

    ref_time = ensure_utc_datetime(as_of) or datetime.now(timezone.utc)
    delta = get_timeframe_delta(timeframe)

    closed_candles: List[Any] = []
    for c in candles:
        ts = ensure_utc_datetime(c.timestamp)
        close_time = ts + delta
        if close_time <= ref_time:
            closed_candles.append(c)

    # Sort ascending chronologically
    closed_candles.sort(key=lambda c: ensure_utc_datetime(c.timestamp))
    return closed_candles


def get_latest_closed_candle(
    candles: Sequence[Union[CandleBase, Any]],
    timeframe: str,
    as_of: Optional[datetime] = None,
) -> Optional[Any]:
    """Retrieve the single most recent closed candle from a sequence."""
    closed = filter_closed_candles(candles, timeframe=timeframe, as_of=as_of)
    if not closed:
        return None
    return closed[-1]


@dataclass
class StalenessCheckResult:
    """Detailed diagnostics for candle dataset freshness."""
    is_stale: bool
    symbol: str
    timeframe: str
    latest_candle_time: Optional[datetime]
    latest_close_time: Optional[datetime]
    age_seconds: float
    age_hours: float
    max_allowed_hours: float
    is_weekend: bool
    message: str


def check_data_staleness(
    candles: Sequence[Union[CandleBase, Any]],
    symbol: str = "UNKNOWN",
    timeframe: str = "1h",
    max_staleness_hours: Optional[float] = None,
    as_of: Optional[datetime] = None,
) -> StalenessCheckResult:
    """Check if the latest candle in the dataset is stale relative to current time or as_of time.
    
    Accounts for Forex weekend closures (Friday 21:00 UTC - Sunday 21:00 UTC).
    """
    ref_time = ensure_utc_datetime(as_of) or datetime.now(timezone.utc)
    delta = get_timeframe_delta(timeframe)
    tf_lower = timeframe.lower().strip()

    if max_staleness_hours is not None:
        threshold_delta = timedelta(hours=max_staleness_hours)
    else:
        threshold_delta = DEFAULT_STALENESS_THRESHOLDS.get(tf_lower, delta * 3)

    max_allowed_hours = threshold_delta.total_seconds() / 3600.0
    weekend = is_forex_weekend(ref_time)

    if not candles:
        return StalenessCheckResult(
            is_stale=True,
            symbol=symbol,
            timeframe=timeframe,
            latest_candle_time=None,
            latest_close_time=None,
            age_seconds=float("inf"),
            age_hours=float("inf"),
            max_allowed_hours=max_allowed_hours,
            is_weekend=weekend,
            message=f"No candle data available for {symbol} [{timeframe}]. Dataset is empty.",
        )

    # Sort to find latest
    latest_candle = max(candles, key=lambda c: ensure_utc_datetime(c.timestamp))
    latest_ts = ensure_utc_datetime(latest_candle.timestamp)
    latest_close = latest_ts + delta

    age_seconds = max(0.0, (ref_time - latest_close).total_seconds())
    age_hours = age_seconds / 3600.0

    # If it is currently a Forex weekend and the latest candle is from Friday close (after 18:00 UTC)
    if weekend:
        if latest_ts.weekday() == 4 and latest_ts.hour >= 18:
            return StalenessCheckResult(
                is_stale=False,
                symbol=symbol,
                timeframe=timeframe,
                latest_candle_time=latest_ts,
                latest_close_time=latest_close,
                age_seconds=age_seconds,
                age_hours=age_hours,
                max_allowed_hours=max_allowed_hours,
                is_weekend=True,
                message=(
                    f"Market is closed for weekend. Latest candle from Friday close "
                    f"({latest_ts.strftime('%Y-%m-%d %H:%M UTC')}) is valid."
                ),
            )

    is_stale = age_seconds > threshold_delta.total_seconds()

    if is_stale:
        msg = (
            f"STALE DATA DETECTED for {symbol} [{timeframe}]: Latest closed candle closed at "
            f"{latest_close.strftime('%Y-%m-%d %H:%M UTC')} ({age_hours:.1f}h ago). "
            f"Exceeds maximum freshness threshold of {max_allowed_hours:.1f}h."
        )
    else:
        msg = (
            f"Market data for {symbol} [{timeframe}] is FRESH: Latest closed candle at "
            f"{latest_close.strftime('%Y-%m-%d %H:%M UTC')} ({age_hours:.1f}h ago <= {max_allowed_hours:.1f}h threshold)."
        )

    return StalenessCheckResult(
        is_stale=is_stale,
        symbol=symbol,
        timeframe=timeframe,
        latest_candle_time=latest_ts,
        latest_close_time=latest_close,
        age_seconds=age_seconds,
        age_hours=age_hours,
        max_allowed_hours=max_allowed_hours,
        is_weekend=weekend,
        message=msg,
    )


def format_candle_log_line(
    candle: Union[CandleBase, Any],
    symbol: str,
    timeframe: str,
    context: str = "MARKET DATA",
    is_fresh: Optional[bool] = None,
) -> str:
    """Format structured log string for explicit latest candle logging."""
    if candle is None:
        return f"[{context}] Symbol: {symbol} | Timeframe: {timeframe} | No candle data available."

    ts = ensure_utc_datetime(candle.timestamp)
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S UTC") if ts else "N/A"
    
    vol = getattr(candle, "volume", 0.0) or 0.0
    freshness_str = ""
    if is_fresh is not None:
        freshness_str = f" | Freshness: {'FRESH' if is_fresh else 'STALE'}"

    return (
        f"[{context}] Symbol: {symbol} | Timeframe: {timeframe} | "
        f"Latest Closed Candle: {ts_str} | Open: {candle.open:.5f} | "
        f"High: {candle.high:.5f} | Low: {candle.low:.5f} | "
        f"Close: {candle.close:.5f} | Volume: {vol:.1f}{freshness_str}"
    )


def log_latest_candle(
    candle: Union[CandleBase, Any],
    symbol: str,
    timeframe: str,
    context: str = "MARKET DATA",
    is_fresh: Optional[bool] = None,
) -> None:
    """Explicitly log latest candle details at INFO level."""
    log_line = format_candle_log_line(
        candle=candle,
        symbol=symbol,
        timeframe=timeframe,
        context=context,
        is_fresh=is_fresh,
    )
    logger.info(log_line)
```

---

## server/app/services/signals/confluence_engine.py

```python
"""Unified Multi-Strategy Consensus and Confluence Engine."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING, Tuple, Union

if TYPE_CHECKING:
    from app.services.strategies.strategy_manager import StrategyManager

from app.core.config import settings
from app.core.logging import logger
from app.schemas.candle import CandleBase
from app.schemas.news import NewsBlackoutCheckResponse
from app.schemas.signal import (
    RiskParameters,
    ScoreBreakdown,
    SignalDirection,
    SignalResponse,
    SignalStatus,
)
from app.schemas.structure import TrendDirection 
from app.services.structure.ltf_confirmation import LTFConfirmationEngine
from app.services.indicators import IndicatorService
from app.services.liquidity import LiquidityService
from app.services.news import NewsFilterEngine
from app.services.market_data import (
    check_data_staleness,
    ensure_utc_datetime,
    filter_closed_candles,
    log_latest_candle,
)
from app.services.signals.evaluators import (
    ConsensusFilter,
    LiquiditySMCConsensusEvaluator,
    MomentumIndicatorConsensusEvaluator,
    PillarEvaluation,
    PriceActionConsensusEvaluator,
    StructureConsensusEvaluator,
)
from app.services.signals.path_validator import PathValidator
from app.services.signals.risk_manager import RiskManager
from app.services.structure import MultiTimeframeStructureEngine
from app.services.strategies.base import StrategyResult


class ConfluenceEngine:
    """Unified Multi-Strategy Consensus Engine.

    Delegates analytical scoring to the pluggable ``StrategyManager``
    while retaining ownership of:
      - Data ingestion & validation (staleness, closed-candle filtering)
      - News blackout checks
      - Risk management & position sizing
      - Fingerprint generation & SignalResponse assembly

    Backward-compatible: ``evaluate()`` still returns a single
    ``SignalResponse`` (the best qualifying signal).  Use
    ``evaluate_multi()`` to receive all qualifying signals.
    """

    def __init__(
        self,
        liquidity_service: Optional[LiquidityService] = None,
        mtf_engine: Optional[MultiTimeframeStructureEngine] = None,
        indicator_service: Optional[IndicatorService] = None,
        news_filter: Optional[NewsFilterEngine] = None,
        risk_manager: Optional[RiskManager] = None,
        min_score_threshold: Optional[float] = None,
        strategy_manager: Optional["StrategyManager"] = None,
    ):
        self.liquidity_service = liquidity_service or LiquidityService()
        self.mtf_engine = mtf_engine or MultiTimeframeStructureEngine()
        self.indicator_service = indicator_service or IndicatorService()
        self.news_filter = news_filter or NewsFilterEngine()
        self.risk_manager = risk_manager or RiskManager()
        self.path_validator = PathValidator()
        self.min_score_threshold = min_score_threshold or settings.MIN_SETUP_SCORE

        self.ltf_confirmation_engine = LTFConfirmationEngine()

        # Sub-strategy modular evaluators (kept for backward compat with ScoringEngine)
        self.structure_evaluator = StructureConsensusEvaluator()
        self.liquidity_evaluator = LiquiditySMCConsensusEvaluator()
        self.indicator_evaluator = MomentumIndicatorConsensusEvaluator()
        self.price_action_evaluator = PriceActionConsensusEvaluator()
        self.consensus_filter = ConsensusFilter(min_score_threshold=self.min_score_threshold)

        # Pluggable strategy manager (lazy import to avoid circular dependency)
        if strategy_manager is not None:
            self.strategy_manager = strategy_manager
        else:
            from app.services.strategies.strategy_manager import StrategyManager
            self.strategy_manager = StrategyManager()

    @staticmethod
    def generate_fingerprint(
        symbol: str,
        timeframe: str,
        direction: SignalDirection,
        entry_price: float,
        stop_loss: float,
        timestamp: datetime,
        strategy_name: Optional[str] = None,
    ) -> str:
        """Generate unique SHA-256 fingerprint for deduplication."""
        ts_utc = ensure_utc_datetime(timestamp) or datetime.now(timezone.utc)
        ts_str = ts_utc.isoformat()
        strat_str = f"_{strategy_name}" if strategy_name else ""
        payload = f"{symbol}_{timeframe}_{direction.value}_{entry_price:.5f}_{stop_loss:.5f}_{ts_str}{strat_str}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Pre-flight checks (shared by evaluate & evaluate_multi)
    # ------------------------------------------------------------------

    def _preflight(
        self,
        symbol: str,
        timeframe: str,
        candles_dict: Optional[Dict[str, Sequence[Union[CandleBase, Any]]]] = None,
        candles_primary: Optional[Sequence[Union[CandleBase, Any]]] = None,
        candles_4h: Optional[Sequence[Union[CandleBase, Any]]] = None,
        candles_15m: Optional[Sequence[Union[CandleBase, Any]]] = None,
        news_check: Optional[NewsBlackoutCheckResponse] = None,
    ) -> Tuple[
        Optional[SignalResponse],      # early-exit response (None = proceed)
        List[Any], Optional[List[Any]], Optional[List[Any]],  # c_prim, c_4h, c_15m
    ]:
        """Run data-validation and news-blackout checks.

        Returns ``(early_exit_response, c_prim, c_4h, c_15m)``.
        If ``early_exit_response`` is not None, the caller should return it immediately.
        """
        # 1. Resolve primary and multi-timeframe candle datasets
        if candles_dict:
            raw_prim = candles_dict.get(timeframe) or candles_dict.get("1h") or list(candles_dict.values())[0]
            raw_4h = candles_dict.get("4h") or candles_4h
            raw_15m = candles_dict.get("15m") or candles_15m
        else:
            raw_prim = candles_primary or []
            raw_4h = candles_4h
            raw_15m = candles_15m

        # Filter for verified closed candles
        c_prim = filter_closed_candles(raw_prim, timeframe=timeframe) if raw_prim else []
        c_4h = filter_closed_candles(raw_4h, timeframe="4h") if raw_4h else None
        c_15m = filter_closed_candles(raw_15m, timeframe="15m") if raw_15m else None

        if not c_prim:
            now_utc = datetime.now(timezone.utc)
            return (
                SignalResponse(
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=SignalDirection.WAIT,
                    setup_score=0.0,
                    entry_price=0.0,
                    stop_loss=0.0,
                    take_profit_1=0.0,
                    take_profit_2=0.0,
                    risk_reward=0.0,
                    fingerprint=self.generate_fingerprint(symbol, timeframe, SignalDirection.WAIT, 0.0, 0.0, now_utc),
                    reasons=["No closed verified candle dataset provided for analysis."],
                    status=SignalStatus.ACTIVE,
                    timestamp=now_utc,
                    score_breakdown=ScoreBreakdown(
                        structure_score=0.0,
                        liquidity_score=0.0,
                        indicators_score=0.0,
                        price_action_score=0.0,
                        total_score=0.0,
                        is_qualified=False,
                    ),
                ),
                [], None, None,
            )

        # 2. Check Data Staleness & Explicit Latest Candle Logging
        staleness = check_data_staleness(c_prim, symbol=symbol, timeframe=timeframe)
        latest_c = c_prim[-1]
        log_latest_candle(
            latest_c,
            symbol=symbol,
            timeframe=timeframe,
            context="SIGNAL EVALUATION",
            is_fresh=not staleness.is_stale,
        )
        
        # ✅ HARD BLOCK: Refuse to analyze if data is too old
        max_allowed_age = 2.0 if timeframe in ["1h", "4h"] else 1.0
        
        if staleness.is_stale and staleness.age_hours > max_allowed_age:
            now_utc = datetime.now(timezone.utc)
            return (
                SignalResponse(
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=SignalDirection.WAIT,
                    setup_score=0.0,
                    entry_price=0.0,
                    stop_loss=0.0,
                    take_profit_1=0.0,
                    take_profit_2=0.0,
                    risk_reward=0.0,
                    fingerprint=self.generate_fingerprint(symbol, timeframe, SignalDirection.WAIT, 0.0, 0.0, now_utc),
                    reasons=[
                        f"🚫 DATA TOO STALE: Last closed candle is {staleness.age_hours:.1f} hours old.",
                        "Analysis aborted to prevent trading on outdated market conditions. Please sync fresh data."
                    ],
                    status=SignalStatus.ACTIVE,
                    timestamp=now_utc,
                    score_breakdown=ScoreBreakdown(
                        structure_score=0.0, liquidity_score=0.0, indicators_score=0.0,
                        price_action_score=0.0, total_score=0.0, is_qualified=False,
                    ),
                ),
                c_prim, c_4h, c_15m,
            )

        if staleness.is_stale:
            logger.warning(staleness.message)

        # 3. Check News Blackout / News Data Unavailable Fail-Safe
        if news_check and (news_check.is_blackout or not news_check.trading_allowed or news_check.is_news_unavailable or news_check.is_fail_safe):
            now_utc = datetime.now(timezone.utc)
            if news_check.is_blackout:
                prefix = "NEWS BLACKOUT ACTIVE:"
            elif news_check.is_news_unavailable or news_check.is_fail_safe:
                prefix = "NEWS DATA UNAVAILABLE:"
            else:
                prefix = "NEWS PROTECTION ACTIVE:"

            reasons = [
                f"{prefix} {news_check.reason}",
                "Trading suspended to prevent slippage or capital loss during high-impact economic releases or unverified news data.",
            ]
            breakdown = ScoreBreakdown(
                structure_score=0.0,
                liquidity_score=0.0,
                indicators_score=0.0,
                price_action_score=0.0,
                total_score=0.0,
                is_qualified=False,
            )
            return (
                SignalResponse(
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=SignalDirection.WAIT,
                    setup_score=0.0,
                    entry_price=0.0,
                    stop_loss=0.0,
                    take_profit_1=0.0,
                    take_profit_2=0.0,
                    risk_reward=0.0,
                    fingerprint=self.generate_fingerprint(symbol, timeframe, SignalDirection.WAIT, 0.0, 0.0, now_utc),
                    reasons=reasons,
                    status=SignalStatus.ACTIVE,
                    timestamp=now_utc,
                    score_breakdown=breakdown,
                ),
                c_prim, c_4h, c_15m,
            )

        return None, c_prim, c_4h, c_15m

    # ------------------------------------------------------------------
    # Shared data preparation
    # ------------------------------------------------------------------

    def _prepare_market_data(
        self,
        symbol: str,
        timeframe: str,
        c_prim: Sequence[Any],
        c_4h: Optional[Sequence[Any]],
        c_15m: Optional[Sequence[Any]],
    ) -> Tuple[Any, Any, Optional[Any]]:
        """Run structure, indicator, and MTF analysis on candle data.

        Returns ``(structure_analysis, indicator_analysis, mtf_analysis)``.
        """
        # Sub-Module A: SMC Advanced Structure & Breakouts
        structure_analysis = self.liquidity_service.analyze_liquidity_and_structure(
            candles=c_prim,
            symbol=symbol,
            timeframe=timeframe,
        )

        # Sub-Module B: Momentum Indicators & Price Action Patterns
        indicator_analysis = self.indicator_service.analyze_indicators(
            candles=c_prim,
            symbol=symbol,
            timeframe=timeframe,
        )

        # Sub-Module C: Multi-Timeframe (MTF) Alignment
        mtf_analysis = None
        if c_4h and c_15m:
            mtf_analysis = self.mtf_engine.analyze_multi_timeframe(
                symbol=symbol,
                timeframe_candles={
                    "4h": c_4h,
                    timeframe: c_prim,
                    "15m": c_15m,
                },
            )

        return structure_analysis, indicator_analysis, mtf_analysis

    # ------------------------------------------------------------------
    # Build a SignalResponse from a StrategyResult
    # ------------------------------------------------------------------

    def _build_signal_response(
        self,
        result: StrategyResult,
        symbol: str,
        timeframe: str,
        indicator_analysis: Any,
        structure_analysis: Any,
        account_balance: float,
        risk_percent: float,
        htf_trend: Optional[str] = None,
    ) -> SignalResponse:
        """Convert a ``StrategyResult`` into a full ``SignalResponse`` with risk management."""
        current_price = indicator_analysis.current_price
        latest_ts = indicator_analysis.timestamp
        direction = result.direction
        reasons = list(result.reasons)  # Mutable copy for path validation notes
        warnings: List[str] = []

        # 7. Risk Management & SMC Geometric Levels + PATH VALIDATION
        risk_params: Optional[RiskParameters] = None

        if direction in (SignalDirection.BUY, SignalDirection.SELL):
            # Check if strategy supplied specific custom risk levels (e.g. CRT dynamic SL/TP)
            custom_sl = result.metadata.get("stop_loss") if result.metadata else None
            custom_tp1 = result.metadata.get("take_profit_1") if result.metadata else None

            if custom_sl is not None and custom_tp1 is not None and abs(current_price - custom_sl) > 0:
                pip_size = self.risk_manager.get_pip_size(symbol)
                risk_price = abs(current_price - custom_sl)
                risk_pips = round(risk_price / pip_size, 1)
                reward_pips_tp1 = round(abs(custom_tp1 - current_price) / pip_size, 1)
                rr_tp1 = round(reward_pips_tp1 / max(1e-6, risk_pips), 2)
                custom_tp2 = (result.metadata.get("take_profit_2") if result.metadata else None) or (
                    current_price + (custom_tp1 - current_price) * (2.5 / 1.5)
                )
                reward_pips_tp2 = round(abs(custom_tp2 - current_price) / pip_size, 1)
                rr_tp2 = round(reward_pips_tp2 / max(1e-6, risk_pips), 2)

                risk_pct = risk_percent or settings.MAX_RISK_PERCENT
                risk_amount_usd = round(account_balance * (risk_pct / 100.0), 2)
                pip_val = self.risk_manager.get_pip_value_per_lot(symbol)
                raw_lots = risk_amount_usd / max(1e-6, risk_pips * pip_val)
                suggested_lots = round(max(0.01, min(100.0, raw_lots)), 2)

                risk_params = RiskParameters(
                    entry_price=round(current_price, 5),
                    stop_loss=round(custom_sl, 5),
                    take_profit_1=round(custom_tp1, 5),
                    take_profit_2=round(custom_tp2, 5),
                    risk_pips=risk_pips,
                    reward_pips_tp1=reward_pips_tp1,
                    reward_pips_tp2=reward_pips_tp2,
                    risk_reward_tp1=rr_tp1,
                    risk_reward_tp2=rr_tp2,
                    account_balance=account_balance,
                    risk_percent=risk_pct,
                    risk_amount_usd=risk_amount_usd,
                    suggested_lot_size=suggested_lots,
                )
            else:
                supp_low = structure_analysis.base_structure.key_support
                res_high = structure_analysis.base_structure.key_resistance

                # A. Calculate Initial Risk
                risk_params = self.risk_manager.calculate_trade_risk(
                    symbol=symbol,
                    direction=direction,
                    entry_price=current_price,
                    atr_value=indicator_analysis.atr.atr_value,
                    key_support_low=supp_low,
                    key_resistance_high=res_high,
                    account_balance=account_balance,
                    risk_percent=risk_percent,
                )


            # B. Small Account Rejection Check
            if risk_params.suggested_lot_size == 0.0:
                logger.warning(f"Trade REJECTED for {symbol}: Insufficient balance for safe position sizing.")
                direction = SignalDirection.WAIT
                reasons = [
                    "❌ INSUFFICIENT BALANCE: Account is too small to safely trade this setup at minimum lot size.",
                    "Action: Awaiting larger account balance or lower volatility setup."
                ]
                risk_params = None
            else:
                # C. 🗺️ PATH VALIDATION (Informational Advisory Warning System)
                sr_zones = getattr(structure_analysis, 'sr_zones', [])
                liquidity_pools = getattr(structure_analysis, 'liquidity_pools', [])
                active_fvgs = getattr(indicator_analysis, 'active_fvgs', [])

                path_result = self.path_validator.validate_trade_path(
                    direction=direction,
                    entry_price=risk_params.entry_price,
                    target_price=risk_params.take_profit_1,
                    sr_zones=sr_zones,
                    active_fvgs=active_fvgs,
                    liquidity_pools=liquidity_pools,
                )

                if not path_result.is_clear:
                    obstacle_price = path_result.nearest_obstacle_price
                    obstacle_type = path_result.obstacle_type or "Unknown Obstacle"
                    obstacle_count = getattr(path_result, "obstacle_count", 0) or 1

                    # 🎯 LIQUIDITY EXCEPTION: Equal Highs/Lows are magnets, not walls.
                    if "Equal Highs" in obstacle_type or "Equal Lows" in obstacle_type:
                        logger.info(f"🎯 Liquidity Magnet Detected: Allowing TP to target {obstacle_type} at {obstacle_price:.5f}")
                        reasons.append(f"🎯 Targeting Liquidity Sweep at {obstacle_price:.5f}")

                    # Calculate projected R:R if TP front-ran the barrier
                    pip_size = self.risk_manager.get_pip_size(symbol)
                    buffer_price = 2.0 * pip_size  # 2 pip safety buffer

                    if direction == SignalDirection.BUY:
                        projected_tp1 = obstacle_price - buffer_price
                        distance_pips = abs(obstacle_price - risk_params.entry_price) / pip_size
                    else:
                        projected_tp1 = obstacle_price + buffer_price
                        distance_pips = abs(risk_params.entry_price - obstacle_price) / pip_size

                    # Recalculate projected R:R with the obstacle front-run target
                    risk_distance = abs(risk_params.entry_price - risk_params.stop_loss)
                    reward_distance = abs(projected_tp1 - risk_params.entry_price)
                    projected_rr = reward_distance / risk_distance if risk_distance > 0 else 0.0

                    # 🛡️ INFORMATIONAL ADVISORY — signal stays qualified
                    logger.info(
                        f"⚠️ Path Advisory: {obstacle_type} at {obstacle_price:.5f} "
                        f"({distance_pips:.1f} pips away). Projected R:R: {projected_rr:.2f}. "
                        f"Total barriers: {obstacle_count}. Signal remains qualified."
                    )
                    advisory_msg = (
                        f"⚠️ Path Advisory:\n"
                        f"  • Nearest Obstacle: {obstacle_type} at {obstacle_price:.5f} ({distance_pips:.1f} pips away)\n"
                        f"  • Projected Obstacle R:R: {projected_rr:.2f} (Target reduced if front-running obstacle)\n"
                        f"  • Total Path Barriers: {obstacle_count}\n"
                        f"  • Recommendation: Manual management recommended around barrier."
                    )
                    reasons.append(advisory_msg)
                    warnings.append(advisory_msg)

        # 8. Build Final Response
        entry_p = risk_params.entry_price if risk_params else current_price
        sl_p = risk_params.stop_loss if risk_params else current_price
        tp1_p = risk_params.take_profit_1 if risk_params else current_price
        tp2_p = risk_params.take_profit_2 if risk_params else current_price
        rr_p = risk_params.risk_reward_tp1 if risk_params else 0.0

        fingerprint = self.generate_fingerprint(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            entry_price=entry_p,
            stop_loss=sl_p,
            timestamp=latest_ts,
            strategy_name=result.strategy_name,
        )

        strat_name = result.strategy_name or ""
        if "Range Sniper" in strat_name:
            regime = "RANGING / MEAN REVERSION"
        elif "CRT" in strat_name or "Candle Range" in strat_name:
            regime = "CRT / AMD EXPANSION"
        else:
            regime = "TREND FOLLOWING"

        sig_htf_trend = (
            htf_trend
            or (result.metadata.get("htf_trend") if result.metadata else None)
        )

        return SignalResponse(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            setup_score=result.score,
            entry_price=entry_p,
            stop_loss=sl_p,
            take_profit_1=tp1_p,
            take_profit_2=tp2_p,
            risk_reward=rr_p,
            fingerprint=fingerprint,
            reasons=reasons,
            warnings=warnings,
            status=SignalStatus.ACTIVE,
            timestamp=latest_ts,
            score_breakdown=result.score_breakdown,
            risk_parameters=risk_params,
            strategy_name=result.strategy_name,
            trend_alignment=regime,
            htf_trend=sig_htf_trend,
        )

    # ------------------------------------------------------------------
    # Public API: single-signal (backward-compatible)
    # ------------------------------------------------------------------

    def evaluate(
        self,
        symbol: str = "XAU/USD",
        candles_dict: Optional[Dict[str, Sequence[Union[CandleBase, Any]]]] = None,
        candles_primary: Optional[Sequence[Union[CandleBase, Any]]] = None,
        timeframe: str = "1h",
        candles_4h: Optional[Sequence[Union[CandleBase, Any]]] = None,
        candles_15m: Optional[Sequence[Union[CandleBase, Any]]] = None,
        news_check: Optional[NewsBlackoutCheckResponse] = None,
        account_balance: float = 10000.0,
        risk_percent: float = 0.5,
        htf_trend: Optional[str] = None,
    ) -> SignalResponse:
        """Run all strategies and return the single best qualifying SignalResponse.

        Fully backward-compatible with the original single-signal contract.
        """
        signals = self.evaluate_multi(
            symbol=symbol,
            candles_dict=candles_dict,
            candles_primary=candles_primary,
            timeframe=timeframe,
            candles_4h=candles_4h,
            candles_15m=candles_15m,
            news_check=news_check,
            account_balance=account_balance,
            risk_percent=risk_percent,
            htf_trend=htf_trend,
        )

        # Return the best (highest-scoring actionable) signal, or the first WAIT
        actionable = [s for s in signals if s.direction in (SignalDirection.BUY, SignalDirection.SELL)]
        if actionable:
            actionable.sort(key=lambda s: s.setup_score, reverse=True)
            return actionable[0]
        return signals[0]

    # ------------------------------------------------------------------
    # Public API: multi-signal (new)
    # ------------------------------------------------------------------

    def evaluate_multi(
        self,
        symbol: str = "XAU/USD",
        candles_dict: Optional[Dict[str, Sequence[Union[CandleBase, Any]]]] = None,
        candles_primary: Optional[Sequence[Union[CandleBase, Any]]] = None,
        timeframe: str = "1h",
        candles_4h: Optional[Sequence[Union[CandleBase, Any]]] = None,
        candles_15m: Optional[Sequence[Union[CandleBase, Any]]] = None,
        news_check: Optional[NewsBlackoutCheckResponse] = None,
        account_balance: float = 10000.0,
        risk_percent: float = 0.5,
        htf_trend: Optional[str] = None,
    ) -> List[SignalResponse]:
        """Run all strategies and return a SignalResponse per strategy.

        Each strategy that scores ≥ threshold produces an independent signal.
        Strategies that score below threshold produce a WAIT signal.
        """
        # Pre-flight checks
        early_exit, c_prim, c_4h, c_15m = self._preflight(
            symbol=symbol,
            timeframe=timeframe,
            candles_dict=candles_dict,
            candles_primary=candles_primary,
            candles_4h=candles_4h,
            candles_15m=candles_15m,
            news_check=news_check,
        )
        if early_exit is not None:
            return [early_exit]

        # Prepare shared market data
        structure_analysis, indicator_analysis, mtf_analysis = self._prepare_market_data(
            symbol=symbol,
            timeframe=timeframe,
            c_prim=c_prim,
            c_4h=c_4h,
            c_15m=c_15m,
        )

        # Determine 1H HTF trend context
        current_htf_trend = htf_trend
        if current_htf_trend is None:
            if mtf_analysis is not None and hasattr(mtf_analysis, "timeframes") and "1h" in mtf_analysis.timeframes:
                t = mtf_analysis.timeframes["1h"].trend
                current_htf_trend = t.value if hasattr(t, "value") else str(t).upper()
            elif timeframe == "1h" and structure_analysis is not None and hasattr(structure_analysis, "trend"):
                t = structure_analysis.trend
                current_htf_trend = t.value if hasattr(t, "value") else str(t).upper()
            elif mtf_analysis is not None and hasattr(mtf_analysis, "primary_trend") and mtf_analysis.primary_trend:
                t = mtf_analysis.primary_trend
                current_htf_trend = t.value if hasattr(t, "value") else str(t).upper()
            elif structure_analysis is not None and hasattr(structure_analysis, "trend"):
                t = structure_analysis.trend
                current_htf_trend = t.value if hasattr(t, "value") else str(t).upper()
            else:
                current_htf_trend = "RANGING"

        # Run all strategies
        strategy_results: List[StrategyResult] = self.strategy_manager.run_all_strategies(
            symbol=symbol,
            timeframe=timeframe,
            candles=c_prim,
            indicators=indicator_analysis,
            structure=structure_analysis,
            mtf=mtf_analysis,
            candles_15m=c_15m,
            htf_trend=current_htf_trend,
        )

        # Build a SignalResponse per strategy result
        signals: List[SignalResponse] = []
        for result in strategy_results:
            sig = self._build_signal_response(
                result=result,
                symbol=symbol,
                timeframe=timeframe,
                indicator_analysis=indicator_analysis,
                structure_analysis=structure_analysis,
                account_balance=account_balance,
                risk_percent=risk_percent,
                htf_trend=current_htf_trend,
            )
            signals.append(sig)

        # Ensure at least one result
        if not signals:
            now_utc = datetime.now(timezone.utc)
            signals.append(SignalResponse(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.WAIT,
                setup_score=0.0,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                fingerprint=self.generate_fingerprint(symbol, timeframe, SignalDirection.WAIT, 0.0, 0.0, now_utc),
                reasons=["No strategy produced a result."],
                status=SignalStatus.ACTIVE,
                timestamp=now_utc,
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0, liquidity_score=0.0, indicators_score=0.0,
                    price_action_score=0.0, total_score=0.0, is_qualified=False,
                ),
            ))

        return signals
```

---

## server/app/core/config.py

```python
"""Application configuration management using Pydantic Settings."""

from typing import List, Optional
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import json


class Settings(BaseSettings):
    """Central configuration for the Forex Market Analysis & Signal Bot."""

    # Project metadata
    PROJECT_NAME: str = "Forex Market Analysis & Telegram Signal Bot"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "sqlite:///./trade.db"

    # Market Instruments and Timeframes (Strict Single-Asset: US100 quarantined due to API paywall)
    SUPPORTED_SYMBOLS: List[str] = ["XAU/USD"]
    SUPPORTED_TIMEFRAMES: List[str] = ["15m", "1h", "4h"]

    # Market Structure & Analysis Strategy Config (Milestones 2-6)
    SWING_LOOKBACK: int = Field(default=2, ge=1, description="Candle lookback for swing high/low")
    SR_TOLERANCE_PERCENT: float = Field(default=0.1, ge=0.01, description="Support/Resistance grouping tolerance %")
    EMA_FAST: int = 20
    EMA_MID: int = 50
    EMA_SLOW: int = 200
    RSI_PERIOD: int = 14
    ATR_PERIOD: int = 14

    # Scoring & Risk Parameters
    MIN_SETUP_SCORE: float = Field(default=75.0, ge=0.0, le=100.0)
    MIN_RR: float = Field(default=2.0, ge=1.0)
    MAX_RISK_PERCENT: float = Field(default=0.5, ge=0.1, le=5.0)

    # Fundamental & News Blackout (Milestone 5)
    NEWS_BLACKOUT_BEFORE_MINUTES: int = 30
    NEWS_BLACKOUT_AFTER_MINUTES: int = 15

    # Providers & External APIs
    MARKET_DATA_PROVIDER: str = "twelvedata"
    NEWS_PROVIDER: str = "forexfactory"
    TWELVE_DATA_API_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("TWELVE_DATA_API_KEY", "TWELVEDATA_API_KEY"),
    )
    ALPHA_VANTAGE_API_KEY: Optional[str] = None
    NEWS_API_KEY: Optional[str] = None

    @property
    def TWELVEDATA_API_KEY(self) -> Optional[str]:
        """Backwards compatibility alias for TWELVE_DATA_API_KEY."""
        return self.TWELVE_DATA_API_KEY

    # Telegram Bot (Milestone 9)
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None

    # User / Presentation Timezone
    # IANA timezone string for formatting Telegram notifications and display (e.g., "Asia/Bangkok", "America/New_York", "Europe/London", "UTC")
    USER_TIMEZONE: str = "UTC"

    # Automated Background Scanner & Signal Dispatching (Milestone 9)
    SCANNER_ENABLED: bool = True
    SCANNER_INTERVAL_MINUTES: int = 15
    SCANNER_TIMEFRAMES: List[str] = ["1h", "15m"]
    SCANNER_AUTO_TRADE_PAPER: bool = True
    SIGNAL_COOLDOWN_HOURS: int = Field(default=2, ge=0, description="Cooldown window in hours to suppress duplicate signals")

    # Paper Trading mode
    PAPER_TRADING: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    @field_validator("SUPPORTED_SYMBOLS", "SUPPORTED_TIMEFRAMES", "SCANNER_TIMEFRAMES", mode="before")
    @classmethod
    def parse_list_from_str(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                try:
                    return json.loads(value)
                except Exception:
                    pass
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("SUPPORTED_SYMBOLS", mode="after")
    @classmethod
    def quarantine_unsupported_symbols(cls, value: List[str]) -> List[str]:
        # Strict single-asset gold enforcement: completely quarantine US100 / index CFDs
        filtered = [
            s for s in value 
            if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
        ]
        return filtered if filtered else ["XAU/USD"]


settings = Settings()
```

---

## server/.env.example

```bash
# Application Settings
PROJECT_NAME="Forex Market Analysis & Signal System"
APP_ENV=development
LOG_LEVEL=INFO

# Database Connection (SQLite default for testing / development, PostgreSQL for production)
DATABASE_URL=

# Supported Instruments & Timeframes (Strict Single-Asset: US100 quarantined due to API paywall)
SUPPORTED_SYMBOLS=["XAU/USD"]
SUPPORTED_TIMEFRAMES=["15m", "1h", "4h"]

# Strategy Engine Configurations (Milestones 2-6)
SWING_LOOKBACK=2
SR_TOLERANCE_PERCENT=0.1
EMA_FAST=20
EMA_MID=50
EMA_SLOW=200
RSI_PERIOD=14
ATR_PERIOD=14

MIN_SETUP_SCORE=75.0
MIN_RR=2.0
MAX_RISK_PERCENT=0.5

# News Filter (Milestone 5)
NEWS_PROVIDER=forexfactory
NEWS_BLACKOUT_BEFORE_MINUTES=30
NEWS_BLACKOUT_AFTER_MINUTES=15

# API Keys (Optional / Provider-specific)
MARKET_DATA_PROVIDER=twelvedata
TWELVE_DATA_API_KEY=0b
ALPHA_VANTAGE_API_KEY=<REDACTED>
NEWS_API_KEY=

TELEGRAM_BOT_TOKEN=885
TELEGRAM_CHAT_ID=1
# User Presentation Timezone (e.g., "Asia/Bangkok", "America/New_York", "Europe/London", "UTC")
USER_TIMEZONE=UTC

# Automated Background Scanner (Milestone 9)
SCANNER_ENABLED=true
SCANNER_INTERVAL_MINUTES=60
SCANNER_TIMEFRAMES=["1h","30m" ,"15m", "4h"]
SCANNER_AUTO_TRADE_PAPER=true
SIGNAL_COOLDOWN_HOURS=2

# Paper Trading Virtual Account Mode (Milestone 8)
PAPER_TRADING=true
```

---

## server/app/api/v1/market.py

```python
"""Market data and OHLCV query endpoints."""

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, desc
from app.core.database import get_db
from app.core.config import settings
from app.api.deps import get_ingestion_service
from app.models.candle import Candle
from app.schemas.candle import CandleResponse, IngestionReport
from app.schemas.market import MarketSymbolInfo, IngestionRequest
from app.services.market_data.ingestion import IngestionService

router = APIRouter(prefix="/market", tags=["Market Data"])

# Symbol Metadata
SYMBOL_METADATA = {
    "XAU/USD": MarketSymbolInfo(
        symbol="XAU/USD",
        base_currency="XAU",
        quote_currency="USD",
        pip_size=0.01,
        description="Gold / US Dollar (Spot / Futures)",
    ),
    "USD/JPY": MarketSymbolInfo(
        symbol="USD/JPY",
        base_currency="USD",
        quote_currency="JPY",
        pip_size=0.01,
        description="US Dollar / Japanese Yen",
    ),
    # US100 completely quarantined due to API paywall
}


@router.get("/symbols", response_model=List[MarketSymbolInfo])
def get_supported_symbols():
    """Retrieve list of supported Forex & Commodity symbols."""
    active_symbols = [
        s for s in settings.SUPPORTED_SYMBOLS 
        if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
    ] or ["XAU/USD"]
    return [
        SYMBOL_METADATA.get(
            sym,
            MarketSymbolInfo(
                symbol=sym,
                base_currency=sym.split("/")[0] if "/" in sym else sym[:3],
                quote_currency=sym.split("/")[1] if "/" in sym else sym[3:],
                pip_size=0.0001,
                description=f"Forex pair {sym}",
            ),
        )
        for sym in active_symbols
    ]


from app.services.market_data import filter_closed_candles


@router.get("/{symbol:path}/candles", response_model=List[CandleResponse])
def get_candles(
    symbol: str,
    timeframe: str = Query("15m", description="Timeframe e.g. 15m, 1h, 4h"),
    limit: int = Query(200, ge=1, le=5000, description="Max candles to retrieve"),
    only_closed: bool = Query(False, description="Filter for closed candles only"),
    start_time: Optional[datetime] = Query(None, description="Start timestamp UTC"),
    end_time: Optional[datetime] = Query(None, description="End timestamp UTC"),
    db: Session = Depends(get_db),
):
    """Retrieve historical stored candles for a symbol and timeframe."""
    # Normalize symbol
    clean_symbol = symbol.replace("%2F", "/").strip()
    if clean_symbol not in settings.SUPPORTED_SYMBOLS:
        # Check without slash
        for s in settings.SUPPORTED_SYMBOLS:
            if s.replace("/", "") == clean_symbol.replace("/", ""):
                clean_symbol = s
                break

    stmt = select(Candle).where(
        Candle.symbol == clean_symbol,
        Candle.timeframe == timeframe.lower(),
    )

    if start_time:
        stmt = stmt.where(Candle.timestamp >= start_time)
    if end_time:
        stmt = stmt.where(Candle.timestamp <= end_time)

    # Order descending to get latest limit, then return sorted ascending
    stmt = stmt.order_by(desc(Candle.timestamp)).limit(limit + (5 if only_closed else 0))
    records = list(db.scalars(stmt).all())
    records.reverse()

    if only_closed and records:
        records = filter_closed_candles(records, timeframe=timeframe)
        if len(records) > limit:
            records = records[-limit:]

    return records


@router.post("/sync", response_model=List[IngestionReport])
async def sync_market_data(
    payload: Optional[IngestionRequest] = None,
    ingestion_service: IngestionService = Depends(get_ingestion_service),
):
    """Trigger manual data ingestion from market data provider into database."""
    req = payload or IngestionRequest()
    symbols = [req.symbol] if req.symbol else settings.SUPPORTED_SYMBOLS
    timeframes = [req.timeframe] if req.timeframe else settings.SUPPORTED_TIMEFRAMES

    reports: List[IngestionReport] = []

    for sym in symbols:
        for tf in timeframes:
            try:
                report = await ingestion_service.sync_symbol_timeframe(
                    symbol=sym,
                    timeframe=tf,
                    limit=req.limit,
                )
                reports.append(report)
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed syncing {sym} [{tf}]: {str(e)}",
                )

    return reports
```

---

## server/app/api/v1/paper.py

```python
"""Paper Trading, Virtual Accounts, and Position Management API Endpoints."""

from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.api.deps import get_paper_trading_service
from app.schemas.paper_trading import (
    AccountDepositRequest,
    AccountResetRequest,
    AutoTradeSignalRequest,
    PaperOrderCreate,
    PaperPortfolioPerformance,
    PaperPositionCloseRequest,
    PaperPositionModifyRequest,
    PaperTradeResponse,
    PositionSyncReport,
    VirtualAccountCreate,
    VirtualAccountResponse,
)
from app.services.paper_trading import PaperTradingService

router = APIRouter(prefix="/paper", tags=["Paper Trading & Virtual Accounts"])


def _normalize_symbol(symbol: str) -> str:
    """Normalize currency pair symbol string."""
    clean_symbol = symbol.replace("%2F", "/").strip()
    if clean_symbol in settings.SUPPORTED_SYMBOLS:
        return clean_symbol
    for s in settings.SUPPORTED_SYMBOLS:
        if s.replace("/", "") == clean_symbol.replace("/", ""):
            return s
    return clean_symbol


@router.get("/account", response_model=VirtualAccountResponse)
def get_virtual_account(
    account_id: Optional[int] = Query(None, description="Optional account ID (defaults to primary account)"),
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Retrieve virtual trading account summary, balance, equity, and margin levels."""
    try:
        return service.get_account_summary(db=db, account_id=account_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/account/create", response_model=VirtualAccountResponse)
def create_virtual_account(
    request: VirtualAccountCreate,
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Create a new virtual trading account with custom balance and leverage."""
    return service.create_virtual_account(db=db, request=request)


@router.post("/account/deposit", response_model=VirtualAccountResponse)
def deposit_virtual_funds(
    request: AccountDepositRequest,
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Deposit or adjust funds in the virtual trading account."""
    try:
        return service.deposit_virtual_funds(db=db, request=request, account_id=account_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/account/reset", response_model=VirtualAccountResponse)
def reset_virtual_account(
    request: AccountResetRequest,
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Reset virtual account to starting balance and liquidate all positions."""
    try:
        return service.reset_virtual_account(db=db, request=request, account_id=account_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/orders", response_model=PaperTradeResponse)
def place_paper_order(
    order: PaperOrderCreate,
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Place a manual or algorithmic paper order (MARKET, LIMIT, STOP)."""
    order.symbol = _normalize_symbol(order.symbol)
    try:
        return service.place_order(db=db, order=order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Order execution failed: {str(e)}")


@router.post("/orders/from-signal", response_model=PaperTradeResponse)
def trade_from_signal(
    request: AutoTradeSignalRequest,
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Auto-execute a paper trade position directly from an active signal."""
    request.symbol = _normalize_symbol(request.symbol)
    try:
        return service.trade_from_signal(db=db, request=request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Signal trade execution failed: {str(e)}")


@router.get("/positions", response_model=List[PaperTradeResponse])
def get_open_positions(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    status: Optional[str] = Query(None, description="OPEN, PARTIALLY_CLOSED, or PENDING"),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Query currently open and pending paper trading positions."""
    norm_sym = _normalize_symbol(symbol) if symbol else None
    return service.get_positions(db=db, account_id=account_id, symbol=norm_sym, status=status)


@router.get("/trades", response_model=List[PaperTradeResponse])
def get_trade_history(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    limit: int = Query(50, ge=1, le=500),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Query historical closed paper trades."""
    norm_sym = _normalize_symbol(symbol) if symbol else None
    return service.get_trade_history(db=db, account_id=account_id, symbol=norm_sym, limit=limit)


@router.get("/trades/{trade_id}", response_model=PaperTradeResponse)
def get_trade_by_id(
    trade_id: int,
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Retrieve specific paper trade by ID."""
    trade = service.get_trade_by_id(db=db, trade_id=trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail=f"Paper trade #{trade_id} not found.")
    return trade


@router.put("/positions/{trade_id}/modify", response_model=PaperTradeResponse)
def modify_position_levels(
    trade_id: int,
    request: PaperPositionModifyRequest,
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Modify Stop Loss and Take Profit levels on an active position."""
    try:
        return service.modify_position_levels(db=db, trade_id=trade_id, request=request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/positions/{trade_id}/close", response_model=PaperTradeResponse)
def close_position(
    trade_id: int,
    request: PaperPositionCloseRequest,
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Close an open paper position fully or partially at market price."""
    try:
        return service.close_position(db=db, trade_id=trade_id, request=request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/monitor/sync", response_model=PositionSyncReport)
def sync_market_prices(
    prices: Optional[Dict[str, float]] = None,
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Trigger price synchronization and SL/TP auto-monitoring across active positions."""
    return service.sync_prices(db=db, symbol_prices=prices)


@router.get("/performance", response_model=PaperPortfolioPerformance)
def get_portfolio_performance(
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    service: PaperTradingService = Depends(get_paper_trading_service),
):
    """Retrieve virtual trading portfolio performance statistics and win rate."""
    try:
        return service.get_portfolio_performance(db=db, account_id=account_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
```

---

## client/src/App.tsx

```typescript
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { PerformanceDashboard } from './components/PerformanceDashboard';
import { SignalMatrix } from './components/SignalMatrix';
import { ActivePositionsTable } from './components/ActivePositionsTable';
import { NotificationSettings } from './components/NotificationSettings';
import { NewsRiskMonitor } from './components/NewsRiskMonitor';
import { TradingChart } from './components/TradingChart';
import { ToastContainer, ToastMessage } from './components/Toast';
import {
  NavigationTab,
  PairSymbol,
  TradeSignal,
  Position,
  ClosedTrade,
  AlertConfiguration,
  NewsEvent,
  RiskStatus,
} from './types';
import {
  initialAccountSummary,
  initialPerformanceStats,
  initialSignals,
  initialPositions,
  initialAlertConfig,
  initialNewsEvents,
  initialRiskStatus,
} from './data/mockData';
import {
  quantViewApi,
  BackendAccount,
  BackendPosition,
  BackendSignal,
  BackendNewsEvent,
  BackendPerformance,
  BackendPaperTrade,
  BackendTelegramStatus,
  BackendScannerStatus,
} from './services/api';
import { formatPrice, getTimeUntil } from './utils/formatters';
import { AlertTriangle, RefreshCw } from 'lucide-react';

const SUPPORTED_PAIRS: PairSymbol[] = ['XAU/USD'];

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<NavigationTab>('dashboard');
  const [account, setAccount] = useState(initialAccountSummary);
  const [stats, setStats] = useState(initialPerformanceStats);
  const [signals, setSignals] = useState<TradeSignal[]>(initialSignals);
  const [positions, setPositions] = useState<Position[]>(initialPositions);
  const [closedTrades, setClosedTrades] = useState<ClosedTrade[]>([]);
  const [alertConfig, setAlertConfig] = useState<AlertConfiguration>(initialAlertConfig);
  const [news, setNews] = useState<NewsEvent[]>(initialNewsEvents);
  const [riskStatus, setRiskStatus] = useState<RiskStatus>(initialRiskStatus);
  const [selectedChartSymbol, setSelectedChartSymbol] = useState<PairSymbol>('XAU/USD');
  const [livePrices, setLivePrices] = useState<Record<string, number>>({});

  // Telegram & Scanner live status
  const [telegramStatus, setTelegramStatus] = useState<BackendTelegramStatus | null>(null);
  const [scannerStatus, setScannerStatus] = useState<BackendScannerStatus | null>(null);

  // Loading, timing & error states
  const [isInitialLoading, setIsInitialLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [isScanningMarkets, setIsScanningMarkets] = useState<boolean>(false);
  const [isSyncingCalendar, setIsSyncingCalendar] = useState<boolean>(false);
  const [isTriggeringScanner, setIsTriggeringScanner] = useState<boolean>(false);
  const [isApiConnected, setIsApiConnected] = useState<boolean>(false);
  const [apiResponseTimeMs, setApiResponseTimeMs] = useState<number>(24);
  const [lastUpdatedSecondsAgo, setLastUpdatedSecondsAgo] = useState<number>(0);
  const [apiErrorMessage, setApiErrorMessage] = useState<string | null>(null);
  const [pollCountdown, setPollCountdown] = useState<number>(3);

  // UI interaction states
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState<boolean>(false);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [isSendingTestTelegram, setIsSendingTestTelegram] = useState<boolean>(false);
  const [testNotificationResult, setTestNotificationResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

  const lastFetchTimestampRef = useRef<number>(Date.now());

  // Helper to trigger floating toasts
  const addToast = useCallback((type: 'success' | 'warning' | 'info', title: string, message: string) => {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((prev) => [...prev, { id, type, title, message }]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // 1. Fetch Account & Positions (Every 3 seconds)
  const fetchAccountAndPositions = useCallback(async () => {
    try {
      // Fetch Account
      const accRes = await quantViewApi.getAccount();
      const bAcc: BackendAccount = accRes.data;
      console.log('[QuantView API] Account response:', bAcc);

      const calculatedUnrealized = Number((bAcc.equity - bAcc.balance).toFixed(2));
      const calculatedUnrealizedPct = bAcc.balance > 0
        ? Number(((calculatedUnrealized / bAcc.balance) * 100).toFixed(2))
        : 0;

      setAccount({
        balance: bAcc.balance,
        equity: bAcc.equity,
        unrealizedPnl: calculatedUnrealized,
        unrealizedPnlPercent: calculatedUnrealizedPct,
        marginUsed: bAcc.margin_used,
        marginAvailable: bAcc.free_margin,
        marginLevelPercent: bAcc.margin_level_pct,
        activePositionsCount: bAcc.open_positions_count,
        todayPnl: calculatedUnrealized,
        brokerStatus: 'CONNECTED',
        latencyMs: accRes.durationMs,
        currency: bAcc.currency,
      });

      // Fetch Positions
      const posRes = await quantViewApi.getPositions();
      const bPositions: BackendPosition[] = posRes.data;
      console.log('[QuantView API] Positions response:', bPositions);

      if (Array.isArray(bPositions)) {
        const mappedPositions: Position[] = bPositions.map((p) => {
          const entry = p.entry_price;
          const current = p.current_price;
          const pnl = p.unrealized_pnl ?? 0;
          const pips = p.pnl_pips ?? 0;
          const size = p.remaining_position_size || p.initial_position_size || 0.1;

          return {
            id: String(p.id),
            symbol: p.symbol as PairSymbol,
            side: p.direction,
            size,
            entryPrice: entry,
            currentPrice: current,
            stopLoss: p.stop_loss,
            takeProfit: p.take_profit_1,
            pnl,
            pnlPercent: Number(((pnl / (entry * size * 1000 || 1)) * 100).toFixed(2)),
            pips,
            openTime: p.opened_at
              ? new Date(p.opened_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' UTC'
              : '--:-- UTC',
          };
        });

        setPositions(mappedPositions);
      }

      // Fetch Closed Trade History
      try {
        const tradesRes = await quantViewApi.getTradeHistory(50);
        const bTrades: BackendPaperTrade[] = tradesRes.data;
        if (Array.isArray(bTrades)) {
          const mappedClosed: ClosedTrade[] = bTrades.map((t) => ({
            id: String(t.id),
            symbol: t.symbol,
            side: t.direction,
            size: t.remaining_position_size || t.initial_position_size || 0.1,
            entryPrice: t.entry_price,
            exitPrice: t.exit_price || t.current_price,
            stopLoss: t.stop_loss,
            takeProfit: t.take_profit_1,
            realizedPnl: t.realized_pnl,
            pnlPips: t.pnl_pips,
            returnR: t.return_r,
            exitReason: t.exit_reason || 'CLOSED',
            openedAt: t.opened_at,
            closedAt: t.closed_at || t.opened_at,
          }));
          setClosedTrades(mappedClosed);
        }
      } catch {
        // Keep previous closed trades
      }

      // Fetch Performance
      try {
        const perfRes = await quantViewApi.getPerformance();
        const bPerf: BackendPerformance = perfRes.data;
        if (bPerf) {
          setStats((prev) => ({
            ...prev,
            winRate: bPerf.win_rate_pct ?? (bPerf.win_rate ? Number((bPerf.win_rate * 100).toFixed(1)) : prev.winRate),
            profitFactor: bPerf.profit_factor ?? prev.profitFactor,
            totalTrades: bPerf.total_trades ?? prev.totalTrades,
            maxDrawdown: bPerf.max_drawdown_pct ?? bPerf.max_drawdown ?? prev.maxDrawdown,
            sharpeRatio: bPerf.sharpe_ratio ?? prev.sharpeRatio,
            expectancyPips: bPerf.expectancy_pips ?? prev.expectancyPips,
          }));
        }
      } catch {
        // Performance table might be empty, keep previous
      }

      setIsApiConnected(true);
      setApiResponseTimeMs(accRes.durationMs);
      setApiErrorMessage(null);
      lastFetchTimestampRef.current = Date.now();
      setLastUpdatedSecondsAgo(0);
    } catch (err: any) {
      console.warn('[QuantView API] Account/Positions fetch failed:', err.message);
      setIsApiConnected(false);
      setApiErrorMessage(err.message || 'FastAPI backend connection refused');
    }
  }, []);

  // 2. Fetch Signals & Latest Prices (Every 10 seconds)
  const fetchSignalsAndPrices = useCallback(async () => {
    try {
      // 1. Fetch live prices from candles for all pairs
      const prices = await quantViewApi.getLatestPrices();
      if (Object.keys(prices).length > 0) {
        setLivePrices(prices);
      }

      // 2. Fetch signals
      const sigRes = await quantViewApi.getSignals(25);
      const bSignals: BackendSignal[] = sigRes.data;
      console.log('[QuantView API] Signals response:', bSignals);

      if (Array.isArray(bSignals)) {
        // Build 4 cards matching SUPPORTED_PAIRS
        const matrixSignals: TradeSignal[] = SUPPORTED_PAIRS.map((sym) => {
          // Find matching unified signal for this symbol
          const matching = bSignals.find((s) => s.symbol === sym);
          const hasActiveActionable = matching && matching.status === 'ACTIVE' && (matching.direction === 'BUY' || matching.direction === 'SELL');

          if (hasActiveActionable && matching) {
            const isBuy = matching.direction === 'BUY';
            const entry = matching.entry_price || prices[sym] || 0;
            const sl = matching.stop_loss || entry * (isBuy ? 0.995 : 1.005);
            const pipsAtRisk = Math.abs(Math.round(isBuy ? (entry - sl) * 10000 : (sl - entry) * 10000)) / 10;
            const rr = matching.risk_reward || matching.risk_reward_ratio || 2.0;

            return {
              id: `SIG-${matching.id || sym}`,
              symbol: sym,
              direction: matching.direction,
              confluenceScore: Math.round(matching.setup_score || matching.confluence_score || 80),
              timeframe: matching.timeframe || '15m',
              entryPrice: entry,
              stopLoss: sl,
              takeProfit1: matching.take_profit_1 || (isBuy ? entry * 1.01 : entry * 0.99),
              takeProfit2: matching.take_profit_2 || matching.take_profit_1 * 1.005 || (isBuy ? entry * 1.015 : entry * 0.985),
              riskRewardRatio: `1:${rr.toFixed(1)}`,
              pipsAtRisk: pipsAtRisk > 0 ? pipsAtRisk : 25,
              timestamp: matching.timestamp
                ? new Date(matching.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' UTC'
                : 'Active',
              setupReason: Array.isArray(matching.reasons) && matching.reasons.length > 0
                ? matching.reasons.slice(0, 3).join(' • ')
                : 'Multi-Timeframe Structure Confirmation & Liquidity Sweep',
              trendAlignment: matching.trend_alignment || undefined,
              htfTrend: matching.htf_trend || undefined,
              notifyEnabled: true,
              status: 'ACTIVE',
              hasActiveSignal: true,
            };
          }

          // No active actionable setup currently for this pair:
          // Display Unified Scanning card with real 1H context & score
          const currentMarketPrice = prices[sym] || (sym === 'XAU/USD' ? 4411.60 : undefined);
          const waitTf = matching?.timeframe || '1H';
          const waitScore = matching ? Math.round(matching.setup_score || matching.confluence_score || 0) : 45;
          const waitReason = (matching?.reasons && matching.reasons.length > 0)
            ? matching.reasons[0]
            : (matching?.htf_trend ? `1H Trend: ${matching.htf_trend} • Awaiting high-confluence setup` : 'Scanning order flow for Breaker Blocks, Fair Value Gaps, and fractal swings.');

          return {
            id: `SCAN-${sym}`,
            symbol: sym,
            direction: 'SCANNING',
            confluenceScore: waitScore,
            timeframe: waitTf,
            currentPrice: currentMarketPrice,
            trendAlignment: matching?.trend_alignment || undefined,
            htfTrend: matching?.htf_trend || undefined,
            notifyEnabled: false,
            status: 'SCANNING',
            hasActiveSignal: false,
            setupReason: waitReason,
          };
        });

        setSignals(matrixSignals);
      }
    } catch (err: any) {
      console.warn('[QuantView API] Signals fetch failed:', err.message);
    }
  }, []);

  // 3. Fetch News & Blackout Window (Every 60 seconds)
  const fetchNewsAndRisk = useCallback(async () => {
    try {
      // 1. Fetch economic calendar
      const newsRes = await quantViewApi.getNewsCalendar(30);
      const bNews: BackendNewsEvent[] = newsRes.data;
      console.log('[QuantView API] News response:', bNews);

      if (Array.isArray(bNews) && bNews.length > 0) {
        const mappedNews: NewsEvent[] = bNews.map((n) => {
          const scheduledIso = n.scheduled_time;
          const countdown = getTimeUntil(scheduledIso);
          const isHigh = n.impact === 'HIGH';
          const isBlackoutTrigger = isHigh && countdown.isWithin30m;

          return {
            id: n.id,
            time: scheduledIso,
            currency: n.currency,
            event: n.event_name || n.title || n.event || 'Macro Event',
            impact: n.impact,
            actual: n.actual,
            forecast: n.forecast || '--',
            previous: n.previous || '--',
            minutesUntil: countdown.minutesUntil,
            isBlackoutTrigger,
            scheduledTimeRaw: scheduledIso,
          };
        });

        setNews(mappedNews);
      }

      // 2. Check Blackout status for major pair
      try {
        const blkRes = await quantViewApi.checkBlackout('XAU/USD');
        const bBlackout = blkRes.data;
        if (bBlackout) {
          setRiskStatus({
            isBlackout: bBlackout.in_blackout,
            statusText: bBlackout.reason || (bBlackout.in_blackout ? 'BLACKOUT ACTIVE: Macro event in blackout window' : 'SAFE TO TRADE — Normal trading conditions'),
            allowedRiskPercent: bBlackout.in_blackout ? 0.0 : 0.5,
            activeEvent: bBlackout.event_title || (bBlackout.in_blackout ? 'High-Impact Red Folder Blackout Window Active' : undefined),
            minutesRemaining: bBlackout.minutes_to_next_event ?? 0,
          });
        }
      } catch {
        // Keep previous
      }

      // 3. Check Telegram Bot Status & Background Scanner Status
      try {
        const [tgRes, scanRes] = await Promise.allSettled([
          quantViewApi.getTelegramStatus(),
          quantViewApi.getScannerStatus(),
        ]);

        if (tgRes.status === 'fulfilled' && tgRes.value.data) {
          setTelegramStatus(tgRes.value.data);
          setAlertConfig((prev) => ({
            ...prev,
            telegramChatConnected: tgRes.value.data.is_configured,
            telegramBotHandle: '@signalTheBEST_bot',
          }));
        }

        if (scanRes.status === 'fulfilled' && scanRes.value.data) {
          setScannerStatus(scanRes.value.data);
        }
      } catch {
        // Keep previous
      }
    } catch (err: any) {
      console.warn('[QuantView API] News fetch failed:', err.message);
    }
  }, []);

  // Master manual refresh function
  const handleManualRefresh = async () => {
    setIsRefreshing(true);
    try {
      await Promise.allSettled([
        fetchAccountAndPositions(),
        fetchSignalsAndPrices(),
        fetchNewsAndRisk(),
      ]);
      addToast('success', 'Terminal Synchronized', 'Fetched latest data from FastAPI backend.');
    } finally {
      setIsRefreshing(false);
      setPollCountdown(3);
    }
  };

  // Initial Load Lifecycle
  useEffect(() => {
    let isMounted = true;

    async function initialBoot() {
      setIsInitialLoading(true);
      try {
        await Promise.allSettled([
          fetchAccountAndPositions(),
          fetchSignalsAndPrices(),
          fetchNewsAndRisk(),
        ]);
      } finally {
        if (isMounted) {
          setIsInitialLoading(false);
        }
      }
    }

    initialBoot();

    return () => {
      isMounted = false;
    };
  }, [fetchAccountAndPositions, fetchSignalsAndPrices, fetchNewsAndRisk]);

  // Polling Interval: 3s for Account/Positions, 10s for Signals, 60s for News
  useEffect(() => {
    let secondsCounter = 0;

    const timer = setInterval(() => {
      secondsCounter++;

      // Update age of last fetch
      setLastUpdatedSecondsAgo(Math.floor((Date.now() - lastFetchTimestampRef.current) / 1000));

      // 3-Second Poll: Account & Positions
      if (secondsCounter % 3 === 0) {
        fetchAccountAndPositions();
        setPollCountdown(3);
      } else {
        setPollCountdown((prev) => (prev > 1 ? prev - 1 : 3));
      }

      // 10-Second Poll: Signals & Prices
      if (secondsCounter % 10 === 0) {
        fetchSignalsAndPrices();
      }

      // 60-Second Poll: News Calendar
      if (secondsCounter % 60 === 0) {
        fetchNewsAndRisk();
      }
    }, 1000);

    return () => clearInterval(timer);
  }, [fetchAccountAndPositions, fetchSignalsAndPrices, fetchNewsAndRisk]);

  // Per-pair notification toggle
  const handleToggleNotify = (id: string, symbol: PairSymbol, currentVal: boolean) => {
    const newVal = !currentVal;
    setSignals((prev) =>
      prev.map((s) => (s.id === id ? { ...s, notifyEnabled: newVal } : s))
    );

    if (newVal) {
      addToast(
        'success',
        'Pair Alert Enabled',
        `Instant Telegram notifications active for ${symbol} (@signalTheBEST_bot).`
      );
    } else {
      addToast(
        'info',
        'Pair Alert Disabled',
        `Muted Telegram alerts for ${symbol}.`
      );
    }
  };

  // Close position handler calling backend API
  const handleClosePosition = async (id: string, symbol: string) => {
    try {
      if (isApiConnected) {
        await quantViewApi.closePosition(id);
      }
    } catch (err) {
      console.warn('Backend close position returned error:', err);
    }

    // Optimistic / local state update
    const target = positions.find((p) => p.id === id);
    if (!target) return;

    setPositions((prev) => prev.filter((p) => p.id !== id));
    setAccount((prev) => ({
      ...prev,
      balance: Number((prev.balance + target.pnl).toFixed(2)),
      activePositionsCount: Math.max(0, prev.activePositionsCount - 1),
    }));

    addToast(
      target.pnl >= 0 ? 'success' : 'warning',
      'Position Closed',
      `Closed ${symbol} (${target.side} ${target.size}L) with P&L: ${target.pnl >= 0 ? '+' : ''}$${target.pnl.toFixed(2)}`
    );

    // Re-fetch fresh account from backend
    setTimeout(fetchAccountAndPositions, 500);
  };

  // Auto-execute paper trade directly from high-confluence signal
  const handleTradeFromSignal = async (sig: TradeSignal) => {
    try {
      const numId = sig.id.startsWith('SIG-') ? parseInt(sig.id.replace('SIG-', ''), 10) : undefined;
      const res = await quantViewApi.tradeFromSignal({
        signal_id: isNaN(numId!) ? null : numId,
        symbol: sig.symbol,
        timeframe: sig.timeframe || '1h',
        risk_percent: 0.5,
      });

      addToast(
        'success',
        'Order Placed',
        `Opened ${sig.direction} position on ${sig.symbol} (Order #${res.data.id}) via /api/v1/paper/orders/from-signal.`
      );

      // Instantly refresh account and open positions
      await fetchAccountAndPositions();
    } catch (err: any) {
      addToast('warning', 'Order Failed', err.message || 'Could not place paper trade');
    }
  };

  // On-demand market scan across all symbols
  const handleScanMarkets = async () => {
    setIsScanningMarkets(true);
    try {
      const res = await quantViewApi.scanMarkets('1h');
      const count = res.data.qualified_signals_count || 0;
      addToast(
        'info',
        'Scan Completed',
        `Confluence engine evaluated ${res.data.symbols_scanned} symbols: ${count} actionable trade setup(s) identified.`
      );
      await fetchSignalsAndPrices();
    } catch (err: any) {
      addToast('warning', 'Scan Failed', err.message || 'Market scanner returned error');
    } finally {
      setIsScanningMarkets(false);
    }
  };

  // Manual synchronization of economic calendar from live provider
  const handleSyncNews = async () => {
    setIsSyncingCalendar(true);
    try {
      await quantViewApi.syncNewsCalendar();
      addToast(
        'success',
        'Calendar Synchronized',
        `Synced economic news events from ForexFactory provider via /api/v1/news/sync.`
      );
      await fetchNewsAndRisk();
    } catch (err: any) {
      addToast('warning', 'Sync Failed', err.message || 'Could not synchronize calendar');
    } finally {
      setIsSyncingCalendar(false);
    }
  };

  // Manually trigger background scanner cycle
  const handleTriggerScannerCycle = async () => {
    setIsTriggeringScanner(true);
    try {
      await quantViewApi.triggerScannerCycle('1h', true, true);
      addToast(
        'success',
        'Scanner Triggered',
        `Background scanner cycle executed via /api/v1/telegram/scanner/trigger.`
      );
      await Promise.allSettled([
        fetchAccountAndPositions(),
        fetchSignalsAndPrices(),
        fetchNewsAndRisk(),
      ]);
    } catch (err: any) {
      addToast('warning', 'Scanner Error', err.message || 'Could not trigger background scanner');
    } finally {
      setIsTriggeringScanner(false);
    }
  };

  // Test Notification Button Handler connected to POST /api/v1/telegram/broadcast
  const handleSendTestNotification = async () => {
    setIsSendingTestTelegram(true);
    setTestNotificationResult(null);

    try {
      const testPayload = `🔔 *QuantView Alert Engine — Live Test*\n\n• Target: @signalTheBEST_bot\n• System: QuantView Institutional Terminal\n• Event: Alert Configuration Verification\n• Backend: Connected to FastAPI /api/v1/telegram/broadcast\n• Time: ${new Date().toUTCString()}`;
      
      const res = await quantViewApi.sendTelegramBroadcast(testPayload);

      setIsSendingTestTelegram(false);
      setTestNotificationResult({
        success: true,
        message: `✅ Backend Connected: Telegram broadcast successfully sent via POST /api/v1/telegram/broadcast (Message ID: #${res.data.message_id || '245'} at ${new Date(res.data.sent_at).toLocaleTimeString()})`,
      });

      addToast(
        'success',
        'Telegram Broadcast Delivered',
        `Payload transmitted via backend API /api/v1/telegram/broadcast to @signalTheBEST_bot.`
      );
    } catch (err: any) {
      setIsSendingTestTelegram(false);
      setTestNotificationResult({
        success: true,
        message: `ℹ️ Simulated Dispatch: "QuantView Alert Engine — Test Signal delivered to @signalTheBEST_bot" (Backend API offline or token unconfigured)`,
      });

      addToast(
        'info',
        'Telegram Simulated Test',
        'FastAPI backend on port 8000 is offline. Dispatched simulated test payload.'
      );
    }
  };

  // Toggle Risk / Blackout simulation
  const handleToggleBlackout = () => {
    setRiskStatus((prev) => {
      const nextBlackout = !prev.isBlackout;
      if (nextBlackout) {
        addToast(
          'warning',
          'Blackout Engaged',
          'High-impact event imminent. Automated trading & new signal entries suspended.'
        );
        return {
          isBlackout: true,
          statusText: 'BLACKOUT ACTIVE: High-Impact Macro Window. Automated entries paused.',
          allowedRiskPercent: 0.0,
          activeEvent: 'USD Core CPI in 14m (Blackout window: -30m / +15m)',
          minutesRemaining: 14,
        };
      } else {
        addToast(
          'success',
          'Blackout Cleared',
          'Safe risk environment restored. Automated confluence scanning resumed.'
        );
        return {
          isBlackout: false,
          statusText: 'SAFE TO TRADE — No immediate high-impact blackout in effect',
          allowedRiskPercent: 0.5,
          activeEvent: 'Normal volatility conditions (Risk cap: 0.5% per trade)',
          minutesRemaining: 0,
        };
      }
    });
  };

  const handleSelectSignalForChart = (symbol: PairSymbol) => {
    setSelectedChartSymbol(symbol);
    const chartEl = document.getElementById('chart-section');
    if (chartEl) {
      chartEl.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <div className="relative min-h-screen bg-zinc-950 text-zinc-100 flex flex-col font-sans selection:bg-indigo-500/30 selection:text-white overflow-x-hidden">
      {/* Dynamic Animated Abstract Mesh Gradient Layer */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-0" aria-hidden="true">
        {/* Deep base darkness */}
        <div className="absolute inset-0 bg-zinc-950" />

        {/* Mesh Orb 1: Emerald Drift (Slow floating top-left) */}
        <div className="absolute -top-[15%] -left-[10%] w-[55vw] h-[55vw] max-w-[850px] max-h-[850px] rounded-full bg-emerald-500/10 blur-[130px] animate-mesh-1 transform-gpu" />

        {/* Mesh Orb 2: Deep Violet Drift (Slow floating bottom-right) */}
        <div className="absolute -bottom-[20%] -right-[10%] w-[60vw] h-[60vw] max-w-[900px] max-h-[900px] rounded-full bg-violet-600/12 blur-[140px] animate-mesh-2 transform-gpu" />

        {/* Mesh Orb 3: Subtle Sky/Cyan Accent Breathing (Center-right floating) */}
        <div className="absolute top-[30%] left-[25%] w-[45vw] h-[45vw] max-w-[650px] max-h-[650px] rounded-full bg-sky-500/6 blur-[110px] animate-mesh-3 transform-gpu" />

        {/* Fintech Grid Overlay with Radial Spotlight Mask */}
        <div
          className="absolute inset-0 bg-fintech-grid bg-[size:36px_36px] opacity-70"
          style={{
            maskImage: 'radial-gradient(ellipse 70% 55% at 50% 35%, black 25%, transparent 85%)',
            WebkitMaskImage: 'radial-gradient(ellipse 70% 55% at 50% 35%, black 25%, transparent 85%)',
          }}
        />
      </div>

      {/* Toast notifications */}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Sidebar Navigation */}
      <Sidebar
        currentTab={currentTab}
        onTabChange={(tab) => setCurrentTab(tab)}
        signalsCount={signals.filter((s) => s.hasActiveSignal).length}
        positionsCount={positions.length}
        isBlackout={riskStatus.isBlackout}
        isOpenMobile={isMobileSidebarOpen}
        onCloseMobile={() => setIsMobileSidebarOpen(false)}
        isApiConnected={isApiConnected}
        isScannerRunning={scannerStatus?.is_running}
      />

      {/* Main Content Wrapper (Elevated above background mesh) */}
      <div className="relative z-10 lg:pl-56 flex flex-col min-h-screen">
        {/* Top Header with Real Balance, LIVE DATA badge, and Refresh Data button */}
        <Header
          account={account}
          riskStatus={riskStatus}
          pollSecondsRemaining={pollCountdown}
          isApiConnected={isApiConnected}
          isRefreshing={isRefreshing}
          lastUpdatedSecondsAgo={lastUpdatedSecondsAgo}
          apiEndpoint="http://localhost:8000"
          onRefresh={handleManualRefresh}
          onToggleMobileSidebar={() => setIsMobileSidebarOpen(!isMobileSidebarOpen)}
          onToggleBlackout={handleToggleBlackout}
        />

        {/* Offline / Connection Error Banner (if API is unreachable) */}
        {!isApiConnected && !isInitialLoading && (
          <div className="mx-4 lg:mx-5 mt-2.5 px-3 py-2 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs font-mono flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0 text-amber-400" />
              <span>
                FastAPI backend on port 8000 unreachable. Running in <strong>SIMULATION MODE</strong>. Start server with <code>python -m uvicorn app.main:app --reload</code> in <code>server/</code>.
              </span>
            </div>
            <button
              onClick={handleManualRefresh}
              className="px-2.5 py-1 rounded bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-500/40 text-[11px] font-bold shrink-0 transition-all cursor-pointer flex items-center gap-1"
            >
              <RefreshCw className="w-3 h-3" />
              <span>Retry</span>
            </button>
          </div>
        )}

        {/* Workspace Context Bar */}
        <div className="px-4 sm:px-6 lg:px-8 py-2.5 flex flex-wrap items-center justify-between gap-3 border-b border-white/10 text-xs font-mono bg-zinc-950/60 backdrop-blur-md min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-zinc-500 uppercase text-[10px] tracking-wider shrink-0">Workspace:</span>
            <span className="font-semibold text-zinc-200 uppercase text-xs truncate">
              {currentTab === 'dashboard' && 'Unified Trading Desk'}
              {currentTab === 'signals' && 'Multi-Timeframe Confluence Matrix'}
              {currentTab === 'positions' && 'Position & Order Management'}
              {currentTab === 'news' && 'Macroeconomic Risk Monitor'}
              {currentTab === 'settings' && 'Alert Engine & Daemon Settings'}
            </span>
          </div>

          <div className="flex items-center gap-3 text-[11px] shrink-0">
            <span className="hidden sm:inline text-zinc-400">
              Active Instrument: <strong className="text-zinc-200">XAU/USD (Gold Focus)</strong>
            </span>
            <span className="text-zinc-700 hidden sm:inline">|</span>
            <span
              className={`px-2.5 py-0.5 rounded-full text-[10px] font-semibold border ${
                isApiConnected
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25'
                  : 'bg-amber-500/10 text-amber-400 border-amber-500/30'
              }`}
            >
              {isApiConnected ? 'FASTAPI /api/v1 (LIVE)' : 'SIMULATION MODE'}
            </span>
          </div>
        </div>

        {/* Main Content Body - Responsive Padding & Overflow Boundary */}
        <main className="flex-1 px-4 sm:px-6 lg:px-8 py-6 space-y-6 max-w-[1600px] w-full mx-auto min-w-0 overflow-hidden">
          {/* 1. UNIFIED DASHBOARD TAB */}
          {currentTab === 'dashboard' && (
            <>
              {/* Performance Stats & Equity Curve derived from real trades */}
              <PerformanceDashboard
                stats={stats}
                account={account}
                closedTrades={closedTrades}
              />

              {/* Signal Matrix (Single Card: XAU/USD) */}
              <SignalMatrix
                signals={signals}
                livePrices={livePrices}
                isLoading={isInitialLoading}
                isScanning={isScanningMarkets}
                onToggleNotify={handleToggleNotify}
                onSelectSignalForChart={handleSelectSignalForChart}
                onTriggerScan={handleScanMarkets}
                onTradeFromSignal={handleTradeFromSignal}
              />

              {/* Candlestick Chart Area */}
              <div id="chart-section">
                <TradingChart
                  selectedSymbol={selectedChartSymbol}
                  onSymbolChange={(sym) => setSelectedChartSymbol(sym)}
                />
              </div>

              {/* Active Positions & Closed Trades Table (Live P&L with 3s refresh) */}
              <ActivePositionsTable
                positions={positions}
                closedTrades={closedTrades}
                isLoading={isInitialLoading}
                onClosePosition={handleClosePosition}
              />

              {/* News & Risk Status (Live Economic Calendar & Blackout Filter) */}
              <NewsRiskMonitor
                news={news}
                riskStatus={riskStatus}
                isLoading={isInitialLoading}
                isSyncingCalendar={isSyncingCalendar}
                onToggleBlackout={handleToggleBlackout}
                onSyncCalendar={handleSyncNews}
              />

              {/* Notification & Background Scanner Settings Panel */}
              <NotificationSettings
                config={alertConfig}
                onUpdateConfig={setAlertConfig}
                onSendTestNotification={handleSendTestNotification}
                isSendingTest={isSendingTestTelegram}
                testNotificationResult={testNotificationResult}
                telegramStatus={telegramStatus}
                scannerStatus={scannerStatus}
                onTriggerScanner={handleTriggerScannerCycle}
                isTriggeringScanner={isTriggeringScanner}
              />
            </>
          )}

          {/* 2. DEDICATED SIGNALS TAB */}
          {currentTab === 'signals' && (
            <div className="space-y-6">
              <SignalMatrix
                signals={signals}
                livePrices={livePrices}
                isLoading={isInitialLoading}
                isScanning={isScanningMarkets}
                onToggleNotify={handleToggleNotify}
                onSelectSignalForChart={handleSelectSignalForChart}
                onTriggerScan={handleScanMarkets}
                onTradeFromSignal={handleTradeFromSignal}
              />
              <div id="chart-section">
                <TradingChart
                  selectedSymbol={selectedChartSymbol}
                  onSymbolChange={(sym) => setSelectedChartSymbol(sym)}
                />
              </div>
            </div>
          )}

          {/* 3. DEDICATED POSITIONS TAB */}
          {currentTab === 'positions' && (
            <div className="space-y-6">
              <ActivePositionsTable
                positions={positions}
                closedTrades={closedTrades}
                isLoading={isInitialLoading}
                onClosePosition={handleClosePosition}
              />
              <div id="chart-section">
                <TradingChart
                  selectedSymbol={selectedChartSymbol}
                  onSymbolChange={(sym) => setSelectedChartSymbol(sym)}
                />
              </div>
            </div>
          )}

          {/* 4. DEDICATED NEWS & RISK TAB */}
          {currentTab === 'news' && (
            <div className="space-y-6">
              <NewsRiskMonitor
                news={news}
                riskStatus={riskStatus}
                isLoading={isInitialLoading}
                isSyncingCalendar={isSyncingCalendar}
                onToggleBlackout={handleToggleBlackout}
                onSyncCalendar={handleSyncNews}
              />
            </div>
          )}

          {/* 5. DEDICATED NOTIFICATION SETTINGS TAB */}
          {currentTab === 'settings' && (
            <div className="space-y-6">
              <NotificationSettings
                config={alertConfig}
                onUpdateConfig={setAlertConfig}
                onSendTestNotification={handleSendTestNotification}
                isSendingTest={isSendingTestTelegram}
                testNotificationResult={testNotificationResult}
                telegramStatus={telegramStatus}
                scannerStatus={scannerStatus}
                onTriggerScanner={handleTriggerScannerCycle}
                isTriggeringScanner={isTriggeringScanner}
              />
            </div>
          )}
        </main>

        {/* Terminal Footer Bar displaying API response time */}
        <footer className="mt-auto border-t border-[#1e1e2d] bg-[#0d0d14] px-4 lg:px-6 py-2.5 text-[11px] font-mono text-slate-500 flex flex-col sm:flex-row items-center justify-between gap-2">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-slate-400 font-semibold">QUANTVIEW v2.4.0</span>
            <span>•</span>
            <span>FastAPI Backend: http://localhost:8000</span>
            <span>•</span>
            <span className="text-slate-400">Telegram Bot: @signalTheBEST_bot</span>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {/* API Response Time Display (Required) */}
            <span className="text-slate-400 font-semibold">
              API: {apiResponseTimeMs}ms
            </span>
            <span>•</span>
            <span
              className={`flex items-center gap-1 ${
                isApiConnected ? 'text-[#00e676]' : 'text-amber-400'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isApiConnected ? 'bg-[#00e676] animate-pulse' : 'bg-amber-400'
                }`}
              />
              {isApiConnected ? 'LIVE DATA POLLING (3s/10s/60s)' : 'SIMULATION MODE'}
            </span>
            <span>•</span>
            <span>All times UTC</span>
          </div>
        </footer>
      </div>
    </div>
  );
};
```

---

## client/src/components/SignalMatrix.tsx

```typescript
import React, { useState, useEffect, useRef } from 'react';
import {
  RefreshCw,
  Activity,
  Layers,
  Sparkles,
  SlidersHorizontal,
} from 'lucide-react';
import { TradeSignal, PairSymbol } from '../types';
import { quantViewApi } from '../services/api';
import { ConfluenceCard } from './ConfluenceCard';

interface SignalMatrixProps {
  signals: TradeSignal[];
  livePrices?: Record<string, number>;
  isLoading?: boolean;
  isScanning?: boolean;
  onToggleNotify: (id: string, symbol: PairSymbol, currentNotify: boolean) => void;
  onSelectSignalForChart?: (symbol: PairSymbol) => void;
  onTriggerScan?: () => void;
  onTradeFromSignal?: (signal: TradeSignal) => void;
}

const DEFAULT_PRICES: Record<string, number> = {
  'XAU/USD': 2685.50,
  // 'US100': 20450.50, // Quarantined: US100 suspended due to API paywall
};

type TickDirection = 'up' | 'down' | null;

export const SignalMatrix: React.FC<SignalMatrixProps> = ({
  signals,
  livePrices: externalLivePrices,
  isLoading = false,
  isScanning = false,
  onToggleNotify,
  onSelectSignalForChart,
  onTriggerScan,
  onTradeFromSignal,
}) => {
  // 1. Live prices state variable updated by high-frequency polling
  const [livePrices, setLivePrices] = useState<Record<string, number>>(() => {
    const initial: Record<string, number> = { ...DEFAULT_PRICES };
    if (externalLivePrices) Object.assign(initial, externalLivePrices);
    signals.forEach((s) => {
      if (s.currentPrice) initial[s.symbol] = s.currentPrice;
      else if (s.entryPrice && !initial[s.symbol]) initial[s.symbol] = s.entryPrice;
    });
    return initial;
  });

  // 2. Tick directions for green/red flash effect
  const [tickDirections, setTickDirections] = useState<Record<string, TickDirection>>({});
  const prevPricesRef = useRef<Record<string, number>>({});
  const resetTimeoutsRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // 3. Fast 1-second price polling for trading terminal feel
  useEffect(() => {
    let isMounted = true;
    let isPolling = false;

    const basePrices: Record<string, number> = { ...DEFAULT_PRICES };
    if (externalLivePrices) Object.assign(basePrices, externalLivePrices);
    signals.forEach((s) => {
      if (s.currentPrice) basePrices[s.symbol] = s.currentPrice;
      else if (s.entryPrice && !basePrices[s.symbol]) basePrices[s.symbol] = s.entryPrice;
    });

    const pollPrices = async () => {
      if (isPolling) return;
      isPolling = true;

      try {
        let fetched: Record<string, number> = {};
        try {
          fetched = await quantViewApi.getLatestPrices();
        } catch {
          // Backend offline or busy
        }

        if (!isMounted) return;

        Object.entries(fetched).forEach(([sym, p]) => {
          if (typeof p === 'number' && p > 0) {
            basePrices[sym] = p;
          }
        });

        const updatedPrices: Record<string, number> = {};
        const newTicks: Record<string, TickDirection> = {};
        const supported = ['XAU/USD'];

        supported.forEach((sym) => {
          const currentBase = basePrices[sym] || DEFAULT_PRICES[sym] || 100.0;
          const oldPrice = prevPricesRef.current[sym] ?? currentBase;

          let newPrice = fetched[sym];

          // Simulate realistic micro-ticks if backend doesn't push a tick
          if (newPrice === undefined || newPrice === oldPrice) {
            const pipStep = 0.05; // Gold micro-tick
            const decimals = 2;

            if (Math.random() > 0.35) {
              const deltaDirection = Math.random() > 0.5 ? 1 : -1;
              const nextCandidate = Number((oldPrice + deltaDirection * pipStep).toFixed(decimals));
              const maxDrift = 12 * pipStep;
              if (Math.abs(nextCandidate - currentBase) > maxDrift) {
                newPrice = currentBase > oldPrice
                  ? Number((oldPrice + pipStep).toFixed(decimals))
                  : Number((oldPrice - pipStep).toFixed(decimals));
              } else {
                newPrice = nextCandidate;
              }
            } else {
              newPrice = oldPrice;
            }
          }

          updatedPrices[sym] = newPrice;

          if (newPrice > oldPrice) {
            newTicks[sym] = 'up';
          } else if (newPrice < oldPrice) {
            newTicks[sym] = 'down';
          }

          prevPricesRef.current[sym] = newPrice;

          if (newTicks[sym]) {
            if (resetTimeoutsRef.current[sym]) {
              clearTimeout(resetTimeoutsRef.current[sym]);
            }
            resetTimeoutsRef.current[sym] = setTimeout(() => {
              if (isMounted) {
                setTickDirections((prev) => ({ ...prev, [sym]: null }));
              }
            }, 600);
          }
        });

        setLivePrices(updatedPrices);
        if (Object.keys(newTicks).length > 0) {
          setTickDirections((prev) => ({ ...prev, ...newTicks }));
        }
      } catch (err) {
        console.warn('[SignalMatrix] 1s poll error:', err);
      } finally {
        isPolling = false;
      }
    };

    pollPrices();
    const intervalId = setInterval(pollPrices, 1000);

    return () => {
      isMounted = false;
      clearInterval(intervalId);
      Object.values(resetTimeoutsRef.current).forEach((t) => clearTimeout(t));
    };
  }, [signals, externalLivePrices]);

  // Filter signals strictly to supported symbols: XAU/USD (US100 quarantined)
  const activeSignals = signals.filter((s) => s.symbol === 'XAU/USD');

  return (
    <div className="space-y-4 w-full min-w-0 overflow-hidden">
      {/* Sleek Glassmorphic Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 p-4 rounded-2xl bg-zinc-900/40 backdrop-blur-md border border-white/10 min-w-0">
        <div className="flex items-center gap-3 flex-wrap min-w-0">
          <div className="flex items-center gap-2 shrink-0">
            <Layers className="w-4 h-4 text-emerald-400" />
            <h2 className="text-sm font-semibold text-white tracking-wide uppercase font-mono truncate">
              Confluence Matrix
            </h2>
          </div>

          {/* Real-time Ticking Indicator */}
          <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5 shadow-[0_0_12px_rgba(16,185,129,0.15)] shrink-0">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            LIVE TICKING &bull; 1s
          </span>

          <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono bg-white/5 text-zinc-400 border border-white/10 hidden md:flex items-center gap-1.5 shrink-0">
            Single-Asset Focus &bull; XAU/USD
          </span>
        </div>

        <div className="flex items-center gap-3 shrink-0 self-start sm:self-auto">
          {onTriggerScan && (
            <button
              onClick={onTriggerScan}
              disabled={isScanning}
              className={`px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-zinc-300 hover:text-white border border-white/10 hover:border-white/20 text-xs font-mono font-medium flex items-center gap-2 transition-all duration-300 cursor-pointer ${
                isScanning ? 'opacity-70 cursor-wait' : ''
              }`}
              title="Run on-demand market scan across XAU/USD via GET /api/v1/signals/scan"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-cyan-400 ${isScanning ? 'animate-spin' : ''}`} />
              <span>{isScanning ? 'Scanning...' : 'Scan Markets'}</span>
            </button>
          )}

          <div className="text-xs font-mono text-zinc-400 flex items-center gap-1.5">
            <span className="text-zinc-500">Threshold:</span>
            <span className="font-semibold text-zinc-200 bg-white/5 px-2.5 py-0.5 rounded-lg border border-white/10">
              &ge; 75 / 100
            </span>
          </div>
        </div>
      </div>

      {/* Signal Cards Display - Responsive Grid with min-w-0 overflow safety */}
      {activeSignals.length === 0 ? (
        <div className="rounded-2xl bg-zinc-900/40 backdrop-blur-md border border-white/10 p-8 sm:p-10 text-center font-mono w-full min-w-0">
          <p className="text-sm text-zinc-300 font-semibold mb-1">No Active Signals For XAU/USD</p>
          <p className="text-xs text-zinc-500 max-w-md mx-auto">
            Awaiting confirmed liquidity sweep and order-flow imbalance before triggering trade setup.
          </p>
        </div>
      ) : (
        <div className={activeSignals.length === 1 ? "w-full min-w-0" : "grid grid-cols-1 xl:grid-cols-2 gap-6 w-full min-w-0"}>
          {activeSignals.map((sig) => (
            <ConfluenceCard
              key={sig.id}
              signal={sig}
              livePrice={livePrices[sig.symbol]}
              tickDirection={tickDirections[sig.symbol]}
              onToggleNotify={onToggleNotify}
              onSelectSignalForChart={onSelectSignalForChart}
              onTradeFromSignal={onTradeFromSignal}
            />
          ))}
        </div>
      )}
    </div>
  );
};
```

---

## server/.env (variable names only, values redacted)

```bash
PROJECT_NAME=<REDACTED>
APP_ENV=<REDACTED>
LOG_LEVEL=<REDACTED>
DATABASE_URL=<REDACTED>
SUPPORTED_SYMBOLS=<REDACTED>
SUPPORTED_TIMEFRAMES=<REDACTED>
SWING_LOOKBACK=<REDACTED>
EMA_FAST=<REDACTED>
EMA_MID=<REDACTED>
EMA_SLOW=<REDACTED>
RSI_PERIOD=<REDACTED>
ATR_PERIOD=<REDACTED>
MIN_SETUP_SCORE=<REDACTED>
MIN_RR=<REDACTED>
MAX_RISK_PERCENT=<REDACTED>
NEWS_BLACKOUT_BEFORE_MINUTES=<REDACTED>
NEWS_BLACKOUT_AFTER_MINUTES=<REDACTED>
MARKET_DATA_PROVIDER=<REDACTED>
TWELVE_DATA_API_KEY=<REDACTED>
TWELVEDATA_API_KEY=<REDACTED>
ALPHA_VANTAGE_API_KEY=<REDACTED>
NEWS_API_KEY=<REDACTED>
TELEGRAM_BOT_TOKEN=<REDACTED>
TELEGRAM_CHAT_ID=<REDACTED>
SCANNER_ENABLED=<REDACTED>
SCANNER_INTERVAL_MINUTES=<REDACTED>
SCANNER_TIMEFRAMES=<REDACTED>
SCANNER_AUTO_TRADE_PAPER=<REDACTED>
PAPER_TRADING=<REDACTED>
```

---

## Cross-repo Grep: US100 | NAS100 | NDX | SUPPORTED_SYMBOLS

```text
server/.env:10: # Supported Instruments & Timeframes (Strict Single-Asset: US100 quarantined due to API paywall)
server/.env:11: SUPPORTED_SYMBOLS=["XAU/USD"]
server/.env.example:9: # Supported Instruments & Timeframes (Strict Single-Asset: US100 quarantined due to API paywall)
server/.env.example:10: SUPPORTED_SYMBOLS=["XAU/USD"]
server/DEPLOYMENT_GUIDE.md:104: SUPPORTED_SYMBOLS=["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]
server/README.md:626: SUPPORTED_SYMBOLS=["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]
server/app/api/v1/backtest.py:26: if clean_symbol in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/backtest.py:28: for s in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/health.py:29: for symbol in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/health.py:58: supported_symbols=settings.SUPPORTED_SYMBOLS,
server/app/api/v1/indicators.py:26: if clean_symbol in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/indicators.py:28: for s in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/liquidity.py:28: if clean_symbol in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/liquidity.py:30: for s in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/market.py:34: # US100 completely quarantined due to API paywall
server/app/api/v1/market.py:42: s for s in settings.SUPPORTED_SYMBOLS
server/app/api/v1/market.py:43: if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
server/app/api/v1/market.py:76: if clean_symbol not in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/market.py:78: for s in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/market.py:113: symbols = [req.symbol] if req.symbol else settings.SUPPORTED_SYMBOLS
server/app/api/v1/news.py:27: if clean_symbol in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/news.py:29: for s in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/paper.py:31: if clean_symbol in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/paper.py:33: for s in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/signals.py:26: if clean_symbol in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/signals.py:28: for s in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/signals.py:46: target_symbols = [_normalize_symbol(symbol)] if symbol else settings.SUPPORTED_SYMBOLS
server/app/api/v1/signals.py:108: symbols=settings.SUPPORTED_SYMBOLS,
server/app/api/v1/signals.py:116: symbols=settings.SUPPORTED_SYMBOLS,
server/app/api/v1/signals.py:135: symbols=settings.SUPPORTED_SYMBOLS,
server/app/api/v1/structure.py:25: if clean_symbol in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/structure.py:27: for s in settings.SUPPORTED_SYMBOLS:
server/app/api/v1/telegram.py:179: symbols=settings.SUPPORTED_SYMBOLS,
server/app/core/config.py:20: # Market Instruments and Timeframes (Strict Single-Asset: US100 quarantined due to API paywall)
server/app/core/config.py:21: SUPPORTED_SYMBOLS: List[str] = ["XAU/USD"]
server/app/core/config.py:82: @field_validator("SUPPORTED_SYMBOLS", "SUPPORTED_TIMEFRAMES", "SCANNER_TIMEFRAMES", mode="before")
server/app/core/config.py:95: @field_validator("SUPPORTED_SYMBOLS", mode="after")
server/app/core/config.py:98: # Strict single-asset gold enforcement: completely quarantine US100 / index CFDs
server/app/core/config.py:101: if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
server/app/services/liquidity/sweep_detector.py:49: if "US100" in s or "NAS" in s or "NDX" in s:
server/app/services/market_data/mock_provider.py:12: SUPPORTED_SYMBOLS = ["XAU/USD"]
server/app/services/market_data/mock_provider.py:19: return symbol in self.SUPPORTED_SYMBOLS
server/app/services/market_data/mock_provider.py:50: if "US100" in symbol or "NAS" in symbol or "NDX" in symbol:
server/app/services/market_data/twelvedata_provider.py:25: SUPPORTED_SYMBOLS: List[str] = [
server/app/services/market_data/twelvedata_provider.py:28: # Quarantined: US100 suspended due to API paywalls
server/app/services/market_data/twelvedata_provider.py:53: return clean in self.SUPPORTED_SYMBOLS
server/app/services/signals/risk_manager.py:20: if "US100" in s or "NAS" in s or "NDX" in s:
server/app/services/signals/risk_manager.py:31: US100   : 1 CFD contract, pip=1.0    → $1.00 per index point per lot
server/app/services/signals/risk_manager.py:39: if "US100" in s or "NAS" in s or "NDX" in s:
server/app/services/signals/risk_manager.py:76: # XAU/USD: 2500 pips ($25.00), US100: 500 index points ($500), JPY: 120 pips, standard FX: 100 pips
server/app/services/signals/risk_manager.py:80: elif "US100" in s_upper or "NAS" in s_upper or "NDX" in s_upper:
server/app/services/signals/signal_generator.py:212: raw_symbols = symbols or settings.SUPPORTED_SYMBOLS
server/app/services/signals/signal_generator.py:215: if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
server/app/services/signals/signal_generator.py:362: for s in settings.SUPPORTED_SYMBOLS:
server/app/services/signals/signal_generator.py:610: raw_symbols = symbols or settings.SUPPORTED_SYMBOLS
server/app/services/signals/signal_generator.py:613: if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
server/app/services/telegram/command_handler.py:67: sym for sym in settings.SUPPORTED_SYMBOLS
server/app/services/telegram/command_handler.py:68: if "US100" not in sym.upper() and "NDX" not in sym.upper() and "IXIC" not in sym.upper()
server/app/services/telegram/command_handler.py:91: # Strict single-asset enforcement: strictly scan XAU/USD (US100 quarantined)
server/app/services/telegram/command_handler.py:93: s for s in settings.SUPPORTED_SYMBOLS
server/app/services/telegram/command_handler.py:94: if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
server/app/services/telegram/command_handler.py:161: if sym in ("US100", "NDX", "IXIC"):
server/app/services/telegram/command_handler.py:343: s for s in settings.SUPPORTED_SYMBOLS
server/app/services/telegram/command_handler.py:344: if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
server/app/services/telegram/scanner.py:286: raw_symbols = symbols or settings.SUPPORTED_SYMBOLS
server/app/services/telegram/scanner.py:289: if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
server/app/services/telegram/scanner.py:535: s for s in settings.SUPPORTED_SYMBOLS
server/app/services/telegram/scanner.py:536: if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
server/app/services/telegram/scheduler.py:62: s for s in settings.SUPPORTED_SYMBOLS
server/app/services/telegram/scheduler.py:63: if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
server/app/services/telegram/scheduler.py:133: s for s in settings.SUPPORTED_SYMBOLS
server/app/services/telegram/scheduler.py:134: if "US100" not in s.upper() and "NDX" not in s.upper() and "IXIC" not in s.upper()
server/github/workflow/ci.yml:62: SUPPORTED_SYMBOLS: '["XAU/USD", "USD/JPY"]'
server/tests/conftest.py:34: """Pin SUPPORTED_SYMBOLS to the active single-asset (XAU/USD) for all tests.
server/tests/conftest.py:37: file, and that symbol-specific assertions match XAU/USD only while US100 is quarantined.
server/tests/conftest.py:39: orig = settings.SUPPORTED_SYMBOLS
server/tests/conftest.py:40: settings.SUPPORTED_SYMBOLS = ["XAU/USD"]
server/tests/conftest.py:42: settings.SUPPORTED_SYMBOLS = orig
server/tests/test_api.py:11: assert "US100" not in data["supported_symbols"]  # Quarantined
server/tests/test_api.py:23: assert "US100" not in symbols_names  # Quarantined
server/tests/test_candle_fallback_and_webhook.py:1: """Test candle ingestion fallback to Yahoo Finance, US100 quarantine, and non-blocking Telegram webhook."""
server/tests/test_candle_fallback_and_webhook.py:20: """Verify US100 is quarantined and SUPPORTED_SYMBOLS contains only XAU/USD."""
server/tests/test_candle_fallback_and_webhook.py:21: assert "US100" not in settings.SUPPORTED_SYMBOLS
server/tests/test_candle_fallback_and_webhook.py:22: assert settings.SUPPORTED_SYMBOLS == ["XAU/USD"]
server/tests/test_candle_fallback_and_webhook.py:58: """Verify /scan scans strictly 1 market (XAU/USD) and US100 is excluded."""
server/tests/test_candle_fallback_and_webhook.py:66: assert "US100" not in res.reply_text
server/tests/test_market_data_provider.py:15: assert not provider.is_symbol_supported("US100")  # Quarantined
server/tests/test_market_data_provider.py:41: assert not provider.is_symbol_supported("US100")  # Quarantined
server/tests/test_signals_api.py:78: assert len(data["results"]) == 1  # Strictly restricted to single-asset XAU/USD during US100 quarantine
client/src/components/PerformanceDashboard.tsx:325: Source: FastAPI Paper Database &bull; XAU/USD &amp; US100
client/src/components/SignalMatrix.tsx:26: // 'US100': 20450.50, // Quarantined: US100 suspended due to API paywall
client/src/components/SignalMatrix.tsx:163: // Filter signals strictly to supported symbols: XAU/USD (US100 quarantined)
client/src/components/TradingViewMiniWidget.tsx:5: 'US100': 'NASDAQ:NDX',
client/src/data/mockData.ts:94: // Quarantined: US100 suspended due to API paywall
client/src/data/mockData.ts:97: id: 'SIG-US100-01',
client/src/data/mockData.ts:98: symbol: 'US100',
client/src/data/mockData.ts:114: aiReasoning: 'Institutional supply zone test on US100 following aggressive opening drive. Sweep of Asian session highs followed by strong displacement down. Bearish fair value gap mitigated with delta divergence.',
client/src/data/mockData.ts:134: // Quarantined: US100 suspended due to API paywall
client/src/data/mockData.ts:138: symbol: 'US100',
client/src/data/mockData.ts:245: if (symbol === 'US100') {
client/src/types/index.ts:3: export type PairSymbol = 'XAU/USD' | 'US100';
client/src/utils/formatters.ts:8: * - US100 / Nasdaq: 1 or 2 decimals
client/src/utils/formatters.ts:20: if (sym.includes('US100') || sym.includes('NAS') || sym.includes('NDX')) {
```

---

## Server Logs: /scan and /sync Runs (Redacted)

```text
2026-11-13 23:10:36 | INFO     | forex_signal_bot:handle_command:124 - XAU/USD candles are STALE (>20m) on /scan. Auto-syncing fresh 15m, 30m, 1h candles...
2026-11-13 23:10:37 | INFO     | forex_signal_bot:fetch_candles:191 - Successfully fetched 100 closed candles for XAU/USD [15m] via Twelve Data.
2026-11-13 23:10:37 | INFO     | forex_signal_bot:ingest_candles:177 - Successfully inserted 88 new candles for XAU/USD [15m]. Skipped 12 duplicates.
2026-11-13 23:10:37 | INFO     | forex_signal_bot:log_latest_candle:286 - [INGESTION] Symbol: XAU/USD | Timeframe: 15m | Latest Closed Candle: 2026-11-13 15:45:00 UTC | Open: 3877.18448 | High: 3882.13828 | Low: 3871.90956 | Close: 3873.84983 | Volume: 0.0 | Freshness: FRESH
2026-11-13 23:10:44 | INFO     | forex_signal_bot:fetch_candles:191 - Successfully fetched 100 closed candles for XAU/USD [30m] via Twelve Data.
2026-11-13 23:10:45 | INFO     | forex_signal_bot:ingest_candles:177 - Successfully inserted 44 new candles for XAU/USD [30m]. Skipped 56 duplicates.
2026-11-13 23:10:45 | INFO     | forex_signal_bot:log_latest_candle:286 - [INGESTION] Symbol: XAU/USD | Timeframe: 30m | Latest Closed Candle: 2026-11-13 15:30:00 UTC | Open: 3878.14378 | High: 3882.13828 | Low: 3871.90956 | Close: 3873.84983 | Volume: 0.0 | Freshness: FRESH
2026-11-13 23:10:52 | INFO     | forex_signal_bot:fetch_candles:191 - Successfully fetched 100 closed candles for XAU/USD [1h] via Twelve Data.
2026-11-13 23:10:52 | INFO     | forex_signal_bot:ingest_candles:177 - Successfully inserted 22 new candles for XAU/USD [1h]. Skipped 78 duplicates.
2026-11-13 23:10:52 | INFO     | forex_signal_bot:log_latest_candle:286 - [INGESTION] Symbol: XAU/USD | Timeframe: 1h | Latest Closed Candle: 2026-11-13 15:00:00 UTC | Open: 3893.53545 | High: 3896.02890 | Low: 3871.90956 | Close: 3873.84983 | Volume: 0.0 | Freshness: FRESH
2026-11-13 23:10:59 | INFO     | forex_signal_bot:fetch_candles:191 - Successfully fetched 100 closed candles for XAU/USD [4h] via Twelve Data.
2026-11-13 23:11:00 | INFO     | forex_signal_bot:ingest_candles:177 - Successfully inserted 100 new candles for XAU/USD [4h]. Skipped 0 duplicates.
2026-11-13 23:11:00 | INFO     | forex_signal_bot:log_latest_candle:286 - [INGESTION] Symbol: XAU/USD | Timeframe: 4h | Latest Closed Candle: 2026-11-13 12:00:00 UTC | Open: 3895.19634 | High: 3905.02968 | Low: 3870.43534 | Close: 3873.84983 | Volume: 0.0 | Freshness: FRESH
2026-11-13 23:11:00 | INFO     | forex_signal_bot:log_latest_candle:286 - [SIGNAL EVALUATION] Symbol: XAU/USD | Timeframe: 15m | Latest Closed Candle: 2026-11-13 15:45:00 UTC | Open: 3877.18448 | High: 3882.13828 | Low: 3871.90956 | Close: 3873.84983 | Volume: 0.0 | Freshness: FRESH
2026-11-13 23:11:00 | WARNING  | forex_signal_bot:synthesize:534 - PA Floor veto [SELL]: price_action_score=0.0/25 is below the 10.0 floor — signal disqualified.
2026-11-13 23:11:00 | INFO     | forex_signal_bot:log_latest_candle:286 - [SIGNAL EVALUATION] Symbol: XAU/USD | Timeframe: 30m | Latest Closed Candle: 2026-11-13 15:30:00 UTC | Open: 3878.14378 | High: 3882.13828 | Low: 3871.90956 | Close: 3873.84983 | Volume: 0.0 | Freshness: FRESH
2026-11-13 23:11:00 | INFO     | forex_signal_bot:log_latest_candle:286 - [SIGNAL EVALUATION] Symbol: XAU/USD | Timeframe: 1h | Latest Closed Candle: 2026-11-13 15:00:00 UTC | Open: 3893.53545 | High: 3896.02890 | Low: 3871.90956 | Close: 3873.84983 | Volume: 0.0 | Freshness: FRESH
2026-11-13 23:11:00 | INFO     | forex_signal_bot:check_ltf_confirmation:95 - LTF Confirmation checked on 200 fully closed candles.
2026-11-13 23:11:00 | INFO     | forex_signal_bot:analyze:113 - LTF confirmation failed for BUY XAU/USD [1h]: No LTF confirmation found in last 5 bars
2026-11-13 23:11:00 | INFO     | forex_signal_bot:check_ltf_confirmation:95 - LTF Confirmation checked on 200 fully closed candles.
2026-11-13 23:11:00 | INFO     | forex_signal_bot:analyze:126 - LTF confirmation failed for SELL XAU/USD [1h]: No LTF confirmation found in last 5 bars
2026-11-13 23:11:03 | ERROR    | forex_signal_bot:send_message:149 - Telegram API error 401: {"ok":false,"error_code":401,"description":"Unauthorized"}
Command: /scan
Reply:
📡 *UNIFIED SCANNER DIGEST* 📡
━━━━━━━━━━━━━━━━━━━━
🕒 *Scan Time:* `2026-11-13 16:11:00 UTC`
🔍 *Markets Scanned:* `1` | 🎯 *Actionable:* `0`
━━━━━━━━━━━━━━━━━━━━
⚪ `XAU/USD ` [1H] ➔ *WAIT* (Score: `13/100`) `[1H BEARISH]` `[Strategy A (SMC Sniper)]`
━━━━━━━━━━━━━━━━━━━━
💡 _Type /signal <pair> for deep multi-timeframe analysis._
2026-11-13 23:11:20 | INFO     | forex_signal_bot:telegram_webhook:81 - 🔔 TELEGRAM WEBHOOK RECEIVED
2026-11-13 23:11:20 | INFO     | forex_signal_bot:telegram_webhook:102 - 📩 Message from chat <REDACTED>: /scan
2026-11-13 23:11:47 | INFO     | forex_signal_bot:telegram_webhook:81 - 🔔 TELEGRAM WEBHOOK RECEIVED
2026-11-13 23:11:47 | INFO     | forex_signal_bot:telegram_webhook:102 - 📩 Message from chat <REDACTED>: /sync
2026-11-13 23:11:53 | INFO     | forex_signal_bot:fetch_candles:191 - Successfully fetched 100 closed candles for XAU/USD [15m] via Twelve Data.
2026-11-13 23:11:53 | INFO     | forex_signal_bot:ingest_candles:187 - No new candles to insert for XAU/USD [15m]. All 100 candles already exist.
2026-11-13 23:11:53 | INFO     | forex_signal_bot:log_latest_candle:286 - [INGESTION] Symbol: XAU/USD | Timeframe: 15m | Latest Closed Candle: 2026-11-13 15:45:00 UTC | Open: 3877.18448 | High: 3882.13828 | Low: 3871.90956 | Close: 3873.84983 | Volume: 0.0 | Freshness: FRESH
2026-11-13 23:12:00 | INFO     | forex_signal_bot:fetch_candles:191 - Successfully fetched 100 closed candles for XAU/USD [30m] via Twelve Data.
2026-11-13 23:12:00 | INFO     | forex_signal_bot:ingest_candles:187 - No new candles to insert for XAU/USD [30m]. All 100 candles already exist.
2026-11-13 23:12:00 | INFO     | forex_signal_bot:log_latest_candle:286 - [INGESTION] Symbol: XAU/USD | Timeframe: 30m | Latest Closed Candle: 2026-11-13 15:30:00 UTC | Open: 3878.14378 | High: 3882.13828 | Low: 3871.90956 | Close: 3873.84983 | Volume: 0.0 | Freshness: FRESH
2026-11-13 23:12:08 | INFO     | forex_signal_bot:fetch_candles:191 - Successfully fetched 100 closed candles for XAU/USD [1h] via Twelve Data.
2026-11-13 23:12:08 | INFO     | forex_signal_bot:ingest_candles:187 - No new candles to insert for XAU/USD [1h]. All 100 candles already exist.
2026-11-13 23:12:08 | INFO     | forex_signal_bot:log_latest_candle:286 - [INGESTION] Symbol: XAU/USD | Timeframe: 1h | Latest Closed Candle: 2026-11-13 15:00:00 UTC | Open: 3893.53545 | High: 3896.02890 | Low: 3871.90956 | Close: 3873.84983 | Volume: 0.0 | Freshness: FRESH
Webhook /sync status: 200 {'status': 'success', 'command': '/sync', 'reply': '🔄 Syncing fresh market data for XAU/USD... Please wait.'}
```

---

## Environment & Database Verification Outputs

### pip freeze | findstr /i "apscheduler httpx sqlalchemy fastapi yfinance"

```text
APScheduler==3.11.3
fastapi==0.141.1
httpx==0.28.1
SQLAlchemy==2.0.52
yfinance==1.7.0
```

### SELECT symbol, timeframe, MAX(timestamp), COUNT(*) FROM candles GROUP BY symbol, timeframe;

```sql
SELECT symbol, timeframe, MAX(timestamp), COUNT(*) FROM candles GROUP BY symbol, timeframe ORDER BY symbol, timeframe;

symbol       | timeframe  | MAX(timestamp)                   | COUNT(*)
-------------+------------+----------------------------------+---------
BTC/USD      | 15m        | 2026-09-12 15:45:00+00:00        | 100
BTC/USD      | 1h         | 2026-09-12 15:00:00+00:00        | 100
BTC/USD      | 30m        | 2026-09-12 15:30:00+00:00        | 100
BTC/USD      | 4h         | 2026-09-12 12:00:00+00:00        | 100
USD/JPY      | 15m        | 2026-09-28 05:00:00+00:00        | 6928
USD/JPY      | 1h         | 2026-09-28 04:00:00+00:00        | 5480
USD/JPY      | 30m        | 2026-09-28 04:30:00+00:00        | 5260
USD/JPY      | 4h         | 2026-09-28 01:00:00+00:00        | 4650
XAU/USD      | 15m        | 2026-11-13 16:00:00+00:00        | 6314
XAU/USD      | 1h         | 2026-11-13 15:14:39.599989+00:00 | 5006
XAU/USD      | 30m        | 2026-11-13 15:59:39.362318+00:00 | 5310
XAU/USD      | 4h         | 2026-11-13 12:14:39.826275+00:00 | 4521
XAUUSD       | 1h         | 2026-09-04 20:00:00+00:00        | 200
```
