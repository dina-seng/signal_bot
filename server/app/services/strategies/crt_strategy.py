"""Strategy D (Candle Range Theory) — AMD Accumulation, Manipulation, Distribution Strategy.

A modular, standalone strategy based on the institutional AMD framework:
- Accumulation: Benchmark range set by a completed higher timeframe candle (e.g. 1H).
- Manipulation: Liquidity sweep breaching the range boundary on a lower timeframe (e.g. 15m)
  by at least `min_manip_pct` depth and satisfying minimum ATR/spread threshold.
- Distribution: Confirmed when lower timeframe candle(s) close back inside the benchmark range
  with displacement and market structure shift (MSS).

Target & Risk Management:
- Entry: Retracement entry zone (FVG/OB from displacement leg, fallback 50% equilibrium).
- Stop Loss: Extreme manipulation wick plus buffer, extended beyond any adjacent liquidity pool.
- Take Profit: CRT-native targets (TP1 = range midpoint, TP2 = range high/low),
  capped before opposing unmitigated FVG or Order Block via PathValidator.
"""

from datetime import datetime, time as dtime, timedelta, timezone
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.logging import logger
from app.schemas.indicators import FVGType, IndicatorAnalysisResponse
from app.schemas.liquidity import (
    AdvancedStructureAnalysisResponse,
    BOSCHOCHType,
    LiquidityEventType,
    ZoneType,
)
from app.schemas.signal import ScoreBreakdown, SignalDirection
from app.schemas.structure import CRTAnalysis, MultiTimeframeStructureResponse
from app.services.market_data.symbols import get_instrument_spec, UnknownSymbolError
from app.services.strategies.base import BaseStrategy, StrategyResult
from app.services.structure.crt_analyzer import CRTAnalyzer, _get_candle_ts, _get_candle_val

# CRT Modular Subsystems
from app.services.strategies.crt.daily_bias import calculate_daily_bias, classify_swept_level
from app.services.strategies.crt.targets import calculate_crt_targets, CRTTargetPlan
from app.services.strategies.crt.entry import calculate_retracement_entry, RetracementEntry
from app.services.strategies.crt.confirmation import verify_ltf_confirmation, LTFConfirmationResult
from app.services.strategies.crt.tiers import determine_quality_tier, QualityTierResult
from app.services.strategies.crt.lifecycle import evaluate_lifecycle_state, CRTState, StateTransitionResult


def _norm_trend(x: Any) -> str:
    """Normalize trend indicator to standard uppercase string: BULLISH, BEARISH, or RANGING."""
    if x is None:
        return "RANGING"
    if hasattr(x, "value"):
        val = str(x.value).strip().upper()
    else:
        val = str(x).strip().upper()
    if val in ("BULLISH", "BEARISH"):
        return val
    return "RANGING"


