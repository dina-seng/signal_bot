"""Pytest configuration and shared test fixtures."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.base import Base
from app.core.database import get_db
from app.services.market_data.mock_provider import MockMarketDataProvider
from app.services.market_data.ingestion import IngestionService
from app.services.news.mock_provider import MockNewsProvider
from app.services.telegram.client import MockTelegramClient
from app.core.config import settings
from app.api.deps import get_provider, get_news_provider, get_telegram_client_dep
from app.services.telegram.scheduler import stop_scanner_scheduler
from app.main import app


@pytest.fixture(autouse=True)
def disable_background_scanner():
    """Disable background scanner during unit/integration tests by default."""
    orig_val = settings.SCANNER_ENABLED
    settings.SCANNER_ENABLED = False
    stop_scanner_scheduler()
    yield
    settings.SCANNER_ENABLED = orig_val
    stop_scanner_scheduler()


@pytest.fixture(autouse=True)
def enforce_test_symbols():
    """Pin SUPPORTED_SYMBOLS to the active single-asset (XAU/USD) for all tests.

    This ensures tests are hermetically isolated from whatever is in the .env
    file, and that symbol-specific assertions match XAU/USD only while US100 is quarantined.
    """
    orig = settings.SUPPORTED_SYMBOLS
    settings.SUPPORTED_SYMBOLS = ["XAU/USD"]
    yield
    settings.SUPPORTED_SYMBOLS = orig


@pytest.fixture(scope="function")
def test_db_session():
    """Create a fresh in-memory SQLite database session for each test function."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def mock_provider():
    """Return a mock market data provider."""
    return MockMarketDataProvider()


@pytest.fixture(scope="function")
def mock_news_provider():
    """Return a mock economic news provider."""
    return MockNewsProvider()


@pytest.fixture(scope="function")
def mock_telegram_client():
    """Return a mock Telegram client."""
    return MockTelegramClient()


@pytest.fixture(scope="function")
def ingestion_service(test_db_session, mock_provider):
    """Return an IngestionService wired to test db and mock provider."""
    return IngestionService(provider=mock_provider, db=test_db_session)


@pytest.fixture(scope="function")
def client(test_db_session, mock_provider, mock_news_provider, mock_telegram_client):
    """FastAPI TestClient with overridden database, provider, and telegram dependencies."""
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    def override_get_provider():
        return mock_provider

    def override_get_news_provider():
        return mock_news_provider

    def override_get_telegram_client():
        return mock_telegram_client

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_provider] = override_get_provider
    app.dependency_overrides[get_news_provider] = override_get_news_provider
    app.dependency_overrides[get_telegram_client_dep] = override_get_telegram_client

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    stop_scanner_scheduler()
