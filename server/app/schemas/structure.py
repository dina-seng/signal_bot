"""Pydantic schemas for Market Structure analysis, Swing Detection, and Trend Classification."""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.candle import CandleBase


class SwingType(str, Enum):
    """Type of swing point."""
    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"


class StructureLabel(str, Enum):
    """Market structure classification label for swing points."""
    HH = "HH"  # Higher High
    HL = "HL"  # Higher Low
    LH = "LH"  # Lower High
    LL = "LL"  # Lower Low
    EH = "EH"  # Equal High (Double Top / Resistance Pool)
    EL = "EL"  # Equal Low (Double Bottom / Support Pool)
    UNCERTAIN = "UNCERTAIN"


class TrendDirection(str, Enum):
    """Overall market structure trend direction."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGING = "RANGING"


class MultiTimeframeAlignment(str, Enum):
    """Multi-timeframe trend alignment status."""
    BULLISH_ALIGNED = "BULLISH_ALIGNED"
    BEARISH_ALIGNED = "BEARISH_ALIGNED"
    HTF_BULLISH_PULLBACK = "HTF_BULLISH_PULLBACK"
    HTF_BEARISH_PULLBACK = "HTF_BEARISH_PULLBACK"
    MIXED = "MIXED"


class SwingPoint(BaseModel):
    """Identified swing high or swing low point."""
    index: int = Field(..., description="0-based index of the candle in the analyzed sequence")
    timestamp: datetime = Field(..., description="Candle timestamp UTC")
    price: float = Field(..., description="Price of the swing extreme (High for swing high, Low for swing low)")
    swing_type: SwingType = Field(..., description="SWING_HIGH or SWING_LOW")
    structure_label: Optional[StructureLabel] = Field(
        default=None,
        description="Market structure classification (HH, HL, LH, LL, EH, EL)",
    )
    confirmed: bool = Field(default=True, description="Whether the swing point has the required right lookback bars")
    bar_high: float = Field(..., description="Candle High price")
    bar_low: float = Field(..., description="Candle Low price")
    prev_swing_price: Optional[float] = Field(default=None, description="Previous swing price of same type")
    prev_swing_timestamp: Optional[datetime] = Field(default=None, description="Previous swing timestamp")

    model_config = ConfigDict(from_attributes=True)


class StructureAnalysisRequest(BaseModel):
    """Request schema for on-demand structure analysis of candles."""
    candles: List[CandleBase] = Field(..., description="List of OHLCV candles sorted chronologically")
    symbol: Optional[str] = Field(default="CUSTOM", description="Symbol identifier")
    timeframe: Optional[str] = Field(default="1h", description="Timeframe identifier")
    lookback: Optional[int] = Field(default=2, ge=1, le=20, description="N-bar lookback for swing detection")
    tolerance_percent: Optional[float] = Field(
        default=0.05,
        ge=0.0,
        le=2.0,
        description="Tolerance % for equal highs/lows classification",
    )


class StructureAnalysisResponse(BaseModel):
    """Complete market structure and trend analysis result."""
    symbol: str = Field(..., description="Analyzed symbol")
    timeframe: str = Field(..., description="Analyzed timeframe")
    trend: TrendDirection = Field(..., description="Current classified trend: BULLISH, BEARISH, or RANGING")
    trend_strength: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Trend strength score from 0.0 (weak/flat) to 1.0 (strong/clean trend)",
    )
    total_candles: int = Field(..., description="Number of candles analyzed")
    total_swings: int = Field(..., description="Total confirmed swing points detected")
    swing_points: List[SwingPoint] = Field(default_factory=list, description="All detected swing points in chronological order")
    last_swing_high: Optional[SwingPoint] = Field(default=None, description="Most recent confirmed Swing High")
    last_swing_low: Optional[SwingPoint] = Field(default=None, description="Most recent confirmed Swing Low")
    previous_swing_high: Optional[SwingPoint] = Field(default=None, description="Preceding Swing High")
    previous_swing_low: Optional[SwingPoint] = Field(default=None, description="Preceding Swing Low")
    higher_highs_count: int = Field(default=0, description="Count of Higher Highs")
    higher_lows_count: int = Field(default=0, description="Count of Higher Lows")
    lower_highs_count: int = Field(default=0, description="Count of Lower Highs")
    lower_lows_count: int = Field(default=0, description="Count of Lower Lows")
    equal_highs_count: int = Field(default=0, description="Count of Equal Highs (Double Tops)")
    equal_lows_count: int = Field(default=0, description="Count of Equal Lows (Double Bottoms)")
    key_resistance: Optional[float] = Field(default=None, description="Key structural resistance (highest recent swing high)")
    key_support: Optional[float] = Field(default=None, description="Key structural support (lowest recent swing low)")

    model_config = ConfigDict(from_attributes=True)


class MultiTimeframeStructureResponse(BaseModel):
    """Multi-timeframe structure analysis and alignment report."""
    symbol: str = Field(..., description="Analyzed symbol")
    primary_timeframe: str = Field(default="4h", description="Higher timeframe anchor (e.g. 4h)")
    primary_trend: TrendDirection = Field(..., description="Trend on primary higher timeframe")
    alignment: MultiTimeframeAlignment = Field(..., description="Overall multi-timeframe alignment status")
    alignment_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="MTF alignment score (1.0 = full confluence, 0.0 = total conflict)",
    )
    timeframes: Dict[str, StructureAnalysisResponse] = Field(
        ...,
        description="Detailed structure analysis breakdown per timeframe",
    )
    summary: str = Field(..., description="Human-readable executive summary of market structure")

    model_config = ConfigDict(from_attributes=True)


class CRTAnalysis(BaseModel):
    """Candle Range Theory (CRT) Analysis based on Accumulation, Manipulation, and Distribution (AMD)."""
    range_high: float
    range_low: float
    range_open: float
    range_close: float
    positive_direction: bool  # True if range_close > range_open
    breach_point: Optional[float] = None  # The extreme low/high during manipulation
    is_breached: bool = False
    is_confirmed: bool = False  # True if price closed back inside the range
    manip_depth_pct: float = 0.0  # Percentage of range size that was breached
    range_open_timestamp: Optional[datetime] = None
    breach_timestamp: Optional[datetime] = None
    breach_wick_ratio: float = 0.0
    confirmation_displacement: float = 0.0
    reentry_depth_pct: float = 0.0
    has_missing_timestamps: bool = False
    manipulation_candle_index: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

