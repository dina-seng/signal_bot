"""System Configuration API Endpoint."""

from typing import List
from fastapi import APIRouter
from pydantic import BaseModel
from app.core.config import settings, ACTIVE_SYMBOLS

router = APIRouter(prefix="/config", tags=["Configuration"])


class AppConfigResponse(BaseModel):
    """Read-only system configuration schema containing zero secrets."""
    min_confluence_score: float
    duplicate_cooldown_hours: int
    risk_per_order_pct: float
    news_buffer_pre_min: int
    news_buffer_post_min: int
    min_rr_tp1: float
    min_rr_tp2: float
    quote_poll_seconds: int
    mode: str
    provider_name: str
    quote_max_age_seconds: int
    quote_cache_ttl_seconds: float
    quote_response_cache_ttl_seconds: int
    derived_cache_ttl_seconds: float
    dashboard_poll_seconds: int
    quote_idle_cache_ttl_seconds: int
    quote_presence_ttl_seconds: int
    quote_stale_after_seconds: int
    active_symbols: List[str]


@router.get("", response_model=AppConfigResponse)
def get_system_config():
    """Retrieve read-only system settings and operational thresholds."""
    return AppConfigResponse(
        min_confluence_score=settings.MIN_SETUP_SCORE,
        duplicate_cooldown_hours=settings.SIGNAL_COOLDOWN_HOURS,
        risk_per_order_pct=settings.MAX_RISK_PERCENT,
        news_buffer_pre_min=settings.NEWS_BLACKOUT_BEFORE_MINUTES,
        news_buffer_post_min=settings.NEWS_BLACKOUT_AFTER_MINUTES,
        min_rr_tp1=settings.MIN_RR_TP1,
        min_rr_tp2=settings.MIN_RR_TP2,
        quote_poll_seconds=settings.QUOTE_POLL_SECONDS,
        mode=settings.MODE,
        provider_name=settings.MARKET_DATA_PROVIDER,
        quote_max_age_seconds=settings.QUOTE_MAX_AGE_SECONDS,
        quote_cache_ttl_seconds=settings.QUOTE_CACHE_TTL_SECONDS,
        quote_response_cache_ttl_seconds=settings.QUOTE_RESPONSE_CACHE_TTL_SECONDS,
        derived_cache_ttl_seconds=settings.DERIVED_CACHE_TTL_SECONDS,
        dashboard_poll_seconds=settings.DASHBOARD_POLL_SECONDS,
        quote_idle_cache_ttl_seconds=settings.QUOTE_IDLE_CACHE_TTL_SECONDS,
        quote_presence_ttl_seconds=settings.QUOTE_PRESENCE_TTL_SECONDS,
        quote_stale_after_seconds=settings.QUOTE_STALE_AFTER_SECONDS,
        active_symbols=list(ACTIVE_SYMBOLS),
    )
