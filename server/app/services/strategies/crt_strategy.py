"""Strategy D (Candle Range Theory) — AMD Accumulation, Manipulation, Distribution Strategy.

A modular, standalone strategy based on the institutional AMD framework:
- Accumulation: Benchmark range set by a completed higher timeframe candle (e.g. 1H).
- Manipulation: Liquidity sweep breaching the range boundary on a lower timeframe (e.g. 15m)
  by at least `min_manip_pct` depth.
- Distribution: Confirmed when lower timeframe candle(s) close back inside the benchmark range.

Risk Management:
- Entry: Current market price.
- Stop Loss: The extreme manipulation wick (breach_point).
- Take Profit 1: 1.5 R:R ratio relative to the manipulation wick.
"""

from typing import Any, Dict, List, Optional, Sequence, Union
from app.core.config import settings
from app.core.logging import logger
from app.schemas.indicators import IndicatorAnalysisResponse
from app.schemas.liquidity import AdvancedStructureAnalysisResponse
from app.schemas.signal import ScoreBreakdown, SignalDirection
from app.schemas.structure import CRTAnalysis, MultiTimeframeStructureResponse
from app.services.strategies.base import BaseStrategy, StrategyResult
from app.services.structure.crt_analyzer import CRTAnalyzer, _get_candle_val


