"""Unit tests for Historical Data Import and Resample Tooling."""

import os
from datetime import datetime, timezone
import pytest

from app.scripts.import_history import (
    align_timestamp,
    parse_timestamp,
    parse_and_validate_csv,
    resample_bars,
    audit_series_cleanliness,
    import_dukascopy_to_sqlite,
)


def test_align_timestamp_utc():
    """Verify UTC boundary alignment for 15m, 30m, 1h, 4h, 1d."""
    dt = datetime(2026, 8, 1, 14, 27, 45, tzinfo=timezone.utc)

    # 15m -> 14:15:00
    a15 = align_timestamp(dt, "15m")
    assert a15.minute == 15
    assert a15.second == 0

    # 30m -> 14:00:00
    a30 = align_timestamp(dt, "30m")
    assert a30.minute == 0
    assert a30.second == 0

    # 1h -> 14:00:00
    a1h = align_timestamp(dt, "1h")
    assert a1h.hour == 14
    assert a1h.minute == 0

    # 4h -> 12:00:00 (14 - 14%4 = 12)
    a4h = align_timestamp(dt, "4h")
    assert a4h.hour == 12
    assert a4h.minute == 0

    # 1d -> 00:00:00
    a1d = align_timestamp(dt, "1d")
    assert a1d.hour == 0
    assert a1d.minute == 0


def test_csv_parser_rejects_corrupted_rows(tmp_path):
    """Verify parsing rejects corrupted rows where high < low or prices <= 0."""
    csv_file = tmp_path / "test_dukascopy.csv"
    content = (
        "Gmt time,Open,High,Low,Close,Volume\n"
        "01.08.2026 00:00:00.000,2500.0,2505.0,2495.0,2502.0,10.0\n"  # Valid
        "01.08.2026 00:01:00.000,2502.0,2490.0,2505.0,2495.0,10.0\n"  # Invariant broken: High < Low!
        "01.08.2026 00:02:00.000,2502.0,2504.0,2501.0,-10.0,10.0\n"   # Invalid price <= 0!
        "01.08.2026 00:03:00.000,2502.0,2506.0,2500.0,2504.0,15.0\n"  # Valid
    )
    csv_file.write_text(content, encoding="utf-8")

    clean, rejected = parse_and_validate_csv(str(csv_file))
    assert len(clean) == 2
    assert rejected == 2
    assert clean[0]["open"] == 2500.0
    assert clean[1]["open"] == 2502.0


def test_resample_1m_to_15m():
    """Verify 1m candles correctly resample into 15m OHLCV bars."""
    bars_1m = []
    base_t = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    for m in range(15):
        bars_1m.append({
            "timestamp": base_t.replace(minute=m),
            "open": 2500.0 + m,
            "high": 2505.0 + m,
            "low": 2495.0 + m,
            "close": 2501.0 + m,
            "volume": 10.0,
        })

    res_15m = resample_bars(bars_1m, "15m")
    assert len(res_15m) == 1
    b15 = res_15m[0]
    assert b15["timestamp"] == base_t
    assert b15["open"] == 2500.0  # first bar open
    assert b15["high"] == 2519.0  # max of 2505 + 14
    assert b15["low"] == 2495.0   # min of 2495 + 0
    assert b15["close"] == 2515.0 # last bar close (2501 + 14)
    assert b15["volume"] == 150.0 # sum of volumes (10 * 15)


def test_import_refuses_neon_production_db(tmp_path):
    """Verify import history strictly refuses to target production/Neon database URLs."""
    csv_file = tmp_path / "dummy.csv"
    csv_file.write_text("Time,Open,High,Low,Close,Volume\n", encoding="utf-8")

    with pytest.raises(PermissionError, match="REFUSED TO WRITE TO PRODUCTION DATABASE"):
        import_dukascopy_to_sqlite(
            csv_path=str(csv_file),
            db_path="postgresql://user:pass@ep-cool-neon.tech/neondb",
        )


def test_end_to_end_import_dukascopy(tmp_path):
    """End-to-end import into isolated temporary SQLite database."""
    csv_file = tmp_path / "xau_1m.csv"
    db_file = tmp_path / "test_backtest.db"

    # Create 30 1m bars spanning across two 15m intervals
    lines = ["Gmt time,Open,High,Low,Close,Volume"]
    for m in range(30):
        t_str = f"01.08.2026 10:{m:02d}:00.000"
        lines.append(f"{t_str},2500.0,2505.0,2495.0,2502.0,5.0")
    csv_file.write_text("\n".join(lines), encoding="utf-8")

    res = import_dukascopy_to_sqlite(
        csv_path=str(csv_file),
        db_path=str(db_file),
        source_tag="dukascopy_test",
        symbol="XAU/USD",
    )

    assert res["clean_1m_bars"] == 30
    assert res["rejected_rows"] == 0
    assert res["total_inserted"] > 0
    assert os.path.exists(str(db_file))

    # Check 15m cleanliness audit
    audit_15m = res["audit_reports"]["15m"]
    assert audit_15m["total_bars"] == 2
    assert audit_15m["misaligned"] == 0
    assert audit_15m["overlaps"] == 0


def test_import_directory_without_csv_files_raises(tmp_path):
    """Verify specifying a directory with no CSV files raises actionable ValueError."""
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()

    with pytest.raises(ValueError, match="is a directory containing no .csv files"):
        parse_and_validate_csv(str(empty_dir))


def test_import_directory_with_multiple_csv_files(tmp_path):
    """Verify specifying a directory with multiple CSV files parses and combines all bars."""
    csv_dir = tmp_path / "csv_chunks"
    csv_dir.mkdir()

    csv1 = csv_dir / "part1.csv"
    csv1.write_text(
        "Gmt time,Open,High,Low,Close,Volume\n"
        "01.08.2026 10:00:00.000,2500.0,2505.0,2495.0,2502.0,10.0\n"
        "01.08.2026 10:01:00.000,2502.0,2506.0,2501.0,2504.0,10.0\n",
        encoding="utf-8",
    )

    csv2 = csv_dir / "part2.csv"
    csv2.write_text(
        "Gmt time,Open,High,Low,Close,Volume\n"
        "01.08.2026 10:02:00.000,2504.0,2507.0,2502.0,2505.0,10.0\n",
        encoding="utf-8",
    )

    clean_bars, rejected = parse_and_validate_csv(str(csv_dir))
    assert len(clean_bars) == 3
    assert rejected == 0
    assert clean_bars[0]["timestamp"].minute == 0
    assert clean_bars[1]["timestamp"].minute == 1
    assert clean_bars[2]["timestamp"].minute == 2
