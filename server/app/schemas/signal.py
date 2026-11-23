"""Pydantic schemas for Trading Signals, Scoring Engine, and Risk Management."""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.candle import CandleBase


class SignalDirection(str, Enum):
    """Trading signal direction."""
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"


class SignalStatus(str, Enum):
    """Lifecycle status of a generated trading signal."""
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"
    TP1_HIT = "TP1_HIT"
    TP2_HIT = "TP2_HIT"
    SL_HIT = "SL_HIT"
    EXPIRED = "EXPIRED"


class ScoreBreakdown(BaseModel):
    """Detailed score breakdown across all technical and institutional pillars."""
    structure_score: float = Field(..., ge=0.0, le=35.0, description="Score from Trend & BOS/CHOCH (Max 35)")
    liquidity_score: float = Field(..., ge=0.0, le=40.0, description="Score from Sweeps, S/R Zones & FVGs (Max 40)")
    indicators_score: float = Field(default=0.0, ge=0.0, le=25.0, description="Legacy score from EMAs, RSI, ATR (Max 25)")
    price_action_score: float = Field(..., ge=0.0, le=25.0, description="Score from Pin Bars & Engulfing (Max 25)")
    total_score: float = Field(..., ge=0.0, le=100.0, description="Composite score (0 to 100)")
    is_qualified: bool = Field(..., description="True if total_score >= MIN_SETUP_SCORE (e.g. 60)")


class RiskParameters(BaseModel):
    """Risk management calculations and suggested position sizing."""
    entry_price: float = Field(..., description="Suggested entry price")
    stop_loss: float = Field(..., description="Protective Stop Loss price")
    take_profit_1: float = Field(..., description="Target 1 (Min 2.0 R:R)")
    take_profit_2: float = Field(..., description="Target 2 (Extended 3.0 R:R)")
    risk_pips: float = Field(..., ge=0.0, description="Stop loss risk distance in pips")
    reward_pips_tp1: float = Field(..., ge=0.0, description="Reward distance to TP1 in pips")
    reward_pips_tp2: float = Field(..., ge=0.0, description="Reward distance to TP2 in pips")
    risk_reward_tp1: float = Field(..., ge=0.0, description="R:R ratio for TP1")
    risk_reward_tp2: float = Field(..., ge=0.0, description="R:R ratio for TP2")
    account_balance: float = Field(default=10000.0, description="Account equity in USD")
    risk_percent: float = Field(default=5.0, description="Risk per trade percentage")
    risk_amount_usd: float = Field(..., description="Dollar amount at risk")
    suggested_lot_size: float = Field(..., ge=0.0, description="Executable volume floored to broker step (0.0 when below min)")
    raw_lot_size: Optional[float] = Field(default=None, ge=0.0, description="Unrounded required volume")
    is_executable: Optional[bool] = Field(default=None, description="False when raw volume is below broker minimum")
    min_lot_risk_usd: Optional[float] = Field(default=None, ge=0.0, description="Loss at minimum lot for this stop")
    volume_step: Optional[float] = Field(default=None, ge=0.0, description="Broker volume step used")


class SignalBase(BaseModel):
    """Base schema for a trading signal."""
    symbol: str
    timeframe: str
    direction: SignalDirection
    setup_score: float = Field(..., ge=0.0, le=100.0)
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None
    risk_reward: Optional[float] = None
    fingerprint: str
    reasons: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list, description="Advisory or risk warnings attached to signal")
    status: SignalStatus = SignalStatus.ACTIVE
    trend_alignment: Optional[str] = Field(default=None, description="Trend alignment status: TREND FOLLOWING or COUNTER-TREND SCALP")
    htf_trend: Optional[str] = Field(default=None, description="Higher timeframe (1H) trend bias: BULLISH, BEARISH, RANGING")
    strategy_name: Optional[str] = Field(default=None, description="Strategy that generated this signal (e.g. 'SMC Confluence', 'Momentum')")
    is_broadcasted: bool = False
    timestamp: datetime


class SignalResponse(SignalBase):
    """Response schema for a persisted or evaluated signal."""
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    score_breakdown: Optional[ScoreBreakdown] = None
    risk_parameters: Optional[RiskParameters] = None

    model_config = ConfigDict(from_attributes=True)


class MarketScanSymbolResult(BaseModel):
    """Scan summary for a single instrument."""
    symbol: str
    timeframe: str
    direction: SignalDirection
    setup_score: float
    is_actionable: bool
    signal: Optional[SignalResponse] = None
    blackout_blocked: bool = False
    trend_alignment: Optional[str] = Field(default=None, description="TREND FOLLOWING or COUNTER-TREND SCALP")
    htf_trend: Optional[str] = Field(default=None, description="Higher timeframe (1H) trend bias")
    reasons: List[str] = Field(default_factory=list)


class MarketScanResponse(BaseModel):
    """Response schema for multi-symbol market scan."""
    timestamp: datetime
    scanned_count: int
    actionable_count: int
    results: List[MarketScanSymbolResult]


class StatelessSignalRequest(BaseModel):
    """Request schema for evaluating custom candles for a signal."""
    candles: List[CandleBase]
    symbol: Optional[str] = Field(default="XAU/USD")
    timeframe: Optional[str] = Field(default="1h")
    account_balance: Optional[float] = Field(default=10000.0)
    risk_percent: Optional[float] = Field(default=None)
    bypass_news_check: Optional[bool] = Field(default=False)
