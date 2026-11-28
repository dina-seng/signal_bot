"""Strategy Manager — orchestrates all registered trading strategies.

The manager holds a list of ``BaseStrategy`` instances and provides a
single entry-point (``run_all_strategies``) that fans out analysis across
every strategy and collects the results.
"""

from typing import Any, List, Optional, Sequence

from app.core.logging import logger
from app.schemas.indicators import IndicatorAnalysisResponse
from app.schemas.liquidity import AdvancedStructureAnalysisResponse
from app.schemas.structure import MultiTimeframeStructureResponse
from app.services.signals.crypto_risk_engine import BTC_SYMBOL
from app.services.strategies.base import BaseStrategy, StrategyResult
from app.services.strategies.btc_momentum_strategy import BTCMomentumStrategy


class StrategyManager:
    """Orchestrator that runs every registered strategy and collects results.

    Usage::

        manager = StrategyManager()
        results = manager.run_all_strategies(
            symbol="XAU/USD",
            timeframe="1h",
            candles=c_prim,
            indicators=indicator_analysis,
            structure=structure_analysis,
        )
        for r in results:
            print(f"{r.strategy_name}: {r.direction.value} @ {r.score:.1f}")
    """

    def __init__(
        self,
        strategies: Optional[List[BaseStrategy]] = None,
    ) -> None:
        if strategies is not None:
            self.strategies: List[BaseStrategy] = strategies
        else:
            # Lazy imports to avoid circular dependency:
            # strategy_manager -> smc_strategy -> signals.evaluators -> signals.__init__ -> confluence_engine -> strategy_manager
            from app.services.strategies.smc_strategy import SMCStrategy
            self.strategies = [
                SMCStrategy(),
                # Validated config from the BTC momentum sweep: min score 85,
                # ADX >= 25, min volume 1.0. The earlier 65/25/1.0 instance was
                # never the configuration that was proven profitable.
                BTCMomentumStrategy(
                    min_score_threshold=85.0,
                    adx_threshold=25.0,
                    min_volume=1.0,
                ),
            ]


    def strategies_for(self, symbol: str) -> List[BaseStrategy]:
        """Route each instrument to its own strategy; never rely on self-gates.

        BTC/USD runs the momentum strategy only. Every other symbol (XAU/USD)
        keeps the SMC pipeline unchanged. Extra strategies registered at runtime
        continue to run for both symbols.
        """
        is_btc = str(symbol or "").strip().upper() == BTC_SYMBOL
        routed: List[BaseStrategy] = []
        for strategy in self.strategies:
            is_momentum = isinstance(strategy, BTCMomentumStrategy)
            if is_btc and not is_momentum:
                continue
            if not is_btc and is_momentum:
                continue
            routed.append(strategy)
        return routed

    def register(self, strategy: BaseStrategy) -> None:
        """Add a new strategy to the pipeline at runtime."""
        self.strategies.append(strategy)
        logger.info(f"Registered strategy: {strategy.name}")

    def run_all_strategies(
        self,
        symbol: str,
        timeframe: str,
        candles: Sequence[Any],
        indicators: IndicatorAnalysisResponse,
        structure: AdvancedStructureAnalysisResponse,
        mtf: Optional[MultiTimeframeStructureResponse] = None,
        candles_15m: Optional[Sequence[Any]] = None,
        htf_trend: Optional[str] = None,
        **kwargs: Any,
    ) -> List[StrategyResult]:
        """Execute every registered strategy and return the list of results.

        Strategies that raise exceptions are logged and skipped so a single
        broken strategy cannot take down the entire signal pipeline.
        """
        results: List[StrategyResult] = []

        # Determine HTF trend context if not passed
        current_htf_trend = htf_trend
        if current_htf_trend is None:
            if mtf is not None and hasattr(mtf, "timeframes") and "1h" in mtf.timeframes:
                t = mtf.timeframes["1h"].trend
                current_htf_trend = t.value if hasattr(t, "value") else str(t).upper()
            elif structure is not None and hasattr(structure, "trend"):
                t = structure.trend
                current_htf_trend = t.value if hasattr(t, "value") else str(t).upper()
            elif mtf is not None and hasattr(mtf, "primary_trend"):
                t = mtf.primary_trend
                current_htf_trend = t.value if hasattr(t, "value") else str(t).upper()
            else:
                current_htf_trend = "RANGING"

        for strategy in self.strategies_for(symbol):
            try:
                call_kwargs = dict(kwargs)
                call_kwargs["htf_trend"] = current_htf_trend

                result = strategy.analyze(
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=candles,
                    indicators=indicators,
                    structure=structure,
                    mtf=mtf,
                    candles_15m=candles_15m,
                    **call_kwargs,
                )
                results.append(result)
                logger.debug(
                    f"Strategy '{strategy.name}' [{symbol}][{timeframe}]: "
                    f"{result.direction.value} (Score: {result.score:.1f})"
                )
            except Exception as exc:
                logger.error(
                    f"Strategy '{strategy.name}' failed for {symbol} [{timeframe}]: {exc}",
                    exc_info=True,
                )

        return results
