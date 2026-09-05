import hashlib
from datetime import datetime, timezone
from typing import List, Optional
import httpx

from app.core.logging import logger
from app.core.normalization import normalize_utc_datetime
from app.schemas.news import NewsEventCreate, NewsImpact
from app.services.news.base import BaseNewsProvider


class ForexFactoryProvider(BaseNewsProvider):
    """Fetches real-time economic calendar events from public JSON feeds."""

    CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout_seconds = timeout_seconds

    @property
    def is_live_provider(self) -> bool:
        return True

    @staticmethod
    def _parse_impact(raw_impact: str) -> NewsImpact:
        """Parse raw impact string to NewsImpact enum."""
        imp = raw_impact.strip().lower()
        if "high" in imp or "red" in imp:
            return NewsImpact.HIGH
        elif "medium" in imp or "orange" in imp:
            return NewsImpact.MEDIUM
        return NewsImpact.LOW

    @staticmethod
    def generate_fingerprint(currency: str, event_name: str, scheduled_time: datetime) -> str:
        """Generate deterministic SHA-256 fingerprint for event deduplication."""
        c = currency.upper().strip()
        name = event_name.strip().lower()
        ts = normalize_utc_datetime(scheduled_time)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        payload = f"{c}:{name}:{ts_str}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def fetch_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        currencies: Optional[List[str]] = None,
    ) -> List[NewsEventCreate]:
        """Fetch economic calendar events from live feed with retries and synthetic fallback."""
        max_retries = 3

        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            for attempt in range(1, max_retries + 1):
                try:
                    response = await client.get(self.CALENDAR_URL)
                    if response.status_code == 200:
                        data = response.json()
                        events: List[NewsEventCreate] = []

                        for item in data:
                            curr = item.get("country", "").upper().strip()
                            title = item.get("title", "").strip()
                            raw_impact = item.get("impact", "")
                            date_str = item.get("date", "")

                        if not title or not date_str:
                            continue

                            # Parse ISO timestamp
                            try:
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
                                    previous=str(item.get("previous")) if item.get("previous") is not None else None,
                                    forecast=str(item.get("forecast")) if item.get("forecast") is not None else None,
                                    actual=str(item.get("actual")) if item.get("actual") is not None else None,
                                )
                            )

                        logger.info(f"Successfully fetched {len(events)} economic events from ForexFactory feed.")
                        return events
                    else:
                        logger.warning(
                            f"ForexFactory HTTP {response.status_code} on attempt {attempt}/{max_retries}"
                        )
                except Exception as e:
                    logger.warning(f"ForexFactory attempt {attempt}/{max_retries} failed: {e}")
                
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        logger.warning("ForexFactory live feed unreachable after retries. Using deterministic mock fallback.")
        return await self.mock_fallback.fetch_events(
            start_time=start_time,
            end_time=end_time,
            currencies=currencies,
        )
