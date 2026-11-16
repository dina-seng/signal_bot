"""Database model for persisting CRT sweep events and managing lifecycle across restarts."""

from sqlalchemy import Column, Integer, String, Float, DateTime, Index
from app.core.database import Base
from app.models.base import utc_now


class CRTSweepEvent(Base):
    """Persisted record of CRT sweep events with lifecycle state machine and dedup tracking."""

    __tablename__ = "crt_sweep_events"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    sweep_key = Column(String(255), unique=True, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False)
    direction = Column(String(10), nullable=False)
    current_state = Column(String(30), nullable=False, default="POTENTIAL", index=True)
    quality_tier = Column(String(10), nullable=True)  # "A+", "A", "B", "C"
    last_alerted_state = Column(String(30), nullable=True)

    # Geometry & Zone
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit_1 = Column(Float, nullable=True)
    take_profit_2 = Column(Float, nullable=True)
    zone_high = Column(Float, nullable=True)
    zone_low = Column(Float, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    emitted_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    cooldown_until = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_crt_sweep_key_cooldown", "sweep_key", "cooldown_until"),
        Index("ix_crt_sweep_state", "symbol", "current_state"),
    )

