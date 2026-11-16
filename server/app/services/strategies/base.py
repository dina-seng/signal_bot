"""Abstract Strategy Interface and Result dataclass for the pluggable Strategy Engine."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

from app.schemas.indicators import IndicatorAnalysisResponse
from app.schemas.liquidity import AdvancedStructureAnalysisResponse
from app.schemas.signal import ScoreBreakdown, SignalDirection
from app.schemas.structure import MultiTimeframeStructureResponse


@dataclass
class StrategyResult:
    """Output of a single strategy's analysis pass.

    Each strategy produces one StrategyResult per evaluation cycle,
    containing its independent score, direction, and reasoning.
    """

    strategy_name: str
    direction: SignalDirection
    score: float  # 0.0 – 100.0
    reasons: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    score_breakdown: Optional[ScoreBreakdown] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None
    risk_reward: Optional[float] = None
    breach_point: Optional[float] = None


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies.

    Every concrete strategy must implement ``analyze()`` which receives
    pre-computed market data and returns a ``StrategyResult``.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable strategy identifier (e.g. 'SMC Confluence')."""
        ...

    @abstractmethod
    def analyze(
        self,
        symbol: str,
        timeframe: str,
        candles: Sequence[Any],
        indicators: IndicatorAnalysisResponse,
        structure: AdvancedStructureAnalysisResponse,
        mtf: Optional[MultiTimeframeStructureResponse] = None,
        candles_15m: Optional[Sequence[Any]] = None,
        **kwargs: Any,
    ) -> StrategyResult:
        """Run strategy-specific analysis and return a scored result.

        Args:
            symbol: Instrument identifier (e.g. ``"XAU/USD"``).
            timeframe: Primary timeframe being evaluated (e.g. ``"1h"``).
            candles: Primary timeframe closed candle sequence.
            indicators: Pre-computed indicator analysis for ``candles``.
            structure: Pre-computed SMC structure / liquidity analysis.
            mtf: Optional multi-timeframe alignment analysis.
            candles_15m: Optional 15-minute candle sequence for LTF confirmation.

        Returns:
            A ``StrategyResult`` with direction, score, reasons, and metadata.
        """
        ...
