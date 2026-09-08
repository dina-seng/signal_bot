"""Parameter Grid Search and Optimization Engine."""

import itertools
from typing import Any, List, Optional, Sequence, Union

from app.schemas.backtesting import (
    BacktestConfig,
    ParameterSweepRequest,
    ParameterSweepResponse,
    ParameterSweepResultItem,
)
from app.schemas.candle import CandleBase
from app.services.backtesting.backtest_engine import BacktestEngine


class ParameterOptimizer:
    """Systematic parameter optimization across score thresholds, risk %, and R:R targets."""

    def __init__(self, engine: Optional[BacktestEngine] = None):
        self.engine = engine or BacktestEngine()

    def run_sweep(
        self,
        candles: Sequence[Union[CandleBase, Any]],
        symbol: str = "EUR/USD",
        timeframe: str = "1h",
        request: Optional[ParameterSweepRequest] = None,
        candles_4h: Optional[Sequence[Union[CandleBase, Any]]] = None,
        candles_15m: Optional[Sequence[Union[CandleBase, Any]]] = None,
    ) -> ParameterSweepResponse:
        """Execute grid search parameter sweep across specified ranges.

        Args:
            candles: Historical candles.
            symbol: Target symbol.
            timeframe: Target timeframe.
            request: Sweep ranges and base parameters.
            candles_4h: Optional 4h candles.
            candles_15m: Optional 15m candles.

        Returns:
            ParameterSweepResponse with ranked results.
        """
        req = request or ParameterSweepRequest(symbol=symbol, timeframe=timeframe)
        thresholds = req.score_thresholds or [70.0, 75.0, 80.0]
        risk_pcts = req.risk_percentages or [0.5, 1.0]
        rr_targets = req.rr_targets or [1.5, 2.0, 2.5, 3.0]

        results: List[ParameterSweepResultItem] = []
        combinations = list(itertools.product(thresholds, risk_pcts, rr_targets))

        for thresh, risk_p, rr1 in combinations:
            rr2 = round(rr1 + 1.0, 1)
            cfg = BacktestConfig(
                initial_balance=req.initial_balance,
                risk_percent=risk_p,
                min_score_threshold=thresh,
                take_profit_1_rr=rr1,
                take_profit_2_rr=rr2,
                move_sl_to_be_on_tp1=True,
                partial_tp_ratio=0.5,
            )

            res = self.engine.run_simulation(
                candles=candles,
                symbol=symbol,
                timeframe=timeframe,
                config=cfg,
                candles_4h=candles_4h,
                candles_15m=candles_15m,
            )

            m = res.metrics
            results.append(
                ParameterSweepResultItem(
                    score_threshold=thresh,
                    risk_percent=risk_p,
                    take_profit_1_rr=rr1,
                    take_profit_2_rr=rr2,
                    total_trades=m.total_trades,
                    win_rate=m.win_rate,
                    profit_factor=m.profit_factor,
                    total_pnl=m.total_pnl,
                    total_pnl_percent=m.total_pnl_percent,
                    max_drawdown_pct=m.max_drawdown_pct,
                    sharpe_ratio=m.sharpe_ratio,
                    expectancy_usd=m.expectancy_usd,
                )
            )

        # Rank optimal parameter sets
        valid_trades_results = [r for r in results if r.total_trades > 0]
        best_sharpe = (
            max(valid_trades_results, key=lambda x: x.sharpe_ratio)
            if valid_trades_results
            else (results[0] if results else None)
        )
        best_pnl = (
            max(valid_trades_results, key=lambda x: x.total_pnl)
            if valid_trades_results
            else (results[0] if results else None)
        )
        best_pf = (
            max(valid_trades_results, key=lambda x: x.profit_factor)
            if valid_trades_results
            else (results[0] if results else None)
        )

        return ParameterSweepResponse(
            symbol=symbol,
            timeframe=timeframe,
            tested_combinations=len(combinations),
            best_by_sharpe=best_sharpe,
            best_by_pnl=best_pnl,
            best_by_profit_factor=best_pf,
            results=results,
        )
