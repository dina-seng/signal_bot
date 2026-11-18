"""Historical data backfill script for Twelve Data candles.

Pulls XAU/USD 15m and 1h candles from Twelve Data for the SMC calibration window
(2025-01-01 to 2025-05-21) and saves them to a local SQLite database for fast replay.

Usage:
    python server/scripts/backfill_calibration.py
    python server/scripts/backfill_calibration.py --timeframes 15min 1h --db-path server/backtest.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import requests

# Ensure server package can be imported from any working directory
REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

try:
    from app.core.config import settings
except ImportError:
    settings = None  # type: ignore


TIMEFRAME_MAP: Dict[str, Tuple[str, str]] = {
    "15m": ("15m", "15min"),
    "15min": ("15m", "15min"),
    "1h": ("1h", "1h"),
    "60m": ("1h", "1h"),
    "4h": ("4h", "4h"),
    "1d": ("1d", "1day"),
}


def resolve_timeframe(tf_str: str) -> Tuple[str, str]:
    """Resolve input timeframe string into (db_timeframe, twelvedata_interval).
    
    Examples:
        '15min' -> ('15m', '15min')
        '15m'   -> ('15m', '15min')
        '1h'    -> ('1h', '1h')
    """
    normalized = tf_str.strip().lower()
    if normalized in TIMEFRAME_MAP:
        return TIMEFRAME_MAP[normalized]
    return (tf_str, tf_str)


def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize SQLite database and ensure candles table exists."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol VARCHAR(20) NOT NULL,
            timeframe VARCHAR(10) NOT NULL,
            timestamp DATETIME NOT NULL,
            open FLOAT NOT NULL,
            high FLOAT NOT NULL,
            low FLOAT NOT NULL,
            close FLOAT NOT NULL,
            volume FLOAT NOT NULL DEFAULT 0.0,
            source VARCHAR(50) DEFAULT 'twelvedata',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_symbol_timeframe_timestamp UNIQUE (symbol, timeframe, timestamp)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS ix_candle_query
        ON candles (symbol, timeframe, timestamp)
    """)
    conn.commit()
    return conn


def fetch_twelve_data_page(
    symbol: str,
    interval: str,
    api_key: str,
    start_date: str,
    end_date: str,
    outputsize: int = 5000,
    max_retries: int = 3,
    sleep_between_calls: float = 1.5,
) -> List[Dict[str, Any]]:
    """Fetch a single page of candles from Twelve Data /time_series endpoint.
    
    Handles HTTP 429 rate limits, network timeouts, and JSON error payloads.
    """
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": min(outputsize, 5000),
        "timezone": "UTC",
        "order": "ASC",
        "apikey": api_key,
    }
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                if attempt < max_retries:
                    print(f"[*] HTTP 429 Rate Limit (attempt {attempt}/{max_retries}). Sleeping 60s...")
                    time.sleep(60.0)
                    continue
                raise RuntimeError("Twelve Data HTTP 429 rate limit exceeded after retries.")

            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, dict):
                if data.get("status") == "error" or ("code" in data and data["code"] != 200):
                    err_code = data.get("code")
                    err_msg = data.get("message", "Unknown error")
                    if err_code == 429 or "rate limit" in str(err_msg).lower():
                        if attempt < max_retries:
                            print(f"[*] API Error 429 (attempt {attempt}/{max_retries}): {err_msg}. Sleeping 60s...")
                            time.sleep(60.0)
                            continue
                        raise RuntimeError(f"Twelve Data rate limit error: {err_msg}")
                    raise RuntimeError(f"Twelve Data API error [{err_code}]: {err_msg}")

            return data.get("values", [])
        except (requests.Timeout, requests.ConnectionError) as req_err:
            if attempt < max_retries:
                print(f"[*] Network error on attempt {attempt}: {req_err}. Retrying in 5s...")
                time.sleep(5.0)
                continue
            raise RuntimeError(f"Twelve Data connection failed: {req_err}") from req_err
        finally:
            if sleep_between_calls > 0:
                time.sleep(sleep_between_calls)

    return []


def save_candles_to_db(
    conn: sqlite3.Connection,
    candles: List[Dict[str, Any]],
    symbol: str,
    timeframe: str,
    source: str = "twelvedata",
) -> Tuple[int, int]:
    """Save candle records to SQLite using INSERT OR IGNORE for idempotency.
    
    Returns:
        (inserted_count, skipped_count)
    """
    valid_rows: List[Tuple[Any, ...]] = []
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for c in candles:
        try:
            ts = c["datetime"]
            o = float(c["open"])
            h = float(c["high"])
            l = float(c["low"])
            cl = float(c["close"])
            vol = float(c.get("volume", 0.0) or 0.0)

            # Invariant checks: strictly positive prices and High/Low envelope
            if o <= 0 or h <= 0 or l <= 0 or cl <= 0:
                continue
            if h < l or h < o or h < cl or l > o or l > cl:
                continue

            valid_rows.append((symbol, timeframe, ts, o, h, l, cl, vol, source, now_str))
        except (ValueError, KeyError, TypeError):
            continue

    if not valid_rows:
        return 0, 0

    changes_before = conn.total_changes
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT OR IGNORE INTO candles (
            symbol, timeframe, timestamp, open, high, low, close, volume, source, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        valid_rows,
    )
    conn.commit()
    inserted = conn.total_changes - changes_before
    skipped = len(valid_rows) - inserted
    return inserted, skipped


