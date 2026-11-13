"""Candle Integrity Diagnostics & Contamination Cleanup Script.

Audits the database for:
1. Misaligned candle timestamps (second != 0 or minute % timeframe != 0, including sub-seconds).
2. Overlapping / duplicate bars (timestamp - LAG(timestamp) < timeframe_delta).

When invoked with `--clean`, safely purges:
- Non-XAU/USD junk symbols (e.g., BTC/USD, USD/JPY, XAUUSD, etc.)
- Sub-second / misaligned candle rows
"""

import argparse
import os
import sys
from typing import Dict, List, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Ensure UTF-8 stdout on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import ACTIVE_SYMBOLS, settings
from app.core.logging import logger
from app.models.candle import Candle


def get_db_engine(db_url: str = None):
    """Create SQLAlchemy engine for the specified or default database URL."""
    url = db_url or settings.DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    return create_engine(url, connect_args=connect_args)


def run_audit(engine) -> Tuple[Dict[Tuple[str, str], int], Dict[Tuple[str, str], int]]:
    """Execute audit queries and return counts for misaligned and overlapping candles.

    Returns:
        (misaligned_counts, overlapping_counts) mapped by (symbol, timeframe).
    """
    is_sqlite = engine.dialect.name == "sqlite"

    # Query 1: Misaligned candles (second != 0 or minute % tf != 0)
    if is_sqlite:
        misaligned_sql = text("""
            SELECT symbol, timeframe, count(*) AS cnt
            FROM candles
            WHERE (
                CAST(strftime('%f', timestamp) AS REAL) != 0
                OR (timeframe = '15m' AND (CAST(strftime('%M', timestamp) AS INTEGER) % 15 != 0))
                OR (timeframe = '30m' AND (CAST(strftime('%M', timestamp) AS INTEGER) % 30 != 0))
                OR (timeframe = '1h' AND (CAST(strftime('%M', timestamp) AS INTEGER) != 0))
                OR (timeframe = '4h' AND (CAST(strftime('%M', timestamp) AS INTEGER) != 0 OR CAST(strftime('%H', timestamp) AS INTEGER) % 4 != 0))
                OR (timeframe = '1d' AND (CAST(strftime('%M', timestamp) AS INTEGER) != 0 OR CAST(strftime('%H', timestamp) AS INTEGER) != 0))
            )
            GROUP BY symbol, timeframe
            ORDER BY symbol, timeframe
        """)
    else:
        # PostgreSQL
        misaligned_sql = text("""
            SELECT symbol, timeframe, count(*) AS cnt
            FROM candles
            WHERE (
                EXTRACT(SECOND FROM timestamp) != 0
                OR EXTRACT(MICROSECOND FROM timestamp) != 0
                OR (timeframe = '15m' AND (EXTRACT(MINUTE FROM timestamp)::integer % 15 != 0))
                OR (timeframe = '30m' AND (EXTRACT(MINUTE FROM timestamp)::integer % 30 != 0))
                OR (timeframe = '1h' AND (EXTRACT(MINUTE FROM timestamp)::integer != 0))
                OR (timeframe = '4h' AND (EXTRACT(MINUTE FROM timestamp)::integer != 0 OR EXTRACT(HOUR FROM timestamp)::integer % 4 != 0))
                OR (timeframe = '1d' AND (EXTRACT(MINUTE FROM timestamp)::integer != 0 OR EXTRACT(HOUR FROM timestamp)::integer != 0))
            )
            GROUP BY symbol, timeframe
            ORDER BY symbol, timeframe
        """)

    # Query 2: Overlapping bars (timestamp - LAG(timestamp) < tf_delta)
    if is_sqlite:
        overlapping_sql = text("""
            WITH lagged AS (
                SELECT id, symbol, timeframe, timestamp,
                       LAG(timestamp) OVER (PARTITION BY symbol, timeframe ORDER BY timestamp) AS prev_ts
                FROM candles
            )
            SELECT symbol, timeframe, count(*) AS cnt
            FROM lagged
            WHERE prev_ts IS NOT NULL AND (strftime('%s', timestamp) - strftime('%s', prev_ts)) < CASE timeframe
                WHEN '15m' THEN 900
                WHEN '30m' THEN 1800
                WHEN '1h' THEN 3600
                WHEN '4h' THEN 14400
                WHEN '1d' THEN 86400
                ELSE 900
            END
            GROUP BY symbol, timeframe
            ORDER BY symbol, timeframe
        """)
    else:
        # PostgreSQL
        overlapping_sql = text("""
            WITH lagged AS (
                SELECT id, symbol, timeframe, timestamp,
                       LAG(timestamp) OVER (PARTITION BY symbol, timeframe ORDER BY timestamp) AS prev_ts
                FROM candles
            )
            SELECT symbol, timeframe, count(*) AS cnt
            FROM lagged
            WHERE prev_ts IS NOT NULL AND EXTRACT(EPOCH FROM (timestamp - prev_ts)) < CASE timeframe
                WHEN '15m' THEN 900
                WHEN '30m' THEN 1800
                WHEN '1h' THEN 3600
                WHEN '4h' THEN 14400
                WHEN '1d' THEN 86400
                ELSE 900
            END
            GROUP BY symbol, timeframe
            ORDER BY symbol, timeframe
        """)

    misaligned_counts = {}
    overlapping_counts = {}

    with engine.connect() as conn:
        for row in conn.execute(misaligned_sql).fetchall():
            misaligned_counts[(row[0], row[1])] = row[2]

        for row in conn.execute(overlapping_sql).fetchall():
            overlapping_counts[(row[0], row[1])] = row[2]

    return misaligned_counts, overlapping_counts


