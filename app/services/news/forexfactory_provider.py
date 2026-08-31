"""ForexFactory & Live Economic Calendar Provider."""

from datetime import datetime, timezone
import httpx
from typing import List, Optional
from app.core.logging import logger
from app.schemas.news import NewsEventCreate, NewsImpact
from app.services.news.base import BaseNewsProvider


class ForexFactoryProvider(BaseNewsProvider):
    """Fetches real-time economic calendar events from public JSON feeds."""

    CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout_seconds = timeout_seconds

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
<<<<<<< HEAD
        """Fetch economic calendar events from live feed without injecting mock data on failure."""
        events: List[NewsEventCreate] = []
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True, headers=headers) as client:
                response = await client.get(self.CALENDAR_URL)
                if response.status_code == 200:
                    data = response.json()
                    for item in data:
                        curr = item.get("country", "").upper().strip()
                        title = item.get("title", "").strip()
                        raw_impact = item.get("impact", "")
                        date_str = item.get("date", "")
=======
        """Fetch economic calendar events from live feed with retries, falling back to synthetic data if unreachable."""
        events: List[NewsEventCreate] = []
        max_retries = 3

        for attempt in range(1, max_retries + 1):
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
>>>>>>> 21e941ad997d90ca91056ed5ed23cc52dfdc6f87

                            if not title or not date_str:
                                continue

<<<<<<< HEAD
                        # Parse ISO datetime
                        try:
                            # format e.g. 2026-08-28T08:30:00-04:00
                            dt = datetime.fromisoformat(date_str)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc, microsecond=0)
                            else:
                                dt = dt.astimezone(timezone.utc).replace(microsecond=0)
                        except Exception:
                            continue
=======
                            # Parse ISO datetime
                            try:
                                dt = datetime.fromisoformat(date_str)
                                if dt.tzinfo is None:
                                    dt = dt.replace(tzinfo=timezone.utc)
                                else:
                                    dt = dt.astimezone(timezone.utc)
                            except Exception:
                                continue
>>>>>>> 21e941ad997d90ca91056ed5ed23cc52dfdc6f87

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
                    else:
                        logger.warning(
                            f"ForexFactory HTTP {response.status_code} on attempt {attempt}/{max_retries}"
                        )
<<<<<<< HEAD
                    logger.info(f"Successfully fetched {len(events)} economic events from ForexFactory feed.")
                    return events
                else:
                    logger.warning(
                        f"ForexFactory calendar request returned non-200 status code: {response.status_code}. "
                        "Live economic calendar fetch aborted without mock fallback."
                    )
                    return []
        except Exception as e:
            logger.warning(
                f"Could not fetch live ForexFactory calendar ({e}). Live economic calendar fetch aborted without mock fallback."
            )
            return []
=======
            except Exception as e:
                logger.warning(f"ForexFactory attempt {attempt}/{max_retries} failed: {e}")
                if attempt < max_retries:
                    import asyncio
                    await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        logger.warning("ForexFactory live feed unreachable after retries. Using deterministic mock fallback.")
        # Fallback to mock calendar
        return await self.mock_fallback.fetch_events(
            start_time=start_time,
            end_time=end_time,
            currencies=currencies,
        )
>>>>>>> 21e941ad997d90ca91056ed5ed23cc52dfdc6f87
