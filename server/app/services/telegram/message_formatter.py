"""Telegram Message Formatting with rich emojis, entity sanitization, and Markdown/HTML styling."""

from datetime import datetime, timezone
import html
from typing import Any, List, Optional

from app.schemas.news import NewsEventResponse
from app.schemas.paper_trading import PaperPortfolioPerformance, VirtualAccountResponse
from app.schemas.signal import MarketScanResponse, SignalDirection, SignalResponse


class TelegramMessageFormatter:
    """Formats market signals, position alerts, news summaries, and portfolio updates for Telegram.
    
    Provides sanitization and escaping for dynamic user/market values to prevent Telegram entity parsing errors (400).
    """

    @staticmethod
    def escape_markdown(text: Any, version: int = 1) -> str:
        """Sanitize/escape dynamic strings to prevent Telegram Markdown parsing errors."""
        if text is None:
            return ""
        s = str(text)
        if version == 2:
            escape_chars = r"\_*[]()~`>#+-=|{}.!"
            return "".join(f"\\{c}" if c in escape_chars else c for c in s)
        else:
            escape_chars = ("\\", "_", "*", "`", "[", "]")
            for c in escape_chars:
                s = s.replace(c, f"\\{c}")
            return s

    @staticmethod
    def escape_markdown_v2(text: Any) -> str:
        """Convenience method for MarkdownV2 escaping."""
        return TelegramMessageFormatter.escape_markdown(text, version=2)

    @staticmethod
    def escape_code(text: Any) -> str:
        """Sanitize dynamic values placed inside single-backtick inline code spans (`...`)."""
        if text is None:
            return ""
        return str(text).replace("`", "'")

    @staticmethod
    def escape_html(text: Any) -> str:
        """Escape dynamic strings for Telegram HTML parse_mode (&, <, >)."""
        if text is None:
            return ""
        return html.escape(str(text), quote=False)

    @staticmethod
    def format_price(price: Optional[float], symbol: str) -> str:
        """Format price string with appropriate decimal precision per instrument."""
        if price is None:
            return "N/A"
        sym = symbol.upper().replace("/", "")
        if "XAU" in sym or "GOLD" in sym:
            return f"{price:.2f}"
        elif "JPY" in sym:
            return f"{price:.3f}"
        return f"{price:.5f}"

    @staticmethod
    def calculate_pips(entry: float, target: float, symbol: str) -> float:
        """Calculate standard pip distance adjusted for asset class."""
        diff = abs(entry - target)
        sym = symbol.upper().replace("/", "")
        if "XAU" in sym or "GOLD" in sym:
            # For Gold: 1 pip = $0.10 (10 cents)
            return round(diff / 0.10, 1)
        elif "JPY" in sym:
            # For JPY: 1 pip = 0.01
            return round(diff / 0.01, 1)
        else:
            # Standard Forex: 1 pip = 0.0001
            return round(diff / 0.0001, 1)

    @classmethod
    def format_signal_alert(cls, sig: SignalResponse) -> str:
        """Format an actionable trade setup alert."""
        dir_emoji = "🟢 *STRONG BUY (LONG)*" if sig.direction == SignalDirection.BUY else "🔴 *STRONG SELL (SHORT)*"
        rp = sig.risk_parameters

        sym_clean = sig.symbol
        sym = cls.escape_code(sym_clean)
        tf = cls.escape_code(sig.timeframe)
        score_str = f"{sig.setup_score:.1f}"

        lines = [
            f"⚡ *NEW FOREX TRADE SIGNAL* ⚡",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"📊 *Instrument:* `{sym}`",
            f"⏱ *Timeframe:* `{tf}`",
            f"🎯 *Direction:* {dir_emoji}",
            f"⭐ *Confluence Score:* `{score_str} / 100`",
        ]

        if getattr(sig, "trend_alignment", None):
            align_icon = "✅" if sig.trend_alignment == "TREND FOLLOWING" else "⚠️"
            lines.append(f"🧭 *Trend Alignment:* {align_icon} `{cls.escape_code(sig.trend_alignment)}`")

        if getattr(sig, "htf_trend", None):
            lines.append(f"📈 *1H Context:* `{cls.escape_code(sig.htf_trend)}`")

        lines.append(f"━━━━━━━━━━━━━━━━━━━━")

        if sig.entry_price is not None:
            formatted_entry = cls.format_price(sig.entry_price, sym_clean)
            lines.append(f"📍 *Entry Price:* `{formatted_entry}`")

        if sig.stop_loss is not None and sig.entry_price is not None:
            formatted_sl = cls.format_price(sig.stop_loss, sym_clean)
            sl_pips = cls.calculate_pips(sig.entry_price, sig.stop_loss, sym_clean)
            lines.append(f"🛑 *Stop Loss:* `{formatted_sl}` ({sl_pips:.1f} pips)")

        if sig.take_profit_1 is not None and sig.entry_price is not None:
            formatted_tp1 = cls.format_price(sig.take_profit_1, sym_clean)
            tp1_pips = cls.calculate_pips(sig.entry_price, sig.take_profit_1, sym_clean)
            lines.append(f"🎯 *Take Profit 1 (TP1):* `{formatted_tp1}` ({tp1_pips:.1f} pips | 2.0 R:R)")

        if sig.take_profit_2 is not None and sig.entry_price is not None:
            formatted_tp2 = cls.format_price(sig.take_profit_2, sym_clean)
            tp2_pips = cls.calculate_pips(sig.entry_price, sig.take_profit_2, sym_clean)
            lines.append(f"🏆 *Take Profit 2 (TP2):* `{formatted_tp2}` ({tp2_pips:.1f} pips | 3.0 R:R)")

        if rp:
            lines.extend([
                f"━━━━━━━━━━━━━━━━━━━━",
                f"💼 *Risk Management (0.5% Rule):*",
                f"  • *Suggested Sizing:* `{rp.suggested_lot_size:.2f} Standard Lots`",
                f"  • *Risk Allocation:* `${rp.risk_amount_usd:,.2f}` on `${rp.account_balance:,.0f}` balance",
            ])

        if sig.score_breakdown:
            bd = sig.score_breakdown
            lines.extend([
                f"━━━━━━━━━━━━━━━━━━━━",
                f"🏛 *Pillar Breakdown:*",
                f"  • Structure & MTF: `{bd.structure_score:.0f}/30`",
                f"  • Liquidity & S/R: `{bd.liquidity_score:.0f}/25`",
                f"  • Indicators: `{bd.indicators_score:.0f}/25`",
                f"  • Price Action: `{bd.price_action_score:.0f}/20`",
            ])

        if sig.reasons:
            lines.append(f"━━━━━━━━━━━━━━━━━━━━\n💡 *Key Confluence Catalysts:*")
            for r in sig.reasons[:4]:
                lines.append(f"  ✓ {cls.escape_markdown(r)}")

        lines.extend([
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🛡 *News Blackout Status:* `✅ CLEAR - Safe to trade`",
            f"🕒 *Timestamp:* `{sig.timestamp.strftime('%Y-%m-%d %H:%M UTC')}`",
            f"⚠️ *Notice:* _Rule-based analysis only. Always manage your capital responsibly._",
        ])

        return "\n".join(lines)

    @classmethod
    def format_tp1_hit(cls, symbol: str, price: float, realized_pnl: float, new_sl: float) -> str:
        """Format a Take Profit 1 reached notification."""
        sym = cls.escape_code(symbol)
        formatted_price = cls.format_price(price, symbol)
        formatted_sl = cls.format_price(new_sl, symbol)
        return (
            f"🎯 *TAKE PROFIT 1 REACHED!* 🎯\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Pair:* `{sym}`\n"
            f"💰 *Exit Price:* `{formatted_price}`\n"
            f"💵 *Locked-in Profit:* `+${realized_pnl:,.2f}`\n"
            f"🔒 *Action Taken:* `Closed 50% lots. Stop Loss moved to Break-Even ({formatted_sl})`\n"
            f"🏃 *Runner:* `50% position remaining active for TP2 target.`\n"
            f"🕒 `{datetime.now(timezone.utc).strftime('%H:%M UTC')}`"
        )

    @classmethod
    def format_tp2_hit(cls, symbol: str, price: float, total_pnl: float, return_r: float) -> str:
        """Format a Take Profit 2 final target notification."""
        sym = cls.escape_code(symbol)
        formatted_price = cls.format_price(price, symbol)
        return (
            f"🏆 *TAKE PROFIT 2 TARGET HIT!* 🏆\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Pair:* `{sym}`\n"
            f"💰 *Exit Price:* `{formatted_price}`\n"
            f"💵 *Total Realized PnL:* `+${total_pnl:,.2f}`\n"
            f"📈 *Payoff Return:* `+{return_r:.2f} R-Multiple`\n"
            f"🎉 *Status:* `Trade fully completed with maximum target profit!`\n"
            f"🕒 `{datetime.now(timezone.utc).strftime('%H:%M UTC')}`"
        )

    @classmethod
    def format_sl_hit(cls, symbol: str, price: float, loss_pnl: float, is_be: bool) -> str:
        """Format Stop Loss / Break-Even alert."""
        tag = "⚡ *BREAK-EVEN STOP TRIGGERED*" if is_be else "🛑 *STOP LOSS HIT*"
        pnl_str = f"${loss_pnl:,.2f}" if loss_pnl >= 0 else f"-${abs(loss_pnl):,.2f}"
        sym = cls.escape_code(symbol)
        formatted_price = cls.format_price(price, symbol)
        return (
            f"{tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Pair:* `{sym}`\n"
            f"📍 *Exit Price:* `{formatted_price}`\n"
            f"💵 *Realized PnL:* `{pnl_str}`\n"
            f"🛡 *Capital Protected:* `Position closed per strict risk management rules.`\n"
            f"🕒 `{datetime.now(timezone.utc).strftime('%H:%M UTC')}`"
        )

    @classmethod
    def format_market_scan_summary(cls, scan_result: MarketScanResponse) -> str:
        """Format full multi-symbol unified market scanner digest."""
        lines = [
            f"📡 *UNIFIED SCANNER DIGEST* 📡",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🕒 *Scan Time:* `{scan_result.timestamp.strftime('%Y-%m-%d %H:%M UTC')}`",
            f"🔍 *Markets Scanned:* `{scan_result.scanned_count}` | 🎯 *Actionable:* `{scan_result.actionable_count}`",
            f"━━━━━━━━━━━━━━━━━━━━",
        ]

        for r in scan_result.results:
            dir_icon = "🟢" if r.direction == SignalDirection.BUY else ("🔴" if r.direction == SignalDirection.SELL else "⚪")
            status_text = f"*{cls.escape_markdown(r.direction.value)}* (Score: `{r.setup_score:.0f}/100`)"

            # Trend alignment tag
            if getattr(r, "trend_alignment", None):
                align = r.trend_alignment
                if align == "COUNTER-TREND SCALP":
                    status_text += " `[⚠️ COUNTER-TREND SCALP]`"
                elif align == "TREND FOLLOWING":
                    status_text += " `[✅ TREND FOLLOWING]`"
                else:
                    status_text += f" `[{cls.escape_markdown(align)}]`"
            elif r.direction == SignalDirection.WAIT and getattr(r, "htf_trend", None):
                status_text += f" `[1H {cls.escape_markdown(r.htf_trend)}]`"

            if r.blackout_blocked:
                status_text += " `[NEWS BLOCKED]`"

            sym = cls.escape_code(f"{r.symbol:<8}")
            tf_display = "1H" if r.timeframe.lower() == "1h" else r.timeframe
            tf = cls.escape_code(tf_display)
            lines.append(f"{dir_icon} `{sym}` [{tf}] ➔ {status_text}")

        lines.extend([
            f"━━━━━━━━━━━━━━━━━━━━",
            f"💡 _Type /signal <pair> for deep multi-timeframe analysis._",
        ])
        return "\n".join(lines)

    @classmethod
    def format_economic_news_alert(cls, events: List[NewsEventResponse]) -> str:
        """Format scheduled economic news alerts."""
        lines = [
            f"📰 *ECONOMIC CALENDAR & NEWS MONITOR* 📰",
            f"━━━━━━━━━━━━━━━━━━━━",
        ]
        if not events:
            lines.append("✅ *No high or medium impact events scheduled today.*")
            return "\n".join(lines)

        for ev in events[:5]:
            impact_icon = "🔴" if ev.impact.upper() == "HIGH" else "🟡"
            curr = cls.escape_markdown(ev.currency)
            ev_name = cls.escape_code(ev.event_name)
            fc = cls.escape_code(ev.forecast or 'N/A')
            prev = cls.escape_code(ev.previous or 'N/A')
            lines.append(
                f"{impact_icon} *({curr})* `{ev_name}`\n"
                f"   ⏰ `{ev.scheduled_time.strftime('%H:%M UTC')}` | Forecast: `{fc}` | Prior: `{prev}`"
            )

        lines.extend([
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🛡 _Trading automatically pauses 30m before high-impact releases._",
        ])
        return "\n".join(lines)

    @classmethod
    def format_news_unavailable_alert(cls, reason: Optional[str] = None) -> str:
        """Format structured alert when live economic news feed is unreachable."""
        lines = [
            f"⚠️ *NEWS DATA UNAVAILABLE* ⚠️",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"❌ *Live economic calendar feed is currently unreachable.*",
            f"🛡 *FAIL-SAFE ACTIVATED:* New trade generation is safely paused to protect capital until economic news feed is restored.",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"⚡ _Institutional Capital Protection Rule_",
        ]
        return "\n".join(lines)

    @classmethod
    def format_portfolio_summary(cls, acc: VirtualAccountResponse, perf: PaperPortfolioPerformance) -> str:
        """Format virtual account portfolio overview."""
        acc_name = cls.escape_code(acc.name)
        return (
            f"💼 *VIRTUAL TRADING PORTFOLIO* 💼\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *Account:* `{acc_name}`\n"
            f"💵 *Balance:* `${acc.balance:>10,.2f}`\n"
            f"📈 *Equity:*  `${acc.equity:>10,.2f}`\n"
            f"📊 *Floating PnL:* `${acc.floating_pnl:>+9,.2f}`\n"
            f"🔒 *Margin Used:*  `${acc.margin_used:>10,.2f}` (Level: `{acc.margin_level_pct:.1f}%`)\n"
            f"🆓 *Free Margin:*  `${acc.free_margin:>10,.2f}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 *Trading Performance:*\n"
            f"  • *Total Return:* `{perf.total_return_pct:>+6.2f}%`\n"
            f"  • *Win Rate:* `{perf.win_rate:.1f}%` ({perf.winning_trades}W / {perf.losing_trades}L)\n"
            f"  • *Profit Factor:* `{perf.profit_factor:.2f}`\n"
            f"  • *Active Positions:* `{perf.open_trades}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕒 `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}`"
        )

    @staticmethod
    def format_help_menu() -> str:
        """Format bot command help menu."""
        return (
            f" *FOREX SIGNAL BOT - COMMAND MENU* \n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 `/scan` - Scan all markets (XAU/USD, USD/JPY)\n"
            f"🔄 `/sync` - Force fresh data sync for ALL pairs (Fixes Stale Data)\n"
            f"🎯 `/signal <pair>` - Deep setup score for symbol (e.g. `/signal XAU/USD`)\n"
            f"📰 `/news` - Today's economic calendar & news blackout check\n"
            f" `/account` - Virtual paper trading balance, equity & margin\n"
            f"📊 `/positions` - List all active & pending paper positions\n"
            f"🏆 `/performance` - Strategy win rate & portfolio statistics\n"
            f" `/backtest <pair>` - Run historical strategy backtest\n"
            f"❓ `/help` - Show this command reference\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ _Institutional Rule-Based Market Analysis & Risk Management_"
        )