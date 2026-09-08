"""Unit tests for SQLAlchemy models and Pydantic validation schemas."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from app.models.candle import Candle
from app.models.structure import StructureEvent
from app.models.liquidity import LiquidityEvent
from app.models.news import NewsEvent
from app.models.signal import Signal
from app.schemas.candle import CandleCreate


def test_candle_model_creation(test_db_session):
    """Test saving and querying a Candle in the database."""
    now = datetime.now(timezone.utc)
    candle = Candle(
        symbol="EUR/USD",
        timeframe="15m",
        timestamp=now,
        open=1.0850,
        high=1.0875,
        low=1.0840,
        close=1.0865,
        volume=1250.0,
    )
    test_db_session.add(candle)
    test_db_session.commit()

    saved = test_db_session.query(Candle).filter_by(symbol="EUR/USD").first()
    assert saved is not None
    assert saved.symbol == "EUR/USD"
    assert saved.timeframe == "15m"
    assert saved.open == 1.0850
    assert saved.high == 1.0875
    assert saved.low == 1.0840
    assert saved.close == 1.0865
    assert saved.volume == 1250.0
    assert saved.created_at is not None


def test_candle_unique_constraint(test_db_session):
    """Test that duplicate (symbol, timeframe, timestamp) cannot be inserted into the database."""
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    candle1 = Candle(
        symbol="EUR/USD",
        timeframe="15m",
        timestamp=now,
        open=1.0850,
        high=1.0870,
        low=1.0840,
        close=1.0860,
    )
    test_db_session.add(candle1)
    test_db_session.commit()

    candle2 = Candle(
        symbol="EUR/USD",
        timeframe="15m",
        timestamp=now,
        open=1.0855,
        high=1.0880,
        low=1.0850,
        close=1.0870,
    )
    test_db_session.add(candle2)
    with pytest.raises(IntegrityError):
        test_db_session.commit()
    test_db_session.rollback()


def test_candle_schema_validation_valid():
    """Test that valid OHLC values pass CandleCreate validation."""
    now = datetime.now(timezone.utc)
    valid_candle = CandleCreate(
        symbol="GBP/USD",
        timeframe="1h",
        timestamp=now,
        open=1.2800,
        high=1.2850,
        low=1.2780,
        close=1.2820,
        volume=500.0,
    )
    assert valid_candle.high >= valid_candle.open
    assert valid_candle.high >= valid_candle.close
    assert valid_candle.low <= valid_candle.open
    assert valid_candle.low <= valid_candle.close


def test_candle_schema_validation_invalid_high_low():
    """Test that high < low raises ValidationError."""
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        CandleCreate(
            symbol="GBP/USD",
            timeframe="1h",
            timestamp=now,
            open=1.2800,
            high=1.2750,  # Invalid: high is lower than low
            low=1.2780,
            close=1.2760,
        )


def test_candle_schema_validation_invalid_open_above_high():
    """Test that open > high raises ValidationError."""
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        CandleCreate(
            symbol="USD/JPY",
            timeframe="4h",
            timestamp=now,
            open=155.00,  # Invalid: open is higher than high
            high=154.50,
            low=153.00,
            close=154.00,
        )


def test_all_architecture_models_persistable(test_db_session):
    """Verify that structure, liquidity, news, and signal models instantiate without issue."""
    now = datetime.now(timezone.utc)
    struct = StructureEvent(
        symbol="EUR/USD",
        timeframe="15m",
        event_type="BULLISH_BOS",
        price=1.0890,
        timestamp=now,
    )
    liq = LiquidityEvent(
        symbol="EUR/USD",
        timeframe="15m",
        event_type="SELL_SIDE_SWEEP",
        price_level=1.0820,
        timestamp=now,
    )
    news = NewsEvent(
        currency="USD",
        event_name="Non-Farm Payrolls",
        impact="HIGH",
        scheduled_time=now,
    )
    sig = Signal(
        symbol="EUR/USD",
        timeframe="15m",
        direction="BUY",
        setup_score=85.0,
        entry_price=1.0850,
        stop_loss=1.0830,
        take_profit_1=1.0890,
        fingerprint="EURUSD_15m_BUY_test",
        reasons={"market_structure": "bullish_bos"},
        timestamp=now,
    )
    test_db_session.add_all([struct, liq, news, sig])
    test_db_session.commit()

    assert test_db_session.query(StructureEvent).count() == 1
    assert test_db_session.query(LiquidityEvent).count() == 1
    assert test_db_session.query(NewsEvent).count() == 1
    assert test_db_session.query(Signal).count() == 1
