"""SQLAlchemy database engine, session management, and dependencies."""

from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings
from app.core.logging import logger

# Configure connect_args for SQLite if applicable
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=(settings.LOG_LEVEL.upper() == "DEBUG"),
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Dependency for yielding database sessions per request/task."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all database tables defined in the models."""
    from sqlalchemy import inspect, text
    logger.info("Initializing database tables...")
    try:
        insp = inspect(engine)
        if insp.has_table("paper_trades"):
            columns = [c["name"] for c in insp.get_columns("paper_trades")]
            if "account_id" not in columns:
                logger.info("Migrating paper_trades table schema...")
                with engine.connect() as conn:
                    conn.execute(text("DROP TABLE IF EXISTS paper_trades"))
                    conn.commit()
    except Exception as e:
        logger.debug(f"Table inspection note: {e}")

    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized successfully.")
