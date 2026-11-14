"""Pydantic schemas for Signal Candidates."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class SignalCandidateCreate(BaseModel):
    """Schema for logging a candidate trade setup."""
    symbol: str = "XAU/USD"
    timestamp: datetime
    timeframe: str = "15m"
    direction: str  # BUY, SELL, WAIT

    # Pillar Scores
    structure_score: float = 0.0
    liquidity_score: float = 0.0
    indicators_score: float = 0.0
    price_action_score: float = 0.0
    total_score: float = 0.0

    # Key Features
    htf_trend: Optional[str] = None
    session: Optional[str] = None
    atr_percentile: Optional[float] = None
    sweep_yes_no: bool = False
    bos_choch_type: Optional[str] = None
    fvg_ob_present: bool = False
    premium_discount: Optional[str] = None
    rr: Optional[float] = None
    distance_to_sl_atr: Optional[float] = None

    # Final Score & Qualification
    final_score: float = 0.0
    qualified: bool = False

    # Outcome Labels
    reached_1r: Optional[bool] = None
    reached_2r: Optional[bool] = None
    hit_sl: Optional[bool] = None
    mfe: Optional[float] = None
    mae: Optional[float] = None
    bars_to_resolution: Optional[int] = None
    r_multiple: Optional[float] = None

    # Pricing & Metadata
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    strategy_name: Optional[str] = None
    source: Optional[str] = "twelvedata"
    skipped_reason: Optional[str] = None


class SignalCandidateResponse(SignalCandidateCreate):
    """Schema for returning signal candidate data."""
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
