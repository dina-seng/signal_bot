"""Market information and API status schemas."""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class MarketSymbolInfo(BaseModel):
    """Information about a supported market instrument."""
    symbol: str
    base_currency: str
    quote_currency: str
    pip_size: float
    description: str


class MarketHealthResponse(BaseModel):
    """System and Market Data health status schema."""
    status: str
    database_connected: bool
    app_version: str
    supported_symbols: List[str]
    supported_timeframes: List[str]
    candle_counts: Dict[str, Dict[str, int]]
    server_time_utc: datetime
    scanner_enabled: Optional[bool] = None
    scanner_running: Optional[bool] = None
    scheduler_running: Optional[bool] = None
    scanner_interval_minutes: Optional[int] = None
    last_scan: Optional[datetime] = None
    next_scan: Optional[datetime] = None
    last_closed_15m_bar_time: Optional[datetime] = None
    candle_age_seconds: Optional[float] = None
    is_data_fresh: bool = False
    data_freshness_status: str = "UNKNOWN"
    credits_used_today: int = 0
    credits_max_budget: int = 780
    last_sync_status: Optional[str] = None
    last_sync_error: Optional[str] = None


class IngestionRequest(BaseModel):
    """Payload for triggering market data sync."""
    symbol: Optional[str] = Field(None, description="Specific symbol or null for all")
    timeframe: Optional[str] = Field(None, description="Specific timeframe or null for all")
    limit: int = Field(default=200, ge=10, le=2000, description="Number of candles to fetch per timeframe")


class QuoteResponse(BaseModel):
    """Real-time market price quote schema."""
    symbol: str
    price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[float] = None
    timestamp: datetime
    source: str = "realtime"
    provider: str = "twelvedata"
    provider_symbol: str = ""
    age_seconds: float = 0.0
    is_stale: bool = False
    degraded: bool = False
    fallback_reason: Optional[str] = None
    cached: bool = False
    cache_age_ms: Optional[float] = None
