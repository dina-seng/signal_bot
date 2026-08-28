"""Unified Technical Indicators, Price Action, and Confluence Scoring Service."""

from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Union

from app.core.config import settings
from app.schemas.candle import CandleBase
from app.schemas.indicators import (
    DivergenceType,
    IndicatorAnalysisResponse,
    PatternType,
)
from app.services.indicators.ema_calculator import EMACalculator
from app.services.indicators.rsi_calculator import RSICalculator
from app.services.indicators.atr_calculator import ATRCalculator
from app.services.indicators.price_action import PriceActionDetector
from app.services.structure.swing_detector import SwingDetector


class IndicatorService:
    """Orchestrates EMA, RSI, ATR, Divergence, Price Action, and Fair Value Gap analysis."""

    def __init__(
        self,
        ema_calc: Optional[EMACalculator] = None,
        rsi_calc: Optional[RSICalculator] = None,
        atr_calc: Optional[ATRCalculator] = None,
        pa_detector: Optional[PriceActionDetector] = None,
        swing_detector: Optional[SwingDetector] = None,
    ):
        self.ema_calc = ema_calc or EMACalculator()
        self.rsi_calc = rsi_calc or RSICalculator()
        self.atr_calc = atr_calc or ATRCalculator()
        self.pa_detector = pa_detector or PriceActionDetector()
        self.swing_detector = swing_detector or SwingDetector(default_lookback=settings.SWING_LOOKBACK)

    @staticmethod
    def _extract_arrays(
        candles: Sequence[Union[CandleBase, Any]],
    ) -> tuple[List[datetime], List[float], List[float], List[float], List[float]]:
        """Extract timestamps, opens, highs, lows, closes as parallel lists."""
        timestamps: List[datetime] = []
        opens: List[float] = []
        highs: List[float] = []
        lows: List[float] = []
        closes: List[float] = []

        for c in candles:
            if isinstance(c, dict):
                ts = c.get("timestamp")
                o = float(c.get("open", 0.0))
                h = float(c.get("high", 0.0))
                l = float(c.get("low", 0.0))
                cl = float(c.get("close", 0.0))
            else:
                ts = getattr(c, "timestamp")
                o = float(getattr(c, "open"))
                h = float(getattr(c, "high"))
                l = float(getattr(c, "low"))
                cl = float(getattr(c, "close"))

            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)

            timestamps.append(ts)
            opens.append(o)
            highs.append(h)
            lows.append(l)
            closes.append(cl)

        return timestamps, opens, highs, lows, closes

    def _calculate_confluence(
        self,
        ema_trend: str,
        price_vs_200: Optional[str],
        rsi_condition: str,
        divergences: list,
        recent_patterns: list,
    ) -> tuple[str, float]:
        """Compute directional technical confluence score from -100 (Strong Bearish) to +100 (Strong Bullish)."""
        score = 0.0

        # 1. EMA Trend Factor
        if ema_trend == "BULLISH_STACK":
            score += 25.0
        elif ema_trend == "BEARISH_STACK":
            score -= 25.0
        elif ema_trend == "BULLISH_BIAS":
            score += 10.0
        elif ema_trend == "BEARISH_BIAS":
            score -= 10.0

        if price_vs_200 == "ABOVE":
            score += 15.0
        elif price_vs_200 == "BELOW":
            score -= 15.0

        # 2. RSI Condition Factor
        if rsi_condition == "BULLISH_ZONE":
            score += 15.0
        elif rsi_condition == "BEARISH_ZONE":
            score -= 15.0
        elif rsi_condition == "OVERSOLD":
            score += 20.0  # Mean reversion upside potential
        elif rsi_condition == "OVERBOUGHT":
            score -= 20.0  # Mean reversion downside potential

        # 3. RSI Divergence Factor (most recent divergence)
        if divergences:
            latest_div = divergences[-1]
            if latest_div.divergence_type in (DivergenceType.REGULAR_BULLISH, DivergenceType.HIDDEN_BULLISH):
                score += 25.0 * latest_div.strength
            elif latest_div.divergence_type in (DivergenceType.REGULAR_BEARISH, DivergenceType.HIDDEN_BEARISH):
                score -= 25.0 * latest_div.strength

        # 4. Recent Price Action Pattern Factor
        if recent_patterns:
            latest_pa = recent_patterns[-1]
            if latest_pa.pattern_type in (PatternType.BULLISH_PIN_BAR, PatternType.BULLISH_ENGULFING):
                score += 20.0 * latest_pa.confidence
            elif latest_pa.pattern_type in (PatternType.BEARISH_PIN_BAR, PatternType.BEARISH_ENGULFING):
                score -= 20.0 * latest_pa.confidence

        # Clamp between -100.0 and +100.0
        clamped_score = round(max(-100.0, min(100.0, score)), 1)

        # Categorize bias
        if clamped_score >= 50.0:
            bias = "STRONG_BULLISH"
        elif clamped_score >= 20.0:
            bias = "MODERATE_BULLISH"
        elif clamped_score <= -50.0:
            bias = "STRONG_BEARISH"
        elif clamped_score <= -20.0:
            bias = "MODERATE_BEARISH"
        else:
            bias = "NEUTRAL"

        return bias, clamped_score

    def analyze_indicators(
        self,
        candles: Sequence[Union[CandleBase, Any]],
        symbol: str = "EUR/USD",
        timeframe: str = "1h",
        ema_fast: int = 20,
        ema_mid: int = 50,
        ema_slow: int = 200,
        rsi_period: int = 14,
        atr_period: int = 14,
    ) -> IndicatorAnalysisResponse:
        """Run full indicators, divergences, price action, and confluence analysis on a candle series.

        Args:
            candles: Sequence of candles chronologically sorted.
            symbol: Forex instrument symbol.
            timeframe: Timeframe identifier.
            ema_fast: Fast EMA period.
            ema_mid: Medium EMA period.
            ema_slow: Slow EMA period.
            rsi_period: RSI period.
            atr_period: ATR period.

        Returns:
            IndicatorAnalysisResponse.
        """
        timestamps, opens, highs, lows, closes = self._extract_arrays(candles)
        latest_ts = timestamps[-1] if timestamps else datetime.now(timezone.utc)
        latest_price = closes[-1] if closes else 0.0

        # 1. EMAs
        ema_snapshot, _, _, _ = self.ema_calc.calculate_ema_snapshot(
            closes=closes,
            fast_period=ema_fast,
            mid_period=ema_mid,
            slow_period=ema_slow,
        )

        # 2. RSI & Series
        rsi_snapshot, rsi_series = self.rsi_calc.calculate_rsi_snapshot(
            closes=closes,
            period=rsi_period,
        )

        # 3. Detect Swings & RSI Divergences
        swings = self.swing_detector.detect_swings(candles)
        divergences = self.rsi_calc.detect_divergences(swings=swings, rsi_series=rsi_series)

        # 4. ATR
        atr_snapshot, _ = self.atr_calc.calculate_atr_snapshot(
            highs=highs,
            lows=lows,
            closes=closes,
            symbol=symbol,
            period=atr_period,
        )

        # 5. Price Action Patterns
        patterns = self.pa_detector.detect_candlestick_patterns(candles)

        # 6. Fair Value Gaps
        fvgs = self.pa_detector.detect_fair_value_gaps(candles, symbol=symbol)
        active_fvgs = [f for f in fvgs if not f.is_mitigated]

        # 7. Confluence Scoring
        confluence_bias, confluence_score = self._calculate_confluence(
            ema_trend=ema_snapshot.ema_trend,
            price_vs_200=ema_snapshot.price_vs_ema200,
            rsi_condition=rsi_snapshot.condition,
            divergences=divergences,
            recent_patterns=patterns[-3:] if patterns else [],
        )

        return IndicatorAnalysisResponse(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=latest_ts,
            current_price=latest_price,
            ema=ema_snapshot,
            rsi=rsi_snapshot,
            atr=atr_snapshot,
            divergences=divergences,
            recent_patterns=patterns[-5:] if patterns else [],
            active_fvgs=active_fvgs[-10:] if active_fvgs else [],
            confluence_bias=confluence_bias,
            confluence_score=confluence_score,
        )
