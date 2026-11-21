"""SQLAlchemy database engine, session management, and dependencies."""

from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings
from app.core.logging import logger

# Normalize DATABASE_URL for compatibility across Render, Neon, Heroku, Supabase
db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    # Render and Heroku default to postgres:// which SQLAlchemy 1.4+ rejects
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Build engine kwargs dynamically based on dialect
engine_kwargs = {
    "echo": (settings.LOG_LEVEL.upper() == "DEBUG"),
    "pool_pre_ping": True,
}

if db_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL cloud settings (Neon/Supabase) to handle idle sleep and reconnects
    engine_kwargs["pool_recycle"] = 300
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 10

engine = create_engine(
    db_url,
    **engine_kwargs,
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
    
    # 1. IMPORT ALL MODELS SO SQLALCHEMY REGISTERS THEIR TABLES
    import app.models.candle
    import app.models.paper
    import app.models.news
    import app.models.signal
    import app.models.signal_candidate
    import app.models.structure
    import app.models.liquidity
    import app.models.backtest
    import app.models.api_usage

    logger.info("Initializing database tables...")
    try:
        insp = inspect(engine)
        if insp.has_table("paper_trades"):
            columns = [c["name"] for c in insp.get_columns("paper_trades")]
            if "account_id" not in columns:
                logger.info("Adding missing account_id column to paper_trades table schema...")
                with engine.connect() as conn:
                    conn.execute(text("ALTER TABLE paper_trades ADD COLUMN account_id INTEGER REFERENCES virtual_accounts(id)"))
                    conn.commit()

        if insp.has_table("candles"):
            candle_columns = [c["name"] for c in insp.get_columns("candles")]
            if "source" not in candle_columns:
                logger.info("Adding missing source column to candles table schema...")
                with engine.connect() as conn:
                    conn.execute(text("ALTER TABLE candles ADD COLUMN source VARCHAR(50) DEFAULT 'twelvedata'"))
                    conn.commit()
    except Exception as e:
        logger.debug(f"Table inspection note: {e}")

    # 2. CREATE TABLES
    Base.metadata.create_all(bind=engine)
    logger.info(f"Database tables initialized successfully. Created tables: {list(Base.metadata.tables.keys())}")