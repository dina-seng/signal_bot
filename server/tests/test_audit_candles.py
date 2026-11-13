"""Unit tests for standalone candle diagnostic & cleanup script (audit_candles.py)."""

from datetime import datetime, timezone
import pytest
from sqlalchemy import text
from app.models.candle import Candle
from scripts.audit_candles import get_db_engine, run_audit, execute_cleanup


def test_audit_candles_detection_and_cleanup(test_db_session):
    """Verify that audit_candles correctly identifies misaligned and overlapping rows,
    and purges non-XAU/USD junk symbols and misaligned rows upon cleanup.
    """
    engine = test_db_session.bind

    # 1. Valid XAU/USD candles (aligned to 15m)
    c1 = Candle(
        symbol="XAU/USD",
        timeframe="15m",
        timestamp=datetime(2026, 8, 27, 13, 0, 0, tzinfo=timezone.utc),
        open=2500.0,
        high=2505.0,
        low=2495.0,
        close=2502.0,
        volume=100.0,
    )
    c2 = Candle(
        symbol="XAU/USD",
        timeframe="15m",
        timestamp=datetime(2026, 8, 27, 13, 15, 0, tzinfo=timezone.utc),
        open=2502.0,
        high=2507.0,
        low=2498.0,
        close=2504.0,
        volume=110.0,
    )

    # 2. Junk symbols
    c_junk1 = Candle(
        symbol="BTC/USD",
        timeframe="15m",
        timestamp=datetime(2026, 8, 27, 13, 0, 0, tzinfo=timezone.utc),
        open=60000.0,
        high=60100.0,
        low=59900.0,
        close=60050.0,
        volume=10.0,
    )
    c_junk2 = Candle(
        symbol="USD/JPY",
        timeframe="15m",
        timestamp=datetime(2026, 8, 27, 13, 0, 0, tzinfo=timezone.utc),
        open=150.0,
        high=151.0,
        low=149.0,
        close=150.5,
        volume=50.0,
    )
    c_junk3 = Candle(
        symbol="XAUUSD",
        timeframe="15m",
        timestamp=datetime(2026, 8, 27, 13, 0, 0, tzinfo=timezone.utc),
        open=2500.0,
        high=2505.0,
        low=2495.0,
        close=2502.0,
        volume=100.0,
    )

    # 3. Misaligned sub-second candle (second != 0, microsecond != 0)
    c_misaligned = Candle(
        symbol="XAU/USD",
        timeframe="15m",
        timestamp=datetime(2026, 8, 27, 13, 18, 23, 752051, tzinfo=timezone.utc),
        open=2503.0,
        high=2508.0,
        low=2499.0,
        close=2505.0,
        volume=20.0,
    )

    # 4. Overlapping bar (< 15m delta from c1: at 13:05)
    c_overlap = Candle(
        symbol="XAU/USD",
        timeframe="15m",
        timestamp=datetime(2026, 8, 27, 13, 5, 0, tzinfo=timezone.utc),
        open=2501.0,
        high=2506.0,
        low=2496.0,
        close=2503.0,
        volume=30.0,
    )

    test_db_session.add_all([c1, c2, c_junk1, c_junk2, c_junk3, c_misaligned, c_overlap])
    test_db_session.commit()

    # Run audit detection
    misaligned, overlapping = run_audit(engine)

    assert misaligned[("XAU/USD", "15m")] >= 1
    assert overlapping[("XAU/USD", "15m")] >= 1

    # Execute cleanup
    summary = execute_cleanup(engine)
    assert summary["junk_symbols_deleted"] == 3  # BTC/USD, USD/JPY, XAUUSD
    assert summary["misaligned_deleted"] >= 1     # sub-second / misaligned rows

    # Post-cleanup verification
    post_misaligned, _ = run_audit(engine)
    assert post_misaligned.get(("XAU/USD", "15m"), 0) == 0

    # Verify only XAU/USD remains
    remaining_symbols = test_db_session.scalars(
        text("SELECT DISTINCT symbol FROM candles")
    ).all()
    assert remaining_symbols == ["XAU/USD"]
