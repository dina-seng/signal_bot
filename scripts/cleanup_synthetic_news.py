"""Database maintenance script to purge synthetic mock news events from production database."""

import os
import sys
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
from app.models.news import NewsEvent
from app.core.logging import logger


MOCK_EVENT_NAMES = {
    "FOMC Member Speech",
    "German Prelim CPI m/m",
    "GDP m/m",
    "Non-Farm Employment Change (NFP)",
    "Unemployment Rate",
    "ECB Monetary Policy Statement & Rate Decision",
    "BOE Monetary Policy Report",
    "BOJ Press Conference & Policy Rate",
    "CPI m/m & Core CPI",
    "FOMC Statement & Federal Funds Rate",
    "Eurozone Flash Manufacturing PMI",
    "Tokyo Core CPI y/y",
    "Retail Sales m/m",
    "Claimant Count Change",
}


def purge_synthetic_news(purge_all: bool = False) -> int:
    """Purge synthetic news events from the database.
    
    Args:
        purge_all: If True, deletes all news events. If False, only deletes events matching synthetic patterns.
    """
    init_db()
    db = SessionLocal()
    try:
        if purge_all:
            count = db.query(NewsEvent).delete()
        else:
            # Delete events matching synthetic templates or with microsecond timestamps
            deleted_ids = []
            events = db.scalars(select(NewsEvent)).all()
            for ev in events:
                is_synthetic_template = ev.event_name in MOCK_EVENT_NAMES
                has_microsecond = ev.scheduled_time.microsecond > 0
                if is_synthetic_template or has_microsecond:
                    deleted_ids.append(ev.id)
            
            if deleted_ids:
                count = db.query(NewsEvent).filter(NewsEvent.id.in_(deleted_ids)).delete(synchronize_session=False)
            else:
                count = 0

        db.commit()
        print(f"[OK] Successfully purged {count} synthetic news events from database.")
        logger.info(f"Purged {count} synthetic news events from database.")
        return count
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Failed purging synthetic news events: {e}")
        logger.error(f"Failed purging synthetic news events: {e}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    purge_all_flag = "--all" in sys.argv
    purge_synthetic_news(purge_all=purge_all_flag)
