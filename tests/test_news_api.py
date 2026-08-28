"""API integration tests for Economic News and Blackout Filter endpoints."""

from datetime import datetime, timedelta, timezone
import pytest
from app.models.news import NewsEvent


def seed_news_events(db):
    """Seed test economic events in DB."""
    base_time = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    events = [
        NewsEvent(
            currency="USD",
            event_name="Non-Farm Payrolls",
            impact="HIGH",
            scheduled_time=base_time,
            previous="180K",
            forecast="175K",
        ),
        NewsEvent(
            currency="EUR",
            event_name="ECB Rate Decision",
            impact="HIGH",
            scheduled_time=base_time + timedelta(hours=3),
            previous="3.75%",
            forecast="3.50%",
        ),
        NewsEvent(
            currency="GBP",
            event_name="Retail Sales",
            impact="MEDIUM",
            scheduled_time=base_time + timedelta(hours=5),
            previous="0.1%",
            forecast="0.2%",
        ),
    ]
    db.add_all(events)
    db.commit()


def test_get_economic_calendar(client, test_db_session):
    """Test retrieving economic calendar events via API."""
    seed_news_events(test_db_session)

    response = client.get("/api/v1/news/calendar")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3

    # Test currency filter
    res_usd = client.get("/api/v1/news/calendar?currency=USD")
    assert res_usd.status_code == 200
    data_usd = res_usd.json()
    assert len(data_usd) == 1
    assert data_usd[0]["currency"] == "USD"


def test_check_news_blackout_endpoint(client, test_db_session):
    """Test news blackout check endpoint."""
    seed_news_events(test_db_session)
    event_time = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc).isoformat()

    # Query during blackout for USD
    response = client.get(f"/api/v1/news/check/EUR/USD?target_time={event_time}&before_minutes=30&after_minutes=15")
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "EUR/USD"
    assert data["is_blackout"] is True
    assert data["trading_allowed"] is False
    assert len(data["blackout_events"]) > 0

    # Query at safe time (2 hours after USD news, 1 hour before EUR news)
    safe_time = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc).isoformat()
    response_safe = client.get(f"/api/v1/news/check/EUR/USD?target_time={safe_time}&before_minutes=30&after_minutes=15")
    assert response_safe.status_code == 200
    data_safe = response_safe.json()

    assert data_safe["symbol"] == "EUR/USD"
    assert data_safe["is_blackout"] is False
    assert data_safe["trading_allowed"] is True


def test_sync_economic_calendar_endpoint(client):
    """Test POST /api/v1/news/sync endpoint."""
    response = client.post("/api/v1/news/sync")
    assert response.status_code == 200
    data = response.json()

    assert "fetched_count" in data
    assert "inserted_count" in data
    assert data["fetched_count"] > 0
