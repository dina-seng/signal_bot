"""Data-integrity regression tests for the canonical 15m loader.

Covers the approved contract §7: OHLC validity, monotonic time, conflicting
duplicates, forming bars, source/calendar filters, and session tagging.
Hermetic: temporary SQLite files only, removed by pytest's tmp_path fixture.
"""

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from replay_harness import TF_15M, assign_session_ids, load_full_15m_candles

NY = ZoneInfo("America/New_York")


def _make_db(tmp_path, rows, table="candles"):
    path = tmp_path / "bars.db"
    conn = sqlite3.connect(path)
    conn.execute(
        f"""CREATE TABLE {table} (
            symbol TEXT, timeframe TEXT, timestamp TEXT,
            open REAL, high REAL, low REAL, close REAL,
            volume REAL, source TEXT
        )"""
    )
    conn.executemany(
        f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()
    return path


def _row(ts, o=2000.0, h=2000.2, l=1999.8, c=2000.0, source="twelvedata", tf="15m"):
    return ("XAU/USD", tf, ts, o, h, l, c, 100.0, source)


def test_valid_series_loads_and_counts(tmp_path):
    path = _make_db(tmp_path, [
        _row("2026-01-05 10:00:00"),
        _row("2026-01-05 10:15:00"),
    ])
    bars, meta = load_full_15m_candles(path, "XAU/USD", "twelvedata")
    assert len(bars) == 2
    assert meta["raw_rows"] == 2
    assert meta["open_market_bars"] == 2


def test_invalid_ohlc_rejected(tmp_path):
    path = _make_db(tmp_path, [
        _row("2026-01-05 10:00:00", h=1999.0, l=2001.0),  # high < low
    ])
    with pytest.raises(SystemExit, match="invalid OHLC"):
        load_full_15m_candles(path, "XAU/USD", "twelvedata")


def test_mixed_timestamp_formats_load_in_chronological_order(tmp_path):
    # SQL string ordering puts the space-format row first; the loader must
    # order by the parsed UTC instant instead (real DB mixes these spellings).
    path = _make_db(tmp_path, [
        _row("2026-01-05 10:00:00", c=2010.0, h=2010.2, l=2009.8, o=2010.0),
        _row("2026-01-05T09:00:00+00:00"),
    ])
    bars, _ = load_full_15m_candles(path, "XAU/USD", "twelvedata")
    assert [b.timestamp for b in bars] == [
        datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc),
    ]
    assert bars[0].close == 2000.0
    assert bars[1].close == 2010.0


def test_conflicting_duplicate_rejected(tmp_path):
    path = _make_db(tmp_path, [
        _row("2026-01-05 10:00:00", o=2000.0, h=2000.2, l=1999.8, c=2000.0),
        _row("2026-01-05 10:00:00", o=2010.0, h=2010.2, l=2009.8, c=2010.0),
    ])
    with pytest.raises(SystemExit, match="conflicting duplicate"):
        load_full_15m_candles(path, "XAU/USD", "twelvedata")


def test_identical_duplicate_collapsed(tmp_path):
    path = _make_db(tmp_path, [
        _row("2026-01-05 10:00:00"),
        _row("2026-01-05 10:00:00"),
    ])
    bars, meta = load_full_15m_candles(path, "XAU/USD", "twelvedata")
    assert len(bars) == 1
    assert meta["duplicates_dropped"] == 1


def test_forming_bar_excluded_when_as_of_given(tmp_path):
    path = _make_db(tmp_path, [
        _row("2026-01-05 10:00:00"),
        _row("2026-01-05 10:15:00"),
    ])
    as_of = datetime(2026, 1, 5, 10, 15, tzinfo=timezone.utc)
    bars, _ = load_full_15m_candles(path, "XAU/USD", "twelvedata", as_of=as_of)
    assert [b.timestamp for b in bars] == [datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)]


def test_source_and_calendar_filters_preserved(tmp_path):
    path = _make_db(tmp_path, [
        _row("2026-01-05 10:00:00"),                       # Monday open - keep
        _row("2026-01-03 12:00:00"),                       # Saturday - drop
        _row("2026-01-05 10:15:00", source="yfinance"),   # wrong source - drop
    ])
    bars, meta = load_full_15m_candles(path, "XAU/USD", "twelvedata")
    assert len(bars) == 1
    assert meta["closed_market_dropped"] == 1
    assert meta["raw_rows"] == 2  # source filter applies in SQL before loading


def _b(ts):
    from app.schemas.candle import CandleCreate
    return CandleCreate(
        symbol="XAU/USD", timeframe="15m", timestamp=ts,
        open=2000.0, high=2000.2, low=1999.8, close=2000.0,
        volume=1.0, source="twelvedata",
    )


def test_session_ids_increment_at_session_opens():
    fri = datetime(2026, 1, 2, 16, 45, tzinfo=NY).astimezone(timezone.utc)
    mon = datetime(2026, 1, 5, 18, 0, tzinfo=NY).astimezone(timezone.utc)
    ids = assign_session_ids([_b(fri), _b(fri + TF_15M), _b(mon), _b(mon + TF_15M)])
    assert ids == [0, 0, 1, 1]


def test_session_ids_flat_within_session():
    mon = datetime(2026, 1, 5, 10, 0, tzinfo=NY).astimezone(timezone.utc)
    ids = assign_session_ids([_b(mon), _b(mon + TF_15M), _b(mon + 2 * TF_15M)])
    assert ids == [0, 0, 0]
