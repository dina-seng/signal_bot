"""Database models for Paper Trading, Virtual Accounts, and Transactions."""

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import utc_now


class VirtualAccount(Base):
    """Virtual trading account simulating balance, equity, and margin."""
    __tablename__ = "virtual_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(100), nullable=False, default="Primary Virtual Account")
    initial_balance = Column(Float, nullable=False, default=10000.0)
    balance = Column(Float, nullable=False, default=10000.0)
    equity = Column(Float, nullable=False, default=10000.0)
    margin_used = Column(Float, nullable=False, default=0.0)
    free_margin = Column(Float, nullable=False, default=10000.0)
    currency = Column(String(10), nullable=False, default="USD")
    leverage = Column(Integer, nullable=False, default=100)  # e.g. 100 for 1:100 leverage
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    trades = relationship("PaperTrade", back_populates="account", cascade="all, delete-orphan")
    transactions = relationship("AccountTransaction", back_populates="account", cascade="all, delete-orphan")


class PaperTrade(Base):
    """Paper trading simulated position and order entity."""
    __tablename__ = "paper_trades"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    account_id = Column(Integer, ForeignKey("virtual_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    signal_id = Column(Integer, nullable=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False)  # "BUY", "SELL"
    order_type = Column(String(15), nullable=False, default="MARKET")  # "MARKET", "LIMIT", "STOP"
    status = Column(String(20), nullable=False, default="OPEN", index=True)  # "PENDING", "OPEN", "PARTIALLY_CLOSED", "CLOSED", "CANCELLED"
    
    # Pricing & Levels
    target_entry_price = Column(Float, nullable=True)  # Set for LIMIT/STOP pending orders
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit_1 = Column(Float, nullable=False)
    take_profit_2 = Column(Float, nullable=True)
    
    # Position sizing & Margin
    initial_position_size = Column(Float, nullable=False)  # Lots
    remaining_position_size = Column(Float, nullable=False)  # Lots
    margin_used = Column(Float, nullable=False, default=0.0)

    # State tracking
    tp1_hit = Column(Boolean, nullable=False, default=False)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    unrealized_pnl = Column(Float, nullable=False, default=0.0)
    pnl_pips = Column(Float, nullable=False, default=0.0)
    return_r = Column(Float, nullable=False, default=0.0)

    # Exit details
    exit_price = Column(Float, nullable=True)
    exit_reason = Column(String(50), nullable=True)  # "TP1_HIT", "TP2_HIT", "SL_HIT", "BREAK_EVEN", "MANUAL", "CANCELLED", "MARGIN_STOP_OUT"
    
    opened_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    account = relationship("VirtualAccount", back_populates="trades")

    __table_args__ = (
        Index("ix_paper_trade_sym_status", "symbol", "status", "opened_at"),
    )


class AccountTransaction(Base):
    """Ledger of balance changes (Deposits, Withdrawals, Realized Trade PnL, Resets)."""
    __tablename__ = "account_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    account_id = Column(Integer, ForeignKey("virtual_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    trade_id = Column(Integer, nullable=True, index=True)
    transaction_type = Column(String(30), nullable=False)  # "DEPOSIT", "WITHDRAWAL", "TRADE_REALIZED_PNL", "RESET"
    amount = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    account = relationship("VirtualAccount", back_populates="transactions")

    __table_args__ = (
        Index("ix_acc_tx_account_time", "account_id", "created_at"),
    )
