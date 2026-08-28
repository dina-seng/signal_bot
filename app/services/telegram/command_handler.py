"""Interactive Telegram Bot Commands Processor."""

from datetime import datetime, timezone
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
from app.services.news import NewsFilterEngine
from app.services.paper_trading import PaperTradingService
from app.services.signals import SignalGenerator
from app.services.telegram.client import BaseTelegramClient, get_telegram_client
from app.services.telegram.message_formatter import TelegramMessageFormatter


class TelegramCommandHandler:
    """Handles incoming bot commands (/scan, /signal, /news, /account, /positions, /performance, /help)."""

    def __init__(
        self,
        signal_generator: Optional[SignalGenerator] = None,
        paper_service: Optional[PaperTradingService] = None,
        backtest_service: Optional[BacktestService] = None,
        news_filter: Optional[NewsFilterEngine] = None,
        telegram_client: Optional[BaseTelegramClient] = None,
    ):
        self.signal_generator = signal_generator or SignalGenerator()
        self.paper_service = paper_service or PaperTradingService()
        self.backtest_service = backtest_service or BacktestService()
        self.news_filter = news_filter or NewsFilterEngine()
        self.telegram_client = telegram_client or get_telegram_client()
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
        # 2. Market Scanner (/scan)
        # -------------------------------------------------------------
        elif cmd_name == "/scan":
            scan_res = self.signal_generator.scan_all_symbols(
                db=db,
                symbols=settings.SUPPORTED_SYMBOLS,
                timeframe="1h",
                account_balance=10000.0,
                risk_percent=0.5,
                persist_qualified=True,
            )
            reply = self.formatter.format_market_scan_summary(scan_res)

        # -------------------------------------------------------------
        # 3. Single Pair Deep Signal Evaluation (/signal <symbol>)
        # -------------------------------------------------------------
        elif cmd_name == "/signal":
            if len(parts) < 2:
                reply = "⚠️ *Usage:* `/signal <symbol>`\n_Example:_ `/signal EUR/USD` or `/signal XAU/USD`"
            else:
                sym = self._normalize_symbol(parts[1])
                c1h = list(
                    db.scalars(
                        select(Candle)
                        .where(Candle.symbol == sym, Candle.timeframe == "1h")
                        .order_by(desc(Candle.timestamp))
                        .limit(200)
                    ).all()
                )
                c1h.reverse()

                if not c1h:
                    reply = f"❌ No candle data found in database for `{sym}`. Ingest data first."
                else:
                    c4h = list(
                        db.scalars(
                            select(Candle)
                            .where(Candle.symbol == sym, Candle.timeframe == "4h")
                            .order_by(desc(Candle.timestamp))
                            .limit(100)
                        ).all()
                    )
                    c4h.reverse()

                    c15m = list(
                        db.scalars(
                            select(Candle)
                            .where(Candle.symbol == sym, Candle.timeframe == "15m")
                            .order_by(desc(Candle.timestamp))
                            .limit(100)
                        ).all()
                    )
                    c15m.reverse()

                    news_check = self.news_filter.check_from_db(db=db, symbol=sym, target_time=datetime.now(timezone.utc))

                    sig = self.signal_generator.evaluate_market_signal(
                        candles_primary=c1h,
                        symbol=sym,
                        timeframe="1h",
                        candles_4h=c4h if c4h else None,
                        candles_15m=c15m if c15m else None,
                        news_check=news_check,
                    )

                    if sig.direction in (SignalDirection.BUY, SignalDirection.SELL):
                        reply = self.formatter.format_signal_alert(sig)
                    else:
                        sym_code = self.formatter.escape_code(sig.symbol)
                        reply = (
                            f"⚪ *MARKET STATUS: WAIT (NO ACTIVE SETUP)*\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"📊 *Pair:* `{sym_code}` (1h)\n"
                            f"⭐ *Setup Score:* `{sig.setup_score:.1f} / 100` (Min required: `{settings.MIN_SETUP_SCORE:.1f}`)\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"💡 *Current Market Analysis:*\n"
                        )
                        for r in sig.reasons:
                            reply += f"  • {self.formatter.escape_markdown(r)}\n"

        # -------------------------------------------------------------
        # 4. Economic News Calendar (/news)
        # -------------------------------------------------------------
        elif cmd_name == "/news":
            now = datetime.now(timezone.utc)
            events = list(
                db.scalars(
                    select(NewsEvent)
                    .where(NewsEvent.scheduled_time >= now)
                    .order_by(NewsEvent.scheduled_time.asc())
                    .limit(5)
                ).all()
            )
            event_resps = [NewsEventResponse.model_validate(e) for e in events]
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
                    dir_icon = "🟢 BUY" if p.direction == SignalDirection.BUY else "🔴 SELL"
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
                f"📊 *Total Trades:* `{perf.total_trades}` ({perf.winning_trades}W / {perf.losing_trades}L)\n"
                f"🎯 *Win Rate:* `{perf.win_rate:.1f}%`\n"
                f"💰 *Profit Factor:* `{perf.profit_factor:.2f}`\n"
                f"💵 *Average Win:* `${perf.average_win:,.2f}`\n"
                f"🛑 *Average Loss:* `${perf.average_loss:,.2f}`\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

        # -------------------------------------------------------------
        # 8. Quick Strategy Backtest (/backtest <symbol>)
        # -------------------------------------------------------------
        elif cmd_name == "/backtest":
            sym = self._normalize_symbol(parts[1]) if len(parts) > 1 else "EUR/USD"
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
                    f"💵 *Net PnL:* `${m.total_pnl:>+,.2f}` (`{m.total_pnl_percent:>+6.2f}%`)\n"
                    f"📉 *Max Drawdown:* `{m.max_drawdown_pct:.2f}%` (`${m.max_drawdown_usd:,.2f}`)\n"
                    f"⭐ *Sharpe Ratio:* `{m.sharpe_ratio:.2f}` | *Calmar:* `{m.calmar_ratio:.2f}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )

        else:
            raw_escaped = self.formatter.escape_code(raw_cmd)
            reply = f"❓ Unknown command `{raw_escaped}`. Type `/help` for available options."

        # Send response to chat if requested
        if request.chat_id:
            await self.telegram_client.send_message(text=reply, chat_id=request.chat_id)

        return TelegramCommandResponse(
            command=raw_cmd,
            reply_text=reply,
            handled_successfully=True,
            chat_id=request.chat_id,
        )
