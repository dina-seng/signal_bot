"""Momentum Strategy — Strategy B (Momentum Catcher).

Evaluates momentum signals from EMA alignment, RSI divergences, and ATR expansion.
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
    """Momentum-based strategy using EMA crossovers and RSI divergences."""

    @property
    def name(self) -> str:
        return "Strategy B (Momentum Catcher)"

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
        """Evaluate momentum signals from EMA alignment, RSI divergences, and ATR expansion."""

        buy_score = 0.0
        buy_reasons: List[str] = []
        sell_score = 0.0
        sell_reasons: List[str] = []

        # RSI Divergences
        bull_divs = [
            d for d in indicators.divergences
            if d.divergence_type in (DivergenceType.REGULAR_BULLISH, DivergenceType.HIDDEN_BULLISH)
        ]
        bear_divs = [
            d for d in indicators.divergences
            if d.divergence_type in (DivergenceType.REGULAR_BEARISH, DivergenceType.HIDDEN_BEARISH)
        ]

        # ATR Volatility State
        atr_is_high = getattr(indicators.atr, "volatility_state", "") == "HIGH"
        atr_pips = getattr(indicators.atr, "atr_pips", 0.0) or 0.0

        # ------------------------------------------------------------------
        # 1. Evaluate BUY Momentum
        # ------------------------------------------------------------------
        if indicators.ema.golden_cross:
            buy_score += 40.0
            buy_reasons.append("EMA Golden Cross (50 EMA crossed above 200 EMA)")
        elif indicators.ema.ema_trend == "BULLISH_STACK":
            buy_score += 25.0
            buy_reasons.append("Bullish EMA Stack (20 > 50 > 200)")
        elif indicators.ema.price_vs_ema200 == "ABOVE":
            buy_score += 15.0
            buy_reasons.append("Price Holding Above 200 EMA")

        if bull_divs:
            buy_score += 25.0
            buy_reasons.append(f"RSI Bullish Divergence ({bull_divs[-1].divergence_type.value})")

        if indicators.rsi.condition in ("OVERSOLD", "BULLISH_ZONE"):
            buy_score += 15.0
            buy_reasons.append(f"RSI in favorable zone for BUY ({indicators.rsi.condition})")

        if atr_is_high and (indicators.ema.golden_cross or indicators.ema.ema_trend == "BULLISH_STACK"):
            buy_score += 10.0
            buy_reasons.append(f"ATR Volatility Expansion ({atr_pips:.1f} pips)")

        # ------------------------------------------------------------------
        # 2. Evaluate SELL Momentum
        # ------------------------------------------------------------------
        if indicators.ema.death_cross:
            sell_score += 40.0
            sell_reasons.append("EMA Death Cross (50 EMA crossed below 200 EMA)")
        elif indicators.ema.ema_trend == "BEARISH_STACK":
            sell_score += 25.0
            sell_reasons.append("Bearish EMA Stack (20 < 50 < 200)")
        elif indicators.ema.price_vs_ema200 == "BELOW":
            sell_score += 15.0
            sell_reasons.append("Price Holding Below 200 EMA")

        if bear_divs:
            sell_score += 25.0
            sell_reasons.append(f"RSI Bearish Divergence ({bear_divs[-1].divergence_type.value})")

        if indicators.rsi.condition in ("OVERBOUGHT", "BEARISH_ZONE"):
            sell_score += 15.0
            sell_reasons.append(f"RSI in favorable zone for SELL ({indicators.rsi.condition})")

        if atr_is_high and (indicators.ema.death_cross or indicators.ema.ema_trend == "BEARISH_STACK"):
            sell_score += 10.0
            sell_reasons.append(f"ATR Volatility Expansion ({atr_pips:.1f} pips)")

        # Cap scores at 100
        buy_score = min(100.0, buy_score)
        sell_score = min(100.0, sell_score)

        # ------------------------------------------------------------------
        # 3. Direction Selection (Threshold: 70.0 for actionable momentum)
        # ------------------------------------------------------------------
        min_threshold = 70.0
        final_score = 0.0
        final_reasons: List[str] = []
        direction = SignalDirection.WAIT

        if buy_score >= sell_score and buy_score >= min_threshold:
            direction = SignalDirection.BUY
            final_score = buy_score
            final_reasons = buy_reasons
        elif sell_score > buy_score and sell_score >= min_threshold:
            direction = SignalDirection.SELL
            final_score = sell_score
            final_reasons = sell_reasons
        else:
            direction = SignalDirection.WAIT
            final_score = max(buy_score, sell_score)
            best_reasons = buy_reasons if buy_score >= sell_score else sell_reasons
            final_reasons = [
                f"Momentum Neutral / Below Threshold ({final_score:.1f}/100, Min required: {min_threshold:.1f})"
            ] + best_reasons[:2]

        # ------------------------------------------------------------------
        # 4. Build ScoreBreakdown (Distributed to satisfy Pydantic limits)
        # ------------------------------------------------------------------
        # We distribute the final_score across the pillars so no single pillar 
        # exceeds its max limit (Structure=30, Liquidity=25, Indicators=25, PA=20)
        final_score_capped = min(100.0, final_score)
        remaining = final_score_capped
        
        struct_score = min(30.0, remaining)
        remaining -= struct_score
        
        liq_score = min(25.0, remaining)
        remaining -= liq_score
        
        ind_score = min(25.0, remaining)
        remaining -= ind_score
        
        pa_score = min(20.0, remaining)

        capped_indicators_score = min(25.0, final_score)


        final_breakdown = ScoreBreakdown(
            structure_score=round(struct_score, 1),
            liquidity_score=round(liq_score, 1),
            indicators_score=capped_indicators_score,
            price_action_score=round(pa_score, 1),
            total_score=round(final_score_capped, 1),
            is_qualified=final_score_capped >= min_threshold
        )

        logger.debug(
            f"MomentumStrategy [{symbol}][{timeframe}]: "
            f"direction={direction.value}, score={final_score:.1f}"
        )

        return StrategyResult(
            strategy_name=self.name,
            direction=direction,
            score=final_score,
            reasons=final_reasons,
            metadata={
                "golden_cross": indicators.ema.golden_cross,
                "death_cross": indicators.ema.death_cross,
                "ema_trend": indicators.ema.ema_trend,
                "rsi_condition": indicators.rsi.condition,
                "buy_score": buy_score,
                "sell_score": sell_score,
                "volatility_state": getattr(indicators.atr, "volatility_state", None),
            },
            score_breakdown=final_breakdown,
        )