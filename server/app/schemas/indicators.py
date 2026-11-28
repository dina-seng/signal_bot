"""Pydantic schemas for Technical Indicators, RSI Divergences, Price Action, and Fair Value Gaps."""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.candle import CandleBase


class DivergenceType(str, Enum):
    """RSI Divergence classification."""
    REGULAR_BULLISH = "REGULAR_BULLISH"  # Lower Low in Price vs Higher Low in RSI (Reversal Long)
    REGULAR_BEARISH = "REGULAR_BEARISH"  # Higher High in Price vs Lower High in RSI (Reversal Short)
    HIDDEN_BULLISH = "HIDDEN_BULLISH"    # Higher Low in Price vs Lower Low in RSI (Continuation Long)
    HIDDEN_BEARISH = "HIDDEN_BEARISH"    # Lower High in Price vs Higher High in RSI (Continuation Short)


class PatternType(str, Enum):
    """Price Action Candlestick Pattern classification."""
    BULLISH_PIN_BAR = "BULLISH_PIN_BAR"      # Hammer / Rejection Wick Below
    BEARISH_PIN_BAR = "BEARISH_PIN_BAR"      # Shooting Star / Rejection Wick Above
    BULLISH_ENGULFING = "BULLISH_ENGULFING"  # Bullish Outside Engulfing Bar
    BEARISH_ENGULFING = "BEARISH_ENGULFING"  # Bearish Outside Engulfing Bar
    INSIDE_BAR = "INSIDE_BAR"                # Consolidation inside mother bar range
    MORNING_STAR = "MORNING_STAR"            # 3-bar bullish reversal pattern
    EVENING_STAR = "EVENING_STAR"            # 3-bar bearish reversal pattern


class FVGType(str, Enum):
    """Fair Value Gap / Imbalance classification."""
    BULLISH_FVG = "BULLISH_FVG"  # Imbalance Gap: Low[i] > High[i-2]
    BEARISH_FVG = "BEARISH_FVG"  # Imbalance Gap: High[i] < Low[i-2]


class EMASnapshot(BaseModel):
    """Snapshot of Exponential Moving Averages."""
    ema_fast: Optional[float] = Field(default=None, description="Fast EMA (default 20)")
    ema_mid: Optional[float] = Field(default=None, description="Medium EMA (default 50)")
    ema_slow: Optional[float] = Field(default=None, description="Slow EMA (default 200)")
    ema_trend: str = Field(
        default="NEUTRAL",
        description="BULLISH_STACK (EMA20 > EMA50 AND price > EMA20), BEARISH_STACK (inverse), BIAS variants, or NEUTRAL",
    )
    golden_cross: bool = Field(default=False, description="EMA 50 crossed above EMA 200")
    death_cross: bool = Field(default=False, description="EMA 50 crossed below EMA 200")
    price_vs_ema200: Optional[str] = Field(
        default=None, description="ABOVE or BELOW long-term baseline"
    )

    model_config = ConfigDict(from_attributes=True)


class RSISnapshot(BaseModel):
    """Snapshot of Relative Strength Index (RSI 14)."""
    rsi_value: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="RSI (14-period)")
    condition: str = Field(
        default="NEUTRAL",
        description="OVERBOUGHT (>70), OVERSOLD (<30), BULLISH_ZONE (50-70), BEARISH_ZONE (30-50)",
    )
    is_overbought: bool = Field(default=False)
    is_oversold: bool = Field(default=False)

    model_config = ConfigDict(from_attributes=True)


class RSIDivergence(BaseModel):
    """Detected RSI Divergence signal."""
    divergence_type: DivergenceType = Field(..., description="Type of RSI divergence")
    start_index: int = Field(..., description="Starting swing index")
    end_index: int = Field(..., description="Ending swing index")
    start_timestamp: datetime = Field(..., description="Timestamp of first swing")
    end_timestamp: datetime = Field(..., description="Timestamp of second swing")
    price_start: float = Field(..., description="Price at first swing")
    price_end: float = Field(..., description="Price at second swing")
    rsi_start: float = Field(..., description="RSI value at first swing")
    rsi_end: float = Field(..., description="RSI value at second swing")
    strength: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score")

    model_config = ConfigDict(from_attributes=True)


