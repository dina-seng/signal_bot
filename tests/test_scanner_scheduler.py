"""Comprehensive tests for Automated Scanner, Production Scheduler, Error Isolation, and Safety."""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Optional
import pytest

from app.core.config import settings
from app.models.candle import Candle
from app.models.signal import Signal
from app.schemas.candle import CandleCreate
from app.schemas.signal import SignalDirection, SignalResponse, SignalStatus
from app.services.market_data.base import BaseMarketDataProvider
from app.services.market_data.mock_provider import MockMarketDataProvider
from app.services.news.mock_provider import MockNewsProvider
from app.services.news.ingestion import NewsIngestionService
from app.services.paper_trading import PaperTradingService
from app.services.signals import SignalGenerator
from app.services.telegram.client import MockTelegramClient
from app.services.telegram.scanner import AutomatedMarketScanner
from app.services.telegram.scheduler import (
    get_scheduler_info,
    get_shared_scanner,
    is_scheduler_running,
    set_shared_scanner,
    start_scanner_scheduler,
    stop_scanner_scheduler,
)


class FailingMarketDataProvider(BaseMarketDataProvider):
    """Market data provider that raises runtime exceptions to test error isolation."""

    def is_symbol_supported(self, symbol: str) -> bool:
        return True

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[CandleCreate]:
        raise ConnectionError("Simulated remote provider connection outage!")

    async def fetch_latest(
        self, symbol: str, timeframe: str, count: int = 50
    ) -> List[CandleCreate]:
        raise ConnectionError("Simulated remote provider connection outage!")


