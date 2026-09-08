"""Health and System Status Endpoints."""

from datetime import datetime, timezone
from typing import Dict
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.config import settings
from app.models.candle import Candle
from app.schemas.market import MarketHealthResponse

router = APIRouter(tags=["Health & Status"])


@router.get("/health", response_model=MarketHealthResponse)
def get_health_status(db: Session = Depends(get_db)):
    """Check system health, database connection, and candle store status."""
    db_connected = True
    counts_map: Dict[str, Dict[str, int]] = {}

    try:
        # Query candle count per symbol and timeframe
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

    except Exception:
        db_connected = False

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

    return MarketHealthResponse(
        status="healthy" if db_connected else "degraded",
        database_connected=db_connected,
        app_version="1.0.0",
        supported_symbols=settings.SUPPORTED_SYMBOLS,
        supported_timeframes=settings.SUPPORTED_TIMEFRAMES,
        candle_counts=counts_map,
        server_time_utc=datetime.now(timezone.utc),
        scanner_enabled=settings.SCANNER_ENABLED,
        scanner_running=scanner_running,
        scanner_interval_minutes=settings.SCANNER_INTERVAL_MINUTES,
        last_scan=last_scan,
        next_scan=next_scan,
    )
