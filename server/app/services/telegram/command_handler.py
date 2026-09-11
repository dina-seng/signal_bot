"""Interactive Telegram Bot Commands Processor."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.config import settings
from app.core.logging import logger
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
    filter_closed_candles,
    get_market_data_provider,
    log_latest_candle,
)
from app.services.news import (
    BaseNewsProvider,
    NewsFilterEngine,
    NewsIngestionService,
    get_news_provider,
)
from app.services.paper_trading import PaperTradingService
from app.services.signals import SignalGenerator
from app.services.telegram.client import BaseTelegramClient, get_telegram_client
from app.services.telegram.message_formatter import TelegramMessageFormatter


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

    def _normalize_symbol(self, raw: str) -> str:
        """Normalize currency symbol string."""
        s = raw.upper().replace("%2F", "/").strip()
        for sym in settings.SUPPORTED_SYMBOLS:
            if sym.replace("/", "") == s.replace("/", ""):
                return sym
        return s

    async def handle_command(self, db: Session, request: TelegramCommandRequest) -> TelegramCommandResponse:
        """Parse and execute a Telegram bot command."""
        raw_cmd = request.command.strip()
        parts = raw_cmd.split()
        cmd_name = parts[0].lower() if parts else "/help"

        # -------------------------------------------------------------
        # 1. Help & Start Menu
        # -------------------------------------------------------------
        if cmd_name in ("/start", "/help"):
            reply = self.formatter.format_help_menu()

        # -------------------------------------------------------------
        # 2. Unified Multi-Timeframe Market Scanner (/scan)
        # -------------------------------------------------------------
        elif cmd_name == "/scan":
            scan_res = self.signal_generator.scan_unified_all(
                db=db,
                symbols=settings.SUPPORTED_SYMBOLS,
                account_balance=10000.0,
                risk_percent=0.5,
                persist_qualified=True,
            )
            reply = self.formatter.format_market_scan_summary(scan_res)

        # -------------------------------------------------------------
        # 3. Single Pair Unified Signal Evaluation (/signal <symbol>)
        # -------------------------------------------------------------
        elif cmd_name == "/signal":
            if len(parts) < 2:
                reply = "⚠️ *Usage:* `/signal <symbol>`\n_Example:_ `/signal XAU/USD` or `/signal USD/JPY`"
            else:
                sym = self._normalize_symbol(parts[1])

                # 1. Provider <-> DB Synchronization: Refresh fresh candle data from provider
                if self.market_provider:
                    ingest_svc = self.market_ingestion or IngestionService(
                        provider=self.market_provider, db=db
                    )
                    ingest_svc.db = db
                    for tf in ["1h", "4h", "30m", "15m"]:
                        try:
                            await ingest_svc.sync_symbol_timeframe(symbol=sym, timeframe=tf, limit=100)
                        except Exception as e:
                            logger.warning(f"Failed to refresh market data for {sym} [{tf}] via provider: {e}")

                # 2. Evaluate Unified Multi-Timeframe Signal
                scan_res = self.signal_generator.scan_unified(
                    db=db,
                    symbol=sym,
                    account_balance=10000.0,
                    risk_percent=0.5,
                    persist_qualified=True,
                )

                if scan_res.is_actionable and scan_res.signal:
                    reply = self.formatter.format_signal_alert(scan_res.signal)
                else:
                    sym_code = self.formatter.escape_code(sym)
                    htf_txt = self.formatter.escape_code(scan_res.htf_trend or "NEUTRAL")
                    score_txt = f"{scan_res.setup_score:.0f}/100"
                    align_txt = f" • Alignment: `{scan_res.trend_alignment}`" if scan_res.trend_alignment else ""
                    reasons_lines = "\n".join([f"  • {self.formatter.escape_markdown(r)}" for r in scan_res.reasons[:4]])
                    reply = (
                        f"⚪ *UNIFIED SIGNAL STATUS: WAIT*\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"📊 *Pair:* `{sym_code}` [{scan_res.timeframe}]\n"
                        f"📈 *1H Context:* `{htf_txt}`{align_txt}\n"
                        f"⭐ *Confluence Score:* `{score_txt}` (Min: `{settings.MIN_SETUP_SCORE:.0f}`)\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"💡 *Current Market Analysis:*\n"
                        f"{reasons_lines}\n\n"
                        f"⚠️ _Awaiting 15m/30m/1H confirmation before generating actionable entry._"
                    )

        # -------------------------------------------------------------
        # 4. Economic News Calendar (/news)
        # -------------------------------------------------------------
        elif cmd_name == "/news":
            # 1. Attempt on-demand refresh from configured news provider
            live_failed = False
            if self.news_provider:
                news_ingest = self.news_ingestion or NewsIngestionService(
                    provider=self.news_provider, db=db
                )
                news_ingest.db = db
                try:
                    report = await news_ingest.sync_calendar()
                    if report.status in ("UNAVAILABLE", "ERROR") or (getattr(self.news_provider, "is_live_provider", False) and report.fetched_count == 0):
                        live_failed = True
                except Exception as e:
                    logger.warning(f"Error syncing economic news in /news command: {e}")
                    live_failed = True

            now = datetime.now(timezone.utc)
            events = list(
                db.scalars(
                    select(NewsEvent)
                    .where(NewsEvent.scheduled_time >= (now - timedelta(minutes=15)))
                    .order_by(NewsEvent.scheduled_time.asc())
                    .limit(5)
                ).all()
            )
            event_resps = [NewsEventResponse.model_validate(e) for e in events]

            if not event_resps and (live_failed or getattr(self.news_provider, "is_live_provider", False)):
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
                reply = "💼 *No open or pending paper trading positions currently.*"
            else:
                lines = [
                    f"📊 *ACTIVE PAPER POSITIONS ({len(positions)})* 📊",
                    f"━━━━━━━━━━━━━━━━━━━━",
                ]
                for p in positions:
                    dir_icon = "🟢 BUY" if p.direction == SignalDirection.BUY else " SELL"
                    pnl_str = f"+${p.unrealized_pnl:,.2f}" if p.unrealized_pnl >= 0 else f"-${abs(p.unrealized_pnl):,.2f}"
                    lines.append(
                        f"• *{self.formatter.escape_markdown(p.symbol)}* ({dir_icon} `{p.remaining_position_size} Lots`)\n"
                        f"  Entry: `{p.entry_price:.5f}` | Current: `{p.current_price:.5f}` | PnL: `{pnl_str}`\n"
                        f"  SL: `{p.stop_loss:.5f}` | TP1: `{p.take_profit_1:.5f}`"
                    )
                reply = "\n".join(lines)

        # -------------------------------------------------------------
        # 7. Portfolio Performance Statistics (/performance)
        # -------------------------------------------------------------
        elif cmd_name == "/performance":
            perf = self.paper_service.get_portfolio_performance(db)
            reply = (
                f"🏆 *VIRTUAL TRADING PERFORMANCE* 🏆\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💵 *Current Balance:* `${perf.current_balance:,.2f}`\n"
                f"📈 *Total Return:* `{perf.total_return_pct:>+6.2f}%`\n"
                f" *Total Trades:* `{perf.total_trades}` ({perf.winning_trades}W / {perf.losing_trades}L)\n"
                f" *Win Rate:* `{perf.win_rate:.1f}%`\n"
                f"💰 *Profit Factor:* `{perf.profit_factor:.2f}`\n"
                f"💵 *Average Win:* `${perf.average_win:,.2f}`\n"
                f"🛑 *Average Loss:* `${perf.average_loss:,.2f}`\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

        # -------------------------------------------------------------
        # 8. Quick Strategy Backtest (/backtest <symbol>)
        # -------------------------------------------------------------
        elif cmd_name == "/backtest":
            sym = self._normalize_symbol(parts[1]) if len(parts) > 1 else "XAU/USD"
            candles = list(
                db.scalars(
                    select(Candle)
                    .where(Candle.symbol == sym, Candle.timeframe == "1h")
                    .order_by(Candle.timestamp.asc())
                ).all()
            )
            if len(candles) < 30:
                reply = f"❌ Insufficient candle data in database to backtest `{self.formatter.escape_code(sym)}`."
            else:
                bt_res = self.backtest_service.engine.run_simulation(
                    candles=candles,
                    symbol=sym,
                    timeframe="1h",
                )
                m = bt_res.metrics
                sym_escaped = self.formatter.escape_markdown(sym)
                reply = (
                    f"📈 *HISTORICAL STRATEGY BACKTEST: {sym_escaped} [1h]* 📈\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 *Total Trades:* `{m.total_trades}` ({m.winning_trades}W / {m.losing_trades}L)\n"
                    f"🎯 *Win Rate:* `{m.win_rate:.1f}%`\n"
                    f"💰 *Profit Factor:* `{m.profit_factor:.2f}`\n"
                    f" *Net PnL:* `${m.total_pnl:>+,.2f}` (`{m.total_pnl_percent:>+6.2f}%`)\n"
                    f"📉 *Max Drawdown:* `{m.max_drawdown_pct:.2f}%` (`${m.max_drawdown_usd:,.2f}`)\n"
                    f"⭐ *Sharpe Ratio:* `{m.sharpe_ratio:.2f}` | *Calmar:* `{m.calmar_ratio:.2f}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )

        # -------------------------------------------------------------
        # 9. Force Fresh Data Sync (/sync)
        # -------------------------------------------------------------
        elif cmd_name == "/sync":
            reply = "🔄 *FORCING FRESH DATA SYNC...*\n━━━━━━━━━━━━━━━━━━━━\n"
            
            provider = self.market_provider or get_market_data_provider(settings.MARKET_DATA_PROVIDER)
            ingest_svc = self.market_ingestion or IngestionService(provider=provider, db=db)
            ingest_svc.db = db

            synced_count = 0
            target_timeframes = ["15m", "30m", "1h"] 

            for sym in settings.SUPPORTED_SYMBOLS:
                for tf in target_timeframes:
                    try:
                        await ingest_svc.sync_symbol_timeframe(symbol=sym, timeframe=tf, limit=100)
                        synced_count += 1
                    except Exception as e:
                        logger.error(f"Manual sync failed for {sym} [{tf}]: {e}")

            reply += f"✅ *Sync Complete!*\n"
            reply += f"📊 *Pairs Synced:* {len(settings.SUPPORTED_SYMBOLS)}\n"
            reply += f"⏱ *Timeframes:* {', '.join(target_timeframes)}\n"
            reply += f"🔄 *Total API Fetches:* {synced_count}\n"
            reply += "━━━━━━━━━━━━━━━━━━━━\n"
            reply += "_Database updated. Staleness blocks cleared. Ready to scan!_"

        # -------------------------------------------------------------
        # 10. Fallback for Unknown Commands (MUST BE LAST)
        # -------------------------------------------------------------
        else:
            raw_escaped = self.formatter.escape_code(raw_cmd)
            reply = f"❓ Unknown command `{raw_escaped}`. Type `/help` for available options."


        if request.chat_id:
            await self.telegram_client.send_message(text=reply, chat_id=request.chat_id)

        return TelegramCommandResponse(
            command=raw_cmd,
            reply_text=reply,
            handled_successfully=True,
            chat_id=request.chat_id,
        )