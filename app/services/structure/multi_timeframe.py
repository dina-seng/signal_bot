"""Multi-Timeframe Market Structure Analysis Engine."""

from typing import Dict, List, Optional, Sequence
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from app.core.config import settings
from app.models.candle import Candle
from app.schemas.candle import CandleBase
from app.schemas.structure import (
    MultiTimeframeAlignment,
    MultiTimeframeStructureResponse,
    StructureAnalysisResponse,
    TrendDirection,
)
from app.services.structure.structure_engine import StructureEngine


# Timeframe hierarchy ordering (smaller minutes = lower timeframe)
TIMEFRAME_ORDER = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
}


class MultiTimeframeStructureEngine:
    """Evaluates market structure alignment across multiple timeframes (HTF -> ITF -> LTF)."""

    def __init__(self, structure_engine: Optional[StructureEngine] = None):
        self.structure_engine = structure_engine or StructureEngine()

    @staticmethod
    def _sort_timeframes(timeframes: List[str]) -> List[str]:
        """Sort timeframes from highest timeframe (HTF) to lowest timeframe (LTF)."""
        return sorted(
            timeframes,
            key=lambda tf: TIMEFRAME_ORDER.get(tf.lower(), 0),
            reverse=True,
        )

    def analyze_multi_timeframe(
        self,
        symbol: str,
        timeframe_candles: Dict[str, Sequence[CandleBase]],
        lookback: Optional[int] = None,
        tolerance_percent: Optional[float] = None,
    ) -> MultiTimeframeStructureResponse:
        """Analyze structure across provided candles per timeframe.

        Args:
            symbol: Instrument symbol (e.g., 'EUR/USD').
            timeframe_candles: Dictionary mapping timeframe name -> candle sequence.
            lookback: Lookback bars for swing detection.
            tolerance_percent: Percentage tolerance for equal highs/lows.

        Returns:
            MultiTimeframeStructureResponse with individual TF breakdown and overall alignment.
        """
        tf_list = list(timeframe_candles.keys())
        sorted_tfs = self._sort_timeframes(tf_list)

        results: Dict[str, StructureAnalysisResponse] = {}
        for tf in sorted_tfs:
            candles = timeframe_candles[tf]
            results[tf] = self.structure_engine.analyze_structure(
                candles=candles,
                symbol=symbol,
                timeframe=tf,
                lookback=lookback,
                tolerance_percent=tolerance_percent,
            )

        # Primary HTF is the highest timeframe
        primary_tf = sorted_tfs[0] if sorted_tfs else "4h"
        primary_res = results.get(primary_tf)
        primary_trend = primary_res.trend if primary_res else TrendDirection.RANGING

        # Evaluate overall alignment
        alignment, alignment_score = self.evaluate_alignment(sorted_tfs, results)
        summary = self._build_summary(symbol, primary_tf, primary_trend, sorted_tfs, results, alignment)

        return MultiTimeframeStructureResponse(
            symbol=symbol,
            primary_timeframe=primary_tf,
            primary_trend=primary_trend,
            alignment=alignment,
            alignment_score=alignment_score,
            timeframes=results,
            summary=summary,
        )

    def analyze_from_db(
        self,
        db: Session,
        symbol: str,
        timeframes: Optional[List[str]] = None,
        limit_per_tf: int = 200,
        lookback: Optional[int] = None,
        tolerance_percent: Optional[float] = None,
        persist: bool = False,
    ) -> MultiTimeframeStructureResponse:
        """Fetch candles from database for each timeframe and run multi-timeframe analysis."""
        tfs = timeframes or settings.SUPPORTED_TIMEFRAMES
        sorted_tfs = self._sort_timeframes(tfs)

        timeframe_candles: Dict[str, List[Candle]] = {}
        for tf in sorted_tfs:
            stmt = (
                select(Candle)
                .where(Candle.symbol == symbol, Candle.timeframe == tf.lower())
                .order_by(desc(Candle.timestamp))
                .limit(limit_per_tf)
            )
            records = list(db.scalars(stmt).all())
            records.reverse()
            timeframe_candles[tf] = records

        response = self.analyze_multi_timeframe(
            symbol=symbol,
            timeframe_candles=timeframe_candles,
            lookback=lookback,
            tolerance_percent=tolerance_percent,
        )

        if persist:
            for tf, analysis in response.timeframes.items():
                if analysis.swing_points:
                    self.structure_engine.persist_structure_events(
                        db=db,
                        symbol=symbol,
                        timeframe=tf,
                        swings=analysis.swing_points,
                    )

        return response

    def evaluate_alignment(
        self,
        sorted_tfs: List[str],
        results: Dict[str, StructureAnalysisResponse],
    ) -> tuple[MultiTimeframeAlignment, float]:
        """Evaluate MTF confluence and alignment score."""
        if not sorted_tfs or not results:
            return MultiTimeframeAlignment.MIXED, 0.0

        trends = [results[tf].trend for tf in sorted_tfs if tf in results]
        strengths = [results[tf].trend_strength for tf in sorted_tfs if tf in results]

        avg_strength = sum(strengths) / len(strengths) if strengths else 0.5

        # All bullish
        if all(t == TrendDirection.BULLISH for t in trends):
            score = round(min(1.0, 0.8 + (avg_strength * 0.2)), 2)
            return MultiTimeframeAlignment.BULLISH_ALIGNED, score

        # All bearish
        if all(t == TrendDirection.BEARISH for t in trends):
            score = round(min(1.0, 0.8 + (avg_strength * 0.2)), 2)
            return MultiTimeframeAlignment.BEARISH_ALIGNED, score

        # HTF vs LTF pullback checks
        htf = sorted_tfs[0]
        ltf = sorted_tfs[-1]
        htf_trend = results[htf].trend
        ltf_trend = results[ltf].trend

        if htf_trend == TrendDirection.BULLISH and ltf_trend == TrendDirection.BEARISH:
            return MultiTimeframeAlignment.HTF_BULLISH_PULLBACK, 0.70

        if htf_trend == TrendDirection.BEARISH and ltf_trend == TrendDirection.BULLISH:
            return MultiTimeframeAlignment.HTF_BEARISH_PULLBACK, 0.70

        return MultiTimeframeAlignment.MIXED, round(max(0.1, avg_strength * 0.4), 2)

    def _build_summary(
        self,
        symbol: str,
        primary_tf: str,
        primary_trend: TrendDirection,
        sorted_tfs: List[str],
        results: Dict[str, StructureAnalysisResponse],
        alignment: MultiTimeframeAlignment,
    ) -> str:
        """Construct a clear human-readable multi-timeframe structural summary."""
        tf_summaries = []
        for tf in sorted_tfs:
            if tf in results:
                r = results[tf]
                tf_summaries.append(f"{tf}: {r.trend.value} (Strength: {r.trend_strength:.2f})")

        tfs_text = ", ".join(tf_summaries)

        if alignment == MultiTimeframeAlignment.BULLISH_ALIGNED:
            return (
                f"{symbol} demonstrates FULL BULLISH ALIGNMENT across all monitored timeframes [{tfs_text}]. "
                f"Higher Highs & Higher Lows confirmed on HTF ({primary_tf}). Favorable for long setups."
            )
        elif alignment == MultiTimeframeAlignment.BEARISH_ALIGNED:
            return (
                f"{symbol} demonstrates FULL BEARISH ALIGNMENT across all monitored timeframes [{tfs_text}]. "
                f"Lower Highs & Lower Lows confirmed on HTF ({primary_tf}). Favorable for short setups."
            )
        elif alignment == MultiTimeframeAlignment.HTF_BULLISH_PULLBACK:
            return (
                f"{symbol} is in a primary HTF BULLISH trend ({primary_tf}) with an active LTF pullback/discount retracement [{tfs_text}]. "
                f"Watch for bullish reversal confirmation at key support levels."
            )
        elif alignment == MultiTimeframeAlignment.HTF_BEARISH_PULLBACK:
            return (
                f"{symbol} is in a primary HTF BEARISH trend ({primary_tf}) with an active LTF pullback/premium retracement [{tfs_text}]. "
                f"Watch for bearish reversal confirmation at key resistance levels."
            )
        else:
            return (
                f"{symbol} market structure is MIXED/RANGING [{tfs_text}]. "
                f"Market lacks full multi-timeframe directional consensus."
            )
