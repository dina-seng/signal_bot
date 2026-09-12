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
from app.schemas.structure import TrendDirection 
from app.services.structure.ltf_confirmation import LTFConfirmationEngine
from app.services.indicators import IndicatorService
from app.services.liquidity import LiquidityService
from app.services.news import NewsFilterEngine
from app.services.market_data import (
    check_data_staleness,
    ensure_utc_datetime,
    filter_closed_candles,
    log_latest_candle,
)
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
from app.services.strategies.base import StrategyResult


class ConfluenceEngine:
    """Unified Multi-Strategy Consensus Engine.

    Delegates analytical scoring to the pluggable ``StrategyManager``
    while retaining ownership of:
      - Data ingestion & validation (staleness, closed-candle filtering)
      - News blackout checks
      - Risk management & position sizing
      - Fingerprint generation & SignalResponse assembly

    Backward-compatible: ``evaluate()`` still returns a single
    ``SignalResponse`` (the best qualifying signal).  Use
    ``evaluate_multi()`` to receive all qualifying signals.
    """

    def __init__(
        self,
        liquidity_service: Optional[LiquidityService] = None,
        mtf_engine: Optional[MultiTimeframeStructureEngine] = None,
        indicator_service: Optional[IndicatorService] = None,
        news_filter: Optional[NewsFilterEngine] = None,
        risk_manager: Optional[RiskManager] = None,
        min_score_threshold: Optional[float] = None,
        strategy_manager: Optional[StrategyManager] = None,
    ):
        self.liquidity_service = liquidity_service or LiquidityService()
        self.mtf_engine = mtf_engine or MultiTimeframeStructureEngine()
        self.indicator_service = indicator_service or IndicatorService()
        self.news_filter = news_filter or NewsFilterEngine()
        self.risk_manager = risk_manager or RiskManager()
        self.min_score_threshold = min_score_threshold or settings.MIN_SETUP_SCORE

        self.ltf_confirmation_engine = LTFConfirmationEngine()

        # Sub-strategy modular evaluators (kept for backward compat with ScoringEngine)
        self.structure_evaluator = StructureConsensusEvaluator()
        self.liquidity_evaluator = LiquiditySMCConsensusEvaluator()
        self.indicator_evaluator = MomentumIndicatorConsensusEvaluator()
        self.price_action_evaluator = PriceActionConsensusEvaluator()
        self.consensus_filter = ConsensusFilter(min_score_threshold=self.min_score_threshold)

        # Pluggable strategy manager (lazy import to avoid circular dependency)
        if strategy_manager is not None:
            self.strategy_manager = strategy_manager
        else:
            from app.services.strategies.strategy_manager import StrategyManager
            self.strategy_manager = StrategyManager()

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
        ts_utc = ensure_utc_datetime(timestamp) or datetime.now(timezone.utc)
        ts_str = ts_utc.isoformat()
        payload = f"{symbol}_{timeframe}_{direction.value}_{entry_price:.5f}_{stop_loss:.5f}_{ts_str}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Pre-flight checks (shared by evaluate & evaluate_multi)
    # ------------------------------------------------------------------

    def _preflight(
        self,
        symbol: str,
        timeframe: str,
        candles_dict: Optional[Dict[str, Sequence[Union[CandleBase, Any]]]] = None,
        candles_primary: Optional[Sequence[Union[CandleBase, Any]]] = None,
        candles_4h: Optional[Sequence[Union[CandleBase, Any]]] = None,
        candles_15m: Optional[Sequence[Union[CandleBase, Any]]] = None,
        news_check: Optional[NewsBlackoutCheckResponse] = None,
    ) -> Tuple[
        Optional[SignalResponse],      # early-exit response (None = proceed)
        List[Any], Optional[List[Any]], Optional[List[Any]],  # c_prim, c_4h, c_15m
    ]:
        """Run data-validation and news-blackout checks.

        Returns ``(early_exit_response, c_prim, c_4h, c_15m)``.
        If ``early_exit_response`` is not None, the caller should return it immediately.
        """
        # 1. Resolve primary and multi-timeframe candle datasets
        if candles_dict:
            raw_prim = candles_dict.get(timeframe) or candles_dict.get("1h") or list(candles_dict.values())[0]
            raw_4h = candles_dict.get("4h") or candles_4h
            raw_15m = candles_dict.get("15m") or candles_15m
        else:
            raw_prim = candles_primary or []
            raw_4h = candles_4h
            raw_15m = candles_15m

        # Filter for verified closed candles
        c_prim = filter_closed_candles(raw_prim, timeframe=timeframe) if raw_prim else []
        c_4h = filter_closed_candles(raw_4h, timeframe="4h") if raw_4h else None
        c_15m = filter_closed_candles(raw_15m, timeframe="15m") if raw_15m else None

        if not c_prim:
            now_utc = datetime.now(timezone.utc)
            return (
                SignalResponse(
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
                    reasons=["No closed verified candle dataset provided for analysis."],
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
                ),
                [], None, None,
            )

        # 2. Check Data Staleness & Explicit Latest Candle Logging
        staleness = check_data_staleness(c_prim, symbol=symbol, timeframe=timeframe)
        latest_c = c_prim[-1]
        log_latest_candle(
            latest_c,
            symbol=symbol,
            timeframe=timeframe,
            context="SIGNAL EVALUATION",
            is_fresh=not staleness.is_stale,
        )
        
        # ✅ HARD BLOCK: Refuse to analyze if data is too old
        max_allowed_age = 2.0 if timeframe in ["1h", "4h"] else 1.0
        
        if staleness.is_stale and staleness.age_hours > max_allowed_age:
            now_utc = datetime.now(timezone.utc)
            return (
                SignalResponse(
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
                    reasons=[
                        f"🚫 DATA TOO STALE: Last closed candle is {staleness.age_hours:.1f} hours old.",
                        "Analysis aborted to prevent trading on outdated market conditions. Please sync fresh data."
                    ],
                    status=SignalStatus.ACTIVE,
                    timestamp=now_utc,
                    score_breakdown=ScoreBreakdown(
                        structure_score=0.0, liquidity_score=0.0, indicators_score=0.0,
                        price_action_score=0.0, total_score=0.0, is_qualified=False,
                    ),
                ),
                c_prim, c_4h, c_15m,
            )

        if staleness.is_stale:
            logger.warning(staleness.message)

        # 3. Check News Blackout / News Data Unavailable Fail-Safe
        if news_check and (news_check.is_blackout or not news_check.trading_allowed or news_check.is_news_unavailable or news_check.is_fail_safe):
            now_utc = datetime.now(timezone.utc)
            if news_check.is_blackout:
                prefix = "NEWS BLACKOUT ACTIVE:"
            elif news_check.is_news_unavailable or news_check.is_fail_safe:
                prefix = "NEWS DATA UNAVAILABLE:"
            else:
                prefix = "NEWS PROTECTION ACTIVE:"

            reasons = [
                f"{prefix} {news_check.reason}",
                "Trading suspended to prevent slippage or capital loss during high-impact economic releases or unverified news data.",
            ]
            breakdown = ScoreBreakdown(
                structure_score=0.0,
                liquidity_score=0.0,
                indicators_score=0.0,
                price_action_score=0.0,
                total_score=0.0,
                is_qualified=False,
            )
            return (
                SignalResponse(
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
                ),
                c_prim, c_4h, c_15m,
            )

        return None, c_prim, c_4h, c_15m

    # ------------------------------------------------------------------
    # Shared data preparation
    # ------------------------------------------------------------------

    def _prepare_market_data(
        self,
        symbol: str,
        timeframe: str,
        c_prim: Sequence[Any],
        c_4h: Optional[Sequence[Any]],
        c_15m: Optional[Sequence[Any]],
    ) -> Tuple[Any, Any, Optional[Any]]:
        """Run structure, indicator, and MTF analysis on candle data.

        Returns ``(structure_analysis, indicator_analysis, mtf_analysis)``.
        """
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
                    timeframe: c_prim,
                    "15m": c_15m,
                },
            )

        return structure_analysis, indicator_analysis, mtf_analysis

    # ------------------------------------------------------------------
    # Build a SignalResponse from a StrategyResult
    # ------------------------------------------------------------------

    def _build_signal_response(
        self,
        result: StrategyResult,
        symbol: str,
        timeframe: str,
        indicator_analysis: Any,
        structure_analysis: Any,
        account_balance: float,
        risk_percent: float,
    ) -> SignalResponse:
        """Convert a ``StrategyResult`` into a full ``SignalResponse`` with risk management."""
        current_price = indicator_analysis.current_price
        latest_ts = indicator_analysis.timestamp
        direction = result.direction

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
            setup_score=result.score,
            entry_price=entry_p,
            stop_loss=sl_p,
            take_profit_1=tp1_p,
            take_profit_2=tp2_p,
            risk_reward=rr_p,
            fingerprint=fingerprint,
            reasons=result.reasons,
            status=SignalStatus.ACTIVE,
            timestamp=latest_ts,
            score_breakdown=result.score_breakdown,
            risk_parameters=risk_params,
            strategy_name=result.strategy_name,
        )

    # ------------------------------------------------------------------
    # Public API: single-signal (backward-compatible)
    # ------------------------------------------------------------------

    def evaluate(
        self,
        symbol: str = "XAU/USD",
        candles_dict: Optional[Dict[str, Sequence[Union[CandleBase, Any]]]] = None,
        candles_primary: Optional[Sequence[Union[CandleBase, Any]]] = None,
        timeframe: str = "1h",
        candles_4h: Optional[Sequence[Union[CandleBase, Any]]] = None,
        candles_15m: Optional[Sequence[Union[CandleBase, Any]]] = None,
        news_check: Optional[NewsBlackoutCheckResponse] = None,
        account_balance: float = 10000.0,
        risk_percent: float = 0.5,
    ) -> SignalResponse:
        """Run all strategies and return the single best qualifying SignalResponse.

        Fully backward-compatible with the original single-signal contract.
        """
        signals = self.evaluate_multi(
            symbol=symbol,
            candles_dict=candles_dict,
            candles_primary=candles_primary,
            timeframe=timeframe,
            candles_4h=candles_4h,
            candles_15m=candles_15m,
            news_check=news_check,
            account_balance=account_balance,
            risk_percent=risk_percent,
        )

        # Return the best (highest-scoring actionable) signal, or the first WAIT
        actionable = [s for s in signals if s.direction in (SignalDirection.BUY, SignalDirection.SELL)]
        if actionable:
            actionable.sort(key=lambda s: s.setup_score, reverse=True)
            return actionable[0]
        return signals[0]

    # ------------------------------------------------------------------
    # Public API: multi-signal (new)
    # ------------------------------------------------------------------

    def evaluate_multi(
        self,
        symbol: str = "XAU/USD",
        candles_dict: Optional[Dict[str, Sequence[Union[CandleBase, Any]]]] = None,
        candles_primary: Optional[Sequence[Union[CandleBase, Any]]] = None,
        timeframe: str = "1h",
        candles_4h: Optional[Sequence[Union[CandleBase, Any]]] = None,
        candles_15m: Optional[Sequence[Union[CandleBase, Any]]] = None,
        news_check: Optional[NewsBlackoutCheckResponse] = None,
        account_balance: float = 10000.0,
        risk_percent: float = 0.5,
    ) -> List[SignalResponse]:
        """Run all strategies and return a SignalResponse per strategy.

        Each strategy that scores ≥ threshold produces an independent signal.
        Strategies that score below threshold produce a WAIT signal.
        """
        # Pre-flight checks
        early_exit, c_prim, c_4h, c_15m = self._preflight(
            symbol=symbol,
            timeframe=timeframe,
            candles_dict=candles_dict,
            candles_primary=candles_primary,
            candles_4h=candles_4h,
            candles_15m=candles_15m,
            news_check=news_check,
        )
        if early_exit is not None:
            return [early_exit]

        # Prepare shared market data
        structure_analysis, indicator_analysis, mtf_analysis = self._prepare_market_data(
            symbol=symbol,
            timeframe=timeframe,
            c_prim=c_prim,
            c_4h=c_4h,
            c_15m=c_15m,
        )

        # Run all strategies
        strategy_results: List[StrategyResult] = self.strategy_manager.run_all_strategies(
            symbol=symbol,
            timeframe=timeframe,
            candles=c_prim,
            indicators=indicator_analysis,
            structure=structure_analysis,
            mtf=mtf_analysis,
            candles_15m=c_15m,
        )

        # Build a SignalResponse per strategy result
        signals: List[SignalResponse] = []
        for result in strategy_results:
            sig = self._build_signal_response(
                result=result,
                symbol=symbol,
                timeframe=timeframe,
                indicator_analysis=indicator_analysis,
                structure_analysis=structure_analysis,
                account_balance=account_balance,
                risk_percent=risk_percent,
            )
            signals.append(sig)

        # Ensure at least one result
        if not signals:
            now_utc = datetime.now(timezone.utc)
            signals.append(SignalResponse(
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
                reasons=["No strategy produced a result."],
                status=SignalStatus.ACTIVE,
                timestamp=now_utc,
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0, liquidity_score=0.0, indicators_score=0.0,
                    price_action_score=0.0, total_score=0.0, is_qualified=False,
                ),
            ))

        return signals
