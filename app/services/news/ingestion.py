"""Economic news calendar ingestion and database synchronization service."""

from datetime import datetime, timezone
from typing import List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.core.logging import logger
from app.models.news import NewsEvent
from app.schemas.news import NewsEventCreate, NewsSyncReport
from app.services.news.base import BaseNewsProvider


class NewsIngestionService:
    """Ingests, cleans, deduplicates, and persists economic news calendar events."""

    def __init__(self, provider: BaseNewsProvider, db: Session):
        self.provider = provider
        self.db = db

    def ingest_events(self, events: List[NewsEventCreate]) -> NewsSyncReport:
        """Process and persist economic calendar events with deduplication."""
        fetched_count = len(events)
        if not events:
            return NewsSyncReport(
                fetched_count=0,
                inserted_count=0,
                skipped_count=0,
            )

        # Ensure all timestamps in UTC with microseconds stripped
        for e in events:
            if e.scheduled_time.tzinfo is None:
                e.scheduled_time = e.scheduled_time.replace(tzinfo=timezone.utc, microsecond=0)
            else:
                e.scheduled_time = e.scheduled_time.astimezone(timezone.utc).replace(microsecond=0)

        min_time = min(e.scheduled_time for e in events)
        max_time = max(e.scheduled_time for e in events)

        # Query existing records in timestamp window
        stmt = select(NewsEvent.currency, NewsEvent.event_name, NewsEvent.scheduled_time).where(
            NewsEvent.scheduled_time >= min_time,
            NewsEvent.scheduled_time <= max_time,
        )
        existing_rows = self.db.execute(stmt).all()
        existing_set: Set[tuple] = set()

        for curr, name, sched_t in existing_rows:
            st = sched_t.replace(tzinfo=timezone.utc, microsecond=0) if sched_t.tzinfo is None else sched_t.astimezone(timezone.utc).replace(microsecond=0)
            existing_set.add((curr.upper().strip(), name.strip(), st))

        to_insert: List[NewsEvent] = []
        skipped_count = 0

        for e in events:
            curr_clean = e.currency.upper().strip()
            name_clean = e.event_name.strip()
            key = (curr_clean, name_clean, e.scheduled_time)
            if key in existing_set:
                skipped_count += 1
                continue

            existing_set.add(key)
            to_insert.append(
                NewsEvent(
                    currency=curr_clean,
                    event_name=name_clean,
                    impact=e.impact.value,
                    scheduled_time=e.scheduled_time,
                    previous=e.previous,
                    forecast=e.forecast,
                    actual=e.actual,
                )
            )

        if to_insert:
            self.db.add_all(to_insert)
            self.db.commit()
            logger.info(
                f"Successfully persisted {len(to_insert)} new economic calendar events. Skipped {skipped_count} duplicates."
            )

        return NewsSyncReport(
            fetched_count=fetched_count,
            inserted_count=len(to_insert),
            skipped_count=skipped_count,
            start_time=min_time,
            end_time=max_time,
        )

    async def sync_calendar(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        currencies: Optional[List[str]] = None,
    ) -> NewsSyncReport:
        """Fetch from configured news provider and ingest into database."""
        try:
            events = await self.provider.fetch_events(
                start_time=start_time,
                end_time=end_time,
                currencies=currencies,
            )
            return self.ingest_events(events)
        except Exception as e:
            logger.error(f"Error syncing economic news calendar: {e}")
            return NewsSyncReport(
                fetched_count=0,
                inserted_count=0,
                skipped_count=0,
            )