def print_audit_report(
    misaligned_counts: Dict[Tuple[str, str], int],
    overlapping_counts: Dict[Tuple[str, str], int],
    total_rows: int,
):
    """Print formatted diagnostic summary table."""
    all_keys = sorted(set(list(misaligned_counts.keys()) + list(overlapping_counts.keys())))

    print("=" * 80)
    print(" CANDLE DATA INTEGRITY & CONTAMINATION AUDIT REPORT")
    print("=" * 80)
    print(f"Total Candles in Database: {total_rows}")
    print("-" * 80)
    print(f"{'Symbol':<15} {'Timeframe':<10} {'Misaligned':<15} {'Overlapping':<15} {'Total Faults':<15}")
    print("-" * 80)

    total_misaligned = sum(misaligned_counts.values())
    total_overlapping = sum(overlapping_counts.values())

    if not all_keys:
        print("  [OK] No contamination detected! Database candles are clean and aligned.")
    else:
        for sym, tf in all_keys:
            m_cnt = misaligned_counts.get((sym, tf), 0)
            o_cnt = overlapping_counts.get((sym, tf), 0)
            faults = m_cnt + o_cnt
            print(f"{sym:<15} {tf:<10} {m_cnt:<15} {o_cnt:<15} {faults:<15}")

    print("-" * 80)
    print(f"{'TOTAL CONTAMINATIONS':<26} {total_misaligned:<15} {total_overlapping:<15} {total_misaligned + total_overlapping:<15}")
    print("=" * 80)


def execute_cleanup(engine) -> Dict[str, int]:
    """Purge non-XAU/USD junk symbols and misaligned sub-second rows."""
    is_sqlite = engine.dialect.name == "sqlite"
    summary = {"junk_symbols_deleted": 0, "misaligned_deleted": 0}

    with engine.begin() as conn:
        # 1. Delete non-XAU/USD junk symbols (BTC/USD, USD/JPY, XAUUSD, etc.)
        junk_del_sql = text("DELETE FROM candles WHERE symbol != 'XAU/USD'")
        res_junk = conn.execute(junk_del_sql)
        summary["junk_symbols_deleted"] = res_junk.rowcount

        # 2. Delete misaligned sub-second rows
        if is_sqlite:
            clean_misaligned_sql = text("""
                DELETE FROM candles
                WHERE (
                    CAST(strftime('%f', timestamp) AS REAL) != 0
                    OR (timeframe = '15m' AND (CAST(strftime('%M', timestamp) AS INTEGER) % 15 != 0))
                    OR (timeframe = '30m' AND (CAST(strftime('%M', timestamp) AS INTEGER) % 30 != 0))
                    OR (timeframe = '1h' AND (CAST(strftime('%M', timestamp) AS INTEGER) != 0))
                    OR (timeframe = '4h' AND (CAST(strftime('%M', timestamp) AS INTEGER) != 0 OR CAST(strftime('%H', timestamp) AS INTEGER) % 4 != 0))
                    OR (timeframe = '1d' AND (CAST(strftime('%M', timestamp) AS INTEGER) != 0 OR CAST(strftime('%H', timestamp) AS INTEGER) != 0))
                )
            """)
        else:
            clean_misaligned_sql = text("""
                DELETE FROM candles
                WHERE (
                    EXTRACT(SECOND FROM timestamp) != 0
                    OR EXTRACT(MICROSECOND FROM timestamp) != 0
                    OR (timeframe = '15m' AND (EXTRACT(MINUTE FROM timestamp)::integer % 15 != 0))
                    OR (timeframe = '30m' AND (EXTRACT(MINUTE FROM timestamp)::integer % 30 != 0))
                    OR (timeframe = '1h' AND (EXTRACT(MINUTE FROM timestamp)::integer != 0))
                    OR (timeframe = '4h' AND (EXTRACT(MINUTE FROM timestamp)::integer != 0 OR EXTRACT(HOUR FROM timestamp)::integer % 4 != 0))
                    OR (timeframe = '1d' AND (EXTRACT(MINUTE FROM timestamp)::integer != 0 OR EXTRACT(HOUR FROM timestamp)::integer != 0))
                )
            """)

        res_misaligned = conn.execute(clean_misaligned_sql)
        summary["misaligned_deleted"] = res_misaligned.rowcount

    return summary


def main():
    parser = argparse.ArgumentParser(description="Audit and clean candle database contamination.")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Execute database purge of non-XAU/USD junk symbols and misaligned candle rows.",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Optional database URL override (default: from settings.DATABASE_URL).",
    )
    args = parser.parse_args()

    engine = get_db_engine(args.db_url)
    dialect = engine.dialect.name
    print(f"[*] Connected to database: {engine.url.render_as_string(hide_password=True)} [dialect: {dialect}]")

    with engine.connect() as conn:
        total_rows = conn.execute(text("SELECT count(*) FROM candles")).scalar() or 0

    misaligned, overlapping = run_audit(engine)
    print_audit_report(misaligned, overlapping, total_rows)

    if args.clean:
        print("\n[*] Running database cleanup (--clean flag supplied)...")
        cleanup_res = execute_cleanup(engine)
        print(f"  • Deleted non-XAU/USD junk rows: {cleanup_res['junk_symbols_deleted']}")
        print(f"  • Deleted misaligned / sub-second rows: {cleanup_res['misaligned_deleted']}")
        print("✅ Cleanup transaction committed successfully.\n")

        # Post-cleanup audit
        with engine.connect() as conn:
            new_total = conn.execute(text("SELECT count(*) FROM candles")).scalar() or 0
        post_misaligned, post_overlapping = run_audit(engine)
        print_audit_report(post_misaligned, post_overlapping, new_total)
    else:
        print("\n[i] Dry-run audit complete. Pass --clean flag to execute deletion of junk & misaligned rows.")


if __name__ == "__main__":
    main()
