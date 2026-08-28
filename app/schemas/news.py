"""Pydantic schemas for Economic News Calendar and Blackout Filter."""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class NewsImpact(str, Enum):
    """Economic news event impact level."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class NewsEventBase(BaseModel):
    """Base schema for an economic calendar event."""
    currency: str = Field(..., description="Currency code affected (e.g. 'USD', 'EUR', 'GBP', 'JPY')")
    event_name: str = Field(..., description="Name of the economic indicator or release (e.g. 'Non-Farm Payrolls')")
    impact: NewsImpact = Field(..., description="HIGH, MEDIUM, or LOW impact")
    scheduled_time: datetime = Field(..., description="Scheduled release time in UTC")
    previous: Optional[str] = Field(default=None, description="Previous reading")
    forecast: Optional[str] = Field(default=None, description="Market consensus forecast")
    actual: Optional[str] = Field(default=None, description="Actual released figure if available")


class NewsEventCreate(NewsEventBase):
    """Schema for creating a news event record."""
    pass


class NewsEventResponse(NewsEventBase):
    """Schema for returning news event data via API."""
    id: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)



class NewsBlackoutCheckResponse(BaseModel):
    """Result of news blackout filter check for a specific Forex instrument."""
    symbol: str = Field(..., description="Forex instrument checked (e.g. 'EUR/USD')")
    checked_time: datetime = Field(..., description="Reference UTC timestamp evaluated")
    is_blackout: bool = Field(..., description="True if currently within an active news blackout window")
    trading_allowed: bool = Field(..., description="True if safe to trade / generate signals")
    reason: str = Field(..., description="Explanation of blackout status or permission")
    blackout_events: List[NewsEventResponse] = Field(
        default_factory=list, description="High impact events currently causing blackout"
    )
    next_event: Optional[NewsEventResponse] = Field(
        default=None, description="Upcoming economic event within 24 hours"
    )
    minutes_to_next_event: Optional[float] = Field(
        default=None, description="Minutes remaining until next scheduled event"
    )
    minutes_since_last_event: Optional[float] = Field(
        default=None, description="Minutes elapsed since most recent event"
    )

    model_config = ConfigDict(from_attributes=True)


class NewsSyncReport(BaseModel):
    """Report generated after syncing economic calendar."""
    fetched_count: int
    inserted_count: int
    skipped_count: int
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
