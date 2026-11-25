"""Aggregated dashboard snapshot schema (one round-trip for the full UI)."""

from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class DashboardSnapshotResponse(BaseModel):
    """Everything the dashboard main poll needs, in a single response."""

    symbol: str
    timeframe: str
    quote: Any = None
    # Fast quote tick (QUOTE_CACHE_TTL_SECONDS) used by the chart's forming bar.
    # Kept separate from `candles`, which is the 30s derived-cache history layer.
    live_quote: Any = None
    candles: List[Any] = Field(default_factory=list)
    indicators: Any = None
    structure: Any = None
    liquidity: Any = None
    paper_summary: Any = None
    positions: List[Any] = Field(default_factory=list)
    trades: List[Any] = Field(default_factory=list)
    performance: Any = None
    signals: List[Any] = Field(default_factory=list)
    news: List[Any] = Field(default_factory=list)
    blackout: Any = None
    telegram_status: Any = None
    scanner_status: Any = None
    config: Any = None
    as_of: datetime
    timings_ms: Dict[str, float] = Field(default_factory=dict)
