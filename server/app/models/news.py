from sqlalchemy import Column, Integer, String, DateTime, Index, UniqueConstraint
from app.core.database import Base
from app.models.base import utc_now


class NewsEvent(Base):
    """Economic calendar news event."""
    __tablename__ = "news_events"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    currency = Column(String(10), nullable=False, index=True)  # e.g., "USD", "EUR", "GBP", "JPY"
    event_name = Column(String(150), nullable=False)
    impact = Column(String(10), nullable=False)  # "LOW", "MEDIUM", "HIGH"
    scheduled_time = Column(DateTime(timezone=True), nullable=False, index=True)
    previous = Column(String(50), nullable=True)
    forecast = Column(String(50), nullable=True)
    actual = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("currency", "event_name", "scheduled_time", name="uq_news_currency_name_time"),
        Index("ix_news_currency_time", "currency", "scheduled_time"),
    )
