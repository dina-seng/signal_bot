"""Unit tests for pure resampling functions."""

from datetime import datetime, timedelta, timezone
import zoneinfo
import pytest

from app.schemas.candle import CandleCreate
from app.services.market_data.resample import (
    get_bucket_start_utc,
    get_ny_session_start,
    resample_ohlc,
    NY_TZ,
)


def _make_15m_bar(ts: datetime, o=2000.0, h=2010.0, l=1990.0, c=2005.0, v=100.0) -> CandleCreate:
    return CandleCreate(
        symbol="XAU/USD",
        timeframe="15m",
        timestamp=ts,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=v,
    )


def test_resample_30m_complete_and_incomplete():
    """Verify 30m buckets require exactly 2 consecutive 15m bars."""
    base = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    # Complete 30m bucket (10:00, 10:15)
    b0 = _make_15m_bar(base, o=2650.0, h=2655.0, l=2648.0, c=2652.0, v=10.0)
    b1 = _make_15m_bar(base + timedelta(minutes=15), o=2652.0, h=2660.0, l=2650.0, c=2658.0, v=20.0)

    # Incomplete 30m bucket (only 10:30, missing 10:45)
    b2 = _make_15m_bar(base + timedelta(minutes=30), o=2658.0, h=2662.0, l=2655.0, c=2660.0, v=15.0)

    res = resample_ohlc([b0, b1, b2], "30m", strict_completeness=True)
    assert len(res) == 1
    assert res[0].timestamp == base
    assert res[0].open == 2650.0
    assert res[0].high == 2660.0
    assert res[0].low == 2648.0
    assert res[0].close == 2658.0
    assert res[0].volume == 30.0
    assert res[0].timeframe == "30m"


def test_resample_1h_golden_fixture():
    """Verify 1h bucket requires 4 consecutive bars and correctly aggregates OHLCV."""
    base = datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc)
    bars = [
        _make_15m_bar(base, o=100.0, h=105.0, l=98.0, c=102.0, v=10.0),
        _make_15m_bar(base + timedelta(minutes=15), o=102.0, h=110.0, l=101.0, c=108.0, v=20.0),
        _make_15m_bar(base + timedelta(minutes=30), o=108.0, h=109.0, l=95.0, c=97.0, v=30.0),
        _make_15m_bar(base + timedelta(minutes=45), o=97.0, h=103.0, l=96.0, c=101.0, v=40.0),
    ]

    res = resample_ohlc(bars, "1h", strict_completeness=True)
    assert len(res) == 1
    assert res[0].timestamp == base
    assert res[0].open == 100.0
    assert res[0].high == 110.0
    assert res[0].low == 95.0
    assert res[0].close == 101.0
    assert res[0].volume == 100.0
    assert res[0].timeframe == "1h"


def test_resample_1h_incomplete_omitted():
    """Verify incomplete 1h bucket (e.g. 3 bars) is omitted."""
    base = datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc)
    bars = [
        _make_15m_bar(base),
        _make_15m_bar(base + timedelta(minutes=15)),
        _make_15m_bar(base + timedelta(minutes=30)),
        # Missing :45
    ]
    res = resample_ohlc(bars, "1h", strict_completeness=True)
    assert len(res) == 0


def test_resample_4h_requires_16_bars():
    """Verify 4h bucket anchored at 00:00, 04:00, etc. requires 16 bars."""
    base = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)
    bars = [
        _make_15m_bar(base + timedelta(minutes=15 * i), o=2000.0 + i, h=2050.0, l=1950.0, c=2001.0 + i)
        for i in range(16)
    ]

    res = resample_ohlc(bars, "4h", strict_completeness=True)
    assert len(res) == 1
    assert res[0].timestamp == base
    assert res[0].open == 2000.0
    assert res[0].close == 2001.0 + 15

    # 15 bars => incomplete => omitted
    res_incomplete = resample_ohlc(bars[:15], "4h", strict_completeness=True)
    assert len(res_incomplete) == 0


def test_ny_session_daily_anchor_dst():
    """Verify 17:00 America/New_York daily session anchor is DST-aware."""
    # Summer (EDT, UTC-4): 17:00 EDT = 21:00 UTC
    dt_summer = datetime(2026, 7, 15, 21, 30, tzinfo=timezone.utc)
    session_start_summer = get_ny_session_start(dt_summer)
    assert session_start_summer == datetime(2026, 7, 15, 21, 0, tzinfo=timezone.utc)

    # Bar before 17:00 EDT (e.g. 15:00 EDT = 19:00 UTC) belongs to previous day session (starts 21:00 UTC July 14)
    dt_summer_early = datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc)
    assert get_ny_session_start(dt_summer_early) == datetime(2026, 7, 14, 21, 0, tzinfo=timezone.utc)

    # Winter (EST, UTC-5): 17:00 EST = 22:00 UTC
    dt_winter = datetime(2026, 1, 15, 22, 30, tzinfo=timezone.utc)
    session_start_winter = get_ny_session_start(dt_winter)
    assert session_start_winter == datetime(2026, 1, 15, 22, 0, tzinfo=timezone.utc)


def test_open_close_edge_1h_buckets():
    """Verify 1h buckets align cleanly with spot gold open/close hours (17:00 NY close, 18:00 NY open).
    
    Because market opens and closes on the hour (17:00 NY and 18:00 NY), all open 1h buckets
    contain exactly 4 bars (:00, :15, :30, :45). Zero bars occur during the closed break.
    """
    # Friday close in Summer (20:00-21:00 UTC): 4 open bars
    fri_close_start = datetime(2026, 7, 10, 20, 0, tzinfo=timezone.utc)
    bars_fri = [
        _make_15m_bar(fri_close_start + timedelta(minutes=15 * i))
        for i in range(4)
    ]
    res_fri = resample_ohlc(bars_fri, "1h", strict_completeness=True)
    assert len(res_fri) == 1
    assert res_fri[0].timestamp == fri_close_start

    # Sunday open in Summer (22:00-23:00 UTC): 4 open bars
    sun_open_start = datetime(2026, 7, 12, 22, 0, tzinfo=timezone.utc)
    bars_sun = [
        _make_15m_bar(sun_open_start + timedelta(minutes=15 * i))
        for i in range(4)
    ]
    res_sun = resample_ohlc(bars_sun, "1h", strict_completeness=True)
    assert len(res_sun) == 1
    assert res_sun[0].timestamp == sun_open_start


def test_open_close_edge_4h_calendar_aware():
    """Verify 4h bucket spanning Friday close with calendar_aware=True expects only open bars (4 bars)."""
    # 2026-07-10 is a Friday. Market closes at 21:00 UTC (17:00 EDT).
    # The 20:00 UTC 4h bucket only has open market from 20:00 to 21:00 (4 bars).
    fri_bucket_start = datetime(2026, 7, 10, 20, 0, tzinfo=timezone.utc)
    bars_4h_edge = [
        _make_15m_bar(fri_bucket_start + timedelta(minutes=15 * i))
        for i in range(4)
    ]
    # Without calendar awareness, strict 4h requires 16 bars and is omitted
    res_strict = resample_ohlc(bars_4h_edge, "4h", strict_completeness=True, calendar_aware=False)
    assert len(res_strict) == 0

    # With calendar awareness, 4 open bars match the expected open schedule for that bucket
    res_calendar = resample_ohlc(bars_4h_edge, "4h", strict_completeness=True, calendar_aware=True)
    assert len(res_calendar) == 1
    assert res_calendar[0].timestamp == fri_bucket_start

