"""Telegram Message Formatting with rich emojis, entity sanitization, and pure HTML styling."""

from dataclasses import dataclass
from datetime import datetime, timezone
import html
from typing import Any, Dict, List, Optional, Union

from app.core.config import settings
from app.services.market_data.symbols import (
    UnknownSymbolError,
    calculate_pips,
    format_price,
    get_instrument_spec,
    normalize_symbol,
    target_account_for_symbol,
)
from app.schemas.news import NewsEventResponse
from app.schemas.paper_trading import (
    PaperPortfolioPerformance,
    PaperTradeResponse,
    VirtualAccountResponse,
)
from app.schemas.signal import MarketScanResponse, SignalDirection, SignalResponse


@dataclass
class SignalContext:
    """External context passed to the pure signal formatter."""
    account_balance: Optional[float] = None
    risk_percent: Optional[float] = None
    risk_amount_usd: Optional[float] = None
    suggested_lot_size: Optional[float] = None
    news_blackout_status: Optional[str] = None
    regime: Optional[str] = None
    htf_context: Optional[str] = None
    catalysts: Optional[List[str]] = None
    warnings: Optional[List[str]] = None
    created_at: Optional[datetime] = None


def escape_html(text: Any) -> str:
    """Escape dynamic strings for Telegram HTML parse_mode (&, <, >)."""
    if text is None:
        return ""
    return html.escape(str(text), quote=False)


def resolve_target_account(signal: Any) -> str:
    """Read ``target_account`` ("MAIN"/"CENT") from signal metadata.

    Persisted legacy signals have no metadata, so fall back to the symbol
    routing rule (BTC/USD -> CENT, everything else -> MAIN).
    """
    meta = getattr(signal, "metadata", None) if not isinstance(signal, dict) else signal
    raw = meta.get("target_account") if isinstance(meta, dict) else None
    if raw:
        return str(raw).strip().upper()
    symbol = (
        getattr(signal, "symbol", None)
        if not isinstance(signal, dict)
        else meta.get("symbol")
    )
    return target_account_for_symbol(str(symbol or ""))


def format_target_account_label(account: str, meta: Optional[Dict[str, Any]] = None) -> str:
    """Render e.g. ``CENT (2000c)`` when the account nickname is supplied."""
    detail = (meta or {}).get("target_account_label") or (meta or {}).get("account_label")
    return f"{account} ({detail})" if detail else account


