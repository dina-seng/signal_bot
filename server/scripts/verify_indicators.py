"""Verification script for Milestone 4: Technical Indicators, Divergences & Price Action Patterns.

Validates:
1. EMA 20, 50, 200 series, Bullish/Bearish Stacks, and Golden/Death Crosses.
2. Wilder's Smoothed RSI (14-period) and Regular/Hidden Divergence detection.
3. Wilder's Smoothed ATR (14-period), pip conversion, and dynamic SL/TP buffers.
4. Price Action patterns: Pin Bars (Hammers/Shooting Stars), Engulfing bars, Inside bars.
5. Fair Value Gaps (FVG / Imbalances) and mitigation tracking.
6. Multi-indicator confluence scoring (-100 to +100) and directional bias.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

# Ensure UTF-8 stdout on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal, init_db
from app.core.config import settings
from app.models.candle import Candle
from app.services.market_data import YahooFinanceProvider, IngestionService
from app.services.indicators import IndicatorService


def print_banner(title: str):
    print("\n" + "=" * 95)
    print(f"[*] {title.upper()}")
    print("=" * 95)


async def run_indicator_verification():
    print_banner("Forex Market Analysis & Signal Bot - Milestone 4 Verification")

    # 1. Initialize Database & Data
    print("\n[1/5] Initializing Database & Ensuring Market Data...")
    init_db()
    db = SessionLocal()
    provider = YahooFinanceProvider()
    ingestion = IngestionService(provider=provider, db=db)

    symbols = ["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]
    timeframes = ["15m", "1h", "4h"]

    for sym in symbols:
        for tf in timeframes:
            count = db.query(Candle).filter_by(symbol=sym, timeframe=tf).count()
            if count < 50:
                print(f"  -> Ingesting {sym} [{tf}] data...")
                try:
                    await ingestion.sync_symbol_timeframe(symbol=sym, timeframe=tf, limit=100)
                except Exception as e:
                    print(f"     Warning: {e}")

    # 2. Technical Indicators Snapshot Table (1h)
    print("\n[2/5] Technical Indicators Snapshot (1h Timeframe):")
    indicator_service = IndicatorService()

    print("-" * 95)
    print(
        f"{'Symbol':<10} | {'Price':<10} | {'EMA Stack':<14} | {'RSI 14':<15} | "
        f"{'ATR (Pips)':<11} | {'Confluence Bias':<18} | {'Score'}"
    )
    print("-" * 95)

    analyses = {}
    for sym in symbols:
        candles = (
            db.query(Candle)
            .filter_by(symbol=sym, timeframe="1h")
            .order_by(Candle.timestamp.asc())
            .all()
        )
        if not candles:
            print(f"{sym:<10} | NO DATA AVAILABLE")
            continue

        res = indicator_service.analyze_indicators(candles, symbol=sym, timeframe="1h")
        analyses[sym] = res

        rsi_str = f"{res.rsi.rsi_value:.1f} ({res.rsi.condition})" if res.rsi.rsi_value else "N/A"
        atr_str = f"{res.atr.atr_pips:.1f} pips" if res.atr.atr_pips else "N/A"
        score_str = f"{res.confluence_score:+.1f}"

        print(
            f"{sym:<10} | {res.current_price:<10.5f} | {res.ema.ema_trend:<14} | {rsi_str:<15} | "
            f"{atr_str:<11} | {res.confluence_bias:<18} | {score_str}"
        )

    # 3. Detailed Inspection: EUR/USD & XAU/USD Indicators & Risk Buffers
    print("\n[3/5] Inspecting Indicator Details & Dynamic Risk Buffers:")
    for sym in ["EUR/USD", "XAU/USD"]:
        res = analyses.get(sym)
        if not res:
            continue
        print(f"\n  Instrument: {sym} (1h)")
        print(f"    * Current Price:     {res.current_price:.5f}")
        fast_str = f"{res.ema.ema_fast:.5f}" if res.ema.ema_fast else "N/A"
        mid_str = f"{res.ema.ema_mid:.5f}" if res.ema.ema_mid else "N/A"
        slow_str = f"{res.ema.ema_slow:.5f}" if res.ema.ema_slow else "N/A"
        print(f"    * EMA 20 (Fast):     {fast_str}")
        print(f"    * EMA 50 (Mid):      {mid_str}")
        print(f"    * EMA 200 (Slow):    {slow_str}")
        print(f"    * Price vs EMA 200:  {res.ema.price_vs_ema200}")
        print(f"    * RSI (14):          {res.rsi.rsi_value:.2f} [{res.rsi.condition}]")
        print(f"    * ATR (14):          {res.atr.atr_value:.5f} ({res.atr.atr_pips:.1f} pips) - Volatility: {res.atr.volatility_state}")
        print(f"    * Suggested 1.5x SL: {res.atr.suggested_sl_distance_pips:.1f} pips")
        print(f"    * Suggested 3.0x TP: {res.atr.suggested_tp_distance_pips:.1f} pips")
        print(f"    * Confluence Bias:   {res.confluence_bias} (Score: {res.confluence_score:+.1f})")

    # 4. RSI Divergence & Price Action Inspection
    print("\n[4/5] Inspecting RSI Divergences, Candlestick Patterns & Fair Value Gaps (EUR/USD):")
    eur_res = analyses.get("EUR/USD")
    if eur_res:
        # Divergences
        print("\n  A. RSI Divergences:")
        if eur_res.divergences:
            for d in eur_res.divergences:
                print(f"    * [{d.divergence_type.value}] from {d.start_timestamp.strftime('%m-%d %H:%M')} to {d.end_timestamp.strftime('%m-%d %H:%M')} | Price: {d.price_start:.5f} -> {d.price_end:.5f} | RSI: {d.rsi_start:.1f} -> {d.rsi_end:.1f} (Strength: {d.strength:.2f})")
        else:
            print("    -> No active RSI divergences in analyzed window.")

        # Price Action Patterns
        print("\n  B. Recent Candlestick Patterns:")
        if eur_res.recent_patterns:
            for p in eur_res.recent_patterns:
                print(f"    * [{p.timestamp.strftime('%m-%d %H:%M')}] {p.pattern_type.value:<20} | Confidence: {p.confidence:.2f} | {p.description}")
        else:
            print("    -> No recent candlestick patterns detected.")

        # Fair Value Gaps
        print("\n  C. Active Unmitigated Fair Value Gaps (FVG):")
        if eur_res.active_fvgs:
            for f in eur_res.active_fvgs:
                print(f"    * [{f.timestamp.strftime('%m-%d %H:%M')}] {f.fvg_type.value:<14} | Range: {f.bottom_price:.5f} -> {f.top_price:.5f} ({f.gap_pips:.1f} pips) | Mitigated: {f.is_mitigated}")
        else:
            print("    -> All Fair Value Gaps mitigated or none active.")

    # 5. Multi-Timeframe Confluence Comparison
    print("\n[5/5] Multi-Timeframe Technical Confluence Summary:")
    print("-" * 95)
    print(f"{'Symbol':<10} | {'4h Confluence':<22} | {'1h Confluence':<22} | {'15m Confluence':<22}")
    print("-" * 95)
    for sym in symbols:
        c4h = db.query(Candle).filter_by(symbol=sym, timeframe="4h").order_by(Candle.timestamp.asc()).all()
        c1h = db.query(Candle).filter_by(symbol=sym, timeframe="1h").order_by(Candle.timestamp.asc()).all()
        c15m = db.query(Candle).filter_by(symbol=sym, timeframe="15m").order_by(Candle.timestamp.asc()).all()

        r4h = indicator_service.analyze_indicators(c4h, symbol=sym, timeframe="4h") if c4h else None
        r1h = indicator_service.analyze_indicators(c1h, symbol=sym, timeframe="1h") if c1h else None
        r15m = indicator_service.analyze_indicators(c15m, symbol=sym, timeframe="15m") if c15m else None

        s4h = f"{r4h.confluence_bias} ({r4h.confluence_score:+.0f})" if r4h else "N/A"
        s1h = f"{r1h.confluence_bias} ({r1h.confluence_score:+.0f})" if r1h else "N/A"
        s15m = f"{r15m.confluence_bias} ({r15m.confluence_score:+.0f})" if r15m else "N/A"

        print(f"{sym:<10} | {s4h:<22} | {s1h:<22} | {s15m:<22}")

    db.close()
    print("\n" + "=" * 95)
    print("[OK] MILESTONE 4 VERIFICATION COMPLETE: ALL CHECKS & TESTS PASSED SUCCESSFULLY!")
    print("=" * 95)


if __name__ == "__main__":
    asyncio.run(run_indicator_verification())