class CRTStrategy(BaseStrategy):
    """Candle Range Theory (CRT) Strategy implementing the AMD framework.

    Runs in parallel with SMCStrategy and RangeStrategy as a standalone high-probability setup.
    """

    def __init__(
        self,
        min_manip_pct: float = 5.0,
        max_manip_pct: float = 100.0,
        confirm_bars: int = 1,
        base_score: float = 80.0,
        min_score_threshold: Optional[float] = None,
        analyzer: Optional[CRTAnalyzer] = None,
    ) -> None:
        self.min_manip_pct = min_manip_pct
        self.max_manip_pct = max_manip_pct
        self.confirm_bars = confirm_bars
        self.base_score = base_score
        self._min_score_threshold = (
            min_score_threshold if min_score_threshold is not None else settings.MIN_SETUP_SCORE
        )
        self.analyzer = analyzer or CRTAnalyzer(
            default_min_manip_pct=min_manip_pct,
            default_confirm_bars=confirm_bars,
        )


    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Human-readable strategy identifier."""
        return "Candle Range Theory (CRT)"

    def analyze(
        self,
        symbol: str,
        timeframe: str,
        candles: Sequence[Any],
        indicators: Optional[IndicatorAnalysisResponse] = None,
        structure: Optional[AdvancedStructureAnalysisResponse] = None,
        mtf: Optional[MultiTimeframeStructureResponse] = None,
        candles_15m: Optional[Sequence[Any]] = None,
        range_candles: Optional[Sequence[Any]] = None,
        confirm_candles: Optional[Sequence[Any]] = None,
        htf_trend: str = "RANGING",
        **kwargs: Any,
    ) -> StrategyResult:
        """Evaluate BUY and SELL setups using the Candle Range Theory (AMD) framework.

        Args:
            symbol: Trading instrument (e.g. "XAU/USD").
            timeframe: Timeframe of the primary analysis (e.g. "1h" or "15m").
            candles: Primary timeframe candles.
            indicators: Pre-computed indicators for primary candles (optional).
            structure: Advanced structure analysis (optional).
            mtf: Multi-timeframe structure response (optional).
            candles_15m: Lower timeframe candles for confirmation.
            range_candles: Explicit HTF accumulation candles (overrides auto-detection).
            confirm_candles: Explicit LTF manipulation/confirmation candles (overrides auto-detection).
            htf_trend: Higher timeframe trend bias ("BULLISH", "BEARISH", "RANGING").
            **kwargs: Additional candle sets (e.g. candles_1h, candles_4h).

        Returns:
            A StrategyResult with score 80.0 on qualified setups and dynamic SL/TP levels.
        """
        # 1. Resolve Range (HTF) and Confirmation (LTF) candle series
        r_candles = range_candles
        c_candles = confirm_candles

        if r_candles is None:
            if candles_15m is not None and len(candles_15m) > 0:
                # Primary candles represent the HTF range (e.g. 1H), candles_15m the LTF
                r_candles = candles
                if c_candles is None:
                    c_candles = candles_15m
            elif kwargs.get("candles_1h") is not None:
                r_candles = kwargs.get("candles_1h")
                if c_candles is None:
                    c_candles = candles
            elif kwargs.get("candles_4h") is not None:
                r_candles = kwargs.get("candles_4h")
                if c_candles is None:
                    c_candles = candles
            else:
                r_candles = candles
                if c_candles is None:
                    c_candles = candles

        if c_candles is None:
            c_candles = candles_15m if candles_15m is not None else candles

        # 2. Run CRT Analysis
        analysis: CRTAnalysis = self.analyzer.analyze(
            range_candles=r_candles,
            confirm_candles=c_candles,
            min_manip_pct=self.min_manip_pct,
            confirm_bars=self.confirm_bars,
        )

        # 3. Determine Current Price for Entry
        if (
            indicators is not None
            and getattr(indicators, "current_price", None) is not None
            and indicators.current_price > 0
        ):
            current_price = indicators.current_price
        elif c_candles and len(c_candles) > 0:
            current_price = _get_candle_val(c_candles[-1], "close")
        elif r_candles and len(r_candles) > 0:
            current_price = _get_candle_val(r_candles[-1], "close")
        else:
            current_price = 0.0

        # Determine HTF Trend (infer from mtf or structure if default "RANGING")
        resolved_htf_trend = (
            htf_trend.value if hasattr(htf_trend, "value") else str(htf_trend)
        ).upper() if htf_trend is not None else "RANGING"

        if resolved_htf_trend == "RANGING":
            if mtf is not None:
                if hasattr(mtf, "trend") and mtf.trend:
                    t = mtf.trend.value if hasattr(mtf.trend, "value") else str(mtf.trend).upper()
                    if t in ("BULLISH", "BEARISH"):
                        resolved_htf_trend = t
                elif hasattr(mtf, "timeframes") and mtf.timeframes:
                    for tf_key in ("1h", "4h"):
                        if tf_key in mtf.timeframes and mtf.timeframes[tf_key].trend:
                            t = mtf.timeframes[tf_key].trend
                            t_val = t.value if hasattr(t, "value") else str(t).upper()
                            if t_val in ("BULLISH", "BEARISH"):
                                resolved_htf_trend = t_val
                                break
                if resolved_htf_trend == "RANGING" and hasattr(mtf, "primary_trend") and mtf.primary_trend:
                    t = mtf.primary_trend.value if hasattr(mtf.primary_trend, "value") else str(mtf.primary_trend).upper()
                    if t in ("BULLISH", "BEARISH"):
                        resolved_htf_trend = t

            if resolved_htf_trend == "RANGING" and structure is not None and hasattr(structure, "trend") and structure.trend:
                t = structure.trend.value if hasattr(structure.trend, "value") else str(structure.trend).upper()
                if t in ("BULLISH", "BEARISH"):
                    resolved_htf_trend = t

        htf_trend = resolved_htf_trend

        # 4. Check Setup Qualification
        is_qualified = (
            analysis.is_confirmed
            and analysis.is_breached
            and analysis.breach_point is not None
            and analysis.manip_depth_pct >= self.min_manip_pct
            and analysis.manip_depth_pct <= self.max_manip_pct
            and current_price > 0.0
        )

        if is_qualified:
            direction = (
                SignalDirection.BUY
                if analysis.positive_direction
                else SignalDirection.SELL
            )
            score = self.base_score
            stop_loss = analysis.breach_point
            risk_distance = abs(current_price - stop_loss)

            if direction == SignalDirection.BUY:
                take_profit_1 = round(current_price + (risk_distance * 1.5), 5)
                take_profit_2 = round(current_price + (risk_distance * 2.5), 5)
            else:
                take_profit_1 = round(current_price - (risk_distance * 1.5), 5)
                take_profit_2 = round(current_price - (risk_distance * 2.5), 5)

            score_breakdown = ScoreBreakdown(
                structure_score=30.0,
                liquidity_score=30.0,
                indicators_score=0.0,
                price_action_score=20.0,
                total_score=score,
                is_qualified=True,
            )

            bias_str = "BULLISH" if analysis.positive_direction else "BEARISH"
            reasons = [
                f"CRT AMD Setup Confirmed ({direction.value}): {bias_str} Accumulation -> Manipulation -> Distribution",
                f"Accumulation Range: High={analysis.range_high:.5f}, Low={analysis.range_low:.5f}, Open={analysis.range_open:.5f}, Close={analysis.range_close:.5f}",
                f"Manipulation Phase: Extreme breach at {analysis.breach_point:.5f} ({analysis.manip_depth_pct:.1f}% depth >= {self.min_manip_pct:.1f}% min, <= {self.max_manip_pct:.1f}% max)",
                f"Distribution Phase: Price closed back inside range ({'above range low' if analysis.positive_direction else 'below range high'})",
                f"Risk Profile: Entry={current_price:.5f}, SL={stop_loss:.5f} (Breach Point), TP1={take_profit_1:.5f} (1.5 R:R)",
            ]

            # --- HTF TREND ALIGNMENT FILTER ---
            if htf_trend == "BEARISH" and direction == SignalDirection.BUY:
                is_qualified = False
                reasons.append(f"REJECTED (Trend Conflict): HTF Trend is BEARISH. Ignoring Bullish CRT setup.")
                
            elif htf_trend == "BULLISH" and direction == SignalDirection.SELL:
                is_qualified = False
                reasons.append(f"REJECTED (Trend Conflict): HTF Trend is BULLISH. Ignoring Bearish CRT setup.")
            # ----------------------------------

            if not is_qualified:
                score_breakdown = ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                )
                metadata = {
                    "crt_analysis": analysis.model_dump(),
                    "gatekeeper_passed": False,
                    "trend_conflict": True,
                    "htf_trend": htf_trend,
                }
                result = StrategyResult(
                    strategy_name=self.name,
                    direction=SignalDirection.WAIT,
                    score=0.0,
                    reasons=reasons,
                    metadata=metadata,
                    score_breakdown=score_breakdown,
                )
                result.entry_price = round(current_price, 5) if current_price > 0 else 0.0
                result.stop_loss = 0.0
                result.take_profit_1 = 0.0
                result.take_profit_2 = 0.0
                result.risk_reward = 0.0
                result.breach_point = analysis.breach_point
                return result

            metadata: Dict[str, Any] = {
                "entry_price": round(current_price, 5),
                "stop_loss": round(stop_loss, 5),
                "take_profit_1": round(take_profit_1, 5),
                "take_profit_2": round(take_profit_2, 5),
                "risk_reward": 1.5,
                "breach_point": analysis.breach_point,
                "manip_depth_pct": analysis.manip_depth_pct,
                "crt_analysis": analysis.model_dump(),
                "positive_direction": analysis.positive_direction,
                "htf_trend": htf_trend,
            }

            result = StrategyResult(
                strategy_name=self.name,
                direction=direction,
                score=score,
                reasons=reasons,
                metadata=metadata,
                score_breakdown=score_breakdown,
            )

            # Direct attribute exposure for ergonomic access in callers/tests
            result.entry_price = round(current_price, 5)
            result.stop_loss = round(stop_loss, 5)
            result.take_profit_1 = round(take_profit_1, 5)
            result.take_profit_2 = round(take_profit_2, 5)
            result.risk_reward = 1.5
            result.breach_point = analysis.breach_point
            return result

        # 5. Non-qualified setup returns WAIT
        score_breakdown = ScoreBreakdown(
            structure_score=0.0,
            liquidity_score=0.0,
            indicators_score=0.0,
            price_action_score=0.0,
            total_score=0.0,
            is_qualified=False,
        )

        reasons = [
            f"MARKET BIAS: NEUTRAL / WAIT (CRT Setup Not Confirmed).",
            f"Accumulation: High={analysis.range_high:.5f}, Low={analysis.range_low:.5f}, Positive={analysis.positive_direction}",
            f"Manipulation State: Breached={analysis.is_breached}, BreachPoint={analysis.breach_point}, Depth={analysis.manip_depth_pct:.1f}% (Min {self.min_manip_pct:.1f}%, Max {self.max_manip_pct:.1f}%)",
            f"Distribution State: Confirmed={analysis.is_confirmed}",
        ]

        if analysis.manip_depth_pct > self.max_manip_pct:
            reasons.append(
                f"REJECTED: Manipulation depth ({analysis.manip_depth_pct:.1f}%) exceeds maximum allowed ({self.max_manip_pct:.1f}%). Likely a breakout/spike, not a sweep."
            )


        metadata = {
            "crt_analysis": analysis.model_dump(),
            "gatekeeper_passed": False,
        }

        result = StrategyResult(
            strategy_name=self.name,
            direction=SignalDirection.WAIT,
            score=0.0,
            reasons=reasons,
            metadata=metadata,
            score_breakdown=score_breakdown,
        )
        result.entry_price = round(current_price, 5) if current_price > 0 else 0.0
        result.stop_loss = 0.0
        result.take_profit_1 = 0.0
        result.take_profit_2 = 0.0
        result.risk_reward = 0.0
        result.breach_point = analysis.breach_point
        return result