def format_signal(
    signal: Any,
    ctx: Optional[SignalContext] = None,
    risk_warning: Optional[str] = None,
) -> str:
    """Pure, zero-I/O function that formats a trading signal for Telegram (HTML mode).
    
    Zero defaults for trading values, no datetime.now() inside signal timestamp formatting.
    Every displayed field comes strictly from the signal and ctx objects.
    Missing fields render as explicit 'N/A'. Never substitutes placeholder numbers.
    """
    if signal is None:
        raise ValueError("Cannot format null signal.")

    ctx = ctx or SignalContext()

    # 1. Identity & Instrument
    raw_sym = getattr(signal, "symbol", None)
    if not raw_sym:
        raise ValueError("Signal symbol is required.")
    try:
        sym = normalize_symbol(raw_sym)
    except UnknownSymbolError:
        sym = raw_sym

    tf = getattr(signal, "timeframe", None) or "N/A"
    direction_val = getattr(signal, "direction", None)
    if isinstance(direction_val, SignalDirection):
        dir_str = direction_val.value
    elif direction_val is not None:
        dir_str = str(direction_val).upper()
    else:
        dir_str = "N/A"

    strategy_label = getattr(signal, "strategy_name", None) or "N/A"
    score_val = getattr(signal, "setup_score", None)
    score_str = f"{score_val:.1f} / 100" if score_val is not None else "N/A"

    meta = getattr(signal, "metadata", {}) or {}
    if risk_warning:
        meta = dict(meta) if isinstance(meta, dict) else {}
        meta["risk_warning"] = risk_warning
    setup_state_str = meta.get("setup_state") if isinstance(meta, dict) else None

    is_btc = sym == "BTC/USD"
    target_account = resolve_target_account(signal)
    account_label = format_target_account_label(
        target_account, meta if isinstance(meta, dict) else {}
    )

    # Do not print "STRONG BUY" unless setup_state is CONFIRMED_SETUP and score is >= threshold
    min_score = getattr(settings, "MIN_SETUP_SCORE", 60.0)
    is_confirmed_strong = (
        (setup_state_str == "CONFIRMED_SETUP" or setup_state_str is None)
        and score_val is not None
        and score_val >= min_score
    )

    if dir_str == "BUY":
        dir_badge = "🟢 <b>STRONG BUY (LONG)</b>" if is_confirmed_strong else "🟢 <b>BUY (LONG)</b>"
    elif dir_str == "SELL":
        dir_badge = "🔴 <b>STRONG SELL (SHORT)</b>" if is_confirmed_strong else "🔴 <b>SELL (SHORT)</b>"
    else:
        dir_badge = f"⚪ <b>{escape_html(dir_str)}</b>"

    # 2. Strategy & Header — the executing account is always explicit.
    lines = [f"⚡ <b>NEW SIGNAL: {escape_html(strategy_label)}</b> ⚡"]
    if is_btc and dir_str in ("BUY", "SELL"):
        icon = "🟢" if dir_str == "BUY" else "🔴"
        lines.append(
            f"{icon} <b>BTC MOMENTUM {escape_html(dir_str)}</b> | "
            f"Account: <code>{escape_html(account_label)}</code>"
        )
    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        f"🏦 <b>Executing Account:</b> <code>{escape_html(account_label)}</code>",
        f"📊 <b>Instrument:</b> <code>{escape_html(sym)}</code>",
        f"⏱ <b>Timeframe:</b> <code>{escape_html(tf)}</code>",
        f"🎯 <b>Direction:</b> {dir_badge}",
        f"🧠 <b>Strategy:</b> <code>{escape_html(strategy_label)}</code>",
        f"⭐ <b>Confluence Score:</b> <code>{score_str}</code>",
    ])

    quality_tier = (meta.get("quality_tier_label") or meta.get("quality_tier")) if isinstance(meta, dict) else None
    if quality_tier:
        lines.append(f"🎖 <b>Quality Tier:</b> <code>{escape_html(quality_tier)}</code>")

    if setup_state_str:
        lines.append(f"📌 <b>Setup State:</b> <code>{escape_html(setup_state_str)}</code>")

    entry_zone = meta.get("entry_zone") if isinstance(meta, dict) else None
    entry_mode = meta.get("entry_mode") if isinstance(meta, dict) else None
    ideal_entry = meta.get("ideal_entry") if isinstance(meta, dict) else None
    if entry_zone and isinstance(entry_zone, (list, tuple)) and len(entry_zone) == 2:
        mode_str = f" ({entry_mode})" if entry_mode else ""
        ideal_str = f" [Ideal: {ideal_entry:.2f}]" if ideal_entry is not None else ""
        lines.append(f"🎯 <b>Entry Zone:</b> <code>[{entry_zone[0]:.2f} - {entry_zone[1]:.2f}]</code>{mode_str}{ideal_str}")

    expires_utc = meta.get("expires_at_utc") if isinstance(meta, dict) else None
    expires_utc7 = meta.get("expires_at_utc7") if isinstance(meta, dict) else None
    if expires_utc:
        utc7_str = f" / {expires_utc7} UTC+7" if expires_utc7 else ""
        lines.append(f"⏳ <b>Valid Until:</b> <code>{escape_html(expires_utc)} UTC{utc7_str}</code>")

    session_name = meta.get("session_name") if isinstance(meta, dict) else None
    if session_name:
        lines.append(f"🌐 <b>Session:</b> <code>{escape_html(session_name)}</code>")

    # SMC-only provenance is suppressed for the momentum strategy.
    if not is_btc:
        sweep_level_type = meta.get("sweep_level_type") if isinstance(meta, dict) else None
        if sweep_level_type:
            lines.append(f"🌊 <b>Swept Level:</b> <code>{escape_html(sweep_level_type)}</code>")

        nearest_obs = meta.get("nearest_obstacle") if isinstance(meta, dict) else None
        if nearest_obs:
            lines.append(f"🚧 <b>Nearest Obstacle:</b> <code>{escape_html(nearest_obs)}</code>")

    # 3. Market Regime & strategy-specific context.
    # BTC momentum uses EMA/RSI/ADX; SMC HTF/structure terms are XAU-only.
    regime = ctx.regime
    if not regime:
        if is_btc:
            adx_raw = meta.get("adx_14") if isinstance(meta, dict) else None
            regime = (
                f"MOMENTUM TREND (ADX {float(adx_raw):.1f})"
                if adx_raw is not None else "MOMENTUM REGIME"
            )
        elif "RANGING" in str(getattr(signal, "htf_trend", "")):
            regime = "RANGING / MEAN REVERSION"
        elif getattr(signal, "trend_alignment", None):
            regime = str(signal.trend_alignment)
        else:
            regime = "TREND FOLLOWING"
    lines.append(f"🔄 <b>Market Regime:</b> <code>{escape_html(regime)}</code>")

    if is_btc:
        ema_50 = meta.get("ema_50") if isinstance(meta, dict) else None
        ema_200 = meta.get("ema_200") if isinstance(meta, dict) else None
        ema_trend = meta.get("ema_trend") if isinstance(meta, dict) else None
        if ema_trend is None and ema_50 is not None and ema_200 is not None:
            ema_trend = "Bullish" if float(ema_50) > float(ema_200) else "Bearish"
        rsi_raw = meta.get("rsi_14") if isinstance(meta, dict) else None
        adx_raw = meta.get("adx_14") if isinstance(meta, dict) else None
        momentum_bits = [
            f"EMA Trend: {ema_trend or 'N/A'}",
            f"RSI: {float(rsi_raw):.0f}" if rsi_raw is not None else "RSI: N/A",
            f"ADX: {float(adx_raw):.0f}" if adx_raw is not None else "ADX: N/A",
        ]
        lines.append(
            f"📈 <b>Momentum Indicators:</b> <code>{escape_html(' | '.join(momentum_bits))}</code>"
        )
        if ema_50 is not None and ema_200 is not None:
            lines.append(
                f"📐 <b>EMA 50 / 200:</b> <code>{float(ema_50):.2f} / {float(ema_200):.2f}</code>"
            )
        provenance = meta.get("heuristic_provenance") if isinstance(meta, dict) else None
        if provenance:
            lines.append(
                f"🧪 <b>Provenance:</b> <code>{escape_html(provenance)}</code> "
                "<i>(empirical 1H heuristic, not paper-validated intraday)</i>"
            )
    else:
        htf_source = meta.get("htf_trend_source") if isinstance(meta, dict) else None
        htf = ctx.htf_context or getattr(signal, "htf_trend", None) or (meta.get("htf_trend") if isinstance(meta, dict) else None)
        if htf or htf_source:
            if htf_source == "structure_primary":
                htf_str = f"{htf} (Source: Primary Structure 15m - Unconfirmed HTF)" if htf else "Primary Structure 15m - Unconfirmed HTF"
            elif htf_source and htf_source != "none":
                htf_str = f"{htf} (Source: {htf_source})" if htf else f"(Source: {htf_source})"
            else:
                htf_str = str(htf)
            lines.append(f"📈 <b>HTF Context:</b> <code>{escape_html(htf_str)}</code>")
        else:
            lines.append("📈 <b>HTF Context:</b> <code>N/A</code>")

    lines.append("━━━━━━━━━━━━━━━━━━━━")

    # 4. Entry, SL, TP1, TP2 Pricing & Computed Pip Distances
    entry_price = getattr(signal, "entry_price", None)
    if entry_price is not None:
        lines.append(f"📍 <b>Entry Price:</b> <code>{format_price(entry_price, sym)}</code>")
    else:
        lines.append("📍 <b>Entry Price:</b> <code>N/A</code>")

    stop_loss = getattr(signal, "stop_loss", None)
    if stop_loss is not None:
        sl_formatted = format_price(stop_loss, sym)
        if entry_price is not None:
            sl_pips = calculate_pips(entry_price, stop_loss, sym)
            lines.append(f"🛑 <b>Stop Loss:</b> <code>{sl_formatted}</code> ({sl_pips:.1f} pips)")
        else:
            lines.append(f"🛑 <b>Stop Loss:</b> <code>{sl_formatted}</code> (N/A pips)")
    else:
        lines.append("🛑 <b>Stop Loss:</b> <code>N/A</code>")

    rp = getattr(signal, "risk_parameters", None)

    tp1 = getattr(signal, "take_profit_1", None)
    if tp1 is not None:
        tp1_formatted = format_price(tp1, sym)
        if entry_price is not None:
            tp1_pips = calculate_pips(entry_price, tp1, sym)
            rr_tp1 = getattr(rp, "risk_reward_tp1", None) or getattr(signal, "risk_reward", None)
            rr_tp1_str = f"{rr_tp1:.1f} R:R" if rr_tp1 is not None else "N/A R:R"
            lines.append(f"🎯 <b>Take Profit 1 (TP1):</b> <code>{tp1_formatted}</code> ({tp1_pips:.1f} pips | {rr_tp1_str})")
        else:
            lines.append(f"🎯 <b>Take Profit 1 (TP1):</b> <code>{tp1_formatted}</code> (N/A)")
    else:
        lines.append("🎯 <b>Take Profit 1 (TP1):</b> <code>N/A</code>")

    tp2 = getattr(signal, "take_profit_2", None)
    if tp2 is not None:
        tp2_formatted = format_price(tp2, sym)
        if entry_price is not None:
            tp2_pips = calculate_pips(entry_price, tp2, sym)
            rr_tp2 = getattr(rp, "risk_reward_tp2", None)
            rr_tp2_str = f"{rr_tp2:.1f} R:R" if rr_tp2 is not None else "N/A R:R"
            lines.append(f"🏆 <b>Take Profit 2 (TP2):</b> <code>{tp2_formatted}</code> ({tp2_pips:.1f} pips | {rr_tp2_str})")
        else:
            lines.append(f"🏆 <b>Take Profit 2 (TP2):</b> <code>{tp2_formatted}</code> (N/A)")
    else:
        lines.append("🏆 <b>Take Profit 2 (TP2):</b> <code>N/A</code>")

    # 5. Risk Allocation & Sizing
    risk_pct = getattr(rp, "risk_percent", None) or ctx.risk_percent
    suggested_lots = getattr(rp, "suggested_lot_size", None) or ctx.suggested_lot_size
    risk_amount = getattr(rp, "risk_amount_usd", None) or ctx.risk_amount_usd
    balance = getattr(rp, "account_balance", None) or ctx.account_balance
    risk_warning = meta.get("risk_warning") if isinstance(meta, dict) else None

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    risk_pct_str = f"{risk_pct:.1f}%" if risk_pct is not None else "N/A"
    lines.append(f"💼 <b>Risk Management ({risk_pct_str} Rule):</b>")

    if risk_warning and (
        "RISK EXCEEDS LIMIT" in str(risk_warning)
        or "Risk budget insufficient" in str(risk_warning)
    ):
        # Formerly dead branch: now reachable via format_signal(risk_warning=...) and
        # via signal.metadata["risk_warning"] set by the dispatcher on rejection.
        lines.append(f"  ⚠️ <b>TRADE REJECTED — RISK BUDGET:</b> <code>{escape_html(risk_warning)}</code>")
        if balance is not None and risk_pct is not None:
            budget = balance * (risk_pct / 100.0)
            lines.append(f"  • <b>Risk Budget:</b> <code>${budget:,.2f}</code> (minimum lot cannot be funded)")
    else:
        lots_str = f"{suggested_lots:.2f} Standard Lots" if suggested_lots is not None else "N/A"
        lines.append(f"  • <b>Suggested Sizing:</b> <code>{lots_str}</code>")
        if risk_amount is not None and balance is not None:
            lines.append(f"  • <b>Risk Allocation:</b> <code>${risk_amount:,.2f}</code> on <code>${balance:,.0f}</code> balance")
        elif risk_amount is not None:
            lines.append(f"  • <b>Risk Allocation:</b> <code>${risk_amount:,.2f}</code> (Balance: N/A)")
        else:
            lines.append("  • <b>Risk Allocation:</b> <code>N/A</code>")
        if risk_warning:
            lines.append(f"  ⚠️ <b>Risk Alert:</b> <code>{escape_html(risk_warning)}</code>")
        is_executable = getattr(rp, "is_executable", None)
        if is_executable is False:
            raw_lots = getattr(rp, "raw_lot_size", None)
            min_risk = getattr(rp, "min_lot_risk_usd", None)
            raw_str = f", raw {raw_lots:.6f}" if raw_lots is not None else ""
            min_str = f", min-lot loss ${min_risk:,.2f}" if min_risk is not None else ""
            lines.append(
                f"  ℹ️ <b>INFORMATIONAL ONLY</b> — volume below broker minimum"
                f"{raw_str}{min_str}. No executable paper trade."
            )

    # 6. Pillar Breakdown — momentum pillars for BTC, SMC pillars for XAU.
    bd = getattr(signal, "score_breakdown", None)
    if bd is not None:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        if is_btc:
            lines.append("🏛 <b>Momentum Pillars:</b>")

            def _pts(key: str, cap: float) -> str:
                value = meta.get(key) if isinstance(meta, dict) else None
                return f"{float(value):.0f}/{cap:.0f}" if value is not None else "N/A"

            lines.append(f"  • EMA Trend: <code>{_pts('trend_score', 40.0)}</code>")
            lines.append(f"  • RSI Momentum: <code>{_pts('rsi_score', 35.0)}</code>")
            lines.append(f"  • Price Location: <code>{_pts('location_score', 25.0)}</code>")
            lines.append(f"  • Total Momentum Score: <code>{score_str}</code>")
        else:
            lines.append("🏛 <b>Pillar Breakdown:</b>")
            struct = f"{bd.structure_score:.0f}/35" if getattr(bd, "structure_score", None) is not None else "N/A"
            liq = f"{bd.liquidity_score:.0f}/40" if getattr(bd, "liquidity_score", None) is not None else "N/A"
            pa = f"{bd.price_action_score:.0f}/25" if getattr(bd, "price_action_score", None) is not None else "N/A"
            lines.append(f"  • Structure &amp; MTF: <code>{struct}</code>")
            lines.append(f"  • Liquidity &amp; POIs: <code>{liq}</code>")
            lines.append(f"  • Price Action: <code>{pa}</code>")
            if getattr(bd, "indicators_score", 0) > 0:
                lines.append(f"  • Indicators (Aux): <code>{bd.indicators_score:.0f}/25</code>")

    # 7. Key Confluence Catalysts
    reasons = getattr(signal, "reasons", None) or ctx.catalysts or []
    if reasons:
        lines.append("━━━━━━━━━━━━━━━━━━━━\n💡 <b>Key Confluence Catalysts:</b>")
        for r in reasons[:4]:
            lines.append(f"  ✓ {escape_html(r)}")

    # 7b. Warnings / Path Advisory
    warnings = getattr(signal, "warnings", None) or getattr(ctx, "warnings", None) or []
    if warnings:
        lines.append("━━━━━━━━━━━━━━━━━━━━\n⚠️ *Path Advisory:*")
        for w in warnings:
            lines.append(f"  • {escape_html(w)}")

    # 8. News Blackout Status
    blackout_status = ctx.news_blackout_status
    if not blackout_status:
        if getattr(signal, "blackout_blocked", False):
            blackout_status = "⚠️ BLOCKED - High Impact Macro Blackout"
        else:
            blackout_status = "✅ CLEAR - No Active Blackout"

    # 9. Signal ID & Timestamps (Strict UTC, zero datetime.now() inside signal formatting)
    sig_id = getattr(signal, "id", None) or getattr(signal, "fingerprint", None) or "N/A"
    sig_time = getattr(signal, "created_at", None) or getattr(signal, "timestamp", None) or ctx.created_at
    if sig_time is not None:
        if sig_time.tzinfo is None:
            sig_time = sig_time.replace(tzinfo=timezone.utc)
        time_str = sig_time.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    else:
        time_str = "N/A"

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        f"🛡 <b>News Blackout Status:</b> <code>{escape_html(blackout_status)}</code>",
        f"🆔 <b>Signal ID:</b> <code>{escape_html(str(sig_id))}</code>",
        f"🕒 <b>Timestamp:</b> <code>{time_str}</code>",
        "⚠️ <i>Rule-based algorithmic analysis only. Manage risk responsibly.</i>",
    ])

    return "\n".join(lines)


