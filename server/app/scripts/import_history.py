"""Import and Resample Historical 1-Minute CSV Data for XAU/USD.

Usage:
    python -m app.scripts.import_history --csv PATH --timeframe-source dukascopy [--db-path backtest.db] [--source-tag dukascopy]

Enforces:
1. Hermetic Isolation: Writes ONLY to an isolated SQLite file (default backtest.db).
   Strictly refuses to touch or write to production Neon DB.
2. Row Invariant Validation: Rejects corrupted rows where high < low or prices <= 0.
3. Multi-timeframe UTC-aligned resampling: 1m -> 15m, 30m, 1h, 4h, 1d.
4. Cleanliness Auditing: Verifies zero misaligned bars, zero overlaps, and reports weekday data gaps (excluding weekends).
"""

import argparse
import csv
from datetime import datetime, timedelta, timezone
import os
import sys
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

# Ensure server root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core.logging import logger
from app.models.candle import Candle
from app.services.market_data.freshness import is_forex_weekend, get_timeframe_delta


DATE_FORMATS = [
    "%d.%m.%Y %H:%M:%S.%f",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y.%m.%d %H:%M:%S.%f",
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
]


def parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse various timestamp formats into a UTC-aware datetime."""
    s = ts_str.strip()
    if not s:
        return None

    # Handle unix epoch integer/float
    try:
        val = float(s)
        # If timestamp is in milliseconds
        if val > 1e11:
            val = val / 1000.0
        return datetime.fromtimestamp(val, tz=timezone.utc)
    except ValueError:
        pass

    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    # Fallback to ISO format
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def align_timestamp(dt: datetime, tf: str) -> datetime:
    """Align a datetime to the start of its timeframe boundary in UTC."""
    t = tf.lower().strip()
    year = dt.year
    month = dt.month
    day = dt.day
    hour = dt.hour
    minute = dt.minute

    if t == "1m":
        return datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)
    elif t == "15m":
        aligned_m = minute - (minute % 15)
        return datetime(year, month, day, hour, aligned_m, 0, tzinfo=timezone.utc)
    elif t == "30m":
        aligned_m = minute - (minute % 30)
        return datetime(year, month, day, hour, aligned_m, 0, tzinfo=timezone.utc)
    elif t == "1h":
        return datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)
    elif t == "4h":
        aligned_h = hour - (hour % 4)
        return datetime(year, month, day, aligned_h, 0, 0, tzinfo=timezone.utc)
    elif t == "1d":
        return datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
    else:
        return datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)


def _parse_single_csv_file(csv_file_path: str) -> Tuple[List[Dict[str, Any]], int]:
    """Parse a single 1-minute CSV file and reject rows violating price invariants."""
    clean_bars: List[Dict[str, Any]] = []
    rejected_count = 0

    with open(csv_file_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return clean_bars, 0

        # Map header columns case-insensitively
        norm_header = [h.strip().lower() for h in header]
        ts_idx = -1
        open_idx = -1
        high_idx = -1
        low_idx = -1
        close_idx = -1
        vol_idx = -1

        for i, col in enumerate(norm_header):
            if any(k in col for k in ("time", "date", "timestamp", "gmt", "local")):
                ts_idx = i
            elif "open" in col:
                open_idx = i
            elif "high" in col:
                high_idx = i
            elif "low" in col:
                low_idx = i
            elif "close" in col:
                close_idx = i
            elif any(k in col for k in ("vol", "volume")):
                vol_idx = i

        if min(ts_idx, open_idx, high_idx, low_idx, close_idx) < 0:
            raise ValueError(
                f"Could not map required OHLC columns in CSV header: {header}. "
                "Expected columns for timestamp, open, high, low, close."
            )

        for row_num, row in enumerate(reader, start=2):
            if not row or len(row) <= max(ts_idx, open_idx, high_idx, low_idx, close_idx):
                continue

            raw_ts = row[ts_idx]
            dt = parse_timestamp(raw_ts)
            if dt is None:
                rejected_count += 1
                continue

            try:
                op = float(row[open_idx])
                hi = float(row[high_idx])
                lo = float(row[low_idx])
                cl = float(row[close_idx])
                vol = float(row[vol_idx]) if vol_idx >= 0 and vol_idx < len(row) and row[vol_idx].strip() else 0.0
            except ValueError:
                rejected_count += 1
                continue

            # Invariant check: high >= low, high >= open, high >= close, low <= open, low <= close, prices > 0
            if (
                hi < lo
                or hi < op
                or hi < cl
                or lo > op
                or lo > cl
                or op <= 0
                or hi <= 0
                or lo <= 0
                or cl <= 0
            ):
                rejected_count += 1
                continue

            # Align 1m bar timestamp to boundary
            aligned_1m = align_timestamp(dt, "1m")
            clean_bars.append({
                "timestamp": aligned_1m,
                "open": op,
                "high": hi,
                "low": lo,
                "close": cl,
                "volume": vol,
            })

    return clean_bars, rejected_count


def parse_and_validate_csv(
    csv_path: str,
) -> Tuple[List[Dict[str, Any]], int]:
    """Parse 1-minute CSV file(s) and reject rows violating price invariants.
    
    Accepts either:
    1. A path to a single .csv file.
    2. A directory containing one or more .csv files.
    
    Returns:
        (clean_1m_bars, rejected_count)
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Path not found: {csv_path}")

    if os.path.isdir(csv_path):
        csv_files = [
            os.path.join(csv_path, f)
            for f in sorted(os.listdir(csv_path))
            if f.lower().endswith(".csv")
        ]
        if not csv_files:
            raise ValueError(
                f"Path '{csv_path}' is a directory containing no .csv files.\n"
                f"Please specify the path to your downloaded 1-minute CSV file, for example:\n"
                f"  python -m app.scripts.import_history --csv D:/trade/xauusd_1m.csv --timeframe-source dukascopy\n"
                f"Or place your .csv file inside '{csv_path}'."
            )
        
        all_bars: List[Dict[str, Any]] = []
        total_rejected = 0
        for cf in csv_files:
            bars, rej = _parse_single_csv_file(cf)
            all_bars.extend(bars)
            total_rejected += rej
        
        all_bars.sort(key=lambda b: b["timestamp"])
        deduped: List[Dict[str, Any]] = []
        seen_ts = set()
        for b in all_bars:
            t = b["timestamp"]
            if t not in seen_ts:
                seen_ts.add(t)
                deduped.append(b)
        return deduped, total_rejected

    clean_bars, rejected_count = _parse_single_csv_file(csv_path)

    # Sort chronologically and deduplicate 1m bars by timestamp
    clean_bars.sort(key=lambda b: b["timestamp"])
    deduped: List[Dict[str, Any]] = []
    seen_ts = set()
    for b in clean_bars:
        t = b["timestamp"]
        if t not in seen_ts:
            seen_ts.add(t)
            deduped.append(b)

    return deduped, rejected_count


