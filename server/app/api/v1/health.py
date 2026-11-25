"""Health and System Status Endpoints."""

from datetime import datetime, timezone
from typing import Dict, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select, func, desc
from app.core.database import get_db, SessionLocal
from app.core.config import settings
from app.core.metrics import metrics
from app.services.market_data.cache import derived_cache, provider_cache
from app.models.candle import Candle
from app.schemas.market import MarketHealthResponse
from app.services.market_data.freshness import ensure_utc_datetime, is_forex_weekend
from app.services.market_data.twelvedata_provider import get_daily_usage

router = APIRouter(tags=["Health & Status"])


@router.get("/health", response_model=MarketHealthResponse)
def get_health_status(db: Session = Depends(get_db)):
    """Check system health, database connection, and candle store status."""
    db_connected = True
    counts_map: Dict[str, Dict[str, int]] = {}
    last_15m_bar: Optional[Candle] = None

    try:
        stmt = select(
            Candle.symbol, Candle.timeframe, func.count(Candle.id)
        ).group_by(Candle.symbol, Candle.timeframe)
        results = db.execute(stmt).all()

        for symbol in settings.SUPPORTED_SYMBOLS:
            counts_map[symbol] = {}
            for tf in settings.SUPPORTED_TIMEFRAMES:
                counts_map[symbol][tf] = 0

        for symbol, tf, count in results:
            if symbol not in counts_map:
                counts_map[symbol] = {}
            counts_map[symbol][tf] = count

        # Query latest closed 15m bar for XAU/USD
        last_15m_bar = db.scalars(
            select(Candle)
            .where(Candle.symbol == "XAU/USD", Candle.timeframe == "15m")
            .order_by(desc(Candle.timestamp))
            .limit(1)
        ).first()

    except Exception:
        db_connected = False

    # Scheduler info
    scanner_running = False
    last_scan = None
    next_scan = None
    try:
        from app.services.telegram.scheduler import get_scheduler_info
        info = get_scheduler_info()
        scanner_running = info.get("is_running", False)
        last_scan = info.get("last_scan_at")
        next_scan = info.get("next_scan_at")
    except Exception:
        pass

    # API Usage today
    usage_info = get_daily_usage(SessionLocal)
    credits_today = usage_info.get("calls_today", 0)

    # Freshness evaluation
    now_utc = datetime.now(timezone.utc)
    last_bar_time = None
    age_seconds = None
    is_fresh = False
    freshness_status = "STALE"

    if last_15m_bar and last_15m_bar.timestamp:
        last_bar_time = ensure_utc_datetime(last_15m_bar.timestamp)
        close_time = last_bar_time + (last_15m_bar.timestamp - last_15m_bar.timestamp + (datetime(2000, 1, 1, 0, 15) - datetime(2000, 1, 1, 0, 0)))
        age_seconds = max(0.0, (now_utc - close_time).total_seconds())

        weekend = is_forex_weekend(now_utc)
        if weekend:
            # During weekend/break, if Friday close exists, data is not stale
            is_fresh = True
            freshness_status = "MARKET_CLOSED"
        elif age_seconds <= 1800.0:  # Fresh if bar is <= 30 minutes old
            is_fresh = True
            freshness_status = "FRESH"
        else:
            is_fresh = False
            freshness_status = "STALE"

    overall_status = "healthy"
    if not db_connected or credits_today >= 780 or (not is_fresh and freshness_status == "STALE"):
        overall_status = "degraded"

    return MarketHealthResponse(
        status=overall_status,
        database_connected=db_connected,
        app_version="1.0.0",
        supported_symbols=settings.SUPPORTED_SYMBOLS,
        supported_timeframes=settings.SUPPORTED_TIMEFRAMES,
        candle_counts=counts_map,
        server_time_utc=now_utc,
        scanner_enabled=settings.SCANNER_ENABLED,
        scanner_running=scanner_running,
        scheduler_running=scanner_running,
        scanner_interval_minutes=settings.SCANNER_INTERVAL_MINUTES,
        last_scan=last_scan,
        next_scan=next_scan,
        last_closed_15m_bar_time=last_bar_time,
        candle_age_seconds=round(age_seconds, 1) if age_seconds is not None else None,
        is_data_fresh=is_fresh,
        data_freshness_status=freshness_status,
        credits_used_today=credits_today,
        credits_max_budget=780,
        last_sync_status="ok" if is_fresh else "sync_needed",
        last_sync_error=None,
    )


@router.get("/health/latency")
def get_latency_health():
    """Expose measured pipeline timings so performance claims can be verified."""
    provider_stats = provider_cache.stats()
    derived_stats = derived_cache.stats()
    snapshot = metrics.snapshot()
    stages = snapshot["stages"]
    return {
        "provider_fetch_ms": provider_stats["avg_provider_fetch_ms"],
        "cache_hit_rate": provider_stats["cache_hit_rate"],
        "db_query_ms": stages.get("db", {}).get("avg_ms", 0.0),
        "serialize_ms": stages.get("serialize", {}).get("avg_ms", 0.0),
        "total_request_ms": snapshot["requests"].get("avg_ms", 0.0),
        "provider_cache": provider_stats,
        "derived_cache": derived_stats,
        "stages": stages,
        "requests": snapshot["requests"],
        "sample_size": snapshot["sample_size"],
        "config": {
            "quote_cache_ttl_seconds": settings.QUOTE_CACHE_TTL_SECONDS,
            "derived_cache_ttl_seconds": settings.DERIVED_CACHE_TTL_SECONDS,
            "cors_max_age_seconds": settings.CORS_MAX_AGE_SECONDS,
            "dashboard_poll_seconds": settings.DASHBOARD_POLL_SECONDS,
        },
    }
