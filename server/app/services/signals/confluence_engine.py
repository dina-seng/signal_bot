"""Unified Multi-Strategy Consensus and Confluence Engine."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING, Tuple, Union

if TYPE_CHECKING:
    from app.services.strategies.strategy_manager import StrategyManager

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
from app.services.market_data.symbols import target_account_for_symbol
from app.services.signals.evaluators import (
    ConsensusFilter,
    LiquiditySMCConsensusEvaluator,
    MomentumIndicatorConsensusEvaluator,
    PillarEvaluation,
    PriceActionConsensusEvaluator,
    StructureConsensusEvaluator,
)
from app.services.signals.path_validator import PathValidator
from app.services.signals.risk_engine import RiskEngine
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
        risk_engine: Optional[RiskEngine] = None,
        min_score_threshold: Optional[float] = None,
        strategy_manager: Optional["StrategyManager"] = None,
    ):
        self.liquidity_service = liquidity_service or LiquidityService()
        self.mtf_engine = mtf_engine or MultiTimeframeStructureEngine()
        self.indicator_service = indicator_service or IndicatorService()
        self.news_filter = news_filter or NewsFilterEngine()
        # The Risk Engine is the only SL/TP/lot calculator in the pipeline.
        self.risk_engine = risk_engine or RiskEngine()
        self.path_validator = PathValidator()
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
        strategy_name: Optional[str] = None,
    ) -> str:
        """Generate deterministic SHA-256 fingerprint for deduplication based on closed candle timestamp."""
        ts_utc = ensure_utc_datetime(timestamp)
        if ts_utc is None:
            raise ValueError("Deterministic fingerprint requires a valid closed candle timestamp, never None")
        ts_str = ts_utc.isoformat()
        strat_str = f"_{strategy_name}" if strategy_name else ""
        payload = f"{symbol}_{timeframe}_{direction.value}_{entry_price:.5f}_{stop_loss:.5f}_{ts_str}{strat_str}"
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
        as_of: Optional[datetime] = None,
        backtest_mode: bool = False,
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

        # Filter for verified closed candles (relative to as_of if specified)
        c_prim = filter_closed_candles(raw_prim, timeframe=timeframe, as_of=as_of) if raw_prim else []
        c_4h = filter_closed_candles(raw_4h, timeframe="4h", as_of=as_of) if raw_4h else None
        c_15m = filter_closed_candles(raw_15m, timeframe="15m", as_of=as_of) if raw_15m else None

        if not c_prim:
            ref_ts = ensure_utc_datetime(as_of) or datetime.now(timezone.utc)
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
                    fingerprint=self.generate_fingerprint(symbol, timeframe, SignalDirection.WAIT, 0.0, 0.0, ref_ts),
                    reasons=["No closed verified candle dataset provided for analysis."],
                    status=SignalStatus.ACTIVE,
                    timestamp=ref_ts,
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
        staleness = check_data_staleness(c_prim, symbol=symbol, timeframe=timeframe, as_of=as_of)
        latest_c = c_prim[-1]
        latest_c_raw_ts = getattr(latest_c, "timestamp", None) or (latest_c.get("timestamp") if isinstance(latest_c, dict) else None)
        latest_candle_ts = ensure_utc_datetime(latest_c_raw_ts)

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
            sig_ts = latest_candle_ts or ensure_utc_datetime(as_of) or datetime.now(timezone.utc)
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
                    fingerprint=self.generate_fingerprint(symbol, timeframe, SignalDirection.WAIT, 0.0, 0.0, sig_ts),
                    reasons=[
                        f"🚫 DATA TOO STALE: Last closed candle is {staleness.age_hours:.1f} hours old.",
                        "Analysis aborted to prevent trading on outdated market conditions. Please sync fresh data."
                    ],
                    status=SignalStatus.ACTIVE,
                    timestamp=sig_ts,
                    score_breakdown=ScoreBreakdown(
                        structure_score=0.0, liquidity_score=0.0, indicators_score=0.0,
                        price_action_score=0.0, total_score=0.0, is_qualified=False,
                    ),
                ),
                c_prim, c_4h, c_15m,
            )

        if staleness.is_stale:
            logger.warning(staleness.message)

        # 3. Check News Blackout / News Data Unavailable Fail-Safe (bypassed in backtest_mode)
        if not backtest_mode and news_check and (news_check.is_blackout or not news_check.trading_allowed or news_check.is_news_unavailable or news_check.is_fail_safe):
            sig_ts = latest_candle_ts or ensure_utc_datetime(as_of) or datetime.now(timezone.utc)
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
                    fingerprint=self.generate_fingerprint(symbol, timeframe, SignalDirection.WAIT, 0.0, 0.0, sig_ts),
                    reasons=reasons,
                    status=SignalStatus.ACTIVE,
                    timestamp=sig_ts,
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
        htf_trend: Optional[str] = None,
        candles_15m: Optional[Sequence[Any]] = None,
    ) -> SignalResponse:
        """Convert a ``StrategyResult`` into a ``SignalResponse``.

        The Signal Engine contributes the entry only; SL/TP/lot come from the
        Risk Engine actor below.
        """
        current_price = indicator_analysis.current_price
        latest_ts = indicator_analysis.timestamp
        direction = result.direction
        reasons = list(result.reasons)  # Mutable copy for path validation notes
        warnings: List[str] = []

        # Propagate strategy metadata (momentum indicators, provenance) and the
        # deterministic account routing target to every downstream consumer
        # (Telegram alerts, signal API, dashboard Confluence Matrix).
        result_meta: Dict[str, Any] = dict(result.metadata or {})
        result_meta["target_account"] = (
            str(result_meta.get("target_account") or target_account_for_symbol(symbol)).upper()
        )

        # 7. RISK ENGINE ACTOR — entry-only hand-off.
        # The Signal Engine has found `resolved_entry`; everything below is
        # calculated by the Risk Engine, never by the Signal Engine.
        risk_params: Optional[RiskParameters] = None

        if direction in (SignalDirection.BUY, SignalDirection.SELL):
            # Local import avoids a signals <-> paper_trading package import cycle.
            from app.services.paper_trading.broker_spec import get_broker_spec

            limit_entry = result_meta.get("ideal_entry")
            resolved_entry = (
                float(limit_entry)
                if result_meta.get("entry_mode") == "limit_zone" and limit_entry
                else current_price
            )

            levels = self.risk_engine.resolve_levels(
                symbol=symbol,
                direction=direction,
                entry_price=resolved_entry,
                timeframe="15m",
                candles=candles_15m,
                balance=account_balance,
                risk_percent=risk_percent,
            )

            pip_size = RiskEngine.get_pip_size(symbol)
            risk_pips = round(levels.sl_distance / pip_size, 1)
            reward_pips_tp1 = round(levels.tp_distance / pip_size, 1)
            rr_tp1 = round(levels.rr_multiple, 2)
            spec = get_broker_spec(settings.BROKER_SPEC)

            risk_params = RiskParameters(
                entry_price=levels.entry_price,
                stop_loss=levels.stop_loss,
                take_profit_1=levels.take_profit_1,
                take_profit_2=levels.take_profit_2,
                risk_pips=risk_pips,
                reward_pips_tp1=reward_pips_tp1,
                reward_pips_tp2=reward_pips_tp1,
                risk_reward_tp1=rr_tp1,
                risk_reward_tp2=rr_tp1,
                account_balance=account_balance,
                risk_percent=levels.risk_percent,
                risk_amount_usd=levels.risk_amount_usd,
                suggested_lot_size=levels.lot_size,
                raw_lot_size=levels.raw_lot_size,
                is_executable=True,
                min_lot_risk_usd=levels.min_lot_risk_usd,
                volume_step=float(spec.lot_step),
            )

            if risk_params is not None:
                # C. 🗺️ PATH VALIDATION (Informational Advisory Warning System)
                sr_zones = getattr(structure_analysis, 'sr_zones', [])
                liquidity_pools = getattr(structure_analysis, 'liquidity_pools', [])
                active_fvgs = getattr(indicator_analysis, 'active_fvgs', [])

                path_result = self.path_validator.validate_trade_path(
                    direction=direction,
                    entry_price=risk_params.entry_price,
                    target_price=risk_params.take_profit_1,
                    sr_zones=sr_zones,
                    active_fvgs=active_fvgs,
                    liquidity_pools=liquidity_pools,
                )

                if not path_result.is_clear:
                    obstacle_price = float(path_result.nearest_obstacle_price or 0.0)
                    obstacle_type = path_result.obstacle_type or "Unknown Obstacle"
                    obstacle_count = getattr(path_result, "obstacle_count", 0) or 1

                    # 🎯 LIQUIDITY EXCEPTION: Equal Highs/Lows are magnets, not walls.
                    is_liquidity_magnet = (
                        "Equal Highs" in obstacle_type or "Equal Lows" in obstacle_type
                    )
                    if is_liquidity_magnet:
                        logger.info(
                            f"🎯 Liquidity Magnet Detected: Allowing TP to target "
                            f"{obstacle_type} at {obstacle_price:.5f}"
                        )
                        reasons.append(
                            f"🎯 Targeting Liquidity Sweep at {obstacle_price:.5f}"
                        )

                    # Calculate projected R:R if TP front-ran the barrier.
                    pip_size = RiskEngine.get_pip_size(symbol)
                    buffer_price = 2.0 * pip_size

                    if direction == SignalDirection.BUY:
                        projected_tp1 = obstacle_price - buffer_price
                        distance_pips = abs(obstacle_price - risk_params.entry_price) / pip_size
                    else:
                        projected_tp1 = obstacle_price + buffer_price
                        distance_pips = abs(risk_params.entry_price - obstacle_price) / pip_size

                    risk_distance = abs(risk_params.entry_price - risk_params.stop_loss)
                    reward_distance = abs(projected_tp1 - risk_params.entry_price)
                    projected_rr = reward_distance / risk_distance if risk_distance > 0 else 0.0

                    is_structural_wall = any(
                        token in obstacle_type for token in ("Zone", "FVG")
                    )
                    if not is_liquidity_magnet and is_structural_wall and projected_rr < 1.0:
                        # Hard gate: buying under resistance / selling into support
                        # with less than 1R of room is not executable.
                        risk_params.is_executable = False
                        rejection_msg = (
                            f"🚫 PATH BLOCK REJECTION: {obstacle_type} at {obstacle_price:.5f} "
                            f"({distance_pips:.1f} pips away). Projected obstacle R:R "
                            f"{projected_rr:.2f} < 1.0."
                        )
                        reasons.append(rejection_msg)
                        # Sentinel consumed by the execution engine.
                        reasons.append("PATH_BLOCK_REJECTION")
                        warnings.append(rejection_msg)
                        logger.warning(rejection_msg)
                    else:
                        # Liquidity magnets and >=1R paths remain advisory only.
                        logger.info(
                            f"⚠️ Path Advisory: {obstacle_type} at {obstacle_price:.5f} "
                            f"({distance_pips:.1f} pips away). Projected R:R: {projected_rr:.2f}."
                        )
                        advisory_msg = (
                            f"⚠️ Path Advisory:\n"
                            f"  • Nearest Obstacle: {obstacle_type} at {obstacle_price:.5f} "
                            f"({distance_pips:.1f} pips away)\n"
                            f"  • Projected Obstacle R:R: {projected_rr:.2f}\n"
                            f"  • Total Path Barriers: {obstacle_count}"
                        )
                        reasons.append(advisory_msg)
                        warnings.append(advisory_msg)

        # 8. Build Final Response
        entry_p = risk_params.entry_price if risk_params else current_price
        sl_p = risk_params.stop_loss if risk_params else current_price
        tp1_p = risk_params.take_profit_1 if risk_params else current_price
        tp2_p = risk_params.take_profit_2 if risk_params else current_price
        rr_p = risk_params.risk_reward_tp1 if risk_params else 0.0

        fingerprint = self.generate_fingerprint(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            entry_price=entry_p,
            stop_loss=sl_p,
            timestamp=latest_ts,
            strategy_name=result.strategy_name,
        )

        regime = "TREND FOLLOWING"

        sig_htf_trend = (
            htf_trend
            or (result.metadata.get("htf_trend") if result.metadata else None)
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
            reasons=reasons,
            warnings=warnings,
            status=SignalStatus.ACTIVE,
            timestamp=latest_ts,
            score_breakdown=result.score_breakdown,
            risk_parameters=risk_params,
            strategy_name=result.strategy_name,
            metadata=result_meta,
            trend_alignment=regime,
            htf_trend=sig_htf_trend,
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
        risk_percent: Optional[float] = None,
        htf_trend: Optional[str] = None,
        as_of: Optional[datetime] = None,
        backtest_mode: bool = False,
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
            htf_trend=htf_trend,
            as_of=as_of,
            backtest_mode=backtest_mode,
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
        risk_percent: Optional[float] = None,
        htf_trend: Optional[str] = None,
        as_of: Optional[datetime] = None,
        backtest_mode: bool = False,
    ) -> List[SignalResponse]:
        """Run all strategies and return a SignalResponse per strategy.

        Each strategy that scores ≥ threshold produces an independent signal.
        Strategies that score below threshold produce a WAIT signal.
        """
        # Single authoritative risk % for the whole signal/execution pipeline.
        risk_percent = risk_percent or settings.MAX_RISK_PERCENT
        logger.debug(
            f"[RISK] {symbol}: signal sizing uses risk={risk_percent:.1f}% "
            f"balance=${account_balance:,.2f} (settings.MAX_RISK_PERCENT)"
        )

        # Pre-flight checks
        early_exit, c_prim, c_4h, c_15m = self._preflight(
            symbol=symbol,
            timeframe=timeframe,
            candles_dict=candles_dict,
            candles_primary=candles_primary,
            candles_4h=candles_4h,
            candles_15m=candles_15m,
            news_check=news_check,
            as_of=as_of,
            backtest_mode=backtest_mode,
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

        # Determine 1H HTF trend context
        current_htf_trend = htf_trend
        if current_htf_trend is None:
            if mtf_analysis is not None and hasattr(mtf_analysis, "timeframes") and "1h" in mtf_analysis.timeframes:
                t = mtf_analysis.timeframes["1h"].trend
                current_htf_trend = t.value if hasattr(t, "value") else str(t).upper()
            elif timeframe == "1h" and structure_analysis is not None and hasattr(structure_analysis, "trend"):
                t = structure_analysis.trend
                current_htf_trend = t.value if hasattr(t, "value") else str(t).upper()
            elif mtf_analysis is not None and hasattr(mtf_analysis, "primary_trend") and mtf_analysis.primary_trend:
                t = mtf_analysis.primary_trend
                current_htf_trend = t.value if hasattr(t, "value") else str(t).upper()
            elif structure_analysis is not None and hasattr(structure_analysis, "trend"):
                t = structure_analysis.trend
                current_htf_trend = t.value if hasattr(t, "value") else str(t).upper()
            else:
                current_htf_trend = "RANGING"

        # Run all strategies
        strategy_results: List[StrategyResult] = self.strategy_manager.run_all_strategies(
            symbol=symbol,
            timeframe=timeframe,
            candles=c_prim,
            indicators=indicator_analysis,
            structure=structure_analysis,
            mtf=mtf_analysis,
            candles_15m=c_15m,
            htf_trend=current_htf_trend,
        )

        # 15m candles are the Risk Engine's sole source for structural SL.
        risk_candles = c_15m if c_15m else (c_prim if timeframe == "15m" else None)

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
                htf_trend=current_htf_trend,
                candles_15m=risk_candles,
            )
            signals.append(sig)

        # Ensure at least one result
        if not signals:
            latest_c = c_prim[-1] if c_prim else None
            latest_c_raw_ts = (getattr(latest_c, "timestamp", None) or (latest_c.get("timestamp") if isinstance(latest_c, dict) else None)) if latest_c else None
            sig_ts = ensure_utc_datetime(latest_c_raw_ts) or datetime(2026, 1, 1, tzinfo=timezone.utc)
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
                fingerprint=self.generate_fingerprint(symbol, timeframe, SignalDirection.WAIT, 0.0, 0.0, sig_ts),
                reasons=["No strategy produced a result."],
                status=SignalStatus.ACTIVE,
                timestamp=sig_ts,
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0, liquidity_score=0.0, indicators_score=0.0,
                    price_action_score=0.0, total_score=0.0, is_qualified=False,
                ),
            ))

        return signals
