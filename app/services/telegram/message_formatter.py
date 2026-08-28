"""Telegram Message Formatting with rich emojis and Markdown styling."""

from datetime import datetime, timezone
from typing import List, Optional

from app.schemas.news import NewsEventResponse
from app.schemas.paper_trading import PaperPortfolioPerformance, VirtualAccountResponse
from app.schemas.signal import MarketScanResponse, SignalDirection, SignalResponse


class TelegramMessageFormatter:
    """Formats market signals, position alerts, news summaries, and portfolio updates for Telegram."""

    @staticmethod
    def format_signal_alert(sig: SignalResponse) -> str:
        """Format an actionable trade setup alert."""
        dir_emoji = "🟢 *STRONG BUY (LONG)*" if sig.direction == SignalDirection.BUY else "🔴 *STRONG SELL (SHORT)*"
        rp = sig.risk_parameters

        lines = [
            f"⚡ *NEW FOREX TRADE SIGNAL* ⚡",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"📊 *Instrument:* `{sig.symbol}`",
            f"⏱ *Timeframe:* `{sig.timeframe}`",
            f"🎯 *Direction:* {dir_emoji}",
            f"⭐ *Confluence Score:* `{sig.setup_score:.1f} / 100`",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"📍 *Entry Price:* `{sig.entry_price:.5f}`",
            f"🛑 *Stop Loss:* `{sig.stop_loss:.5f}`" + (f" ({rp.risk_pips:.1f} pips)" if rp else ""),
            f"🎯 *Take Profit 1 (TP1):* `{sig.take_profit_1:.5f}`" + (f" ({rp.reward_pips_tp1:.1f} pips | 2.0 R:R)" if rp else ""),
            f"🏆 *Take Profit 2 (TP2):* `{sig.take_profit_2:.5f}`" + (f" ({rp.reward_pips_tp2:.1f} pips | 3.0 R:R)" if rp else ""),
        ]

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
                lines.append(f"  ✓ {r}")

        lines.extend([
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🛡 *News Blackout Status:* `✅ CLEAR - Safe to trade`",
            f"🕒 *Timestamp:* `{sig.timestamp.strftime('%Y-%m-%d %H:%M UTC')}`",
            f"⚠️ *Notice:* _Rule-based analysis only. Always manage your capital responsibly._",
        ])

        return "\n".join(lines)

    @staticmethod
    def format_tp1_hit(symbol: str, price: float, realized_pnl: float, new_sl: float) -> str:
        """Format a Take Profit 1 reached notification."""
        return (
            f"🎯 *TAKE PROFIT 1 REACHED!* 🎯\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Pair:* `{symbol}`\n"
            f"💰 *Exit Price:* `{price:.5f}`\n"
            f"💵 *Locked-in Profit:* `+${realized_pnl:,.2f}`\n"
            f"🔒 *Action Taken:* `Closed 50% lots. Stop Loss moved to Break-Even ({new_sl:.5f})`\n"
            f"🏃 *Runner:* `50% position remaining active for TP2 target.`\n"
            f"🕒 `{datetime.now(timezone.utc).strftime('%H:%M UTC')}`"
        )

    @staticmethod
    def format_tp2_hit(symbol: str, price: float, total_pnl: float, return_r: float) -> str:
        """Format a Take Profit 2 final target notification."""
        return (
            f"🏆 *TAKE PROFIT 2 TARGET HIT!* 🏆\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Pair:* `{symbol}`\n"
            f"💰 *Exit Price:* `{price:.5f}`\n"
            f"💵 *Total Realized PnL:* `+${total_pnl:,.2f}`\n"
            f"📈 *Payoff Return:* `+{return_r:.2f} R-Multiple`\n"
            f"🎉 *Status:* `Trade fully completed with maximum target profit!`\n"
            f"🕒 `{datetime.now(timezone.utc).strftime('%H:%M UTC')}`"
        )

    @staticmethod
    def format_sl_hit(symbol: str, price: float, loss_pnl: float, is_be: bool) -> str:
        """Format Stop Loss / Break-Even alert."""
        tag = "⚡ *BREAK-EVEN STOP TRIGGERED*" if is_be else "🛑 *STOP LOSS HIT*"
        pnl_str = f"${loss_pnl:,.2f}" if loss_pnl >= 0 else f"-${abs(loss_pnl):,.2f}"
        return (
            f"{tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Pair:* `{symbol}`\n"
            f"📍 *Exit Price:* `{price:.5f}`\n"
            f"💵 *Realized PnL:* `{pnl_str}`\n"
            f"🛡 *Capital Protected:* `Position closed per strict risk management rules.`\n"
            f"🕒 `{datetime.now(timezone.utc).strftime('%H:%M UTC')}`"
        )

    @staticmethod
    def format_market_scan_summary(scan_result: MarketScanResponse) -> str:
        """Format full multi-symbol market scanner digest."""
        lines = [
            f"📡 *MULTI-MARKET SCANNER DIGEST* 📡",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🕒 *Scan Time:* `{scan_result.timestamp.strftime('%Y-%m-%d %H:%M UTC')}`",
            f"🔍 *Markets Scanned:* `{scan_result.scanned_count}` | 🎯 *Actionable:* `{scan_result.actionable_count}`",
            f"━━━━━━━━━━━━━━━━━━━━",
        ]

        for r in scan_result.results:
            dir_icon = "🟢" if r.direction == SignalDirection.BUY else ("🔴" if r.direction == SignalDirection.SELL else "⚪")
            status_text = f"*{r.direction.value}* (Score: `{r.setup_score:.0f}/100`)"
            if r.blackout_blocked:
                status_text += " `[NEWS BLOCKED]`"

            lines.append(f"{dir_icon} `{r.symbol:<8}` [{r.timeframe}] ➔ {status_text}")

        lines.extend([
            f"━━━━━━━━━━━━━━━━━━━━",
            f"💡 _Type /signal <pair> for deep analysis on any symbol._",
        ])
        return "\n".join(lines)

    @staticmethod
    def format_economic_news_alert(events: List[NewsEventResponse]) -> str:
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
            lines.append(
                f"{impact_icon} *[{ev.currency}]* `{ev.event_name}`\n"
                f"   ⏰ `{ev.scheduled_time.strftime('%H:%M UTC')}` | Forecast: `{ev.forecast or 'N/A'}` | Prior: `{ev.previous or 'N/A'}`"
            )

        lines.extend([
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🛡 _Trading automatically pauses 30m before high-impact releases._",
        ])
        return "\n".join(lines)

    @staticmethod
    def format_portfolio_summary(acc: VirtualAccountResponse, perf: PaperPortfolioPerformance) -> str:
        """Format virtual account portfolio overview."""
        return (
            f"💼 *VIRTUAL TRADING PORTFOLIO* 💼\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *Account:* `{acc.name}`\n"
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
            f"🤖 *FOREX SIGNAL BOT - COMMAND MENU* 🤖\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 `/scan` - Scan all markets (EUR/USD, GBP/USD, USD/JPY, Gold)\n"
            f"🎯 `/signal <pair>` - Deep setup score for symbol (e.g. `/signal EUR/USD`)\n"
            f"📰 `/news` - Today's economic calendar & news blackout check\n"
            f"💼 `/account` - Virtual paper trading balance, equity & margin\n"
            f"📊 `/positions` - List all active & pending paper positions\n"
            f"🏆 `/performance` - Strategy win rate & portfolio statistics\n"
            f"📈 `/backtest <pair>` - Run historical strategy backtest\n"
            f"❓ `/help` - Show this command reference\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ _Institutional Rule-Based Market Analysis & Risk Management_"
        )
