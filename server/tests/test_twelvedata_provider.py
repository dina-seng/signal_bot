"""Tests for TwelveDataProvider: error payloads, 429 path, forming bar drop, budget stop, OHLC invariants."""

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from app.models.api_usage import ApiUsage
from app.services.market_data.twelvedata_provider import (
    TwelveDataProvider,
    TwelveDataError,
    TwelveDataRateLimitError,
    TwelveDataBudgetExceededError,
    TokenBucketRateLimiter,
)


@pytest.mark.asyncio
async def test_shared_http_client_injected():
    """Verify TwelveDataProvider receives and uses the injected shared httpx.AsyncClient."""
    shared_client = httpx.AsyncClient()
    provider = TwelveDataProvider(api_key="test_key", http_client=shared_client)

    assert provider.http_client is shared_client

    # Verify dependency injection via app lifespan
    from app.main import app
    from app.api.deps import get_provider
    app.state.http_client = shared_client
    mock_request = MagicMock()
    mock_request.app = app
    dep_provider = get_provider(mock_request)
    assert dep_provider.http_client is shared_client

    await shared_client.aclose()


@pytest.mark.asyncio
async def test_error_payload_handling():
    """Verify HTTP 200 with status=error or code field is treated as an error."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    # Return 200 OK with error payload
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "error",
        "code": 401,
        "message": "Invalid API key provided",
    }
    mock_client.get.return_value = mock_resp

    limiter = TokenBucketRateLimiter(rate_per_minute=100.0)
    provider = TwelveDataProvider(api_key="bad_key", http_client=mock_client, rate_limiter=limiter)

    with pytest.raises(TwelveDataError, match="Invalid API key provided"):
        await provider.fetch_candles("XAU/USD", "15m", limit=10)


@pytest.mark.asyncio
async def test_429_rate_limit_retry_and_loud_failure():
    """Verify 429 encounters sleep and retries up to 3 times then fails loudly."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "Too Many Requests"
    mock_client.get.return_value = mock_resp

    limiter = TokenBucketRateLimiter(rate_per_minute=1000.0)
    provider = TwelveDataProvider(api_key="test_key", http_client=mock_client, rate_limiter=limiter)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(TwelveDataRateLimitError, match="HTTP 429 rate limit exceeded after 3 retries"):
            await provider.fetch_candles("XAU/USD", "15m", limit=10)

        # 3 retries => slept 60s three times
        assert mock_sleep.call_count >= 3


@pytest.mark.asyncio
async def test_forming_bar_dropped_by_timestamp_rule():
    """Verify forming bar is dropped when ts + delta > now_utc, never by index."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    now_utc = datetime(2026, 11, 15, 12, 5, 0, tzinfo=timezone.utc)

    # Closed bar: 11:45 (closes at 12:00 <= 12:05)
    # Forming bar: 12:00 (closes at 12:15 > 12:05)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "ok",
        "values": [
            {
                "datetime": "2026-11-15 11:45:00",
                "open": "2600.0",
                "high": "2605.0",
                "low": "2595.0",
                "close": "2602.0",
                "volume": "100",
            },
            {
                "datetime": "2026-11-15 12:00:00",
                "open": "2602.0",
                "high": "2608.0",
                "low": "2601.0",
                "close": "2607.0",
                "volume": "50",
            },
        ],
    }
    mock_client.get.return_value = mock_resp

    limiter = TokenBucketRateLimiter(rate_per_minute=100.0)
    provider = TwelveDataProvider(api_key="test_key", http_client=mock_client, rate_limiter=limiter)

    with patch("app.services.market_data.twelvedata_provider.datetime") as mock_dt:
        mock_dt.now.return_value = now_utc
        mock_dt.strptime = datetime.strptime

        candles = await provider.fetch_candles("XAU/USD", "15m", limit=10, drop_unclosed=True)
        assert len(candles) == 1
        assert candles[0].timestamp == datetime(2026, 11, 15, 11, 45, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_daily_budget_stop(test_db_session):
    """Verify hard stop at 780 calls/day persisted in api_usage table."""
    today = date.today()
    # Seed table at 780 calls (upsert)
    usage = test_db_session.query(ApiUsage).filter(ApiUsage.date == today).first()
    if not usage:
        usage = ApiUsage(date=today, calls=780)
        test_db_session.add(usage)
    else:
        usage.calls = 780
    test_db_session.commit()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    limiter = TokenBucketRateLimiter(rate_per_minute=100.0)

    def test_session_factory():
        return test_db_session

    provider = TwelveDataProvider(
        api_key="test_key",
        http_client=mock_client,
        session_factory=test_session_factory,
        rate_limiter=limiter,
    )

    with pytest.raises(TwelveDataBudgetExceededError, match="daily budget exhausted"):
        await provider.fetch_candles("XAU/USD", "15m", limit=10)


@pytest.mark.asyncio
async def test_ohlc_invariants_rejected_and_counted():
    """Verify invalid OHLC rows (high < max(open, close), low > min(open, close)) are rejected and counted."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "ok",
        "values": [
            # Valid row
            {
                "datetime": "2026-11-15 10:00:00",
                "open": "2600.0",
                "high": "2605.0",
                "low": "2595.0",
                "close": "2602.0",
                "volume": "100",
            },
            # Invalid: high < open
            {
                "datetime": "2026-11-15 10:15:00",
                "open": "2610.0",
                "high": "2605.0",
                "low": "2595.0",
                "close": "2600.0",
                "volume": "100",
            },
            # Invalid: low > close
            {
                "datetime": "2026-11-15 10:30:00",
                "open": "2600.0",
                "high": "2605.0",
                "low": "2602.0",
                "close": "2598.0",
                "volume": "100",
            },
        ],
    }
    mock_client.get.return_value = mock_resp

    limiter = TokenBucketRateLimiter(rate_per_minute=100.0)
    provider = TwelveDataProvider(api_key="test_key", http_client=mock_client, rate_limiter=limiter)

    now_utc = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
    with patch("app.services.market_data.twelvedata_provider.datetime") as mock_dt:
        mock_dt.now.return_value = now_utc
        mock_dt.strptime = datetime.strptime

        candles = await provider.fetch_candles("XAU/USD", "15m", limit=10)
        assert len(candles) == 1
        assert provider.rejected_rows_count == 2
