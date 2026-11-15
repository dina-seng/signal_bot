"""Unit tests for Spot Gold (XAU/USD) Market Calendar and Closed-Market Handling."""

from datetime import datetime, timedelta, timezone
import pytest

from app.schemas.candle import CandleCreate
from app.services.market_data.calendar import (
    is_market_open,
    filter_open_market_candles,
    is_forex_weekend,
)
from app.services.market_data.freshness import check_data_staleness
from app.services.market_data.resample import resample_ohlc


def _bar(ts: datetime, o=2650.0, h=2655.0, l=2648.0, c=2652.0) -> CandleCreate:
    return CandleCreate(
        symbol="XAU/USD",
        timeframe="15m",
        timestamp=ts,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=100.0,
    )


def test_is_market_open_dst_summer():
    """Verify market open/closed boundaries in summer (EDT = UTC-4)."""
    # Summer date: July 17, 2026 (Friday)
    # Friday 16:45 NY = 20:45 UTC -> OPEN
    assert is_market_open(datetime(2026, 7, 17, 20, 45, tzinfo=timezone.utc)) is True
    # Friday 17:00 NY = 21:00 UTC -> CLOSED
    assert is_market_open(datetime(2026, 7, 17, 21, 0, tzinfo=timezone.utc)) is False
    # Friday 22:00 UTC -> CLOSED
    assert is_market_open(datetime(2026, 7, 17, 22, 0, tzinfo=timezone.utc)) is False

    # Saturday July 18, 2026 -> CLOSED all day
    assert is_market_open(datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)) is False

    # Sunday July 19, 2026:
    # Sunday 17:45 NY = 21:45 UTC -> CLOSED
    assert is_market_open(datetime(2026, 7, 19, 21, 45, tzinfo=timezone.utc)) is False
    # Sunday 18:00 NY = 22:00 UTC -> OPEN
    assert is_market_open(datetime(2026, 7, 19, 22, 0, tzinfo=timezone.utc)) is True
    # Sunday 22:15 UTC -> OPEN
    assert is_market_open(datetime(2026, 7, 19, 22, 15, tzinfo=timezone.utc)) is True

    # Tuesday July 21, 2026: Daily break 17:00-18:00 NY = 21:00-22:00 UTC
    assert is_market_open(datetime(2026, 7, 21, 20, 45, tzinfo=timezone.utc)) is True
    assert is_market_open(datetime(2026, 7, 21, 21, 15, tzinfo=timezone.utc)) is False
    assert is_market_open(datetime(2026, 7, 21, 22, 0, tzinfo=timezone.utc)) is True


def test_is_market_open_dst_winter():
    """Verify market open/closed boundaries in winter (EST = UTC-5)."""
    # Winter date: January 16, 2026 (Friday)
    # Friday 16:45 NY = 21:45 UTC -> OPEN
    assert is_market_open(datetime(2026, 1, 16, 21, 45, tzinfo=timezone.utc)) is True
    # Friday 17:00 NY = 22:00 UTC -> CLOSED
    assert is_market_open(datetime(2026, 1, 16, 22, 0, tzinfo=timezone.utc)) is False

    # Saturday January 17, 2026 -> CLOSED
    assert is_market_open(datetime(2026, 1, 17, 15, 0, tzinfo=timezone.utc)) is False

    # Sunday January 18, 2026:
    # Sunday 17:45 NY = 22:45 UTC -> CLOSED
    assert is_market_open(datetime(2026, 1, 18, 22, 45, tzinfo=timezone.utc)) is False
    # Sunday 18:00 NY = 23:00 UTC -> OPEN
    assert is_market_open(datetime(2026, 1, 18, 23, 0, tzinfo=timezone.utc)) is True

    # Tuesday January 20, 2026: Daily break 17:00-18:00 NY = 22:00-23:00 UTC
    assert is_market_open(datetime(2026, 1, 20, 21, 45, tzinfo=timezone.utc)) is True
    assert is_market_open(datetime(2026, 1, 20, 22, 30, tzinfo=timezone.utc)) is False
    assert is_market_open(datetime(2026, 1, 20, 23, 0, tzinfo=timezone.utc)) is True


def test_filter_open_market_candles_drops_placeholder_bars():
    """Verify filter_open_market_candles retains only genuine trading bars."""
    bars = [
        _bar(datetime(2026, 7, 17, 20, 45, tzinfo=timezone.utc)), # Fri 16:45 NY -> Keep
        _bar(datetime(2026, 7, 17, 21, 0, tzinfo=timezone.utc)),  # Fri 17:00 NY -> Drop
        _bar(datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)),  # Sat -> Drop
        _bar(datetime(2026, 7, 19, 21, 45, tzinfo=timezone.utc)), # Sun 17:45 NY -> Drop
        _bar(datetime(2026, 7, 19, 22, 0, tzinfo=timezone.utc)),  # Sun 18:00 NY -> Keep
    ]
    filtered = filter_open_market_candles(bars)
    assert len(filtered) == 2
    assert filtered[0].timestamp == datetime(2026, 7, 17, 20, 45, tzinfo=timezone.utc)
    assert filtered[1].timestamp == datetime(2026, 7, 19, 22, 0, tzinfo=timezone.utc)


def test_staleness_logic_during_closed_market():
    """Verify closed market (weekend or daily break) does NOT mark data STALE."""
    # Weekend Saturday reference time
    ref_sat = datetime(2026, 7, 18, 14, 0, tzinfo=timezone.utc)
    fri_close_bar = _bar(datetime(2026, 7, 17, 20, 45, tzinfo=timezone.utc))

    res_sat = check_data_staleness([fri_close_bar], symbol="XAU/USD", timeframe="15m", as_of=ref_sat)
    assert res_sat.is_stale is False
    assert "closed" in res_sat.message.lower()

    # Weekday daily break reference time (Tuesday 21:30 UTC = 17:30 NY)
    ref_break = datetime(2026, 7, 21, 21, 30, tzinfo=timezone.utc)
    break_close_bar = _bar(datetime(2026, 7, 21, 20, 45, tzinfo=timezone.utc))
    res_break = check_data_staleness([break_close_bar], symbol="XAU/USD", timeframe="15m", as_of=ref_break)
    assert res_break.is_stale is False
    assert "closed" in res_break.message.lower()


def test_edge_bucket_resampling():
    """Verify how 1h/4h/daily buckets treat open/close edges."""
    # 4h bucket during daily break (Tuesday 20:00 - 00:00 UTC summer):
    # Active: 20:00, 20:15, 20:30, 20:45 (4 bars), then 22:00 to 23:45 (8 bars) = 12 open bars
    base = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
    open_bars_in_4h = [
        _bar(base + timedelta(minutes=15 * i))
        for i in range(16)
        if is_market_open(base + timedelta(minutes=15 * i))
    ]
    assert len(open_bars_in_4h) == 12

    # With calendar_aware=True, bucket emits complete 4h bar
    res = resample_ohlc(open_bars_in_4h, "4h", strict_completeness=True, calendar_aware=True)
    assert len(res) == 1
    assert res[0].timestamp == base

    # Daily bucket (1d) spanning Sunday 18:00 NY to Monday 17:00 NY: exactly 92 15m bars
    sun_open = datetime(2026, 7, 19, 22, 0, tzinfo=timezone.utc)
    daily_open_bars = [
        _bar(sun_open + timedelta(minutes=15 * i))
        for i in range(92)
    ]
    assert all(is_market_open(b.timestamp) for b in daily_open_bars)
    res_1d = resample_ohlc(daily_open_bars, "1d", strict_completeness=True, expected_daily_bars=92)
    assert len(res_1d) == 1
