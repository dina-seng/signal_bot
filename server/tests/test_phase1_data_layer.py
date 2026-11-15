"""Phase 1 Data Layer Comprehensive Tests."""

from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest

from app.core.config import settings
from app.main import app
from app.models.candle import Candle
from app.schemas.candle import CandleCreate
from app.services.market_data import (
    TwelveDataProvider,
    IngestionService,
    get_market_data_provider,
)
from app.services.market_data.freshness import (
    check_data_staleness,
    is_forex_weekend,
    ensure_utc_datetime,
)


def test_provider_factory_rejects_mock_and_yahoo():
    """Verify production provider factory rejects 'mock', 'yahoo', and unknown providers."""
    with pytest.raises(ValueError, match="forbidden in production factory"):
        get_market_data_provider("mock")

    with pytest.raises(ValueError, match="forbidden in production factory"):
        get_market_data_provider("yfinance")

    with pytest.raises(ValueError, match="forbidden in production factory"):
        get_market_data_provider("yahoo")

    with pytest.raises(ValueError, match="Only 'twelvedata' is supported"):
        get_market_data_provider("binance")

    # twelvedata succeeds
    prov = get_market_data_provider("twelvedata")
    assert isinstance(prov, TwelveDataProvider)


@pytest.mark.asyncio
async def test_twelvedata_provider_rejects_non_xauusd():
    """Verify TwelveDataProvider strictly rejects any symbol other than XAU/USD."""
    prov = TwelveDataProvider(api_key="test")
    assert prov.is_symbol_supported("XAU/USD") is True
    assert prov.is_symbol_supported("EUR/USD") is False

    with pytest.raises(ValueError, match="only supports 'XAU/USD'"):
        await prov.fetch_candles("EUR/USD", "15m")


def test_gap_detection_flags_missing_candles(test_db_session):
    """Verify IngestionService detects missing 15m candles during active market hours."""
    prov = TwelveDataProvider(api_key="dummy")
    ingest = IngestionService(provider=prov, db=test_db_session)

    # Tuesday: bar 0 at 10:00, bar 1 at 10:45 (missing 10:15 and 10:30)
    t0 = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 10, 10, 45, tzinfo=timezone.utc)

    candles = [
        CandleCreate(symbol="XAU/USD", timeframe="15m", timestamp=t0, open=2600.0, high=2605.0, low=2595.0, close=2601.0, volume=10.0),
        CandleCreate(symbol="XAU/USD", timeframe="15m", timestamp=t1, open=2601.0, high=2606.0, low=2599.0, close=2604.0, volume=15.0),
    ]

    gaps = ingest.detect_gaps(candles, "XAU/USD", "15m")
    assert len(gaps) == 1
    assert gaps[0].missing_candles_estimated == 2
    assert gaps[0].gap_start == t0
    assert gaps[0].gap_end == t1


def test_freshness_across_weekend():
    """Verify that during a weekend, Friday closing candle is considered fresh (not STALE)."""
    # Saturday afternoon: 2026-11-14 14:00 UTC
    sat_as_of = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
    assert is_forex_weekend(sat_as_of) is True

    # Friday closing bar (e.g. 20:45 UTC, closed at 21:00 UTC)
    fri_bar_ts = datetime(2026, 11, 13, 20, 45, tzinfo=timezone.utc)
    fri_bar = CandleCreate(
        symbol="XAU/USD", timeframe="15m", timestamp=fri_bar_ts,
        open=2650.0, high=2655.0, low=2648.0, close=2652.0, volume=100.0
    )

    res = check_data_staleness([fri_bar], symbol="XAU/USD", timeframe="15m", as_of=sat_as_of)
    assert res.is_stale is False
    assert res.is_weekend is True
    assert "weekend" in res.message.lower()


def test_health_endpoint_response_schema(test_db_session):
    """Verify /api/v1/health exposes all Phase 1.9 diagnostic fields."""
    # Seed one 15m candle
    now_utc = datetime.now(timezone.utc)
    candle = Candle(
        symbol="XAU/USD",
        timeframe="15m",
        timestamp=now_utc - timedelta(minutes=15),
        open=2650.0,
        high=2655.0,
        low=2648.0,
        close=2652.0,
        volume=100.0,
        source="twelvedata",
    )
    test_db_session.add(candle)
    test_db_session.commit()

    client = TestClient(app)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()

    assert "last_closed_15m_bar_time" in data
    assert "candle_age_seconds" in data
    assert "is_data_fresh" in data
    assert "data_freshness_status" in data
    assert "credits_used_today" in data
    assert "credits_max_budget" in data
    assert data["credits_max_budget"] == 780
    assert "scheduler_running" in data
    assert "last_sync_status" in data
