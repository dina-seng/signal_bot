"""Data cleanup script with strict safety controls.

Requirements:
(a) Export all candles to a local CSV backup.
(b) Print a dry-run table of what would be deleted:
    - all symbols except XAU/USD
    - all timeframes except 15m for XAU/USD
    - rows with non-aligned timestamps
    - overlapping bars
    - mislabeled sources
(c) Only delete when env CONFIRM_PURGE=yes, then re-backfill 15m from Twelve Data.
(d) source column default 'twelvedata' for rows created by this pipeline.
"""

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set
from sqlalchemy import select, delete

from app.core.database import SessionLocal
from app.models.candle import Candle


def run_cleanup():
    print("=" * 70)
    print("QuantView Phase 1.8 Data Cleanup & Integrity Audit")
    print("=" * 70)

    backup_dir = Path("data/backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"candles_backup_{timestamp_str}.csv"

    with SessionLocal() as db:
        print(f"[*] Step (a): Exporting all candles to local CSV backup: {backup_path}")
        stmt = select(Candle).order_by(Candle.symbol, Candle.timeframe, Candle.timestamp)
        all_candles = db.scalars(stmt).all()
        print(f"[*] Found {len(all_candles)} total candle rows in database.")

        with open(backup_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "symbol", "timeframe", "timestamp", "open", "high", "low", "close", "volume", "source"])
            for c in all_candles:
                writer.writerow([
                    c.id, c.symbol, c.timeframe,
                    c.timestamp.isoformat() if c.timestamp else "",
                    c.open, c.high, c.low, c.close, c.volume,
                    getattr(c, "source", "twelvedata")
                ])
        print(f"[+] Backup completed successfully ({backup_path.stat().st_size} bytes).")

        # Step (b): Categorize what would be deleted
        keep_ids: Set[int] = set()
        delete_categories: Dict[str, List[int]] = {
            "Non-XAU/USD symbols": [],
            "Non-15m timeframes (30m, 1h, 4h, 1d)": [],
            "Misaligned 15m timestamps": [],
            "Overlapping / duplicate bars": [],
            "Mislabeled sources": [],
        }

        seen_15m_timestamps: Set[datetime] = set()

        for c in all_candles:
            cid = c.id
            sym = (c.symbol or "").upper()
            tf = (c.timeframe or "").lower()
            ts = c.timestamp
            src = getattr(c, "source", None)

            if sym != "XAU/USD":
                delete_categories["Non-XAU/USD symbols"].append(cid)
                continue

            if tf != "15m":
                delete_categories["Non-15m timeframes (30m, 1h, 4h, 1d)"].append(cid)
                continue

            # 15m XAU/USD row: check alignment (:00, :15, :30, :45 with 00 seconds)
            if ts is None or ts.minute % 15 != 0 or ts.second != 0:
                delete_categories["Misaligned 15m timestamps"].append(cid)
                continue

            if ts in seen_15m_timestamps:
                delete_categories["Overlapping / duplicate bars"].append(cid)
                continue

            if src not in (None, "twelvedata"):
                delete_categories["Mislabeled sources"].append(cid)
                continue

            # This bar meets all criteria
            seen_15m_timestamps.add(ts)
            keep_ids.add(cid)

        total_to_delete = sum(len(ids) for ids in delete_categories.values())
        print("\n" + "-" * 70)
        print("Dry-Run Cleanup Audit Table:")
        print("-" * 70)
        print(f"{'Category':<45} | {'Count':>10}")
        print("-" * 70)
        for cat, ids in delete_categories.items():
            print(f"{cat:<45} | {len(ids):>10}")
        print("-" * 70)
        print(f"{'Total rows to delete':<45} | {total_to_delete:>10}")
        print(f"{'Total clean 15m XAU/USD rows to keep':<45} | {len(keep_ids):>10}")
        print("-" * 70)

        # Step (c): Check CONFIRM_PURGE=yes
        confirm = os.environ.get("CONFIRM_PURGE", "").strip().lower()
        if confirm != "yes":
            print("\n[!] SAFETY STOP: CONFIRM_PURGE != 'yes'.")
            print("[!] No records were deleted. To proceed with deletion, set CONFIRM_PURGE=yes.")
            return

        print("\n[*] CONFIRM_PURGE=yes detected. Executing purge of non-compliant records...")
        all_delete_ids = [cid for ids in delete_categories.values() for cid in ids]
        if all_delete_ids:
            # Batch delete
            batch_size = 500
            for i in range(0, len(all_delete_ids), batch_size):
                batch = all_delete_ids[i:i + batch_size]
                db.execute(delete(Candle).where(Candle.id.in_(batch)))
            db.commit()
            print(f"[+] Purged {len(all_delete_ids)} records from candles table.")
        else:
            print("[*] No records required purging.")


if __name__ == "__main__":
    run_cleanup()
