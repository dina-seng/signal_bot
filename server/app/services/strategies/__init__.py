"""Pluggable Strategy Engine package.

Provides the abstract ``BaseStrategy`` interface, concrete strategy
implementations (SMC, Momentum), and the ``StrategyManager`` orchestrator.

Note: Concrete strategy classes (SMCStrategy, MomentumStrategy) are
imported lazily to avoid circular dependencies with the signals package.
Import them directly when needed:

    from app.services.strategies.smc_strategy import SMCStrategy
    from app.services.strategies.momentum_strategy import MomentumStrategy
"""

from app.services.strategies.base import BaseStrategy, StrategyResult
from app.services.strategies.strategy_manager import StrategyManager

__all__ = [
    "BaseStrategy",
    "StrategyManager",
    "StrategyResult",
]
