"""Pytest configuration and shared test fixtures."""

import os

_raw_env_url = os.environ.get("DATABASE_URL", "")
if "postgres" in _raw_env_url.lower() or "postgresql" in _raw_env_url.lower():
    raise RuntimeError(f"CRITICAL GUARD: DATABASE_URL points to postgres during tests! ({_raw_env_url})")

# HERMETIC TEST DATABASE ISOLATION:
# Force tests to NEVER connect to Neon production DATABASE_URL.
# Set DATABASE_URL to in-memory SQLite before application modules are loaded.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.core.config import settings
settings.DATABASE_URL = "sqlite:///:memory:"

import app.core.database as db_core
from app.models.base import Base
from app.core.database import get_db

# Wire app.core.database engine and SessionLocal to isolated in-memory SQLite StaticPool
test_shared_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
db_core.engine = test_shared_engine
db_core.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_shared_engine)
Base.metadata.create_all(bind=test_shared_engine)

from app.services.market_data.mock_provider import MockMarketDataProvider
from app.services.market_data.ingestion import IngestionService
from app.services.news.mock_provider import MockNewsProvider
from app.services.telegram.client import MockTelegramClient
from app.api.deps import get_provider, get_news_provider, get_telegram_client_dep
from app.services.telegram.scheduler import stop_scanner_scheduler
from app.main import app


@pytest.fixture(autouse=True)
def verify_test_database_isolation():
    """Safety check verifying tests NEVER connect to production Neon database.
    
    Hard Rule 6: Tests must be hermetic: temporary SQLite, never Neon.
    Add a conftest guard that fails if DATABASE_URL points to postgres during tests.
    """
    raw_env_url = os.environ.get("DATABASE_URL", "").lower()
    engine_url = str(db_core.engine.url).lower()
    settings_url = str(getattr(settings, "DATABASE_URL", "")).lower()

    if "postgres" in raw_env_url or "postgresql" in raw_env_url:
        pytest.fail(f"CRITICAL GUARD: DATABASE_URL points to postgres during tests! ({os.environ.get('DATABASE_URL')})")
    if "postgres" in engine_url or "postgresql" in engine_url:
        pytest.fail(f"CRITICAL GUARD: engine.url points to postgres during tests! ({db_core.engine.url})")
    if "postgres" in settings_url or "postgresql" in settings_url:
        pytest.fail(f"CRITICAL GUARD: settings.DATABASE_URL points to postgres during tests! ({settings.DATABASE_URL})")

    assert "neon.tech" not in engine_url, (
        "CRITICAL ERROR: Tests attempted to connect to production Neon database!"
    )
    assert "sqlite" in engine_url, (
        "CRITICAL ERROR: Tests must run on isolated SQLite database!"
    )


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
def disable_http_session_auth():
    """Existing tests exercise unauthenticated endpoints; auth has its own tests."""
    original = settings.AUTH_ENABLED
    original_secure = settings.SESSION_COOKIE_SECURE
    original_samesite = settings.SESSION_COOKIE_SAMESITE
    original_widget_secure = settings.WIDGET_COOKIE_SECURE
    original_widget_samesite = settings.WIDGET_COOKIE_SAMESITE
    settings.AUTH_ENABLED = False
    # TestClient speaks plain HTTP; a Secure cookie would never be sent back.
    settings.SESSION_COOKIE_SECURE = False
    settings.SESSION_COOKIE_SAMESITE = "lax"
    settings.WIDGET_COOKIE_SECURE = False
    settings.WIDGET_COOKIE_SAMESITE = "lax"
    yield
    settings.AUTH_ENABLED = original
    settings.SESSION_COOKIE_SECURE = original_secure
    settings.SESSION_COOKIE_SAMESITE = original_samesite
    settings.WIDGET_COOKIE_SECURE = original_widget_secure
    settings.WIDGET_COOKIE_SAMESITE = original_widget_samesite


@pytest.fixture(autouse=True)
def enforce_test_symbols():
    """Pin SUPPORTED_SYMBOLS to the active single-asset (XAU/USD) for all tests."""
    orig = settings.SUPPORTED_SYMBOLS
    settings.SUPPORTED_SYMBOLS = ["XAU/USD"]
    yield
    settings.SUPPORTED_SYMBOLS = orig


@pytest.fixture(scope="function")
def test_db_session():
    """Create a fresh isolated session on the in-memory SQLite test database."""
    Base.metadata.create_all(bind=test_shared_engine)
    db = db_core.SessionLocal()
    try:
        yield db
    finally:
        db.close()
        # Clean tables between test runs for hermetic isolation
        for table in reversed(Base.metadata.sorted_tables):
            try:
                db.execute(table.delete())
                db.commit()
            except Exception:
                db.rollback()
        db.close()


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
