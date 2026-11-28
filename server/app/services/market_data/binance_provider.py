"""Public Binance market-data provider for BTC/USD (USDT-quoted spot).

Twelve Data's BTC/USD series carries no volume field, so the momentum strategy's
liquidity gate cannot be evaluated with it. This provider uses Binance's public
``/api/v3/klines`` endpoint instead, which returns full OHLCV data and needs no
API key. XAU/USD remains exclusively on Twelve Data; no Twelve Data logic is
changed here.

A small local SQLite cache keeps dashboard refreshes off the Binance request
budget: closed bars are immutable and reused across processes, and recent
windows are refreshed only after a short TTL.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.schemas.candle import CandleCreate
from app.schemas.market import QuoteResponse
from app.services.market_data.base import BaseMarketDataProvider
from app.services.market_data.freshness import get_timeframe_delta
from app.services.market_data.symbols import (
    UnknownSymbolError,
    get_provider_symbol,
    normalize_symbol,
)

SERVER_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_PATH = SERVER_ROOT / "data" / "binance_ohlcv_cache.sqlite3"

BINANCE_BASE_URL = "https://api.binance.com/api/v3/klines"
# Public spot ticker plus Binance's public data mirror. The mirror keeps quotes
# alive on networks/regions where api.binance.com is geo-restricted (451).
BINANCE_TICKER_URLS = (
    "https://api.binance.com/api/v3/ticker/price",
    "https://data-api.binance.vision/api/v3/ticker/price",
)
MAX_KLINES_PER_PAGE = 1000  # Binance hard cap
INTERVAL_MAP = {"15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d"}
DEFAULT_CACHE_TTL_SECONDS = 60.0


class BinanceAPIError(RuntimeError):
    """Raised on a non-200 Binance response, transport error, or bad payload."""


class BinancePublicProvider(BaseMarketDataProvider):
    """BTC/USD OHLCV provider backed by public Binance BTCUSDT klines."""

    def __init__(
        self,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout: float = 15.0,
        cache_path: Optional[Path] = None,
        cache_ttl_seconds: Optional[float] = None,
    ) -> None:
        self.http_client = http_client
        self.timeout = float(timeout)
        self.cache_path = Path(cache_path) if cache_path else DEFAULT_CACHE_PATH
        self.cache_ttl_seconds = float(
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else getattr(settings, "QUOTE_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS)
        )

    # ------------------------------------------------------------------
    # BaseMarketDataProvider contract
    # ------------------------------------------------------------------
    def is_symbol_supported(self, symbol: str) -> bool:
        try:
            return normalize_symbol(symbol) == "BTC/USD"
        except UnknownSymbolError:
            return False

    @staticmethod
    def _map_timeframe(timeframe: str) -> str:
        tf = str(timeframe or "").lower().strip()
        if tf not in INTERVAL_MAP:
            raise ValueError(f"Unsupported timeframe for Binance provider: {timeframe!r}")
        return INTERVAL_MAP[tf]

    @staticmethod
    def _to_ohlcv_dict(row: Sequence[Any]) -> dict[str, Any]:
        """Map a raw kline array to the app's standard OHLCV dictionary shape.

        Binance kline: [time, open, high, low, close, volume, ...]. ``datetime``
        is formatted like a Twelve Data row so downstream parsing is identical;
        all prices and the volume are cast to float (never left as a string).
        """
        ts = datetime.fromtimestamp(int(row[0]) / 1000.0, tz=timezone.utc)
        return {
            "datetime": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }

    @staticmethod
    def _parse_datetime(raw: Any) -> datetime:
        dt = datetime.fromisoformat(str(raw).strip().replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _to_candle(ohlcv: dict[str, Any], canonical: str, timeframe: str) -> CandleCreate:
        """Validate an OHLCV dict and build a schema-valid closed candle."""
        o, h, l, c = (
            float(ohlcv["open"]), float(ohlcv["high"]),
            float(ohlcv["low"]), float(ohlcv["close"]),
        )
        vol = float(ohlcv["volume"])
        if not (o > 0 and h > 0 and l > 0 and c > 0):
            raise ValueError("non-positive OHLC price")
        if not (h >= max(o, c) and l <= min(o, c) and h >= l):
            raise ValueError("OHLC invariant violation")
        return CandleCreate(
            symbol=canonical,
            timeframe=timeframe,
            timestamp=BinancePublicProvider._parse_datetime(ohlcv["datetime"]),
            open=o, high=h, low=l, close=c, volume=vol,
            source="binance", is_closed=True,
        )

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 200,
    ) -> list[CandleCreate]:
        """Fetch OHLCV candles, paging backwards with ``endTime`` if needed.

        ``limit`` bars ending at ``end_time`` are returned. When ``limit``
        exceeds Binance's 1000-bar page cap, successive requests move
        ``endTime`` to just before the earliest kline of the previous page.
        """
        canonical = normalize_symbol(symbol)
        if canonical != "BTC/USD":
            raise ValueError(
                f"BinancePublicProvider only supports 'BTC/USD'; requested: '{symbol}'"
            )
        interval = self._map_timeframe(timeframe)
        delta = get_timeframe_delta(timeframe)
        limit = max(1, int(limit))

        now = datetime.now(timezone.utc)
        end = end_time or now
        start = start_time or end - delta * limit
        if end <= start:
            return []

        cached = self._read_cache(canonical, timeframe, start, end)
        expected = int((end - start) / delta) + 1
        last_closed = now - delta  # a bar labelled `now - delta` closed at `now`
        # Allow up to two boundary slots to be absent (one forming bar plus a
        # possible window-edge offset) before declaring the cache incomplete.
        usable = (
            len(cached) >= max(1, expected - 2)
            and cached[0].timestamp <= start + 2 * delta
            and cached[-1].timestamp >= min(end, last_closed) - 2 * delta
        )
        recent_request = end >= last_closed
        if usable and (not recent_request or self._cache_is_fresh(timeframe)):
            return cached[-limit:]

        provider_symbol = get_provider_symbol(canonical, "binance")
        params_base: dict[str, Any] = {
            "symbol": provider_symbol,
            "interval": interval,
        }
        start_ms = int(start.timestamp() * 1000)
        cursor_end_ms = int(end.timestamp() * 1000)
        fetched: list[CandleCreate] = []
        rejected = 0
        close_client = False
        client = self.http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout)
            close_client = True

        try:
            while cursor_end_ms >= start_ms and len(fetched) < limit:
                page_size = min(MAX_KLINES_PER_PAGE, limit - len(fetched))
                params = {**params_base, "limit": page_size, "endTime": cursor_end_ms}
                try:
                    response = await client.get(BINANCE_BASE_URL, params=params)
                except httpx.HTTPError as exc:
                    raise BinanceAPIError(
                        f"Binance request failed: {type(exc).__name__}: {exc}"
                    ) from exc
                if response.status_code != 200:
                    raise BinanceAPIError(
                        f"Binance HTTP {response.status_code}: {response.text[:500]}"
                    )
                try:
                    rows = response.json()
                except Exception as exc:
                    raise BinanceAPIError(
                        f"Binance non-JSON response (HTTP {response.status_code}): "
                        f"{response.text[:500]}"
                    ) from exc
                if isinstance(rows, dict):
                    raise BinanceAPIError(f"Binance error payload: {rows}")
                if not rows:
                    break

                earliest_ms: Optional[int] = None
                for row in rows:
                    try:
                        ohlcv = self._to_ohlcv_dict(row)
                        candle = self._to_candle(ohlcv, canonical, timeframe)
                    except (IndexError, TypeError, ValueError):
                        rejected += 1
                        continue
                    ts_ms = int(candle.timestamp.timestamp() * 1000)
                    if ts_ms > cursor_end_ms or ts_ms < start_ms:
                        continue
                    # Forming-bar rule: keep only bars whose 1H bucket is closed.
                    if ts_ms + int(delta.total_seconds() * 1000) > int(now.timestamp() * 1000):
                        continue
                    fetched.append(candle)
                    if earliest_ms is None or ts_ms < earliest_ms:
                        earliest_ms = ts_ms

                if earliest_ms is None or earliest_ms >= cursor_end_ms:
                    break
                cursor_end_ms = earliest_ms - 1  # endTime is inclusive
        finally:
            if close_client:
                await client.aclose()

        if rejected:
            logger.warning("Binance rejected %s malformed kline rows.", rejected)
        if fetched:
            self._write_cache(canonical, timeframe, fetched)
            fetched = self._read_cache(canonical, timeframe, start, end)
        merged = {c.timestamp: c for c in cached}
        merged.update({c.timestamp: c for c in fetched})
        return [merged[ts] for ts in sorted(merged)][-limit:]

    async def fetch_latest(
        self, symbol: str, timeframe: str, count: int = 50
    ) -> list[CandleCreate]:
        return await self.fetch_candles(symbol, timeframe, limit=count)

    async def fetch_quote(self, symbol: str) -> Optional[QuoteResponse]:
        """Fetch the latest BTC/USD price from Binance's public ticker endpoint.

        The ticker payload is ``{"symbol": "BTCUSDT", "price": "64200.00"}``.
        It carries no provider timestamp, so ``timestamp``/``fetched_at`` are the
        local call time; the API layer derives staleness from observed price
        changes rather than from the provider label.
        """
        canonical = normalize_symbol(symbol)
        if canonical != "BTC/USD":
            raise ValueError(
                f"BinancePublicProvider only supports 'BTC/USD'; requested: '{symbol}'"
            )
        provider_symbol = get_provider_symbol(canonical, "binance")

        close_client = False
        client = self.http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout)
            close_client = True

        try:
            data: Optional[dict[str, Any]] = None
            last_error: Optional[Exception] = None
            for ticker_url in BINANCE_TICKER_URLS:
                try:
                    response = await client.get(
                        ticker_url, params={"symbol": provider_symbol}
                    )
                    if response.status_code != 200:
                        raise BinanceAPIError(
                            f"HTTP {response.status_code}: {response.text[:300]}"
                        )
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise BinanceAPIError(
                            f"payload is not an object: {str(payload)[:300]}"
                        )
                    data = payload
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Binance ticker %s unavailable: %s", ticker_url, exc
                    )
            if data is None:
                raise BinanceAPIError(
                    f"All Binance ticker endpoints failed for {provider_symbol}: {last_error}"
                )

            echoed = str(data.get("symbol") or "").upper()
            if echoed and echoed != provider_symbol.upper():
                raise BinanceAPIError(
                    f"Binance echoed symbol mismatch: expected {provider_symbol}, got {echoed}"
                )

            raw_price = data.get("price")
            try:
                price = float(raw_price)
            except (TypeError, ValueError) as exc:
                raise BinanceAPIError(
                    f"Binance returned a non-numeric price for {provider_symbol}: {raw_price!r}"
                ) from exc
            if price <= 0:
                raise BinanceAPIError(
                    f"Binance returned a non-positive price for {provider_symbol}: {raw_price!r}"
                )

            now_utc = datetime.now(timezone.utc)
            return QuoteResponse(
                symbol=canonical,
                price=price,
                timestamp=now_utc,
                provider_timestamp=None,
                fetched_at=now_utc,
                source="binance",
                provider="binance",
                provider_symbol=provider_symbol,
                age_seconds=0.0,
                is_stale=False,
                degraded=False,
                cached=False,
            )
        except BinanceAPIError as exc:
            # Never let a transient ticker failure kill the whole /quote request.
            # A candle close is a usable last resort, but it is explicitly marked
            # degraded so it can never be mistaken for a live tick.
            logger.warning("Binance ticker unavailable (%s); using candle fallback.", exc)
            try:
                fallback = await super().fetch_quote(canonical)
            except Exception as fallback_exc:
                logger.warning("Binance candle fallback also failed: %s", fallback_exc)
                fallback = None
            if fallback is not None:
                fallback.source = "binance_candle_fallback"
                fallback.provider = "binance"
                fallback.provider_symbol = provider_symbol
                fallback.degraded = True
                fallback.fallback_reason = (
                    "Binance ticker unavailable; using last closed candle"
                )
            return fallback
        finally:
            if close_client:
                await client.aclose()

    # ------------------------------------------------------------------
    # Local SQLite cache (no API key, no repeated upstream calls)
    # ------------------------------------------------------------------
    def _init_cache(self) -> sqlite3.Connection:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.cache_path))
        conn.execute(
            """CREATE TABLE IF NOT EXISTS binance_candles (
                   symbol VARCHAR(20) NOT NULL,
                   timeframe VARCHAR(10) NOT NULL,
                   timestamp DATETIME NOT NULL,
                   open FLOAT NOT NULL,
                   high FLOAT NOT NULL,
                   low FLOAT NOT NULL,
                   close FLOAT NOT NULL,
                   volume FLOAT NOT NULL,
                   source VARCHAR(30) DEFAULT 'binance',
                   PRIMARY KEY (symbol, timeframe, timestamp))"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS binance_cache_meta (
                   key VARCHAR(80) PRIMARY KEY,
                   fetched_at REAL NOT NULL)"""
        )
        conn.commit()
        return conn

    def _read_cache(
        self, canonical: str, timeframe: str, start: datetime, end: datetime
    ) -> list[CandleCreate]:
        if not self.cache_path.exists():
            return []
        try:
            conn = sqlite3.connect(f"file:{self.cache_path.as_posix()}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """SELECT timestamp, open, high, low, close, volume, source
                       FROM binance_candles
                       WHERE symbol = ? AND timeframe = ? AND timestamp >= ? AND timestamp <= ?
                       ORDER BY timestamp""",
                    (
                        canonical, timeframe,
                        start.strftime("%Y-%m-%d %H:%M:%S"),
                        end.strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            logger.warning("Could not read Binance cache %s: %s", self.cache_path, exc)
            return []

        candles: list[CandleCreate] = []
        for row in rows:
            try:
                candles.append(
                    CandleCreate(
                        symbol=canonical,
                        timeframe=timeframe,
                        timestamp=self._parse_datetime(row["timestamp"]),
                        open=float(row["open"]), high=float(row["high"]),
                        low=float(row["low"]), close=float(row["close"]),
                        volume=float(row["volume"]),
                        source=str(row["source"] or "binance"), is_closed=True,
                    )
                )
            except (TypeError, ValueError):
                continue
        return candles

    def _write_cache(
        self, canonical: str, timeframe: str, candles: Sequence[CandleCreate]
    ) -> None:
        if not candles:
            return
        conn = self._init_cache()
        try:
            conn.executemany(
                """INSERT OR REPLACE INTO binance_candles
                   (symbol, timeframe, timestamp, open, high, low, close, volume, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        canonical, timeframe, c.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                        c.open, c.high, c.low, c.close, c.volume, c.source or "binance",
                    )
                    for c in candles
                ],
            )
            conn.execute(
                """INSERT OR REPLACE INTO binance_cache_meta (key, fetched_at)
                   VALUES (?, ?)""",
                (f"{canonical}|{timeframe}", time.time()),
            )
            conn.commit()
        finally:
            conn.close()

    def _cache_is_fresh(self, timeframe: str) -> bool:
        if not self.cache_path.exists():
            return False
        try:
            conn = sqlite3.connect(f"file:{self.cache_path.as_posix()}?mode=ro", uri=True)
            try:
                row = conn.execute(
                    "SELECT fetched_at FROM binance_cache_meta WHERE key = ?",
                    (f"BTC/USD|{timeframe}",),
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return False
        return bool(row and (time.time() - float(row[0])) <= self.cache_ttl_seconds)