class ATRSnapshot(BaseModel):
    """Snapshot of Average True Range (ATR 14)."""
    atr_value: Optional[float] = Field(default=None, ge=0.0, description="ATR in price units")
    atr_pips: Optional[float] = Field(default=None, ge=0.0, description="ATR converted to pips")
    volatility_state: str = Field(default="NORMAL", description="HIGH, NORMAL, or LOW volatility")
    suggested_sl_distance_pips: Optional[float] = Field(
        default=None, description="Suggested 1.5x ATR Stop Loss distance in pips"
    )
    suggested_tp_distance_pips: Optional[float] = Field(
        default=None, description="Suggested 3.0x ATR Take Profit distance in pips"
    )

    model_config = ConfigDict(from_attributes=True)


class PriceActionPattern(BaseModel):
    """Identified candlestick price action pattern."""
    index: int = Field(..., description="Candle index of the pattern")
    timestamp: datetime = Field(..., description="Candle timestamp UTC")
    pattern_type: PatternType = Field(..., description="Type of price action pattern")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Pattern quality score")
    description: str = Field(..., description="Explanatory pattern description")

    model_config = ConfigDict(from_attributes=True)


class FairValueGap(BaseModel):
    """Fair Value Gap / Price Imbalance."""
    index: int = Field(..., description="Candle index where the FVG was formed (bar i)")
    timestamp: datetime = Field(..., description="Timestamp of the FVG creation candle")
    fvg_type: FVGType = Field(..., description="BULLISH_FVG or BEARISH_FVG")
    top_price: float = Field(..., description="Upper boundary of the imbalance gap")
    bottom_price: float = Field(..., description="Lower boundary of the imbalance gap")
    gap_size: float = Field(..., description="Gap height in price units")
    gap_pips: float = Field(..., description="Gap height in pips")
    is_mitigated: bool = Field(default=False, description="Whether subsequent price has filled the gap")
    mitigated_timestamp: Optional[datetime] = Field(default=None, description="Timestamp when gap was mitigated")

    model_config = ConfigDict(from_attributes=True)


class IndicatorAnalysisResponse(BaseModel):
    """Comprehensive technical indicator, divergence, and price action report."""
    symbol: str = Field(..., description="Forex instrument symbol")
    timeframe: str = Field(..., description="Timeframe identifier")
    timestamp: datetime = Field(..., description="Timestamp of latest candle analyzed")
    current_price: float = Field(..., description="Latest closing price")
    
    # Indicators
    ema: EMASnapshot = Field(..., description="EMA 20, 50, 200 state")
    rsi: RSISnapshot = Field(..., description="RSI 14 state")
    atr: ATRSnapshot = Field(..., description="ATR 14 state and volatility")
    
    # Divergences & Patterns
    divergences: List[RSIDivergence] = Field(default_factory=list, description="Detected RSI divergences")
    recent_patterns: List[PriceActionPattern] = Field(default_factory=list, description="Detected price action candlestick patterns")
    active_fvgs: List[FairValueGap] = Field(default_factory=list, description="Active unmitigated Fair Value Gaps")
    
    # Overall Confluence
    confluence_bias: str = Field(
        ...,
        description="STRONG_BULLISH, MODERATE_BULLISH, NEUTRAL, MODERATE_BEARISH, STRONG_BEARISH",
    )
    confluence_score: float = Field(
        ...,
        ge=-100.0,
        le=100.0,
        description="Net directional confluence score (-100 strong bearish to +100 strong bullish)",
    )

    model_config = ConfigDict(from_attributes=True)


class StatelessIndicatorRequest(BaseModel):
    """Request schema for on-demand stateless indicator analysis."""
    candles: List[CandleBase] = Field(..., description="Candle list sorted chronologically")
    symbol: Optional[str] = Field(default="CUSTOM")
    timeframe: Optional[str] = Field(default="1h")
    ema_fast: Optional[int] = Field(default=20)
    ema_mid: Optional[int] = Field(default=50)
    ema_slow: Optional[int] = Field(default=200)
    rsi_period: Optional[int] = Field(default=14)
    atr_period: Optional[int] = Field(default=14)
