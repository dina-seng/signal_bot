"""High-level Backtesting Orchestration and Database Persistence Service."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Union
from sqlalchemy.orm import Session
from sqlalchemy import select, desc, delete

from app.core.logging import logger
from app.models.candle import Candle
from app.models.backtest import BacktestRun, BacktestTrade
from app.schemas.backtesting import (
    BacktestConfig,
    BacktestRequest,
    BacktestResultResponse,
    BacktestRunSummary,
    BacktestTradeLog,
    EquityPoint,
    ParameterSweepRequest,
    ParameterSweepResponse,
    PerformanceMetrics,
    StatelessBacktestRequest,
)
from app.schemas.candle import CandleBase
from app.schemas.signal import SignalDirection
from app.services.backtesting.backtest_engine import BacktestEngine
from app.services.backtesting.optimization import ParameterOptimizer


class BacktestService:
    """Service coordinating database retrieval, backtest execution, persistence, and sweeps."""

    def __init__(
        self,
        engine: Optional[BacktestEngine] = None,
        optimizer: Optional[ParameterOptimizer] = None,
    ):
        self.engine = engine or BacktestEngine()
        self.optimizer = optimizer or ParameterOptimizer(engine=self.engine)

    def run_backtest(
        self,
        db: Session,
        request: BacktestRequest,
    ) -> BacktestResultResponse:
        """Fetch historical candles from database, run simulation, and persist results."""
        # 1. Query candles from DB
        stmt = (
            select(Candle)
            .where(
                Candle.symbol == request.symbol,
                Candle.timeframe == request.timeframe,
            )
            .order_by(Candle.timestamp.asc())
        )

        if request.start_date:
            stmt = stmt.where(Candle.timestamp >= request.start_date)
        if request.end_date:
            stmt = stmt.where(Candle.timestamp <= request.end_date)

        candles = list(db.scalars(stmt).all())

        if not candles:
            raise ValueError(
                f"No candle data found in database for symbol '{request.symbol}' and timeframe '{request.timeframe}'."
            )

        # Query 4h and 15m candles for MTF if available
        candles_4h = list(
            db.scalars(
                select(Candle)
                .where(Candle.symbol == request.symbol, Candle.timeframe == "4h")
                .order_by(Candle.timestamp.asc())
            ).all()
        )
        candles_15m = list(
            db.scalars(
                select(Candle)
                .where(Candle.symbol == request.symbol, Candle.timeframe == "15m")
                .order_by(Candle.timestamp.asc())
            ).all()
        )

        # 2. Run simulation
        result = self.engine.run_simulation(
            candles=candles,
            symbol=request.symbol,
            timeframe=request.timeframe,
            config=request.config or BacktestConfig(),
            candles_4h=candles_4h if candles_4h else None,
            candles_15m=candles_15m if candles_15m else None,
            name=request.name or f"{request.symbol} {request.timeframe} Backtest",
        )

        # 3. Persist run & trades if requested
        if request.save_run:
            m = result.metrics
            cfg = result.config

            db_run = BacktestRun(
                name=result.name,
                symbol=result.symbol,
                timeframe=result.timeframe,
                start_date=result.start_date,
                end_date=result.end_date,
                initial_balance=m.initial_balance,
                final_balance=m.final_balance,
                total_pnl=m.total_pnl,
                total_pnl_percent=m.total_pnl_percent,
                total_trades=m.total_trades,
                winning_trades=m.winning_trades,
                losing_trades=m.losing_trades,
                break_even_trades=m.break_even_trades,
                win_rate=m.win_rate,
                profit_factor=m.profit_factor,
                max_drawdown_pct=m.max_drawdown_pct,
                max_drawdown_usd=m.max_drawdown_usd,
                sharpe_ratio=m.sharpe_ratio,
                sortino_ratio=m.sortino_ratio,
                calmar_ratio=m.calmar_ratio,
                expectancy_usd=m.expectancy_usd,
                expectancy_r=m.expectancy_r,
                config=cfg.model_dump(),
                metrics=m.model_dump(),
            )
            db.add(db_run)
            db.commit()
            db.refresh(db_run)

            # Persist individual trades
            for t in result.trades:
                db_trade = BacktestTrade(
                    run_id=db_run.id,
                    symbol=t.symbol,
                    direction=t.direction.value,
                    entry_time=t.entry_time,
                    exit_time=t.exit_time,
                    entry_price=t.entry_price,
                    exit_price=t.exit_price,
                    stop_loss=t.stop_loss,
                    take_profit_1=t.take_profit_1,
                    take_profit_2=t.take_profit_2,
                    position_size=t.position_size,
                    pnl=t.pnl,
                    pnl_percent=t.pnl_percent,
                    return_r=t.return_r,
                    exit_reason=t.exit_reason,
                    score=t.score,
                )
                db.add(db_trade)

            db.commit()
            result.run_id = db_run.id
            logger.info(
                f"PERSISTED BACKTEST RUN #{db_run.id}: {db_run.symbol} {db_run.timeframe} "
                f"(Trades: {m.total_trades}, WinRate: {m.win_rate}%, PF: {m.profit_factor}, PnL: ${m.total_pnl})"
            )

        return result

    def execute_stateless(
        self,
        request: StatelessBacktestRequest,
    ) -> BacktestResultResponse:
        """Run in-memory backtest on user-supplied candle series without database dependency."""
        if not request.candles or len(request.candles) < 15:
            raise ValueError("Candles array must contain at least 15 candles for simulation.")

        return self.engine.run_simulation(
            candles=request.candles,
            symbol=request.symbol,
            timeframe=request.timeframe,
            config=request.config or BacktestConfig(),
            name=f"Stateless {request.symbol} {request.timeframe} Test",
        )

    def optimize_parameters(
        self,
        db: Session,
        request: ParameterSweepRequest,
    ) -> ParameterSweepResponse:
        """Run parameter sweep optimization on historical candles from DB."""
        stmt = (
            select(Candle)
            .where(
                Candle.symbol == request.symbol,
                Candle.timeframe == request.timeframe,
            )
            .order_by(Candle.timestamp.asc())
        )

        if request.start_date:
            stmt = stmt.where(Candle.timestamp >= request.start_date)
        if request.end_date:
            stmt = stmt.where(Candle.timestamp <= request.end_date)

        candles = list(db.scalars(stmt).all())

        if not candles:
            raise ValueError(
                f"No candles found for parameter optimization on {request.symbol} {request.timeframe}."
            )

        candles_4h = list(
            db.scalars(
                select(Candle)
                .where(Candle.symbol == request.symbol, Candle.timeframe == "4h")
                .order_by(Candle.timestamp.asc())
            ).all()
        )
        candles_15m = list(
            db.scalars(
                select(Candle)
                .where(Candle.symbol == request.symbol, Candle.timeframe == "15m")
                .order_by(Candle.timestamp.asc())
            ).all()
        )

        return self.optimizer.run_sweep(
            candles=candles,
            symbol=request.symbol,
            timeframe=request.timeframe,
            request=request,
            candles_4h=candles_4h if candles_4h else None,
            candles_15m=candles_15m if candles_15m else None,
        )

    def get_runs(
        self,
        db: Session,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: int = 50,
    ) -> List[BacktestRunSummary]:
        """List historical backtest runs."""
        stmt = select(BacktestRun)
        if symbol:
            stmt = stmt.where(BacktestRun.symbol == symbol)
        if timeframe:
            stmt = stmt.where(BacktestRun.timeframe == timeframe)

        stmt = stmt.order_by(desc(BacktestRun.created_at)).limit(limit)
        runs = list(db.scalars(stmt).all())
        return [BacktestRunSummary.model_validate(r) for r in runs]

    def get_run_details(
        self,
        db: Session,
        run_id: int,
    ) -> Optional[BacktestResultResponse]:
        """Retrieve full details of a saved backtest run, including trade logs."""
        run = db.get(BacktestRun, run_id)
        if not run:
            return None

        trades_stmt = (
            select(BacktestTrade)
            .where(BacktestTrade.run_id == run_id)
            .order_by(BacktestTrade.entry_time.asc())
        )
        db_trades = list(db.scalars(trades_stmt).all())

        trade_logs: List[BacktestTradeLog] = []
        for t in db_trades:
            trade_logs.append(
                BacktestTradeLog(
                    id=t.id,
                    run_id=t.run_id,
                    symbol=t.symbol,
                    direction=SignalDirection(t.direction),
                    entry_time=t.entry_time,
                    exit_time=t.exit_time,
                    entry_price=t.entry_price,
                    exit_price=t.exit_price,
                    stop_loss=t.stop_loss,
                    take_profit_1=t.take_profit_1,
                    take_profit_2=t.take_profit_2,
                    position_size=t.position_size,
                    pnl=t.pnl,
                    pnl_percent=t.pnl_percent,
                    return_r=t.return_r,
                    exit_reason=t.exit_reason,
                    score=t.score,
                )
            )

        metrics = PerformanceMetrics.model_validate(run.metrics)
        config = BacktestConfig.model_validate(run.config)

        return BacktestResultResponse(
            run_id=run.id,
            name=run.name,
            symbol=run.symbol,
            timeframe=run.timeframe,
            start_date=run.start_date,
            end_date=run.end_date,
            config=config,
            metrics=metrics,
            equity_curve=[],  # Equity curve is synthesized in live simulation
            trades=trade_logs,
            created_at=run.created_at,
        )

    def delete_run(self, db: Session, run_id: int) -> bool:
        """Delete a backtest run and all its associated trades."""
        run = db.get(BacktestRun, run_id)
        if not run:
            return False
        db.delete(run)
        db.commit()
        return True