def backfill_timeframe(
    conn: sqlite3.Connection,
    symbol: str,
    tf_input: str,
    start_date: str,
    end_date: str,
    api_key: str,
    db_name: str = "backtest.db",
    sleep_between_calls: float = 1.5,
) -> Dict[str, Any]:
    """Fetch candles across pages for a single timeframe and persist them."""
    db_tf, interval = resolve_timeframe(tf_input)
    print(f"Fetching {db_tf} data...")

    start_str = f"{start_date} 00:00:00" if len(start_date) == 10 else start_date
    end_str = f"{end_date} 23:59:59" if len(end_date) == 10 else end_date

    current_end = end_str
    total_fetched = 0
    total_inserted = 0
    total_skipped = 0

    while True:
        raw_values = fetch_twelve_data_page(
            symbol=symbol,
            interval=interval,
            api_key=api_key,
            start_date=start_str,
            end_date=current_end,
            outputsize=5000,
            sleep_between_calls=sleep_between_calls,
        )

        if not raw_values:
            break

        count = len(raw_values)
        total_fetched += count
        print(f"Fetched {count} bars")

        print(f"Saving to {db_name}")
        inserted, skipped = save_candles_to_db(
            conn=conn,
            candles=raw_values,
            symbol=symbol,
            timeframe=db_tf,
        )
        total_inserted += inserted
        total_skipped += skipped

        earliest_ts = raw_values[0]["datetime"]

        # Pagination complete when earliest bar meets start window or batch is smaller than outputsize
        if earliest_ts <= start_str or count < 5000:
            break

        if earliest_ts >= current_end:
            break

        current_end = earliest_ts

    return {
        "timeframe": db_tf,
        "fetched": total_fetched,
        "inserted": total_inserted,
        "skipped": total_skipped,
    }


def run_backfill(
    symbol: str = "XAU/USD",
    timeframes: Sequence[str] = ("15min", "1h"),
    start_date: str = "2025-01-01",
    end_date: str = "2025-05-21",
    db_path: Optional[Path] = None,
    api_key: Optional[str] = None,
    sleep_sec: float = 1.5,
) -> Dict[str, Any]:
    """Run full backfill pipeline for the specified symbol, timeframes, and date range."""
    target_api_key = api_key or (getattr(settings, "TWELVE_DATA_API_KEY", None) if settings else None) or os.getenv("TWELVE_DATA_API_KEY")
    if not target_api_key:
        raise ValueError("TWELVE_DATA_API_KEY is not configured in settings or environment.")

    resolved_db_path = db_path or (SERVER_ROOT / "backtest.db")
    db_name = resolved_db_path.name

    conn = init_db(resolved_db_path)
    total_inserted_all = 0
    total_fetched_all = 0

    try:
        for tf in timeframes:
            res = backfill_timeframe(
                conn=conn,
                symbol=symbol,
                tf_input=tf,
                start_date=start_date,
                end_date=end_date,
                api_key=target_api_key,
                db_name=db_name,
                sleep_between_calls=sleep_sec,
            )
            total_fetched_all += res["fetched"]
            total_inserted_all += res["inserted"]

        # Query total bars saved in DB and date range covered
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*), MIN(timestamp), MAX(timestamp)
            FROM candles
            WHERE symbol = ?
            """,
            (symbol,),
        )
        total_saved, min_ts, max_ts = cur.fetchone()

        print(f"\nBackfill Complete:")
        print(f"Total bars saved: {total_saved}")
        print(f"Date range covered: {min_ts} to {max_ts}")

        return {
            "total_fetched": total_fetched_all,
            "total_inserted": total_inserted_all,
            "total_bars_in_db": total_saved,
            "date_range": (min_ts, max_ts),
        }
    finally:
        conn.close()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill XAU/USD 15m and 1h candles from Twelve Data for SMC calibration window."
    )
    parser.add_argument("--symbol", default="XAU/USD", help="Symbol to backfill (default: XAU/USD)")
    parser.add_argument(
        "--timeframes",
        nargs="+",
        default=["15min", "1h"],
        help="Timeframes to backfill (default: 15min 1h)",
    )
    parser.add_argument(
        "--start-date",
        default="2025-01-01",
        help="Calibration start date YYYY-MM-DD (default: 2025-01-01)",
    )
    parser.add_argument(
        "--end-date",
        default="2025-05-21",
        help="Calibration end date YYYY-MM-DD (default: 2025-05-21)",
    )
    parser.add_argument(
        "--db-path",
        default=str(SERVER_ROOT / "backtest.db"),
        help="Path to SQLite database (default: server/backtest.db)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Twelve Data API key (defaults to settings.TWELVE_DATA_API_KEY)",
    )
    parser.add_argument(
        "--sleep-sec",
        type=float,
        default=1.5,
        help="Sleep duration in seconds between API calls (default: 1.5)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db_path)
    run_backfill(
        symbol=args.symbol,
        timeframes=args.timeframes,
        start_date=args.start_date,
        end_date=args.end_date,
        db_path=db_path,
        api_key=args.api_key,
        sleep_sec=args.sleep_sec,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
