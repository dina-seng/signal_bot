"""Comprehensive Unit & Integration Tests for Milestone 1: Data Freshness, Closed Candle Selection, and Refresh."""

from datetime import datetime, timedelta, timezone
import pytest
from app.models.candle import Candle
from app.schemas.candle import CandleBase, CandleCreate
from app.schemas.telegram import TelegramCommandRequest
from app.services.market_data.freshness import (
    DEFAULT_STALENESS_THRESHOLDS,
    TIMEFRAME_DELTAS,
    check_data_staleness,
    ensure_utc_datetime,
    filter_closed_candles,
    format_candle_log_line,
    get_latest_closed_candle,
    get_timeframe_delta,
    is_candle_closed,
    is_forex_weekend,
    log_latest_candle,
)
from app.services.market_data.mock_provider import MockMarketDataProvider
from app.services.telegram.client import MockTelegramClient
from app.services.telegram.command_handler import TelegramCommandHandler


# ---------------------------------------------------------------------------
# 1. Timestamp & Timeframe Delta Tests
# ---------------------------------------------------------------------------
def test_ensure_utc_datetime():
    """Verify UTC normalization for naive and aware datetimes."""
    assert ensure_utc_datetime(None) is None

    # Naive datetime
    naive = datetime(2026, 8, 28, 14, 30, 0)
    aware = ensure_utc_datetime(naive)
    assert aware.tzinfo == timezone.utc
    assert aware.year == 2026 and aware.month == 8 and aware.day == 28
    assert aware.hour == 14 and aware.minute == 30

    # Already aware UTC
    utc_dt = datetime(2026, 8, 28, 14, 30, 0, tzinfo=timezone.utc)
    res = ensure_utc_datetime(utc_dt)
    assert res == utc_dt


def test_get_timeframe_delta():
    """Verify timeframe string conversion to timedelta."""
    assert get_timeframe_delta("1m") == timedelta(minutes=1)
    assert get_timeframe_delta("5m") == timedelta(minutes=5)
    assert get_timeframe_delta("15m") == timedelta(minutes=15)
    assert get_timeframe_delta("30m") == timedelta(minutes=30)
    assert get_timeframe_delta("1h") == timedelta(hours=1)
    assert get_timeframe_delta("4h") == timedelta(hours=4)
    assert get_timeframe_delta("1d") == timedelta(days=1)
    assert get_timeframe_delta("1w") == timedelta(weeks=1)

    with pytest.raises(ValueError):
        get_timeframe_delta("unsupported_tf")


# ---------------------------------------------------------------------------
# 2. Weekend Detection Tests
# ---------------------------------------------------------------------------
def test_is_forex_weekend():
    """Verify Forex weekend closure detection (Friday 21:00 UTC - Sunday 21:00 UTC)."""
    # Friday 15:00 UTC -> Market Open
    fri_open = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
    assert is_forex_weekend(fri_open) is False

    # Friday 21:30 UTC -> Market Closed
    fri_closed = datetime(2026, 8, 28, 21, 30, tzinfo=timezone.utc)
    assert is_forex_weekend(fri_closed) is True

    # Saturday 12:00 UTC -> Market Closed
    sat = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    assert is_forex_weekend(sat) is True

    # Sunday 18:00 UTC -> Market Closed
    sun_early = datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc)
    assert is_forex_weekend(sun_early) is True

    # Sunday 22:00 UTC -> Market Reopened
    sun_open = datetime(2026, 8, 30, 22, 0, tzinfo=timezone.utc)
    assert is_forex_weekend(sun_open) is False

    # Monday 10:00 UTC -> Market Open
    mon = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    assert is_forex_weekend(mon) is False


# ---------------------------------------------------------------------------
# 3. Latest Closed Candle Selection Tests
# ---------------------------------------------------------------------------
def test_is_candle_closed():
    """Verify closed vs in-progress candle identification."""
    ref_time = datetime(2026, 8, 28, 14, 25, tzinfo=timezone.utc)

    # 1h candle starting at 13:00 closes at 14:00 (14:00 <= 14:25 -> CLOSED)
    c_1300 = CandleBase(
        symbol="EUR/USD",
        timeframe="1h",
        timestamp=datetime(2026, 8, 28, 13, 0, tzinfo=timezone.utc),
        open=1.0800,
        high=1.0850,
        low=1.0790,
        close=1.0830,
    )
    assert is_candle_closed(c_1300, timeframe="1h", as_of=ref_time) is True

    # 1h candle starting at 14:00 closes at 15:00 (15:00 > 14:25 -> UNCLOSED / FORMING)
    c_1400 = CandleBase(
        symbol="EUR/USD",
        timeframe="1h",
        timestamp=datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc),
        open=1.0830,
        high=1.0860,
        low=1.0820,
        close=1.0840,
    )
    assert is_candle_closed(c_1400, timeframe="1h", as_of=ref_time) is False