def resample_bars(
    clean_1m_bars: List[Dict[str, Any]],
    target_timeframe: str,
) -> List[Dict[str, Any]]:
    """Resample 1-minute bars into a target timeframe (15m, 30m, 1h, 4h, 1d) with UTC-aligned boundaries."""
    if not clean_1m_bars:
        return []

    buckets: Dict[datetime, List[Dict[str, Any]]] = {}
    for bar in clean_1m_bars:
        bucket_ts = align_timestamp(bar["timestamp"], target_timeframe)
        if bucket_ts not in buckets:
            buckets[bucket_ts] = []
        buckets[bucket_ts].append(bar)

    resampled: List[Dict[str, Any]] = []
    for bucket_ts in sorted(buckets.keys()):
        bar_list = buckets[bucket_ts]
        # In-order aggregation
        op = bar_list[0]["open"]
        hi = max(b["high"] for b in bar_list)
        lo = min(b["low"] for b in bar_list)
        cl = bar_list[-1]["close"]
        vol = sum(b["volume"] for b in bar_list)

        resampled.append({
            "timestamp": bucket_ts,
            "open": round(op, 5),
            "high": round(hi, 5),
            "low": round(lo, 5),
            "close": round(cl, 5),
            "volume": round(vol, 2),
        })

    return resampled


def audit_series_cleanliness(
    bars: List[Dict[str, Any]],
    timeframe: str,
) -> Dict[str, Any]:
    """Audit resampled bar series: misalignments, overlaps, and weekday gaps."""
    delta = get_timeframe_delta(timeframe)
    misaligned = 0
    overlaps = 0
    weekday_gaps = 0

    for i, bar in enumerate(bars):
        ts = bar["timestamp"]
        # Misaligned check
        if align_timestamp(ts, timeframe) != ts:
            misaligned += 1

        if i > 0:
            prev_ts = bars[i - 1]["timestamp"]
            spacing = ts - prev_ts
            if spacing < delta:
                overlaps += 1
            elif spacing > delta:
                # Check if this gap is during a Forex weekend (Friday 21:00 UTC - Sunday 21:00 UTC)
                is_weekend_gap = False
                cur_probe = prev_ts + delta
                # If all skipped time is within Forex weekend, it's normal weekend closure
                gap_hours = (ts - prev_ts).total_seconds() / 3600.0
                if 48.0 <= gap_hours <= 52.0 and prev_ts.weekday() == 4 and prev_ts.hour >= 20:
                    is_weekend_gap = True
                elif is_forex_weekend(cur_probe) and is_forex_weekend(ts - timedelta(minutes=1)):
                    is_weekend_gap = True

                if not is_weekend_gap:
                    weekday_gaps += 1

    return {
        "timeframe": timeframe,
        "total_bars": len(bars),
        "misaligned": misaligned,
        "overlaps": overlaps,
        "weekday_gaps": weekday_gaps,
        "first_bar": bars[0]["timestamp"].isoformat() if bars else None,
        "last_bar": bars[-1]["timestamp"].isoformat() if bars else None,
    }


