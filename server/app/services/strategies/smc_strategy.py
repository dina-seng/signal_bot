"""SMC (Smart Money Concepts) Strategy — migrated from ConfluenceEngine.

Wraps the existing 4-pillar evaluation pipeline (Structure, Liquidity/SMC,
Momentum Indicators, Price Action) and the LTF confirmation filter into the
pluggable BaseStrategy interface.

All original math is preserved exactly; the evaluators in ``evaluators.py``
are reused by composition.
"""

from typing import Any, Dict, List, Optional, Sequence

from app.core.config import settings
from app.core.logging import logger
from app.schemas.indicators import IndicatorAnalysisResponse
from app.schemas.liquidity import AdvancedStructureAnalysisResponse
from app.schemas.signal import ScoreBreakdown, SignalDirection
from app.schemas.structure import MultiTimeframeStructureResponse, TrendDirection
from app.services.signals.evaluators import (
    ConsensusFilter,
    LiquiditySMCConsensusEvaluator,
    PriceActionConsensusEvaluator,
    StructureConsensusEvaluator,
)
from app.services.structure.ltf_confirmation import LTFConfirmationEngine
from app.services.strategies.base import BaseStrategy, StrategyResult


class SMCStrategy(BaseStrategy):
    """Smart Money Concepts 3-pillar pure SMC confluence strategy.

    Scoring pillars (max 100 pts):
        - Structure & MTF Alignment: 35 pts
        - Liquidity & SMC (Sweeps, S/R, FVGs): 40 pts
        - Price Action Confirmation: 25 pts

    Directional conflict penalties and LTF confirmation are applied
    identically to the original ``ConfluenceEngine`` logic.
    """

    def __init__(self, min_score_threshold: Optional[float] = None) -> None:
        self._min_score_threshold = min_score_threshold or settings.MIN_SETUP_SCORE
        self.structure_evaluator = StructureConsensusEvaluator()
        self.liquidity_evaluator = LiquiditySMCConsensusEvaluator()
        self.price_action_evaluator = PriceActionConsensusEvaluator()
        self.consensus_filter = ConsensusFilter(min_score_threshold=self._min_score_threshold)
        self.ltf_confirmation_engine = LTFConfirmationEngine()

    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "Strategy A (SMC Sniper)"

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
        """Evaluate BUY and SELL setups using the pure 3-pillar SMC framework."""

        current_price = indicators.current_price
        active_fvgs = getattr(indicators, "active_fvgs", [])

        # ----- Multi-Pillar Evaluations: BUY -----
        buy_evals = {
            "structure": self.structure_evaluator.evaluate(SignalDirection.BUY, structure, mtf),
            "liquidity": self.liquidity_evaluator.evaluate(
                SignalDirection.BUY, structure, current_price, active_fvgs=active_fvgs
            ),
            "price_action": self.price_action_evaluator.evaluate(SignalDirection.BUY, indicators),
        }
        buy_score, buy_breakdown, buy_reasons, buy_fatal = self.consensus_filter.synthesize(
            buy_evals, SignalDirection.BUY
        )

        # ----- Multi-Pillar Evaluations: SELL -----
        sell_evals = {
            "structure": self.structure_evaluator.evaluate(SignalDirection.SELL, structure, mtf),
            "liquidity": self.liquidity_evaluator.evaluate(
                SignalDirection.SELL, structure, current_price, active_fvgs=active_fvgs
            ),
            "price_action": self.price_action_evaluator.evaluate(SignalDirection.SELL, indicators),
        }
        sell_score, sell_breakdown, sell_reasons, sell_fatal = self.consensus_filter.synthesize(
            sell_evals, SignalDirection.SELL
        )

        # ----- LTF Confirmation Filter (penalize if 15m doesn't confirm) -----
        final_buy_score = buy_score
        final_sell_score = sell_score

        if timeframe in ["1h", "4h"] and candles_15m:
            # BUY LTF check
            is_buy_confirmed, buy_ltf_reason = self.ltf_confirmation_engine.check_ltf_confirmation(
                primary_timeframe=timeframe,
                primary_direction=TrendDirection.BULLISH,
                primary_candles=candles,
                ltf_candles=candles_15m,
                max_bars_ago=5,
            )
            if not is_buy_confirmed:
                final_buy_score = buy_score * 0.3  # 70% penalty
                buy_reasons.append(f"⚠️ LTF Confirmation Missing (BUY): {buy_ltf_reason}")
                logger.info(f"LTF confirmation failed for BUY {symbol} [{timeframe}]: {buy_ltf_reason}")

            # SELL LTF check
            is_sell_confirmed, sell_ltf_reason = self.ltf_confirmation_engine.check_ltf_confirmation(
                primary_timeframe=timeframe,
                primary_direction=TrendDirection.BEARISH,
                primary_candles=candles,
                ltf_candles=candles_15m,
                max_bars_ago=5,
            )
            if not is_sell_confirmed:
                final_sell_score = sell_score * 0.3  # 70% penalty
                sell_reasons.append(f"⚠️ LTF Confirmation Missing (SELL): {sell_ltf_reason}")
                logger.info(f"LTF confirmation failed for SELL {symbol} [{timeframe}]: {sell_ltf_reason}")

        # ----- Direction Selection -----
        if final_buy_score >= final_sell_score and final_buy_score >= self._min_score_threshold and not buy_fatal:
            direction = SignalDirection.BUY
            total_score = final_buy_score
            breakdown = buy_breakdown
            reasons = buy_reasons
        elif final_sell_score > final_buy_score and final_sell_score >= self._min_score_threshold and not sell_fatal:
            direction = SignalDirection.SELL
            total_score = final_sell_score
            breakdown = sell_breakdown
            reasons = sell_reasons
        else:
            direction = SignalDirection.WAIT
            total_score = max(final_buy_score, final_sell_score)
            breakdown = buy_breakdown if final_buy_score >= final_sell_score else sell_breakdown

            conflict_note = ""
            if buy_fatal or sell_fatal:
                conflict_note = "Directional contradiction between pillars detected. "

            reasons = [
                f"MARKET BIAS: NEUTRAL / WAIT ({conflict_note}Score: {total_score:.1f}/100, Min required: {self._min_score_threshold:.1f}).",
                f"Market State: {structure.market_state}",
                f"Technical Bias: {indicators.confluence_bias} (Score: {indicators.confluence_score:+.0f})",
            ]
            # Include best catalysts as context
            best_catalysts = buy_reasons if final_buy_score >= final_sell_score else sell_reasons
            for c in best_catalysts[:3]:
                if not c.startswith("MARKET BIAS"):
                    reasons.append(f"Observation: {c}")

        return StrategyResult(
            strategy_name=self.name,
            direction=direction,
            score=total_score,
            reasons=reasons,
            metadata={
                "buy_score": final_buy_score,
                "sell_score": final_sell_score,
                "buy_fatal": buy_fatal,
                "sell_fatal": sell_fatal,
            },
            score_breakdown=breakdown,
        )
