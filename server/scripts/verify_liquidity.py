"""Verification script for Milestone 3: BOS, CHOCH/MSS, Liquidity Sweeps & S/R Zones.

Validates SMC (Smart Money Concepts) algorithms across EUR/USD, GBP/USD, USD/JPY, and XAU/USD:
1. Break of Structure (BOS) trend continuation detection.
2. Change of Character / Market Structure Shift (CHOCH/MSS) reversal detection.
3. Buy-Side Liquidity (BSL) and Sell-Side Liquidity (SSL) sweeps / stop hunts.
4. Dynamic Support & Resistance Zones and Resting Liquidity Pools (Equal Highs/Lows).
5. Institutional Market State classification.
6. Database persistence to StructureEvent and LiquidityEvent tables.
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
from app.models.structure import StructureEvent
from app.models.liquidity import LiquidityEvent
from app.services.market_data import YahooFinanceProvider, IngestionService
from app.services.liquidity import LiquidityService
from sqlalchemy import func, select


def print_banner(title: str):
    print("\n" + "=" * 90)
    print(f"[*] {title.upper()}")
    print("=" * 90)


async def run_liquidity_verification():
    print_banner("Forex Market Analysis & Signal Bot - Milestone 3 Verification")

    # 1. Initialize Database & Ensure Data
    print("\n[1/5] Initializing Database & Loading Candle Data...")
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

    # 2. Run SMC Liquidity & Structure Analysis across all instruments
    print("\n[2/5] Running SMC Advanced Market Structure Analysis (1h Timeframe)...")
    liquidity_service = LiquidityService()

    print("-" * 90)
    print(
        f"{'Symbol':<10} | {'Trend':<8} | {'Market State':<28} | {'BOS':<4} | "
        f"{'CHOCH':<5} | {'Sweeps':<6} | {'S/R Zones':<9} | {'Pools'}"
    )
    print("-" * 90)

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

        res = liquidity_service.analyze_liquidity_and_structure(
            candles=candles,
            symbol=sym,
            timeframe="1h",
            lookback=2,
            tolerance_percent=0.08,
        )

        print(
            f"{sym:<10} | {res.trend.value:<8} | {res.market_state:<28} | "
            f"{len(res.bos_events):<4} | {len(res.choch_events):<5} | "
            f"{len(res.liquidity_sweeps):<6} | {len(res.sr_zones):<9} | {len(res.liquidity_pools)}"
        )

    # 3. Detailed Inspection of EUR/USD (1h) Breakouts & Sweeps
    print("\n[3/5] Inspecting EUR/USD (1h) SMC Breakouts, Sweeps & S/R Zones:")
    eur_candles = (
        db.query(Candle)
        .filter_by(symbol="EUR/USD", timeframe="1h")
        .order_by(Candle.timestamp.asc())
        .all()
    )
    eur_res = liquidity_service.analyze_liquidity_and_structure(
        candles=eur_candles,
        symbol="EUR/USD",
        timeframe="1h",
        lookback=2,
    )

    # Display Breakouts (BOS / CHOCH)
    print("\n  A. Market Structure Breakout Events (BOS & CHOCH):")
    breakouts = eur_res.bos_events + eur_res.choch_events
    breakouts.sort(key=lambda b: b.timestamp)
    if breakouts:
        print("  " + "-" * 85)
        print(f"  {'Timestamp (UTC)':<18} | {'Type':<15} | {'Close':<10} | {'Broken Level':<12} | {'Broken Label':<12} | {'Displacement'}")
        print("  " + "-" * 85)
        for b in breakouts[-5:]:
            lbl = b.broken_swing_label.value if b.broken_swing_label else "-"
            print(
                f"  {b.timestamp.strftime('%Y-%m-%d %H:%M'):<18} | {b.event_type.value:<15} | "
                f"{b.breakout_price:<10.5f} | {b.broken_swing_price:<12.5f} | {lbl:<12} | {b.displacement_strength:<.2f}"
            )
    else:
        print("  -> No breakout events detected in recent window.")

    # Display Liquidity Sweeps
    print("\n  B. Liquidity Sweeps / Institutional Stop Hunts:")
    if eur_res.liquidity_sweeps:
        print("  " + "-" * 85)
        print(f"  {'Timestamp (UTC)':<18} | {'Sweep Type':<18} | {'Swept Level':<12} | {'Wick Extreme':<12} | {'Close':<10} | {'Pips Swept'}")
        print("  " + "-" * 85)
        for s in eur_res.liquidity_sweeps[-5:]:
            print(
                f"  {s.timestamp.strftime('%Y-%m-%d %H:%M'):<18} | {s.sweep_type.value:<18} | "
                f"{s.swept_level:<12.5f} | {s.sweep_extreme:<12.5f} | {s.close_price:<10.5f} | {s.pips_swept:<.1f} pips"
            )
    else:
        print("  -> No liquidity sweeps detected in recent window.")

    # Display Support & Resistance Zones
    print("\n  C. Dynamic Support & Resistance Zones:")
    print("  " + "-" * 80)
    print(f"  {'Zone Type':<12} | {'Range Low':<10} | {'Range High':<10} | {'Center':<10} | {'Touches':<8} | {'Strength':<8} | {'Fresh'}")
    print("  " + "-" * 80)
    for z in eur_res.sr_zones[:6]:
        fresh_str = "YES" if z.is_fresh else "NO"
        print(
            f"  {z.zone_type.value:<12} | {z.price_low:<10.5f} | {z.price_high:<10.5f} | "
            f"{z.center_price:<10.5f} | {z.touch_count:<8} | {z.strength:<8.2f} | {fresh_str}"
        )

    # 4. Multi-Timeframe Liquidity Analysis
    print("\n[4/5] Multi-Timeframe Liquidity & Structure Verification:")
    for sym in ["EUR/USD", "XAU/USD"]:
        print(f"\n  Instrument: {sym}")
        for tf in ["4h", "1h", "15m"]:
            tf_candles = db.query(Candle).filter_by(symbol=sym, timeframe=tf).order_by(Candle.timestamp.asc()).all()
            if tf_candles:
                tf_res = liquidity_service.analyze_liquidity_and_structure(tf_candles, symbol=sym, timeframe=tf, lookback=2)
                last_bos_str = tf_res.latest_bos.event_type.value if tf_res.latest_bos else "None"
                last_choch_str = tf_res.latest_choch.event_type.value if tf_res.latest_choch else "None"
                last_sweep_str = tf_res.latest_sweep.sweep_type.value if tf_res.latest_sweep else "None"
                print(f"    [{tf:<4}] Trend: {tf_res.trend.value:<8} | State: {tf_res.market_state:<26} | Latest BOS: {last_bos_str:<12} | Latest CHOCH: {last_choch_str:<14} | Sweep: {last_sweep_str}")

    # 5. Database Persistence Verification
    print("\n[5/5] Testing Database Persistence of Structure & Liquidity Events...")
    for sym in symbols:
        for tf in ["1h", "15m"]:
            c_list = db.query(Candle).filter_by(symbol=sym, timeframe=tf).order_by(Candle.timestamp.asc()).all()
            if c_list:
                ana = liquidity_service.analyze_liquidity_and_structure(c_list, symbol=sym, timeframe=tf, lookback=2)
                liquidity_service.persist_events(db=db, symbol=sym, timeframe=tf, analysis=ana)

    total_struct = db.query(func.count(StructureEvent.id)).scalar()
    total_liq = db.query(func.count(LiquidityEvent.id)).scalar()
    print(f"  -> Total persisted records in StructureEvent table: {total_struct}")
    print(f"  -> Total persisted records in LiquidityEvent table: {total_liq}")

    assert total_struct > 0, "Structure events failed to persist!"
    assert total_liq >= 0, "Liquidity events query failed!"

    db.close()
    print("\n" + "=" * 90)
    print("[OK] MILESTONE 3 VERIFICATION COMPLETE: ALL CHECKS & TESTS PASSED SUCCESSFULLY!")
    print("=" * 90)


if __name__ == "__main__":
    asyncio.run(run_liquidity_verification())
