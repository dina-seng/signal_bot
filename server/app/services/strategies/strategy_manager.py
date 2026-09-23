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
from app.services.strategies.base import BaseStrategy, StrategyResult


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
            from app.services.strategies.range_strategy import RangeStrategy
            from app.services.strategies.crt_strategy import CRTStrategy
            self.strategies = [
                SMCStrategy(),
                RangeStrategy(),
                CRTStrategy(),
            ]


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
    ) -> List[StrategyResult]:
        """Execute every registered strategy and return the list of results.

        Strategies that raise exceptions are logged and skipped so a single
        broken strategy cannot take down the entire signal pipeline.
        """
        results: List[StrategyResult] = []

        for strategy in self.strategies:
            try:
                result = strategy.analyze(
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=candles,
                    indicators=indicators,
                    structure=structure,
                    mtf=mtf,
                    candles_15m=candles_15m,
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
