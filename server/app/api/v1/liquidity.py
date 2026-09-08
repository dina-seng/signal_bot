"""Liquidity, BOS, CHOCH, Sweeps, and Dynamic S/R Zones API Endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.config import settings
from app.api.deps import get_liquidity_service
from app.models.candle import Candle
from app.schemas.candle import CandleBase
from app.schemas.liquidity import (
    AdvancedStructureAnalysisResponse,
    LiquidityPool,
    LiquiditySweep,
    SupportResistanceZone,
)
from app.services.liquidity import LiquidityService

router = APIRouter(prefix="/liquidity", tags=["Liquidity & SMC Structure"])


def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol string."""
    clean_symbol = symbol.replace("%2F", "/").strip()
    if clean_symbol in settings.SUPPORTED_SYMBOLS:
        return clean_symbol
    for s in settings.SUPPORTED_SYMBOLS:
        if s.replace("/", "") == clean_symbol.replace("/", ""):
            return s
    return clean_symbol


class SRZonesResponse(BaseModel):
    """Support/Resistance Zones and Liquidity Pools response."""
    symbol: str
    timeframe: str
    sr_zones: List[SupportResistanceZone]
    liquidity_pools: List[LiquidityPool]


class StatelessLiquidityRequest(BaseModel):
    """Request schema for on-demand liquidity analysis."""
    candles: List[CandleBase] = Field(..., description="Candle list sorted chronologically")
    symbol: Optional[str] = Field(default="CUSTOM")
    timeframe: Optional[str] = Field(default="1h")
    lookback: Optional[int] = Field(default=2, ge=1, le=20)
    tolerance_percent: Optional[float] = Field(default=0.1, ge=0.0, le=2.0)


@router.get("/{symbol:path}/analysis", response_model=AdvancedStructureAnalysisResponse)
def get_liquidity_analysis(
    symbol: str,
    timeframe: str = Query("1h", description="Timeframe e.g. 15m, 1h, 4h"),
    lookback: Optional[int] = Query(None, ge=1, le=20, description="N-bar swing lookback"),
    limit: int = Query(200, ge=10, le=2000, description="Max historical candles to analyze"),
    persist: bool = Query(False, description="Persist detected breakouts and sweeps to database"),
    tolerance_percent: Optional[float] = Query(None, ge=0.0, le=2.0, description="Tolerance % for equal highs/lows and S/R"),
    db: Session = Depends(get_db),
    liquidity_service: LiquidityService = Depends(get_liquidity_service),
):
    """Complete SMC Market Structure, BOS, CHOCH/MSS, Liquidity Sweeps, and S/R Zones analysis."""
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

    analysis = liquidity_service.analyze_liquidity_and_structure(
        candles=records,
        symbol=clean_symbol,
        timeframe=tf,
        lookback=lookback,
        tolerance_percent=tolerance_percent,
    )

    if persist:
        liquidity_service.persist_events(
            db=db,
            symbol=clean_symbol,
            timeframe=tf,
            analysis=analysis,
        )

    return analysis


@router.get("/{symbol:path}/sweeps", response_model=List[LiquiditySweep])
def get_liquidity_sweeps(
    symbol: str,
    timeframe: str = Query("1h", description="Timeframe e.g. 15m, 1h, 4h"),
    lookback: Optional[int] = Query(None, ge=1, le=20),
    limit: int = Query(200, ge=10, le=2000),
    db: Session = Depends(get_db),
    liquidity_service: LiquidityService = Depends(get_liquidity_service),
):
    """Retrieve detected institutional Buy-Side Liquidity (BSL) and Sell-Side Liquidity (SSL) sweeps."""
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

    analysis = liquidity_service.analyze_liquidity_and_structure(
        candles=records,
        symbol=clean_symbol,
        timeframe=tf,
        lookback=lookback,
    )
    return analysis.liquidity_sweeps


@router.get("/{symbol:path}/zones", response_model=SRZonesResponse)
def get_sr_zones_and_pools(
    symbol: str,
    timeframe: str = Query("1h", description="Timeframe e.g. 15m, 1h, 4h"),
    lookback: Optional[int] = Query(None, ge=1, le=20),
    tolerance_percent: Optional[float] = Query(None, ge=0.0, le=2.0),
    limit: int = Query(200, ge=10, le=2000),
    db: Session = Depends(get_db),
    liquidity_service: LiquidityService = Depends(get_liquidity_service),
):
    """Retrieve dynamic Support & Resistance zones and Equal Highs/Lows resting liquidity pools."""
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

    analysis = liquidity_service.analyze_liquidity_and_structure(
        candles=records,
        symbol=clean_symbol,
        timeframe=tf,
        lookback=lookback,
        tolerance_percent=tolerance_percent,
    )

    return SRZonesResponse(
        symbol=clean_symbol,
        timeframe=tf,
        sr_zones=analysis.sr_zones,
        liquidity_pools=analysis.liquidity_pools,
    )


@router.post("/analyze", response_model=AdvancedStructureAnalysisResponse)
def analyze_stateless_liquidity(
    request: StatelessLiquidityRequest,
    liquidity_service: LiquidityService = Depends(get_liquidity_service),
):
    """Stateless on-demand liquidity and structure analysis for arbitrary candle inputs."""
    if not request.candles:
        raise HTTPException(
            status_code=400,
            detail="Candles list cannot be empty",
        )

    analysis = liquidity_service.analyze_liquidity_and_structure(
        candles=request.candles,
        symbol=request.symbol or "CUSTOM",
        timeframe=request.timeframe or "1h",
        lookback=request.lookback,
        tolerance_percent=request.tolerance_percent,
    )
    return analysis
