"""Technical Indicators, RSI Divergence, Price Action & Fair Value Gap API Endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.config import settings
from app.api.deps import get_indicator_service
from app.models.candle import Candle
from app.schemas.indicators import (
    FairValueGap,
    IndicatorAnalysisResponse,
    RSIDivergence,
    StatelessIndicatorRequest,
)
from app.services.indicators import IndicatorService

router = APIRouter(prefix="/indicators", tags=["Technical Indicators & Price Action"])


def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol string."""
    clean_symbol = symbol.replace("%2F", "/").strip()
    if clean_symbol in settings.SUPPORTED_SYMBOLS:
        return clean_symbol
    for s in settings.SUPPORTED_SYMBOLS:
        if s.replace("/", "") == clean_symbol.replace("/", ""):
            return s
    return clean_symbol


@router.get("/{symbol:path}/fvg", response_model=List[FairValueGap])
def get_fair_value_gaps(
    symbol: str,
    timeframe: str = Query("1h", description="Timeframe e.g. 15m, 1h, 4h"),
    limit: int = Query(200, ge=20, le=2000),
    db: Session = Depends(get_db),
    indicator_service: IndicatorService = Depends(get_indicator_service),
):
    """Query active and historical Fair Value Gaps (FVG) / Price Imbalances."""
    clean_symbol = _normalize_symbol(symbol)
    tf = timeframe.lower().strip()

    stmt = (
        select(Candle)
        .where(Candle.symbol == clean_symbol, Candle.timeframe == tf)
        .order_by(desc(Candle.timestamp))
        .limit(limit)
    )
    records = list(db.scalars(stmt).all())
    records.reverse()

    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"No candles found for symbol '{clean_symbol}' and timeframe '{tf}'.",
        )

    analysis = indicator_service.analyze_indicators(
        candles=records,
        symbol=clean_symbol,
        timeframe=tf,
    )
    return analysis.active_fvgs


@router.get("/{symbol:path}/divergences", response_model=List[RSIDivergence])
def get_rsi_divergences(
    symbol: str,
    timeframe: str = Query("1h", description="Timeframe e.g. 15m, 1h, 4h"),
    limit: int = Query(200, ge=20, le=2000),
    db: Session = Depends(get_db),
    indicator_service: IndicatorService = Depends(get_indicator_service),
):
    """Query detected Regular and Hidden RSI Divergences."""
    clean_symbol = _normalize_symbol(symbol)
    tf = timeframe.lower().strip()

    stmt = (
        select(Candle)
        .where(Candle.symbol == clean_symbol, Candle.timeframe == tf)
        .order_by(desc(Candle.timestamp))
        .limit(limit)
    )
    records = list(db.scalars(stmt).all())
    records.reverse()

    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"No candles found for symbol '{clean_symbol}' and timeframe '{tf}'.",
        )

    analysis = indicator_service.analyze_indicators(
        candles=records,
        symbol=clean_symbol,
        timeframe=tf,
    )
    return analysis.divergences


@router.get("/{symbol:path}", response_model=IndicatorAnalysisResponse)
def get_indicator_analysis(
    symbol: str,
    timeframe: str = Query("1h", description="Timeframe e.g. 15m, 1h, 4h"),
    limit: int = Query(200, ge=20, le=2000, description="Max historical candles to analyze"),
    ema_fast: int = Query(20, ge=2, le=100),
    ema_mid: int = Query(50, ge=5, le=200),
    ema_slow: int = Query(200, ge=20, le=500),
    rsi_period: int = Query(14, ge=2, le=50),
    atr_period: int = Query(14, ge=2, le=50),
    db: Session = Depends(get_db),
    indicator_service: IndicatorService = Depends(get_indicator_service),
):
    """Retrieve full technical indicators (EMA 20/50/200, RSI 14, ATR 14), Divergences, Price Action Patterns, and FVGs."""
    clean_symbol = _normalize_symbol(symbol)
    tf = timeframe.lower().strip()

    stmt = (
        select(Candle)
        .where(Candle.symbol == clean_symbol, Candle.timeframe == tf)
        .order_by(desc(Candle.timestamp))
        .limit(limit)
    )
    records = list(db.scalars(stmt).all())
    records.reverse()

    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"No candles found for symbol '{clean_symbol}' and timeframe '{tf}'. Please sync market data first.",
        )

    return indicator_service.analyze_indicators(
        candles=records,
        symbol=clean_symbol,
        timeframe=tf,
        ema_fast=ema_fast,
        ema_mid=ema_mid,
        ema_slow=ema_slow,
        rsi_period=rsi_period,
        atr_period=atr_period,
    )


@router.post("/analyze", response_model=IndicatorAnalysisResponse)
def analyze_stateless_indicators(
    request: StatelessIndicatorRequest,
    indicator_service: IndicatorService = Depends(get_indicator_service),
):
    """Stateless on-demand technical indicator and price action calculation for custom candle series."""
    if not request.candles:
        raise HTTPException(
            status_code=400,
            detail="Candles list cannot be empty",
        )

    return indicator_service.analyze_indicators(
        candles=request.candles,
        symbol=request.symbol or "CUSTOM",
        timeframe=request.timeframe or "1h",
        ema_fast=request.ema_fast or 20,
        ema_mid=request.ema_mid or 50,
        ema_slow=request.ema_slow or 200,
        rsi_period=request.rsi_period or 14,
        atr_period=request.atr_period or 14,
    )
