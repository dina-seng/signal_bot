"""Backtesting, Performance Metrics, and Optimization API Endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.api.deps import get_backtest_service
from app.schemas.backtesting import (
    BacktestRequest,
    BacktestResultResponse,
    BacktestRunSummary,
    ParameterSweepRequest,
    ParameterSweepResponse,
    StatelessBacktestRequest,
)
from app.services.backtesting import BacktestService

router = APIRouter(prefix="/backtest", tags=["Backtesting & Optimization"])


def _normalize_symbol(symbol: str) -> str:
    """Normalize currency pair symbol string."""
    clean_symbol = symbol.replace("%2F", "/").strip()
    if clean_symbol in settings.SUPPORTED_SYMBOLS:
        return clean_symbol
    for s in settings.SUPPORTED_SYMBOLS:
        if s.replace("/", "") == clean_symbol.replace("/", ""):
            return s
    return clean_symbol


@router.post("/run", response_model=BacktestResultResponse)
def run_backtest(
    request: BacktestRequest,
    db: Session = Depends(get_db),
    service: BacktestService = Depends(get_backtest_service),
):
    """Run historical backtest simulation using stored candles from the database."""
    request.symbol = _normalize_symbol(request.symbol)
    try:
        return service.run_backtest(db=db, request=request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backtest execution failed: {str(e)}")


@router.post("/execute", response_model=BacktestResultResponse)
def execute_stateless_backtest(
    request: StatelessBacktestRequest,
    service: BacktestService = Depends(get_backtest_service),
):
    """Execute on-demand stateless backtest on provided custom candle series."""
    request.symbol = _normalize_symbol(request.symbol)
    try:
        return service.execute_stateless(request=request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stateless simulation failed: {str(e)}")


@router.post("/optimize", response_model=ParameterSweepResponse)
def optimize_parameters(
    request: ParameterSweepRequest,
    db: Session = Depends(get_db),
    service: BacktestService = Depends(get_backtest_service),
):
    """Run parameter optimization sweep across threshold scores, risk %, and R:R ratios."""
    request.symbol = _normalize_symbol(request.symbol)
    try:
        return service.optimize_parameters(db=db, request=request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimization sweep failed: {str(e)}")


@router.get("/runs", response_model=List[BacktestRunSummary])
def get_backtest_runs(
    symbol: Optional[str] = Query(None, description="Filter runs by symbol"),
    timeframe: Optional[str] = Query(None, description="Filter runs by timeframe"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    service: BacktestService = Depends(get_backtest_service),
):
    """Retrieve historical saved backtest runs."""
    norm_sym = _normalize_symbol(symbol) if symbol else None
    return service.get_runs(db=db, symbol=norm_sym, timeframe=timeframe, limit=limit)


@router.get("/runs/{run_id}", response_model=BacktestResultResponse)
def get_backtest_run_details(
    run_id: int,
    db: Session = Depends(get_db),
    service: BacktestService = Depends(get_backtest_service),
):
    """Retrieve detailed report and trade logs for a specific backtest run."""
    result = service.get_run_details(db=db, run_id=run_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Backtest run #{run_id} not found.")
    return result


@router.delete("/runs/{run_id}")
def delete_backtest_run(
    run_id: int,
    db: Session = Depends(get_db),
    service: BacktestService = Depends(get_backtest_service),
):
    """Delete a saved backtest run and its trade logs."""
    deleted = service.delete_run(db=db, run_id=run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Backtest run #{run_id} not found.")
    return {"status": "success", "message": f"Backtest run #{run_id} deleted successfully."}
