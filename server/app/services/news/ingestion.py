"""Economic news calendar ingestion and database synchronization service."""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, desc
from sqlalchemy.exc import IntegrityError

from app.core.logging import logger
from app.core.normalization import normalize_utc_datetime
from app.models.news import NewsEvent
from app.schemas.news import NewsEventCreate, NewsSyncReport
from app.services.market_data.freshness import is_forex_weekend
from app.services.news.base import BaseNewsProvider


def generate_event_fingerprint(currency: str, event_name: str, scheduled_time: datetime) -> str:
    """Generate deterministic SHA-256 fingerprint for event identity and deduplication."""
    c = currency.upper().strip()
    name = event_name.strip().lower()
    ts = normalize_utc_datetime(scheduled_time)
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
    payload = f"{c}:{name}:{ts_str}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class NewsIngestionService:
    """Ingests, cleans, deduplicates, and persists economic news calendar events."""

    def __init__(self, provider: BaseNewsProvider, db: Session):
        self.provider = provider
        self.db = db
        self._last_sync_time: Optional[datetime] = None
        self._last_sync_status: str = "INITIAL"
        self._last_sync_error: Optional[str] = None

    @staticmethod
    def generate_fingerprint(currency: str, event_name: str, scheduled_time: datetime) -> str:
        return generate_event_fingerprint(currency, event_name, scheduled_time)

    def ingest_events(self, events: List[NewsEventCreate]) -> NewsSyncReport:
        """Process and persist economic calendar events with atomic deduplication and updates."""
        fetched_count = len(events)
        is_live = getattr(self.provider, "is_live_provider", True)

        if not events:
            return NewsSyncReport(
                fetched_count=0,
                inserted_count=0,
                skipped_count=0,
                updated_count=0,
                status="SUCCESS" if not is_live else "UNAVAILABLE",
                error_message="0 events returned from news provider",
                is_live_provider=is_live,
            )

        # Ensure all timestamps in UTC and strings normalized
        for e in events:
            e.scheduled_time = normalize_utc_datetime(e.scheduled_time)
            e.currency = e.currency.upper().strip()
            e.event_name = e.event_name.strip()
            if not e.fingerprint:
                e.fingerprint = self.generate_fingerprint(e.currency, e.event_name, e.scheduled_time)

        min_time = min(e.scheduled_time for e in events)
        max_time = max(e.scheduled_time for e in events)

        # Query existing records in timestamp window
        stmt = select(NewsEvent).where(
            NewsEvent.scheduled_time >= min_time,
            NewsEvent.scheduled_time <= max_time,
        )
        existing_models = list(self.db.scalars(stmt).all())
        existing_map: Dict[str, NewsEvent] = {}

        for m in existing_models:
            st = normalize_utc_datetime(m.scheduled_time)
            fp = self.generate_fingerprint(m.currency, m.event_name, st)
            existing_map[fp] = m

        to_insert: List[NewsEvent] = []
        skipped_count = 0
        updated_count = 0
        seen_batch_fps: Set[str] = set()

        for e in events:
            fp = e.fingerprint or self.generate_fingerprint(e.currency, e.event_name, e.scheduled_time)
            if fp in seen_batch_fps:
                skipped_count += 1
                continue
            seen_batch_fps.add(fp)

            if fp in existing_map:
                existing_m = existing_map[fp]
                # Update actual, forecast, or previous if newly available
                changed = False
                if e.actual is not None and existing_m.actual != e.actual:
                    existing_m.actual = e.actual
                    changed = True
                if e.forecast is not None and existing_m.forecast != e.forecast:
                    existing_m.forecast = e.forecast
                    changed = True
                if e.previous is not None and existing_m.previous != e.previous:
                    existing_m.previous = e.previous
                    changed = True
                if hasattr(e.impact, "value") and existing_m.impact != e.impact.value:
                    existing_m.impact = e.impact.value
                    changed = True
                elif isinstance(e.impact, str) and existing_m.impact != e.impact.upper():
                    existing_m.impact = e.impact.upper()
                    changed = True

                if changed:
                    updated_count += 1
                else:
                    skipped_count += 1
                continue

            to_insert.append(
                NewsEvent(
                    currency=e.currency,
                    event_name=e.event_name,
                    impact=e.impact.value if hasattr(e.impact, "value") else str(e.impact).upper(),
                    scheduled_time=e.scheduled_time,
                    previous=e.previous,
                    forecast=e.forecast,
                    actual=e.actual,
                )
            )

        try:
            if to_insert:
                self.db.add_all(to_insert)
            self.db.commit()
            logger.info(
                f"Economic calendar sync: Inserted {len(to_insert)}, Updated {updated_count}, "
                f"Skipped {skipped_count} duplicate events."
            )
        except IntegrityError:
            self.db.rollback()
            logger.warning("Concurrent news ingestion conflict detected. Rolled back safely.")

        self._last_sync_time = datetime.now(timezone.utc)
        self._last_sync_status = "SUCCESS"

        return NewsSyncReport(
            fetched_count=fetched_count,
            inserted_count=len(to_insert),
            skipped_count=skipped_count,
            updated_count=updated_count,
            status="SUCCESS",
            is_live_provider=is_live,
            start_time=min_time,
            end_time=max_time,
        )

    async def sync_calendar(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        currencies: Optional[List[str]] = None,
    ) -> NewsSyncReport:
        """Fetch from configured news provider and ingest into database with error tracking."""
        is_live = getattr(self.provider, "is_live_provider", True)
        try:
            events = await self.provider.fetch_events(
                start_time=start_time,
                end_time=end_time,
                currencies=currencies,
            )
            report = self.ingest_events(events)
            if is_live and report.fetched_count == 0:
                report.status = "UNAVAILABLE"
                report.error_message = "Live provider returned 0 events"
                self._last_sync_status = "UNAVAILABLE"
                self._last_sync_error = report.error_message
            return report
        except Exception as e:
            err_msg = f"Error syncing economic news calendar: {e}"
            logger.error(err_msg)
            self._last_sync_time = datetime.now(timezone.utc)
            self._last_sync_status = "ERROR"
            self._last_sync_error = str(e)
            return NewsSyncReport(
                fetched_count=0,
                inserted_count=0,
                skipped_count=0,
                updated_count=0,
                status="ERROR",
                error_message=str(e),
                is_live_provider=is_live,
            )

    def check_calendar_staleness(
        self,
        reference_time: Optional[datetime] = None,
        lookahead_hours: int = 48,
    ) -> Tuple[bool, str]:
        """Check if the economic calendar in the database is stale or missing upcoming events.
        
        Returns:
            Tuple of (is_stale: bool, description: str)
        """
        ref_time = normalize_utc_datetime(reference_time) or datetime.now(timezone.utc)
        weekend = is_forex_weekend(ref_time)

        # Over the weekend, having no events on Saturday or Sunday before reopen is normal
        if weekend:
            # Check if events exist for the upcoming week
            stmt = select(NewsEvent).where(
                NewsEvent.scheduled_time >= ref_time,
                NewsEvent.scheduled_time <= ref_time + timedelta(days=7),
            )
            count = len(list(self.db.scalars(stmt).all()))
            if count > 0:
                return False, f"Weekend calendar valid ({count} events scheduled for upcoming week)."
            return True, "Weekend calendar has 0 scheduled events for upcoming week."

        # Active market trading days (Mon-Fri)
        window_start = ref_time - timedelta(hours=24)
        window_end = ref_time + timedelta(hours=lookahead_hours)

        stmt = select(NewsEvent).where(
            NewsEvent.scheduled_time >= window_start,
            NewsEvent.scheduled_time <= window_end,
        )
        count = len(list(self.db.scalars(stmt).all()))

        if count == 0:
            return True, f"Economic calendar is stale/empty: 0 events found in window [{window_start.strftime('%Y-%m-%d %H:%M')} to {window_end.strftime('%Y-%m-%d %H:%M')}]."

        return False, f"Economic calendar is fresh ({count} events in active window)."
