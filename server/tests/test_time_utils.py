"""Unit tests for Timezone Utility and Local Time Presentation."""

import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.time_utils import format_local_time, get_user_timezone
from app.schemas.signal import (
    RiskParameters,
    ScoreBreakdown,
    SignalDirection,
    SignalResponse,
    SignalStatus,
)
from app.services.telegram.message_formatter import TelegramMessageFormatter


def test_naive_utc_datetime_converted_to_local(monkeypatch):
    """Verify that naive datetimes are assumed to be UTC and converted correctly."""
    monkeypatch.setattr(settings, "USER_TIMEZONE", "Asia/Bangkok")
    naive_dt = datetime(2026, 9, 24, 8, 30, 0)  # Naive UTC: 08:30

    result = format_local_time(naive_dt)

    # In Asia/Bangkok (UTC+7), 08:30 UTC is 15:30 +07
    assert result == "2026-09-24 15:30:00 +07"
    # Ensure original datetime object was not mutated
    assert naive_dt.tzinfo is None
    assert naive_dt.hour == 8


def test_timezone_aware_utc_datetime_converted(monkeypatch):
    """Verify that timezone-aware UTC datetimes are converted to configured local timezone."""
    monkeypatch.setattr(settings, "USER_TIMEZONE", "America/New_York")
    aware_dt = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)

    # In late September, New York is on daylight saving time (EDT = UTC-4)
    # 12:00 UTC -> 08:00 EDT
    result = format_local_time(aware_dt)
    assert result == "2026-09-24 08:00:00 EDT"
    assert aware_dt.tzinfo == timezone.utc
    assert aware_dt.hour == 12


def test_default_utc_configuration(monkeypatch):
    """Verify that default UTC configuration formats cleanly with UTC identifier."""
    monkeypatch.setattr(settings, "USER_TIMEZONE", "UTC")
    aware_dt = datetime(2026, 9, 24, 8, 30, 0, tzinfo=timezone.utc)

    result = format_local_time(aware_dt)
    assert result == "2026-09-24 08:30:00 UTC"


def test_explicit_timezone_override():
    """Verify that passing an explicit timezone override parameter works."""
    dt = datetime(2026, 9, 24, 8, 30, 0, tzinfo=timezone.utc)

    # Explicit Tokyo (+09)
    tokyo_result = format_local_time(dt, tz="Asia/Tokyo")
    assert tokyo_result == "2026-09-24 17:30:00 JST"

    # Explicit ZoneInfo instance
    london_result = format_local_time(dt, tz=ZoneInfo("Europe/London"))
    # In September, London is on BST (UTC+1) -> 09:30
    assert london_result == "2026-09-24 09:30:00 BST"


def test_invalid_timezone_fallback_to_utc(monkeypatch):
    """Verify that an invalid timezone string safely falls back to UTC without crashing."""
    monkeypatch.setattr(settings, "USER_TIMEZONE", "Invalid/Nonexistent_Timezone_123")
    dt = datetime(2026, 9, 24, 8, 30, 0, tzinfo=timezone.utc)

    result = format_local_time(dt)
    assert result == "2026-09-24 08:30:00 UTC"


def test_none_datetime_handling():
    """Verify graceful handling when None is passed."""
    assert format_local_time(None) == "N/A"


def test_backend_utc_integrity():
    """Verify backend datetime storage and strategy objects remain strictly in UTC."""
    utc_now = datetime(2026, 9, 24, 10, 0, 0, tzinfo=timezone.utc)
    
    # Simulate signal generation with UTC timestamp
    sig = SignalResponse(
        symbol="USD/JPY",
        timeframe="15m",
        direction=SignalDirection.BUY,
        setup_score=85.0,
        entry_price=158.35,
        stop_loss=158.20,
        take_profit_1=158.65,
        take_profit_2=158.95,
        risk_reward=2.0,
        fingerprint="test_fp",
        reasons=["Bullish BOS"],
        status=SignalStatus.ACTIVE,
        timestamp=utc_now,
        score_breakdown=ScoreBreakdown(
            structure_score=30.0,
            liquidity_score=30.0,
            indicators_score=10.0,
            price_action_score=15.0,
            total_score=85.0,
            is_qualified=True,
        ),
    )

    # 1. Backend integrity check: Signal object preserves exact UTC timestamp
    assert sig.timestamp == utc_now
    assert sig.timestamp.tzinfo == timezone.utc
    assert sig.timestamp.hour == 10

    # 2. Presentation check: Formatter converts only string output to local time
    formatter = TelegramMessageFormatter()
    msg = formatter.format_signal_alert(sig)

    # Signal object MUST still be strictly UTC
    assert sig.timestamp == utc_now
    assert sig.timestamp.hour == 10
    # The formatted message contains the formatted timestamp
    assert format_local_time(sig.timestamp) in msg
