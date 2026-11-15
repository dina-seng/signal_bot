"""Idempotent, rate-limited, resumable backfill script for Twelve Data 15m XAU/USD candles.

Usage:
    python -m app.scripts.backfill_twelvedata --start 2023-03-01 --end 2026-06-01 --db-path backtest.db
"""

import argparse
import asyncio
from datetime import datetime, timezone
import os
import sys
from typing import List, Set
import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.core.logging import logger
from app.models.candle import Candle
from app.models.api_usage import ApiUsage
from app.services.market_data.freshness import ensure_utc_datetime
from app.services.market_data.twelvedata_provider import (
    TwelveDataProvider,
    get_daily_usage,
)


async def backfill(
    start_str: str,
    end_str: str,
    page_size: int = 5000,
    dry_run: bool = False,
    db_path: str = "backtest.db",
) -> None:
    start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if " " in end_str:
        end_dt = datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    else:
        end_dt = datetime.strptime(end_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)

    # Establish engine and session for targeted db
    if db_path.startswith("sqlite") or db_path.startswith("postgresql"):
        db_url = db_path
    else:
        db_url = f"sqlite:///{db_path}"

    print(f"[*] Starting Twelve Data backfill for XAU/USD [15m]")
    print(f"[*] Target DB: {db_url}")
    print(f"[*] Window: {start_dt.isoformat()} -> {end_dt.isoformat()}")
    print(f"[*] Target page size: {page_size} bars | Dry run: {dry_run}")

    engine_kwargs = {"echo": False}
    if db_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    target_engine = create_engine(db_url, **engine_kwargs)
    Base.metadata.create_all(target_engine)
    TargetSession = sessionmaker(autocommit=False, autoflush=False, bind=target_engine)

    initial_usage = get_daily_usage(TargetSession)
    initial_calls = initial_usage["calls_today"]
    print(f"[*] Initial API Credits today: {initial_calls} / {initial_usage['max_budget']}")

    async with httpx.AsyncClient(timeout=45.0) as http_client:
        provider = TwelveDataProvider(http_client=http_client, session_factory=TargetSession)

        current_end = end_dt
        page_num = 1
        total_inserted = 0
        total_fetched = 0

        while current_end > start_dt:
            print(f"\n--- Page {page_num} (end_date: {current_end.strftime('%Y-%m-%d %H:%M:%S')}) ---", flush=True)
            candles = await provider.fetch_candles(
                symbol="XAU/USD",
                timeframe="15m",
                start_time=start_dt,
                end_time=current_end,
                limit=page_size,
                drop_unclosed=False,
            )

            if not candles:
                print(f"[*] No candles returned for page {page_num}. Backfill complete or reached end of data.", flush=True)
                break

            total_fetched += len(candles)
            earliest_in_page = candles[0].timestamp
            latest_in_page = candles[-1].timestamp
            print(f"[*] Fetched {len(candles)} bars: {earliest_in_page} -> {latest_in_page}", flush=True)

            if not dry_run:
                with TargetSession() as db:
                    existing_stmt = select(Candle.timestamp).where(
                        Candle.symbol == "XAU/USD",
                        Candle.timeframe == "15m",
                        Candle.timestamp >= earliest_in_page,
                        Candle.timestamp <= latest_in_page,
                    )
                    existing_ts = {ensure_utc_datetime(t) for t in db.scalars(existing_stmt).all()}

                    to_insert: List[Candle] = []
                    skipped_duplicates = 0
                    for c in candles:
                        c_ts = ensure_utc_datetime(c.timestamp)
                        if c_ts in existing_ts:
                            skipped_duplicates += 1
                            continue
                        existing_ts.add(c_ts)
                        to_insert.append(
                            Candle(
                                symbol="XAU/USD",
                                timeframe="15m",
                                timestamp=c_ts,
                                open=c.open,
                                high=c.high,
                                low=c.low,
                                close=c.close,
                                volume=c.volume,
                                source="twelvedata",
                            )
                        )

                    if to_insert:
                        db.add_all(to_insert)
                        db.commit()
                        total_inserted += len(to_insert)

                    print(f"[*] Page {page_num} DB result: {len(to_insert)} inserted, {skipped_duplicates} duplicates skipped.", flush=True)

            usage_info = get_daily_usage(TargetSession)
            credits_spent = usage_info["calls_today"] - initial_calls
            print(f"[*] Cumulative API calls today: {usage_info['calls_today']} / {usage_info['max_budget']} (Credits used this session: {credits_spent})", flush=True)

            if earliest_in_page <= start_dt or len(candles) < 10:
                print(f"[*] Reached target start date ({start_dt}).", flush=True)
                break

            if earliest_in_page >= current_end:
                print("[*] Earliest bar equal to or greater than current end; terminating pagination.", flush=True)
                break

            current_end = earliest_in_page
            page_num += 1

        final_usage = get_daily_usage(TargetSession)
        total_credits_used = final_usage["calls_today"] - initial_calls

        print(f"\n[+] Backfill Summary:", flush=True)
        print(f"    Total bars fetched: {total_fetched}", flush=True)
        print(f"    Total bars inserted: {total_inserted}", flush=True)
        print(f"    Pages requested: {page_num}", flush=True)
        print(f"    Credits used in this session: {total_credits_used}", flush=True)
        print(f"    Daily API usage: {final_usage['calls_today']} / {final_usage['max_budget']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Backfill 15m XAU/USD candles from Twelve Data.")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--page-size", type=int, default=5000, help="Candles per request (up to 5000)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report counts without writing to DB")
    parser.add_argument("--db-path", default="backtest.db", help="Path to SQLite database file or database URL")

    args = parser.parse_args()
    asyncio.run(
        backfill(
            args.start,
            args.end,
            page_size=args.page_size,
            dry_run=args.dry_run,
            db_path=args.db_path,
        )
    )


if __name__ == "__main__":
    main()
