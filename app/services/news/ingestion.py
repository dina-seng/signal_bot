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

        # Ensure all timestamps in UTC
        for e in events:
            if e.scheduled_time.tzinfo is None:
                e.scheduled_time = e.scheduled_time.replace(tzinfo=timezone.utc)
            else:
                e.scheduled_time = e.scheduled_time.astimezone(timezone.utc)

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
            st = sched_t.replace(tzinfo=timezone.utc) if sched_t.tzinfo is None else sched_t.astimezone(timezone.utc)
            existing_set.add((curr, name, st))

        to_insert: List[NewsEvent] = []
        skipped_count = 0

        for e in events:
            key = (e.currency, e.event_name, e.scheduled_time)
            if key in existing_set:
                skipped_count += 1
                continue

            existing_set.add(key)
            to_insert.append(
                NewsEvent(
                    currency=e.currency,
                    event_name=e.event_name,
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
        events = await self.provider.fetch_events(
            start_time=start_time,
            end_time=end_time,
            currencies=currencies,
        )
        return self.ingest_events(events)
