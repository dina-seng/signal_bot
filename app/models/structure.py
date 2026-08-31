from sqlalchemy import Column, Integer, String, Float, DateTime, Index, UniqueConstraint
from app.core.database import Base
from app.models.base import utc_now


class StructureEvent(Base):
    """Market structure event recording (HH, HL, LH, LL, BOS, CHOCH)."""
    __tablename__ = "structure_events"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)
    event_type = Column(String(30), nullable=False)  # e.g., "SWING_HIGH", "SWING_LOW", "BULLISH_BOS", "BEARISH_CHOCH"
    price = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    reference_price = Column(Float, nullable=True)
    reference_timestamp = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "event_type", "timestamp", name="uq_structure_symbol_tf_type_ts"),
        Index("ix_structure_symbol_tf", "symbol", "timeframe", "timestamp"),
    )
