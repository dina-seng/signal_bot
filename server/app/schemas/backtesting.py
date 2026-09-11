"""Pydantic schemas for Backtesting, Performance Metrics, and Optimization."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.candle import CandleBase
from app.schemas.signal import SignalDirection


class BacktestConfig(BaseModel):
    """Configuration parameters for a backtest simulation run."""
    initial_balance: float = Field(default=10000.0, ge=100.0, description="Starting account balance in USD")
    risk_percent: float = Field(default=0.5, ge=0.01, le=10.0, description="Risk percentage per trade")
    min_score_threshold: float = Field(default=75.0, ge=0.0, le=100.0, description="Minimum strategy setup score to take a trade")
    take_profit_1_rr: float = Field(default=2.0, ge=0.5, le=20.0, description="First Take Profit Risk:Reward multiplier")
    take_profit_2_rr: float = Field(default=3.0, ge=1.0, le=30.0, description="Second Take Profit Risk:Reward multiplier")
    partial_tp_ratio: float = Field(default=0.5, ge=0.0, le=1.0, description="Position fraction closed at TP1 (e.g. 0.5 = 50%)")
    move_sl_to_be_on_tp1: bool = Field(default=True, description="Move Stop Loss to Break-Even when TP1 is reached")
    spread_pips: float = Field(default=1.0, ge=0.0, description="Bid/Ask spread in pips")
    slippage_pips: float = Field(default=0.5, ge=0.0, description="Execution slippage in pips")
    commission_per_lot: float = Field(default=0.0, ge=0.0, description="Commission in USD per standard lot roundturn")
    max_open_trades: int = Field(default=3, ge=1, le=20, description="Maximum concurrent open positions allowed")
    warmup_bars: int = Field(default=50, ge=10, le=500, description="Number of historical bars for warming up indicators and structure")


class BacktestTradeLog(BaseModel):
    """Simulated individual trade log item."""
    id: Optional[int] = None
    run_id: Optional[int] = None
    symbol: str
    direction: SignalDirection
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: Optional[float] = None
    position_size: float = Field(..., description="Position size in standard lots")
    pnl: float = Field(..., description="Net realized PnL in USD")
    pnl_percent: float = Field(..., description="PnL return percentage based on account balance at entry")
    return_r: float = Field(..., description="Realized R-multiple payoff (e.g. +2.0 R, -1.0 R)")
    exit_reason: str = Field(..., description="Reason for trade exit (TP1_HIT, TP2_HIT, SL_HIT, BREAK_EVEN, END_OF_DATA)")
    score: float = Field(default=0.0, description="Confluence score at signal generation")

    model_config = ConfigDict(from_attributes=True)


class EquityPoint(BaseModel):
    """Time-series equity curve point."""
    timestamp: datetime
    equity: float = Field(..., description="Account floating equity in USD")
    balance: float = Field(..., description="Account realized balance in USD")
    drawdown_pct: float = Field(..., description="Current drawdown percentage from peak equity")
    drawdown_usd: float = Field(..., description="Current drawdown in USD from peak equity")
    open_positions: int = Field(default=0, description="Number of active open trades at this timestamp")


class PerformanceMetrics(BaseModel):
    """Comprehensive institutional performance and risk metrics."""
    initial_balance: float
    final_balance: float
    total_pnl: float
    total_pnl_percent: float
    peak_equity: float

    # Trade counts & win/loss ratios
    total_trades: int
    winning_trades: int
    losing_trades: int
    break_even_trades: int
    win_rate: float = Field(..., description="Winning trades percentage (0.0 to 100.0)")
    loss_rate: float = Field(..., description="Losing trades percentage (0.0 to 100.0)")

    # Profitability and payoff metrics
    profit_factor: float = Field(..., description="Gross Profit / Gross Loss ratio")
    gross_profit: float
    gross_loss: float
    average_win: float
    average_loss: float
    win_loss_payoff_ratio: float = Field(..., description="Average Win / Average Loss ratio")
    expectancy_usd: float = Field(..., description="Expected USD return per executed trade")
    expectancy_r: float = Field(..., description="Expected R-multiple return per executed trade")

    # Risk and Drawdown statistics
    max_drawdown_pct: float = Field(..., description="Maximum peak-to-trough equity drawdown percentage")
    max_drawdown_usd: float = Field(..., description="Maximum peak-to-trough equity drawdown in USD")
    max_drawdown_duration_bars: int = Field(default=0, description="Longest drawdown duration in bars")
    sharpe_ratio: float = Field(..., description="Annualized or per-trade Sharpe ratio")
    sortino_ratio: float = Field(..., description="Downside risk-adjusted Sortino ratio")
    calmar_ratio: float = Field(..., description="Annualized Return / Max Drawdown ratio")

    # Directional Breakdown (Long vs Short)
    buy_trades_count: int = 0
    buy_winning_trades: int = 0
    buy_win_rate: float = 0.0
    buy_pnl: float = 0.0
    sell_trades_count: int = 0
    sell_winning_trades: int = 0
    sell_win_rate: float = 0.0
    sell_pnl: float = 0.0


class BacktestRequest(BaseModel):
    """Request payload for running a backtest on database candles."""
    symbol: str = Field(default="XAU/USD", description="Currency pair symbol")
    timeframe: str = Field(default="1h", description="Timeframe (e.g. 15m, 1h, 4h)")
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    name: Optional[str] = None
    config: Optional[BacktestConfig] = None
    save_run: bool = Field(default=True, description="Whether to persist run and trades to database")


class StatelessBacktestRequest(BaseModel):
    """Request payload for running a stateless in-memory backtest on raw candle sequences."""
    candles: List[CandleBase]
    symbol: str = Field(default="XAU/USD")
    timeframe: str = Field(default="1h")
    config: Optional[BacktestConfig] = None


class BacktestResultResponse(BaseModel):
    """Complete result returned after a backtest execution."""
    run_id: Optional[int] = None
    name: Optional[str] = None
    symbol: str
    timeframe: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    config: BacktestConfig
    metrics: PerformanceMetrics
    equity_curve: List[EquityPoint]
    trades: List[BacktestTradeLog]
    created_at: Optional[datetime] = None


class BacktestRunSummary(BaseModel):
    """Lightweight summary of a historical backtest run."""
    id: int
    name: Optional[str]
    symbol: str
    timeframe: str
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    initial_balance: float
    final_balance: float
    total_pnl: float
    total_pnl_percent: float
    total_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ParameterSweepRequest(BaseModel):
    """Request schema for optimizing parameters across a candidate grid."""
    symbol: str = Field(default="XAU/USD")
    timeframe: str = Field(default="1h")
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    score_thresholds: List[float] = Field(default_factory=lambda: [70.0, 75.0, 80.0])
    risk_percentages: List[float] = Field(default_factory=lambda: [0.5, 1.0])
    rr_targets: List[float] = Field(default_factory=lambda: [1.5, 2.0, 2.5, 3.0])
    initial_balance: float = Field(default=10000.0)


class ParameterSweepResultItem(BaseModel):
    """Evaluation result for one specific parameter combination."""
    score_threshold: float
    risk_percent: float
    take_profit_1_rr: float
    take_profit_2_rr: float
    total_trades: int
    win_rate: float
    profit_factor: float
    total_pnl: float
    total_pnl_percent: float
    max_drawdown_pct: float
    sharpe_ratio: float
    expectancy_usd: float


class ParameterSweepResponse(BaseModel):
    """Summary of parameter optimization grid sweep."""
    symbol: str
    timeframe: str
    tested_combinations: int
    best_by_sharpe: Optional[ParameterSweepResultItem] = None
    best_by_pnl: Optional[ParameterSweepResultItem] = None
    best_by_profit_factor: Optional[ParameterSweepResultItem] = None
    results: List[ParameterSweepResultItem]
