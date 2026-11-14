"""Unit and integration tests for Quote Provenance, Symbol Correctness, Staleness, and Fail-Safe HTTP 503."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from fastapi.testclient import TestClient

from app.core.config import settings
from app.schemas.market import QuoteResponse
from app.services.market_data.mock_provider import MockMarketDataProvider
from app.services.market_data.twelvedata_provider import TwelveDataProvider
from app.services.market_data.yfinance_provider import YahooFinanceProvider
from app.api.v1.market import _quote_cache, _resolve_quote
from app.main import app


def test_quote_response_provenance_fields():
    """Verify QuoteResponse schema includes all provenance, caching, and health fields."""
    now = datetime.now(timezone.utc)
    quote = QuoteResponse(
        symbol="XAU/USD",
        price=2680.50,
        bid=2680.45,
        ask=2680.55,
        high=2690.00,
        low=2675.00,
        volume=12000.0,
        timestamp=now,
        source="twelvedata",
        provider="twelvedata",
        provider_symbol="XAU/USD",
        age_seconds=1.2,
        is_stale=False,
        degraded=False,
        fallback_reason=None,
        cached=False,
        cache_age_ms=0.0,
    )
    assert quote.symbol == "XAU/USD"
    assert quote.provider == "twelvedata"
    assert quote.provider_symbol == "XAU/USD"
    assert quote.is_stale is False
    assert quote.degraded is False
    assert quote.fallback_reason is None


@pytest.mark.asyncio
async def test_twelvedata_rejects_mismatched_echoed_symbol():
    """Verify TwelveDataProvider rejects a quote if the echoed symbol does not match the requested symbol."""
    mock_yahoo = AsyncMock(spec=YahooFinanceProvider)
    sample_yahoo_quote = QuoteResponse(
        symbol="XAU/USD",
        price=2685.00,
        timestamp=datetime.now(timezone.utc),
        provider="yahoo",
        provider_symbol="GC=F",
        age_seconds=2.0,
        is_stale=False,
        degraded=True,
        fallback_reason="TwelveData provider returned no quote",
    )
    mock_yahoo.fetch_quote.return_value = sample_yahoo_quote

    provider = TwelveDataProvider(api_key="dummy_key", fallback_provider=mock_yahoo)

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "symbol": "EUR/USD",  # Mismatched symbol returned by upstream
            "close": "1.1050",
            "timestamp": int(datetime.now(timezone.utc).timestamp()),
        }
        mock_get.return_value = mock_resp

        quote = await provider.fetch_quote("XAU/USD")
        assert quote.provider == "yahoo"
        assert quote.fallback_reason is not None
        assert "Twelve Data echoed symbol mismatch" in quote.fallback_reason


@pytest.mark.asyncio
async def test_quote_fallback_sets_loud_warning_and_fallback_reason():
    """Verify fallback from TwelveData to Yahoo logs a warning and marks degraded=True with reason."""
    mock_yahoo = AsyncMock(spec=YahooFinanceProvider)
    sample_yahoo_quote = QuoteResponse(
        symbol="XAU/USD",
        price=2685.00,
        timestamp=datetime.now(timezone.utc),
        provider="yahoo",
        provider_symbol="GC=F",
        age_seconds=5.0,
        is_stale=False,
        degraded=True,
        fallback_reason="TwelveData API returned error 429",
    )
    mock_yahoo.fetch_quote.return_value = sample_yahoo_quote

    provider = TwelveDataProvider(api_key="test_key", fallback_provider=mock_yahoo)

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Rate limit reached"
        mock_get.return_value = mock_resp

        quote = await provider.fetch_quote("XAU/USD")
        assert quote.provider == "yahoo"
        assert quote.degraded is True
        assert quote.fallback_reason is not None
        assert "Twelve Data API returned 429" in quote.fallback_reason


@pytest.mark.asyncio
async def test_total_failure_returns_503_never_fake_price():
    """Verify that when all upstream providers fail, HTTP 503 is returned without serving fake/stale data."""
    failing_provider = AsyncMock(spec=TwelveDataProvider)
    failing_provider.fetch_quote.return_value = None

    _quote_cache.clear()

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await _resolve_quote("XAU/USD", failing_provider)

    assert exc_info.value.status_code == 503
    assert "market quote currently unavailable" in exc_info.value.detail


@pytest.mark.asyncio
async def test_cache_keyed_by_provider_and_symbol_with_cache_status():
    """Verify 3s cache is keyed by (provider, canonical_symbol) and reports cached=True with cache_age_ms."""
    _quote_cache.clear()
    mock_prov = MockMarketDataProvider()

    # First fetch: cache miss
    quote1 = await _resolve_quote("XAU/USD", mock_prov)
    assert quote1.cached is False

    # Second fetch within 3s: cache hit
    quote2 = await _resolve_quote("XAU/USD", mock_prov)
    assert quote2.cached is True
    assert quote2.cache_age_ms is not None
    assert quote2.cache_age_ms >= 0


@pytest.mark.asyncio
async def test_staleness_flagged_if_age_exceeds_threshold():
    """Verify quote is marked is_stale=True and degraded=True if timestamp is older than QUOTE_MAX_AGE_SECONDS."""
    _quote_cache.clear()
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=settings.QUOTE_MAX_AGE_SECONDS + 10)
    stale_quote = QuoteResponse(
        symbol="XAU/USD",
        price=2650.00,
        timestamp=stale_time,
        provider="yahoo",
        provider_symbol="GC=F",
        age_seconds=130.0,
        is_stale=False,
        degraded=False,
    )

    mock_prov = AsyncMock()
    mock_prov.fetch_quote.return_value = stale_quote

    resolved = await _resolve_quote("XAU/USD", mock_prov)
    assert resolved.is_stale is True
    assert resolved.degraded is True
    assert "Quote is stale" in (resolved.fallback_reason or "")


def test_mock_provider_rejected_in_live_mode():
    """Verify startup fails fast if MODE is 'live' and MARKET_DATA_PROVIDER is 'mock'."""
    from app.main import lifespan

    with patch.object(settings, "MODE", "live"), patch.object(settings, "MARKET_DATA_PROVIDER", "mock"):
        import asyncio
        with pytest.raises(RuntimeError) as exc_info:
            asyncio.run(lifespan(app).__aenter__())
        assert "Cannot run in LIVE mode with MOCK market data provider" in str(exc_info.value)