def _seed_candles(db, symbol="EUR/USD", count=40):
    """Seed test candles."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(count):
        c = Candle(
            symbol=symbol,
            timeframe="1h",
            timestamp=now + timedelta(hours=i),
            open=1.1000 + (i * 0.0005),
            high=1.1020 + (i * 0.0005),
            low=1.0990 + (i * 0.0005),
            close=1.1010 + (i * 0.0005),
            volume=500.0,
        )
        db.add(c)
    db.commit()


# =====================================================================
# 1. Lifecycle & Scheduling Configuration Tests
# =====================================================================

@pytest.mark.asyncio
async def test_scheduler_starts_when_enabled():
    """Verify scheduler starts properly when SCANNER_ENABLED=True."""
    settings.SCANNER_ENABLED = True
    settings.SCANNER_INTERVAL_MINUTES = 15

    mock_scanner = AutomatedMarketScanner(telegram_client=MockTelegramClient())
    scheduler = start_scanner_scheduler(mock_scanner)

    assert scheduler is not None
    assert is_scheduler_running() is True

    job = scheduler.get_job("automated_market_scanner")
    assert job is not None
    assert job.name == "Automated Market Scanner"

    stop_scanner_scheduler()
    assert is_scheduler_running() is False


@pytest.mark.asyncio
async def test_scheduler_does_not_start_when_disabled():
    """Verify scheduler does not start when SCANNER_ENABLED=False."""
    settings.SCANNER_ENABLED = False
    stop_scanner_scheduler()

    scheduler = start_scanner_scheduler()
    assert scheduler is None
    assert is_scheduler_running() is False


@pytest.mark.asyncio
async def test_scheduler_custom_interval():
    """Verify scheduler respects custom SCANNER_INTERVAL_MINUTES."""
    settings.SCANNER_ENABLED = True
    settings.SCANNER_INTERVAL_MINUTES = 7

    mock_scanner = AutomatedMarketScanner(telegram_client=MockTelegramClient())
    scheduler = start_scanner_scheduler(mock_scanner)

    assert scheduler is not None
    info = get_scheduler_info()
    assert info["interval_minutes"] == 7

    stop_scanner_scheduler()


@pytest.mark.asyncio
async def test_prevent_duplicate_scheduler_instances():
    """Verify starting scheduler multiple times returns the same running instance."""
    settings.SCANNER_ENABLED = True
    mock_scanner = AutomatedMarketScanner(telegram_client=MockTelegramClient())

    sched1 = start_scanner_scheduler(mock_scanner)
    sched2 = start_scanner_scheduler(mock_scanner)

    assert sched1 is sched2
    assert len(sched1.get_jobs()) == 1

    stop_scanner_scheduler()


# =====================================================================
# 2. Dependency Wiring & Pipeline Execution Tests
# =====================================================================

@pytest.mark.asyncio
async def test_scanner_dependency_wiring(test_db_session):
    """Verify scanner coordinates market data ingestion, news check, signals, telegram, and paper trading."""
    mock_market = MockMarketDataProvider()
    mock_news = MockNewsProvider()
    mock_tg = MockTelegramClient()
    paper_svc = PaperTradingService()
    signal_gen = SignalGenerator()

    scanner = AutomatedMarketScanner(
        signal_generator=signal_gen,
        paper_service=paper_svc,
        telegram_client=mock_tg,
        market_provider=mock_market,
        news_provider=mock_news,
    )

    assert scanner.market_provider is mock_market
    assert scanner.news_provider is mock_news
    assert scanner.telegram_client is mock_tg
    assert scanner.signal_generator is signal_gen
    assert scanner.paper_service is paper_svc

    # Run cycle across test db
    res = await scanner.run_scan_cycle(
        db=test_db_session,
        symbols=["EUR/USD"],
        timeframes=["1h"],
        broadcast_to_telegram=True,
        auto_paper_trade=True,
    )

    assert res is not None
    assert res.symbols_scanned == ["EUR/USD"]
    assert res.timeframes_scanned == ["1h"]
    assert res.execution_time_seconds >= 0.0


# =====================================================================
# 3. Overlap Protection Tests
# =====================================================================

@pytest.mark.asyncio
async def test_overlap_protection(test_db_session):
    """Verify concurrent scan cycles are rejected cleanly via locking."""
    mock_tg = MockTelegramClient()
    scanner = AutomatedMarketScanner(telegram_client=mock_tg)

    # Acquire lock externally to simulate long running scan
    await scanner._lock.acquire()

    # Attempt to start another scan
    res = await scanner.run_scan_cycle(db=test_db_session, symbols=["EUR/USD"])

    assert "Scan skipped" in res.summary
    assert res.symbols_scanned == []

    # Release lock
    scanner._lock.release()

    # Next scan should proceed normally
    _seed_candles(test_db_session, "EUR/USD", 40)
    res2 = await scanner.run_scan_cycle(
        db=test_db_session, symbols=["EUR/USD"], timeframes=["1h"]
    )
    assert res2.symbols_scanned == ["EUR/USD"]


# =====================================================================
# 4. Error Isolation Tests
# =====================================================================

@pytest.mark.asyncio
async def test_error_isolation_market_data_failure(test_db_session):
    """Simulate market data provider failure; scanner must survive and finish gracefully."""
    failing_provider = FailingMarketDataProvider()
    mock_tg = MockTelegramClient()

    scanner = AutomatedMarketScanner(
        market_provider=failing_provider,
        telegram_client=mock_tg,
    )

    # Even with failing market data provider, scan cycle must complete without raising exception
    res = await scanner.run_scan_cycle(
        db=test_db_session, symbols=["EUR/USD"], timeframes=["1h"]
    )
    assert res is not None
    assert scanner._total_scans_completed == 1


@pytest.mark.asyncio
async def test_error_isolation_telegram_failure(test_db_session):
    """Simulate Telegram delivery failure; scanner must survive and continue."""
    mock_tg = MockTelegramClient()
    scanner = AutomatedMarketScanner(telegram_client=mock_tg)

    # Corrupt telegram send_message by mocking an exception
    async def mock_fail_send(*args, **kwargs):
        raise ConnectionResetError("Telegram socket closed unexpectedly")

    scanner.telegram_client.send_message = mock_fail_send

    _seed_candles(test_db_session, "EUR/USD", 40)
    res = await scanner.run_scan_cycle(
        db=test_db_session, symbols=["EUR/USD"], timeframes=["1h"]
    )
    assert res is not None
    assert scanner._total_scans_completed == 1


# =====================================================================
# 5. Telegram Deduplication Tests
# =====================================================================

@pytest.mark.asyncio
async def test_telegram_signal_deduplication(test_db_session):
    """Verify that identical signal fingerprints are not broadcast repeatedly."""
    mock_tg = MockTelegramClient()
    scanner = AutomatedMarketScanner(telegram_client=mock_tg)

    # Create synthetic actionable signal
    sig_resp = SignalResponse(
        symbol="EUR/USD",
        timeframe="1h",
        direction=SignalDirection.BUY,
        setup_score=88.0,
        entry_price=1.1050,
        stop_loss=1.1000,
        take_profit_1=1.1150,
        take_profit_2=1.1200,
        risk_reward=2.0,
        fingerprint="unique_test_fp_12345",
        reasons=["Test confluence reason"],
        status=SignalStatus.ACTIVE,
        timestamp=datetime.now(timezone.utc),
    )

    # Mock signal_generator.scan_all_symbols to return this signal
    from unittest.mock import MagicMock
    from app.schemas.signal import MarketScanResponse, MarketScanSymbolResult

    mock_scan_res = MarketScanResponse(
        timestamp=datetime.now(timezone.utc),
        scanned_count=1,
        actionable_count=1,
        results=[
            MarketScanSymbolResult(
                symbol="EUR/USD",
                timeframe="1h",
                direction=SignalDirection.BUY,
                setup_score=88.0,
                is_actionable=True,
                signal=sig_resp,
                blackout_blocked=False,
                reasons=["Test"],
            )
        ],
    )
    scanner.signal_generator.scan_all_symbols = MagicMock(return_value=mock_scan_res)

    # Cycle 1: should broadcast
    res1 = await scanner.run_scan_cycle(
        db=test_db_session,
        symbols=["EUR/USD"],
        timeframes=["1h"],
        broadcast_to_telegram=True,
        auto_paper_trade=False,
    )
    assert res1.signals_broadcast_count == 1
    assert len(mock_tg.sent_messages) == 1

    # Cycle 2: identical signal fingerprint should be skipped / deduplicated
    res2 = await scanner.run_scan_cycle(
        db=test_db_session,
        symbols=["EUR/USD"],
        timeframes=["1h"],
        broadcast_to_telegram=True,
        auto_paper_trade=False,
    )
    assert res2.signals_broadcast_count == 0
    assert len(mock_tg.sent_messages) == 1  # No additional message sent


# =====================================================================
# 6. Paper Trading Safety Tests
# =====================================================================

@pytest.mark.asyncio
async def test_paper_trading_safety_when_disabled(test_db_session):
    """Verify paper trading does not execute when PAPER_TRADING=False."""
    settings.PAPER_TRADING = False
    settings.SCANNER_AUTO_TRADE_PAPER = True

    mock_tg = MockTelegramClient()
    scanner = AutomatedMarketScanner(telegram_client=mock_tg)

    sig_resp = SignalResponse(
        symbol="EUR/USD",
        timeframe="1h",
        direction=SignalDirection.BUY,
        setup_score=90.0,
        entry_price=1.1050,
        stop_loss=1.1000,
        take_profit_1=1.1150,
        take_profit_2=1.1200,
        risk_reward=2.0,
        fingerprint="safety_test_fp_disabled",
        reasons=["Test"],
        status=SignalStatus.ACTIVE,
        timestamp=datetime.now(timezone.utc),
    )

    from unittest.mock import MagicMock
    from app.schemas.signal import MarketScanResponse, MarketScanSymbolResult

    mock_scan_res = MarketScanResponse(
        timestamp=datetime.now(timezone.utc),
        scanned_count=1,
        actionable_count=1,
        results=[
            MarketScanSymbolResult(
                symbol="EUR/USD",
                timeframe="1h",
                direction=SignalDirection.BUY,
                setup_score=90.0,
                is_actionable=True,
                signal=sig_resp,
                blackout_blocked=False,
                reasons=["Test"],
            )
        ],
    )
    scanner.signal_generator.scan_all_symbols = MagicMock(return_value=mock_scan_res)

    res = await scanner.run_scan_cycle(
        db=test_db_session,
        symbols=["EUR/USD"],
        timeframes=["1h"],
        auto_paper_trade=True,
    )

    assert res.paper_trades_opened_count == 0

    # Restore setting
    settings.PAPER_TRADING = True


@pytest.mark.asyncio
async def test_paper_trading_safety_when_auto_trade_disabled(test_db_session):
    """Verify paper trading does not execute when SCANNER_AUTO_TRADE_PAPER=False."""
    settings.PAPER_TRADING = True
    settings.SCANNER_AUTO_TRADE_PAPER = False

    mock_tg = MockTelegramClient()
    scanner = AutomatedMarketScanner(telegram_client=mock_tg)

    sig_resp = SignalResponse(
        symbol="EUR/USD",
        timeframe="1h",
        direction=SignalDirection.BUY,
        setup_score=90.0,
        entry_price=1.1050,
        stop_loss=1.1000,
        take_profit_1=1.1150,
        take_profit_2=1.1200,
        risk_reward=2.0,
        fingerprint="safety_test_fp_auto_false",
        reasons=["Test"],
        status=SignalStatus.ACTIVE,
        timestamp=datetime.now(timezone.utc),
    )

    from unittest.mock import MagicMock
    from app.schemas.signal import MarketScanResponse, MarketScanSymbolResult

    mock_scan_res = MarketScanResponse(
        timestamp=datetime.now(timezone.utc),
        scanned_count=1,
        actionable_count=1,
        results=[
            MarketScanSymbolResult(
                symbol="EUR/USD",
                timeframe="1h",
                direction=SignalDirection.BUY,
                setup_score=90.0,
                is_actionable=True,
                signal=sig_resp,
                blackout_blocked=False,
                reasons=["Test"],
            )
        ],
    )
    scanner.signal_generator.scan_all_symbols = MagicMock(return_value=mock_scan_res)

    res = await scanner.run_scan_cycle(
        db=test_db_session,
        symbols=["EUR/USD"],
        timeframes=["1h"],
        auto_paper_trade=True,
    )

    assert res.paper_trades_opened_count == 0

    # Restore setting
    settings.SCANNER_AUTO_TRADE_PAPER = True


@pytest.mark.asyncio
async def test_paper_trading_when_enabled(test_db_session):
    """Verify paper trading executes and logs properly when auto paper trading is enabled."""
    _seed_candles(test_db_session, "EUR/USD", 40)
    settings.PAPER_TRADING = True
    settings.SCANNER_AUTO_TRADE_PAPER = True

    mock_market = MockMarketDataProvider()
    mock_news = MockNewsProvider()
    mock_tg = MockTelegramClient()
    scanner = AutomatedMarketScanner(
        telegram_client=mock_tg,
        market_provider=mock_market,
        news_provider=mock_news,
    )
    scanner._broadcasted_fingerprints = {"existing_dummy_fp"}

    db_sig = Signal(
        symbol="EUR/USD",
        timeframe="1h",
        direction="BUY",
        setup_score=95.0,
        entry_price=1.1050,
        stop_loss=1.1000,
        take_profit_1=1.1150,
        take_profit_2=1.1200,
        risk_reward=2.0,
        status="ACTIVE",
        fingerprint="safety_test_fp_auto_enabled",
        reasons=["High score confluence"],
        timestamp=datetime.now(timezone.utc),
    )
    test_db_session.add(db_sig)
    test_db_session.commit()
    test_db_session.refresh(db_sig)

    sig_resp = SignalResponse.model_validate(db_sig)

    from unittest.mock import MagicMock
    from app.schemas.signal import MarketScanResponse, MarketScanSymbolResult

    mock_scan_res = MarketScanResponse(
        timestamp=datetime.now(timezone.utc),
        scanned_count=1,
        actionable_count=1,
        results=[
            MarketScanSymbolResult(
                symbol="EUR/USD",
                timeframe="1h",
                direction=SignalDirection.BUY,
                setup_score=95.0,
                is_actionable=True,
                signal=sig_resp,
                blackout_blocked=False,
                reasons=["Test"],
            )
        ],
    )
    scanner.signal_generator.scan_all_symbols = MagicMock(return_value=mock_scan_res)

    res = await scanner.run_scan_cycle(
        db=test_db_session,
        symbols=["EUR/USD"],
        timeframes=["1h"],
        broadcast_to_telegram=True,
        auto_paper_trade=True,
    )

    assert res.paper_trades_opened_count == 1


# =====================================================================
# 7. Health API Schema & Values Test
# =====================================================================

def test_health_check_contains_scanner_fields(client):
    """Verify GET /api/v1/health returns scanner health fields."""
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert "scanner_enabled" in data
    assert "scanner_running" in data
    assert "scanner_interval_minutes" in data
    assert data["status"] == "healthy"

