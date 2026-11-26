"""In-memory TTL cache with single-flight coalescing for upstream providers.

Provider instances are created per request, so the cache is module-level state
rather than instance state. Concurrent callers asking for the same symbol and
timeframe share one upstream request, protecting the provider rate limit.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from app.core.config import settings
from app.core.logging import logger
from app.schemas.market import QuoteResponse


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float
    stored_at: float


class ProviderCache:
    """Async TTL cache with request coalescing and last-good throttle fallback."""

    def __init__(self) -> None:
        self._entries: Dict[tuple, _CacheEntry] = {}
        self._last_good: Dict[tuple, Tuple[Any, float]] = {}
        self._inflight: Dict[tuple, asyncio.Future] = {}
        self._lock: Optional[asyncio.Lock] = None
        self._hits = 0
        self._misses = 0
        self._coalesced = 0
        self._provider_calls = 0
        self._provider_fetch_ms_total = 0.0

    def _get_lock(self) -> asyncio.Lock:
        # Created lazily: this module is imported by sync code before any loop runs.
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def get_or_fetch(
        self,
        key: tuple,
        ttl_seconds: float,
        fetch: Callable[[], Awaitable[Any]],
        *,
        stale_decorator: Optional[Callable[[Any, float], Any]] = None,
    ) -> Any:
        """Return cached value or fetch once, sharing an in-flight fetch by key."""
        now = time.monotonic()
        entry = self._entries.get(key)
        if entry and now < entry.expires_at:
            self._hits += 1
            return entry.value

        async with self._get_lock():
            now = time.monotonic()
            entry = self._entries.get(key)
            if entry and now < entry.expires_at:
                self._hits += 1
                return entry.value
            future = self._inflight.get(key)
            if future is None:
                future = asyncio.get_running_loop().create_future()
                self._inflight[key] = future
                is_owner = True
                self._misses += 1
            else:
                is_owner = False
                self._coalesced += 1

        if not is_owner:
            # N concurrent identical requests => one provider call.
            return await future

        started = time.perf_counter()
        try:
            value = await fetch()
            self._provider_calls += 1
            self._provider_fetch_ms_total += (time.perf_counter() - started) * 1000.0
            stored_at = time.monotonic()
            self._entries[key] = _CacheEntry(
                value, stored_at + max(0.0, float(ttl_seconds)), stored_at
            )
            self._last_good[key] = (value, stored_at)
            if not future.done():
                future.set_result(value)
            return value
        except Exception as exc:
            last_good = self._last_good.get(key)
            if settings.STALE_ON_THROTTLE and last_good is not None:
                value, stored_at = last_good
                age_seconds = max(0.0, time.monotonic() - stored_at)
                logger.warning(
                    "Provider request for cache key %s failed (%s); serving "
                    "last-good cached value (age %.1fs).",
                    key,
                    exc,
                    age_seconds,
                )
                served = stale_decorator(value, age_seconds) if stale_decorator else value
                stored_at = time.monotonic()
                self._entries[key] = _CacheEntry(
                    served, stored_at + max(0.0, float(ttl_seconds)), stored_at
                )
                if not future.done():
                    future.set_result(served)
                return served
            if not future.done():
                future.set_exception(exc)
                # The owner raises directly below; mark the future as observed so
                # asyncio does not log "exception was never retrieved" when there
                # are no coalesced waiters.
                future.exception()
            raise
        finally:
            self._inflight.pop(key, None)

    def invalidate_prefix(self, prefix: tuple) -> None:
        """Drop cached entries whose key starts with ``prefix``.

        Used when a consumed setup closes: the cached dashboard signal view for
        that symbol must not survive into the next poll.
        """
        for key in list(self._entries):
            if isinstance(key, tuple) and key[: len(prefix)] == tuple(prefix):
                self._entries.pop(key, None)
                self._last_good.pop(key, None)

    def stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        return {
            "enabled": settings.PROVIDER_CACHE_ENABLED,
            "hits": self._hits,
            "misses": self._misses,
            "coalesced": self._coalesced,
            "provider_calls": self._provider_calls,
            "cache_hit_rate": round(self._hits / total, 4) if total else 0.0,
            "avg_provider_fetch_ms": (
                round(self._provider_fetch_ms_total / self._provider_calls, 2)
                if self._provider_calls
                else 0.0
            ),
            "entries": len(self._entries),
        }

    def clear(self) -> None:
        self._entries.clear()
        self._last_good.clear()
        self._hits = 0
        self._misses = 0
        self._coalesced = 0
        self._provider_calls = 0
        self._provider_fetch_ms_total = 0.0


# Separate namespaces so derived analytics cannot evict quote ticks.
provider_cache = ProviderCache()
derived_cache = ProviderCache()


def stale_quote_decorator(value: Any, age_seconds: float) -> Any:
    """Keep a throttled quote usable without flipping the UI to DEGRADED."""
    if isinstance(value, QuoteResponse):
        return value.model_copy(
            update={
                "cached": True,
                "cache_age_ms": round(age_seconds * 1000, 1),
                "is_stale": False,
                "degraded": False,
                "fallback_reason": "provider throttled: serving last-good cached quote",
            }
        )
    return value


def _cache_key(*parts: Any) -> tuple:
    return tuple(str(p) for p in parts)


class CachedMarketDataProvider:
    """TTL + single-flight proxy around any BaseMarketDataProvider implementation."""

    def __init__(self, provider: Any, cache: Optional[ProviderCache] = None) -> None:
        self._provider = provider
        self._cache = cache or provider_cache

    def __getattr__(self, name: str) -> Any:
        # Expose provider-specific attributes (e.g. rejected_rows_count, name).
        return getattr(self._provider, name)

    @property
    def name(self) -> str:
        return getattr(
            self._provider,
            "name",
            self._provider.__class__.__name__.lower().replace("provider", ""),
        )

    def is_symbol_supported(self, symbol: str) -> bool:
        return self._provider.is_symbol_supported(symbol)

    async def fetch_quote(self, symbol: str) -> Optional[QuoteResponse]:
        if not settings.PROVIDER_CACHE_ENABLED:
            return await self._provider.fetch_quote(symbol)

        async def _fetch() -> QuoteResponse:
            quote = await self._provider.fetch_quote(symbol)
            if quote is None:
                raise RuntimeError(f"Provider returned no quote for {symbol}")
            return quote

        return await self._cache.get_or_fetch(
            _cache_key("quote", symbol),
            settings.QUOTE_CACHE_TTL_SECONDS,
            _fetch,
            stale_decorator=stale_quote_decorator,
        )

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time=None,
        end_time=None,
        limit: int = 200,
        **kwargs,
    ) -> list:
        if not settings.PROVIDER_CACHE_ENABLED:
            return await self._provider.fetch_candles(
                symbol,
                timeframe,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                **kwargs,
            )

        async def _fetch() -> list:
            return await self._provider.fetch_candles(
                symbol,
                timeframe,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                **kwargs,
            )

        return await self._cache.get_or_fetch(
            _cache_key(
                "candles", symbol, timeframe, start_time, end_time, limit,
                sorted(kwargs.items()),
            ),
            settings.QUOTE_CACHE_TTL_SECONDS,
            _fetch,
        )

    async def fetch_latest(self, symbol: str, timeframe: str, count: int = 50) -> list:
        if not settings.PROVIDER_CACHE_ENABLED:
            return await self._provider.fetch_latest(symbol, timeframe, count=count)

        async def _fetch() -> list:
            return await self._provider.fetch_latest(symbol, timeframe, count=count)

        return await self._cache.get_or_fetch(
            _cache_key("latest", symbol, timeframe, count),
            settings.QUOTE_CACHE_TTL_SECONDS,
            _fetch,
        )
