"""Database cleanup script to purge removed symbols (EUR/USD, GBP/USD) across all tables."""

import os
import sys
from typing import Dict, List
from sqlalchemy import select, delete

# Ensure UTF-8 stdout on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal, init_db
from app.core.logging import logger
from app.models.candle import Candle
from app.models.signal import Signal
from app.models.paper import PaperTrade, AccountTransaction
from app.models.structure import StructureEvent
from app.models.liquidity import LiquidityEvent
from app.models.backtest import BacktestRun, BacktestTrade

# Canonical and formatted variations of symbols being dropped
REMOVED_SYMBOLS: List[str] = [
    "EUR/USD",
    "GBP/USD",
    "EURUSD",
    "GBPUSD",
    "EUR_USD",
    "GBP_USD",
    "EURUSD=X",
    "GBPUSD=X",
]


def cleanup_removed_symbols(dry_run: bool = False) -> Dict[str, int]:
    """Purge all database records belonging to removed currency pairs.

    Tables cleaned:
    - account_transactions (via linked trade_ids and descriptions)
    - paper_trades
    - candles
    - signals
    - structure_events
    - liquidity_events
    - backtest_trades & backtest_runs (if present)

    Args:
        dry_run: If True, counts matching records without deleting them.

    Returns:
        Dict mapping table name to number of deleted/matched records.
    """
    init_db()
    db = SessionLocal()
    summary: Dict[str, int] = {}

    print("=" * 70)
    print(f"[*] QUANTVIEW DATABASE CLEANUP - PURGING REMOVED SYMBOLS")
    print(f"[*] Target Symbols: {REMOVED_SYMBOLS[:2]} (and canonical aliases)")
    print(f"[*] Execution Mode: {'[DRY RUN - No changes committed]' if dry_run else '[LIVE PURGE]'}")
    print("=" * 70)

    try:
        # 1. Identify paper trades to delete to clean up dependent account transactions
        trade_ids_to_delete = db.scalars(
            select(PaperTrade.id).where(PaperTrade.symbol.in_(REMOVED_SYMBOLS))
        ).all()

        # Clean account_transactions linked to these trades or mentioning the symbols
        tx_query = db.query(AccountTransaction)
        if trade_ids_to_delete:
            tx_filter = AccountTransaction.trade_id.in_(trade_ids_to_delete)
        else:
            tx_filter = False

        tx_count = db.query(AccountTransaction).filter(tx_filter).count() if trade_ids_to_delete else 0
        if not dry_run and trade_ids_to_delete:
            db.query(AccountTransaction).filter(AccountTransaction.trade_id.in_(trade_ids_to_delete)).delete(
                synchronize_session=False
            )
        summary["account_transactions"] = tx_count

        # 2. Clean paper_trades
        pt_count = db.query(PaperTrade).filter(PaperTrade.symbol.in_(REMOVED_SYMBOLS)).count()
        if not dry_run and pt_count > 0:
            db.query(PaperTrade).filter(PaperTrade.symbol.in_(REMOVED_SYMBOLS)).delete(synchronize_session=False)
        summary["paper_trades"] = pt_count

        # 3. Clean candles
        candle_count = db.query(Candle).filter(Candle.symbol.in_(REMOVED_SYMBOLS)).count()
        if not dry_run and candle_count > 0:
            db.query(Candle).filter(Candle.symbol.in_(REMOVED_SYMBOLS)).delete(synchronize_session=False)
        summary["candles"] = candle_count

        # 4. Clean signals
        signal_count = db.query(Signal).filter(Signal.symbol.in_(REMOVED_SYMBOLS)).count()
        if not dry_run and signal_count > 0:
            db.query(Signal).filter(Signal.symbol.in_(REMOVED_SYMBOLS)).delete(synchronize_session=False)
        summary["signals"] = signal_count

        # 5. Clean structure_events
        structure_count = db.query(StructureEvent).filter(StructureEvent.symbol.in_(REMOVED_SYMBOLS)).count()
        if not dry_run and structure_count > 0:
            db.query(StructureEvent).filter(StructureEvent.symbol.in_(REMOVED_SYMBOLS)).delete(synchronize_session=False)
        summary["structure_events"] = structure_count

        # 6. Clean liquidity_events
        liquidity_count = db.query(LiquidityEvent).filter(LiquidityEvent.symbol.in_(REMOVED_SYMBOLS)).count()
        if not dry_run and liquidity_count > 0:
            db.query(LiquidityEvent).filter(LiquidityEvent.symbol.in_(REMOVED_SYMBOLS)).delete(synchronize_session=False)
        summary["liquidity_events"] = liquidity_count

        # 7. Optional cleanup: backtest runs and trades
        bt_trade_count = db.query(BacktestTrade).filter(BacktestTrade.symbol.in_(REMOVED_SYMBOLS)).count()
        if not dry_run and bt_trade_count > 0:
            db.query(BacktestTrade).filter(BacktestTrade.symbol.in_(REMOVED_SYMBOLS)).delete(synchronize_session=False)
        summary["backtest_trades"] = bt_trade_count

        bt_run_count = db.query(BacktestRun).filter(BacktestRun.symbol.in_(REMOVED_SYMBOLS)).count()
        if not dry_run and bt_run_count > 0:
            db.query(BacktestRun).filter(BacktestRun.symbol.in_(REMOVED_SYMBOLS)).delete(synchronize_session=False)
        summary["backtest_runs"] = bt_run_count

        if dry_run:
            db.rollback()
            print("\n[DRY RUN SUMMARY] Matching records identified for deletion:")
        else:
            db.commit()
            print("\n[SUCCESS] Records successfully deleted from database:")

        total_records = 0
        for table_name, count in summary.items():
            print(f"  - {table_name:<24}: {count:>6} rows {'would be deleted' if dry_run else 'deleted'}")
            total_records += count

        print("-" * 70)
        print(f"Total rows {'targeted' if dry_run else 'purged'}: {total_records}")
        print("=" * 70)

        logger.info(f"Database cleanup completed. Total rows purged: {total_records}. Breakdown: {summary}")
        return summary

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Database cleanup failed: {e}")
        logger.error(f"Database cleanup failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    is_dry_run = "--dry-run" in sys.argv
    cleanup_removed_symbols(dry_run=is_dry_run)