def test_filter_closed_candles_and_latest():
    """Verify filter_closed_candles excludes forming candles and selects latest closed."""
    ref_time = datetime(2026, 8, 28, 14, 30, tzinfo=timezone.utc)

    candles = [
        CandleBase(
            symbol="EUR/USD",
            timeframe="15m",
            timestamp=datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc),  # closes 14:15 <= 14:30 (CLOSED)
            open=1.0800,
            high=1.0820,
            low=1.0790,
            close=1.0810,
        ),
        CandleBase(
            symbol="EUR/USD",
            timeframe="15m",
            timestamp=datetime(2026, 8, 28, 14, 15, tzinfo=timezone.utc),  # closes 14:30 <= 14:30 (CLOSED)
            open=1.0810,
            high=1.0830,
            low=1.0800,
            close=1.0825,
        ),
        CandleBase(
            symbol="EUR/USD",
            timeframe="15m",
            timestamp=datetime(2026, 8, 28, 14, 30, tzinfo=timezone.utc),  # closes 14:45 > 14:30 (FORMING/OPEN)
            open=1.0825,
            high=1.0840,
            low=1.0820,
            close=1.0835,
        ),
    ]

    closed = filter_closed_candles(candles, timeframe="15m", as_of=ref_time)
    assert len(closed) == 2
    assert closed[0].timestamp == datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)
    assert closed[1].timestamp == datetime(2026, 8, 28, 14, 15, tzinfo=timezone.utc)

    latest = get_latest_closed_candle(candles, timeframe="15m", as_of=ref_time)
    assert latest is not None
    assert latest.timestamp == datetime(2026, 8, 28, 14, 15, tzinfo=timezone.utc)
    assert latest.close == 1.0825


# ---------------------------------------------------------------------------
# 4. Stale Data Detection Tests
# ---------------------------------------------------------------------------
def test_check_data_staleness_fresh():
    """Verify fresh candle dataset passes staleness check."""
    now = datetime(2026, 8, 28, 14, 10, tzinfo=timezone.utc)  # Friday afternoon
    c1 = CandleBase(
        symbol="EUR/USD",
        timeframe="1h",
        timestamp=datetime(2026, 8, 28, 13, 0, tzinfo=timezone.utc),  # closed at 14:00 (10 min old)
        open=1.0800,
        high=1.0850,
        low=1.0790,
        close=1.0830,
    )

    res = check_data_staleness([c1], symbol="EUR/USD", timeframe="1h", as_of=now)
    assert res.is_stale is False
    assert res.symbol == "EUR/USD"
    assert res.age_seconds == 600.0  # 10 minutes
    assert "FRESH" in res.message


def test_check_data_staleness_stale():
    """Verify stale candle dataset is flagged when exceeding threshold."""
    now = datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc)  # Friday 20:00 UTC
    c1 = CandleBase(
        symbol="EUR/USD",
        timeframe="1h",
        timestamp=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),  # closed at 13:00 (7 hours old > 4h max)
        open=1.0800,
        high=1.0850,
        low=1.0790,
        close=1.0830,
    )

    res = check_data_staleness([c1], symbol="EUR/USD", timeframe="1h", as_of=now)
    assert res.is_stale is True
    assert res.age_hours == 7.0
    assert "STALE DATA DETECTED" in res.message


def test_check_data_staleness_empty():
    """Verify empty candle dataset is flagged as stale."""
    res = check_data_staleness([], symbol="EUR/USD", timeframe="1h")
    assert res.is_stale is True
    assert res.latest_candle_time is None
    assert "No candle data available" in res.message


def test_check_data_staleness_weekend_awareness():
    """Verify Friday close candle is recognized as valid during Saturday weekend closure."""
    saturday_noon = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    fri_close_candle = CandleBase(
        symbol="EUR/USD",
        timeframe="1h",
        timestamp=datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc),  # Friday 20:00 UTC
        open=1.0800,
        high=1.0850,
        low=1.0790,
        close=1.0830,
    )

    res = check_data_staleness([fri_close_candle], symbol="EUR/USD", timeframe="1h", as_of=saturday_noon)
    assert res.is_stale is False
    assert res.is_weekend is True
    assert "Market is closed for weekend" in res.message


# ---------------------------------------------------------------------------
# 5. Explicit Logging Formatter Tests
# ---------------------------------------------------------------------------
def test_format_candle_log_line():
    """Verify structured log line output format."""
    c = CandleBase(
        symbol="EUR/USD",
        timeframe="1h",
        timestamp=datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc),
        open=1.08123,
        high=1.08567,
        low=1.07989,
        close=1.08456,
        volume=1250.5,
    )

    line = format_candle_log_line(c, symbol="EUR/USD", timeframe="1h", context="TEST CONTEXT", is_fresh=True)
    assert "[TEST CONTEXT]" in line
    assert "Symbol: EUR/USD" in line
    assert "Timeframe: 1h" in line
    assert "2026-08-28 14:00:00 UTC" in line
    assert "Open: 1.08123" in line
    assert "High: 1.08567" in line
    assert "Low: 1.07989" in line
    assert "Close: 1.08456" in line
    assert "Volume: 1250.5" in line
    assert "Freshness: FRESH" in line


# ---------------------------------------------------------------------------
# 6. /signal Provider Synchronization & Freshness Integration Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_signal_command_refreshes_from_provider_and_selects_closed_candles(test_db_session):
    """Verify /signal command triggers provider synchronization and evaluates closed verified candles."""
    mock_provider = MockMarketDataProvider(base_price=1.1000)
    mock_client = MockTelegramClient()

    handler = TelegramCommandHandler(
        market_provider=mock_provider,
        telegram_client=mock_client,
    )

    # Execute /signal EUR/USD
    req = TelegramCommandRequest(command="/signal EUR/USD", chat_id="12345")
    res = await handler.handle_command(test_db_session, req)

    assert res.handled_successfully is True
    assert "EUR/USD" in res.reply_text

    # Verify candles were ingested into DB from provider
    db_candles = test_db_session.query(Candle).filter_by(symbol="EUR/USD", timeframe="1h").all()
    assert len(db_candles) > 0

    # Verify telegram client received response
    assert len(mock_client.sent_messages) == 1
    assert "12345" == mock_client.sent_messages[0]["chat_id"]
