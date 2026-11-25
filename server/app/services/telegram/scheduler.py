"""Automated Background Market Scanner Scheduler using APScheduler."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import ACTIVE_SYMBOLS, settings
from app.core.database import SessionLocal
from app.core.logging import logger
from app.services.market_data import get_market_data_provider
from app.services.market_data.cache import CachedMarketDataProvider
from app.services.news import ForexFactoryProvider
from app.services.paper_trading import PaperTradingService
from app.services.signals import SignalGenerator
from app.services.telegram.client import get_telegram_client
from app.services.telegram.scanner import AutomatedMarketScanner


_scheduler: Optional[AsyncIOScheduler] = None
_shared_scanner: Optional[AutomatedMarketScanner] = None


def get_shared_scanner() -> AutomatedMarketScanner:
    """Return the shared singleton AutomatedMarketScanner instance."""
    global _shared_scanner
    if _shared_scanner is None:
        _shared_scanner = AutomatedMarketScanner(
            signal_generator=SignalGenerator(),
            paper_service=PaperTradingService(),
            telegram_client=get_telegram_client(),
            market_provider=CachedMarketDataProvider(
                get_market_data_provider(settings.MARKET_DATA_PROVIDER)
            ),
            news_provider=ForexFactoryProvider(),
        )
    return _shared_scanner


def set_shared_scanner(scanner: AutomatedMarketScanner):
    """Set or override the shared AutomatedMarketScanner instance."""
    global _shared_scanner
    _shared_scanner = scanner


def is_scheduler_running() -> bool:
    """Check if the background scanner scheduler is currently active and running."""
    global _scheduler
    return _scheduler is not None and _scheduler.running


def get_scheduler_info() -> Dict[str, Any]:
    """Retrieve runtime information from the scheduler and shared scanner."""
    global _scheduler
    running = is_scheduler_running()
    next_run_time = None
    if running and _scheduler is not None:
        job = _scheduler.get_job("automated_market_scanner")
        if job:
            next_run_time = job.next_run_time

    scanner = get_shared_scanner()
    active_symbols = list(ACTIVE_SYMBOLS)
    return {
        "is_enabled": settings.SCANNER_ENABLED,
        "is_running": running,
        "schedule": "15-minute candle-close (:00:10, :15:10, :30:10, :45:10 UTC)",
        "scanned_symbols": active_symbols,
        "scanned_timeframes": settings.SCANNER_TIMEFRAMES,
        "auto_paper_trade": settings.SCANNER_AUTO_TRADE_PAPER,
        "last_scan_at": scanner._last_scan_at,
        "next_scan_at": next_run_time,
        "last_scan_signals_count": scanner._last_signals_count,
        "total_scans_completed": scanner._total_scans_completed,
    }


def start_scanner_scheduler(
    scanner: Optional[AutomatedMarketScanner] = None,
) -> Optional[AsyncIOScheduler]:
    """Initialize and start the background APScheduler for automated market scanning.

    The scheduler fires at :00:10, :15:10, :30:10, and :45:10 UTC — exactly
    10 seconds after each 15-minute candle close boundary.  This 10-second
    offset allows market data providers to persist the completed bar before the
    scan reads it, eliminating the class of bugs caused by evaluating stale or
    still-forming candles.

    Previous behaviour used IntervalTrigger anchored to server-start time,
    producing arbitrary offsets (e.g. :52 past the hour) that could evaluate
    15m and 30m candles 20–60 minutes after their close.
    """
    global _scheduler
    if not settings.SCANNER_ENABLED:
        logger.info("Automated market scanner is disabled (SCANNER_ENABLED=False).")
        return None

    if _scheduler is not None and _scheduler.running:
        logger.warning("Scanner scheduler is already running. Skipping duplicate startup.")
        return _scheduler

    target_scanner = scanner or get_shared_scanner()
    if scanner is not None:
        set_shared_scanner(scanner)

    logger.info("Scanner enabled")
    logger.info(
        "Scanner schedule: every 15 minutes aligned to candle closes "
        "(:00:10, :15:10, :30:10, :45:10 UTC)"
    )
    logger.info(f"Scanner timeframes: {settings.SCANNER_TIMEFRAMES}")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

    _scheduler = AsyncIOScheduler(timezone=timezone.utc, event_loop=loop)

    async def _scheduled_scan_job():
        """Scheduled task wrapping a single scan cycle with isolated database session and error handling."""
        logger.info("Starting scheduled scan job execution...")
        db = SessionLocal()
        try:
            await target_scanner.run_scan_cycle(
                db=db,
                symbols=list(ACTIVE_SYMBOLS),
                timeframes=settings.SCANNER_TIMEFRAMES,
                broadcast_to_telegram=True,
                auto_paper_trade=settings.SCANNER_AUTO_TRADE_PAPER,
            )
            if _scheduler is not None and _scheduler.running:
                job = _scheduler.get_job("automated_market_scanner")
                if job and job.next_run_time:
                    logger.info(f"Next scan scheduled: {job.next_run_time.isoformat()}")
        except Exception as e:
            logger.error(f"Scanner cycle failed: {e}", exc_info=True)
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # CronTrigger aligned to 15-minute market candle close boundaries.
    #
    # Fires at: HH:00:10, HH:15:10, HH:30:10, HH:45:10 (UTC)
    #   minute="0,15,30,45" — the four 15-minute boundaries per hour
    #   second=10           — 10-second candle-persistence offset
    #
    # No `next_run_time` is set here; the first execution will happen at the
    # next aligned boundary, guaranteeing that the first scan — like all
    # subsequent ones — operates on fully closed and persisted candle data.
    # -----------------------------------------------------------------------
    _scheduler.add_job(
        _scheduled_scan_job,
        trigger=CronTrigger(
            minute="0,15,30,45",
            second=10,
            timezone=timezone.utc,
        ),
        id="automated_market_scanner",
        name="Automated Market Scanner (candle-close aligned)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )

    _scheduler.start()
    logger.info("Scanner started — first scan at next :XX:10 candle-close boundary (UTC)")
    return _scheduler


def stop_scanner_scheduler():
    """Gracefully shutdown the background APScheduler."""
    global _scheduler
    if _scheduler is not None:
        if _scheduler.running:
            _scheduler.shutdown(wait=False)
            logger.info("Scanner stopped")
        _scheduler = None
