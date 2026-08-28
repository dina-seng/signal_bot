"""Unit tests for the Market Data Ingestion Pipeline."""

from datetime import datetime, timedelta, timezone
import pytest
from app.models.candle import Candle
from app.schemas.candle import CandleCreate


def test_clean_and_sort_out_of_order(ingestion_service):
    """Test that out-of-order candles are sorted chronologically."""
    t1 = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 28, 10, 15, tzinfo=timezone.utc)
    t3 = datetime(2026, 8, 28, 10, 30, tzinfo=timezone.utc)

    # Pass in scrambled order: t3, t1, t2
    raw = [
        CandleCreate(symbol="EUR/USD", timeframe="15m", timestamp=t3, open=1.082, high=1.085, low=1.080, close=1.084),
        CandleCreate(symbol="EUR/USD", timeframe="15m", timestamp=t1, open=1.080, high=1.083, low=1.079, close=1.081),
        CandleCreate(symbol="EUR/USD", timeframe="15m", timestamp=t2, open=1.081, high=1.084, low=1.080, close=1.082),
    ]

    cleaned, intra_dups = ingestion_service.clean_and_sort_candles(raw)
    assert intra_dups == 0
    assert len(cleaned) == 3
    assert cleaned[0].timestamp == t1
    assert cleaned[1].timestamp == t2
    assert cleaned[2].timestamp == t3


def test_clean_and_sort_intra_batch_duplicates(ingestion_service):
    """Test that duplicate timestamps within a single batch are deduplicated."""
    t1 = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 28, 10, 15, tzinfo=timezone.utc)

    raw = [
        CandleCreate(symbol="EUR/USD", timeframe="15m", timestamp=t1, open=1.080, high=1.083, low=1.079, close=1.081),
        CandleCreate(symbol="EUR/USD", timeframe="15m", timestamp=t1, open=1.080, high=1.083, low=1.079, close=1.081), # duplicate
        CandleCreate(symbol="EUR/USD", timeframe="15m", timestamp=t2, open=1.081, high=1.084, low=1.080, close=1.082),
    ]

    cleaned, intra_dups = ingestion_service.clean_and_sort_candles(raw)
    assert intra_dups == 1
    assert len(cleaned) == 2
    assert cleaned[0].timestamp == t1
    assert cleaned[1].timestamp == t2


def test_detect_gaps_missing_candles(ingestion_service):
    """Test detection of missing candles in intraday data."""
    t1 = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)
    # Skip 10:15 and 10:30, jump straight to 10:45
    t2 = datetime(2026, 8, 28, 10, 45, tzinfo=timezone.utc)

    candles = [
        CandleCreate(symbol="EUR/USD", timeframe="15m", timestamp=t1, open=1.080, high=1.083, low=1.079, close=1.081),
        CandleCreate(symbol="EUR/USD", timeframe="15m", timestamp=t2, open=1.084, high=1.086, low=1.082, close=1.085),
    ]

    gaps = ingestion_service.detect_gaps(candles, "EUR/USD", "15m")
    assert len(gaps) == 1
    assert gaps[0].missing_candles_estimated == 2
    assert gaps[0].gap_start == t1
    assert gaps[0].gap_end == t2


def test_detect_gaps_weekend_ignored(ingestion_service):
    """Test that standard weekend gap (Friday evening to Sunday evening) is not flagged as an error gap."""
    # Friday 21:00 UTC
    fri_close = datetime(2026, 8, 21, 21, 0, tzinfo=timezone.utc)
    # Sunday 21:00 UTC
    sun_open = datetime(2026, 8, 23, 21, 0, tzinfo=timezone.utc)

    candles = [
        CandleCreate(symbol="EUR/USD", timeframe="1h", timestamp=fri_close, open=1.080, high=1.083, low=1.079, close=1.081),
        CandleCreate(symbol="EUR/USD", timeframe="1h", timestamp=sun_open, open=1.081, high=1.084, low=1.080, close=1.082),
    ]

    gaps = ingestion_service.detect_gaps(candles, "EUR/USD", "1h")
    assert len(gaps) == 0


def test_ingest_candles_database_deduplication(ingestion_service, test_db_session):
    """Test that repeatedly ingesting identical candles does not cause duplicates or errors."""
    t1 = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 28, 10, 15, tzinfo=timezone.utc)

    batch1 = [
        CandleCreate(symbol="EUR/USD", timeframe="15m", timestamp=t1, open=1.080, high=1.083, low=1.079, close=1.081),
        CandleCreate(symbol="EUR/USD", timeframe="15m", timestamp=t2, open=1.081, high=1.084, low=1.080, close=1.082),
    ]

    report1 = ingestion_service.ingest_candles(batch1, "EUR/USD", "15m")
    assert report1.fetched_count == 2
    assert report1.inserted_count == 2
    assert report1.skipped_duplicates_count == 0
    assert test_db_session.query(Candle).count() == 2

    # Ingest overlapping batch: t2 (existing) + t3 (new)
    t3 = datetime(2026, 8, 28, 10, 30, tzinfo=timezone.utc)
    batch2 = [
        CandleCreate(symbol="EUR/USD", timeframe="15m", timestamp=t2, open=1.081, high=1.084, low=1.080, close=1.082),
        CandleCreate(symbol="EUR/USD", timeframe="15m", timestamp=t3, open=1.082, high=1.085, low=1.081, close=1.083),
    ]

    report2 = ingestion_service.ingest_candles(batch2, "EUR/USD", "15m")
    assert report2.fetched_count == 2
    assert report2.inserted_count == 1  # only t3 is inserted
    assert report2.skipped_duplicates_count == 1  # t2 skipped
    assert test_db_session.query(Candle).count() == 3


@pytest.mark.asyncio
async def test_sync_symbol_timeframe(ingestion_service, test_db_session):
    """Test full sync pipeline using provider and database."""
    report = await ingestion_service.sync_symbol_timeframe("GBP/USD", "1h", limit=25)
    assert report.symbol == "GBP/USD"
    assert report.timeframe == "1h"
    assert report.inserted_count == 25
    assert test_db_session.query(Candle).filter_by(symbol="GBP/USD", timeframe="1h").count() == 25
