"""Pydantic schemas for Candle data, ingestion, and validation."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CandleBase(BaseModel):
    """Base candle schema."""
    symbol: str = Field(..., description="Forex or commodity symbol, e.g., 'EUR/USD'")
    timeframe: str = Field(..., description="Timeframe, e.g., '15m', '1h', '4h'")
    timestamp: datetime = Field(..., description="Start timestamp of the candle in UTC")
    open: float = Field(..., description="Opening price")
    high: float = Field(..., description="Highest price during period")
    low: float = Field(..., description="Lowest price during period")
    close: float = Field(..., description="Closing price")
    volume: float = Field(default=0.0, ge=0.0, description="Tick volume or trade volume")


class CandleCreate(CandleBase):
    """Schema for validating and creating a candle."""

    @model_validator(mode="after")
    def validate_ohlc_invariants(self) -> "CandleCreate":
        """Validate standard OHLC pricing invariants."""
        if self.high < self.low:
            raise ValueError(f"High ({self.high}) cannot be less than Low ({self.low})")
        if self.high < self.open or self.high < self.close:
            raise ValueError(
                f"High ({self.high}) must be >= Open ({self.open}) and Close ({self.close})"
            )
        if self.low > self.open or self.low > self.close:
            raise ValueError(
                f"Low ({self.low}) must be <= Open ({self.open}) and Close ({self.close})"
            )
        if self.open <= 0 or self.high <= 0 or self.low <= 0 or self.close <= 0:
            raise ValueError("All OHLC prices must be strictly positive")
        return self


class CandleResponse(CandleBase):
    """Schema for returning candle data via API."""
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CandleFilter(BaseModel):
    """Filter parameters for querying candles."""
    symbol: str
    timeframe: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    limit: int = Field(default=500, ge=1, le=5000)


class GapInfo(BaseModel):
    """Details of a detected gap in candle data."""
    symbol: str
    timeframe: str
    gap_start: datetime
    gap_end: datetime
    missing_candles_estimated: int


class IngestionReport(BaseModel):
    """Report generated after market data ingestion."""
    symbol: str
    timeframe: str
    fetched_count: int
    inserted_count: int
    skipped_duplicates_count: int
    invalid_candles_count: int
    gaps_detected: List[GapInfo] = Field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
