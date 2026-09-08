"""Economic news calendar and blackout filter package."""

from app.services.news.base import BaseNewsProvider
from app.services.news.mock_provider import MockNewsProvider
from app.services.news.forexfactory_provider import ForexFactoryProvider
from app.services.news.ingestion import NewsIngestionService
from app.services.news.filter_engine import NewsFilterEngine


def get_news_provider(provider_name: str = "forexfactory") -> BaseNewsProvider:
    """Factory to retrieve configured economic news provider instance."""
    name = (provider_name or "").lower().strip()
    if name == "forexfactory" or name == "live":
        return ForexFactoryProvider()
    elif name == "mock" or name == "synthetic":
        return MockNewsProvider()
    else:
        return ForexFactoryProvider()


__all__ = [
    "BaseNewsProvider",
    "MockNewsProvider",
    "ForexFactoryProvider",
    "NewsIngestionService",
    "NewsFilterEngine",
    "get_news_provider",
]
