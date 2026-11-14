"""Migration script to add `source` column to candles table without dropping tables."""

import sys
import os
from sqlalchemy import create_engine, inspect, text

# Add server directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.core.config import settings


def migrate_source_column(db_url: str = None):
    url = db_url or settings.DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(url, connect_args=connect_args)
    insp = inspect(engine)

    if not insp.has_table("candles"):
        print("[!] No 'candles' table found. Nothing to migrate.")
        return

    cols = [c["name"] for c in insp.get_columns("candles")]
    if "source" in cols:
        print("[OK] 'source' column already exists in 'candles' table.")
        return

    print("[*] Adding 'source' column to 'candles' table (migration, no DROP TABLE)...")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE candles ADD COLUMN source VARCHAR(50) DEFAULT 'twelvedata'"))
        conn.execute(text("UPDATE candles SET source = 'twelvedata' WHERE source IS NULL"))
    print("✅ Successfully added 'source' column with default 'twelvedata'.")


if __name__ == "__main__":
    db_arg = sys.argv[1] if len(sys.argv) > 1 else None
    migrate_source_column(db_arg)
