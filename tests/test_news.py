"""Unit tests for Economic News Provider, Ingestion, and Blackout Filter Engine."""

from datetime import datetime, timedelta, timezone
import pytest
from app.models.news import NewsEvent
from app.schemas.news import NewsImpact
from app.services.news.mock_provider import MockNewsProvider
from app.services.news.ingestion import NewsIngestionService
from app.services.news.filter_engine import NewsFilterEngine


@pytest.mark.asyncio
async def test_mock_news_provider():
    """Test MockNewsProvider generation and date/currency filtering."""
    ref_time = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    provider = MockNewsProvider(reference_time=ref_time)

    events = await provider.fetch_events()
    assert len(events) > 5

    # Test currency filtering
    usd_events = await provider.fetch_events(currencies=["USD"])
    assert all(e.currency == "USD" for e in usd_events)
    assert len(usd_events) > 0


def test_news_ingestion_service_deduplication(test_db_session):
    """Test NewsIngestionService persistence and duplicate prevention."""
    ref_time = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    provider = MockNewsProvider(reference_time=ref_time)
    service = NewsIngestionService(provider=provider, db=test_db_session)

    # First pass
    events = [
        provider.fetch_events.__wrapped__(provider) if hasattr(provider.fetch_events, "__wrapped__") else None
    ]
    # Use sync helper
    import asyncio
    events = asyncio.run(provider.fetch_events())

    report1 = service.ingest_events(events)
    assert report1.inserted_count == len(events)
    assert report1.skipped_count == 0

    # Query DB
    rows = test_db_session.query(NewsEvent).all()
    assert len(rows) == len(events)

    # Second pass (Idempotency)
    report2 = service.ingest_events(events)
    assert report2.inserted_count == 0
    assert report2.skipped_count == len(events)


def test_news_filter_blackout_window():
    """Test NewsFilterEngine blackout window timings (pre-news, during, post-news buffer, and safe times)."""
    filter_engine = NewsFilterEngine(before_minutes=30, after_minutes=15)
    event_time = datetime(2026, 8, 28, 14, 30, tzinfo=timezone.utc)

    nfp_event = NewsEvent(
        id=1,
        currency="USD",
        event_name="Non-Farm Employment Change",
        impact="HIGH",
        scheduled_time=event_time,
    )

    # 1. 40 minutes before event -> Safe (Not in blackout)
    t_safe_before = event_time - timedelta(minutes=40)
    res1 = filter_engine.is_trading_allowed(
        symbol="EUR/USD",
        events=[nfp_event],
        target_time=t_safe_before,
    )
    assert res1.is_blackout is False
    assert res1.trading_allowed is True
    assert res1.minutes_to_next_event == 40.0

    # 2. 20 minutes before event -> Blackout! (Within 30 min pre-buffer)
    t_blackout_pre = event_time - timedelta(minutes=20)
    res2 = filter_engine.is_trading_allowed(
        symbol="EUR/USD",
        events=[nfp_event],
        target_time=t_blackout_pre,
    )
    assert res2.is_blackout is True
    assert res2.trading_allowed is False
    assert len(res2.blackout_events) == 1
    assert "TRADING BLOCKED" in res2.reason

    # 3. Exact event release time -> Blackout!
    res3 = filter_engine.is_trading_allowed(
        symbol="EUR/USD",
        events=[nfp_event],
        target_time=event_time,
    )
    assert res3.is_blackout is True
    assert res3.trading_allowed is False

    # 4. 10 minutes after event -> Blackout! (Within 15 min post-buffer)
    t_blackout_post = event_time + timedelta(minutes=10)
    res4 = filter_engine.is_trading_allowed(
        symbol="EUR/USD",
        events=[nfp_event],
        target_time=t_blackout_post,
    )
    assert res4.is_blackout is True
    assert res4.trading_allowed is False

    # 5. 25 minutes after event -> Safe (Post-buffer expired)
    t_safe_after = event_time + timedelta(minutes=25)
    res5 = filter_engine.is_trading_allowed(
        symbol="EUR/USD",
        events=[nfp_event],
        target_time=t_safe_after,
    )
    assert res5.is_blackout is False
    assert res5.trading_allowed is True
    assert res5.minutes_since_last_event == 25.0


def test_news_filter_currency_isolation():
    """Test that currency-specific releases only block relevant pairs."""
    filter_engine = NewsFilterEngine(before_minutes=30, after_minutes=15)
    event_time = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

    ecb_event = NewsEvent(
        id=1,
        currency="EUR",
        event_name="ECB Rate Decision",
        impact="HIGH",
        scheduled_time=event_time,
    )

    # 1. EUR/USD should be blocked
    res_eur = filter_engine.is_trading_allowed(
        symbol="EUR/USD",
        events=[ecb_event],
        target_time=event_time,
    )
    assert res_eur.is_blackout is True

    # 2. USD/JPY should NOT be blocked by EUR news
    res_jpy = filter_engine.is_trading_allowed(
        symbol="USD/JPY",
        events=[ecb_event],
        target_time=event_time,
    )
    assert res_jpy.is_blackout is False
    assert res_jpy.trading_allowed is True

    # 3. Gold (XAU/USD) is sensitive to USD news
    usd_event = NewsEvent(
        id=2,
        currency="USD",
        event_name="FOMC Decision",
        impact="HIGH",
        scheduled_time=event_time,
    )
    res_gold = filter_engine.is_trading_allowed(
        symbol="XAU/USD",
        events=[usd_event],
        target_time=event_time,
    )
    assert res_gold.is_blackout is True
