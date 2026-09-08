"""Database models for Backtesting runs and individual simulated trades."""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    JSON,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import utc_now


class BacktestRun(Base):
    """Backtest execution run containing metadata, configuration, and aggregate metrics."""
    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(100), nullable=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False, index=True)
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    
    # Financial metrics summary
    initial_balance = Column(Float, nullable=False, default=10000.0)
    final_balance = Column(Float, nullable=False)
    total_pnl = Column(Float, nullable=False)
    total_pnl_percent = Column(Float, nullable=False)
    total_trades = Column(Integer, nullable=False, default=0)
    winning_trades = Column(Integer, nullable=False, default=0)
    losing_trades = Column(Integer, nullable=False, default=0)
    break_even_trades = Column(Integer, nullable=False, default=0)
    win_rate = Column(Float, nullable=False, default=0.0)
    profit_factor = Column(Float, nullable=False, default=0.0)
    max_drawdown_pct = Column(Float, nullable=False, default=0.0)
    max_drawdown_usd = Column(Float, nullable=False, default=0.0)
    sharpe_ratio = Column(Float, nullable=False, default=0.0)
    sortino_ratio = Column(Float, nullable=False, default=0.0)
    calmar_ratio = Column(Float, nullable=False, default=0.0)
    expectancy_usd = Column(Float, nullable=False, default=0.0)
    expectancy_r = Column(Float, nullable=False, default=0.0)

    # Serialized parameters and metrics
    config = Column(JSON, nullable=False)
    metrics = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    trades = relationship("BacktestTrade", back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_backtest_run_sym_tf", "symbol", "timeframe", "created_at"),
    )


class BacktestTrade(Base):
    """Simulated trade executed during a backtest run."""
    __tablename__ = "backtest_trades"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    run_id = Column(Integer, ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False)  # "BUY", "SELL"
    entry_time = Column(DateTime(timezone=True), nullable=False, index=True)
    exit_time = Column(DateTime(timezone=True), nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit_1 = Column(Float, nullable=False)
    take_profit_2 = Column(Float, nullable=True)
    position_size = Column(Float, nullable=False)  # Standard lots
    pnl = Column(Float, nullable=False)
    pnl_percent = Column(Float, nullable=False)
    return_r = Column(Float, nullable=False)  # R-multiple return (e.g. +2.0, -1.0)
    exit_reason = Column(String(50), nullable=False)  # "TP1_HIT", "TP2_HIT", "SL_HIT", "BREAK_EVEN", "END_OF_DATA"
    score = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    run = relationship("BacktestRun", back_populates="trades")

    __table_args__ = (
        Index("ix_backtest_trade_run_entry", "run_id", "entry_time"),
    )
