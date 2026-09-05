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
from app.models.paper import PaperTrade
from app.models.signal import Signal
from app.models.structure import StructureEvent
from app.schemas.paper_trading import AutoTradeSignalRequest
from app.schemas.signal import SignalDirection, SignalResponse
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
    get_news_provider,
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
        self.news_provider = news_provider or get_news_provider(getattr(settings, "NEWS_PROVIDER", "forexfactory"))
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
                    .where(Signal.is_broadcasted == True)
                    .order_by(desc(Signal.timestamp))
                    .limit(200)
                ).all()
                self._broadcasted_fingerprints.update(recent_fps)
            except Exception as e:
                logger.debug(f"Could not preload signal fingerprints from DB: {e}")

    def has_active_position(self, db: Session, symbol: str) -> bool:
        """Check if an active or pending paper trade exists in the database for the given symbol."""
        stmt = (
            select(PaperTrade.id)
            .where(
                PaperTrade.symbol == symbol,
                PaperTrade.status.in_(["OPEN", "PARTIALLY_CLOSED", "PENDING"]),
            )
            .limit(1)
        )
        return db.scalars(stmt).first() is not None

    def has_opposing_structural_break(
        self,
        db: Session,
        symbol: str,
        direction: Union[SignalDirection, str],
        since_timestamp: datetime,
    ) -> bool:
        """Check if price structure has initiated an opposing structural break since previous signal.

        An opposing structural break indicates market structure shift/reversal:
        - For BUY signals: A BEARISH structure break (e.g. BEARISH_BOS, BEARISH_CHOCH, BEARISH_MSS)
          or opposing SELL signal recorded after the previous signal.
        - For SELL signals: A BULLISH structure break (e.g. BULLISH_BOS, BULLISH_CHOCH, BULLISH_MSS)
          or opposing BUY signal recorded after the previous signal.
        """
        if since_timestamp.tzinfo is None:
            since_ts = since_timestamp.replace(tzinfo=timezone.utc)
        else:
            since_ts = since_timestamp.astimezone(timezone.utc)

        dir_str = direction.value if isinstance(direction, SignalDirection) else str(direction).upper()
        opposing_prefix = "BEARISH" if dir_str == "BUY" else "BULLISH"
        opposing_dir = "SELL" if dir_str == "BUY" else "BUY"

        # 1. Check StructureEvent table for opposing events
        try:
            stmt_struct = select(StructureEvent).where(
                StructureEvent.symbol == symbol,
                StructureEvent.timestamp >= since_ts,
            )
            events = db.scalars(stmt_struct).all()
            for ev in events:
                ev_type = ev.event_type.upper()
                if opposing_prefix in ev_type:
                    logger.info(
                        f"Opposing structural break found for {symbol} ({ev.event_type} at {ev.timestamp}) "
                        f"since previous signal at {since_ts}."
                    )
                    return True
        except Exception as e:
            logger.debug(f"Could not query StructureEvent for opposing break: {e}")

        # 2. Check Signals table for opposing signal generated since
        try:
            stmt_sig = (
                select(Signal)
                .where(
                    Signal.symbol == symbol,
                    Signal.direction == opposing_dir,
                    Signal.timestamp >= since_ts,
                )
                .limit(1)
            )
            if db.scalars(stmt_sig).first() is not None:
                logger.info(
                    f"Opposing signal ({opposing_dir}) found for {symbol} "
                    f"since previous signal at {since_ts}."
                )
                return True
        except Exception as e:
            logger.debug(f"Could not query Signal for opposing break: {e}")

        return False

    def is_signal_in_cooldown(
        self,
        db: Session,
        signal_resp: SignalResponse,
        cooldown_hours: Optional[int] = None,
    ) -> bool:
        """Check if an actionable signal is within the cooldown window for the same symbol and direction.

        Returns True if the signal should be suppressed (is in cooldown and no opposing break occurred).
        """
        cd_hours = cooldown_hours if cooldown_hours is not None else settings.SIGNAL_COOLDOWN_HOURS
        if cd_hours <= 0:
            return False

        dir_str = signal_resp.direction.value if isinstance(signal_resp.direction, SignalDirection) else str(signal_resp.direction).upper()
        current_ts = signal_resp.timestamp or datetime.now(timezone.utc)
        if current_ts.tzinfo is None:
            current_ts = current_ts.replace(tzinfo=timezone.utc)
        else:
            current_ts = current_ts.astimezone(timezone.utc)

        # Query the most recent previous signal for this symbol, timeframe & direction
        stmt = (
            select(Signal)
            .where(
                Signal.symbol == signal_resp.symbol,
                Signal.timeframe == signal_resp.timeframe,
                Signal.direction == dir_str,
            )
            .order_by(desc(Signal.timestamp))
        )

        # Exclude the current signal if it was already persisted
        if signal_resp.id:
            stmt = stmt.where(Signal.id != signal_resp.id)
        elif signal_resp.fingerprint:
            stmt = stmt.where(Signal.fingerprint != signal_resp.fingerprint)

        prev_signal = db.scalars(stmt).first()
        if not prev_signal:
            return False

        prev_ts = prev_signal.timestamp or prev_signal.created_at
        if prev_ts.tzinfo is None:
            prev_ts = prev_ts.replace(tzinfo=timezone.utc)
        else:
            prev_ts = prev_ts.astimezone(timezone.utc)

        elapsed_seconds = (current_ts - prev_ts).total_seconds()
        elapsed_hours = max(0.0, elapsed_seconds / 3600.0)

        if elapsed_hours < cd_hours:
            # Check if an opposing structural break occurred that resets the cooldown
            has_opposing = self.has_opposing_structural_break(
                db=db,
                symbol=signal_resp.symbol,
                direction=signal_resp.direction,
                since_timestamp=prev_ts,
            )
            if not has_opposing:
                logger.info(
                    f"Suppressing duplicate signal alert for {signal_resp.symbol} [{dir_str}]: "
                    f"Recent signal exists from {prev_ts.strftime('%Y-%m-%d %H:%M UTC')} "
                    f"({elapsed_hours:.1f}h ago < {cd_hours}h cooldown window)."
                )
                return True

        return False

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
                        db.rollback()

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
                    db.rollback()
                    continue

                logger.info(f"Signal analysis completed for timeframe [{tf}]")

                for result in scan_res.results:
                    sig = result.signal
                    if not sig or not result.is_actionable or result.blackout_blocked:
                        continue

                    signals_found += 1

                    # 1. Active Position Check: Skip if position is already open/active for this symbol
                    if self.has_active_position(db, sig.symbol):
                        logger.info(f"Skipping signal alert for {sig.symbol}: Position already active.")
                        continue

                    # 2. Signal Cooldown Period Check (Deduping)
                    if self.is_signal_in_cooldown(db, sig):
                        continue

                    # 3. In-memory Fingerprint Deduplication Check
                    if sig.fingerprint in self._broadcasted_fingerprints:
                        logger.debug(f"Skipping signal alert for {sig.symbol}: Fingerprint already broadcasted.")
                        continue

                    self._broadcasted_fingerprints.add(sig.fingerprint)

                    # 4. Standalone Broadcast to Telegram
                    if broadcast_to_telegram:
                        try:
                            msg_text = self.formatter.format_signal_alert(sig)
                            send_res = await self.telegram_client.send_message(text=msg_text)
                            if send_res.success:
                                signals_broadcast += 1
                                if sig.id:
                                    db_sig = db.get(Signal, sig.id)
                                    if db_sig:
                                        db_sig.is_broadcasted = True
                                        db.commit()
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

                    # 5. Paper Trading Safety Check & Auto-execution
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
                                f"AUTO-OPENED PAPER TRADE #{trade.id} on {trade.symbol} [{sig.timeframe}]"
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
                db.rollback()

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
