"""Base model imports and shared mixins."""

from datetime import datetime, timezone
from sqlalchemy import Column, DateTime
from app.core.database import Base


def utc_now() -> datetime:
    """Return timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


class TimestampMixin:
    """Timestamp mixin for database records."""
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
