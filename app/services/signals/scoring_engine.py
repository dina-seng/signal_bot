"""Deterministic Multi-Pillar Signal Scoring Engine (0-100 Points)."""

from typing import List, Optional, Tuple
from app.core.config import settings
from app.schemas.indicators import (
    DivergenceType,
    FVGType,
    IndicatorAnalysisResponse,
    PatternType,
)
from app.schemas.liquidity import (
    AdvancedStructureAnalysisResponse,
    BOSCHOCHType,
    LiquidityEventType,
    ZoneType,
)
from app.schemas.news import NewsBlackoutCheckResponse
from app.schemas.signal import ScoreBreakdown, SignalDirection
from app.schemas.structure import (
    MultiTimeframeAlignment,
    MultiTimeframeStructureResponse,
    TrendDirection,
)


class SignalScoringEngine:
    """Scores trading opportunities deterministically across Market Structure, Liquidity, Indicators, and Price Action."""

    def __init__(self, min_score_threshold: Optional[float] = None):
        self.min_score_threshold = min_score_threshold or settings.MIN_SETUP_SCORE

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

        if buy_score >= sell_score and buy_score >= self.min_score_threshold:
            return SignalDirection.BUY, buy_score, buy_breakdown, buy_reasons
        elif sell_score > buy_score and sell_score >= self.min_score_threshold:
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
        reasons: List[str] = []

        # -------------------------------------------------------------
        # Pillar 1: Market Structure & MTF Alignment (Max 30 pts)
        # -------------------------------------------------------------
        struct_pts = 0.0

        # Base Trend (Max 10 pts)
        if direction == SignalDirection.BUY:
            if structure.trend == TrendDirection.BULLISH:
                struct_pts += 10.0
                reasons.append(f"Bullish Market Structure ({structure.trend_strength * 100:.0f}% strength)")
            elif structure.trend == TrendDirection.RANGING:
                struct_pts += 4.0
        else:
            if structure.trend == TrendDirection.BEARISH:
                struct_pts += 10.0
                reasons.append(f"Bearish Market Structure ({structure.trend_strength * 100:.0f}% strength)")
            elif structure.trend == TrendDirection.RANGING:
                struct_pts += 4.0

        # MTF Alignment (Max 10 pts)
        if mtf:
            if direction == SignalDirection.BUY and mtf.alignment == MultiTimeframeAlignment.BULLISH_ALIGNED:
                struct_pts += 10.0
                reasons.append("Multi-Timeframe Confluence (4h, 1h, 15m Bullish Aligned)")
            elif direction == SignalDirection.SELL and mtf.alignment == MultiTimeframeAlignment.BEARISH_ALIGNED:
                struct_pts += 10.0
                reasons.append("Multi-Timeframe Confluence (4h, 1h, 15m Bearish Aligned)")
            elif mtf.alignment in (
                MultiTimeframeAlignment.HTF_BULLISH_PULLBACK,
                MultiTimeframeAlignment.HTF_BEARISH_PULLBACK,
            ):
                struct_pts += 5.0


        # Breakout / Reversal Shift (BOS / CHOCH) (Max 10 pts)
        if direction == SignalDirection.BUY:
            if structure.latest_bos and structure.latest_bos.event_type == BOSCHOCHType.BULLISH_BOS:
                struct_pts += 10.0
                reasons.append("Confirmed Bullish Break of Structure (BOS continuation)")
            elif structure.latest_choch and structure.latest_choch.event_type == BOSCHOCHType.BULLISH_CHOCH:
                struct_pts += 8.0
                reasons.append("Confirmed Bullish Change of Character (CHOCH/MSS reversal)")
        else:
            if structure.latest_bos and structure.latest_bos.event_type == BOSCHOCHType.BEARISH_BOS:
                struct_pts += 10.0
                reasons.append("Confirmed Bearish Break of Structure (BOS continuation)")
            elif structure.latest_choch and structure.latest_choch.event_type == BOSCHOCHType.BEARISH_CHOCH:
                struct_pts += 8.0
                reasons.append("Confirmed Bearish Change of Character (CHOCH/MSS reversal)")

        struct_pts = min(30.0, struct_pts)

        # -------------------------------------------------------------
        # Pillar 2: Institutional Liquidity & S/R Zones (Max 25 pts)
        # -------------------------------------------------------------
        liq_pts = 0.0

        # Liquidity Sweeps (Max 15 pts)
        if direction == SignalDirection.BUY:
            if structure.latest_sweep and structure.latest_sweep.sweep_type == LiquidityEventType.SELL_SIDE_SWEEP:
                liq_pts += 15.0
                reasons.append(f"Institutional Sell-Side Liquidity Sweep ({structure.latest_sweep.pips_swept:.1f} pips stop hunt)")
        else:
            if structure.latest_sweep and structure.latest_sweep.sweep_type == LiquidityEventType.BUY_SIDE_SWEEP:
                liq_pts += 15.0
                reasons.append(f"Institutional Buy-Side Liquidity Sweep ({structure.latest_sweep.pips_swept:.1f} pips stop hunt)")

        # Support / Resistance Zones (Max 10 pts)
        curr_price = indicators.current_price
        if direction == SignalDirection.BUY:
            support_zones = [z for z in structure.sr_zones if z.zone_type == ZoneType.SUPPORT and z.is_fresh]
            if support_zones and any(abs(curr_price - z.center_price) <= (z.price_high - z.price_low) * 2.0 for z in support_zones):
                liq_pts += 10.0
                reasons.append("Entry at Key Institutional Demand / Support Zone")
            elif any(p.pool_type == LiquidityEventType.EQUAL_LOWS for p in structure.liquidity_pools):
                liq_pts += 5.0
        else:
            resistance_zones = [z for z in structure.sr_zones if z.zone_type == ZoneType.RESISTANCE and z.is_fresh]
            if resistance_zones and any(abs(curr_price - z.center_price) <= (z.price_high - z.price_low) * 2.0 for z in resistance_zones):
                liq_pts += 10.0
                reasons.append("Entry at Key Institutional Supply / Resistance Zone")
            elif any(p.pool_type == LiquidityEventType.EQUAL_HIGHS for p in structure.liquidity_pools):
                liq_pts += 5.0

        liq_pts = min(25.0, liq_pts)

        # -------------------------------------------------------------
        # Pillar 3: Technical Indicators & Confluence (Max 25 pts)
        # -------------------------------------------------------------
        ind_pts = 0.0

        # EMA Trend Stack (Max 10 pts)
        if direction == SignalDirection.BUY:
            if indicators.ema.ema_trend == "BULLISH_STACK":
                ind_pts += 10.0
                reasons.append("EMA Bullish Stack (Price > 20 > 50 > 200)")
            elif indicators.ema.price_vs_ema200 == "ABOVE":
                ind_pts += 6.0
        else:
            if indicators.ema.ema_trend == "BEARISH_STACK":
                ind_pts += 10.0
                reasons.append("EMA Bearish Stack (Price < 20 < 50 < 200)")
            elif indicators.ema.price_vs_ema200 == "BELOW":
                ind_pts += 6.0

        # RSI Momentum & Divergence (Max 10 pts)
        if direction == SignalDirection.BUY:
            bull_divs = [
                d for d in indicators.divergences
                if d.divergence_type in (DivergenceType.REGULAR_BULLISH, DivergenceType.HIDDEN_BULLISH)
            ]
            if bull_divs:
                ind_pts += 10.0
                reasons.append(f"RSI Bullish Divergence ({bull_divs[-1].divergence_type.value})")
            elif indicators.rsi.condition in ("BULLISH_ZONE", "OVERSOLD"):
                ind_pts += 5.0
        else:
            bear_divs = [
                d for d in indicators.divergences
                if d.divergence_type in (DivergenceType.REGULAR_BEARISH, DivergenceType.HIDDEN_BEARISH)
            ]
            if bear_divs:
                ind_pts += 10.0
                reasons.append(f"RSI Bearish Divergence ({bear_divs[-1].divergence_type.value})")
            elif indicators.rsi.condition in ("BEARISH_ZONE", "OVERBOUGHT"):
                ind_pts += 5.0

        # Fair Value Gaps (Max 5 pts)
        if direction == SignalDirection.BUY:
            bull_fvgs = [f for f in indicators.active_fvgs if f.fvg_type == FVGType.BULLISH_FVG]
            if bull_fvgs:
                ind_pts += 5.0
                reasons.append(f"Active Bullish Fair Value Gap ({bull_fvgs[-1].gap_pips:.1f} pips)")
        else:
            bear_fvgs = [f for f in indicators.active_fvgs if f.fvg_type == FVGType.BEARISH_FVG]
            if bear_fvgs:
                ind_pts += 5.0
                reasons.append(f"Active Bearish Fair Value Gap ({bear_fvgs[-1].gap_pips:.1f} pips)")

        ind_pts = min(25.0, ind_pts)

        # -------------------------------------------------------------
        # Pillar 4: Price Action Confirmation (Max 20 pts)
        # -------------------------------------------------------------
        pa_pts = 0.0

        if direction == SignalDirection.BUY:
            bull_patterns = [
                p for p in indicators.recent_patterns
                if p.pattern_type in (PatternType.BULLISH_PIN_BAR, PatternType.BULLISH_ENGULFING)
            ]
            if bull_patterns:
                pa_pts += 20.0 * bull_patterns[-1].confidence
                reasons.append(f"Candlestick Trigger: {bull_patterns[-1].pattern_type.value}")
            elif any(p.pattern_type == PatternType.INSIDE_BAR for p in indicators.recent_patterns):
                pa_pts += 10.0
        else:
            bear_patterns = [
                p for p in indicators.recent_patterns
                if p.pattern_type in (PatternType.BEARISH_PIN_BAR, PatternType.BEARISH_ENGULFING)
            ]
            if bear_patterns:
                pa_pts += 20.0 * bear_patterns[-1].confidence
                reasons.append(f"Candlestick Trigger: {bear_patterns[-1].pattern_type.value}")
            elif any(p.pattern_type == PatternType.INSIDE_BAR for p in indicators.recent_patterns):
                pa_pts += 10.0

        pa_pts = min(20.0, pa_pts)

        # Total Composite Score
        total = round(struct_pts + liq_pts + ind_pts + pa_pts, 1)
        is_qual = total >= self.min_score_threshold

        breakdown = ScoreBreakdown(
            structure_score=round(struct_pts, 1),
            liquidity_score=round(liq_pts, 1),
            indicators_score=round(ind_pts, 1),
            price_action_score=round(pa_pts, 1),
            total_score=total,
            is_qualified=is_qual,
        )

        return total, breakdown, reasons
