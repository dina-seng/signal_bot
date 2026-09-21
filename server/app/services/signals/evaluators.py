"""Modular Sub-Strategy Consensus Evaluators and Agreement/Conflict Filter."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from app.core.config import settings
from app.core.logging import logger
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
from app.schemas.signal import ScoreBreakdown, SignalDirection
from app.schemas.structure import (
    MultiTimeframeAlignment,
    MultiTimeframeStructureResponse,
    TrendDirection,
)


@dataclass
class PillarEvaluation:
    """Evaluation result for a single analytical pillar."""
    pillar_name: str
    direction: SignalDirection  # BUY, SELL, or WAIT/NEUTRAL
    score: float  # Earned points (e.g. 25.0)
    max_score: float  # Maximum possible points (e.g. 30.0)
    weight_percent: float  # Relative weight (e.g. 30.0)
    confidence: float  # Normalized confidence [0.0 - 1.0]
    catalysts: List[str] = field(default_factory=list)
    opposing_signals: List[str] = field(default_factory=list)


# =====================================================================
# Pillar 1: Market Structure & MTF Alignment (30% Weight / Max 30.0 pts)
# =====================================================================
class StructureConsensusEvaluator:
    """Evaluates Higher-Timeframe trend alignment, Swing Points, BOS, and CHOCH/MSS."""

    MAX_POINTS: float = 30.0
    WEIGHT: float = 30.0

    def evaluate(
        self,
        direction: SignalDirection,
        structure: AdvancedStructureAnalysisResponse,
        mtf: Optional[MultiTimeframeStructureResponse] = None,
    ) -> PillarEvaluation:
        """Score structure alignment and breakout signals for candidate direction."""
        score = 0.0
        catalysts: List[str] = []
        opposing: List[str] = []

        # 1. Base Structure Trend & Strength (Max 10.0 pts)
        if direction == SignalDirection.BUY:
            if structure.trend == TrendDirection.BULLISH:
                trend_pts = 10.0 * max(0.5, structure.trend_strength)
                score += trend_pts
                catalysts.append(f"Bullish Market Structure ({structure.trend_strength * 100:.0f}% strength)")
            elif structure.trend == TrendDirection.RANGING:
                score += 4.0
            elif structure.trend == TrendDirection.BEARISH:
                opposing.append(f"Opposing Bearish Trend ({structure.trend_strength * 100:.0f}% strength)")
        elif direction == SignalDirection.SELL:
            if structure.trend == TrendDirection.BEARISH:
                trend_pts = 10.0 * max(0.5, structure.trend_strength)
                score += trend_pts
                catalysts.append(f"Bearish Market Structure ({structure.trend_strength * 100:.0f}% strength)")
            elif structure.trend == TrendDirection.RANGING:
                score += 4.0
            elif structure.trend == TrendDirection.BULLISH:
                opposing.append(f"Opposing Bullish Trend ({structure.trend_strength * 100:.0f}% strength)")

        # 2. Multi-Timeframe (MTF) Alignment (Max 10.0 pts)
        if mtf:
            if direction == SignalDirection.BUY:
                if mtf.alignment == MultiTimeframeAlignment.BULLISH_ALIGNED:
                    score += 10.0
                    catalysts.append("4H/1H/15M Multi-Timeframe Bullish Alignment")
                elif mtf.alignment == MultiTimeframeAlignment.HTF_BULLISH_PULLBACK:
                    score += 5.0
                    catalysts.append("HTF Bullish Pullback to Discount")
                elif mtf.alignment == MultiTimeframeAlignment.BEARISH_ALIGNED:
                    opposing.append("Opposing MTF Bearish Alignment")
            elif direction == SignalDirection.SELL:
                if mtf.alignment == MultiTimeframeAlignment.BEARISH_ALIGNED:
                    score += 10.0
                    catalysts.append("4H/1H/15M Multi-Timeframe Bearish Alignment")
                elif mtf.alignment == MultiTimeframeAlignment.HTF_BEARISH_PULLBACK:
                    score += 5.0
                    catalysts.append("HTF Bearish Pullback to Premium")
                elif mtf.alignment == MultiTimeframeAlignment.BULLISH_ALIGNED:
                    opposing.append("Opposing MTF Bullish Alignment")

        # 3. Structural Break: BOS Continuation & CHOCH Reversal (Max 10.0 pts)
        if direction == SignalDirection.BUY:
            if structure.latest_bos and structure.latest_bos.event_type == BOSCHOCHType.BULLISH_BOS:
                score += 10.0
                catalysts.append("Confirmed Bullish BOS (Trend Expansion)")
            elif structure.latest_choch and structure.latest_choch.event_type == BOSCHOCHType.BULLISH_CHOCH:
                score += 8.0
                catalysts.append("Confirmed Bullish CHOCH/MSS (Structural Reversal)")
            
            # Opposing break check
            if structure.latest_choch and structure.latest_choch.event_type == BOSCHOCHType.BEARISH_CHOCH:
                opposing.append("Opposing Bearish CHOCH detected")
        elif direction == SignalDirection.SELL:
            if structure.latest_bos and structure.latest_bos.event_type == BOSCHOCHType.BEARISH_BOS:
                score += 10.0
                catalysts.append("Confirmed Bearish BOS (Trend Expansion)")
            elif structure.latest_choch and structure.latest_choch.event_type == BOSCHOCHType.BEARISH_CHOCH:
                score += 8.0
                catalysts.append("Confirmed Bearish CHOCH/MSS (Structural Reversal)")

            # Opposing break check
            if structure.latest_choch and structure.latest_choch.event_type == BOSCHOCHType.BULLISH_CHOCH:
                opposing.append("Opposing Bullish CHOCH detected")

        final_score = min(self.MAX_POINTS, score)
        pillar_dir = direction if final_score >= 12.0 else SignalDirection.WAIT
        confidence = min(1.0, final_score / self.MAX_POINTS)

        return PillarEvaluation(
            pillar_name="Structure & MTF Alignment",
            direction=pillar_dir,
            score=round(final_score, 1),
            max_score=self.MAX_POINTS,
            weight_percent=self.WEIGHT,
            confidence=round(confidence, 2),
            catalysts=catalysts,
            opposing_signals=opposing,
        )


# =====================================================================
# Pillar 2: Smart Money Concepts & Liquidity (25% Weight / Max 25.0 pts)
# =====================================================================
class LiquiditySMCConsensusEvaluator:
    """Evaluates Liquidity Sweeps, Fresh S/R & Order Blocks, and Liquidity Pools."""

    MAX_POINTS: float = 25.0
    WEIGHT: float = 25.0

    def evaluate(
        self,
        direction: SignalDirection,
        structure: AdvancedStructureAnalysisResponse,
        current_price: float,
    ) -> PillarEvaluation:
        """Score institutional liquidity sweeps and order block zones."""
        score = 0.0
        catalysts: List[str] = []
        opposing: List[str] = []

        # 1. Institutional Liquidity Sweeps (Max 15.0 pts)
        if direction == SignalDirection.BUY:
            if structure.latest_sweep and structure.latest_sweep.sweep_type == LiquidityEventType.SELL_SIDE_SWEEP:
                pips = structure.latest_sweep.pips_swept
                score += 15.0
                catalysts.append(f"Sell-Side Liquidity Sweep ({pips:.1f} pips stop hunt below support)")
            elif structure.latest_sweep and structure.latest_sweep.sweep_type == LiquidityEventType.BUY_SIDE_SWEEP:
                opposing.append("Recent Buy-Side Liquidity Sweep (Potential Bearish Rejection)")
        elif direction == SignalDirection.SELL:
            if structure.latest_sweep and structure.latest_sweep.sweep_type == LiquidityEventType.BUY_SIDE_SWEEP:
                pips = structure.latest_sweep.pips_swept
                score += 15.0
                catalysts.append(f"Buy-Side Liquidity Sweep ({pips:.1f} pips stop hunt above resistance)")
            elif structure.latest_sweep and structure.latest_sweep.sweep_type == LiquidityEventType.SELL_SIDE_SWEEP:
                opposing.append("Recent Sell-Side Liquidity Sweep (Potential Bullish Rejection)")

        # 2. Key Institutional S/R & Demand/Supply Zones (Max 10.0 pts)
        if direction == SignalDirection.BUY:
            support_zones = [z for z in structure.sr_zones if z.zone_type == ZoneType.SUPPORT and z.is_fresh]
            in_demand_zone = False
            for z in support_zones:
                tol = max(0.0005, (z.price_high - z.price_low) * 2.0)
                if abs(current_price - z.center_price) <= tol or (z.price_low <= current_price <= z.price_high):
                    in_demand_zone = True
                    break

            if in_demand_zone:
                score += 10.0
                catalysts.append("Entry at Fresh Institutional Demand / Support Zone")
            elif any(p.pool_type == LiquidityEventType.EQUAL_LOWS for p in structure.liquidity_pools):
                score += 5.0
                catalysts.append("Equal Lows Liquidity Resting Below Price")
            elif score == 0.0 and structure.trend == TrendDirection.BULLISH:
                # Baseline structural liquidity in confirmed institutional trend
                base_liq = round(8.0 * max(0.5, structure.trend_strength), 1)
                score += base_liq
                catalysts.append(f"Institutional Trend Liquidity Alignment ({base_liq} pts)")
        elif direction == SignalDirection.SELL:
            resistance_zones = [z for z in structure.sr_zones if z.zone_type == ZoneType.RESISTANCE and z.is_fresh]
            in_supply_zone = False
            for z in resistance_zones:
                tol = max(0.0005, (z.price_high - z.price_low) * 2.0)
                if abs(current_price - z.center_price) <= tol or (z.price_low <= current_price <= z.price_high):
                    in_supply_zone = True
                    break

            if in_supply_zone:
                score += 10.0
                catalysts.append("Entry at Fresh Institutional Supply / Resistance Zone")
            elif any(p.pool_type == LiquidityEventType.EQUAL_HIGHS for p in structure.liquidity_pools):
                score += 5.0
                catalysts.append("Equal Highs Liquidity Resting Above Price")
            elif score == 0.0 and structure.trend == TrendDirection.BEARISH:
                # Baseline structural liquidity in confirmed institutional trend
                base_liq = round(8.0 * max(0.5, structure.trend_strength), 1)
                score += base_liq
                catalysts.append(f"Institutional Trend Liquidity Alignment ({base_liq} pts)")

        final_score = min(self.MAX_POINTS, score)
        pillar_dir = direction if final_score >= 8.0 else SignalDirection.WAIT
        confidence = min(1.0, final_score / self.MAX_POINTS)

        return PillarEvaluation(
            pillar_name="Liquidity & SMC",
            direction=pillar_dir,
            score=round(final_score, 1),
            max_score=self.MAX_POINTS,
            weight_percent=self.WEIGHT,
            confidence=round(confidence, 2),
            catalysts=catalysts,
            opposing_signals=opposing,
        )


# =====================================================================
# Pillar 3: Momentum & Trend Indicators (25% Weight / Max 25.0 pts)
# =====================================================================
class MomentumIndicatorConsensusEvaluator:
    """Evaluates EMA 20/50/200 Stack, RSI Dynamic Zones & Divergences, and Fair Value Gaps."""

    MAX_POINTS: float = 25.0
    WEIGHT: float = 25.0

    def evaluate(
        self,
        direction: SignalDirection,
        indicators: IndicatorAnalysisResponse,
    ) -> PillarEvaluation:
        """Score technical indicator confluence, dynamic RSI momentum, and FVGs."""
        score = 0.0
        catalysts: List[str] = []
        opposing: List[str] = []

        # 1. EMA Dynamic Trend Stack (Max 10.0 pts)
        if direction == SignalDirection.BUY:
            if indicators.ema.ema_trend == "BULLISH_STACK":
                score += 10.0
                catalysts.append("EMA Bullish Stack (Price > 20 > 50 > 200)")
            elif indicators.ema.price_vs_ema200 == "ABOVE":
                score += 6.0
                catalysts.append("Price Holding Above 200 EMA")
            elif indicators.ema.ema_trend == "BEARISH_STACK":
                opposing.append("Opposing Bearish EMA Stack")
        elif direction == SignalDirection.SELL:
            if indicators.ema.ema_trend == "BEARISH_STACK":
                score += 10.0
                catalysts.append("EMA Bearish Stack (Price < 20 < 50 < 200)")
            elif indicators.ema.price_vs_ema200 == "BELOW":
                score += 6.0
                catalysts.append("Price Holding Below 200 EMA")
            elif indicators.ema.ema_trend == "BULLISH_STACK":
                opposing.append("Opposing Bullish EMA Stack")

        # 2. RSI Momentum & Regular/Hidden Divergences (Max 10.0 pts)
        if direction == SignalDirection.BUY:
            bull_divs = [
                d for d in indicators.divergences
                if d.divergence_type in (DivergenceType.REGULAR_BULLISH, DivergenceType.HIDDEN_BULLISH)
            ]
            if bull_divs:
                score += 10.0
                catalysts.append(f"RSI Bullish Divergence ({bull_divs[-1].divergence_type.value})")
            elif indicators.ema.ema_trend == "BULLISH_STACK" and indicators.rsi.rsi_value is not None and indicators.rsi.rsi_value >= 70.0:
                # Strong trend momentum leg expansion
                score += 6.0
                catalysts.append(f"RSI Strong Trend Momentum ({indicators.rsi.rsi_value:.1f})")
            elif indicators.rsi.condition in ("BULLISH_ZONE", "OVERSOLD"):
                score += 5.0
                catalysts.append(f"RSI Bullish Momentum ({indicators.rsi.condition})")

            # Check recent opposing divergences (latest 2 divergences only)
            recent_bear_divs = [
                d for d in indicators.divergences[-2:]
                if d.divergence_type in (DivergenceType.REGULAR_BEARISH, DivergenceType.HIDDEN_BEARISH)
            ]
            if recent_bear_divs:
                opposing.append(f"Opposing Bearish RSI Divergence ({recent_bear_divs[-1].divergence_type.value})")
        elif direction == SignalDirection.SELL:
            bear_divs = [
                d for d in indicators.divergences
                if d.divergence_type in (DivergenceType.REGULAR_BEARISH, DivergenceType.HIDDEN_BEARISH)
            ]
            if bear_divs:
                score += 10.0
                catalysts.append(f"RSI Bearish Divergence ({bear_divs[-1].divergence_type.value})")
            elif indicators.ema.ema_trend == "BEARISH_STACK" and indicators.rsi.rsi_value is not None and indicators.rsi.rsi_value <= 30.0:
                # Strong trend momentum leg expansion
                score += 6.0
                catalysts.append(f"RSI Strong Trend Momentum ({indicators.rsi.rsi_value:.1f})")
            elif indicators.rsi.condition in ("BEARISH_ZONE", "OVERBOUGHT"):
                score += 5.0
                catalysts.append(f"RSI Bearish Momentum ({indicators.rsi.condition})")

            # Check recent opposing divergences (latest 2 divergences only)
            recent_bull_divs = [
                d for d in indicators.divergences[-2:]
                if d.divergence_type in (DivergenceType.REGULAR_BULLISH, DivergenceType.HIDDEN_BULLISH)
            ]
            if recent_bull_divs:
                opposing.append(f"Opposing Bullish RSI Divergence ({recent_bull_divs[-1].divergence_type.value})")

        # 3. Fair Value Gaps (FVG) / Imbalances (Max 5.0 pts)
        if direction == SignalDirection.BUY:
            bull_fvgs = [f for f in indicators.active_fvgs if f.fvg_type == FVGType.BULLISH_FVG]
            if bull_fvgs:
                score += 5.0
                catalysts.append(f"Active Bullish Fair Value Gap ({bull_fvgs[-1].gap_pips:.1f} pips)")
        elif direction == SignalDirection.SELL:
            bear_fvgs = [f for f in indicators.active_fvgs if f.fvg_type == FVGType.BEARISH_FVG]
            if bear_fvgs:
                score += 5.0
                catalysts.append(f"Active Bearish Fair Value Gap ({bear_fvgs[-1].gap_pips:.1f} pips)")

        final_score = min(self.MAX_POINTS, score)
        pillar_dir = direction if final_score >= 10.0 else SignalDirection.WAIT
        confidence = min(1.0, final_score / self.MAX_POINTS)

        return PillarEvaluation(
            pillar_name="Momentum & Indicators",
            direction=pillar_dir,
            score=round(final_score, 1),
            max_score=self.MAX_POINTS,
            weight_percent=self.WEIGHT,
            confidence=round(confidence, 2),
            catalysts=catalysts,
            opposing_signals=opposing,
        )


# =====================================================================
# Pillar 4: Price Action & Execution Geometry (20% Weight / Max 20.0 pts)
# =====================================================================
class PriceActionConsensusEvaluator:
    """Evaluates Candlestick Triggers, Rejection Wicks, and Engulfing Impulse Candlesticks."""

    MAX_POINTS: float = 20.0
    WEIGHT: float = 20.0

    def evaluate(
        self,
        direction: SignalDirection,
        indicators: IndicatorAnalysisResponse,
    ) -> PillarEvaluation:
        """Score candlestick patterns and execution trigger confirmation."""
        score = 0.0
        catalysts: List[str] = []
        opposing: List[str] = []

        # Check latest trigger patterns (last 2 candles for immediate entry context)
        immediate_patterns = indicators.recent_patterns[-2:] if indicators.recent_patterns else []

        if direction == SignalDirection.BUY:
            bull_patterns = [
                p for p in immediate_patterns
                if p.pattern_type in (PatternType.BULLISH_PIN_BAR, PatternType.BULLISH_ENGULFING)
            ]
            if bull_patterns:
                best_pat = bull_patterns[-1]
                score += 20.0 * best_pat.confidence
                catalysts.append(f"Candlestick Trigger: {best_pat.pattern_type.value}")
            elif any(p.pattern_type == PatternType.INSIDE_BAR for p in immediate_patterns):
                score += 10.0
                catalysts.append("Inside Bar Volatility Compression")

            # Check opposing patterns in immediate context (last 2 bars)
            bear_patterns = [
                p for p in immediate_patterns
                if p.pattern_type in (PatternType.BEARISH_PIN_BAR, PatternType.BEARISH_ENGULFING)
            ]
            if bear_patterns:
                opposing.append(f"Opposing Candlestick: {bear_patterns[-1].pattern_type.value}")
        elif direction == SignalDirection.SELL:
            bear_patterns = [
                p for p in immediate_patterns
                if p.pattern_type in (PatternType.BEARISH_PIN_BAR, PatternType.BEARISH_ENGULFING)
            ]
            if bear_patterns:
                best_pat = bear_patterns[-1]
                score += 20.0 * best_pat.confidence
                catalysts.append(f"Candlestick Trigger: {best_pat.pattern_type.value}")
            elif any(p.pattern_type == PatternType.INSIDE_BAR for p in immediate_patterns):
                score += 10.0
                catalysts.append("Inside Bar Volatility Compression")

            # Check opposing patterns in immediate context (last 2 bars)
            bull_patterns = [
                p for p in immediate_patterns
                if p.pattern_type in (PatternType.BULLISH_PIN_BAR, PatternType.BULLISH_ENGULFING)
            ]
            if bull_patterns:
                opposing.append(f"Opposing Candlestick: {bull_patterns[-1].pattern_type.value}")

        final_score = min(self.MAX_POINTS, score)
        pillar_dir = direction if final_score >= 10.0 else SignalDirection.WAIT
        confidence = min(1.0, final_score / self.MAX_POINTS)

        return PillarEvaluation(
            pillar_name="Price Action Confirmation",
            direction=pillar_dir,
            score=round(final_score, 1),
            max_score=self.MAX_POINTS,
            weight_percent=self.WEIGHT,
            confidence=round(confidence, 2),
            catalysts=catalysts,
            opposing_signals=opposing,
        )


# =====================================================================
# Consensus Agreement & Directional Conflict Filter
# =====================================================================
class ConsensusFilter:
    """Evaluates multi-pillar agreement, penalizes directional conflicts, and synthesizes score."""

    def __init__(self, min_score_threshold: Optional[float] = None):
        self.min_score_threshold = min_score_threshold or settings.MIN_SETUP_SCORE

    def synthesize(
        self,
        evaluations: Dict[str, PillarEvaluation],
        candidate_direction: SignalDirection,
    ) -> Tuple[float, ScoreBreakdown, List[str], bool]:
        """Synthesize pillar evaluations for a given direction into a composite score.

        Returns:
            Tuple of (final_score, ScoreBreakdown, consolidated_catalysts, has_fatal_conflict)
        """
        raw_struct = evaluations.get("structure", PillarEvaluation("Structure", SignalDirection.WAIT, 0, 30, 30, 0)).score
        raw_liq = evaluations.get("liquidity", PillarEvaluation("Liquidity", SignalDirection.WAIT, 0, 25, 25, 0)).score
        raw_ind = evaluations.get("indicators", PillarEvaluation("Indicators", SignalDirection.WAIT, 0, 25, 25, 0)).score
        raw_pa = evaluations.get("price_action", PillarEvaluation("Price Action", SignalDirection.WAIT, 0, 20, 20, 0)).score

        raw_total = round(raw_struct + raw_liq + raw_ind + raw_pa, 1)

        # Collect all catalysts and opposing signals
        all_catalysts: List[str] = []
        all_opposing: List[str] = []

        for p in evaluations.values():
            all_catalysts.extend(p.catalysts)
            all_opposing.extend(p.opposing_signals)

        # ------------------------------------------------------------------
        # Price Action Floor Gate
        # Any signal that reaches the overall score threshold purely through
        # Structure + Liquidity + Indicators (i.e. zero candlestick confirmation)
        # is inherently unconfirmed and prone to false execution.  Require at
        # least 10.0 / 20.0 PA points before a direction can be qualified.
        # ------------------------------------------------------------------
        pa_floor_blocked = False
        confluence_blocked = False
        if raw_pa < 10.0 and candidate_direction in (SignalDirection.BUY, SignalDirection.SELL):
            pa_floor_blocked = True
            all_catalysts.append(
                f"\u26d4 Price Action Floor Not Met: {raw_pa:.1f}/20.0 "
                "(minimum 10.0 required). No candlestick confirmation present "
                "(Pin Bar, Engulfing, or Inside Bar). Signal disqualified to prevent "
                "unconfirmed entry against live momentum."
            )
            logger.warning(
                f"PA Floor veto [{candidate_direction.value}]: price_action_score={raw_pa:.1f}/20 "
                "is below the 10.0 floor — signal disqualified."
            )

        # ------------------------------------------------------------------
        # Minimum Confluence Rule (The "No Pure Indicator" Filter)
        # A signal cannot be driven purely by lagging indicators. 
        # It must have at least some structural or liquidity backing.
        # ------------------------------------------------------------------
        structural_confluence = raw_struct + raw_liq
        if structural_confluence < 15.0 and candidate_direction in (SignalDirection.BUY, SignalDirection.SELL):
            confluence_blocked = True
            all_catalysts.append(
                f"\u26d4 Minimum Confluence Not Met: Structure + Liquidity = {structural_confluence:.1f} "
                "(minimum 15.0 required). Pure indicator setups are prone to exhaustion and false breakouts."
            )
            logger.warning(
                f"Confluence veto [{candidate_direction.value}]: Structure+Liquidity={structural_confluence:.1f} "
                "is below the 15.0 floor \u2014 pure indicator signal disqualified."
            )

        # Calculate directional conflict penalty
        penalty = 0.0
        fatal_conflict = False

        if all_opposing:
            if len(all_opposing) == 1:
                penalty = 15.0
                all_catalysts.append(f"\u26a0\ufe0f Directional Conflict Warning: {all_opposing[0]} (Penalty: -15.0 pts)")
            else:
                penalty = 30.0
                fatal_conflict = True
                all_catalysts.append(
                    f"\u26d4 Severe Directional Conflict: {', '.join(all_opposing)} (Setup Invalidated)"
                )

        penalized_total = max(0.0, round(raw_total - penalty, 1))
        is_qualified = (
            penalized_total >= self.min_score_threshold
            and not fatal_conflict
            and not pa_floor_blocked
            and not confluence_blocked
        )

        breakdown = ScoreBreakdown(
            structure_score=round(raw_struct, 1),
            liquidity_score=round(raw_liq, 1),
            indicators_score=round(raw_ind, 1),
            price_action_score=round(raw_pa, 1),
            total_score=penalized_total,
            is_qualified=is_qualified,
        )

        return penalized_total, breakdown, all_catalysts, fatal_conflict
