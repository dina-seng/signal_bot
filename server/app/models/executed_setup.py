"""Ledger of candle setups that have already opened a paper trade.

The unique key is (symbol, timeframe, candle_timestamp, direction). Keeping it
outside the signal row means a duplicate signal for the same candle cannot
re-fire after the original position is stopped out.
"""

from sqlalchemy import Column, DateTime, Index, Integer, String, UniqueConstraint

from app.core.database import Base
from app.models.base import utc_now


class ExecutedSetup(Base):
    __tablename__ = "executed_signal_setups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    candle_timestamp = Column(DateTime(timezone=True), nullable=False)
    direction = Column(String(10), nullable=False)
    signal_id = Column(Integer, nullable=True, index=True)
    trade_id = Column(Integer, nullable=True, index=True)
    status = Column(String(20), nullable=False, default="EXECUTED")  # "EXECUTED", "CLOSED"
    executed_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "timeframe",
            "candle_timestamp",
            "direction",
            name="uq_executed_signal_setup",
        ),
        Index("ix_executed_setup_status", "status", "executed_at"),
    )
