"""Comprehensive Unit & Integration Tests for Milestone 2: News Integrity and Fail-Safe Protection."""

from datetime import datetime, timedelta, timezone
import pytest
import httpx
from app.models.news import NewsEvent
from app.schemas.candle import CandleBase
from app.schemas.news import (
    NewsBlackoutCheckResponse,
    NewsEventCreate,
    NewsImpact,
    NewsSyncReport,
)
from app.schemas.signal import SignalDirection
from app.schemas.telegram import TelegramCommandRequest
from app.services.news.base import BaseNewsProvider
from app.services.news.filter_engine import NewsFilterEngine
from app.services.news.forexfactory_provider import ForexFactoryProvider
from app.services.news.ingestion import NewsIngestionService, generate_event_fingerprint
from app.services.news.mock_provider import MockNewsProvider
from app.services.signals.confluence_engine import ConfluenceEngine
from app.services.signals.signal_generator import SignalGenerator
from app.services.telegram.client import MockTelegramClient
from app.services.telegram.command_handler import TelegramCommandHandler
from app.services.telegram.message_formatter import TelegramMessageFormatter


# ---------------------------------------------------------------------------
# 1. Provider Failure Handling & No Mock Fallback Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_live_provider_failure_returns_empty_and_no_mock_injection(monkeypatch):
    """Ensure ForexFactoryProvider returns empty list on network error and never injects mock events."""
    class FailingAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def get(self, url):
            request = httpx.Request("GET", url)
            return httpx.Response(status_code=500, request=request)

    monkeypatch.setattr(httpx, "AsyncClient", FailingAsyncClient)

    provider = ForexFactoryProvider(timeout_seconds=1.0)
    assert provider.is_live_provider is True

    events = await provider.fetch_events()
    assert events == []
    assert len(events) == 0


def test_mock_provider_is_not_live():
    """Ensure MockNewsProvider is flagged as non-live."""
    mock_p = MockNewsProvider()
    assert mock_p.is_live_provider is False


# ---------------------------------------------------------------------------
# 2. Deterministic Event Identity & Deduplication Tests
# ---------------------------------------------------------------------------
def test_deterministic_event_fingerprint():
    """Verify SHA-256 event fingerprint identity generation."""
    t1 = datetime(2026, 8, 28, 14, 30, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 28, 14, 30, 0)  # Naive UTC

    fp1 = generate_event_fingerprint("USD", "Non-Farm Employment Change", t1)
    fp2 = generate_event_fingerprint("usd ", " Non-Farm Employment Change ", t2)

    assert fp1 == fp2
    assert len(fp1) == 64  # Valid SHA-256 hex


def test_event_deduplication_and_in_place_updates(test_db_session):
    """Verify NewsIngestionService deduplicates events and updates existing records in place."""
    t = datetime(2026, 8, 28, 14, 30, 0, tzinfo=timezone.utc)
    mock_p = MockNewsProvider()
    service = NewsIngestionService(provider=mock_p, db=test_db_session)

    # 1. Initial Ingestion
    event_initial = NewsEventCreate(
        currency="USD",
        event_name="CPI m/m",
        impact=NewsImpact.HIGH,
        scheduled_time=t,
        previous="0.2%",
        forecast="0.3%",
        actual=None,
    )
    report1 = service.ingest_events([event_initial])
    assert report1.inserted_count == 1
    assert report1.updated_count == 0
    assert report1.skipped_count == 0

    # 2. Second Ingestion with Actual Result released (Update)
    event_updated = NewsEventCreate(
        currency="USD",
        event_name="CPI m/m",
        impact=NewsImpact.HIGH,
        scheduled_time=t,
        previous="0.2%",
        forecast="0.3%",
        actual="0.4%",
    )
    report2 = service.ingest_events([event_updated])
    assert report2.inserted_count == 0
    assert report2.updated_count == 1
    assert report2.skipped_count == 0

    # Verify single DB row with updated actual value
    rows = test_db_session.query(NewsEvent).filter_by(currency="USD", event_name="CPI m/m").all()
    assert len(rows) == 1
    assert rows[0].actual == "0.4%"

    # 3. Third Ingestion with Identical Data (Skipped)
    report3 = service.ingest_events([event_updated])
    assert report3.inserted_count == 0
    assert report3.updated_count == 0
    assert report3.skipped_count == 1