class TelegramMessageFormatter:
    """Telegram Message Formatter facade supporting HTML parse_mode with backward compatibility."""

    @staticmethod
    def escape_html(text: Any) -> str:
        return escape_html(text)

    @staticmethod
    def escape_markdown(text: Any, version: int = 1) -> str:
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
        return TelegramMessageFormatter.escape_markdown(text, version=2)

    @staticmethod
    def escape_code(text: Any) -> str:
        if text is None:
            return ""
        return str(text).replace("`", "'")

    @staticmethod
    def format_price(price: Optional[float], symbol: str) -> str:
        return format_price(price, symbol)

    @staticmethod
    def calculate_pips(entry: float, target: float, symbol: str) -> float:
        return calculate_pips(entry, target, symbol)

    @classmethod
    def format_signal_alert(cls, sig: SignalResponse) -> str:
        """Format signal alert via the pure format_signal engine."""
        return format_signal(sig)

    @staticmethod
    def _analysis_number(value: Any) -> Optional[float]:
        """NaN/None/strings -> None so a missing value can never break HTML."""
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if number == number and abs(number) != float("inf") else None

    @classmethod
    def format_technical_analysis(
        cls,
        analysis: Any,
        thesis: Optional[str] = None,
    ) -> str:
        """Render the shared confluence payload as a Telegram (HTML) block.

        Accepts either the dict returned by ``calculate_technical_confluence``
        or an object with the same attributes. Every field is optional: missing
        values render as ``N/A`` instead of raising or printing ``nan``.
        """
        if analysis is None:
            return "📉 <b>Indicators:</b> <code>N/A</code>"

        def get(key: str) -> Any:
            if isinstance(analysis, dict):
                return analysis.get(key)
            return getattr(analysis, key, None)

        symbol = str(get("symbol") or "N/A")
        timeframe = str(get("timeframe") or "1h")
        normalized = symbol
        try:
            normalized = normalize_symbol(symbol)
        except UnknownSymbolError:
            pass

        price = cls._analysis_number(get("price"))
        score = cls._analysis_number(get("score"))
        ema_20 = cls._analysis_number(get("ema_20"))
        ema_50 = cls._analysis_number(get("ema_50"))
        rsi = cls._analysis_number(get("rsi"))
        adx = cls._analysis_number(get("adx"))
        trend = str(get("trend") or "NEUTRAL")

        price_str = f"${format_price(price, normalized)}" if price is not None else "N/A"
        score_str = f"{score:.0f}/100" if score is not None else "N/A"

        if "BULLISH_STACK" in trend:
            ema_label = "Bullish Cross"
        elif "BEARISH_STACK" in trend:
            ema_label = "Bearish Cross"
        elif "BULLISH" in trend:
            ema_label = "Bullish Bias"
        elif "BEARISH" in trend:
            ema_label = "Bearish Bias"
        else:
            ema_label = "Neutral / Range"

        if ema_20 is not None and ema_50 is not None:
            ema_label += f" ({format_price(ema_20, normalized)} / {format_price(ema_50, normalized)})"

        if rsi is None:
            rsi_label = "N/A"
        elif rsi < 30.0:
            rsi_label = f"{rsi:.1f} (Oversold)"
        elif rsi > 70.0:
            rsi_label = f"{rsi:.1f} (Overbought)"
        elif rsi < 45.0:
            rsi_label = f"{rsi:.1f} (Bearish Zone)"
        elif rsi > 55.0:
            rsi_label = f"{rsi:.1f} (Bullish Zone)"
        else:
            rsi_label = f"{rsi:.1f} (Neutral)"

        if adx is None:
            adx_label = "N/A"
        elif adx >= 40.0:
            adx_label = f"{adx:.1f} (Very Strong Trend)"
        elif adx >= 25.0:
            adx_label = f"{adx:.1f} (Strong Trend)"
        else:
            adx_label = f"{adx:.1f} (Weak Trend)"

        thesis_text = str(thesis or get("note") or "").strip()
        if not thesis_text:
            if score is not None and score >= 65.0:
                thesis_text = "Confluence confirms the active regime; awaiting a fresh momentum trigger."
            else:
                thesis_text = "Awaiting fresh RSI/EMA momentum crossover with ADX regime confirmation."

        lines = [
            f"📊 <b>QuantView Signal: {escape_html(symbol)}</b> <code>[{escape_html(timeframe.upper())}]</code>",
            f"💰 <b>Price:</b> <code>{escape_html(price_str)}</code>",
            f"📈 <b>Confluence Score:</b> <code>{escape_html(score_str)}</code>",
            "",
            "📉 <b>Indicators:</b>",
            f"  • <b>EMA 20/50:</b> <code>{escape_html(ema_label)}</code>",
            f"  • <b>RSI (14):</b> <code>{escape_html(rsi_label)}</code>",
            f"  • <b>ADX (14):</b> <code>{escape_html(adx_label)}</code>",
            "",
            "🧠 <b>AI Thesis:</b>",
            f'  <i>"{escape_html(thesis_text)}"</i>',
        ]
        return "\n".join(lines)

    @classmethod
    def format_auto_execution(
        cls, trade: PaperTradeResponse, target_account: Optional[str] = None
    ) -> str:
        """Immediate notification for a scanner-created paper position.

        Values are read from the executed trade / live config — no hardcoded
        price, lot, or R:R literals. ``target_account`` comes from the signal's
        metadata ("MAIN"/"CENT"); the symbol routing rule is the fallback.
        """
        direction = getattr(trade.direction, "value", trade.direction)
        symbol = str(trade.symbol)
        lot = float(trade.initial_position_size)
        rr = f"{float(settings.MIN_RR_TP1):g}"
        account = str(target_account or target_account_for_symbol(symbol)).upper()
        is_btc = normalize_symbol(symbol) == "BTC/USD"
        icon = "🟢" if direction == "BUY" else "🔴"
        strategy_tag = "BTC MOMENTUM" if is_btc else "SMC CONFLUENCE"
        return (
            f"{icon} {strategy_tag} {escape_html(direction)} | Account: <code>{escape_html(account)}</code>\n"
            f"🤖 AUTO-EXECUTED: {escape_html(direction)} {escape_html(symbol)} "
            f"@ {cls.format_price(trade.entry_price, symbol)} "
            f"| SL: {cls.format_price(trade.stop_loss, symbol)} "
            f"| TP: {cls.format_price(trade.take_profit_1, symbol)} "
            f"| Lot: {lot:.2f} | R:R 1:{rr}"
        )

    @classmethod
    def format_trade_rejection(
        cls,
        sig: SignalResponse,
        reason: str,
        hints: Optional[Dict[str, str]] = None,
    ) -> str:
        """Compact alert with the exact capital/risk lever for a rejected signal."""
        sym = getattr(sig, "symbol", "N/A")
        try:
            sym = normalize_symbol(sym)
        except UnknownSymbolError:
            pass
        direction_val = getattr(sig, "direction", None)
        dir_str = (
            direction_val.value
            if isinstance(direction_val, SignalDirection)
            else str(direction_val or "N/A").upper()
        )
        score = getattr(sig, "setup_score", None)
        score_str = f"{score:.1f} / 100" if score is not None else "N/A"
        lines = [
            "⚠️ <b>TRADE REJECTED — RISK BUDGET</b> ⚠️",
            "━━━━━━━━━━━━━━━━━━━━",
            f"📊 <b>Instrument:</b> <code>{escape_html(sym)}</code>",
            f"⏱ <b>Timeframe:</b> <code>{escape_html(getattr(sig, 'timeframe', None) or 'N/A')}</code>",
            f"🎯 <b>Direction:</b> <code>{escape_html(dir_str)}</code>",
            f"⭐ <b>Confluence Score:</b> <code>{score_str}</code>",
            "━━━━━━━━━━━━━━━━━━━━",
        ]
        hints = hints or {}
        hint_lines: List[str] = []
        if hints.get("stop"):
            hint_lines.append(f"📏 <b>Stop:</b> <code>{escape_html(hints['stop'])}</code>")
        if hints.get("lots"):
            hint_lines.append(f"📐 <b>Lots:</b> <code>{escape_html(hints['lots'])}</code>")
        if hints.get("max_stop"):
            context = hints.get("budget_context")
            suffix = f" ({escape_html(context)})" if context else ""
            hint_lines.append(
                f"🎯 <b>Max affordable stop:</b> <code>{escape_html(hints['max_stop'])}</code>{suffix}"
            )
        if hints.get("required_balance"):
            hint_lines.append(
                f"💰 <b>Balance needed for this stop:</b> "
                f"<code>{escape_html(hints['required_balance'])}</code>"
            )
        if hints.get("min_lot_risk"):
            hint_lines.append(
                f"📉 <b>Min lot would risk:</b> <code>{escape_html(hints['min_lot_risk'])}</code>"
            )
        if hints.get("context"):
            hint_lines.append(f"🧾 <b>Context:</b> <code>{escape_html(hints['context'])}</code>")
        if hints.get("levels"):
            hint_lines.append(f"📍 <b>Levels:</b> <code>{escape_html(hints['levels'])}</code>")
        if hints.get("broker"):
            hint_lines.append(f"🏦 <b>Broker:</b> <code>{escape_html(hints['broker'])}</code>")
        lines.extend(hint_lines)
        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━",
            f"⚠️ <b>Trade Rejected:</b> <code>{escape_html(reason)}</code>",
            "No paper position was opened — raise balance or risk % to afford this stop.",
        ])
        return "\n".join(lines)

    @classmethod
    def format_tp1_hit(
        cls,
        symbol: str,
        price: float,
        realized_pnl: float,
        new_sl: float,
        closed_lots: Optional[float] = None,
        remaining_lots: Optional[float] = None,
        timestamp: Optional[datetime] = None,
    ) -> str:
        """Format Take Profit 1 reached lifecycle notification."""
        sym = escape_html(symbol)
        formatted_price = format_price(price, symbol)
        formatted_sl = format_price(new_sl, symbol)
        lots_str = f"Closed {closed_lots:.2f} lots" if closed_lots is not None else "Closed 50% lots"
        runner_str = f"{remaining_lots:.2f} lots active" if remaining_lots is not None else "Remaining lots active"
        ts_str = (
            timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if timestamp
            else "N/A"
        )
        return (
            f"🎯 <b>TAKE PROFIT 1 REACHED!</b> 🎯\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Pair:</b> <code>{sym}</code>\n"
            f"💰 <b>Exit Price:</b> <code>{formatted_price}</code>\n"
            f"💵 <b>Locked-in Profit:</b> <code>+${realized_pnl:,.2f}</code>\n"
            f"🔒 <b>Action Taken:</b> <code>{lots_str}. Stop Loss moved to Break-Even ({formatted_sl})</code>\n"
            f"🏃 <b>Runner:</b> <code>{runner_str} for TP2 target.</code>\n"
            f"🕒 <code>{ts_str}</code>"
        )

    @classmethod
    def format_tp2_hit(
        cls,
        symbol: str,
        price: float,
        total_pnl: float,
        return_r: float,
        closed_lots: Optional[float] = None,
        timestamp: Optional[datetime] = None,
    ) -> str:
        """Format Take Profit 2 reached lifecycle notification."""
        sym = escape_html(symbol)
        formatted_price = format_price(price, symbol)
        lots_str = f" ({closed_lots:.2f} lots)" if closed_lots is not None else ""
        ts_str = (
            timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if timestamp
            else "N/A"
        )
        return (
            f"🏆 <b>TAKE PROFIT 2 TARGET HIT!</b> 🏆\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Pair:</b> <code>{sym}</code>\n"
            f"💰 <b>Exit Price:</b> <code>{formatted_price}</code>\n"
            f"💵 <b>Total Realized PnL:</b> <code>+${total_pnl:,.2f}</code>\n"
            f"📈 <b>Payoff Return:</b> <code>+{return_r:.2f} R-Multiple</code>\n"
            f"🎉 <b>Status:</b> <code>Trade fully completed{lots_str} with maximum target profit!</code>\n"
            f"🕒 <code>{ts_str}</code>"
        )

    @classmethod
    def format_take_profit_hit(
        cls,
        symbol: str,
        price: float,
        total_pnl: float,
        return_r: float,
        closed_lots: Optional[float] = None,
        timestamp: Optional[datetime] = None,
    ) -> str:
        """Format a generic winning exit (e.g. a full exit at TP1 with no TP2).

        Wins must never be announced as stop-losses. This template is used
        whenever a position closes at a take-profit target but neither the
        partial TP1 nor the TP2-specific template applies.
        """
        sym = escape_html(symbol)
        formatted_price = format_price(price, symbol)
        pnl_str = (
            f"+${abs(total_pnl):,.2f}" if total_pnl >= 0
            else f"-${abs(total_pnl):,.2f}"
        )
        r_str = f"{return_r:+.2f}R"
        lots_str = f" ({closed_lots:.2f} lots)" if closed_lots is not None else ""
        ts_str = (
            timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if timestamp
            else "N/A"
        )
        return (
            f"🎯 <b>TAKE PROFIT HIT</b> 🎯\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Pair:</b> <code>{sym}</code>\n"
            f"💰 <b>Exit Price:</b> <code>{formatted_price}</code>\n"
            f"💵 <b>Realized PnL:</b> <code>{pnl_str}</code>\n"
            f"📈 <b>R-Multiple:</b> <code>{r_str}</code>\n"
            f"🎉 <b>Status:</b> <code>Position closed{lots_str} at take profit.</code>\n"
            f"🕒 <code>{ts_str}</code>"
        )

    @classmethod
    def format_sl_hit(
        cls,
        symbol: str,
        price: float,
        loss_pnl: float,
        is_be: bool,
        closed_lots: Optional[float] = None,
        return_r: Optional[float] = None,
        timestamp: Optional[datetime] = None,
    ) -> str:
        """Format Stop Loss / Break-Even lifecycle notification."""
        tag = "⚡ <b>BREAK-EVEN STOP TRIGGERED</b>" if is_be else "🛑 <b>STOP LOSS HIT</b>"
        pnl_str = f"${loss_pnl:,.2f}" if loss_pnl >= 0 else f"-${abs(loss_pnl):,.2f}"
        sym = escape_html(symbol)
        formatted_price = format_price(price, symbol)
        lots_str = f" ({closed_lots:.2f} lots)" if closed_lots is not None else ""
        r_str = f" | R-Multiple: <code>{return_r:+.2f}R</code>" if return_r is not None else ""
        ts_str = (
            timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if timestamp
            else "N/A"
        )
        return (
            f"{tag}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Pair:</b> <code>{sym}</code>\n"
            f"📍 <b>Exit Price:</b> <code>{formatted_price}</code>\n"
            f"💵 <b>Realized PnL:</b> <code>{pnl_str}</code>{r_str}\n"
            f"🛡 <b>Capital Protected:</b> <code>Position closed{lots_str} per strict risk rules.</code>\n"
            f"🕒 <code>{ts_str}</code>"
        )

    @classmethod
    def format_market_scan_summary(cls, scan_result: MarketScanResponse) -> str:
        """Format full multi-symbol unified market scanner digest."""
        ts_str = (
            scan_result.timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if scan_result.timestamp
            else "N/A"
        )
        lines = [
            "📡 <b>UNIFIED SCANNER DIGEST</b> 📡",
            "━━━━━━━━━━━━━━━━━━━━",
            f"🕒 <b>Scan Time:</b> <code>{ts_str}</code>",
            f"🔍 <b>Markets Scanned:</b> <code>{scan_result.scanned_count}</code> | 🎯 <b>Actionable:</b> <code>{scan_result.actionable_count}</code>",
            "━━━━━━━━━━━━━━━━━━━━",
        ]

        for r in scan_result.results:
            dir_icon = "🟢" if r.direction == SignalDirection.BUY else ("🔴" if r.direction == SignalDirection.SELL else "⚪")
            status_text = f"<b>{escape_html(r.direction.value)}</b> (Score: <code>{r.setup_score:.0f}/100</code>)"

            if getattr(r, "trend_alignment", None):
                status_text += f" <code>[{escape_html(r.trend_alignment)}]</code>"
            elif r.direction == SignalDirection.WAIT and getattr(r, "htf_trend", None):
                status_text += f" <code>[1H {escape_html(r.htf_trend)}]</code>"

            if r.blackout_blocked:
                status_text += " <code>[NEWS BLOCKED]</code>"

            sym = escape_html(r.symbol)
            tf_display = "1H" if r.timeframe.lower() == "1h" else r.timeframe
            tf = escape_html(tf_display)

            # Per-instrument strategy + its own validated threshold, so a BTC
            # row is never shown with SMC's global 60 floor.
            canonical = r.symbol
            try:
                canonical = normalize_symbol(r.symbol)
            except UnknownSymbolError:
                pass
            is_btc = canonical == "BTC/USD"
            strategy_name = (
                getattr(getattr(r, "signal", None), "strategy_name", None)
                or ("BTC Momentum" if is_btc else "Strategy A (SMC Sniper)")
            )
            threshold = 85.0 if is_btc else float(settings.MIN_SETUP_SCORE)
            strat_badge = (
                f" <code>[{escape_html(strategy_name)} | &gt;= {threshold:g}]</code>"
            )

            lines.append(f"{dir_icon} <code>{sym}</code> [{tf}] ➔ {status_text}{strat_badge}")

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━",
            "💡 <i>Type /signal &lt;pair&gt; for deep multi-timeframe analysis.</i>",
        ])
        return "\n".join(lines)

    @classmethod
    def format_economic_news_alert(cls, events: List[NewsEventResponse]) -> str:
        """Format scheduled economic news alerts."""
        lines = [
            "📰 <b>ECONOMIC CALENDAR & NEWS MONITOR</b> 📰",
            "━━━━━━━━━━━━━━━━━━━━",
        ]
        if not events:
            lines.append("✅ <b>No high or medium impact events scheduled today.</b>")
            return "\n".join(lines)

        for ev in events[:5]:
            impact_icon = "🔴" if ev.impact.upper() == "HIGH" else "🟡"
            curr = escape_html(ev.currency)
            ev_name = escape_html(ev.event_name)
            fc = escape_html(ev.forecast or 'N/A')
            prev = escape_html(ev.previous or 'N/A')
            sched_str = ev.scheduled_time.strftime('%H:%M UTC') if ev.scheduled_time else 'N/A'
            lines.append(
                f"{impact_icon} <b>({curr})</b> <code>{ev_name}</code>\n"
                f"   ⏰ <code>{sched_str}</code> | Forecast: <code>{fc}</code> | Prior: <code>{prev}</code>"
            )

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━",
            "🛡 <i>Trading automatically pauses before high-impact releases.</i>",
        ])
        return "\n".join(lines)

    @classmethod
    def format_news_unavailable_alert(cls, reason: Optional[str] = None) -> str:
        """Format alert when economic calendar is unreachable."""
        return (
            "⚠️ <b>NEWS DATA UNAVAILABLE</b> ⚠️\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "❌ <b>Live economic calendar feed is currently unreachable.</b>\n"
            "🛡 <b>FAIL-SAFE ACTIVATED:</b> New trade generation is safely paused to protect capital until economic news feed is restored.\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ <i>Institutional Capital Protection Rule</i>"
        )

    @classmethod
    def format_multi_strategy_alert(cls, signals: List[Any]) -> str:
        """Format multi-strategy confluence or conflict alert."""
        if not signals:
            return "No signals provided."
        directions = {getattr(s, "direction", None) for s in signals}
        is_conflict = len(directions) > 1
        title = "⚠️ <b>STRATEGY CONFLICT DETECTED</b>" if is_conflict else "🔥 <b>STRATEGY CONFLUENCE CONFIRMED</b>"
        lines = [title, "━━━━━━━━━━━━━━━━━━━━"]
        for s in signals:
            strat = escape_html(getattr(s, "strategy_name", "Unknown Strategy") or "Unknown Strategy")
            dir_val = getattr(s, "direction", "N/A")
            dir_str = dir_val.value if hasattr(dir_val, "value") else str(dir_val)
            score = getattr(s, "setup_score", 0.0) or getattr(s, "confluence_score", 0.0) or 0.0
            lines.append(f"• <b>{strat}</b>: <code>{dir_str}</code> (Score: <code>{score:.1f}/100</code>)")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    @classmethod
    def format_portfolio_summary(
        cls, acc: VirtualAccountResponse, perf: PaperPortfolioPerformance, timestamp: Optional[datetime] = None
    ) -> str:
        """Format virtual account portfolio overview."""
        acc_name = escape_html(acc.name)
        ts_str = (
            timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if timestamp
            else "N/A"
        )
        return (
            f"🏛️ <b>QUANTVIEW MASTER FUND</b> 🏛️\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Account:</b> <code>{acc_name}</code>\n"
            f"💵 <b>Balance:</b> <code>${acc.balance:>10,.2f}</code>\n"
            f"📈 <b>Equity:</b>  <code>${acc.equity:>10,.2f}</code>\n"
            f"📊 <b>Floating PnL:</b> <code>${acc.floating_pnl:>+9,.2f}</code>\n"
            f"🔒 <b>Margin Used:</b>  <code>${acc.margin_used:>10,.2f}</code> (Level: <code>{acc.margin_level_pct:.1f}%</code>)\n"
            f"🆓 <b>Free Margin:</b>  <code>${acc.free_margin:>10,.2f}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 <b>Trading Performance:</b>\n"
            f"  • <b>Total Return:</b> <code>{perf.total_return_pct:>+6.2f}%</code>\n"
            f"  • <b>Win Rate:</b> <code>{perf.win_rate:.1f}%</code> ({perf.winning_trades}W / {perf.losing_trades}L)\n"
            f"  • <b>Profit Factor:</b> <code>{perf.profit_factor:.2f}</code>\n"
            f"  • <b>Active Positions:</b> <code>{perf.open_trades}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕒 <code>{ts_str}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "ℹ️ <i>You are viewing the automated Master Signal Account. "
            "Trades are executed live by the QuantView engine.</i>"
        )

    @staticmethod
    def format_help_menu(active_symbols: Optional[List[str]] = None) -> str:
        """Format bot command help menu."""
        symbols_str = ", ".join(active_symbols) if active_symbols else "Configured Markets"
        return (
            "🤖 <b>FOREX SIGNAL BOT - COMMAND MENU</b> 🤖\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 <code>/scan</code> - Scan active markets ({escape_html(symbols_str)})\n"
            "🔐 <code>/login</code> - Open your authenticated QuantView dashboard\n"
            "🔄 <code>/sync</code> - Force fresh market data sync\n"
            "🎯 <code>/signal &lt;pair&gt;</code> - Deep setup analysis (e.g. <code>/signal XAU/USD</code>)\n"
            "📰 <code>/news</code> - Economic calendar &amp; news blackout check\n"
            "💼 <code>/account</code> - View the Master Fund balance and equity\n"
            "📊 <code>/positions</code> - See the Master Fund's currently open trades\n"
            "🏆 <code>/performance</code> - View the Master Fund track record and win rate\n"
            "📈 <code>/backtest &lt;pair&gt;</code> - Historical strategy simulation\n"
            "❓ <code>/help</code> - Show this command reference\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ <i>Institutional Rule-Based Market Analysis &amp; Risk Management</i>"
        )
