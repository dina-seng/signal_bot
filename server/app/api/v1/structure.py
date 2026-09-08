"""Market Structure & Trend Classification API Endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.config import settings
from app.api.deps import get_structure_engine, get_mtf_structure_engine
from app.models.candle import Candle
from app.schemas.structure import (
    StructureAnalysisRequest,
    StructureAnalysisResponse,
    MultiTimeframeStructureResponse,
)
from app.services.structure import StructureEngine, MultiTimeframeStructureEngine

router = APIRouter(prefix="/structure", tags=["Market Structure & Trend"])


def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol string handling URL encoding and variations."""
    clean_symbol = symbol.replace("%2F", "/").strip()
    if clean_symbol in settings.SUPPORTED_SYMBOLS:
        return clean_symbol
    for s in settings.SUPPORTED_SYMBOLS:
        if s.replace("/", "") == clean_symbol.replace("/", ""):
            return s
    return clean_symbol


@router.get("/{symbol:path}/multi-timeframe", response_model=MultiTimeframeStructureResponse)
def get_multi_timeframe_structure(
    symbol: str,
    timeframes: str = Query("15m,1h,4h", description="Comma-separated list of timeframes (e.g. '15m,1h,4h')"),
    lookback: Optional[int] = Query(None, ge=1, le=20, description="N-bar swing lookback"),
    limit: int = Query(200, ge=10, le=2000, description="Max candles per timeframe"),
    persist: bool = Query(False, description="Persist detected structure events to DB"),
    tolerance_percent: Optional[float] = Query(None, ge=0.0, le=2.0, description="Tolerance % for equal highs/lows"),
    db: Session = Depends(get_db),
    mtf_engine: MultiTimeframeStructureEngine = Depends(get_mtf_structure_engine),
):
    """Perform Multi-Timeframe (MTF) Market Structure and Trend Alignment Analysis.

    Evaluates higher timeframe (HTF) market structure against intermediate and lower timeframes
    to determine trend confluence, pullbacks, or structural conflicts.
    """
    clean_symbol = _normalize_symbol(symbol)
    tf_list = [tf.strip().lower() for tf in timeframes.split(",") if tf.strip()]

    if not tf_list:
        tf_list = settings.SUPPORTED_TIMEFRAMES

    try:
        response = mtf_engine.analyze_from_db(
            db=db,
            symbol=clean_symbol,
            timeframes=tf_list,
            limit_per_tf=limit,
            lookback=lookback,
            tolerance_percent=tolerance_percent,
            persist=persist,
        )
        return response
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error analyzing multi-timeframe structure for {clean_symbol}: {str(e)}",
        )


@router.get("/{symbol:path}", response_model=StructureAnalysisResponse)
def get_symbol_structure(
    symbol: str,
    timeframe: str = Query("1h", description="Timeframe e.g. 15m, 1h, 4h"),
    lookback: Optional[int] = Query(None, ge=1, le=20, description="N-bar swing lookback (default from settings: 2)"),
    limit: int = Query(200, ge=10, le=2000, description="Number of historical candles to analyze"),
    persist: bool = Query(False, description="Persist detected swings to database"),
    tolerance_percent: Optional[float] = Query(None, ge=0.0, le=2.0, description="Tolerance % for equal highs/lows"),
    db: Session = Depends(get_db),
    structure_engine: StructureEngine = Depends(get_structure_engine),
):
    """Analyze Market Structure (HH, HL, LH, LL, Swings) & Trend for a specific symbol and timeframe."""
    clean_symbol = _normalize_symbol(symbol)
    tf = timeframe.lower().strip()

    # Query historical candles
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

    analysis = structure_engine.analyze_structure(
        candles=records,
        symbol=clean_symbol,
        timeframe=tf,
        lookback=lookback,
        tolerance_percent=tolerance_percent,
    )

    if persist and analysis.swing_points:
        structure_engine.persist_structure_events(
            db=db,
            symbol=clean_symbol,
            timeframe=tf,
            swings=analysis.swing_points,
        )

    return analysis


@router.post("/analyze", response_model=StructureAnalysisResponse)
def analyze_candles_structure(
    request: StructureAnalysisRequest,
    structure_engine: StructureEngine = Depends(get_structure_engine),
):
    """Stateless Market Structure analysis for a provided list of OHLCV candles."""
    if not request.candles:
        raise HTTPException(
            status_code=400,
            detail="Candles list cannot be empty",
        )

    analysis = structure_engine.analyze_structure(
        candles=request.candles,
        symbol=request.symbol or "CUSTOM",
        timeframe=request.timeframe or "1h",
        lookback=request.lookback,
        tolerance_percent=request.tolerance_percent,
    )
    return analysis
