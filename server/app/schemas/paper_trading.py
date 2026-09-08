"""Pydantic schemas for Paper Trading, Virtual Accounts, and Positions."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.signal import SignalDirection


class VirtualAccountCreate(BaseModel):
    """Schema for creating a virtual trading account."""
    name: str = Field(default="Primary Virtual Account", description="Descriptive account name")
    initial_balance: float = Field(default=10000.0, ge=100.0, description="Initial virtual balance in USD")
    currency: str = Field(default="USD", description="Account denomination currency")
    leverage: int = Field(default=100, ge=1, le=500, description="Virtual leverage (e.g. 100 for 1:100)")


class VirtualAccountResponse(BaseModel):
    """Virtual account state schema."""
    id: int
    name: str
    initial_balance: float
    balance: float
    equity: float
    margin_used: float
    free_margin: float
    margin_level_pct: float
    currency: str
    leverage: int
    is_active: bool
    open_positions_count: int = 0
    floating_pnl: float = 0.0
    realized_pnl: float = 0.0
    total_return_pct: float = 0.0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AccountDepositRequest(BaseModel):
    """Schema for depositing / withdrawing virtual funds."""
    amount: float = Field(..., gt=0.0, description="Amount to deposit in USD")
    description: Optional[str] = Field(default="Manual deposit", description="Transaction memo")


class AccountResetRequest(BaseModel):
    """Schema for resetting a virtual account."""
    initial_balance: float = Field(default=10000.0, ge=100.0, description="Reset starting balance")


class PaperOrderCreate(BaseModel):
    """Schema for submitting a manual or automated paper order."""
    account_id: Optional[int] = None
    symbol: str = Field(default="EUR/USD")
    direction: SignalDirection = Field(..., description="BUY or SELL")
    order_type: str = Field(default="MARKET", description="MARKET, LIMIT, or STOP")
    target_entry_price: Optional[float] = Field(default=None, description="Target price for LIMIT/STOP orders")
    position_size: Optional[float] = Field(default=None, ge=0.01, le=100.0, description="Lots. If None, auto-calculated via risk_percent")
    risk_percent: Optional[float] = Field(default=0.5, ge=0.01, le=10.0, description="Risk % of account equity if lots is not specified")
    stop_loss: Optional[float] = Field(default=None, description="Stop loss price")
    take_profit_1: Optional[float] = Field(default=None, description="Take profit 1 price (2.0 R:R default)")
    take_profit_2: Optional[float] = Field(default=None, description="Take profit 2 price (3.0 R:R default)")
    signal_id: Optional[int] = Field(default=None, description="Linked signal ID if triggered from signal engine")


class PaperTradeResponse(BaseModel):
    """Schema for a paper trading order / position."""
    id: int
    account_id: int
    signal_id: Optional[int] = None
    symbol: str
    direction: SignalDirection
    order_type: str
    status: str
    target_entry_price: Optional[float] = None
    entry_price: float
    current_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: Optional[float] = None
    initial_position_size: float
    remaining_position_size: float
    margin_used: float
    tp1_hit: bool
    realized_pnl: float
    unrealized_pnl: float
    pnl_pips: float
    return_r: float
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaperPositionModifyRequest(BaseModel):
    """Schema for modifying an open position's SL/TP levels."""
    stop_loss: Optional[float] = Field(default=None, description="Updated Stop Loss price")
    take_profit_1: Optional[float] = Field(default=None, description="Updated TP1 price")
    take_profit_2: Optional[float] = Field(default=None, description="Updated TP2 price")


class PaperPositionCloseRequest(BaseModel):
    """Schema for closing a paper position."""
    close_ratio: float = Field(default=1.0, ge=0.01, le=1.0, description="Fraction of remaining size to close (1.0 = 100%, 0.5 = 50%)")
    exit_price: Optional[float] = Field(default=None, description="Optional custom exit price (if omitted, uses current market price)")
    exit_reason: Optional[str] = Field(default="MANUAL", description="Reason for closing")


class AutoTradeSignalRequest(BaseModel):
    """Schema for converting a generated trade signal into an active virtual position."""
    signal_id: Optional[int] = None
    symbol: str = Field(default="EUR/USD")
    timeframe: str = Field(default="1h")
    account_id: Optional[int] = None
    risk_percent: float = Field(default=0.5, ge=0.01, le=10.0)


class PositionSyncReport(BaseModel):
    """Report produced when ticking market prices across open paper positions."""
    timestamp: datetime
    updated_positions_count: int
    tp1_triggered_count: int
    tp2_triggered_count: int
    sl_triggered_count: int
    limit_orders_filled_count: int
    account_equity: float
    account_balance: float
    unrealized_pnl: float
    events: List[str] = Field(default_factory=list)


class PaperPortfolioPerformance(BaseModel):
    """Virtual account performance metrics summary."""
    initial_balance: float
    current_balance: float
    current_equity: float
    total_realized_pnl: float
    total_unrealized_pnl: float
    total_return_pct: float
    margin_used: float
    free_margin: float
    margin_level_pct: float
    total_trades: int
    open_trades: int
    closed_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    average_win: float
    average_loss: float
