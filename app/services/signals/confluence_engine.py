"""Unified Multi-Strategy Consensus and Confluence Engine."""

from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from app.core.config import settings
from app.core.logging import logger
from app.schemas.candle import CandleBase
from app.schemas.news import NewsBlackoutCheckResponse
from app.schemas.signal import (
    RiskParameters,
    ScoreBreakdown,
    SignalDirection,
    SignalResponse,
    SignalStatus,
)
from app.services.indicators import IndicatorService
from app.services.liquidity import LiquidityService
from app.services.news import NewsFilterEngine
from app.services.signals.evaluators import (
    ConsensusFilter,
    LiquiditySMCConsensusEvaluator,
    MomentumIndicatorConsensusEvaluator,
    PillarEvaluation,
    PriceActionConsensusEvaluator,
    StructureConsensusEvaluator,
)
from app.services.signals.risk_manager import RiskManager
from app.services.structure import MultiTimeframeStructureEngine


class ConfluenceEngine:
    """Unified Multi-Strategy Consensus Engine synthesizing SMC Structure, Liquidity, Indicators, and Price Action.
    
    Evaluates individual analytical sub-modules together for any instrument and produces
    exactly one high-conviction composite trade signal with strict directional agreement filtering.
    """

    def __init__(
        self,
        liquidity_service: Optional[LiquidityService] = None,
        mtf_engine: Optional[MultiTimeframeStructureEngine] = None,
        indicator_service: Optional[IndicatorService] = None,
        news_filter: Optional[NewsFilterEngine] = None,
        risk_manager: Optional[RiskManager] = None,
        min_score_threshold: Optional[float] = None,
    ):
        self.liquidity_service = liquidity_service or LiquidityService()
        self.mtf_engine = mtf_engine or MultiTimeframeStructureEngine()
        self.indicator_service = indicator_service or IndicatorService()
        self.news_filter = news_filter or NewsFilterEngine()
        self.risk_manager = risk_manager or RiskManager()
        self.min_score_threshold = min_score_threshold or settings.MIN_SETUP_SCORE

        # Sub-strategy modular evaluators
        self.structure_evaluator = StructureConsensusEvaluator()
        self.liquidity_evaluator = LiquiditySMCConsensusEvaluator()
        self.indicator_evaluator = MomentumIndicatorConsensusEvaluator()
        self.price_action_evaluator = PriceActionConsensusEvaluator()
        self.consensus_filter = ConsensusFilter(min_score_threshold=self.min_score_threshold)

    @staticmethod
    def generate_fingerprint(
        symbol: str,
        timeframe: str,
        direction: SignalDirection,
        entry_price: float,
        stop_loss: float,
        timestamp: datetime,
    ) -> str:
        """Generate unique SHA-256 fingerprint for deduplication."""
        ts_str = timestamp.isoformat()
        payload = f"{symbol}_{timeframe}_{direction.value}_{entry_price:.5f}_{stop_loss:.5f}_{ts_str}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def evaluate(
        self,
        symbol: str = "EUR/USD",
        candles_dict: Optional[Dict[str, Sequence[Union[CandleBase, Any]]]] = None,
        candles_primary: Optional[Sequence[Union[CandleBase, Any]]] = None,
        timeframe: str = "1h",
        candles_4h: Optional[Sequence[Union[CandleBase, Any]]] = None,
        candles_15m: Optional[Sequence[Union[CandleBase, Any]]] = None,
        news_check: Optional[NewsBlackoutCheckResponse] = None,
        account_balance: float = 10000.0,
        risk_percent: float = 0.5,
    ) -> SignalResponse:
        """Run all analytical models together on candle datasets and produce a single composite SignalResponse."""
        # 1. Resolve primary and multi-timeframe candle datasets
        if candles_dict:
            c_prim = candles_dict.get(timeframe) or candles_dict.get("1h") or list(candles_dict.values())[0]
            c_4h = candles_dict.get("4h") or candles_4h
            c_15m = candles_dict.get("15m") or candles_15m
        else:
            c_prim = candles_primary or []
            c_4h = candles_4h
            c_15m = candles_15m

        if not c_prim:
            now_utc = datetime.now(timezone.utc)
            return SignalResponse(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.WAIT,
                setup_score=0.0,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                fingerprint=self.generate_fingerprint(symbol, timeframe, SignalDirection.WAIT, 0.0, 0.0, now_utc),
                reasons=["No candle dataset provided for analysis."],
                status=SignalStatus.ACTIVE,
                timestamp=now_utc,
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
            )

        # 2. Check News Blackout (Immediate rejection if active)
        if news_check and news_check.is_blackout:
            now_utc = datetime.now(timezone.utc)
            reasons = [
                f"NEWS BLACKOUT ACTIVE: {news_check.reason}",
                "Trading suspended to prevent slippage during high-impact economic releases.",
            ]
            breakdown = ScoreBreakdown(
                structure_score=0.0,
                liquidity_score=0.0,
                indicators_score=0.0,
                price_action_score=0.0,
                total_score=0.0,
                is_qualified=False,
            )
            return SignalResponse(
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.WAIT,
                setup_score=0.0,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                fingerprint=self.generate_fingerprint(symbol, timeframe, SignalDirection.WAIT, 0.0, 0.0, now_utc),
                reasons=reasons,
                status=SignalStatus.ACTIVE,
                timestamp=now_utc,
                score_breakdown=breakdown,
            )

        # 3. Concurrent Multi-Strategy Analytical Pipeline
        # Sub-Module A: SMC Advanced Structure & Breakouts
        structure_analysis = self.liquidity_service.analyze_liquidity_and_structure(
            candles=c_prim,
            symbol=symbol,
            timeframe=timeframe,
        )

        # Sub-Module B: Momentum Indicators & Price Action Patterns
        indicator_analysis = self.indicator_service.analyze_indicators(
            candles=c_prim,
            symbol=symbol,
            timeframe=timeframe,
        )

        # Sub-Module C: Multi-Timeframe (MTF) Alignment
        mtf_analysis = None
        if c_4h and c_15m:
            mtf_analysis = self.mtf_engine.analyze_multi_timeframe(
                symbol=symbol,
                timeframe_candles={
                    "4h": c_4h,
                    "1h": c_prim if timeframe == "1h" else c_4h,
                    "15m": c_15m,
                },
            )

        current_price = indicator_analysis.current_price
        latest_ts = indicator_analysis.timestamp

        # 4. Multi-Pillar Sub-Evaluations for BUY
        buy_evals = {
            "structure": self.structure_evaluator.evaluate(SignalDirection.BUY, structure_analysis, mtf_analysis),
            "liquidity": self.liquidity_evaluator.evaluate(SignalDirection.BUY, structure_analysis, current_price),
            "indicators": self.indicator_evaluator.evaluate(SignalDirection.BUY, indicator_analysis),
            "price_action": self.price_action_evaluator.evaluate(SignalDirection.BUY, indicator_analysis),
        }
        buy_score, buy_breakdown, buy_reasons, buy_fatal = self.consensus_filter.synthesize(
            buy_evals, SignalDirection.BUY
        )

        # Multi-Pillar Sub-Evaluations for SELL
        sell_evals = {
            "structure": self.structure_evaluator.evaluate(SignalDirection.SELL, structure_analysis, mtf_analysis),
            "liquidity": self.liquidity_evaluator.evaluate(SignalDirection.SELL, structure_analysis, current_price),
            "indicators": self.indicator_evaluator.evaluate(SignalDirection.SELL, indicator_analysis),
            "price_action": self.price_action_evaluator.evaluate(SignalDirection.SELL, indicator_analysis),
        }
        sell_score, sell_breakdown, sell_reasons, sell_fatal = self.consensus_filter.synthesize(
            sell_evals, SignalDirection.SELL
        )

        # 5. Determine Composite Direction & Filter Directional Conflict
        if buy_score >= sell_score and buy_score >= self.min_score_threshold and not buy_fatal:
            direction = SignalDirection.BUY
            total_score = buy_score
            breakdown = buy_breakdown
            reasons = buy_reasons
        elif sell_score > buy_score and sell_score >= self.min_score_threshold and not sell_fatal:
            direction = SignalDirection.SELL
            total_score = sell_score
            breakdown = sell_breakdown
            reasons = sell_reasons
        else:
            direction = SignalDirection.WAIT
            total_score = max(buy_score, sell_score)
            breakdown = buy_breakdown if buy_score >= sell_score else sell_breakdown
            
            conflict_note = ""
            if buy_fatal or sell_fatal:
                conflict_note = "Directional contradiction between pillars detected. "
            
            reasons = [
                f"MARKET BIAS: NEUTRAL / WAIT ({conflict_note}Score: {total_score:.1f}/100, Min required: {self.min_score_threshold:.1f}).",
                f"Market State: {structure_analysis.market_state}",
                f"Technical Bias: {indicator_analysis.confluence_bias} (Score: {indicator_analysis.confluence_score:+.0f})",
            ]
            # Include best catalysts as context
            best_catalysts = buy_reasons if buy_score >= sell_score else sell_reasons
            for c in best_catalysts[:3]:
                if not c.startswith("MARKET BIAS"):
                    reasons.append(f"Observation: {c}")

        # 6. Risk Management & SMC Geometric Levels
        risk_params: Optional[RiskParameters] = None
        if direction in (SignalDirection.BUY, SignalDirection.SELL):
            supp_low = structure_analysis.base_structure.key_support
            res_high = structure_analysis.base_structure.key_resistance

            risk_params = self.risk_manager.calculate_trade_risk(
                symbol=symbol,
                direction=direction,
                entry_price=current_price,
                atr_value=indicator_analysis.atr.atr_value,
                key_support_low=supp_low,
                key_resistance_high=res_high,
                account_balance=account_balance,
                risk_percent=risk_percent,
            )
            entry_p = risk_params.entry_price
            sl_p = risk_params.stop_loss
            tp1_p = risk_params.take_profit_1
            tp2_p = risk_params.take_profit_2
            rr_p = risk_params.risk_reward_tp1
        else:
            entry_p = current_price
            sl_p = current_price
            tp1_p = current_price
            tp2_p = current_price
            rr_p = 0.0

        fingerprint = self.generate_fingerprint(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            entry_price=entry_p,
            stop_loss=sl_p,
            timestamp=latest_ts,
        )

        return SignalResponse(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            setup_score=total_score,
            entry_price=entry_p,
            stop_loss=sl_p,
            take_profit_1=tp1_p,
            take_profit_2=tp2_p,
            risk_reward=rr_p,
            fingerprint=fingerprint,
            reasons=reasons,
            status=SignalStatus.ACTIVE,
            timestamp=latest_ts,
            score_breakdown=breakdown,
            risk_parameters=risk_params,
        )
