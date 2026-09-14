"""Unit tests for Lower Timeframe (LTF) Confirmation Engine and Option B optimization."""

from datetime import datetime, timedelta, timezone
import logging
import pytest
from app.schemas.candle import CandleCreate
from app.schemas.structure import TrendDirection
from app.services.structure.ltf_confirmation import LTFConfirmationEngine


def _generate_candles_15m(count: int, start_time: datetime, base_price: float = 2000.0, trend: str = "bullish"):
    """Helper to generate sequential 15-minute candles."""
    candles = []
    current_price = base_price
    for i in range(count):
        t = start_time + timedelta(minutes=15 * i)
        if trend == "bullish":
            # Rising staircase with dips for swings
            o = current_price
            if i % 4 == 0:
                h = o + 3.0
                l = o - 2.0
                c = o - 1.0  # slight pullback
            else:
                h = o + 4.0
                l = o - 1.0
                c = o + 3.0  # upwards
            current_price = c
        elif trend == "bearish":
            o = current_price
            if i % 4 == 0:
                h = o + 2.0
                l = o - 3.0
                c = o + 1.0
            else:
                h = o + 1.0
                l = o - 4.0
                c = o - 3.0
            current_price = c
        else:
            o = current_price
            h = o + 1.0
            l = o - 1.0
            c = o + 0.1
            current_price = c

        candles.append(
            CandleCreate(
                symbol="EUR/USD",
                timeframe="15m",
                timestamp=t,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=100.0,
            )
        )
    return candles


def test_ltf_confirmation_excludes_is_closed_false(caplog):
    """Verify check_ltf_confirmation excludes candles with is_closed=False."""
    engine = LTFConfirmationEngine()
    base_time = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    candles = _generate_candles_15m(20, base_time)

    # Set last candle is_closed = False
    candles[-1] = candles[-1].model_copy(update={"is_closed": False})

    with caplog.at_level(logging.INFO):
        confirmed, reason = engine.check_ltf_confirmation(
            primary_timeframe="1h",
            primary_direction=TrendDirection.BULLISH,
            primary_candles=[],
            ltf_candles=candles,
            max_bars_ago=5,
        )

    # Exactly 19 closed candles out of 20
    assert "LTF Confirmation checked on 19 fully closed candles." in caplog.text


def test_ltf_confirmation_excludes_forming_relative_to_primary_close(caplog):
    """Verify candles opening at or after primary timeframe close are excluded."""
    engine = LTFConfirmationEngine()
    # 1H candle from 09:00 to 10:00 UTC (closes at 10:00 UTC)
    prim_ts = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    prim_candle = CandleCreate(
        symbol="EUR/USD",
        timeframe="1h",
        timestamp=prim_ts,
        open=1.1000,
        high=1.1050,
        low=1.0990,
        close=1.1040,
        volume=1000.0,
    )

    # 15m candles: 20 candles where 20th candle (index 19) starts at 10:00 UTC (1H close!)
    # start_15m = 10:00 - 19 * 15m
    prim_close = prim_ts + timedelta(hours=1)  # 10:00 UTC
    start_15m = prim_close - timedelta(minutes=15 * 19)
    candles_15m = _generate_candles_15m(20, start_15m)

    assert candles_15m[-1].timestamp == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    with caplog.at_level(logging.INFO):
        confirmed, reason = engine.check_ltf_confirmation(
            primary_timeframe="1h",
            primary_direction=TrendDirection.BULLISH,
            primary_candles=[prim_candle],
            ltf_candles=candles_15m,
            max_bars_ago=5,
        )

    # The 10:00 candle must be strictly excluded, leaving 19 fully closed candles
    assert "LTF Confirmation checked on 19 fully closed candles." in caplog.text



def test_ltf_confirmation_insufficient_data():
    """Verify returns insufficient data when closed candles < (max_bars_ago + 5)."""
    engine = LTFConfirmationEngine()
    base_time = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    candles = _generate_candles_15m(5, base_time)

    confirmed, reason = engine.check_ltf_confirmation(
        primary_timeframe="1h",
        primary_direction=TrendDirection.BULLISH,
        primary_candles=[],
        ltf_candles=candles,
        max_bars_ago=5,
    )
    assert not confirmed
    assert "Insufficient LTF data for confirmation" in reason


