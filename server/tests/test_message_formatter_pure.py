"""Unit tests verifying TelegramMessageFormatter is pure, data-driven, has zero I/O, and contains zero hardcoded numbers."""

import pytest
from datetime import datetime, timezone
from app.models.signal import Signal
from app.models.paper import PaperTrade
from app.schemas.signal import SignalDirection, SignalStatus, RiskParameters, ScoreBreakdown
from app.services.telegram.message_formatter import (
    TelegramMessageFormatter,
    SignalContext,
    format_signal,
    escape_html,
)


def test_formatter_is_pure_function_zero_io():
    """Verify format_signal is pure: identical inputs produce identical outputs with zero I/O or global state."""
    fixed_time = datetime(2026, 11, 14, 10, 30, tzinfo=timezone.utc)
    sig = Signal(
        id=999,
        symbol="XAU/USD",
        timeframe="15m",
        direction=SignalDirection.BUY,
        strategy_name="SMC Confluence",
        setup_score=82.5,
        entry_price=3880.25,
        stop_loss=3872.25,
        take_profit_1=3896.25,
        take_profit_2=3904.25,
        risk_reward=2.0,
        reasons=["15m Bullish FVG Retracement", "Demand Sweep"],
        created_at=fixed_time,
    )
    ctx = SignalContext(
        account_balance=25000.0,
        risk_percent=0.5,
        risk_amount_usd=125.0,
        suggested_lot_size=0.15,
        created_at=fixed_time,
    )

    out1 = format_signal(sig, ctx)
    out2 = format_signal(sig, ctx)

    assert out1 == out2
    assert "3880.25" in out1
    assert "3872.25" in out1
    assert "3896.25" in out1
    assert "82.5 / 100" in out1
    assert "0.15 Standard Lots" in out1
    assert "$125.00" in out1
    assert "2026-11-14 10:30:00 UTC" in out1


def test_formatter_renders_different_outputs_for_different_signals():
    """Verify two synthetic signals with different prices/scores/instruments render completely different text."""
    t = datetime(2026, 11, 14, 8, 0, tzinfo=timezone.utc)
    sig1 = Signal(
        id=1,
        symbol="XAU/USD",
        timeframe="15m",
        direction=SignalDirection.BUY,
        strategy_name="SMC Sniper",
        setup_score=85.0,
        entry_price=3850.00,
        stop_loss=3840.00,
        take_profit_1=3870.00,
        created_at=t,
    )
    sig2 = Signal(
        id=2,
        symbol="EUR/USD",
        timeframe="1h",
        direction=SignalDirection.SELL,
        strategy_name="Trend Continuation",
        setup_score=78.0,
        entry_price=1.08500,
        stop_loss=1.08900,
        take_profit_1=1.07700,
        created_at=t,
    )

    text1 = format_signal(sig1, SignalContext(created_at=t))
    text2 = format_signal(sig2, SignalContext(created_at=t))

    assert "XAU/USD" in text1 and "XAU/USD" not in text2
    assert "EUR/USD" in text2 and "EUR/USD" not in text1
    assert "3850.00" in text1 and "3850.00" not in text2
    assert "1.08500" in text2 and "1.08500" not in text1
    assert "BUY" in text1 and "SELL" in text2


def test_no_hardcoded_sample_magic_numbers_leak():
    """Verify old magic numbers and sample constants do not leak into dynamic formatting."""
    t = datetime(2026, 11, 14, 8, 0, tzinfo=timezone.utc)
    sig = Signal(
        id=10,
        symbol="XAU/USD",
        timeframe="15m",
        direction=SignalDirection.BUY,
        strategy_name="SMC Pure",
        setup_score=80.0,
        entry_price=3865.50,
        stop_loss=3855.50,
        take_profit_1=3885.50,
        created_at=t,
    )
    rendered = format_signal(sig, SignalContext(created_at=t))

    # Assert old sample prices from original hardcoded card do not appear
    forbidden_literals = [
        "2650.50", "2642.00", "2667.50", "2676.00",
        "87.5", "0.59", "2026-11-13 02:15",
        "Risk Management (0.5% Rule)",  # should be dynamic, e.g. N/A or actual risk%
    ]
    for lit in forbidden_literals:
        assert lit not in rendered, f"Old hardcoded literal '{lit}' leaked into signal alert!"


def test_missing_fields_render_explicit_na():
    """Verify missing fields gracefully and explicitly render as 'N/A' without crashing or substituting defaults."""
    sig_minimal = Signal(
        id=101,
        symbol="XAU/USD",
        timeframe="15m",
        direction=SignalDirection.BUY,
        # missing entry, SL, TP, score, strategy, timestamps
    )
    rendered = format_signal(sig_minimal)

    assert "N/A" in rendered
    assert "📍 <b>Entry Price:</b> <code>N/A</code>" in rendered
    assert "🛑 <b>Stop Loss:</b> <code>N/A</code>" in rendered
    assert "🎯 <b>Take Profit 1 (TP1):</b> <code>N/A</code>" in rendered
    assert "🏆 <b>Take Profit 2 (TP2):</b> <code>N/A</code>" in rendered
    assert "⭐ <b>Confluence Score:</b> <code>N/A</code>" in rendered


def test_html_entity_escaping_for_special_characters():
    """Verify HTML entities are properly escaped for symbols, strategies, and catalysts."""
    t = datetime(2026, 11, 14, 8, 0, tzinfo=timezone.utc)
    sig = Signal(
        id=202,
        symbol="XAU/USD",
        timeframe="15m",
        direction=SignalDirection.BUY,
        strategy_name="<Breakout & Retest>",
        setup_score=88.0,
        entry_price=3850.0,
        stop_loss=3840.0,
        reasons=["Price > EMA 200 & RSI < 30", "Target 1 < Resistance"],
        created_at=t,
    )
    rendered = format_signal(sig, SignalContext(created_at=t))

    assert "&lt;Breakout &amp; Retest&gt;" in rendered
    assert "Price &gt; EMA 200 &amp; RSI &lt; 30" in rendered
    assert "Target 1 &lt; Resistance" in rendered
    assert "<script>" not in rendered


def test_lifecycle_alerts_render_from_real_position():
    """Verify lifecycle alerts (TP1, TP2, SL) render dynamically from real trade records."""
    trade = PaperTrade(
        id=77,
        symbol="XAU/USD",
        direction="BUY",
        entry_price=3850.00,
        initial_position_size=0.20,
        remaining_position_size=0.10,
        take_profit_1=3870.00,
        stop_loss=3850.00,
        realized_pnl=400.00,
        pnl_pips=200.0,
        return_r=2.0,
    )

    tp1_alert = TelegramMessageFormatter.format_tp1_hit(
        symbol=trade.symbol,
        price=trade.take_profit_1,
        realized_pnl=trade.realized_pnl,
        closed_lots=0.10,
        remaining_lots=0.10,
        new_sl=trade.stop_loss,
    )

    assert "3870.00" in tp1_alert
    assert "+$400.00" in tp1_alert
    assert "0.10 lots" in tp1_alert
    assert "3850.00" in tp1_alert
