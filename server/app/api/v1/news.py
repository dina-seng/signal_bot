"""Economic News Calendar and Blackout Filter API Endpoints."""

from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.config import settings
from app.api.deps import get_news_filter_engine, get_news_ingestion_service
from app.models.news import NewsEvent
from app.schemas.news import (
    NewsBlackoutCheckResponse,
    NewsEventResponse,
    NewsImpact,
    NewsSyncReport,
)
from app.services.news import NewsFilterEngine, NewsIngestionService

router = APIRouter(prefix="/news", tags=["Economic News & Blackout Filter"])


def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol string."""
    clean_symbol = symbol.replace("%2F", "/").strip()
    if clean_symbol in settings.SUPPORTED_SYMBOLS:
        return clean_symbol
    for s in settings.SUPPORTED_SYMBOLS:
        if s.replace("/", "") == clean_symbol.replace("/", ""):
            return s
    return clean_symbol


@router.get("/calendar", response_model=List[NewsEventResponse])
def get_economic_calendar(
    currency: Optional[str] = Query(None, description="Filter by currency code (e.g. USD, EUR, GBP, JPY)"),
    impact: Optional[str] = Query(None, description="Filter by impact level: HIGH, MEDIUM, LOW"),
    start_time: Optional[datetime] = Query(None, description="Start scheduled time UTC"),
    end_time: Optional[datetime] = Query(None, description="End scheduled time UTC"),
    limit: int = Query(50, ge=1, le=500, description="Max records to return"),
    db: Session = Depends(get_db),
):
    """Retrieve scheduled economic calendar events from database."""
    stmt = select(NewsEvent)

    if currency:
        stmt = stmt.where(NewsEvent.currency == currency.upper().strip())
    if impact:
        stmt = stmt.where(NewsEvent.impact == impact.upper().strip())
    if start_time:
        stmt = stmt.where(NewsEvent.scheduled_time >= start_time)
    if end_time:
        stmt = stmt.where(NewsEvent.scheduled_time <= end_time)

    stmt = stmt.order_by(NewsEvent.scheduled_time.asc()).limit(limit)
    return list(db.scalars(stmt).all())


@router.get("/check/{symbol:path}", response_model=NewsBlackoutCheckResponse)
def check_news_blackout(
    symbol: str,
    target_time: Optional[str] = Query(None, description="Reference UTC datetime (default: current time)"),
    before_minutes: Optional[int] = Query(None, ge=5, le=180, description="Pre-news blackout buffer minutes"),
    after_minutes: Optional[int] = Query(None, ge=5, le=180, description="Post-news blackout buffer minutes"),
    min_impact: str = Query("HIGH", description="Minimum impact filter ('HIGH' or 'MEDIUM')"),
    db: Session = Depends(get_db),
    filter_engine: NewsFilterEngine = Depends(get_news_filter_engine),
):
    """Check whether a Forex/Commodity symbol is currently in a high-impact news blackout window."""
    clean_symbol = _normalize_symbol(symbol)
    
    ref_time = datetime.now(timezone.utc)
    if target_time:
        try:
            # Handle URL decoded '+' turned into ' '
            cleaned_t = target_time.strip().replace(" ", "+")
            ref_time = datetime.fromisoformat(cleaned_t)
            if ref_time.tzinfo is None:
                ref_time = ref_time.replace(tzinfo=timezone.utc)
            else:
                ref_time = ref_time.astimezone(timezone.utc)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid target_time format '{target_time}'. Must be valid ISO 8601 string.",
            )

    return filter_engine.check_from_db(
        db=db,
        symbol=clean_symbol,
        target_time=ref_time,
        before_minutes=before_minutes,
        after_minutes=after_minutes,
        min_impact=min_impact,
    )



@router.post("/sync", response_model=NewsSyncReport)
async def sync_economic_calendar(
    ingestion_service: NewsIngestionService = Depends(get_news_ingestion_service),
):
    """Trigger manual synchronization of economic calendar from live provider."""
    try:
        report = await ingestion_service.sync_calendar()
        return report
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed syncing economic news calendar: {str(e)}",
        )
