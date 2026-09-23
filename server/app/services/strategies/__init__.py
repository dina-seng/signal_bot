"""Pluggable Strategy Engine package.

Provides the abstract ``BaseStrategy`` interface, concrete strategy
implementations (SMC), and the ``StrategyManager`` orchestrator.

Note: Concrete strategy class (SMCStrategy) is
imported lazily to avoid circular dependencies with the signals package.
Import it directly when needed:

    from app.services.strategies.smc_strategy import SMCStrategy
"""

from app.services.strategies.base import BaseStrategy, StrategyResult
from app.services.strategies.range_strategy import RangeStrategy
from app.services.strategies.crt_strategy import CRTStrategy
from app.services.strategies.strategy_manager import StrategyManager

__all__ = [
    "BaseStrategy",
    "CRTStrategy",
    "RangeStrategy",
    "StrategyManager",
    "StrategyResult",
]

