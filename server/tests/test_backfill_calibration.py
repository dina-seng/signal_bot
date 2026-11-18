"""Tests for historical data backfill script (backfill_calibration.py)."""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))
SCRIPTS_ROOT = SERVER_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from backfill_calibration import (
    resolve_timeframe,
    init_db,
    save_candles_to_db,
    fetch_twelve_data_page,
    backfill_timeframe,
    run_backfill,
)


def test_resolve_timeframe():
    assert resolve_timeframe("15min") == ("15m", "15min")
    assert resolve_timeframe("15m") == ("15m", "15min")
    assert resolve_timeframe("1h") == ("1h", "1h")
    assert resolve_timeframe("60m") == ("1h", "1h")
    assert resolve_timeframe("4h") == ("4h", "4h")
    assert resolve_timeframe("1d") == ("1d", "1day")
    assert resolve_timeframe("unknown") == ("unknown", "unknown")


def test_init_db(tmp_path):
    db_file = tmp_path / "test_backtest.db"
    conn = init_db(db_file)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='candles'")
    assert cur.fetchone() is not None
    conn.close()


def test_save_candles_to_db_idempotency(tmp_path):
    db_file = tmp_path / "test_candles.db"
    conn = init_db(db_file)

    candles = [
        {"datetime": "2025-01-01 00:00:00", "open": "2600.0", "high": "2605.0", "low": "2595.0", "close": "2602.0", "volume": "100"},
        {"datetime": "2025-01-01 00:15:00", "open": "2602.0", "high": "2610.0", "low": "2600.0", "close": "2608.0", "volume": "150"},
    ]

    # First insert: 2 inserted, 0 skipped
    inserted, skipped = save_candles_to_db(conn, candles, "XAU/USD", "15m")
    assert inserted == 2
    assert skipped == 0

    # Second insert with identical data: 0 inserted, 2 skipped
    inserted2, skipped2 = save_candles_to_db(conn, candles, "XAU/USD", "15m")
    assert inserted2 == 0
    assert skipped2 == 2

    # Query DB to ensure no duplicates
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM candles WHERE symbol='XAU/USD' AND timeframe='15m'")
    assert cur.fetchone()[0] == 2
    conn.close()


def test_save_candles_rejects_invalid_ohlc(tmp_path):
    db_file = tmp_path / "test_invariants.db"
    conn = init_db(db_file)

    candles = [
        # Valid
        {"datetime": "2025-01-01 00:00:00", "open": "2600.0", "high": "2605.0", "low": "2595.0", "close": "2602.0", "volume": "100"},
        # High < Low
        {"datetime": "2025-01-01 00:15:00", "open": "2600.0", "high": "2590.0", "low": "2605.0", "close": "2600.0", "volume": "100"},
        # Price <= 0
        {"datetime": "2025-01-01 00:30:00", "open": "-10.0", "high": "2605.0", "low": "2595.0", "close": "2600.0", "volume": "100"},
        # Corrupted / Missing
        {"datetime": "2025-01-01 00:45:00", "open": "invalid", "high": "2605.0", "low": "2595.0", "close": "2600.0"},
    ]

    inserted, skipped = save_candles_to_db(conn, candles, "XAU/USD", "15m")
    assert inserted == 1

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM candles")
    assert cur.fetchone()[0] == 1
    conn.close()


@patch("requests.get")
@patch("time.sleep")
def test_fetch_twelve_data_page_retry_429(mock_sleep, mock_get):
    resp_429 = MagicMock()
    resp_429.status_code = 429

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {
        "status": "ok",
        "values": [{"datetime": "2025-01-01 00:00:00", "open": "2600", "high": "2605", "low": "2595", "close": "2602", "volume": "10"}],
    }

    mock_get.side_effect = [resp_429, resp_200]

    values = fetch_twelve_data_page(
        symbol="XAU/USD",
        interval="15min",
        api_key="mock_key",
        start_date="2025-01-01",
        end_date="2025-01-02",
        sleep_between_calls=0.0,
    )
    assert len(values) == 1
    assert mock_get.call_count == 2
    mock_sleep.assert_any_call(60.0)


@patch("backfill_calibration.fetch_twelve_data_page")
def test_backfill_timeframe_pagination(mock_fetch, tmp_path):
    db_file = tmp_path / "test_pagination.db"
    conn = init_db(db_file)

    page1 = [
        {"datetime": "2025-03-01 00:00:00", "open": "2600", "high": "2605", "low": "2595", "close": "2602", "volume": "10"},
        {"datetime": "2025-05-21 23:45:00", "open": "2610", "high": "2615", "low": "2605", "close": "2612", "volume": "10"},
    ]
    # Page 1 length 5000 simulation
    page1_large = page1 * 2500

    page2 = [
        {"datetime": "2025-01-01 00:00:00", "open": "2550", "high": "2555", "low": "2545", "close": "2552", "volume": "10"},
        {"datetime": "2025-03-01 00:00:00", "open": "2600", "high": "2605", "low": "2595", "close": "2602", "volume": "10"},
    ]

    mock_fetch.side_effect = [page1_large, page2]

    res = backfill_timeframe(
        conn=conn,
        symbol="XAU/USD",
        tf_input="15min",
        start_date="2025-01-01",
        end_date="2025-05-21",
        api_key="test_key",
        db_name="test_pagination.db",
        sleep_between_calls=0.0,
    )

    assert res["timeframe"] == "15m"
    assert res["fetched"] == len(page1_large) + len(page2)
    # The distinct timestamps are 3
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM candles WHERE symbol='XAU/USD' AND timeframe='15m'")
    assert cur.fetchone()[0] == 3
    conn.close()


@patch("backfill_calibration.fetch_twelve_data_page")
def test_run_backfill_end_to_end(mock_fetch, tmp_path, capsys):
    db_file = tmp_path / "e2e_backtest.db"

    mock_fetch.side_effect = [
        # 15m batch
        [{"datetime": "2025-01-01 00:00:00", "open": "2600", "high": "2605", "low": "2595", "close": "2602", "volume": "10"}],
        # 1h batch
        [{"datetime": "2025-01-01 00:00:00", "open": "2600", "high": "2605", "low": "2595", "close": "2602", "volume": "40"}],
    ]

    res = run_backfill(
        symbol="XAU/USD",
        timeframes=["15min", "1h"],
        start_date="2025-01-01",
        end_date="2025-05-21",
        db_path=db_file,
        api_key="test_api_key",
        sleep_sec=0.0,
    )

    captured = capsys.readouterr().out
    assert "Fetching 15m data..." in captured
    assert "Fetched 1 bars" in captured
    assert "Saving to e2e_backtest.db" in captured
    assert "Fetching 1h data..." in captured
    assert "Total bars saved: 2" in captured

    assert res["total_fetched"] == 2
    assert res["total_inserted"] == 2
    assert res["total_bars_in_db"] == 2
