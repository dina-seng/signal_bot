"""Dashboard performance regressions: caching, coalescing, snapshot, CORS."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

import app.api.v1.market as market_mod
from app.core.config import settings
from app.schemas.market import QuoteResponse
from app.services.market_data.cache import (
    CachedMarketDataProvider,
    derived_cache,
    provider_cache,
)


def _quote(price: float = 2500.0) -> QuoteResponse:
    now = datetime.now(timezone.utc)
    return QuoteResponse(
        symbol="XAU/USD",
        price=price,
        timestamp=now,
        provider="twelvedata",
        provider_symbol="XAU/USD",
        age_seconds=0.0,
        is_stale=False,
        degraded=False,
    )


async def _delayed_quote(symbol):
    # Yield once so concurrent callers actually reach the single-flight lock.
    await asyncio.sleep(0)
    return _quote()


def _fake_provider():
    provider = AsyncMock()
    provider.fetch_quote = AsyncMock(side_effect=_delayed_quote)
    provider.fetch_candles = AsyncMock(return_value=[])
    provider.fetch_latest = AsyncMock(return_value=[])
    provider.is_symbol_supported = lambda symbol: symbol == "XAU/USD"
    return provider


@pytest.fixture(autouse=True)
def _clean_cache():
    provider_cache.clear()
    derived_cache.clear()
    market_mod._quote_cache.clear()
    market_mod._presence_last_beat = 0.0
    yield
    provider_cache.clear()
    derived_cache.clear()
    market_mod._quote_cache.clear()
    market_mod._presence_last_beat = 0.0


@pytest.mark.asyncio
async def test_cache_hit(monkeypatch):
    """A second call inside the TTL must not reach the upstream provider."""
    monkeypatch.setattr(settings, "QUOTE_CACHE_TTL_SECONDS", 5.0)
    upstream = _fake_provider()
    provider = CachedMarketDataProvider(upstream)

    first = await provider.fetch_quote("XAU/USD")
    second = await provider.fetch_quote("XAU/USD")

    assert first is not None and second is not None
    assert upstream.fetch_quote.await_count == 1
    assert provider_cache.stats()["cache_hit_rate"] == 0.5


@pytest.mark.asyncio
async def test_single_flight(monkeypatch):
    """Ten concurrent identical requests share a single upstream call."""
    monkeypatch.setattr(settings, "QUOTE_CACHE_TTL_SECONDS", 5.0)
    upstream = _fake_provider()
    provider = CachedMarketDataProvider(upstream)

    quotes = await asyncio.gather(
        *[provider.fetch_quote("XAU/USD") for _ in range(10)]
    )

    assert len(quotes) == 10
    assert upstream.fetch_quote.await_count == 1
    assert provider_cache.stats()["coalesced"] == 9


@pytest.mark.asyncio
async def test_throttled_provider_serves_last_good(monkeypatch, caplog):
    """A 429-style failure returns the last-good quote instead of DEGRADED."""
    monkeypatch.setattr(settings, "QUOTE_CACHE_TTL_SECONDS", 0)
    monkeypatch.setattr(settings, "STALE_ON_THROTTLE", True)
    calls = {"n": 0}

    async def _flaky(symbol):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("Twelve Data HTTP 429 rate limit exceeded")
        return _quote()

    upstream = AsyncMock()
    upstream.fetch_quote = AsyncMock(side_effect=_flaky)
    provider = CachedMarketDataProvider(upstream)

    first = await provider.fetch_quote("XAU/USD")
    with caplog.at_level("WARNING"):
        second = await provider.fetch_quote("XAU/USD")

    assert calls["n"] == 2
    assert second.price == first.price
    assert second.cached is True
    assert second.degraded is False
    assert second.is_stale is False
    assert "last-good cached value" in caplog.text


def test_snapshot_shape(client):
    """One GET must carry every data group the dashboard polls today."""
    resp = client.get("/api/v1/dashboard/snapshot?symbol=XAU%2FUSD&timeframe=15m")
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    required = {
        "quote",
        "live_quote",
        "candles",
        "indicators",
        "structure",
        "liquidity",
        "paper_summary",
        "positions",
        "trades",
        "performance",
        "signals",
        "news",
        "blackout",
        "telegram_status",
        "scanner_status",
        "config",
        "as_of",
        "timings_ms",
    }
    assert required.issubset(payload.keys())
    assert isinstance(payload["candles"], list)
    assert isinstance(payload["positions"], list)
    assert isinstance(payload["config"], dict)
    # Atomic paper semantics preserved: the ledger and the top-level positions
    # are the same array from /paper/summary.
    assert payload["positions"] == (payload["paper_summary"] or {}).get("positions", [])


def test_latency_endpoint(client):
    resp = client.get("/api/v1/health/latency")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert {"provider_fetch_ms", "cache_hit_rate", "db_query_ms", "serialize_ms"}.issubset(
        payload.keys()
    )


def test_preflight_cached(client):
    """OPTIONS preflight must advertise a long cache lifetime."""
    origin = settings.FRONTEND_ORIGIN[0]
    resp = client.options(
        "/api/v1/paper/summary",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["Access-Control-Allow-Origin"] == origin
    assert resp.headers["Access-Control-Allow-Credentials"] == "true"
    assert int(resp.headers["Access-Control-Max-Age"]) == settings.CORS_MAX_AGE_SECONDS


def test_foreign_origin_rejected(client):
    resp = client.options(
        "/api/v1/paper/summary",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 400
