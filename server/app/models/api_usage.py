"""API usage tracking model for rate limit and daily budget accounting."""

from datetime import date, datetime, timezone
from sqlalchemy import Column, Integer, DateTime, Date
from app.models.base import Base


class ApiUsage(Base):
    """Tracks daily external API calls to enforce budget caps."""

    __tablename__ = "api_usage"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, unique=True, index=True, nullable=False, default=date.today)
    calls = Column(Integer, nullable=False, default=0)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
