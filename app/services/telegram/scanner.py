"""Automated Background Market Scanner and Signal Broadcaster."""

import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Union
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.config import settings
from app.core.logging import logger
from app.models.candle import Candle
from app.models.signal import Signal
from app.schemas.paper_trading import AutoTradeSignalRequest
from app.schemas.signal import SignalDirection
from app.schemas.telegram import ScannerStatusResponse, ScannerTriggerResponse
from app.services.market_data import (
    BaseMarketDataProvider,
    IngestionService,
    get_market_data_provider,
)
from app.services.news import (
    BaseNewsProvider,
    ForexFactoryProvider,
    NewsIngestionService,
)
from app.services.paper_trading import PaperTradingService
from app.services.signals import SignalGenerator
from app.services.telegram.client import BaseTelegramClient, get_telegram_client
from app.services.telegram.message_formatter import TelegramMessageFormatter


class AutomatedMarketScanner:
    """Automated periodic scanner evaluating currency pairs, broadcasting signals, and monitoring paper positions."""

    def __init__(
        self,
        signal_generator: Optional[SignalGenerator] = None,
        paper_service: Optional[PaperTradingService] = None,
        telegram_client: Optional[BaseTelegramClient] = None,
        market_provider: Optional[BaseMarketDataProvider] = None,
        news_provider: Optional[BaseNewsProvider] = None,
        market_ingestion: Optional[IngestionService] = None,
        news_ingestion: Optional[NewsIngestionService] = None,
    ):
        self.signal_generator = signal_generator or SignalGenerator()
        self.paper_service = paper_service or PaperTradingService()
        self.telegram_client = telegram_client or get_telegram_client()
        self.market_provider = market_provider or get_market_data_provider(settings.MARKET_DATA_PROVIDER)
        self.news_provider = news_provider or ForexFactoryProvider()
        self.market_ingestion = market_ingestion
        self.news_ingestion = news_ingestion
        self.formatter = TelegramMessageFormatter()

        # Concurrency lock to prevent overlapping scan runs
        self._lock = asyncio.Lock()

        # Deduplication tracker for broadcasted signals
        self._broadcasted_fingerprints: Set[str] = set()
        self._total_scans_completed = 0
        self._last_scan_at: Optional[datetime] = None
        self._last_signals_count = 0

    def _seed_fingerprints_from_db(self, db: Session):
        """Seed deduplication cache with recent signals from database on startup."""
        if not self._broadcasted_fingerprints:
            try:
                recent_fps = db.scalars(
                    select(Signal.fingerprint)
                    .order_by(desc(Signal.timestamp))
                    .limit(100)
                ).all()
                self._broadcasted_fingerprints.update(recent_fps)
            except Exception as e:
                logger.debug(f"Could not preload signal fingerprints from DB: {e}")

    async def run_scan_cycle(
        self,
        db: Session,
        symbols: Optional[List[str]] = None,
        timeframe: Optional[str] = None,
        timeframes: Optional[List[str]] = None,
        broadcast_to_telegram: bool = True,
        auto_paper_trade: bool = True,
    ) -> ScannerTriggerResponse:
        """Execute a full automated market scan cycle across target symbols and timeframes."""
        if self._lock.locked():
            logger.warning("Scanner cycle already in progress, skipping overlapping scan execution.")
            return ScannerTriggerResponse(
                timestamp=datetime.now(timezone.utc),
                symbols_scanned=[],
                timeframes_scanned=[],
                signals_found_count=0,
                signals_broadcast_count=0,
                paper_trades_opened_count=0,
                positions_synced_count=0,
                execution_time_seconds=0.0,
                summary="Scan skipped: previous scan still in progress.",
            )

        async with self._lock:
            start_time = time.time()
            now = datetime.now(timezone.utc)
            target_symbols = symbols or settings.SUPPORTED_SYMBOLS

            # Resolve target timeframes
            if timeframes:
                target_timeframes = list(timeframes)
            elif timeframe:
                target_timeframes = [timeframe]
            else:
                target_timeframes = list(settings.SCANNER_TIMEFRAMES)

            # Ensure fingerprints cache is seeded
            self._seed_fingerprints_from_db(db)

            signals_found = 0
            signals_broadcast = 0
            paper_trades_opened = 0

            logger.info(
                f"Starting scan cycle across {len(target_symbols)} symbols: {target_symbols} "
                f"on timeframes: {target_timeframes}"
            )

            # 1. Ingest / Sync Market Data
            logger.info("Market data ingestion started")
            sync_timeframes = set(target_timeframes)
            if "1h" in target_timeframes or "15m" in target_timeframes:
                sync_timeframes.update(["15m", "1h", "4h"])

            market_ingest_service = self.market_ingestion or IngestionService(
                provider=self.market_provider, db=db
            )
            market_ingest_service.db = db

            for sym in target_symbols:
                for tf in sync_timeframes:
                    try:
                        await market_ingest_service.sync_symbol_timeframe(
                            symbol=sym, timeframe=tf, limit=100
                        )
                    except Exception as e:
                        logger.error(f"Market data ingestion failed for {sym} [{tf}]: {e}")

            logger.info("Market data ingestion completed")

            # 2. Ingest / Sync Economic News Calendar
            logger.info("News ingestion started")
            try:
                news_ingest_service = self.news_ingestion or NewsIngestionService(
                    provider=self.news_provider, db=db
                )
                news_ingest_service.db = db
                await news_ingest_service.sync_calendar()
                logger.info("News check completed")
            except Exception as e:
                logger.error(f"News ingestion failed: {e}")

            # 3. Run Strategy Signal Evaluation across symbols & timeframes
            for tf in target_timeframes:
                logger.info(f"Signal analysis started for timeframe [{tf}]")
                try:
                    scan_res = self.signal_generator.scan_all_symbols(
                        db=db,
                        symbols=target_symbols,
                        timeframe=tf,
                        account_balance=10000.0,
                        risk_percent=0.5,
                        persist_qualified=True,
                    )
                except Exception as e:
                    logger.error(f"Signal analysis failed for timeframe [{tf}]: {e}")
                    continue

                logger.info(f"Signal analysis completed for timeframe [{tf}]")

                for result in scan_res.results:
                    sig = result.signal
                    if not sig or not result.is_actionable or result.blackout_blocked:
                        continue

                    signals_found += 1

                    # Check deduplication
                    if sig.fingerprint not in self._broadcasted_fingerprints:
                        self._broadcasted_fingerprints.add(sig.fingerprint)

                        # Broadcast to Telegram
                        if broadcast_to_telegram:
                            try:
                                msg_text = self.formatter.format_signal_alert(sig)
                                send_res = await self.telegram_client.send_message(text=msg_text)
                                if send_res.success:
                                    signals_broadcast += 1
                                    logger.info(
                                        f"BROADCASTED NEW SIGNAL: [{sig.direction.value}] {sig.symbol} "
                                        f"[{tf}] (Score: {sig.setup_score:.1f})"
                                    )
                                else:
                                    logger.error(
                                        f"Telegram delivery failed for {sig.symbol}: {send_res.error}"
                                    )
                            except Exception as e:
                                logger.error(f"Telegram delivery failed for {sig.symbol}: {e}")

                        # Paper Trading Safety Check
                        if (
                            auto_paper_trade
                            and settings.PAPER_TRADING
                            and settings.SCANNER_AUTO_TRADE_PAPER
                        ):
                            try:
                                trade = self.paper_service.trade_from_signal(
                                    db=db,
                                    request=AutoTradeSignalRequest(
                                        signal_id=sig.id,
                                        symbol=sig.symbol,
                                        timeframe=sig.timeframe,
                                        risk_percent=0.5,
                                    ),
                                )
                                paper_trades_opened += 1
                                logger.info(
                                    f"AUTO-OPENED PAPER TRADE #{trade.id} on {trade.symbol} [{trade.timeframe}]"
                                )
                            except Exception as e:
                                logger.error(f"Paper trading failed for {sig.symbol}: {e}")
                        else:
                            logger.debug(
                                f"Paper trade skipped for {sig.symbol} (auto_trade={auto_paper_trade}, "
                                f"PAPER_TRADING={settings.PAPER_TRADING}, "
                                f"SCANNER_AUTO_TRADE_PAPER={settings.SCANNER_AUTO_TRADE_PAPER})"
                            )

            # 4. Synchronize Open Paper Trading Positions & Trigger TP/SL Alerts
            updated_pos_count = 0
            try:
                sync_report = self.paper_service.sync_prices(db=db)
                updated_pos_count = sync_report.updated_positions_count
                if broadcast_to_telegram and sync_report.events:
                    for ev in sync_report.events:
                        if any(k in ev for k in ("TP1", "TP2", "SL_HIT", "BREAK_EVEN")):
                            try:
                                await self.telegram_client.send_message(
                                    text=f"🔔 *POSITION UPDATE:* `{ev}`"
                                )
                            except Exception as e:
                                logger.error(f"Telegram delivery failed for position update: {e}")
            except Exception as e:
                logger.error(f"Paper position sync failed: {e}")

            # 5. Update internal metrics & logging
            elapsed = round(time.time() - start_time, 2)
            self._total_scans_completed += 1
            self._last_scan_at = now
            self._last_signals_count = signals_found

            logger.info(f"Qualified signals found: {signals_found}")
            logger.info(f"Telegram broadcast completed: {signals_broadcast} sent")
            logger.info(f"Paper trades created: {paper_trades_opened}")

            summary = (
                f"Scanned {len(target_symbols)} pairs across {target_timeframes} in {elapsed}s | "
                f"Signals: {signals_found} found, {signals_broadcast} broadcast | "
                f"Paper Positions: {paper_trades_opened} opened, {updated_pos_count} synced"
            )
            logger.info(f"Scan cycle completed: {summary}")

            return ScannerTriggerResponse(
                timestamp=now,
                symbols_scanned=target_symbols,
                timeframes_scanned=target_timeframes,
                signals_found_count=signals_found,
                signals_broadcast_count=signals_broadcast,
                paper_trades_opened_count=paper_trades_opened,
                positions_synced_count=updated_pos_count,
                execution_time_seconds=elapsed,
                summary=summary,
            )

    def get_status(self) -> ScannerStatusResponse:
        """Query scanner configuration and activity status."""
        is_running = False
        next_scan_at = None
        try:
            from app.services.telegram.scheduler import is_scheduler_running, get_scheduler_info
            is_running = is_scheduler_running()
            info = get_scheduler_info()
            next_scan_at = info.get("next_scan_at")
        except Exception:
            pass

        return ScannerStatusResponse(
            is_enabled=settings.SCANNER_ENABLED,
            interval_minutes=settings.SCANNER_INTERVAL_MINUTES,
            scanned_symbols=settings.SUPPORTED_SYMBOLS,
            scanned_timeframes=settings.SCANNER_TIMEFRAMES,
            auto_paper_trade=settings.SCANNER_AUTO_TRADE_PAPER,
            is_running=is_running,
            last_scan_at=self._last_scan_at,
            next_scan_at=next_scan_at,
            last_scan_signals_count=self._last_signals_count,
            total_scans_completed=self._total_scans_completed,
        )