# ---------------------------------------------------------------------------
# 3. Stale Calendar Detection Tests
# ---------------------------------------------------------------------------
def test_calendar_staleness_detection(test_db_session):
    """Verify staleness detection flags empty or outdated calendars."""
    mock_p = MockNewsProvider()
    service = NewsIngestionService(provider=mock_p, db=test_db_session)

    # Empty DB on Friday -> Stale
    friday_noon = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
    is_stale, msg = service.check_calendar_staleness(reference_time=friday_noon)
    assert is_stale is True
    assert "0 events found" in msg

    # Add event in window -> Fresh
    test_db_session.add(
        NewsEvent(
            currency="USD",
            event_name="FOMC Decision",
            impact="HIGH",
            scheduled_time=friday_noon + timedelta(hours=2),
        )
    )
    test_db_session.commit()

    is_stale2, msg2 = service.check_calendar_staleness(reference_time=friday_noon)
    assert is_stale2 is False
    assert "fresh" in msg2


# ---------------------------------------------------------------------------
# 4. Fail-Safe Trade Blocking Tests (Do Not Generate New Trade)
# ---------------------------------------------------------------------------
def test_confluence_engine_blocks_trades_when_news_data_unavailable():
    """Verify ConfluenceEngine returns WAIT (no trade generated) when news is unavailable / fail-safe active."""
    engine = ConfluenceEngine()

    # Generate sample 1h candles
    base_t = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)
    candles = [
        CandleBase(
            symbol="EUR/USD",
            timeframe="1h",
            timestamp=base_t + timedelta(hours=i),
            open=1.0800 + i * 0.0005,
            high=1.0820 + i * 0.0005,
            low=1.0790 + i * 0.0005,
            close=1.0815 + i * 0.0005,
            volume=1000.0,
        )
        for i in range(25)
    ]

    # News Check indicating live news is unavailable (Fail-Safe active)
    fail_safe_news = NewsBlackoutCheckResponse(
        symbol="EUR/USD",
        checked_time=base_t + timedelta(hours=26),
        is_blackout=False,
        trading_allowed=False,
        is_news_unavailable=True,
        is_fail_safe=True,
        calendar_stale=True,
        reason="NEWS DATA UNAVAILABLE: Live economic calendar could not be verified. Fail-safe active - trading paused until news feed restored.",
    )

    sig = engine.evaluate(
        symbol="EUR/USD",
        candles_primary=candles,
        timeframe="1h",
        news_check=fail_safe_news,
    )

    assert sig.direction == SignalDirection.WAIT
    assert sig.setup_score == 0.0
    assert "NEWS DATA UNAVAILABLE" in sig.reasons[0]
    assert sig.score_breakdown.is_qualified is False


# ---------------------------------------------------------------------------
# 5. /news Telegram Command Refresh & Fail-Safe Formatting Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_telegram_news_command_live_unavailable_shows_failsafe(test_db_session):
    """Verify /news command shows FAIL-SAFE alert when live news feed fails and DB has no events."""
    class FailingProvider(BaseNewsProvider):
        @property
        def is_live_provider(self) -> bool:
            return True

        async def fetch_events(self, *args, **kwargs):
            raise httpx.ConnectError("Network unreachable")

    failing_provider = FailingProvider()
    mock_client = MockTelegramClient()

    handler = TelegramCommandHandler(
        news_provider=failing_provider,
        telegram_client=mock_client,
    )

    req = TelegramCommandRequest(command="/news", chat_id="12345")
    res = await handler.handle_command(test_db_session, req)

    assert res.handled_successfully is True
    assert "NEWS DATA UNAVAILABLE" in res.reply_text
    assert "FAIL-SAFE ACTIVATED" in res.reply_text
    assert "Live economic calendar feed is currently unreachable" in res.reply_text


@pytest.mark.asyncio
async def test_telegram_news_command_shows_events_when_available(test_db_session):
    """Verify /news command refreshes and formats upcoming events when available."""
    ref = datetime.now(timezone.utc)
    mock_p = MockNewsProvider(reference_time=ref)
    mock_client = MockTelegramClient()

    handler = TelegramCommandHandler(
        news_provider=mock_p,
        telegram_client=mock_client,
    )

    req = TelegramCommandRequest(command="/news", chat_id="12345")
    res = await handler.handle_command(test_db_session, req)

    assert res.handled_successfully is True
    assert "ECONOMIC CALENDAR & NEWS MONITOR" in res.reply_text
