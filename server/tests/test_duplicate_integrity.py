"""Test Suite for Data Integrity, Deduplication, and Normalization."""

from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models.candle import Candle
from app.core.normalization import (
    normalize_symbol,
    normalize_timeframe,
    normalize_utc_datetime,
)
from app.models.news import NewsEvent
from app.models.paper import PaperTrade, VirtualAccount
from app.models.signal import Signal
from app.schemas.news import NewsEventCreate, NewsImpact
from app.schemas.paper_trading import AutoTradeSignalRequest
from app.schemas.signal import SignalDirection, SignalResponse, SignalStatus
from app.services.news.ingestion import NewsIngestionService
from app.services.news.mock_provider import MockNewsProvider
from app.services.paper_trading.order_executor import PaperOrderExecutor
from app.services.signals import SignalGenerator


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    init_db()


def test_symbol_and_timeframe_normalization():
    """Verify that canonical normalization maps all symbol & timeframe variants correctly."""
    assert normalize_symbol("eurusd") == "EUR/USD"
    assert normalize_symbol("EUR_USD") == "EUR/USD"
    assert normalize_symbol("EUR/USD") == "EUR/USD"
    assert normalize_symbol("EURUSD=X") == "EUR/USD"
    assert normalize_symbol("gbpusd") == "GBP/USD"
    assert normalize_symbol("USDJPY") == "USD/JPY"
    assert normalize_symbol("JPY=X") == "USD/JPY"
    assert normalize_symbol("GC=F") == "XAU/USD"
    assert normalize_symbol("XAUUSD") == "XAU/USD"
    assert normalize_symbol("xau_usd") == "XAU/USD"

    assert normalize_timeframe("1H") == "1h"
    assert normalize_timeframe("15M") == "15m"
    assert normalize_timeframe("4H") == "4h"
    assert normalize_timeframe("D1") == "1d"


def test_news_event_atomic_deduplication_and_upsert(test_db_session):
    """Verify that repeated news ingestion updates existing records without duplicate rows."""
    provider = MockNewsProvider()
    service = NewsIngestionService(provider=provider, db=test_db_session)

    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    event1 = NewsEventCreate(
        currency="USD",
        event_name="Federal Reserve Rate Decision",
        impact=NewsImpact.HIGH,
        scheduled_time=now,
        previous="5.25%",
        forecast="5.50%",
        actual=None,
    )

    # 1. Ingest initial event
    rep1 = service.ingest_events([event1])
    assert rep1.inserted_count == 1
    assert rep1.skipped_count == 0

    # 2. Ingest duplicate event with updated actual release data
    event1_updated = NewsEventCreate(
        currency="USD",
        event_name="Federal Reserve Rate Decision",
        impact=NewsImpact.HIGH,
        scheduled_time=now,
        previous="5.25%",
        forecast="5.50%",
        actual="5.50%",
    )

    rep2 = service.ingest_events([event1_updated])
    assert rep2.inserted_count == 0  # No new row inserted
    assert rep2.skipped_count == 0   # It was updated

    # 3. Assert DB contains exactly 1 record with actual="5.50%"
    stmt = select(NewsEvent).where(
        NewsEvent.currency == "USD",
        NewsEvent.event_name == "Federal Reserve Rate Decision",
        NewsEvent.scheduled_time == now,
    )
    records = list(test_db_session.scalars(stmt).all())
    assert len(records) == 1
    assert records[0].actual == "5.50%"


def test_paper_trade_idempotency_from_signal(test_db_session):
    """Verify that open_trade_from_signal is idempotent and prevents duplicate paper trades."""
    executor = PaperOrderExecutor()
    now = datetime.now(timezone.utc)

    # Seed closed 1h candles: execution derives the SL from the signal timeframe.
    for i in range(7):
        test_db_session.add(Candle(
            symbol="EUR/USD", timeframe="1h",
            timestamp=now - timedelta(hours=7 - i),
            open=1.1040, high=1.1060, low=1.1020, close=1.1050, volume=100.0,
        ))
    test_db_session.commit()

    # Create a test signal
    sig = Signal(
        symbol="EUR/USD",
        timeframe="1h",
        direction="BUY",
        setup_score=80.0,
        entry_price=1.1050,
        stop_loss=1.0950,
        take_profit_1=1.1150,
        take_profit_2=1.1200,
        risk_reward=2.0,
        fingerprint=f"test_fp_idempotency_{int(now.timestamp())}",
        reasons=["Test reason"],
        status="ACTIVE",
        timestamp=now,
    )
    test_db_session.add(sig)
    test_db_session.commit()
    test_db_session.refresh(sig)

    # First execution: Should create paper trade
    trade1 = executor.open_trade_from_signal(
        db=test_db_session,
        request=AutoTradeSignalRequest(signal_id=sig.id, symbol="EUR/USD", risk_percent=0.5),
    )
    assert trade1 is not None
    assert trade1.signal_id == sig.id
    trade1_id = trade1.id

    # Second execution: Should return existing trade idempotently
    trade2 = executor.open_trade_from_signal(
        db=test_db_session,
        request=AutoTradeSignalRequest(signal_id=sig.id, symbol="EUR/USD", risk_percent=0.5),
    )
    assert trade2.id == trade1_id

    # Assert only 1 paper trade exists for this signal
    stmt = select(PaperTrade).where(PaperTrade.signal_id == sig.id)
    all_trades = list(test_db_session.scalars(stmt).all())
    assert len(all_trades) == 1


def test_signal_generator_persistence_collision_safety(test_db_session):
    """Verify that re-persisting the same signal fingerprint returns the existing row."""
    generator = SignalGenerator()
    now = datetime.now(timezone.utc)
    fp = f"test_fp_collision_{int(now.timestamp())}"

    sig_resp = SignalResponse(
        symbol="GBP/USD",
        timeframe="1h",
        direction=SignalDirection.BUY,
        setup_score=82.0,
        entry_price=1.2850,
        stop_loss=1.2800,
        take_profit_1=1.2950,
        take_profit_2=1.3000,
        risk_reward=2.0,
        fingerprint=fp,
        reasons=["Confluence setup"],
        status=SignalStatus.ACTIVE,
        timestamp=now,
    )

    db_sig1 = generator.persist_signal_if_qualified(test_db_session, sig_resp)
    assert db_sig1 is not None
    assert db_sig1.fingerprint == fp

    # Second persistence call
    db_sig2 = generator.persist_signal_if_qualified(test_db_session, sig_resp)
    assert db_sig2.id == db_sig1.id

    # Count rows in DB
    stmt = select(Signal).where(Signal.fingerprint == fp)
    assert len(list(test_db_session.scalars(stmt).all())) == 1
