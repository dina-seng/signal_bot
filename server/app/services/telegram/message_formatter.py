"""Telegram Message Formatting with rich emojis, entity sanitization, and Markdown/HTML styling."""

from datetime import datetime, timezone
import html
from typing import Any, List, Optional

from app.core.config import ACTIVE_SYMBOLS
from app.core.time_utils import format_local_time
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
        """Format an actionable trade setup alert.

        Handles three cases:
        - PATH BLOCKED rejection: shows a dedicated rejection card
        - TP Adjusted (trade still valid): shows warning in the alert
        - Normal trade: standard signal format
        """
        # Detect path validation outcomes from reasons and warnings
        path_blocked_reason = None
        tp_adjusted_reason = None
        path_advisory = None

        for w in (getattr(sig, "warnings", []) or []):
            if "Path Advisory" in w:
                path_advisory = w
                break

        for r in (sig.reasons or []):
            if "PATH BLOCKED" in r:
                path_blocked_reason = r
            elif "TP Adjusted" in r:
                tp_adjusted_reason = r
            elif "Path Advisory" in r and not path_advisory:
                path_advisory = r

        # PATH BLOCKED rejection card — trade was killed by obstacle detection (legacy fallback)
        if sig.direction == SignalDirection.WAIT and path_blocked_reason:
            sym = cls.escape_code(sig.symbol)
            tf = cls.escape_code(sig.timeframe)
            lines = [
                f"🚧 *TRADE REJECTED — PATH BLOCKED* 🚧",
                f"━━━━━━━━━━━━━━━━━━━━",
                f"📊 *Instrument:* `{sym}`",
                f"⏱ *Timeframe:* `{tf}`",
                f"━━━━━━━━━━━━━━━━━━━━",
                f"🛑 *Rejection Reason:*",
                f"  {cls.escape_markdown(path_blocked_reason)}",
                f"━━━━━━━━━━━━━━━━━━━━",
                f"🛡 *Risk Protection:* _Structural obstacle between entry and target "
                f"reduces R:R below minimum threshold. Trade skipped to protect capital._",
            ]
            # Include other context reasons (max 3)
            other_reasons = [r for r in (sig.reasons or []) if r != path_blocked_reason]
            if other_reasons:
                lines.append(f"━━━━━━━━━━━━━━━━━━━━\n💡 *Market Context:*")
                for r in other_reasons[:3]:
                    lines.append(f"  • {cls.escape_markdown(r)}")

            lines.extend([
                f"━━━━━━━━━━━━━━━━━━━━",
                f"🕒 *Timestamp:* `{format_local_time(sig.timestamp)}`",
                f"⚡ _Institutional obstacle detection is actively protecting your capital._",
            ])
            return "\n".join(lines)

        # Normal actionable signal format (with optional Path Advisory / TP Adjusted warning)
        dir_emoji = "🟢 *STRONG BUY (LONG)*" if sig.direction == SignalDirection.BUY else "🔴 *STRONG SELL (SHORT)*"
        rp = sig.risk_parameters

        sym_clean = sig.symbol
        sym = cls.escape_code(sym_clean)
        tf = cls.escape_code(sig.timeframe)
        score_str = f"{sig.setup_score:.1f}"

        # Strategy-aware header
        strategy_label = sig.strategy_name or "Confluence"
        header = f"⚡ *NEW SIGNAL: {cls.escape_markdown(strategy_label)}* ⚡"

        lines = [
            header,
            f"━━━━━━━━━━━━━━━━━━━━",
            f"📊 *Instrument:* `{sym}`",
            f"⏱ *Timeframe:* `{tf}`",
            f"🎯 *Direction:* {dir_emoji}",
            f"🧠 *Strategy:* `{cls.escape_code(strategy_label)}`",
            f"⭐ *Confluence Score:* `{score_str} / 100`",
        ]

        strat_name = getattr(sig, "strategy_name", "") or ""
        if "Range Sniper" in strat_name:
            lines.append("🧭 *Market Regime:* 🔄 `RANGING / MEAN REVERSION`")
        else:
            lines.append("🧭 *Market Regime:* 🎯 `TREND FOLLOWING`")

        if getattr(sig, "htf_trend", None):
            lines.append(f"📈 *1H Context:* `{cls.escape_code(sig.htf_trend)}`")

        # Path Advisory section — informational obstacle notification
        if path_advisory:
            lines.extend([
                f"━━━━━━━━━━━━━━━━━━━━",
                f"⚠️ *Path Advisory:*",
            ])
            for line in path_advisory.strip().split("\n"):
                clean = line.strip()
                if clean.startswith("⚠️ Path Advisory"):
                    continue
                lines.append(f"  {cls.escape_markdown(clean)}")
        elif tp_adjusted_reason:
            lines.extend([
                f"━━━━━━━━━━━━━━━━━━━━",
                f"⚠️ *Path Warning:*",
                f"  {cls.escape_markdown(tp_adjusted_reason)}",
            ])

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
            rr_label = f"{sig.risk_reward:.1f}" if sig.risk_reward else "2.0"
            lines.append(f"🎯 *Take Profit 1 (TP1):* `{formatted_tp1}` ({tp1_pips:.1f} pips | {rr_label} R:R)")

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
            breakdown_lines = [
                f"━━━━━━━━━━━━━━━━━━━━",
                f"🏛 *Pillar Breakdown:*",
                f"  • Structure & MTF: `{bd.structure_score:.0f}/35`",
                f"  • Liquidity & POIs: `{bd.liquidity_score:.0f}/40`",
                f"  • Price Action: `{bd.price_action_score:.0f}/25`",
            ]
            if bd.indicators_score > 0:
                breakdown_lines.append(f"  • Indicators (Aux): `{bd.indicators_score:.0f}/25`")
            lines.extend(breakdown_lines)

        if sig.reasons:
            lines.append(f"━━━━━━━━━━━━━━━━━━━━\n💡 *Key Confluence Catalysts:*")
            for r in sig.reasons[:4]:
                # Skip the TP Adjusted and Path Advisory reasons here since they're shown above
                if (tp_adjusted_reason and r == tp_adjusted_reason) or "Path Advisory" in r:
                    continue
                lines.append(f"  ✓ {cls.escape_markdown(r)}")

        lines.extend([
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🛡 *News Blackout Status:* `✅ CLEAR - Safe to trade`",
            f"🕒 *Timestamp:* `{format_local_time(sig.timestamp)}`",
            f"⚠️ *Notice:* _Rule-based analysis only. Always manage your capital responsibly._",
        ])

        return "\n".join(lines)

    @classmethod
    def format_multi_strategy_alert(cls, signals: List[SignalResponse]) -> str:
        """Format an alert when multiple independent strategies produce signals for the same symbol."""
        if not signals:
            return ""
        if len(signals) == 1:
            return cls.format_signal_alert(signals[0])

        sym_clean = signals[0].symbol
        sym = cls.escape_code(sym_clean)
        tf = cls.escape_code(signals[0].timeframe)

        # Check directions
        directions = {s.direction for s in signals if s.direction in (SignalDirection.BUY, SignalDirection.SELL)}
        is_conflict = len(directions) > 1

        if is_conflict:
            header = f"⚠️ *STRATEGY CONFLICT DETECTED: {sym}* ⚠️"
            state_label = "⚠️ *Market State:* `STRATEGY CONFLICT (Opposing Biases)`"
        else:
            dir_val = list(directions)[0] if directions else SignalDirection.WAIT
            dir_text = "BUY" if dir_val == SignalDirection.BUY else ("SELL" if dir_val == SignalDirection.SELL else "WAIT")
            header = f"⚡ *STRATEGY CONFLUENCE: {sym} ({dir_text})* ⚡"
            state_label = "✅ *Market State:* `STRATEGY CONFLUENCE (Aligned Direction)`"

        lines = [
            header,
            f"━━━━━━━━━━━━━━━━━━━━",
            f"📊 *Instrument:* `{sym}`",
            f"⏱ *Timeframe:* `{tf}`",
            state_label,
            f"━━━━━━━━━━━━━━━━━━━━",
        ]

        for s in signals:
            strat = s.strategy_name or "Independent Strategy"
            dir_emoji = "🟢 BUY" if s.direction == SignalDirection.BUY else ("🔴 SELL" if s.direction == SignalDirection.SELL else "⚪ WAIT")
            lines.append(f"🧠 *{cls.escape_markdown(strat)}:* {dir_emoji} (Score: `{s.setup_score:.1f}/100`)")
            if s.reasons:
                for r in s.reasons[:3]:
                    lines.append(f"   • {cls.escape_markdown(r)}")
            lines.append(f"────────────────────")

        # Summary guidance
        if is_conflict:
            lines.extend([
                f"🛡 *Analysis Note:* _Independent strategies show opposing direction. "
                f"Exercise elevated caution or wait for structural resolution._",
            ])
        else:
            actionable = [s for s in signals if s.direction in (SignalDirection.BUY, SignalDirection.SELL)]
            if actionable:
                primary_sig = max(actionable, key=lambda x: x.setup_score)
                if primary_sig.entry_price is not None:
                    lines.append(f"📍 *Confluence Entry:* `{cls.format_price(primary_sig.entry_price, sym_clean)}`")
                if primary_sig.stop_loss is not None:
                    lines.append(f"🛑 *Stop Loss:* `{cls.format_price(primary_sig.stop_loss, sym_clean)}`")
                if primary_sig.take_profit_1 is not None:
                    lines.append(f"🎯 *Take Profit 1:* `{cls.format_price(primary_sig.take_profit_1, sym_clean)}`")

        lines.extend([
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🕒 *Timestamp:* `{format_local_time(signals[0].timestamp)}`",
            f"⚠️ *Notice:* _Rule-based multi-strategy analysis. Manage risk responsibly._",
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
            f"🕒 `{format_local_time(datetime.now(timezone.utc))}`"
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
            f"🕒 `{format_local_time(datetime.now(timezone.utc))}`"
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
            f"🕒 `{format_local_time(datetime.now(timezone.utc))}`"
        )

    @classmethod
    def format_market_scan_summary(cls, scan_result: MarketScanResponse) -> str:
        """Format full multi-symbol unified market scanner digest."""
        lines = [
            f"📡 *UNIFIED SCANNER DIGEST* 📡",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🕒 *Scan Time:* `{format_local_time(scan_result.timestamp)}`",
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

            # Strategy badge
            strat_badge = ""
            if getattr(r, "signal", None) and getattr(r.signal, "strategy_name", None):
                strat_badge = f" `[{cls.escape_code(r.signal.strategy_name)}]`"

            lines.append(f"{dir_icon} `{sym}` [{tf}] ➔ {status_text}{strat_badge}")

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
            f"🕒 `{format_local_time(datetime.now(timezone.utc))}`"
        )

    @staticmethod
    def format_help_menu() -> str:
        """Format bot command help menu."""
        return (
            f" *FOREX SIGNAL BOT - COMMAND MENU* \n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 `/scan` - Scan all markets ({', '.join(ACTIVE_SYMBOLS)})\n"
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