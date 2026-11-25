"""Targeted tests for the presence-gated quote cache TTL."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

import app.api.v1.market as market_mod
from app.core.config import settings
from app.schemas.market import QuoteResponse


def _quote(price=2500.0, now=None):
    now = now or datetime.now(timezone.utc)
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


@pytest.fixture(autouse=True)
def _reset_quote_state():
    market_mod._quote_cache.clear()
    market_mod._presence_last_beat = 0.0
    yield
    market_mod._quote_cache.clear()
    market_mod._presence_last_beat = 0.0


def test_presence_endpoint_marks_dashboard_active(client):
    market_mod._presence_last_beat = 0.0

    resp = client.post("/api/v1/market/presence")

    assert resp.status_code == 200
    assert resp.json()["cache_ttl_seconds"] == settings.QUOTE_RESPONSE_CACHE_TTL_SECONDS
    assert market_mod._presence_is_active() is True
    assert market_mod._effective_cache_ttl() == float(settings.QUOTE_RESPONSE_CACHE_TTL_SECONDS)


@pytest.mark.asyncio
async def test_active_presence_uses_60s_cache_ttl(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(market_mod.time, "time", lambda: clock["now"])
    monkeypatch.setattr(settings, "QUOTE_PRESENCE_TTL_SECONDS", 60)
    monkeypatch.setattr(settings, "QUOTE_RESPONSE_CACHE_TTL_SECONDS", 60)
    monkeypatch.setattr(settings, "QUOTE_IDLE_CACHE_TTL_SECONDS", 300)

    provider = AsyncMock()
    provider.fetch_quote = AsyncMock(side_effect=lambda symbol: _quote(price=2500.0))

    market_mod._presence_last_beat = clock["now"]
    first = await market_mod._resolve_quote("XAU/USD", provider)
    assert first.cached is False

    clock["now"] += 30
    market_mod._presence_last_beat = clock["now"]  # heartbeat keeps presence active
    second = await market_mod._resolve_quote("XAU/USD", provider)
    assert second.cached is True
    assert provider.fetch_quote.await_count == 1

    clock["now"] += 31  # 61s since the cached fetch -> TTL expired
    market_mod._presence_last_beat = clock["now"]
    third = await market_mod._resolve_quote("XAU/USD", provider)
    assert third.cached is False
    assert provider.fetch_quote.await_count == 2


@pytest.mark.asyncio
async def test_idle_presence_stretches_ttl_to_300s(monkeypatch):
    clock = {"now": 2000.0}
    monkeypatch.setattr(market_mod.time, "time", lambda: clock["now"])
    monkeypatch.setattr(settings, "QUOTE_PRESENCE_TTL_SECONDS", 60)
    monkeypatch.setattr(settings, "QUOTE_RESPONSE_CACHE_TTL_SECONDS", 60)
    monkeypatch.setattr(settings, "QUOTE_IDLE_CACHE_TTL_SECONDS", 300)

    provider = AsyncMock()
    provider.fetch_quote = AsyncMock(side_effect=lambda symbol: _quote(price=2500.0))

    # No heartbeat ever recorded -> idle cadence.
    first = await market_mod._resolve_quote("XAU/USD", provider)
    assert first.cached is False

    clock["now"] += 120
    second = await market_mod._resolve_quote("XAU/USD", provider)
    assert second.cached is True
    assert provider.fetch_quote.await_count == 1

    clock["now"] += 181  # 301s since the fetch -> idle TTL expired
    third = await market_mod._resolve_quote("XAU/USD", provider)
    assert third.cached is False
    assert provider.fetch_quote.await_count == 2
