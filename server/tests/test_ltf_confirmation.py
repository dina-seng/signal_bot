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


# =============================================================================
# Bug Fix Tests: Stale Signal & Live Price Invalidation Gate
# (Task 1 — PaperOrderExecutor.validate_signal_before_execution)
# =============================================================================

from datetime import timedelta
from unittest.mock import MagicMock
import pytest

from app.services.paper_trading.order_executor import PaperOrderExecutor


def _make_mock_signal(
    signal_id: int = 1,
    symbol: str = "XAU/USD",
    timeframe: str = "15m",
    direction: str = "SELL",
    stop_loss: float = 1960.00,
    take_profit_1: float = 1930.00,
    entry_price: float = 1950.00,
    age_minutes: float = 0.0,
) -> MagicMock:
    """Build a mock Signal DB object with a configurable wall-clock (created_at) age."""
    signal_ts = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    sig = MagicMock()
    sig.id = signal_id
    sig.symbol = symbol
    sig.timeframe = timeframe
    sig.direction = direction
    sig.stop_loss = stop_loss
    sig.take_profit_1 = take_profit_1
    sig.entry_price = entry_price
    sig.status = "ACTIVE"
    sig.created_at = signal_ts
    sig.timestamp = signal_ts
    return sig


def test_stale_sell_signal_rejected_before_order():
    """Mandatory regression test: a 20-minute-old 15m SELL signal with live price
    above the SL must be rejected by validate_signal_before_execution() with a
    descriptive ValueError BEFORE any paper order or DB write occurs.

    This directly reproduces the failure mode causing 0-second SL_HIT stop-outs:
      - Scanner generates a 15m SELL at T=0 (entry=1950, SL=1960, TP=1930)
      - Market rallies; at T+20min live price = 1965 (already above SL=1960)
      - Old code: execute_order() is called with stale entry=1950, trade opens,
        position_manager sees price 1965 > SL 1960, SL_HIT fires instantly.
      - Fixed code: validate_signal_before_execution() detects:
          (a) signal is 20 min old > 15 min timeframe window → raises ValueError
    """
    executor = PaperOrderExecutor()
    mock_db = MagicMock()

    # Signal is 20 minutes old (one full 15m bar beyond staleness threshold)
    stale_signal = _make_mock_signal(
        timeframe="15m",
        direction="SELL",
        stop_loss=1960.00,
        take_profit_1=1930.00,
        entry_price=1950.00,
        age_minutes=20.0,   # 20 min > 15 min threshold → stale
    )

    # Live price has already rallied above the SL (would guarantee instant SL_HIT)
    live_price_above_sl = 1965.00  # above SL=1960

    with pytest.raises(ValueError) as exc_info:
        executor.validate_signal_before_execution(
            db=mock_db,
            signal=stale_signal,
            current_price=live_price_above_sl,
        )

    error_msg = str(exc_info.value)
    # Must fail on the STALENESS gate (gate 1 fires first, before price gate 2)
    assert "STALE SIGNAL REJECTED" in error_msg, (
        f"Expected staleness rejection message, got: {error_msg}"
    )
    assert "15m" in error_msg, "Error must identify the signal timeframe"

    # No DB interactions should occur — order must not be placed
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()


def test_live_price_above_sl_sell_rejected_independently():
    """Verify the LIVE PRICE invalidation gate (Gate 2) independently blocks a SELL
    order when the current price has already moved above the Stop Loss, even when
    the signal timestamp is fresh (within the 15m window).

    This guards against the scenario where the scheduler fires within the bar window
    but price has still spiked past the SL within those first few minutes.
    """
    executor = PaperOrderExecutor()
    mock_db = MagicMock()

    # Signal is only 3 minutes old — NOT stale for a 15m bar
    fresh_signal = _make_mock_signal(
        timeframe="15m",
        direction="SELL",
        stop_loss=1960.00,
        take_profit_1=1930.00,
        entry_price=1950.00,
        age_minutes=3.0,    # 3 min < 15 min → within staleness window
    )

    # But live price is ABOVE the SL — a guaranteed instant loss
    live_price_above_sl = 1962.00   # >= SL=1960

    with pytest.raises(ValueError) as exc_info:
        executor.validate_signal_before_execution(
            db=mock_db,
            signal=fresh_signal,
            current_price=live_price_above_sl,
        )

    error_msg = str(exc_info.value)
    assert "LIVE PRICE INVALIDATION" in error_msg, (
        f"Expected price invalidation message, got: {error_msg}"
    )
    assert "SL_HIT" in error_msg, "Error must mention instant SL_HIT risk"

    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()


def test_candle_timestamp_drift_does_not_reject_freshly_created_signal():
    """Regression for production 400 on POST /paper/orders/from-signal:
    the scanner stamps Signal.timestamp with the last CLOSED BAR's open time,
    so a 1h signal persisted at 03:45 carries timestamp=02:00 (110 min "old").
    Staleness must be measured against created_at (wall-clock persist time),
    otherwise every manually executed signal is rejected as STALE.
    """
    executor = PaperOrderExecutor()
    mock_db = MagicMock()

    fresh_created_signal = _make_mock_signal(
        timeframe="1h",
        direction="SELL",
        stop_loss=1960.00,
        take_profit_1=1930.00,
        entry_price=1950.00,
        age_minutes=5.0,    # persisted by scanner 5 minutes ago
    )
    # Candle timestamp is far beyond one 1h bar (the production case: 110.5 min)
    fresh_created_signal.timestamp = datetime.now(timezone.utc) - timedelta(minutes=110)

    # Live price still inside the SL/TP corridor → must not raise
    executor.validate_signal_before_execution(
        db=mock_db,
        signal=fresh_created_signal,
        current_price=1951.00,
    )

    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()


def test_valid_fresh_sell_signal_passes_validation():
    """Verify that a fresh, price-valid SELL signal passes both gates without error."""
    executor = PaperOrderExecutor()
    mock_db = MagicMock()

    # 2-minute-old 15m SELL, live price well within SL/TP corridor
    fresh_valid_signal = _make_mock_signal(
        timeframe="15m",
        direction="SELL",
        stop_loss=1960.00,
        take_profit_1=1930.00,
        entry_price=1950.00,
        age_minutes=2.0,    # fresh
    )
    # Price strictly inside the corridor: below SL (1960), above TP (1930)
    live_price_in_range = 1951.00

    # Should not raise
    executor.validate_signal_before_execution(
        db=mock_db,
        signal=fresh_valid_signal,
        current_price=live_price_in_range,
    )
    # Test passes if no exception is raised
