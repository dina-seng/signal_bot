"""Targeted tests for price-change-based staleness semantics."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

import app.api.v1.market as market_mod
from app.core.config import settings
from app.schemas.market import QuoteResponse


def _quote(price=2500.0, now=None, **overrides):
    now = now or datetime.now(timezone.utc)
    payload = dict(
        symbol="XAU/USD",
        price=price,
        timestamp=now,
        provider_timestamp=now,
        fetched_at=now,
        provider="twelvedata",
        provider_symbol="XAU/USD",
        age_seconds=0.0,
        is_stale=False,
        degraded=False,
    )
    payload.update(overrides)
    return QuoteResponse(**payload)


@pytest.fixture(autouse=True)
def _reset_quote_state():
    market_mod._quote_cache.clear()
    market_mod._presence_last_beat = 0.0
    yield
    market_mod._quote_cache.clear()
    market_mod._presence_last_beat = 0.0


@pytest.mark.asyncio
async def test_same_price_keeps_last_price_change_at(monkeypatch):
    monkeypatch.setattr(settings, "QUOTE_PRESENCE_TTL_SECONDS", 600)
    monkeypatch.setattr(settings, "QUOTE_RESPONSE_CACHE_TTL_SECONDS", 0)  # force every call to fetch
    market_mod._presence_last_beat = market_mod.time.time()

    provider = AsyncMock()
    provider.fetch_quote = AsyncMock(side_effect=lambda symbol: _quote(price=2500.0))

    first = await market_mod._resolve_quote("XAU/USD", provider)
    second = await market_mod._resolve_quote("XAU/USD", provider)

    assert second.last_price_change_at == first.last_price_change_at


@pytest.mark.asyncio
async def test_changed_price_advances_last_price_change_at(monkeypatch):
    monkeypatch.setattr(settings, "QUOTE_PRESENCE_TTL_SECONDS", 600)
    monkeypatch.setattr(settings, "QUOTE_RESPONSE_CACHE_TTL_SECONDS", 0)
    market_mod._presence_last_beat = market_mod.time.time()

    prices = iter([2500.0, 2501.5])
    provider = AsyncMock()
    provider.fetch_quote = AsyncMock(side_effect=lambda symbol: _quote(price=next(prices)))

    first = await market_mod._resolve_quote("XAU/USD", provider)
    second = await market_mod._resolve_quote("XAU/USD", provider)

    assert second.price != first.price
    assert second.last_price_change_at > first.last_price_change_at


def test_provider_label_age_does_not_mark_stale(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr("app.api.v1.market.is_market_open", lambda ts: True)
    quote = _quote(
        price=2500.0,
        now=now,
        provider_timestamp=now - timedelta(minutes=30),
        last_price_change_at=now - timedelta(seconds=30),
    )

    resolved = market_mod._apply_freshness(quote, now)

    assert resolved.is_stale is False


def test_stale_when_price_frozen_during_market_hours(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr("app.api.v1.market.is_market_open", lambda ts: True)
    quote = _quote(
        price=2500.0,
        now=now,
        last_price_change_at=now - timedelta(seconds=settings.QUOTE_STALE_AFTER_SECONDS + 1),
    )

    resolved = market_mod._apply_freshness(quote, now)

    assert resolved.is_stale is True
    assert "no price change" in (resolved.fallback_reason or "").lower()


def test_not_stale_when_market_closed(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr("app.api.v1.market.is_market_open", lambda ts: False)
    quote = _quote(
        price=2500.0,
        now=now,
        last_price_change_at=now - timedelta(hours=8),
    )

    resolved = market_mod._apply_freshness(quote, now)

    assert resolved.is_stale is False