def test_ltf_confirmation_bullish_breakout():
    """Verify bullish structure breakout is confirmed on closed candles."""
    engine = LTFConfirmationEngine()
    base_time = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    # 15 candles total; last is open (14 closed, last 10 used in recent_ltf)
    # In recent_ltf (last 10 closed):
    # bar 0 (idx 4): 1.1000
    # bar 1 (idx 5): 1.1020
    # bar 2 (idx 6): 1.1040
    # bar 3 (idx 7): Swing High H=1.1120
    # bar 4 (idx 8): 1.1060
    # bar 5 (idx 9): 1.1030
    # bar 6 (idx 10): 1.1040
    # bar 7 (idx 11): 1.1070
    # bar 8 (idx 12): Breakout C=1.1150 > 1.1120
    # bar 9 (idx 13): 1.1160
    ohlc = [
        (1.0980, 1.0990, 1.0970, 1.0980),  # 0
        (1.0980, 1.0990, 1.0970, 1.0980),  # 1
        (1.0980, 1.0990, 1.0970, 1.0980),  # 2
        (1.0990, 1.1000, 1.0980, 1.0990),  # 3
        (1.1000, 1.1010, 1.0990, 1.1000),  # 4 (recent 0)
        (1.1000, 1.1030, 1.0990, 1.1020),  # 5 (recent 1)
        (1.1020, 1.1050, 1.1010, 1.1040),  # 6 (recent 2)
        (1.1040, 1.1120, 1.1030, 1.1100),  # 7 (recent 3 - Swing High H=1.1120)
        (1.1100, 1.1110, 1.1050, 1.1060),  # 8 (recent 4)
        (1.1060, 1.1070, 1.1020, 1.1030),  # 9 (recent 5)
        (1.1030, 1.1050, 1.1020, 1.1040),  # 10 (recent 6)
        (1.1040, 1.1080, 1.1030, 1.1070),  # 11 (recent 7)
        (1.1070, 1.1160, 1.1060, 1.1150),  # 12 (recent 8 - Breakout C=1.1150 > 1.1120)
        (1.1150, 1.1170, 1.1140, 1.1160),  # 13 (recent 9)
        (1.1160, 1.1200, 1.1150, 1.1180),  # 14 - open candle
    ]
    candles = [
        CandleCreate(
            symbol="EUR/USD",
            timeframe="15m",
            timestamp=base_time + timedelta(minutes=15 * i),
            open=o, high=h, low=l, close=c,
            volume=100.0,
            is_closed=(i < 14),
        )
        for i, (o, h, l, c) in enumerate(ohlc)
    ]

    confirmed, reason = engine.check_ltf_confirmation(
        primary_timeframe="1h",
        primary_direction=TrendDirection.BULLISH,
        primary_candles=[],
        ltf_candles=candles,
        max_bars_ago=5,
    )
    assert confirmed
    assert "LTF Bullish" in reason


def test_ltf_confirmation_bearish_breakout():
    """Verify bearish structure breakout is confirmed on closed candles."""
    engine = LTFConfirmationEngine()
    base_time = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    # In recent_ltf (last 10 closed):
    # bar 3 (idx 7): Swing Low L=1.0920
    # bar 8 (idx 12): Breakout C=1.0890 < 1.0920
    ohlc = [
        (1.1180, 1.1190, 1.1170, 1.1180),  # 0
        (1.1180, 1.1190, 1.1170, 1.1180),  # 1
        (1.1180, 1.1190, 1.1170, 1.1180),  # 2
        (1.1170, 1.1180, 1.1160, 1.1170),  # 3
        (1.1160, 1.1170, 1.1150, 1.1160),  # 4 (recent 0)
        (1.1160, 1.1170, 1.1130, 1.1140),  # 5 (recent 1)
        (1.1140, 1.1150, 1.1110, 1.1120),  # 6 (recent 2)
        (1.1120, 1.1130, 1.0920, 1.0950),  # 7 (recent 3 - Swing Low L=1.0920)
        (1.0950, 1.1000, 1.0940, 1.0980),  # 8 (recent 4)
        (1.0980, 1.1020, 1.0970, 1.1010),  # 9 (recent 5)
        (1.1010, 1.1030, 1.0990, 1.1000),  # 10 (recent 6)
        (1.1000, 1.1010, 1.0970, 1.0980),  # 11 (recent 7)
        (1.0980, 1.0990, 1.0880, 1.0890),  # 12 (recent 8 - Breakout C=1.0890 < 1.0920)
        (1.0890, 1.0910, 1.0870, 1.0880),  # 13 (recent 9)
        (1.0880, 1.0900, 1.0860, 1.0870),  # 14 - open candle
    ]
    candles = [
        CandleCreate(
            symbol="EUR/USD",
            timeframe="15m",
            timestamp=base_time + timedelta(minutes=15 * i),
            open=o, high=h, low=l, close=c,
            volume=100.0,
            is_closed=(i < 14),
        )
        for i, (o, h, l, c) in enumerate(ohlc)
    ]

    confirmed, reason = engine.check_ltf_confirmation(
        primary_timeframe="1h",
        primary_direction=TrendDirection.BEARISH,
        primary_candles=[],
        ltf_candles=candles,
        max_bars_ago=5,
    )
    assert confirmed
    assert "LTF Bearish" in reason


