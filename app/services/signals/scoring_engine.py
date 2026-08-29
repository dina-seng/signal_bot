"""Deterministic Multi-Pillar Signal Scoring Engine (0-100 Points)."""

from typing import List, Optional, Tuple
from app.core.config import settings
from app.schemas.indicators import IndicatorAnalysisResponse
from app.schemas.liquidity import AdvancedStructureAnalysisResponse
from app.schemas.news import NewsBlackoutCheckResponse
from app.schemas.signal import ScoreBreakdown, SignalDirection
from app.schemas.structure import MultiTimeframeStructureResponse
from app.services.signals.evaluators import (
    ConsensusFilter,
    LiquiditySMCConsensusEvaluator,
    MomentumIndicatorConsensusEvaluator,
    PriceActionConsensusEvaluator,
    StructureConsensusEvaluator,
)


class SignalScoringEngine:
    """Scores trading opportunities deterministically across Market Structure, Liquidity, Indicators, and Price Action."""

    def __init__(self, min_score_threshold: Optional[float] = None):
        self.min_score_threshold = min_score_threshold or settings.MIN_SETUP_SCORE
        self.structure_evaluator = StructureConsensusEvaluator()
        self.liquidity_evaluator = LiquiditySMCConsensusEvaluator()
        self.indicator_evaluator = MomentumIndicatorConsensusEvaluator()
        self.price_action_evaluator = PriceActionConsensusEvaluator()
        self.consensus_filter = ConsensusFilter(min_score_threshold=self.min_score_threshold)

    def evaluate_setup(
        self,
        symbol: str,
        timeframe: str,
        structure: AdvancedStructureAnalysisResponse,
        indicators: IndicatorAnalysisResponse,
        mtf: Optional[MultiTimeframeStructureResponse] = None,
        news_check: Optional[NewsBlackoutCheckResponse] = None,
    ) -> Tuple[SignalDirection, float, ScoreBreakdown, List[str]]:
        """Evaluate market data and compute composite score (0 to 100) for BUY and SELL setups.

        Returns:
            Tuple of (SignalDirection, total_score, ScoreBreakdown, list_of_reasons)
        """
        # If trading is blocked by news blackout, immediately return WAIT
        if news_check and news_check.is_blackout:
            reasons = [
                f"NEWS BLACKOUT ACTIVE: {news_check.reason}",
                "Trade signals temporarily suspended to prevent high-volatility slippage.",
            ]
            breakdown = ScoreBreakdown(
                structure_score=0.0,
                liquidity_score=0.0,
                indicators_score=0.0,
                price_action_score=0.0,
                total_score=0.0,
                is_qualified=False,
            )
            return SignalDirection.WAIT, 0.0, breakdown, reasons

        # Score BUY and SELL candidate setups
        buy_score, buy_breakdown, buy_reasons = self._score_direction(
            direction=SignalDirection.BUY,
            structure=structure,
            indicators=indicators,
            mtf=mtf,
        )

        sell_score, sell_breakdown, sell_reasons = self._score_direction(
            direction=SignalDirection.SELL,
            structure=structure,
            indicators=indicators,
            mtf=mtf,
        )

        if buy_score >= sell_score and buy_score >= self.min_score_threshold and buy_breakdown.is_qualified:
            return SignalDirection.BUY, buy_score, buy_breakdown, buy_reasons
        elif sell_score > buy_score and sell_score >= self.min_score_threshold and sell_breakdown.is_qualified:
            return SignalDirection.SELL, sell_score, sell_breakdown, sell_reasons
        else:
            best_score = max(buy_score, sell_score)
            best_breakdown = buy_breakdown if buy_score >= sell_score else sell_breakdown
            reasons = [
                f"INSUFFICIENT CONFLUENCE: Score {best_score:.1f}/100 is below minimum threshold ({self.min_score_threshold:.1f}).",
                f"Market State: {structure.market_state}",
                f"Technical Bias: {indicators.confluence_bias} (Score: {indicators.confluence_score:+.0f})",
            ]
            return SignalDirection.WAIT, best_score, best_breakdown, reasons

    def _score_direction(
        self,
        direction: SignalDirection,
        structure: AdvancedStructureAnalysisResponse,
        indicators: IndicatorAnalysisResponse,
        mtf: Optional[MultiTimeframeStructureResponse] = None,
    ) -> Tuple[float, ScoreBreakdown, List[str]]:
        """Score a specific direction (BUY or SELL) from 0 to 100."""
        evals = {
            "structure": self.structure_evaluator.evaluate(direction, structure, mtf),
            "liquidity": self.liquidity_evaluator.evaluate(direction, structure, indicators.current_price),
            "indicators": self.indicator_evaluator.evaluate(direction, indicators),
            "price_action": self.price_action_evaluator.evaluate(direction, indicators),
        }

        final_score, breakdown, catalysts, _ = self.consensus_filter.synthesize(evals, direction)
        return final_score, breakdown, catalysts

