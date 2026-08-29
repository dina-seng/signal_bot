from sqlalchemy import Column, Integer, String, Float, DateTime, Index, UniqueConstraint
from app.core.database import Base
from app.models.base import utc_now


class LiquidityEvent(Base):
    """Liquidity sweep or pool detection event."""
    __tablename__ = "liquidity_events"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)  # "BUY_SIDE_SWEEP", "SELL_SIDE_SWEEP", "EQUAL_HIGHS", "EQUAL_LOWS"
    price_level = Column(Float, nullable=False)
    sweep_high = Column(Float, nullable=True)
    sweep_low = Column(Float, nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "event_type", "timestamp", name="uq_liquidity_symbol_tf_type_ts"),
        Index("ix_liquidity_symbol_tf", "symbol", "timeframe", "timestamp"),
    )
