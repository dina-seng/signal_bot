"""Abstract base class and interface for Economic Calendar News providers."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
from app.schemas.news import NewsEventCreate


class BaseNewsProvider(ABC):
    """Abstract interface for all economic news calendar providers."""

    @abstractmethod
    async def fetch_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        currencies: Optional[List[str]] = None,
    ) -> List[NewsEventCreate]:
        """Fetch economic calendar events within a date range and currency filter.

        Args:
            start_time: Start datetime UTC.
            end_time: End datetime UTC.
            currencies: Optional list of currency codes (e.g. ['USD', 'EUR', 'GBP', 'JPY']).

        Returns:
            List of validated NewsEventCreate objects sorted chronologically.
        """
        pass

    @property
    def is_live_provider(self) -> bool:
        """Whether this provider represents a live external market feed."""
        return True