def is_in_trading_session(dt: datetime) -> Tuple[bool, str]:
    """Check if the datetime falls within allowed institutional trading sessions in New York time.

    Allowed signal windows (America/New_York):
    - London Session: 03:00 - 07:00 NY
    - New York Session: 08:00 - 12:00 NY (covers 09:30-10:30 open)
    Asian Session (18:00 - 00:00 NY) is liquidity tracking only, not an allowed signal generation window.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        ny_tz = ZoneInfo("America/New_York")
        ny_dt = dt.astimezone(ny_tz)
    except Exception:
        # Fallback to UTC if timezone database is unconfigured
        ny_dt = dt
    ny_time = ny_dt.time()

    # London Session: 03:00 to 07:00 NY
    if dtime(3, 0) <= ny_time <= dtime(7, 0):
        return True, "London Session"
    # New York Session: 08:00 to 12:00 NY
    if dtime(8, 0) <= ny_time <= dtime(12, 0):
        return True, "New York Session"
    # Asian Session: 18:00 to 24:00 (liquidity tracking only)
    if ny_time >= dtime(18, 0) or ny_time == dtime(0, 0):
        return False, "Asian Session (Liquidity Tracking Only / No Signals)"

    return False, f"Off-Session ({ny_time.strftime('%H:%M')} NY)"


def _get_candle_tf(candle: Any) -> Optional[str]:
    """Safely extract timeframe string from a CandleBase, dict, or ORM object."""
    if candle is None:
        return None
    if isinstance(candle, dict):
        return candle.get("timeframe")
    return getattr(candle, "timeframe", None)


class CRTStrategy(BaseStrategy):
    """Candle Range Theory (CRT) Strategy implementing the institutional AMD framework.

    Quality over quantity: rigorous SMC liquidity sweep and AMD expansion setups only.
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
        session_filter_enabled: bool = False,
        min_sweep_atr_mult: float = 0.15,
        min_disp_atr_mult: float = 0.20,
        min_range_atr_mult: float = 0.35,
        max_range_atr_mult: float = 4.0,
        max_risk_atr_mult: float = 3.0,
        min_rr_tp1: float = 1.0,
        entry_expiry_bars: int = 8,
        pip_size: float = 0.10,
        spread: float = 0.0,
        cooldown_seconds: float = 7200.0,
        enable_dedup: bool = True,
        allow_counter_trend_bypass: Optional[bool] = None,
        counter_trend_min_disp_atr_mult: Optional[float] = None,
    ) -> None:
        self.min_manip_pct = min_manip_pct
        self.max_manip_pct = max_manip_pct
        self.confirm_bars = confirm_bars
        self.base_score = base_score
        self._min_score_threshold = (
            min_score_threshold if min_score_threshold is not None else getattr(settings, "MIN_SETUP_SCORE", 75.0)
        )
        self.analyzer = analyzer or CRTAnalyzer(
            default_min_manip_pct=min_manip_pct,
            default_confirm_bars=confirm_bars,
        )
        self.session_filter_enabled = session_filter_enabled
        self.min_sweep_atr_mult = min_sweep_atr_mult
        self.min_disp_atr_mult = min_disp_atr_mult
        self.min_range_atr_mult = min_range_atr_mult
        self.max_range_atr_mult = max_range_atr_mult
        self.max_risk_atr_mult = max_risk_atr_mult
        self.min_rr_tp1 = min_rr_tp1
        self.entry_expiry_bars = entry_expiry_bars
        self.pip_size = pip_size
        self.spread = spread
        self.cooldown_seconds = cooldown_seconds
        self.enable_dedup = enable_dedup
        self.allow_counter_trend_bypass = (
            allow_counter_trend_bypass
            if allow_counter_trend_bypass is not None
            else getattr(settings, "CRT_ALLOW_COUNTER_TREND_BYPASS", getattr(settings, "ALLOW_COUNTER_TREND_BYPASS", False))
        )
        self.counter_trend_min_disp_atr_mult = (
            counter_trend_min_disp_atr_mult
            if counter_trend_min_disp_atr_mult is not None
            else getattr(settings, "CRT_COUNTER_TREND_MIN_DISP_ATR_MULT", 0.30)
        )

        # Deduplication cache for emitted sweep event keys: key -> emit_timestamp (in-memory fast path)
        self._emitted_sweep_events: Dict[str, datetime] = {}

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
        htf_trend: Optional[str] = None,
        **kwargs: Any,
    ) -> StrategyResult:
        """Evaluate BUY and SELL setups using the Candle Range Theory (AMD) framework."""
        # ------------------------------------------------------------------
        # 1. Resolve Range (HTF) and Confirmation (LTF) candle series
        # ------------------------------------------------------------------
        r_candles = range_candles
        c_candles = confirm_candles

        if r_candles is None:
            if kwargs.get("candles_1h") is not None and len(kwargs.get("candles_1h")) > 0:
                r_candles = kwargs.get("candles_1h")
                if c_candles is None:
                    c_candles = candles_15m if candles_15m is not None else candles
            elif kwargs.get("candles_4h") is not None and len(kwargs.get("candles_4h")) > 0:
                r_candles = kwargs.get("candles_4h")
                if c_candles is None:
                    c_candles = candles_15m if candles_15m is not None else candles
            elif candles_15m is not None and len(candles_15m) > 0:
                first_candle = candles[0] if candles else None
                first_tf = _get_candle_tf(first_candle)
                if first_tf in ("1h", "4h") or (first_tf is None and timeframe in ("1h", "4h")):
                    r_candles = candles
                    if c_candles is None:
                        c_candles = candles_15m
                elif candles == candles_15m or (first_tf in ("15m", "5m", "1m", "30m") and timeframe in ("15m", "5m", "1m", "30m")):
                    r_candles = None
                    if c_candles is None:
                        c_candles = candles_15m
            elif timeframe in ("1h", "4h") and candles is not None and len(candles) > 0:
                r_candles = candles
                if c_candles is None:
                    c_candles = candles_15m

        if c_candles is None:
            c_candles = candles_15m if candles_15m is not None else candles

        # Disallow using LTF candles or identical series as HTF range
        if r_candles is not None and len(r_candles) > 0:
            last_r = r_candles[-1]
            last_r_tf = _get_candle_tf(last_r)
            if last_r_tf in ("15m", "5m", "1m", "30m") and timeframe in ("15m", "5m", "1m", "30m"):
                r_candles = None
            elif c_candles is not None and len(c_candles) > 0:
                if r_candles == c_candles or (len(r_candles) == 1 and len(c_candles) == 1 and r_candles[0] == c_candles[0]):
                    r_candles = None

        # Fix 3: SILENT CANDLE FALLBACK CHECK
        if r_candles is None or len(r_candles) == 0 or (r_candles is c_candles and timeframe not in ("1h", "4h")):
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    "WAIT: Missing HTF accumulation range candles. HTF range candle required (e.g. 1H or 4H); silent fallback to LTF is disabled."
                ],
                metadata={
                    "setup_state": "NO_SETUP",
                    "gatekeeper_passed": False,
                    "rejection_gate": "MISSING_HTF_CANDLES",
                    "htf_trend_source": "none",
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=0.0,
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=None,
            )

        # ------------------------------------------------------------------
        # 2. Run CRT Analysis via Analyzer
        # ------------------------------------------------------------------
        analysis: CRTAnalysis = self.analyzer.analyze(
            range_candles=r_candles,
            confirm_candles=c_candles,
            min_manip_pct=self.min_manip_pct,
            confirm_bars=self.confirm_bars,
        )

        # ------------------------------------------------------------------
        # 3. Determine Current Price for Entry & Latest Timestamp
        # ------------------------------------------------------------------
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

        latest_candle = c_candles[-1] if c_candles and len(c_candles) > 0 else (r_candles[-1] if r_candles else None)
        latest_ts = _get_candle_ts(latest_candle) or datetime.now(timezone.utc)

        # ------------------------------------------------------------------
        # 4. Resolve HTF Trend & Trend Source (Fix 2)
        # ------------------------------------------------------------------
        trend_1h = "RANGING"
        trend_4h = "RANGING"
        htf_trend_source = "none"

        if mtf is not None and hasattr(mtf, "timeframes") and mtf.timeframes:
            if "1h" in mtf.timeframes and mtf.timeframes["1h"].trend:
                trend_1h = _norm_trend(mtf.timeframes["1h"].trend)
            if "4h" in mtf.timeframes and mtf.timeframes["4h"].trend:
                trend_4h = _norm_trend(mtf.timeframes["4h"].trend)

        if trend_4h == "RANGING" and mtf is not None:
            if hasattr(mtf, "primary_trend") and mtf.primary_trend:
                trend_4h = _norm_trend(mtf.primary_trend)
            elif hasattr(mtf, "trend") and mtf.trend:
                trend_4h = _norm_trend(mtf.trend)

        if trend_1h in ("BULLISH", "BEARISH"):
            resolved_htf_trend = trend_1h
            htf_trend_source = "mtf_1h"
        elif trend_4h in ("BULLISH", "BEARISH"):
            resolved_htf_trend = trend_4h
            htf_trend_source = "mtf_4h"
        elif htf_trend is not None and _norm_trend(htf_trend) in ("BULLISH", "BEARISH"):
            resolved_htf_trend = _norm_trend(htf_trend)
            htf_trend_source = "explicit"
            if trend_1h == "RANGING":
                trend_1h = resolved_htf_trend
            if trend_4h == "RANGING":
                trend_4h = resolved_htf_trend
        elif structure is not None and hasattr(structure, "trend") and structure.trend:
            s_trend = _norm_trend(structure.trend)
            if s_trend in ("BULLISH", "BEARISH"):
                resolved_htf_trend = s_trend
                htf_trend_source = "structure_primary"
                if trend_1h == "RANGING":
                    trend_1h = resolved_htf_trend
            else:
                resolved_htf_trend = "RANGING"
                htf_trend_source = "none"
        elif htf_trend is not None:
            resolved_htf_trend = _norm_trend(htf_trend)
            htf_trend_source = "explicit" if resolved_htf_trend != "RANGING" else "none"
        else:
            resolved_htf_trend = "RANGING"
            htf_trend_source = "none"

        # Direction candidate based on manipulation side
        direction = (
            SignalDirection.BUY
            if analysis.positive_direction
            else SignalDirection.SELL
        )

        # Effective ATR estimation
        effective_atr = 0.0
        if indicators is not None and getattr(indicators, "atr", None) is not None:
            effective_atr = getattr(indicators.atr, "atr_value", 0.0) or 0.0
        if effective_atr <= 0.0 and kwargs.get("atr_value"):
            effective_atr = float(kwargs["atr_value"])

        # ------------------------------------------------------------------
        # 5. Qualification Gates (Hard, before scoring)
        # ------------------------------------------------------------------
        reasons: List[str] = []
        score_audit: List[Dict[str, Any]] = []

        allow_bypass = bool(kwargs.get("allow_counter_trend_bypass", self.allow_counter_trend_bypass) and (effective_atr > 0.0))
        ct_min_disp_mult = kwargs.get("counter_trend_min_disp_atr_mult", self.counter_trend_min_disp_atr_mult)

        # Check Session Gate
        enforce_session = kwargs.get("enforce_session", self.session_filter_enabled)
        is_session_open, session_name = is_in_trading_session(latest_ts)
        if enforce_session and not is_session_open:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    f"WAIT (Session Gate): Outside allowed institutional trading sessions (London 03:00-07:00 NY, NY 08:00-12:00 NY). Current status: {session_name}."
                ],
                metadata={
                    "setup_state": "NO_SETUP",
                    "gatekeeper_passed": False,
                    "rejection_gate": "OFF_SESSION",
                    "session_name": session_name,
                    "htf_trend_source": htf_trend_source,
                    "htf_trend": resolved_htf_trend,
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=round(current_price, 5),
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=analysis.breach_point,
            )

        # Missing Timestamps Gate
        if getattr(analysis, "has_missing_timestamps", False) or analysis.range_open_timestamp is None:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=["WAIT (Missing Timestamps): Missing timestamps on range or confirmation candles. Cannot chronologically verify setup."],
                metadata={
                    "setup_state": "NO_SETUP",
                    "gatekeeper_passed": False,
                    "rejection_gate": "MISSING_TIMESTAMPS",
                    "crt_analysis": analysis.model_dump(),
                    "htf_trend": resolved_htf_trend,
                    "htf_trend_source": htf_trend_source,
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=round(current_price, 5),
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=None,
            )

        # Basic AMD Pattern detection
        if not analysis.is_breached or analysis.breach_point is None:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=["MARKET BIAS: NEUTRAL / WAIT (No manipulation breach detected)."],
                metadata={
                    "setup_state": "NO_SETUP",
                    "gatekeeper_passed": False,
                    "crt_analysis": analysis.model_dump(),
                    "htf_trend": resolved_htf_trend,
                    "htf_trend_source": htf_trend_source,
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=round(current_price, 5),
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=None,
            )

        # HTF Trend Conflict Gate (Block counter-trend setups unless bypass enabled)
        is_counter_trend = (
            (resolved_htf_trend == "BEARISH" and direction == SignalDirection.BUY)
            or (resolved_htf_trend == "BULLISH" and direction == SignalDirection.SELL)
        )
        if is_counter_trend and not allow_bypass:
            opposing_type = "Bullish" if direction == SignalDirection.BUY else "Bearish"
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    f"REJECTED (Trend Conflict): HTF Trend is {resolved_htf_trend}. Ignoring {opposing_type} CRT setup."
                ],
                metadata={
                    "setup_state": "NO_SETUP",
                    "gatekeeper_passed": False,
                    "trend_conflict": True,
                    "rejection_gate": "TREND_CONFLICT",
                    "htf_trend": resolved_htf_trend,
                    "htf_trend_source": htf_trend_source,
                    "crt_analysis": analysis.model_dump(),
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=round(current_price, 5),
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=analysis.breach_point,
            )

        # Range Quality Gate (reject micro-ranges and giant candles vs ATR)
        range_size = analysis.range_high - analysis.range_low
        if effective_atr > 0.0:
            if range_size < self.min_range_atr_mult * effective_atr:
                return StrategyResult(
                    strategy_name=self.name,
                    direction=SignalDirection.WAIT,
                    score=0.0,
                    reasons=[
                        f"REJECTED (Range Quality): Benchmark range size (${range_size:.2f}) is too small (< {self.min_range_atr_mult}x ATR ${effective_atr:.2f}). Micro-range noise."
                    ],
                    metadata={
                        "setup_state": "NO_SETUP",
                        "gatekeeper_passed": False,
                        "rejection_gate": "MICRO_RANGE",
                        "range_size": range_size,
                        "effective_atr": effective_atr,
                        "crt_analysis": analysis.model_dump(),
                    },
                    score_breakdown=ScoreBreakdown(
                        structure_score=0.0,
                        liquidity_score=0.0,
                        indicators_score=0.0,
                        price_action_score=0.0,
                        total_score=0.0,
                        is_qualified=False,
                    ),
                    entry_price=round(current_price, 5),
                    stop_loss=0.0,
                    take_profit_1=0.0,
                    take_profit_2=0.0,
                    risk_reward=0.0,
                    breach_point=analysis.breach_point,
                )
            if range_size > self.max_range_atr_mult * effective_atr:
                return StrategyResult(
                    strategy_name=self.name,
                    direction=SignalDirection.WAIT,
                    score=0.0,
                    reasons=[
                        f"REJECTED (Range Quality): Benchmark range size (${range_size:.2f}) is abnormally large (> {self.max_range_atr_mult}x ATR ${effective_atr:.2f}). Outlier volatility."
                    ],
                    metadata={
                        "setup_state": "NO_SETUP",
                        "gatekeeper_passed": False,
                        "rejection_gate": "EXCESSIVE_RANGE",
                        "range_size": range_size,
                        "effective_atr": effective_atr,
                        "crt_analysis": analysis.model_dump(),
                    },
                    score_breakdown=ScoreBreakdown(
                        structure_score=0.0,
                        liquidity_score=0.0,
                        indicators_score=0.0,
                        price_action_score=0.0,
                        total_score=0.0,
                        is_qualified=False,
                    ),
                    entry_price=round(current_price, 5),
                    stop_loss=0.0,
                    take_profit_1=0.0,
                    take_profit_2=0.0,
                    risk_reward=0.0,
                    breach_point=analysis.breach_point,
                )

        # Minimum Sweep Size Gate
        swept_edge = analysis.range_low if analysis.positive_direction else analysis.range_high
        sweep_distance = abs(swept_edge - analysis.breach_point)
        min_sweep_dollars = max(self.spread * 3.0, self.min_sweep_atr_mult * effective_atr) if effective_atr > 0 else (self.spread * 3.0)

        if sweep_distance < min_sweep_dollars or analysis.manip_depth_pct < self.min_manip_pct:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    f"REJECTED (Micro-sweep): Sweep distance (${sweep_distance:.2f}) or depth ({analysis.manip_depth_pct:.1f}%) is below minimum required (${min_sweep_dollars:.2f} or {self.min_manip_pct:.1f}%)."
                ],
                metadata={
                    "setup_state": "NO_SETUP",
                    "gatekeeper_passed": False,
                    "rejection_gate": "MICRO_SWEEP",
                    "sweep_distance": sweep_distance,
                    "crt_analysis": analysis.model_dump(),
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=round(current_price, 5),
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=analysis.breach_point,
            )

        if analysis.manip_depth_pct > self.max_manip_pct:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    f"REJECTED: Manipulation depth ({analysis.manip_depth_pct:.1f}%) exceeds maximum allowed ({self.max_manip_pct:.1f}%). Likely a breakout/spike, not a sweep."
                ],
                metadata={
                    "setup_state": "NO_SETUP",
                    "gatekeeper_passed": False,
                    "rejection_gate": "EXCESSIVE_MANIPULATION",
                    "crt_analysis": analysis.model_dump(),
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=round(current_price, 5),
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=analysis.breach_point,
            )

        # Sweep Extreme Invalidation Gate
        first_breach_extreme = analysis.breach_point
        if c_candles:
            for c in c_candles:
                if analysis.positive_direction and _get_candle_val(c, "low") < analysis.range_low:
                    first_breach_extreme = _get_candle_val(c, "low")
                    break
                elif not analysis.positive_direction and _get_candle_val(c, "high") > analysis.range_high:
                    first_breach_extreme = _get_candle_val(c, "high")
                    break

        is_extreme_broken = False
        if direction == SignalDirection.BUY:
            if (analysis.breach_point is not None and current_price <= analysis.breach_point) or \
               (first_breach_extreme is not None and current_price <= first_breach_extreme):
                is_extreme_broken = True
        else:
            if (analysis.breach_point is not None and current_price >= analysis.breach_point) or \
               (first_breach_extreme is not None and current_price >= first_breach_extreme):
                is_extreme_broken = True

        if is_extreme_broken:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    f"INVALIDATED (Sweep Extreme Broken): Price ({current_price:.5f}) broke beyond manipulation extreme ({analysis.breach_point:.5f}) before entry."
                ],
                metadata={
                    "setup_state": "INVALIDATED_SETUP",
                    "gatekeeper_passed": False,
                    "rejection_gate": "SWEEP_EXTREME_BROKEN",
                    "crt_analysis": analysis.model_dump(),
                    "htf_trend": resolved_htf_trend,
                    "htf_trend_source": htf_trend_source,
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=round(current_price, 5),
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=analysis.breach_point,
            )

        # ------------------------------------------------------------------
        # 6. LTF Confirmation Check (Range Re-entry + Displacement + MSS)
        # ------------------------------------------------------------------
        if not analysis.is_confirmed:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    f"WAIT (Confirmation Pending): Manipulation breach at {analysis.breach_point:.5f} detected, awaiting close back inside range."
                ],
                metadata={
                    "setup_state": "WAITING_FOR_CONFIRMATION",
                    "gatekeeper_passed": False,
                    "rejection_gate": "CONFIRMATION_PENDING",
                    "crt_analysis": analysis.model_dump(),
                    "htf_trend": resolved_htf_trend,
                    "htf_trend_source": htf_trend_source,
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=round(current_price, 5),
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=analysis.breach_point,
            )

        confirmation_res: LTFConfirmationResult = verify_ltf_confirmation(
            direction=direction,
            range_high=analysis.range_high,
            range_low=analysis.range_low,
            candles_15m=c_candles,
            breach_point=analysis.breach_point,
            manip_candle_index=getattr(analysis, "manipulation_candle_index", 0),
            breach_timestamp=getattr(analysis, "breach_timestamp", None),
            atr=effective_atr,
            min_disp_atr_mult=self.min_disp_atr_mult,
            structure=structure,
        )

        if not confirmation_res.is_confirmed:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    f"WAIT (Confirmation Pending): {confirmation_res.reason}"
                ],
                metadata={
                    "setup_state": "WAITING_FOR_CONFIRMATION",
                    "gatekeeper_passed": False,
                    "rejection_gate": "CONFIRMATION_PENDING",
                    "confirmation_detail": confirmation_res.reason,
                    "crt_analysis": analysis.model_dump(),
                    "htf_trend": resolved_htf_trend,
                    "htf_trend_source": htf_trend_source,
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=round(current_price, 5),
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=analysis.breach_point,
            )

        # Counter-Trend Displacement Gate (When allow_bypass is True and setup opposes HTF trend)
        counter_trend_bypassed = False
        if is_counter_trend:
            if effective_atr <= 0.0:
                opposing_type = "Bullish" if direction == SignalDirection.BUY else "Bearish"
                return StrategyResult(
                    strategy_name=self.name,
                    direction=SignalDirection.WAIT,
                    score=0.0,
                    reasons=[
                        f"REJECTED (Trend Conflict): HTF Trend is {resolved_htf_trend}. Ignoring {opposing_type} CRT setup."
                    ],
                    metadata={
                        "setup_state": "NO_SETUP",
                        "gatekeeper_passed": False,
                        "trend_conflict": True,
                        "rejection_gate": "TREND_CONFLICT",
                        "htf_trend": resolved_htf_trend,
                        "htf_trend_source": htf_trend_source,
                        "crt_analysis": analysis.model_dump(),
                    },
                    score_breakdown=ScoreBreakdown(
                        structure_score=0.0,
                        liquidity_score=0.0,
                        indicators_score=0.0,
                        price_action_score=0.0,
                        total_score=0.0,
                        is_qualified=False,
                    ),
                    entry_price=round(current_price, 5),
                    stop_loss=0.0,
                    take_profit_1=0.0,
                    take_profit_2=0.0,
                    risk_reward=0.0,
                    breach_point=analysis.breach_point,
                )

            disp_size = confirmation_res.displacement_size or getattr(analysis, "confirmation_displacement", 0.0) or 0.0
            min_disp_req = ct_min_disp_mult * effective_atr
            has_strong_disp = (disp_size >= min_disp_req)

            if allow_bypass and has_strong_disp:
                counter_trend_bypassed = True
                reasons.append(
                    f"COUNTER-TREND BYPASS: Opposing HTF {resolved_htf_trend} overridden by strong LTF displacement "
                    f"(${disp_size:.2f} >= ${min_disp_req:.2f} [{ct_min_disp_mult:.2f}x ATR])."
                )
            else:
                opposing_type = "Bullish" if direction == SignalDirection.BUY else "Bearish"
                reason_msg = f"REJECTED (Trend Conflict): HTF Trend is {resolved_htf_trend}. Ignoring {opposing_type} CRT setup."
                if allow_bypass and not has_strong_disp:
                    reason_msg += f" Insufficient LTF displacement (${disp_size:.2f} < ${min_disp_req:.2f} = {ct_min_disp_mult:.2f}x ATR) for counter-trend bypass."
                return StrategyResult(
                    strategy_name=self.name,
                    direction=SignalDirection.WAIT,
                    score=0.0,
                    reasons=[reason_msg],
                    metadata={
                        "setup_state": "NO_SETUP",
                        "gatekeeper_passed": False,
                        "trend_conflict": True,
                        "rejection_gate": "TREND_CONFLICT",
                        "htf_trend": resolved_htf_trend,
                        "htf_trend_source": htf_trend_source,
                        "displacement_size": disp_size,
                        "crt_analysis": analysis.model_dump(),
                    },
                    score_breakdown=ScoreBreakdown(
                        structure_score=0.0,
                        liquidity_score=0.0,
                        indicators_score=0.0,
                        price_action_score=0.0,
                        total_score=0.0,
                        is_qualified=False,
                    ),
                    entry_price=round(current_price, 5),
                    stop_loss=0.0,
                    take_profit_1=0.0,
                    take_profit_2=0.0,
                    risk_reward=0.0,
                    breach_point=analysis.breach_point,
                )

        # ------------------------------------------------------------------
        # 7. Retracement Entry Zone Calculation & Missed Setup Check
        # ------------------------------------------------------------------
        raw_midpoint = (analysis.range_high + analysis.range_low) / 2.0
        entry_res: RetracementEntry = calculate_retracement_entry(
            direction=direction,
            sweep_extreme=analysis.breach_point,
            displacement_extreme=confirmation_res.displacement_extreme,
            candles_15m=c_candles,
            current_price=current_price,
            target_tp1=raw_midpoint,
            atr=effective_atr,
            spread=self.spread,
            expiry_bars=self.entry_expiry_bars,
            manip_candle_index=getattr(analysis, "manipulation_candle_index", 0),
            tick_size=self.pip_size / 10.0,
        )

        # For limit-zone setups, use ideal_entry for geometry and target calculations
        target_entry = entry_res.ideal_entry if entry_res.entry_mode == "limit_zone" else current_price
        effective_entry = target_entry

        # An entry zone that straddles the stop is not executable. Reject it the
        # same way a missed setup is rejected, with a distinct gate code.
        if entry_res.zone_invalid:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    f"REJECTED (Invalid Entry Zone): entry zone "
                    f"[{entry_res.zone_low:.5f}, {entry_res.zone_high:.5f}] is not clear of "
                    f"stop loss {entry_res.stop_loss:.5f}."
                ],
                metadata={
                    "setup_state": "INVALIDATED_SETUP",
                    "gatekeeper_passed": False,
                    "rejection_gate": "INVALID_ENTRY_ZONE",
                    "entry_zone": [entry_res.zone_low, entry_res.zone_high],
                    "ideal_entry": entry_res.ideal_entry,
                    "crt_analysis": analysis.model_dump(),
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=round(current_price, 5),
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=analysis.breach_point,
            )

        if entry_res.is_missed:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    f"MISSED SETUP: {entry_res.missed_reason}"
                ],
                metadata={
                    "setup_state": "MISSED",
                    "gatekeeper_passed": False,
                    "rejection_gate": "MISSED_SETUP",
                    "entry_zone": [entry_res.zone_low, entry_res.zone_high],
                    "ideal_entry": entry_res.ideal_entry,
                    "crt_analysis": analysis.model_dump(),
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=round(current_price, 5),
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=analysis.breach_point,
            )

        # ------------------------------------------------------------------
        # 8. Stop Loss & Risk Geometry Validation
        # ------------------------------------------------------------------
        sl_buffer = max(self.spread, 0.10 * effective_atr) if (self.spread > 0 or effective_atr > 0) else 0.0

        if direction == SignalDirection.BUY:
            raw_sl = entry_res.stop_loss
            if structure is not None and structure.liquidity_pools:
                for pool in structure.liquidity_pools:
                    if pool.pool_type == LiquidityEventType.EQUAL_LOWS and pool.price_level < effective_entry:
                        if abs(pool.price_level - analysis.breach_point) <= 1.0 * (effective_atr or 5.0):
                            raw_sl = min(raw_sl, pool.price_level - sl_buffer)
            stop_loss = round(raw_sl, 5)

            if stop_loss >= effective_entry:
                return StrategyResult(
                    strategy_name=self.name,
                    direction=SignalDirection.WAIT,
                    score=0.0,
                    reasons=[
                        f"REJECTED (Invalid Risk Geometry): BUY Stop Loss ({stop_loss:.5f}) >= Entry Price ({effective_entry:.5f})."
                    ],
                    metadata={
                        "setup_state": "INVALIDATED_SETUP",
                        "gatekeeper_passed": False,
                        "rejection_gate": "INVALID_RISK_GEOMETRY",
                        "crt_analysis": analysis.model_dump(),
                    },
                    score_breakdown=ScoreBreakdown(
                        structure_score=0.0,
                        liquidity_score=0.0,
                        indicators_score=0.0,
                        price_action_score=0.0,
                        total_score=0.0,
                        is_qualified=False,
                    ),
                    entry_price=round(current_price, 5),
                    stop_loss=0.0,
                    take_profit_1=0.0,
                    take_profit_2=0.0,
                    risk_reward=0.0,
                    breach_point=analysis.breach_point,
                )
            risk_distance = effective_entry - stop_loss

        else:  # SELL
            raw_sl = entry_res.stop_loss
            if structure is not None and structure.liquidity_pools:
                for pool in structure.liquidity_pools:
                    if pool.pool_type == LiquidityEventType.EQUAL_HIGHS and pool.price_level > effective_entry:
                        if abs(pool.price_level - analysis.breach_point) <= 1.0 * (effective_atr or 5.0):
                            raw_sl = max(raw_sl, pool.price_level + sl_buffer)
            stop_loss = round(raw_sl, 5)

            if stop_loss <= effective_entry:
                return StrategyResult(
                    strategy_name=self.name,
                    direction=SignalDirection.WAIT,
                    score=0.0,
                    reasons=[
                        f"REJECTED (Invalid Risk Geometry): SELL Stop Loss ({stop_loss:.5f}) <= Entry Price ({effective_entry:.5f})."
                    ],
                    metadata={
                        "setup_state": "INVALIDATED_SETUP",
                        "gatekeeper_passed": False,
                        "rejection_gate": "INVALID_RISK_GEOMETRY",
                        "crt_analysis": analysis.model_dump(),
                    },
                    score_breakdown=ScoreBreakdown(
                        structure_score=0.0,
                        liquidity_score=0.0,
                        indicators_score=0.0,
                        price_action_score=0.0,
                        total_score=0.0,
                        is_qualified=False,
                    ),
                    entry_price=round(current_price, 5),
                    stop_loss=0.0,
                    take_profit_1=0.0,
                    take_profit_2=0.0,
                    risk_reward=0.0,
                    breach_point=analysis.breach_point,
                )
            risk_distance = stop_loss - effective_entry

        # Enforce maximum risk distance
        if effective_atr > 0.0 and risk_distance > (self.max_risk_atr_mult * effective_atr):
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    f"REJECTED (Excessive Risk): Stop Loss distance (${risk_distance:.2f}) exceeds maximum allowed ({self.max_risk_atr_mult}x ATR ${effective_atr:.2f})."
                ],
                metadata={
                    "setup_state": "NO_SETUP",
                    "gatekeeper_passed": False,
                    "rejection_gate": "EXCESSIVE_RISK_DISTANCE",
                    "risk_distance": risk_distance,
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=round(current_price, 5),
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=analysis.breach_point,
            )

        # ------------------------------------------------------------------
        # 9. CRT-Native Targets & Path Validation via PathValidator
        # ------------------------------------------------------------------
        target_entry = entry_res.ideal_entry if entry_res.entry_mode == "limit_zone" else current_price
        target_plan: CRTTargetPlan = calculate_crt_targets(
            direction=direction,
            entry_price=target_entry,
            stop_loss=stop_loss,
            range_high=analysis.range_high,
            range_low=analysis.range_low,
            atr=effective_atr,
            min_rr=self.min_rr_tp1,
            structure=structure,
            indicators=indicators,
        )

        if not target_plan.is_valid:
            gate_code = target_plan.rejection_gate or "INSUFFICIENT_RR"
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    target_plan.rejection_reason or f"WAIT ({gate_code}): Target plan rejected."
                ],
                metadata={
                    "setup_state": "POTENTIAL_SETUP",
                    "gatekeeper_passed": False,
                    "rejection_gate": gate_code,
                    "nearest_obstacle": target_plan.obstacle_type,
                    "obstacle_r": target_plan.risk_reward_tp1 if target_plan.capped_by_obstacle else None,
                    "risk_reward_tp1": target_plan.risk_reward_tp1,
                    "risk_reward_tp2": target_plan.risk_reward_tp2,
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=round(current_price, 5),
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=analysis.breach_point,
            )

        take_profit_1 = target_plan.take_profit_1
        take_profit_2 = target_plan.take_profit_2
        rr_tp1 = target_plan.risk_reward_tp1
        rr_tp2 = target_plan.risk_reward_tp2

        if target_plan.notes:
            reasons.extend(target_plan.notes)

        # ------------------------------------------------------------------
        # 10. Deduplication (Key: symbol_tf_dir_rangeopen_breachts + Cooldown)
        # ------------------------------------------------------------------
        range_open_ts_str = str(analysis.range_open_timestamp or "0")
        breach_ts_str = str(analysis.breach_timestamp or "0")
        sweep_event_key = f"{symbol}_{timeframe}_{direction.value}_{range_open_ts_str}_{breach_ts_str}"

        now_utc = datetime.now(timezone.utc)
        enable_dedup = kwargs.get("enable_dedup", getattr(self, "enable_dedup", True))
        is_deduped = False
        dedup_reason = f"DEDUPLICATED: Repeat signal for sweep event {sweep_event_key} suppressed by cooldown."

        if enable_dedup:
            if sweep_event_key in self._emitted_sweep_events:
                prev_time = self._emitted_sweep_events[sweep_event_key]
                if (now_utc - prev_time).total_seconds() < self.cooldown_seconds:
                    is_deduped = True
            else:
                db_conn = kwargs.get("db")
                close_sess = False
                if db_conn is None:
                    try:
                        from app.core.database import SessionLocal
                        db_conn = SessionLocal()
                        close_sess = True
                    except Exception:
                        db_conn = None
                if db_conn is not None:
                    try:
                        from app.models.crt_sweep_event import CRTSweepEvent
                        record = db_conn.query(CRTSweepEvent).filter(CRTSweepEvent.sweep_key == sweep_event_key).first()
                        if record is not None and record.cooldown_until is not None:
                            cd_dt = record.cooldown_until
                            if cd_dt.tzinfo is None:
                                cd_dt = cd_dt.replace(tzinfo=timezone.utc)
                            if now_utc < cd_dt:
                                em_dt = record.emitted_at
                                if em_dt.tzinfo is None:
                                    em_dt = em_dt.replace(tzinfo=timezone.utc)
                                self._emitted_sweep_events[sweep_event_key] = em_dt
                                is_deduped = True
                                dedup_reason = f"DEDUPLICATED: Repeat signal for sweep event {sweep_event_key} suppressed by database cooldown."
                    except Exception as e:
                        logger.debug(f"CRT DB dedup check bypassed: {e}")
                    finally:
                        if close_sess and db_conn:
                            db_conn.close()

        if is_deduped:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[dedup_reason],
                metadata={
                    "setup_state": "NO_SETUP",
                    "gatekeeper_passed": False,
                    "rejection_gate": "DEDUPLICATED",
                    "sweep_event_key": sweep_event_key,
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
                entry_price=round(current_price, 5),
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                breach_point=analysis.breach_point,
            )

        # ------------------------------------------------------------------
        # 11. Daily Bias & Swept Level Classification
        # ------------------------------------------------------------------
        daily_bias_res = calculate_daily_bias(
            candles_1h=r_candles,
            current_time=latest_ts,
            current_price=current_price,
        )
        sweep_level_type, level_points = classify_swept_level(
            breach_point=analysis.breach_point,
            positive_direction=analysis.positive_direction,
            daily_bias=daily_bias_res,
            structure=structure,
            atr=effective_atr,
        )

        # ------------------------------------------------------------------
        # 12. Auditable 3-Pillar Scoring Engine
        # ------------------------------------------------------------------
        # Pillar 1: Structure & MTF (Max 35)
        structure_score = 0.0
        aligned_trend = "BULLISH" if direction == SignalDirection.BUY else "BEARISH"

        # 1.1 HTF 1H Alignment (max 12)
        if htf_trend_source == "structure_primary":
            score_audit.append({
                "pillar": "Structure & MTF",
                "rule": "1H Alignment",
                "points": 0.0,
                "max": 12.0,
                "reason": "1H Trend source is structure_primary (No HTF credit awarded)",
            })
        elif trend_1h == aligned_trend:
            structure_score += 12.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "1H Alignment", "points": 12.0, "max": 12.0, "reason": f"1H Trend is aligned ({trend_1h})"})
        elif trend_1h == "RANGING":
            structure_score += 8.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "1H Alignment", "points": 8.0, "max": 12.0, "reason": "1H Trend is RANGING (Partial credit)"})
        elif counter_trend_bypassed:
            structure_score += 8.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "1H Alignment", "points": 8.0, "max": 12.0, "reason": f"1H Trend opposes ({trend_1h}), but Counter-Trend Bypass active (Strong LTF Momentum overrides penalty)"})
        else:
            score_audit.append({"pillar": "Structure & MTF", "rule": "1H Alignment", "points": 0.0, "max": 12.0, "reason": f"1H Trend opposes ({trend_1h})"})

        # 1.2 HTF 4H Alignment (max 8)
        if htf_trend_source == "structure_primary":
            score_audit.append({
                "pillar": "Structure & MTF",
                "rule": "4H Alignment",
                "points": 0.0,
                "max": 8.0,
                "reason": "4H Trend source is structure_primary (No HTF credit awarded)",
            })
        elif trend_4h == aligned_trend:
            structure_score += 8.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "4H Alignment", "points": 8.0, "max": 8.0, "reason": f"4H Trend is aligned ({trend_4h})"})
        elif trend_4h == "RANGING":
            structure_score += 6.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "4H Alignment", "points": 6.0, "max": 8.0, "reason": "4H Trend is RANGING (Partial credit)"})
        elif counter_trend_bypassed:
            structure_score += 6.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "4H Alignment", "points": 6.0, "max": 8.0, "reason": f"4H Trend opposes ({trend_4h}), but Counter-Trend Bypass active (Strong LTF Momentum overrides penalty)"})
        else:
            score_audit.append({"pillar": "Structure & MTF", "rule": "4H Alignment", "points": 0.0, "max": 8.0, "reason": f"4H Trend opposes ({trend_4h})"})

        # 1.3 MSS / CHoCH after sweep (max 8)
        if confirmation_res.has_mss:
            structure_score += 8.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "MSS / CHoCH", "points": 8.0, "max": 8.0, "reason": "Confirmed Market Structure Shift (MSS) after sweep"})
        else:
            structure_score += 4.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "MSS / CHoCH", "points": 4.0, "max": 8.0, "reason": "Baseline reversal structure"})

        # 1.4 Displacement candle strength (max 5)
        disp_body = confirmation_res.displacement_size or analysis.confirmation_displacement
        if effective_atr > 0.0 and disp_body >= 0.30 * effective_atr:
            structure_score += 5.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "Displacement Strength", "points": 5.0, "max": 5.0, "reason": f"Strong confirmation displacement (${disp_body:.2f} >= 0.3x ATR)"})
        elif disp_body > 0:
            structure_score += 4.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "Displacement Strength", "points": 4.0, "max": 5.0, "reason": f"Clean confirmation displacement (${disp_body:.2f})"})
        else:
            structure_score += 2.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "Displacement Strength", "points": 2.0, "max": 5.0, "reason": "Baseline displacement"})

        # 1.5 Premium / Discount alignment (max 4)
        mid_point = analysis.range_low + (range_size * 0.5)
        in_discount = current_price < mid_point
        if (direction == SignalDirection.BUY and in_discount) or (direction == SignalDirection.SELL and not in_discount):
            structure_score += 4.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "Premium/Discount", "points": 4.0, "max": 4.0, "reason": f"Entry in {'Discount' if in_discount else 'Premium'} zone"})
        else:
            score_audit.append({"pillar": "Structure & MTF", "rule": "Premium/Discount", "points": 0.0, "max": 4.0, "reason": "Suboptimal pricing zone"})

        structure_score = min(35.0, max(0.0, structure_score))

        # Pillar 2: Liquidity & POIs (Max 40)
        liquidity_score = 0.0
        # 2.1 Swept Level Significance (max 18)
        liquidity_score += level_points
        score_audit.append({"pillar": "Liquidity & POIs", "rule": "Swept Level", "points": level_points, "max": 18.0, "reason": f"Swept level: {sweep_level_type}"})

        # 2.2 Entry inside/near valid FVG or Order Block (max 12)
        poi_points = 8.0
        poi_reason = f"Retracement {entry_res.zone_type} zone entry"
        if entry_res.zone_type in ("FVG", "ORDER_BLOCK"):
            poi_points = 12.0
            poi_reason = f"Entry sitting directly inside fresh {entry_res.zone_type}"
        elif indicators is not None and indicators.active_fvgs:
            for fvg in indicators.active_fvgs:
                if (direction == SignalDirection.BUY and fvg.fvg_type == FVGType.BULLISH_FVG) or (
                    direction == SignalDirection.SELL and fvg.fvg_type == FVGType.BEARISH_FVG
                ):
                    if not fvg.is_mitigated and fvg.bottom_price <= current_price <= fvg.top_price:
                        poi_points = 12.0
                        poi_reason = "Entry sitting directly inside fresh aligned FVG"
                        break

        liquidity_score += poi_points
        score_audit.append({"pillar": "Liquidity & POIs", "rule": "POI Proximity", "points": poi_points, "max": 12.0, "reason": poi_reason})

        # 2.3 Clean path to target (max 10)
        if not target_plan.capped_by_obstacle:
            liquidity_score += 10.0
            score_audit.append({"pillar": "Liquidity & POIs", "rule": "Clean Path", "points": 10.0, "max": 10.0, "reason": "Unobstructed path to targets (No opposing unmitigated zones)"})
        else:
            if rr_tp1 >= 2.0:
                liquidity_score += 8.0
                score_audit.append({"pillar": "Liquidity & POIs", "rule": "Clean Path", "points": 8.0, "max": 10.0, "reason": f"Generous clear path ({rr_tp1:.1f}R to {target_plan.obstacle_type})"})
            elif rr_tp1 >= 1.2:
                liquidity_score += 6.0
                score_audit.append({"pillar": "Liquidity & POIs", "rule": "Clean Path", "points": 6.0, "max": 10.0, "reason": f"Adequate clear path ({rr_tp1:.1f}R to {target_plan.obstacle_type})"})
            else:
                liquidity_score += 3.0
                score_audit.append({"pillar": "Liquidity & POIs", "rule": "Clean Path", "points": 3.0, "max": 10.0, "reason": f"Tight obstacle margin ({rr_tp1:.1f}R to {target_plan.obstacle_type})"})

        liquidity_score = min(40.0, max(0.0, liquidity_score))

        # Pillar 3: Price Action (Max 25)
        price_action_score = 0.0
        # 3.1 Rejection wick ratio (max 8)
        wick_ratio = analysis.breach_wick_ratio
        if wick_ratio >= 0.50:
            price_action_score += 8.0
            score_audit.append({"pillar": "Price Action", "rule": "Rejection Wick", "points": 8.0, "max": 8.0, "reason": f"Extremely strong rejection wick ({wick_ratio*100:.1f}% of bar)"})
        elif wick_ratio >= 0.35:
            price_action_score += 6.0
            score_audit.append({"pillar": "Price Action", "rule": "Rejection Wick", "points": 6.0, "max": 8.0, "reason": f"Clean rejection wick ({wick_ratio*100:.1f}% of bar)"})
        else:
            price_action_score += 4.0
            score_audit.append({"pillar": "Price Action", "rule": "Rejection Wick", "points": 4.0, "max": 8.0, "reason": f"Moderate rejection wick ({wick_ratio*100:.1f}% of bar)"})

        # 3.2 Close back inside range quality (max 7)
        reentry_pct = analysis.reentry_depth_pct
        if reentry_pct >= 10.0:
            price_action_score += 7.0
            score_audit.append({"pillar": "Price Action", "rule": "Range Re-entry", "points": 7.0, "max": 7.0, "reason": f"Firm re-entry inside accumulation range ({reentry_pct:.1f}% depth)"})
        elif reentry_pct >= 3.0:
            price_action_score += 5.0
            score_audit.append({"pillar": "Price Action", "rule": "Range Re-entry", "points": 5.0, "max": 7.0, "reason": f"Clean re-entry inside accumulation range ({reentry_pct:.1f}% depth)"})
        else:
            price_action_score += 3.0
            score_audit.append({"pillar": "Price Action", "rule": "Range Re-entry", "points": 3.0, "max": 7.0, "reason": "Marginal re-entry inside accumulation range"})

        # 3.3 Displacement / FVG formed on confirmation (max 6)
        if effective_atr > 0.0 and disp_body >= 0.25 * effective_atr:
            price_action_score += 6.0
            score_audit.append({"pillar": "Price Action", "rule": "Confirmation Momentum", "points": 6.0, "max": 6.0, "reason": "High-velocity reversal bar created expansion"})
        elif disp_body > 0:
            price_action_score += 5.0
            score_audit.append({"pillar": "Price Action", "rule": "Confirmation Momentum", "points": 5.0, "max": 6.0, "reason": "Clean reversal close inside range"})
        else:
            price_action_score += 3.0
            score_audit.append({"pillar": "Price Action", "rule": "Confirmation Momentum", "points": 3.0, "max": 6.0, "reason": "Standard reversal close inside range"})

        # 3.4 Confirmation bar quality (max 4)
        price_action_score += 4.0
        score_audit.append({"pillar": "Price Action", "rule": "Confirmation Quality", "points": 4.0, "max": 4.0, "reason": "Clean closing price action"})

        price_action_score = min(25.0, max(0.0, price_action_score))

        # Penalties (subtract)
        penalties = 0.0
        if not is_session_open:
            penalties += 8.0
            score_audit.append({"pillar": "Penalties", "rule": "Off-Session Execution", "points": -8.0, "max": 0.0, "reason": f"Formed outside allowed trading sessions ({session_name})"})

        if target_plan.capped_by_obstacle and rr_tp1 < 1.2:
            penalties += 5.0
            score_audit.append({"pillar": "Penalties", "rule": "Near Obstacle", "points": -5.0, "max": 0.0, "reason": f"Obstacle at {rr_tp1:.2f}R (< 1.2R)"})

        # Calculate Total Composite Score
        total_score = round(max(0.0, min(100.0, structure_score + liquidity_score + price_action_score - penalties)), 1)
        is_qualified = total_score >= self._min_score_threshold

        score_breakdown = ScoreBreakdown(
            structure_score=round(structure_score, 1),
            liquidity_score=round(liquidity_score, 1),
            indicators_score=0.0,
            price_action_score=round(price_action_score, 1),
            total_score=total_score,
            is_qualified=is_qualified,
        )

        # ------------------------------------------------------------------
        # 13. Position Sizing & Pips Math
        # ------------------------------------------------------------------
        contract_size = 100.0
        broker_step = 0.01
        min_lot = 0.01

        account_balance = float(kwargs.get("account_balance", 10000.0))
        risk_percent = float(kwargs.get("risk_percent", 0.5))

        stop_distance_dollars = round(abs(effective_entry - stop_loss), 5)
        risk_pips = round(stop_distance_dollars / self.pip_size, 1)
        tp1_pips = round(abs(take_profit_1 - effective_entry) / self.pip_size, 1)
        tp2_pips = round(abs(take_profit_2 - effective_entry) / self.pip_size, 1)

        risk_budget_dollars = round(account_balance * (risk_percent / 100.0), 2)
        dollar_risk_per_lot = stop_distance_dollars * contract_size

        if dollar_risk_per_lot > 0:
            raw_lots = risk_budget_dollars / dollar_risk_per_lot
            lots = math.floor(raw_lots / broker_step) * broker_step
            lots = round(lots, 2)
        else:
            lots = 0.0

        min_lot_risk_dollars = round(min_lot * dollar_risk_per_lot, 2)

        risk_warning: Optional[str] = None
        if lots < min_lot or min_lot_risk_dollars > risk_budget_dollars:
            risk_warning = (
                f"RISK EXCEEDS LIMIT - min lot too large for account: "
                f"min {min_lot:.2f} lot risks ${min_lot_risk_dollars:.2f} on ${risk_budget_dollars:.2f} budget ({risk_percent}% of ${account_balance:,.0f})"
            )
            suggested_lots = min_lot
            actual_risk_dollars = min_lot_risk_dollars
        else:
            suggested_lots = lots
            actual_risk_dollars = round(lots * dollar_risk_per_lot, 2)

        # ------------------------------------------------------------------
        # 14. Quality Tiering & Lifecycle State Evaluation
        # ------------------------------------------------------------------
        quality_tier_res: QualityTierResult = determine_quality_tier(
            score=total_score,
            gatekeeper_passed=is_qualified,
        )

        setup_state = "CONFIRMED_SETUP" if is_qualified else "POTENTIAL_SETUP"

        expires_at = entry_res.expires_at
        expires_at_utc_str = expires_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            bangkok_tz = ZoneInfo("Asia/Bangkok")
            expires_at_utc7_str = expires_at.astimezone(bangkok_tz).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            expires_at_utc7_str = expires_at_utc_str

        lifecycle_res: StateTransitionResult = evaluate_lifecycle_state(
            sweep_key=sweep_event_key,
            direction=direction,
            current_price=current_price,
            current_time=latest_ts,
            entry_price=effective_entry,
            stop_loss=stop_loss,
            tp1=take_profit_1,
            tp2=take_profit_2,
            zone_high=entry_res.zone_high,
            zone_low=entry_res.zone_low,
            expires_at=expires_at,
            db_conn=kwargs.get("db"),
            is_missed=entry_res.is_missed,
            is_sweep_broken=is_extreme_broken,
        )

        # ------------------------------------------------------------------
        # 15. Assemble Strategy Result & Metadata
        # ------------------------------------------------------------------
        bias_str = "BULLISH" if direction == SignalDirection.BUY else "BEARISH"
        reasons.extend([
            f"CRT AMD Setup Confirmed ({direction.value}): {bias_str} Accumulation -> Manipulation -> Distribution",
            f"Accumulation: High={analysis.range_high:.5f}, Low={analysis.range_low:.5f}, Size=${range_size:.2f}",
            f"Manipulation: Extreme breach at {analysis.breach_point:.5f} ({analysis.manip_depth_pct:.1f}% depth >= {self.min_manip_pct:.1f}% min)",
            f"Distribution: Price closed back inside range at {current_price:.5f}",
            f"Retracement Entry: Mode={entry_res.entry_mode}, Zone=[{entry_res.zone_low:.2f}, {entry_res.zone_high:.2f}], Ideal={entry_res.ideal_entry:.2f}",
            f"Risk Profile: Entry={effective_entry:.5f}, SL={stop_loss:.5f} ({risk_pips:.1f} pips | ${actual_risk_dollars:.2f} risk), TP1={take_profit_1:.5f} ({rr_tp1:.1f} R:R)",
            f"Confluence Score: {total_score:.1f}/100 (Structure: {structure_score:.0f}/35, Liquidity: {liquidity_score:.0f}/40, PriceAction: {price_action_score:.0f}/25)",
        ])

        if risk_warning:
            reasons.append(f"WARNING: {risk_warning}")

        metadata: Dict[str, Any] = {
            "entry_price": round(effective_entry, 5),
            "stop_loss": round(stop_loss, 5),
            "take_profit_1": round(take_profit_1, 5),
            "take_profit_2": round(take_profit_2, 5),
            "risk_reward": rr_tp1,
            "risk_reward_tp1": rr_tp1,
            "risk_reward_tp2": rr_tp2,
            "risk_pips": risk_pips,
            "reward_pips_tp1": tp1_pips,
            "reward_pips_tp2": tp2_pips,
            "breach_point": analysis.breach_point,
            "manip_depth_pct": analysis.manip_depth_pct,
            "crt_analysis": analysis.model_dump(),
            "positive_direction": analysis.positive_direction,
            "htf_trend": resolved_htf_trend,
            "htf_trend_source": htf_trend_source,
            "setup_state": setup_state,
            "sweep_level_type": sweep_level_type,
            "nearest_obstacle": target_plan.obstacle_type,
            "session_name": session_name,
            "score_audit": score_audit,
            "suggested_lot_size": suggested_lots,
            "risk_amount_usd": actual_risk_dollars,
            "risk_warning": risk_warning,
            "sweep_event_key": sweep_event_key,
            "gatekeeper_passed": is_qualified,
            "quality_tier": quality_tier_res.tier,
            "quality_tier_label": quality_tier_res.tier_label,
            "should_alert_telegram": quality_tier_res.should_alert_telegram,
            "entry_zone": [entry_res.zone_low, entry_res.zone_high],
            "ideal_entry": entry_res.ideal_entry,
            "entry_mode": entry_res.entry_mode,
            "target_type": target_plan.target_type,
            "expires_at": expires_at,
            "expires_at_utc": expires_at_utc_str,
            "expires_at_utc7": expires_at_utc7_str,
            "lifecycle_state": lifecycle_res.current_state,
            "previous_state": lifecycle_res.previous_state,
            "transition_occurred": lifecycle_res.transition_occurred,
            "should_send_management_alert": lifecycle_res.should_send_management_alert,
            "daily_bias": daily_bias_res.bias,
            "premium_discount": daily_bias_res.premium_discount,
            "counter_trend_bypassed": counter_trend_bypassed,
            "trend_conflict": is_counter_trend and not counter_trend_bypassed,
        }

        # If not qualified, map direction to WAIT
        result_dir = direction if is_qualified else SignalDirection.WAIT

        if is_qualified and enable_dedup:
            self._emitted_sweep_events[sweep_event_key] = now_utc
            db_conn = kwargs.get("db")
            close_sess = False
            if db_conn is None:
                try:
                    from app.core.database import SessionLocal
                    db_conn = SessionLocal()
                    close_sess = True
                except Exception:
                    db_conn = None
            if db_conn is not None:
                try:
                    from app.models.crt_sweep_event import CRTSweepEvent
                    from app.core.database import engine, Base
                    Base.metadata.create_all(bind=engine, tables=[CRTSweepEvent.__table__])
                    cd_until = now_utc + timedelta(seconds=self.cooldown_seconds)
                    ev = db_conn.query(CRTSweepEvent).filter(CRTSweepEvent.sweep_key == sweep_event_key).first()
                    if ev is not None:
                        ev.emitted_at = now_utc
                        ev.cooldown_until = cd_until
                        ev.current_state = setup_state
                        ev.quality_tier = quality_tier_res.tier
                        ev.entry_price = effective_entry
                        ev.stop_loss = stop_loss
                        ev.take_profit_1 = take_profit_1
                        ev.take_profit_2 = take_profit_2
                        ev.zone_high = entry_res.zone_high
                        ev.zone_low = entry_res.zone_low
                        ev.expires_at = expires_at
                    else:
                        ev = CRTSweepEvent(
                            sweep_key=sweep_event_key,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction=direction.value,
                            emitted_at=now_utc,
                            cooldown_until=cd_until,
                            current_state=setup_state,
                            quality_tier=quality_tier_res.tier,
                            entry_price=effective_entry,
                            stop_loss=stop_loss,
                            take_profit_1=take_profit_1,
                            take_profit_2=take_profit_2,
                            zone_high=entry_res.zone_high,
                            zone_low=entry_res.zone_low,
                            expires_at=expires_at,
                        )
                        db_conn.add(ev)
                    db_conn.commit()
                except Exception as e:
                    if db_conn:
                        db_conn.rollback()
                    logger.debug(f"CRT DB dedup persistence: {e}")
                finally:
                    if close_sess and db_conn:
                        db_conn.close()

        result = StrategyResult(
            strategy_name=self.name,
            direction=result_dir,
            score=total_score if is_qualified else 0.0,
            reasons=reasons,
            metadata=metadata,
            score_breakdown=score_breakdown,
            entry_price=round(effective_entry, 5),
            stop_loss=round(stop_loss, 5),
            take_profit_1=round(take_profit_1, 5),
            take_profit_2=round(take_profit_2, 5),
            risk_reward=rr_tp1,
            breach_point=analysis.breach_point,
        )

        return result
