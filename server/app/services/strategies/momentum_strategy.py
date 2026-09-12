"""Momentum Strategy — placeholder for EMA crossover / RSI divergence signals.

This is a scaffold that returns a basic mock ``StrategyResult`` so the
multi-strategy pipeline can be tested end-to-end.  The actual momentum
math will be filled in later.
"""

from typing import Any, List, Optional, Sequence

from app.core.logging import logger
from app.schemas.indicators import (
    DivergenceType,
    IndicatorAnalysisResponse,
)
from app.schemas.liquidity import AdvancedStructureAnalysisResponse
from app.schemas.signal import ScoreBreakdown, SignalDirection
from app.schemas.structure import MultiTimeframeStructureResponse
from app.services.strategies.base import BaseStrategy, StrategyResult


class MomentumStrategy(BaseStrategy):
    """Momentum-based strategy using EMA crossovers and RSI divergences.

    Currently a **placeholder** — it inspects readily available indicator
    data to produce a lightweight score.  The scoring weights here are
    intentionally conservative to avoid generating false signals until the
    full momentum model is implemented.
    """

    @property
    def name(self) -> str:
        return "Momentum"

    def analyze(
        self,
        symbol: str,
        timeframe: str,
        candles: Sequence[Any],
        indicators: IndicatorAnalysisResponse,
        structure: AdvancedStructureAnalysisResponse,
        mtf: Optional[MultiTimeframeStructureResponse] = None,
        candles_15m: Optional[Sequence[Any]] = None,
    ) -> StrategyResult:
        """Evaluate momentum signals from EMA crossovers and RSI divergences."""

        score = 0.0
        reasons: List[str] = []
        direction = SignalDirection.WAIT

        # ------------------------------------------------------------------
        # 1. EMA Golden / Death Cross (max +40 pts)
        # ------------------------------------------------------------------
        if indicators.ema.golden_cross:
            score += 40.0
            reasons.append("EMA Golden Cross detected (50 EMA crossed above 200 EMA)")
            direction = SignalDirection.BUY
        elif indicators.ema.death_cross:
            score += 40.0
            reasons.append("EMA Death Cross detected (50 EMA crossed below 200 EMA)")
            direction = SignalDirection.SELL

        # ------------------------------------------------------------------
        # 2. EMA Trend Stack alignment (max +20 pts)
        # ------------------------------------------------------------------
        if direction == SignalDirection.BUY and indicators.ema.ema_trend == "BULLISH_STACK":
            score += 20.0
            reasons.append("Bullish EMA Stack confirms momentum direction")
        elif direction == SignalDirection.SELL and indicators.ema.ema_trend == "BEARISH_STACK":
            score += 20.0
            reasons.append("Bearish EMA Stack confirms momentum direction")

        # ------------------------------------------------------------------
        # 3. RSI Divergence confirmation (max +25 pts)
        # ------------------------------------------------------------------
        bull_divs = [
            d for d in indicators.divergences
            if d.divergence_type in (DivergenceType.REGULAR_BULLISH, DivergenceType.HIDDEN_BULLISH)
        ]
        bear_divs = [
            d for d in indicators.divergences
            if d.divergence_type in (DivergenceType.REGULAR_BEARISH, DivergenceType.HIDDEN_BEARISH)
        ]

        if direction == SignalDirection.BUY and bull_divs:
            score += 25.0
            reasons.append(f"RSI Bullish Divergence ({bull_divs[-1].divergence_type.value})")
        elif direction == SignalDirection.SELL and bear_divs:
            score += 25.0
            reasons.append(f"RSI Bearish Divergence ({bear_divs[-1].divergence_type.value})")

        # ------------------------------------------------------------------
        # 4. RSI extreme zone bonus (max +15 pts)
        # ------------------------------------------------------------------
        if direction == SignalDirection.BUY and indicators.rsi.condition in ("OVERSOLD", "BULLISH_ZONE"):
            score += 15.0
            reasons.append(f"RSI in favorable zone for BUY ({indicators.rsi.condition})")
        elif direction == SignalDirection.SELL and indicators.rsi.condition in ("OVERBOUGHT", "BEARISH_ZONE"):
            score += 15.0
            reasons.append(f"RSI in favorable zone for SELL ({indicators.rsi.condition})")

        # Cap at 100
        score = min(100.0, score)

        # If no crossover was detected, remain WAIT
        if direction == SignalDirection.WAIT:
            reasons.append("No EMA crossover detected — momentum strategy inactive")

        logger.debug(
            f"MomentumStrategy [{symbol}][{timeframe}]: "
            f"direction={direction.value}, score={score:.1f}"
        )

        return StrategyResult(
            strategy_name=self.name,
            direction=direction,
            score=score,
            reasons=reasons,
            metadata={
                "golden_cross": indicators.ema.golden_cross,
                "death_cross": indicators.ema.death_cross,
                "ema_trend": indicators.ema.ema_trend,
                "rsi_condition": indicators.rsi.condition,
            },
            score_breakdown=None,
        )

