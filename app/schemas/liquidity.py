"""Pydantic schemas for BOS, CHOCH/MSS, Liquidity Sweeps, and Dynamic S/R Zones."""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.structure import StructureAnalysisResponse, StructureLabel, SwingPoint, TrendDirection


class BOSCHOCHType(str, Enum):
    """Breakout Event classification."""
    BULLISH_BOS = "BULLISH_BOS"      # Bullish Break of Structure (Continuation)
    BEARISH_BOS = "BEARISH_BOS"      # Bearish Break of Structure (Continuation)
    BULLISH_CHOCH = "BULLISH_CHOCH"  # Bullish Change of Character / MSS (Reversal)
    BEARISH_CHOCH = "BEARISH_CHOCH"  # Bearish Change of Character / MSS (Reversal)


class LiquidityEventType(str, Enum):
    """Liquidity sweep and pool event types."""
    BUY_SIDE_SWEEP = "BUY_SIDE_SWEEP"    # Price swept above resistance/high and rejected
    SELL_SIDE_SWEEP = "SELL_SIDE_SWEEP"  # Price swept below support/low and rejected
    EQUAL_HIGHS = "EQUAL_HIGHS"          # Double top / liquidity pool above
    EQUAL_LOWS = "EQUAL_LOWS"            # Double bottom / liquidity pool below


class ZoneType(str, Enum):
    """Support and Resistance zone classification."""
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class BreakoutEvent(BaseModel):
    """BOS or CHOCH/MSS market structure breakout event."""
    index: int = Field(..., description="Candle index that executed the structure break")
    timestamp: datetime = Field(..., description="Timestamp of the breakout candle UTC")
    event_type: BOSCHOCHType = Field(..., description="BULLISH_BOS, BEARISH_BOS, BULLISH_CHOCH, or BEARISH_CHOCH")
    breakout_price: float = Field(..., description="Closing price of the breakout candle")
    broken_swing_price: float = Field(..., description="Price of the broken swing level")
    broken_swing_index: int = Field(..., description="Candle index of the broken swing point")
    broken_swing_timestamp: datetime = Field(..., description="Timestamp of the broken swing point")
    broken_swing_label: Optional[StructureLabel] = Field(default=None, description="HH, HL, LH, LL label of broken swing")
    displacement_strength: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Displacement/momentum score of the breakout candle (0.0 to 1.0)",
    )

    model_config = ConfigDict(from_attributes=True)


class LiquiditySweep(BaseModel):
    """Liquidity sweep / stop hunt event."""
    index: int = Field(..., description="Index of the candle performing the sweep")
    timestamp: datetime = Field(..., description="Timestamp of the sweep candle UTC")
    sweep_type: LiquidityEventType = Field(..., description="BUY_SIDE_SWEEP or SELL_SIDE_SWEEP")
    swept_level: float = Field(..., description="Key swing level price that was breached")
    sweep_extreme: float = Field(..., description="Extreme price reached by the wick (High or Low)")
    close_price: float = Field(..., description="Close price confirming rejection back inside the level")
    wick_ratio: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Ratio of rejection wick to candle range",
    )
    pips_swept: float = Field(..., ge=0.0, description="Distance in pips penetrated beyond the level")
    broken_swing_timestamp: Optional[datetime] = Field(default=None, description="Timestamp of swept swing point")

    model_config = ConfigDict(from_attributes=True)


class LiquidityPool(BaseModel):
    """Equal Highs / Equal Lows resting liquidity pool."""
    pool_type: LiquidityEventType = Field(..., description="EQUAL_HIGHS or EQUAL_LOWS")
    price_level: float = Field(..., description="Average price level of the liquidity pool")
    touch_points: int = Field(default=2, ge=2, description="Number of swing extremes forming this pool")
    first_timestamp: datetime = Field(..., description="First touch timestamp")
    last_timestamp: datetime = Field(..., description="Most recent touch timestamp")
    is_swept: bool = Field(default=False, description="Whether this pool has since been swept by price")

    model_config = ConfigDict(from_attributes=True)


class SupportResistanceZone(BaseModel):
    """Dynamic Support or Resistance Zone derived from price reactions and swing clusters."""
    zone_type: ZoneType = Field(..., description="SUPPORT or RESISTANCE")
    price_low: float = Field(..., description="Lower bound of the S/R zone")
    price_high: float = Field(..., description="Upper bound of the S/R zone")
    center_price: float = Field(..., description="Center median price of the zone")
    touch_count: int = Field(default=1, ge=1, description="Number of swing touches validating this zone")
    strength: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Zone strength score based on touches, recency, and reaction quality",
    )
    is_fresh: bool = Field(default=True, description="True if zone has not been cleanly breached by candle closes")
    last_touch_timestamp: Optional[datetime] = Field(default=None, description="Timestamp of latest touch")

    model_config = ConfigDict(from_attributes=True)


class AdvancedStructureAnalysisResponse(BaseModel):
    """Combined comprehensive analysis response with BOS, CHOCH, Liquidity Sweeps, and S/R Zones."""
    symbol: str = Field(..., description="Forex instrument symbol")
    timeframe: str = Field(..., description="Analyzed timeframe")
    trend: TrendDirection = Field(..., description="Current trend direction")
    trend_strength: float = Field(..., description="Trend strength score")
    market_state: str = Field(..., description="Institutional market state classification")
    
    # Structure Events
    bos_events: List[BreakoutEvent] = Field(default_factory=list, description="All detected Break of Structure events")
    choch_events: List[BreakoutEvent] = Field(default_factory=list, description="All detected Change of Character / MSS events")
    latest_bos: Optional[BreakoutEvent] = Field(default=None, description="Most recent BOS event")
    latest_choch: Optional[BreakoutEvent] = Field(default=None, description="Most recent CHOCH event")
    
    # Liquidity & S/R
    liquidity_sweeps: List[LiquiditySweep] = Field(default_factory=list, description="All detected liquidity sweep events")
    latest_sweep: Optional[LiquiditySweep] = Field(default=None, description="Most recent liquidity sweep")
    liquidity_pools: List[LiquidityPool] = Field(default_factory=list, description="Active Equal High/Low liquidity pools")
    sr_zones: List[SupportResistanceZone] = Field(default_factory=list, description="Dynamic Support and Resistance zones")
    
    # Base Structure Reference
    base_structure: StructureAnalysisResponse = Field(..., description="Base swing structure analysis")

    model_config = ConfigDict(from_attributes=True)