def import_dukascopy_to_sqlite(
    csv_path: str,
    db_path: str = "backtest.db",
    source_tag: str = "dukascopy",
    symbol: str = "XAU/USD",
) -> Dict[str, Any]:
    """Full import pipeline: parse CSV, resample, audit cleanliness, and insert into SQLite backtest.db."""
    # 1. Hermetic Isolation Check: Never write to production/Neon DB
    db_path_clean = db_path.strip()
    if "neon.tech" in db_path_clean.lower() or "postgresql" in db_path_clean.lower():
        raise PermissionError(
            f"REFUSED TO WRITE TO PRODUCTION DATABASE: '{db_path}'. "
            "Import history script strictly writes to isolated SQLite file (e.g. backtest.db)."
        )

    # 2. Parse and Validate 1m CSV
    clean_1m, rejected_rows = parse_and_validate_csv(csv_path)
    if not clean_1m:
        raise ValueError(f"No valid 1-minute candle records found in CSV: {csv_path}")

    # 3. Resample to standard timeframes
    timeframes = ["15m", "30m", "1h", "4h", "1d"]
    resampled_data: Dict[str, List[Dict[str, Any]]] = {}
    audit_reports: Dict[str, Dict[str, Any]] = {}

    for tf in timeframes:
        tf_bars = resample_bars(clean_1m, tf)
        audit = audit_series_cleanliness(tf_bars, tf)
        resampled_data[tf] = tf_bars
        audit_reports[tf] = audit

    # 4. Connect to isolated SQLite DB
    sqlite_url = f"sqlite:///{os.path.abspath(db_path_clean)}"
    engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
    Candle.__table__.create(bind=engine, checkfirst=True)
    SessionMaker = sessionmaker(bind=engine)
    session = SessionMaker()

    # 5. Insert resampled candles in batches
    total_inserted = 0
    try:
        for tf, bars in resampled_data.items():
            db_candles = []
            for b in bars:
                c = Candle(
                    symbol=symbol,
                    timeframe=tf,
                    timestamp=b["timestamp"],
                    open=b["open"],
                    high=b["high"],
                    low=b["low"],
                    close=b["close"],
                    volume=b["volume"],
                    source=source_tag,
                )
                db_candles.append(c)

            # Insert in chunks of 2,000
            chunk_size = 2000
            for k in range(0, len(db_candles), chunk_size):
                chunk = db_candles[k : k + chunk_size]
                session.add_all(chunk)
                session.commit()
                total_inserted += len(chunk)

    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

    return {
        "db_path": db_path_clean,
        "source_tag": source_tag,
        "symbol": symbol,
        "clean_1m_bars": len(clean_1m),
        "rejected_rows": rejected_rows,
        "total_inserted": total_inserted,
        "audit_reports": audit_reports,
    }


def main():
    parser = argparse.ArgumentParser(description="Import historical 1-minute XAU/USD data into backtest.db")
    parser.add_argument("--csv", required=True, help="Path to 1-minute CSV data file")
    parser.add_argument("--timeframe-source", default="dukascopy", help="Source type/format (default: dukascopy)")
    parser.add_argument("--db-path", default="backtest.db", help="Target SQLite file path (default: backtest.db)")
    parser.add_argument("--source-tag", default=None, help="Tag for candle source column (defaults to timeframe-source)")
    parser.add_argument("--symbol", default="XAU/USD", help="Instrument symbol (default: XAU/USD)")

    args = parser.parse_args()
    source_tag = args.source_tag or args.timeframe_source

    print(f"\n=======================================================")
    print(f"📦 HISTORICAL DATA IMPORT & RESAMPLE ENGINE")
    print(f"=======================================================")
    print(f"  • Source CSV:       {args.csv}")
    print(f"  • Provider:         {args.timeframe_source}")
    print(f"  • Target Database:  {args.db_path} (HERMETIC SQLITE)")
    print(f"  • Source Tag:       {source_tag}")
    print(f"  • Symbol:           {args.symbol}")
    print(f"-------------------------------------------------------")

    try:
        res = import_dukascopy_to_sqlite(
            csv_path=args.csv,
            db_path=args.db_path,
            source_tag=source_tag,
            symbol=args.symbol,
        )

        print(f"\n✅ IMPORT SUCCESSFUL!")
        print(f"  • Parsed Clean 1m Bars: {res['clean_1m_bars']:,}")
        print(f"  • Rejected Invariant Rows: {res['rejected_rows']:,}")
        print(f"  • Total Multi-TF Bars Written: {res['total_inserted']:,}")
        print(f"\n📊 RESAMPLED CLEANLINESS AUDIT:")
        print(f"{'TF':<8} {'Bars':<10} {'Misaligned':<12} {'Overlaps':<10} {'Weekday Gaps':<14} {'Range'}")
        print(f"-" * 75)
        for tf, r in res["audit_reports"].items():
            first_t = r['first_bar'][:16] if r['first_bar'] else 'N/A'
            last_t = r['last_bar'][:16] if r['last_bar'] else 'N/A'
            print(f"{tf:<8} {r['total_bars']:<10} {r['misaligned']:<12} {r['overlaps']:<10} {r['weekday_gaps']:<14} {first_t} to {last_t}")
        print(f"=======================================================\n")

    except Exception as e:
        print(f"\n❌ IMPORT FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
