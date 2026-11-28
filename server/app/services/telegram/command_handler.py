"""Interactive Telegram Bot Commands Processor."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.config import ACTIVE_SYMBOLS, SUPPORTED_SYMBOLS_ALL, settings
from app.core.logging import logger
from app.services.auth_service import AuthService
from app.models.candle import Candle
from app.models.news import NewsEvent
from app.schemas.news import NewsEventResponse
from app.schemas.signal import SignalDirection
from app.schemas.telegram import TelegramCommandRequest, TelegramCommandResponse
from app.services.backtesting import BacktestService
from app.services.market_data import (
    BaseMarketDataProvider,
    IngestionService,
    check_data_staleness,
    ensure_utc_datetime,
    filter_closed_candles,
    get_market_data_provider,
    get_provider_for_symbol,
    get_timeframe_delta,
    log_latest_candle,
)
from app.services.indicators.confluence_calculator import (
    MIN_HISTORY_BARS,
    calculate_technical_confluence,
)
from app.services.news import (
    BaseNewsProvider,
    NewsFilterEngine,
    NewsIngestionService,
    get_news_provider,
)
from app.services.paper_trading import PaperTradingService
from app.services.signals import SignalGenerator
from app.services.signals import lifecycle as signal_lifecycle
from app.services.signals.lifecycle import filter_consumed_scan_results
from app.services.telegram.client import BaseTelegramClient, get_telegram_client
from app.services.telegram.message_formatter import TelegramMessageFormatter


MASTER_FUND_FOOTER = (
    "ℹ️ <i>You are viewing the automated Master Signal Account. "
    "Trades are executed live by the QuantView engine.</i>"
)
MASTER_FUND_POSITIONS_FOOTER = (
    "ℹ️ <i>These are live positions managed by the QuantView algorithm.</i>"
)


class TelegramCommandHandler:
    """Handles incoming bot commands (/scan, /signal, /news, /account, /positions, /performance, /help, /sync)."""

    def __init__(
        self,
        signal_generator: Optional[SignalGenerator] = None,
        paper_service: Optional[PaperTradingService] = None,
        backtest_service: Optional[BacktestService] = None,
        news_filter: Optional[NewsFilterEngine] = None,
        telegram_client: Optional[BaseTelegramClient] = None,
        market_provider: Optional[BaseMarketDataProvider] = None,
        market_ingestion: Optional[IngestionService] = None,
        news_provider: Optional[BaseNewsProvider] = None,
        news_ingestion: Optional[NewsIngestionService] = None,
    ):
        self.signal_generator = signal_generator or SignalGenerator()
        self.paper_service = paper_service or PaperTradingService()
        self.backtest_service = backtest_service or BacktestService()
        self.news_filter = news_filter or NewsFilterEngine()
        self.telegram_client = telegram_client or get_telegram_client()
        self.market_provider = market_provider or get_market_data_provider(settings.MARKET_DATA_PROVIDER)
        self.market_ingestion = market_ingestion
        self.news_provider = news_provider or get_news_provider(settings.NEWS_PROVIDER)
        self.news_ingestion = news_ingestion
        self.formatter = TelegramMessageFormatter()

    def _supported_symbols(self) -> list[str]:
        """Every symbol addressable by manual commands and the dashboard."""
        return list(dict.fromkeys(
            list(settings.SUPPORTED_SYMBOLS) + list(SUPPORTED_SYMBOLS_ALL)
        ))

    def _normalize_symbol(self, raw: str) -> str:
        """Map 'btcusd', 'BTCUSD', 'BTC/USD' -> canonical 'BTC/USD'.

        Uses the full supported whitelist, not the auto-scan ACTIVE_SYMBOLS
        subset, so a manually requested BTC signal is never called inactive.
        """
        s = raw.upper().replace("%2F", "/").strip()
        flattened = s.replace("/", "")
        for sym in self._supported_symbols():
            if s == sym or flattened == sym.replace("/", ""):
                return sym
        return s

    def _provider_for(self, symbol: str):
        """Route BTC/USD to Binance, every other symbol to its own provider."""
        if self.market_provider is not None:
            return self.market_provider
        return get_provider_for_symbol(symbol)

    async def _technical_analysis(
        self, db: Session, symbol: str, timeframe: str = "1h"
    ) -> dict:
        """Load (and backfill) enough candles, then run the shared calculator."""
        from app.models.candle import Candle  # local import keeps reloads cheap

        tf = str(timeframe or "1h").lower().strip()
        rows = list(
            db.scalars(
                select(Candle)
                .where(Candle.symbol == symbol, Candle.timeframe == tf)
                .order_by(desc(Candle.timestamp))
                .limit(max(MIN_HISTORY_BARS, 250))
            ).all()
        )
        rows.reverse()

        if len(rows) < MIN_HISTORY_BARS:
            ingest_svc = self.market_ingestion or IngestionService(
                provider=self._provider_for(symbol), db=db
            )
            ingest_svc.db = db
            for tf_to_sync in ("15m", "30m", "1h", "4h"):
                try:
                    await ingest_svc.sync_symbol_timeframe(
                        symbol=symbol,
                        timeframe=tf_to_sync,
                        limit=max(MIN_HISTORY_BARS, 250),
                        force_refresh=True,
                    )
                except Exception as exc:
                    logger.warning(
                        "Technical analysis backfill failed for %s [%s]: %s",
                        symbol, tf_to_sync, exc,
                    )
            try:
                db.commit()
            except Exception:
                db.rollback()
            rows = list(
                db.scalars(
                    select(Candle)
                    .where(Candle.symbol == symbol, Candle.timeframe == tf)
                    .order_by(desc(Candle.timestamp))
                    .limit(max(MIN_HISTORY_BARS, 250))
                ).all()
            )
            rows.reverse()

        return calculate_technical_confluence(rows, symbol=symbol, timeframe=tf)

    @staticmethod
    def _build_login_reply(
        db: Session, request: TelegramCommandRequest
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Shared magic-link flow for /login and the /start login deep link."""
        telegram_id = request.user_id
        if telegram_id is None and request.chat_id and str(request.chat_id).lstrip("-").isdigit():
            telegram_id = int(request.chat_id)
        if telegram_id is None:
            return (
                "⚠️ Could not identify your Telegram account. Try again from a private chat.",
                None,
            )
        try:
            login_url, ttl = AuthService().create_login_link(
                db,
                telegram_id,
                username=request.user_name,
                first_name=request.user_first_name,
            )
            reply = (
                "🔐 <b>QuantView Login</b>\n"
                f"Use the button below within {ttl // 60} minutes to open your "
                "authenticated dashboard."
            )
            markup: Optional[Dict[str, Any]] = {
                "inline_keyboard": [[{
                    "text": "🔐 Click here to log in to QuantView",
                    "url": login_url,
                }]]
            }
            return reply, markup
        except Exception as exc:
            logger.error(f"Failed to create login link for {telegram_id}: {exc}")
            return "❌ Could not create a login link. Please try again.", None

    async def handle_command(self, db: Session, request: TelegramCommandRequest) -> TelegramCommandResponse:
        """Parse and execute a Telegram bot command."""
        raw_cmd = request.command.strip()
        parts = raw_cmd.split()
        cmd_name = parts[0].lower().split("@")[0] if parts else "/help"
        reply_markup: Optional[Dict[str, Any]] = None

        # -------------------------------------------------------------
        # 1. Help & Start Menu (/start login is the web deep-link payload)
        # -------------------------------------------------------------
        login_payload = (
            (request.start_parameter or "").strip().lower() == "login"
            or any(part.strip().lower() == "login" for part in parts[1:])
        )
        if cmd_name == "/start" and login_payload:
            reply, reply_markup = self._build_login_reply(db, request)
        elif cmd_name in ("/start", "/help"):
            reply = self.formatter.format_help_menu(active_symbols=list(ACTIVE_SYMBOLS))

        # -------------------------------------------------------------
        # 2. Unified Multi-Timeframe Market Scanner (/scan)
        # -------------------------------------------------------------
        elif cmd_name == "/scan":
            # Manual /scan covers every supported instrument: XAU/USD (SMC)
            # and BTC/USD (momentum). ACTIVE_SYMBOLS only governs the daemon.
            scan_symbols = self._supported_symbols()
            primary_symbol = scan_symbols[0] if scan_symbols else "XAU/USD"

            now_utc = datetime.now(timezone.utc)
            tf_delta_seconds = int(get_timeframe_delta("15m").total_seconds())
            now_ts = int(now_utc.timestamp())
            expected_open_ts = (now_ts // tf_delta_seconds) * tf_delta_seconds - tf_delta_seconds
            expected_open = datetime.fromtimestamp(expected_open_ts, tz=timezone.utc)

            for sym in scan_symbols:
                latest_candle = db.scalars(
                    select(Candle)
                    .where(Candle.symbol == sym, Candle.timeframe == "15m")
                    .order_by(desc(Candle.timestamp))
                    .limit(1)
                ).first()
                if not latest_candle:
                    latest_candle = db.scalars(
                        select(Candle)
                        .where(Candle.symbol == sym)
                        .order_by(desc(Candle.timestamp))
                        .limit(1)
                    ).first()

                is_stale = True
                if latest_candle and latest_candle.timestamp:
                    candle_ts = ensure_utc_datetime(latest_candle.timestamp)
                    is_stale = candle_ts < expected_open

                if not is_stale:
                    continue

                logger.info(
                    f"{sym} candles are STALE on /scan; auto-syncing 15m/30m/1h/4h."
                )
                provider = self._provider_for(sym)
                ingest_svc = self.market_ingestion or IngestionService(provider=provider, db=db)
                ingest_svc.provider = provider
                ingest_svc.db = db
                for tf in ["15m", "30m", "1h", "4h"]:
                    try:
                        await ingest_svc.sync_symbol_timeframe(
                            symbol=sym,
                            timeframe=tf,
                            limit=max(MIN_HISTORY_BARS, 250),
                            force_refresh=True,
                        )
                    except Exception as e:
                        logger.error(f"Auto-refresh sync failed for {sym} [{tf}]: {e}")
                try:
                    db.commit()
                except Exception:
                    db.rollback()

            acc_balance = 10000.0
            try:
                acc_summary = self.paper_service.get_account_summary(db)
                if acc_summary and acc_summary.balance > 0:
                    acc_balance = acc_summary.balance
            except Exception:
                pass

            scan_res = self.signal_generator.scan_unified_all(
                db=db,
                symbols=scan_symbols,
                account_balance=acc_balance,
                risk_percent=settings.MAX_RISK_PERCENT,
                persist_qualified=True,
            )
            scan_res = filter_consumed_scan_results(db, scan_res)
            reply = self.formatter.format_market_scan_summary(scan_res)

            # Add the shared indicator analysis so /scan is never just a list
            # of nulls when the dashboard and bot disagree.
            try:
                analysis = await self._technical_analysis(db, primary_symbol, "1h")
                reply += "\n\n" + self.formatter.format_technical_analysis(analysis)
            except Exception as exc:
                logger.warning("Could not attach technical analysis to /scan: %s", exc)

        # -------------------------------------------------------------
        # 3. Single Pair Unified Signal Evaluation (/signal <symbol>)
        # -------------------------------------------------------------
        elif cmd_name == "/signal":
            if len(parts) < 2:
                reply = "⚠️ <b>Usage:</b> <code>/signal &lt;symbol&gt;</code>\n<i>Example:</i> <code>/signal XAU/USD</code>"
            else:
                sym = self._normalize_symbol(parts[1])

                supported = self._supported_symbols()
                if sym not in supported:
                    sym_esc = self.formatter.escape_html(sym)
                    supported_esc = ", ".join(f"<code>{s}</code>" for s in supported)
                    reply = (
                        f"⚠️ <b>Unsupported Pair</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"<code>{sym_esc}</code> is not supported.\n"
                        f"Supported instruments: {supported_esc}."
                    )
                else:
                    # 1. Provider <-> DB Synchronization: fetch at least 210 bars
                    # so EMA50/EMA200 and ADX(14) are never computed on a
                    # too-short (NaN-producing) window. BTC routes to Binance.
                    ingest_svc = self.market_ingestion or IngestionService(
                        provider=self._provider_for(sym), db=db
                    )
                    ingest_svc.provider = self._provider_for(sym)
                    ingest_svc.db = db
                    for tf in ["1h", "4h", "30m", "15m"]:
                        try:
                            await ingest_svc.sync_symbol_timeframe(
                                symbol=sym,
                                timeframe=tf,
                                limit=max(MIN_HISTORY_BARS, 250),
                                force_refresh=True,
                            )
                        except Exception as e:
                            logger.warning(f"Failed to refresh market data for {sym} [{tf}] via provider: {e}")

                    # 2. Evaluate Unified Multi-Timeframe Signal
                    acc_balance = 10000.0
                    try:
                        acc_summary = self.paper_service.get_account_summary(db)
                        if acc_summary and acc_summary.balance > 0:
                            acc_balance = acc_summary.balance
                    except Exception:
                        pass

                    scan_res = self.signal_generator.scan_unified(
                        db=db,
                        symbol=sym,
                        account_balance=acc_balance,
                        risk_percent=settings.MAX_RISK_PERCENT,
                        persist_qualified=True,
                    )

                    # A consumed setup is not an active alert, even if the
                    # evaluator just re-produced the same candle again.
                    if signal_lifecycle.is_consumed_scan_result(db, scan_res):
                        scan_res.is_actionable = False
                        scan_res.signal = None

                    if scan_res.is_actionable and scan_res.signal:
                        reply = self.formatter.format_signal_alert(scan_res.signal)
                        thesis = (
                            (scan_res.signal.reasons[0] if scan_res.signal.reasons else None)
                            or getattr(scan_res.signal, "ai_reasoning", None)
                        )
                    else:
                        sym_code = self.formatter.escape_html(sym)
                        htf_txt = self.formatter.escape_html(scan_res.htf_trend or "NEUTRAL")
                        score_txt = f"{scan_res.setup_score:.0f}/100"
                        align_txt = f" • Alignment: <code>{self.formatter.escape_html(scan_res.trend_alignment)}</code>" if scan_res.trend_alignment else ""
                        reasons_lines = "\n".join([f"  • {self.formatter.escape_html(r)}" for r in scan_res.reasons[:4]])
                        is_btc_signal = sym == "BTC/USD"
                        strategy_label = "BTC Momentum" if is_btc_signal else "Strategy A (SMC Sniper)"
                        symbol_floor = 85.0 if is_btc_signal else float(settings.MIN_SETUP_SCORE)
                        reply = (
                            f"⚪ <b>UNIFIED SIGNAL STATUS: WAIT</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"📊 <b>Pair:</b> <code>{sym_code}</code> [{scan_res.timeframe}]\n"
                            f"🧠 <b>Strategy:</b> <code>{strategy_label}</code>\n"
                            f"📈 <b>HTF Context:</b> <code>{htf_txt}</code>{align_txt}\n"
                            f"⭐ <b>Setup Score:</b> <code>{score_txt}</code> (Min: <code>{symbol_floor:.0f}</code>)\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"💡 <b>Current Market Analysis:</b>\n"
                            f"{reasons_lines}\n\n"
                            f"⚠️ <i>Awaiting confirmation before generating actionable entry.</i>"
                        )
                        thesis = scan_res.reasons[0] if scan_res.reasons else None

                    # Always attach the shared indicator analysis — WAIT and
                    # actionable messages must show the same EMA/RSI/ADX/score
                    # as the dashboard, with safe N/A fallbacks.
                    try:
                        analysis = await self._technical_analysis(db, sym, "1h")
                        reply += "\n\n" + self.formatter.format_technical_analysis(
                            analysis, thesis=thesis
                        )
                    except Exception as exc:
                        logger.warning(
                            "Could not attach technical analysis to /signal %s: %s",
                            sym, exc,
                        )

        # -------------------------------------------------------------
        # 4. Economic News Calendar (/news)
        # -------------------------------------------------------------
        elif cmd_name == "/news":
            now = datetime.now(timezone.utc)
            news_ingest = self.news_ingestion or NewsIngestionService(
                provider=self.news_provider, db=db
            )
            news_ingest.db = db

            # DB-First Check: Only invoke external provider sync if database is empty or cache is stale (>2 hours)
            is_cache_fresh = news_ingest.is_calendar_cache_fresh(reference_time=now)
            live_failed = False

            if not is_cache_fresh and self.news_provider:
                try:
                    report = await news_ingest.sync_calendar(force_refresh=True)
                    if report.status in ("UNAVAILABLE", "ERROR") or (getattr(self.news_provider, "is_live_provider", False) and report.fetched_count == 0):
                        live_failed = True
                except Exception as e:
                    logger.warning(f"Error syncing economic news in /news command: {e}")
                    live_failed = True

            events = list(
                db.scalars(
                    select(NewsEvent)
                    .where(NewsEvent.scheduled_time >= (now - timedelta(minutes=15)))
                    .order_by(NewsEvent.scheduled_time.asc())
                    .limit(5)
                ).all()
            )
            event_resps = [NewsEventResponse.model_validate(e) for e in events]

            if not event_resps and (live_failed or (getattr(self.news_provider, "is_live_provider", False) and not is_cache_fresh)):
                reply = self.formatter.format_news_unavailable_alert()
            else:
                reply = self.formatter.format_economic_news_alert(event_resps)

        # -------------------------------------------------------------
        # 5. Virtual Paper Account (/account, /paper)
        # -------------------------------------------------------------
        elif cmd_name in ("/account", "/paper"):
            acc = self.paper_service.get_account_summary(db)
            perf = self.paper_service.get_portfolio_performance(db)
            reply = self.formatter.format_portfolio_summary(acc, perf)

        # -------------------------------------------------------------
        # 6. Active Virtual Positions (/positions)
        # -------------------------------------------------------------
        elif cmd_name == "/positions":
            positions = self.paper_service.get_positions(db)
            if not positions:
                reply = (
                    "💼 <b>No open or pending Master Fund positions currently.</b>\n"
                    f"{MASTER_FUND_POSITIONS_FOOTER}"
                )
            else:
                lines = [
                    f"📡 <b>MASTER FUND ACTIVE POSITIONS ({len(positions)})</b> 📡",
                    "━━━━━━━━━━━━━━━━━━━━",
                ]
                for p in positions:
                    dir_icon = "🟢 BUY" if p.direction == SignalDirection.BUY else "🔴 SELL"
                    pnl_str = f"+${p.unrealized_pnl:,.2f}" if p.unrealized_pnl >= 0 else f"-${abs(p.unrealized_pnl):,.2f}"
                    entry_f = format_price(p.entry_price, p.symbol)
                    curr_f = format_price(p.current_price, p.symbol)
                    sl_f = format_price(p.stop_loss, p.symbol)
                    tp1_f = format_price(p.take_profit_1, p.symbol)
                    lines.append(
                        f"• <b>{self.formatter.escape_html(p.symbol)}</b> ({dir_icon} <code>{p.remaining_position_size} Lots</code>)\n"
                        f"  Entry: <code>{entry_f}</code> | Current: <code>{curr_f}</code> | PnL: <code>{pnl_str}</code>\n"
                        f"  SL: <code>{sl_f}</code> | TP1: <code>{tp1_f}</code>"
                    )
                lines.extend([
                    "━━━━━━━━━━━━━━━━━━━━",
                    MASTER_FUND_POSITIONS_FOOTER,
                ])
                reply = "\n".join(lines)

        # -------------------------------------------------------------
        # 7. Portfolio Performance Statistics (/performance)
        # -------------------------------------------------------------
        elif cmd_name == "/performance":
            perf = self.paper_service.get_portfolio_performance(db)
            reply = (
                f"🏛️ <b>QUANTVIEW MASTER FUND</b> 🏛️\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💵 <b>Current Balance:</b> <code>${perf.current_balance:,.2f}</code>\n"
                f"📈 <b>Total Return:</b> <code>{perf.total_return_pct:>+6.2f}%</code>\n"
                f"📊 <b>Total Trades:</b> <code>{perf.total_trades}</code> ({perf.winning_trades}W / {perf.losing_trades}L)\n"
                f"🎯 <b>Win Rate:</b> <code>{perf.win_rate:.1f}%</code>\n"
                f"💰 <b>Profit Factor:</b> <code>{perf.profit_factor:.2f}</code>\n"
                f"💵 <b>Average Win:</b> <code>${perf.average_win:,.2f}</code>\n"
                f"🛑 <b>Average Loss:</b> <code>${perf.average_loss:,.2f}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{MASTER_FUND_FOOTER}"
            )

        # -------------------------------------------------------------
        # 8. Quick Strategy Backtest (/backtest <symbol>)
        # -------------------------------------------------------------
        elif cmd_name == "/backtest":
            sym = self._normalize_symbol(parts[1]) if len(parts) > 1 else (ACTIVE_SYMBOLS[0] if ACTIVE_SYMBOLS else "XAU/USD")
            candles = list(
                db.scalars(
                    select(Candle)
                    .where(Candle.symbol == sym, Candle.timeframe == "1h")
                    .order_by(Candle.timestamp.asc())
                ).all()
            )
            if len(candles) < 30:
                reply = f"❌ Insufficient candle data in database to backtest <code>{self.formatter.escape_html(sym)}</code>."
            else:
                bt_res = self.backtest_service.engine.run_simulation(
                    candles=candles,
                    symbol=sym,
                    timeframe="1h",
                )
                m = bt_res.metrics
                sym_escaped = self.formatter.escape_html(sym)
                reply = (
                    f"📈 <b>HISTORICAL STRATEGY BACKTEST: {sym_escaped} [1h]</b> 📈\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 <b>Total Trades:</b> <code>{m.total_trades}</code> ({m.winning_trades}W / {m.losing_trades}L)\n"
                    f"🎯 <b>Win Rate:</b> <code>{m.win_rate:.1f}%</code>\n"
                    f"💰 <b>Profit Factor:</b> <code>{m.profit_factor:.2f}</code>\n"
                    f"💵 <b>Net PnL:</b> <code>${m.total_pnl:>+,.2f}</code> (<code>{m.total_pnl_percent:>+6.2f}%</code>)\n"
                    f"📉 <b>Max Drawdown:</b> <code>{m.max_drawdown_pct:.2f}%</code> (<code>${m.max_drawdown_usd:,.2f}</code>)\n"
                    f"⭐ <b>Sharpe Ratio:</b> <code>{m.sharpe_ratio:.2f}</code> | <b>Calmar:</b> <code>{m.calmar_ratio:.2f}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )

        # -------------------------------------------------------------
        # 9. Force Fresh Data Sync (/sync)
        # -------------------------------------------------------------
        elif cmd_name == "/sync":
            reply = "🔄 <b>FORCING FRESH DATA SYNC...</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            
            provider = self.market_provider or get_market_data_provider(settings.MARKET_DATA_PROVIDER)
            ingest_svc = self.market_ingestion or IngestionService(provider=provider, db=db)
            ingest_svc.db = db

            synced_count = 0
            target_timeframes = ["15m", "30m", "1h"] 
            sync_symbols = list(ACTIVE_SYMBOLS)

            for sym in sync_symbols:
                for tf in target_timeframes:
                    try:
                        await ingest_svc.sync_symbol_timeframe(
                            symbol=sym, timeframe=tf, limit=100, force_refresh=True
                        )
                        synced_count += 1
                    except Exception as e:
                        logger.error(f"Manual sync failed for {sym} [{tf}]: {e}")

            try:
                db.commit()
            except Exception:
                db.rollback()

            reply += f"✅ <b>Sync Complete!</b>\n"
            reply += f"📊 <b>Pairs Synced:</b> {len(sync_symbols)}\n"
            reply += f"⏱ <b>Timeframes:</b> {', '.join(target_timeframes)}\n"
            reply += f"🔄 <b>Total API Fetches:</b> {synced_count}\n"
            reply += "━━━━━━━━━━━━━━━━━━━━\n"
            reply += "<i>Database updated. Staleness blocks cleared. Ready to scan!</i>"

        # -------------------------------------------------------------
        # 10. Magic-link dashboard login
        # -------------------------------------------------------------
        elif cmd_name == "/login":
            reply, reply_markup = self._build_login_reply(db, request)

        # -------------------------------------------------------------
        # 11. Fallback for Unknown Commands (MUST BE LAST)
        # -------------------------------------------------------------
        else:
            raw_escaped = self.formatter.escape_html(raw_cmd)
            reply = f"❓ Unknown command <code>{raw_escaped}</code>. Type <code>/help</code> for available options."

        if request.chat_id:
            await self.telegram_client.send_message(
                text=reply,
                chat_id=request.chat_id,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )

        return TelegramCommandResponse(
            command=raw_cmd,
            reply_text=reply,
            handled_successfully=True,
            chat_id=request.chat_id,
        )