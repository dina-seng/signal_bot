"""Mock Economic Calendar Provider for deterministic testing and local development."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from app.schemas.news import NewsEventCreate, NewsImpact
from app.services.news.base import BaseNewsProvider


class MockNewsProvider(BaseNewsProvider):
    """Deterministic synthetic economic calendar generator."""

    def __init__(self, reference_time: Optional[datetime] = None):
        ref = reference_time or datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        else:
            ref = ref.astimezone(timezone.utc)
        self.reference_time = ref.replace(microsecond=0)

    @property
    def is_live_provider(self) -> bool:
        return False

    async def fetch_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        currencies: Optional[List[str]] = None,
    ) -> List[NewsEventCreate]:
        """Generate synthetic economic calendar events."""
        base = self.reference_time

        # Standard schedule of realistic major macro events
        event_templates = [
            # Past events (-2 to -1 days)
            ("USD", "FOMC Member Speech", NewsImpact.MEDIUM, base - timedelta(days=2, hours=4), "N/A", "N/A", "N/A"),
            ("EUR", "German Prelim CPI m/m", NewsImpact.HIGH, base - timedelta(days=1, hours=6), "0.1%", "0.2%", "0.2%"),
            ("GBP", "GDP m/m", NewsImpact.HIGH, base - timedelta(days=1, hours=2), "0.2%", "0.1%", "0.3%"),
            
            # Near events (around base time)
            ("USD", "Non-Farm Employment Change (NFP)", NewsImpact.HIGH, base + timedelta(minutes=45), "185K", "175K", None),
            ("USD", "Unemployment Rate", NewsImpact.HIGH, base + timedelta(minutes=45), "4.1%", "4.1%", None),
            ("EUR", "ECB Monetary Policy Statement & Rate Decision", NewsImpact.HIGH, base + timedelta(hours=3), "3.75%", "3.50%", None),
            ("GBP", "BOE Monetary Policy Report", NewsImpact.HIGH, base + timedelta(hours=6), "5.00%", "4.75%", None),
            ("JPY", "BOJ Press Conference & Policy Rate", NewsImpact.HIGH, base + timedelta(hours=14), "0.25%", "0.25%", None),
            ("USD", "CPI m/m & Core CPI", NewsImpact.HIGH, base + timedelta(days=1, hours=2), "0.2%", "0.2%", None),
            ("USD", "FOMC Statement & Federal Funds Rate", NewsImpact.HIGH, base + timedelta(days=2, hours=6), "5.25%", "5.00%", None),
            ("EUR", "Eurozone Flash Manufacturing PMI", NewsImpact.MEDIUM, base + timedelta(days=3, hours=1), "45.8", "46.2", None),
            ("JPY", "Tokyo Core CPI y/y", NewsImpact.MEDIUM, base + timedelta(days=3, hours=12), "2.2%", "2.1%", None),
            ("USD", "Retail Sales m/m", NewsImpact.MEDIUM, base + timedelta(days=4, hours=4), "0.1%", "0.3%", None),
            ("GBP", "Claimant Count Change", NewsImpact.LOW, base + timedelta(days=4, hours=7), "14.5K", "12.0K", None),
        ]

        results: List[NewsEventCreate] = []
        for curr, name, impact, sched_time, prev, fcast, act in event_templates:
            # Filter by currencies if requested
            if currencies and curr not in currencies:
                continue

            # Filter by date range
            if start_time and sched_time < start_time:
                continue
            if end_time and sched_time > end_time:
                continue

            results.append(
                NewsEventCreate(
                    currency=curr,
                    event_name=name,
                    impact=impact,
                    scheduled_time=sched_time,
                    previous=prev,
                    forecast=fcast,
                    actual=act,
                )
            )

        results.sort(key=lambda e: e.scheduled_time)
        return results
