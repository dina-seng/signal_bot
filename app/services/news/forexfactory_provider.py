"""ForexFactory & Live Economic Calendar Provider with robust fallback."""

from datetime import datetime, timezone
import httpx
from typing import List, Optional
from app.core.logging import logger
from app.schemas.news import NewsEventCreate, NewsImpact
from app.services.news.base import BaseNewsProvider
from app.services.news.mock_provider import MockNewsProvider


class ForexFactoryProvider(BaseNewsProvider):
    """Fetches real-time economic calendar events from public JSON feeds with fallback."""

    CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

    def __init__(self, timeout_seconds: float = 8.0):
        self.timeout_seconds = timeout_seconds
        self.mock_fallback = MockNewsProvider(reference_time=datetime.now(timezone.utc))

    @staticmethod
    def _parse_impact(raw_impact: str) -> NewsImpact:
        """Parse raw impact string to NewsImpact enum."""
        imp = raw_impact.strip().lower()
        if "high" in imp or "red" in imp:
            return NewsImpact.HIGH
        elif "medium" in imp or "orange" in imp:
            return NewsImpact.MEDIUM
        return NewsImpact.LOW

    async def fetch_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        currencies: Optional[List[str]] = None,
    ) -> List[NewsEventCreate]:
        """Fetch economic calendar events from live feed, falling back to synthetic data if unreachable."""
        events: List[NewsEventCreate] = []

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = await client.get(self.CALENDAR_URL)
                if response.status_code == 200:
                    data = response.json()
                    for item in data:
                        curr = item.get("country", "").upper().strip()
                        title = item.get("title", "").strip()
                        raw_impact = item.get("impact", "")
                        date_str = item.get("date", "")

                        if not title or not date_str:
                            continue

                        # Parse ISO datetime
                        try:
                            # format e.g. 2026-08-28T08:30:00-04:00
                            dt = datetime.fromisoformat(date_str)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            else:
                                dt = dt.astimezone(timezone.utc)
                        except Exception:
                            continue

                        impact = self._parse_impact(raw_impact)

                        if currencies and curr not in currencies:
                            continue
                        if start_time and dt < start_time:
                            continue
                        if end_time and dt > end_time:
                            continue

                        events.append(
                            NewsEventCreate(
                                currency=curr,
                                event_name=title,
                                impact=impact,
                                scheduled_time=dt,
                                previous=item.get("previous"),
                                forecast=item.get("forecast"),
                                actual=item.get("actual"),
                            )
                        )
                    logger.info(f"Successfully fetched {len(events)} economic events from ForexFactory feed.")
                    return events
        except Exception as e:
            logger.warning(f"Could not fetch live ForexFactory calendar ({e}). Using deterministic mock fallback.")

        # Fallback to mock calendar
        return await self.mock_fallback.fetch_events(
            start_time=start_time,
            end_time=end_time,
            currencies=currencies,
        )
