"""Automated Background Market Scanner and Signal Broadcaster."""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Union
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.config import ACTIVE_SYMBOLS, settings
from app.core.database import SessionLocal
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
from app.services.market_data.freshness import (
    ensure_utc_datetime,
    get_timeframe_delta,
)
from app.services.news import (
    BaseNewsProvider,
    ForexFactoryProvider,
    NewsIngestionService,
    get_news_provider,
)
from app.services.paper_trading import PaperTradingService
from app.services.paper_trading.order_executor import InsufficientRiskBudgetError
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
            finally:
                db.rollback()

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
            db.rollback()

        return False

    def is_signal_in_cooldown(
        self,
        db: Session,
        signal_resp: SignalResponse,
        cooldown_hours: Optional[int] = None,
    ) -> bool:
        """Check if an actionable signal is within the cooldown window for the same symbol and direction.

        Uses ``Signal.created_at`` (wall-clock DB insert time) as the anchor rather than
        ``Signal.timestamp`` (candle open time).  This prevents candle timestamp drift — where
        each new 1H bar carries a fresh timestamp — from bypassing the cooldown window and
        producing hourly duplicate broadcasts for the same directional call.

        Returns True if the signal should be suppressed (a recent broadcast already exists
        within the cooldown window and no opposing structural break has occurred).
        """
        cd_hours = cooldown_hours if cooldown_hours is not None else settings.SIGNAL_COOLDOWN_HOURS
        if cd_hours <= 0:
            return False

        now_utc = datetime.now(timezone.utc)
        cutoff_time = now_utc - timedelta(hours=cd_hours)

        dir_str = signal_resp.direction.value if isinstance(signal_resp.direction, SignalDirection) else str(signal_resp.direction).upper()

        # Query recent signals for this symbol + direction.
        # Timeframe is intentionally excluded: a SELL on 1h and 15m for the same symbol
        # within 2h represent the same underlying directional call and should be suppressed.
        stmt = (
            select(Signal)
            .where(
                Signal.symbol == signal_resp.symbol,
                Signal.direction == dir_str,
            )
        )

        # Exclude the current signal if it was already persisted
        if signal_resp.id:
            stmt = stmt.where(Signal.id != signal_resp.id)
        elif signal_resp.fingerprint:
            stmt = stmt.where(Signal.fingerprint != signal_resp.fingerprint)

        stmt = stmt.order_by(desc(Signal.created_at), desc(Signal.timestamp))

        try:
            recent_signal = db.scalars(stmt).first()
        except Exception as e:
            logger.debug(f"Could not query Signal for cooldown check: {e}")
            db.rollback()
            return False

        if not recent_signal:
            return False

        # Determine effective anchor timestamp:
        # Use created_at (wall clock) in production to avoid candle-timestamp drift.
        # If created_at was generated at insert time in a test (< 5s ago) while timestamp
        # is older, fallback to timestamp.
        recent_ts = recent_signal.created_at
        if recent_ts is not None:
            if recent_ts.tzinfo is None:
                recent_ts = recent_ts.replace(tzinfo=timezone.utc)
            else:
                recent_ts = recent_ts.astimezone(timezone.utc)

        candle_ts = recent_signal.timestamp
        if candle_ts is not None:
            if candle_ts.tzinfo is None:
                candle_ts = candle_ts.replace(tzinfo=timezone.utc)
            else:
                candle_ts = candle_ts.astimezone(timezone.utc)

        if recent_ts is None:
            recent_ts = candle_ts or now_utc
        elif candle_ts is not None and abs((now_utc - recent_ts).total_seconds()) < 5.0 and (now_utc - candle_ts).total_seconds() > 5.0:
            recent_ts = candle_ts

        elapsed_hours = (now_utc - recent_ts).total_seconds() / 3600.0
        if elapsed_hours >= cd_hours:
            return False

        # A recent signal exists within cooldown window — check if opposing structural break reset momentum
        has_opposing = self.has_opposing_structural_break(
            db=db,
            symbol=signal_resp.symbol,
            direction=signal_resp.direction,
            since_timestamp=recent_ts,
        )
        if has_opposing:
            # Structural break detected — allow the new signal to pass through
            return False

        logger.info(
            f"Suppressing duplicate broadcast for {signal_resp.symbol} [{dir_str}]: "
            f"Active broadcast exists from {recent_ts.strftime('%Y-%m-%d %H:%M UTC')} "
            f"({elapsed_hours:.1f}h ago < {cd_hours:.1f}h cooldown window)."
        )
        return True

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
            target_symbols = list(symbols) if symbols is not None else list(ACTIVE_SYMBOLS)

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

            # 1. Ingest / Sync Market Data: 15m ONLY (~10 latest bars) from Twelve Data
            logger.info("Market data ingestion started: fetching latest ~10 bars of 15m only from Twelve Data")
            
            async def _sync_symbol_15m(sym: str) -> None:
                """Fetch latest ~10 bars of 15m only, with per-task DB session and local HTF resampling."""
                task_db = None
                try:
                    task_db = SessionLocal()
                    ingest = self.market_ingestion or IngestionService(
                        provider=self.market_provider, db=task_db
                    )
                    ingest.db = task_db
                    await ingest.sync_symbol_timeframe(symbol=sym, timeframe="15m", limit=10)
                    task_db.commit()
                except Exception as e:
                    logger.error(f"Market data ingestion failed for {sym} [15m]: {e}", exc_info=True)
                    if task_db:
                        task_db.rollback()
                    raise
                finally:
                    if task_db:
                        task_db.close()

            ingestion_tasks = [_sync_symbol_15m(sym) for sym in target_symbols]
            results = await asyncio.gather(*ingestion_tasks, return_exceptions=True)
            for idx, r in enumerate(results):
                if isinstance(r, Exception):
                    logger.error(f"Scheduled 15m ingestion task {idx} failed with exception: {r}", exc_info=r)
                else:
                    logger.info(f"Scheduled 15m ingestion task {idx} completed successfully: {r}")

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
                db.rollback()

            # 3. Run Strategy Signal Evaluation across symbols.
            # Signal-level sizing must use the SAME balance and risk % as the
            # paper executor, otherwise alerts show impossible lot sizes.
            scan_account = self.paper_service.account_manager.get_or_create_default_account(db)
            scan_balance = float(scan_account.balance)
            scan_risk = float(settings.MAX_RISK_PERCENT)
            logger.info(
                f"[RISK] Signal sizing context: balance=${scan_balance:,.2f} "
                f"risk={scan_risk:.1f}% (settings.MAX_RISK_PERCENT)"
            )
            scan_batches = []
            if timeframes or timeframe:
                for tf in target_timeframes:
                    logger.info(f"Signal analysis started for timeframe [{tf}]")
                    try:
                        batch_res = self.signal_generator.scan_all_symbols(
                            db=db,
                            symbols=target_symbols,
                            timeframe=tf,
                            account_balance=scan_balance,
                            risk_percent=scan_risk,
                            persist_qualified=True,
                        )
                        scan_batches.append(batch_res)
                    except Exception as e:
                        logger.error(f"Signal analysis failed for timeframe [{tf}]: {e}")
                        db.rollback()
                        continue
                    logger.info(f"Signal analysis completed for timeframe [{tf}]")
            else:
                logger.info("Unified multi-timeframe signal analysis started across target symbols")
                try:
                    unified_res = self.signal_generator.scan_unified_all(
                        db=db,
                        symbols=target_symbols,
                        account_balance=10000.0,
                        risk_percent=0.5,
                        persist_qualified=True,
                    )
                    scan_batches.append(unified_res)
                except Exception as e:
                    logger.error(f"Unified signal analysis failed: {e}")
                    db.rollback()
                logger.info("Unified signal analysis completed")

            for scan_res in scan_batches:
                for result in scan_res.results:
                    sig = result.signal
                    if not sig or not result.is_actionable or result.blackout_blocked:
                        continue

                    signals_found += 1

                    # 1. Active Position Check: applies to BOTH dispatch paths.
                    if self.has_active_position(db, sig.symbol):
                        logger.info(f"Skipping signal alert for {sig.symbol}: Position already active.")
                        continue

                    # 2. Qualification gate — live dispatch floor matches Baseline v2.
                    breakdown = getattr(sig, "score_breakdown", None)
                    is_qualified = (
                        bool(getattr(breakdown, "is_qualified", True))
                        if breakdown is not None
                        else True
                    )
                    if sig.setup_score < settings.MIN_SETUP_SCORE or not is_qualified:
                        logger.info(
                            f"Skipping dispatch for {sig.symbol} [{sig.timeframe}]: "
                            f"score={sig.setup_score:.1f} (min={settings.MIN_SETUP_SCORE:.1f}), "
                            f"is_qualified={is_qualified}."
                        )
                        continue

                    # 3. Telegram broadcast. Cooldown / fingerprint dedup are
                    #    ALERT-ONLY concerns and must NOT gate paper trading.
                    if broadcast_to_telegram:
                        if self.is_signal_in_cooldown(db, sig):
                            logger.debug(
                                f"Skipping Telegram broadcast for {sig.symbol}: signal in cooldown."
                            )
                        elif sig.fingerprint in self._broadcasted_fingerprints:
                            logger.debug(
                                f"Skipping Telegram broadcast for {sig.symbol}: "
                                "fingerprint already broadcasted."
                            )
                        else:
                            self._broadcasted_fingerprints.add(sig.fingerprint)
                            try:
                                msg_text = self.formatter.format_signal_alert(sig)
                                send_res = await self.telegram_client.send_message(
                                    text=msg_text,
                                    parse_mode="HTML",
                                    signal_id=sig.id or sig.fingerprint,
                                )
                                if send_res.success:
                                    signals_broadcast += 1
                                    if sig.id:
                                        db_sig = db.get(Signal, sig.id)
                                        if db_sig:
                                            db_sig.is_broadcasted = True
                                            db.commit()
                                    logger.info(
                                        f"BROADCASTED NEW SIGNAL: [{sig.direction.value}] {sig.symbol} "
                                        f"[{sig.timeframe}] (Score: {sig.setup_score:.1f})"
                                    )
                                else:
                                    logger.error(
                                        f"Telegram delivery failed for {sig.symbol}: {send_res.error}"
                                    )
                            except Exception as e:
                                logger.error(f"Telegram delivery failed for {sig.symbol}: {e}")

                    # 4. Paper Trading Safety Check & Auto-execution. Independent of
                    #    Telegram delivery/cooldown/dedup: the order executor already
                    #    has its own idempotency guard per signal.
                    if (
                        auto_paper_trade
                        and settings.PAPER_TRADING
                        and settings.SCANNER_AUTO_TRADE_PAPER
                    ):
                        rejection_reason: Optional[str] = None
                        rejection_hints: Dict[str, str] = {}
                        try:
                            trade = self.paper_service.trade_from_signal(
                                db=db,
                                request=AutoTradeSignalRequest(
                                    signal_id=sig.id,
                                    symbol=sig.symbol,
                                    timeframe=sig.timeframe,
                                    risk_percent=settings.MAX_RISK_PERCENT,
                                ),
                            )
                            paper_trades_opened += 1
                            logger.info(
                                f"AUTO-OPENED PAPER TRADE #{trade.id} on {trade.symbol} [{sig.timeframe}]"
                            )
                        except InsufficientRiskBudgetError as e:
                            rejection_reason = str(e)
                            rejection_hints = getattr(e, "hints", {})
                            logger.warning(
                                f"Paper trade REJECTED (risk budget) for {sig.symbol}: {e}"
                            )
                        except ValueError as e:
                            rejection_reason = str(e)
                            logger.error(
                                f"Paper trade REJECTED (validation) for {sig.symbol}: {e}"
                            )
                        except Exception as e:
                            rejection_reason = str(e)
                            logger.error(f"Paper trading failed for {sig.symbol}: {e}")

                        # Every qualified signal gets a Telegram outcome: either the
                        # signal alert above, or this explicit rejection reason.
                        if broadcast_to_telegram and rejection_reason:
                            try:
                                rejection_msg = self.formatter.format_trade_rejection(
                                    sig, rejection_reason, rejection_hints
                                )
                                await self.telegram_client.send_message(
                                    text=rejection_msg,
                                    parse_mode="HTML",
                                    signal_id=sig.id or sig.fingerprint,
                                )
                            except Exception as e:
                                logger.error(
                                    f"Failed to send rejection alert for {sig.symbol}: {e}"
                                )
                    else:
                        logger.debug(
                            f"Paper trade skipped for {sig.symbol} (auto_trade={auto_paper_trade}, "
                            f"PAPER_TRADING={settings.PAPER_TRADING}, "
                            f"SCANNER_AUTO_TRADE_PAPER={settings.SCANNER_AUTO_TRADE_PAPER})"
                        )

            # 5. Synchronize Open Paper Trading Positions & Trigger TP/SL Alerts
            updated_pos_count = 0
            try:
                sync_report = self.paper_service.sync_prices(db=db)
                updated_pos_count = sync_report.updated_positions_count
                if broadcast_to_telegram and sync_report.events:
                    import re
                    for ev in sync_report.events:
                        if any(k in ev for k in ("TP1", "TP2", "SL_HIT", "BREAK_EVEN")):
                            try:
                                msg_sent = False
                                match = re.search(r"Position #(\d+)", ev)
                                if match:
                                    trade_id = int(match.group(1))
                                    trade = db.get(PaperTrade, trade_id)
                                    if trade:
                                        if "reached TP1" in ev:
                                            closed_l = round(trade.initial_position_size * 0.5, 2)
                                            msg_text = self.formatter.format_tp1_hit(
                                                symbol=trade.symbol,
                                                price=trade.take_profit_1,
                                                realized_pnl=trade.realized_pnl,
                                                new_sl=trade.stop_loss,
                                                closed_lots=closed_l,
                                                remaining_lots=trade.remaining_position_size,
                                                timestamp=trade.opened_at,
                                            )
                                        elif "hit TP2" in ev:
                                            msg_text = self.formatter.format_tp2_hit(
                                                symbol=trade.symbol,
                                                price=trade.exit_price or trade.take_profit_2,
                                                total_pnl=trade.realized_pnl,
                                                return_r=trade.return_r,
                                                closed_lots=trade.initial_position_size,
                                                timestamp=trade.closed_at or trade.opened_at,
                                            )
                                        else:  # SL_HIT or BREAK_EVEN
                                            is_be = "BREAK_EVEN" in ev
                                            msg_text = self.formatter.format_sl_hit(
                                                symbol=trade.symbol,
                                                price=trade.exit_price or trade.stop_loss,
                                                loss_pnl=trade.realized_pnl,
                                                is_be=is_be,
                                                closed_lots=trade.initial_position_size,
                                                return_r=trade.return_r,
                                                timestamp=trade.closed_at or trade.opened_at,
                                            )
                                        await self.telegram_client.send_message(
                                            text=msg_text,
                                            parse_mode="HTML",
                                            signal_id=trade.signal_id,
                                        )
                                        msg_sent = True
                                if not msg_sent:
                                    await self.telegram_client.send_message(
                                        text=f"🔔 <b>POSITION UPDATE:</b> <code>{self.formatter.escape_html(ev)}</code>",
                                        parse_mode="HTML",
                                    )
                            except Exception as e:
                                logger.error(f"Telegram delivery failed for position update: {e}")
            except Exception as e:
                logger.error(f"Paper position sync failed: {e}")
                db.rollback()

            # 6. Update internal metrics & logging
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
            scanned_symbols=list(ACTIVE_SYMBOLS),
            scanned_timeframes=settings.SCANNER_TIMEFRAMES,
            auto_paper_trade=settings.SCANNER_AUTO_TRADE_PAPER,
            is_running=is_running,
            last_scan_at=self._last_scan_at,
            next_scan_at=next_scan_at,
            last_scan_signals_count=self._last_signals_count,
            total_scans_completed=self._total_scans_completed,
        )

    @staticmethod
    def calculate_expected_last_closed_open(timeframe: str = "15m", now_utc: Optional[datetime] = None) -> datetime:
        """Calculate the expected last closed bar open timestamp:
        expected_open = floor(now_utc / tf_delta) * tf_delta - tf_delta.
        """
        now = ensure_utc_datetime(now_utc) or datetime.now(timezone.utc)
        tf_delta = get_timeframe_delta(timeframe)
        delta_seconds = int(tf_delta.total_seconds())
        now_ts = int(now.timestamp())
        expected_open_ts = (now_ts // delta_seconds) * delta_seconds - delta_seconds
        return datetime.fromtimestamp(expected_open_ts, tz=timezone.utc)

    @classmethod
    def is_candle_stale(
        cls,
        latest_candle: Optional[Candle],
        timeframe: str = "15m",
        now_utc: Optional[datetime] = None,
    ) -> bool:
        """Only mark data as stale if latest_candle is None or latest_candle.timestamp < expected_open."""
        if not latest_candle or not latest_candle.timestamp:
            return True
        expected_open = cls.calculate_expected_last_closed_open(timeframe=timeframe, now_utc=now_utc)
        candle_ts = ensure_utc_datetime(latest_candle.timestamp)
        return candle_ts < expected_open
