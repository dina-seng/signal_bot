"""Candle model for storing historical and real-time OHLCV data."""

from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    UniqueConstraint,
    Index,
)
from app.core.database import Base
from app.models.base import utc_now


class Candle(Base):
    """OHLCV Candle entity.

    Enforces unique constraints on (symbol, timeframe, timestamp) and indexes for efficient queries.
    """
    __tablename__ = "candles"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_symbol_timeframe_timestamp"),
        Index("ix_candle_query", "symbol", "timeframe", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<Candle(id={self.id}, symbol='{self.symbol}', tf='{self.timeframe}', "
            f"time='{self.timestamp}', O={self.open}, H={self.high}, L={self.low}, C={self.close})>"
        )
