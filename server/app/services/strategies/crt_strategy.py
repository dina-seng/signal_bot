"""Strategy D (Candle Range Theory) — AMD Accumulation, Manipulation, Distribution Strategy.

A modular, standalone strategy based on the institutional AMD framework:
- Accumulation: Benchmark range set by a completed higher timeframe candle (e.g. 1H).
- Manipulation: Liquidity sweep breaching the range boundary on a lower timeframe (e.g. 15m)
  by at least `min_manip_pct` depth and satisfying minimum ATR/spread threshold.
- Distribution: Confirmed when lower timeframe candle(s) close back inside the benchmark range
  with displacement or market structure shift (MSS).

Risk Management:
- Entry: Current market price.
- Stop Loss: Extreme manipulation wick plus buffer, extended beyond any adjacent liquidity pool.
- Take Profit 1 & 2: Structure-based targets (nearest opposing liquidity) or dynamic 1.5R / 2.5R,
  capped before any opposing unmitigated FVG or Order Block.
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

    Allowed windows (America/New_York):
    - Asian Session: 18:00 - 00:00 NY
    - London Session: 03:00 - 07:00 NY
    - New York Morning: 09:30 - 10:30 NY
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

    # Asian Session: 18:00 to 23:59:59 (or 00:00 midnight)
    if ny_time >= dtime(18, 0) or ny_time == dtime(0, 0):
        return True, "Asian Session"
    # London Session: 03:00 to 07:00
    if dtime(3, 0) <= ny_time <= dtime(7, 0):
        return True, "London Session"
    # New York Morning: 09:30 to 10:30
    if dtime(9, 30) <= ny_time <= dtime(10, 30):
        return True, "New York Session"

    return False, f"Off-Session ({ny_time.strftime('%H:%M')} NY)"


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
        max_range_atr_mult: float = 35.0,
        max_risk_atr_mult: float = 8.0,
        pip_size: float = 0.10,
        spread: float = 0.0,
        cooldown_seconds: float = 7200.0,
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
        self.session_filter_enabled = session_filter_enabled
        self.min_sweep_atr_mult = min_sweep_atr_mult if min_sweep_atr_mult != 0.15 else 0.08
        self.min_disp_atr_mult = min_disp_atr_mult
        self.min_range_atr_mult = min_range_atr_mult
        self.max_range_atr_mult = max_range_atr_mult if max_range_atr_mult != 4.5 else 35.0
        self.max_risk_atr_mult = max_risk_atr_mult
        self.pip_size = pip_size
        self.spread = spread
        self.cooldown_seconds = cooldown_seconds

        # Deduplication cache for emitted sweep event keys: key -> emit_timestamp
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
            elif candles_15m is not None and len(candles_15m) > 0 and candles is not candles_15m:
                # Primary candles represent the HTF range (1H), candles_15m represents the LTF
                r_candles = candles
                if c_candles is None:
                    c_candles = candles_15m
            elif timeframe in ("1h", "4h") and candles is not None and len(candles) > 0:
                r_candles = candles
                if c_candles is None:
                    c_candles = candles_15m

        if c_candles is None:
            c_candles = candles_15m if candles_15m is not None else candles

        # Fix 3: SILENT CANDLE FALLBACK CHECK
        # Missing HTF range candles or using LTF as range must return WAIT with an explicit reason.
        if r_candles is None or len(r_candles) == 0 or (r_candles is c_candles and timeframe not in ("1h", "4h")):
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    "WAIT: Missing HTF accumulation range candles. CRT requires a completed higher timeframe benchmark candle (e.g. 1H or 4H); silent fallback to LTF is disabled."
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
        # 5. Qualification Gates (Hard, before scoring) (Enhancement B)
        # ------------------------------------------------------------------
        reasons: List[str] = []
        score_audit: List[Dict[str, Any]] = []

        # Check Session Gate
        enforce_session = kwargs.get("enforce_session", self.session_filter_enabled)
        is_session_open, session_name = is_in_trading_session(latest_ts)
        if enforce_session and not is_session_open:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    f"WAIT (Session Gate): Outside allowed institutional trading sessions (Asia 18:00-00:00 NY, London 03:00-07:00 NY, NY 09:30-10:30 NY). Current status: {session_name}."
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

        # HTF Trend Conflict Gate (Block counter-trend setups)
        if resolved_htf_trend == "BEARISH" and direction == SignalDirection.BUY:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    f"REJECTED (Trend Conflict): HTF Trend is BEARISH. Ignoring Bullish CRT setup."
                ],
                metadata={
                    "setup_state": "NO_SETUP",
                    "gatekeeper_passed": False,
                    "trend_conflict": True,
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

        if resolved_htf_trend == "BULLISH" and direction == SignalDirection.SELL:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=[
                    f"REJECTED (Trend Conflict): HTF Trend is BULLISH. Ignoring Bearish CRT setup."
                ],
                metadata={
                    "setup_state": "NO_SETUP",
                    "gatekeeper_passed": False,
                    "trend_conflict": True,
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

        # Minimum Sweep Size Gate (Absolute dollars and ATR fraction)
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

        # Confirmation State Gate
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
        # 6. Stop Loss & Take Profit Target Calculation (Enhancements C & D)
        # ------------------------------------------------------------------
        # Buffer is added beyond sweep extreme: max(spread, 0.10 * ATR)
        sl_buffer = max(self.spread, 0.10 * effective_atr) if (self.spread > 0 or effective_atr > 0) else 0.0

        if direction == SignalDirection.BUY:
            raw_sl = analysis.breach_point - sl_buffer
            # Protect beyond nearby liquidity pool / swing low if present
            if structure is not None and structure.liquidity_pools:
                for pool in structure.liquidity_pools:
                    if pool.pool_type == LiquidityEventType.EQUAL_LOWS and pool.price_level < current_price:
                        if abs(pool.price_level - analysis.breach_point) <= 1.0 * (effective_atr or 5.0):
                            raw_sl = min(raw_sl, pool.price_level - sl_buffer)
            stop_loss = round(raw_sl, 5)

            # Fix 4: Direction / Risk Validation (No abs() masking)
            if stop_loss >= current_price:
                return StrategyResult(
                    strategy_name=self.name,
                    direction=SignalDirection.WAIT,
                    score=0.0,
                    reasons=[
                        f"REJECTED (Invalid Risk Geometry): BUY Stop Loss ({stop_loss:.5f}) >= Entry Price ({current_price:.5f})."
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

            # Check if price has broken below breach extreme before entry
            if current_price <= analysis.breach_point:
                return StrategyResult(
                    strategy_name=self.name,
                    direction=SignalDirection.WAIT,
                    score=0.0,
                    reasons=["INVALIDATED: Price broke below the manipulation extreme before entry."],
                    metadata={
                        "setup_state": "INVALIDATED_SETUP",
                        "gatekeeper_passed": False,
                        "rejection_gate": "SWEEP_EXTREME_BROKEN",
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

            risk_distance = current_price - stop_loss
            base_tp1 = current_price + (risk_distance * 1.5)
            base_tp2 = current_price + (risk_distance * 2.5)

        else:  # SELL
            raw_sl = analysis.breach_point + sl_buffer
            # Protect beyond nearby liquidity pool / swing high if present
            if structure is not None and structure.liquidity_pools:
                for pool in structure.liquidity_pools:
                    if pool.pool_type == LiquidityEventType.EQUAL_HIGHS and pool.price_level > current_price:
                        if abs(pool.price_level - analysis.breach_point) <= 1.0 * (effective_atr or 5.0):
                            raw_sl = max(raw_sl, pool.price_level + sl_buffer)
            stop_loss = round(raw_sl, 5)

            # Fix 4: Direction / Risk Validation (No abs() masking)
            if stop_loss <= current_price:
                return StrategyResult(
                    strategy_name=self.name,
                    direction=SignalDirection.WAIT,
                    score=0.0,
                    reasons=[
                        f"REJECTED (Invalid Risk Geometry): SELL Stop Loss ({stop_loss:.5f}) <= Entry Price ({current_price:.5f})."
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

            if current_price >= analysis.breach_point:
                return StrategyResult(
                    strategy_name=self.name,
                    direction=SignalDirection.WAIT,
                    score=0.0,
                    reasons=["INVALIDATED: Price broke above the manipulation extreme before entry."],
                    metadata={
                        "setup_state": "INVALIDATED_SETUP",
                        "gatekeeper_passed": False,
                        "rejection_gate": "SWEEP_EXTREME_BROKEN",
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

            risk_distance = stop_loss - current_price
            base_tp1 = current_price - (risk_distance * 1.5)
            base_tp2 = current_price - (risk_distance * 2.5)

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
        # Clear Path & Take Profit Capping before Opposing OB/FVG
        # ------------------------------------------------------------------
        nearest_obstacle_price: Optional[float] = None
        nearest_obstacle_desc: Optional[str] = None

        if direction == SignalDirection.BUY:
            # Check Bearish FVGs above entry
            if indicators is not None and indicators.active_fvgs:
                for fvg in indicators.active_fvgs:
                    if fvg.fvg_type == FVGType.BEARISH_FVG and not fvg.is_mitigated and fvg.bottom_price > current_price:
                        if nearest_obstacle_price is None or fvg.bottom_price < nearest_obstacle_price:
                            nearest_obstacle_price = fvg.bottom_price
                            nearest_obstacle_desc = f"Bearish FVG at {fvg.bottom_price:.2f}"
            # Check Resistance zones above entry
            if structure is not None and structure.sr_zones:
                for sr in structure.sr_zones:
                    if sr.zone_type == ZoneType.RESISTANCE and sr.price_low > current_price:
                        if nearest_obstacle_price is None or sr.price_low < nearest_obstacle_price:
                            nearest_obstacle_price = sr.price_low
                            nearest_obstacle_desc = f"Resistance Zone at {sr.price_low:.2f}"

            take_profit_1 = base_tp1
            take_profit_2 = base_tp2

            if nearest_obstacle_price is not None:
                dist_to_obs = nearest_obstacle_price - current_price
                obs_r = dist_to_obs / max(1e-6, risk_distance)
                if obs_r < 1.0:
                    return StrategyResult(
                        strategy_name=self.name,
                        direction=SignalDirection.WAIT,
                        score=0.0,
                        reasons=[
                            f"WAIT (Clear Path Blocked): Opposing {nearest_obstacle_desc} is only {obs_r:.2f}R from entry (< 1.0R minimum clear path required)."
                        ],
                        metadata={
                            "setup_state": "POTENTIAL_SETUP",
                            "gatekeeper_passed": False,
                            "rejection_gate": "PATH_BLOCKED",
                            "nearest_obstacle": nearest_obstacle_desc,
                            "obstacle_r": round(obs_r, 2),
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
                elif nearest_obstacle_price < take_profit_1:
                    take_profit_1 = round(nearest_obstacle_price - sl_buffer, 5)
                    reasons.append(f"TP1 capped before opposing {nearest_obstacle_desc}.")

        else:  # SELL
            # Check Bullish FVGs below entry
            if indicators is not None and indicators.active_fvgs:
                for fvg in indicators.active_fvgs:
                    if fvg.fvg_type == FVGType.BULLISH_FVG and not fvg.is_mitigated and fvg.top_price < current_price:
                        if nearest_obstacle_price is None or fvg.top_price > nearest_obstacle_price:
                            nearest_obstacle_price = fvg.top_price
                            nearest_obstacle_desc = f"Bullish FVG at {fvg.top_price:.2f}"
            # Check Support zones below entry
            if structure is not None and structure.sr_zones:
                for sr in structure.sr_zones:
                    if sr.zone_type == ZoneType.SUPPORT and sr.price_high < current_price:
                        if nearest_obstacle_price is None or sr.price_high > nearest_obstacle_price:
                            nearest_obstacle_price = sr.price_high
                            nearest_obstacle_desc = f"Support Zone at {sr.price_high:.2f}"

            take_profit_1 = base_tp1
            take_profit_2 = base_tp2

            if nearest_obstacle_price is not None:
                dist_to_obs = current_price - nearest_obstacle_price
                obs_r = dist_to_obs / max(1e-6, risk_distance)
                if obs_r < 1.0:
                    return StrategyResult(
                        strategy_name=self.name,
                        direction=SignalDirection.WAIT,
                        score=0.0,
                        reasons=[
                            f"WAIT (Clear Path Blocked): Opposing {nearest_obstacle_desc} is only {obs_r:.2f}R from entry (< 1.0R minimum clear path required)."
                        ],
                        metadata={
                            "setup_state": "POTENTIAL_SETUP",
                            "gatekeeper_passed": False,
                            "rejection_gate": "PATH_BLOCKED",
                            "nearest_obstacle": nearest_obstacle_desc,
                            "obstacle_r": round(obs_r, 2),
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
                elif nearest_obstacle_price > take_profit_1:
                    take_profit_1 = round(nearest_obstacle_price + sl_buffer, 5)
                    reasons.append(f"TP1 capped before opposing {nearest_obstacle_desc}.")

        # Real R:R computations
        rr_tp1 = round(abs(take_profit_1 - current_price) / max(1e-6, risk_distance), 2)
        rr_tp2 = round(abs(take_profit_2 - current_price) / max(1e-6, risk_distance), 2)

        # ------------------------------------------------------------------
        # 7. Deduplication (Enhancement F)
        # ------------------------------------------------------------------
        range_open_ts_str = str(analysis.range_open_timestamp or "0")
        breach_ts_str = str(analysis.breach_timestamp or "0")
        sweep_event_key = f"{symbol}_{timeframe}_{direction.value}_{range_open_ts_str}_{breach_ts_str}"

        now_utc = datetime.now(timezone.utc)
        if sweep_event_key in self._emitted_sweep_events:
            prev_time = self._emitted_sweep_events[sweep_event_key]
            if (now_utc - prev_time).total_seconds() < self.cooldown_seconds:
                return StrategyResult(
                    strategy_name=self.name,
                    direction=SignalDirection.WAIT,
                    score=0.0,
                    reasons=[f"DEDUPLICATED: Repeat signal for sweep event {sweep_event_key} suppressed by cooldown."],
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
        # 8. Auditable 3-Pillar Scoring Engine (Enhancement A)
        # ------------------------------------------------------------------
        # Pillar 1: Structure & MTF (Max 35)
        structure_score = 0.0
        aligned_trend = "BULLISH" if direction == SignalDirection.BUY else "BEARISH"
        # 1.1 HTF 1H Alignment (max 12)
        if trend_1h == aligned_trend:
            structure_score += 12.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "1H Alignment", "points": 12.0, "max": 12.0, "reason": f"1H Trend is aligned ({trend_1h})"})
        elif trend_1h == "RANGING":
            structure_score += 8.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "1H Alignment", "points": 8.0, "max": 12.0, "reason": "1H Trend is RANGING (Partial credit)"})
        else:
            score_audit.append({"pillar": "Structure & MTF", "rule": "1H Alignment", "points": 0.0, "max": 12.0, "reason": f"1H Trend opposes ({trend_1h})"})

        # 1.2 HTF 4H Alignment (max 8)
        if trend_4h == aligned_trend:
            structure_score += 8.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "4H Alignment", "points": 8.0, "max": 8.0, "reason": f"4H Trend is aligned ({trend_4h})"})
        elif trend_4h == "RANGING":
            structure_score += 6.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "4H Alignment", "points": 6.0, "max": 8.0, "reason": "4H Trend is RANGING (Partial credit)"})
        else:
            score_audit.append({"pillar": "Structure & MTF", "rule": "4H Alignment", "points": 0.0, "max": 8.0, "reason": f"4H Trend opposes ({trend_4h})"})

        # 1.3 MSS / CHoCH after sweep (max 8)
        has_mss = False
        if structure is not None and structure.choch_events:
            for ev in structure.choch_events:
                if (direction == SignalDirection.BUY and ev.event_type == BOSCHOCHType.BULLISH_CHOCH) or (
                    direction == SignalDirection.SELL and ev.event_type == BOSCHOCHType.BEARISH_CHOCH
                ):
                    has_mss = True
                    break
        if has_mss:
            structure_score += 8.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "MSS / CHoCH", "points": 8.0, "max": 8.0, "reason": "Confirmed Market Structure Shift (CHoCH) after sweep"})
        else:
            structure_score += 6.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "MSS / CHoCH", "points": 6.0, "max": 8.0, "reason": "Clean AMD reversal structure"})

        # 1.4 Displacement candle strength (max 4)
        disp_body = analysis.confirmation_displacement
        if effective_atr > 0.0 and disp_body >= 0.30 * effective_atr:
            structure_score += 5.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "Displacement Strength", "points": 5.0, "max": 5.0, "reason": f"Strong confirmation displacement (${disp_body:.2f} >= 0.3x ATR)"})
        elif disp_body > 0:
            structure_score += 5.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "Displacement Strength", "points": 5.0, "max": 5.0, "reason": f"Clean confirmation displacement (${disp_body:.2f})"})
        else:
            structure_score += 3.0
            score_audit.append({"pillar": "Structure & MTF", "rule": "Displacement Strength", "points": 3.0, "max": 5.0, "reason": "Baseline displacement"})

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
        sweep_level_type = "Benchmark Range Extreme"
        level_points = 14.0
        if structure is not None and structure.liquidity_pools:
            for pool in structure.liquidity_pools:
                if (direction == SignalDirection.BUY and pool.pool_type == LiquidityEventType.EQUAL_LOWS) or (
                    direction == SignalDirection.SELL and pool.pool_type == LiquidityEventType.EQUAL_HIGHS
                ):
                    if abs(pool.price_level - swept_edge) <= 1.0 * (effective_atr or 5.0):
                        sweep_level_type = "Equal Highs/Lows Liquidity Pool"
                        level_points = 18.0
                        break

        if sweep_level_type == "Benchmark Range Extreme" and structure is not None and structure.base_structure.swing_points:
            for sp in structure.base_structure.swing_points:
                if abs(sp.price - swept_edge) <= 1.0 * (effective_atr or 5.0):
                    sweep_level_type = f"Confirmed {sp.swing_type.value}"
                    level_points = 16.0
                    break

        liquidity_score += level_points
        score_audit.append({"pillar": "Liquidity & POIs", "rule": "Swept Level", "points": level_points, "max": 18.0, "reason": f"Swept level: {sweep_level_type}"})

        # 2.2 Entry inside/near valid FVG or Order Block (max 12)
        poi_points = 8.0
        poi_reason = "Benchmark accumulation manipulation zone"
        if indicators is not None and indicators.active_fvgs:
            for fvg in indicators.active_fvgs:
                if (direction == SignalDirection.BUY and fvg.fvg_type == FVGType.BULLISH_FVG) or (
                    direction == SignalDirection.SELL and fvg.fvg_type == FVGType.BEARISH_FVG
                ):
                    if not fvg.is_mitigated:
                        if fvg.bottom_price <= current_price <= fvg.top_price:
                            poi_points = 12.0
                            poi_reason = "Entry sitting directly inside fresh aligned FVG"
                            break
                        elif abs(current_price - (fvg.top_price if direction == SignalDirection.BUY else fvg.bottom_price)) <= 0.5 * risk_distance:
                            poi_points = 10.0
                            poi_reason = "Entry adjacent to fresh aligned FVG"
                            break

        liquidity_score += poi_points
        score_audit.append({"pillar": "Liquidity & POIs", "rule": "POI Proximity", "points": poi_points, "max": 12.0, "reason": poi_reason})

        # 2.3 Clean path to target (max 10)
        if nearest_obstacle_price is None:
            liquidity_score += 10.0
            score_audit.append({"pillar": "Liquidity & POIs", "rule": "Clean Path", "points": 10.0, "max": 10.0, "reason": "Unobstructed path to targets (No opposing unmitigated zones)"})
        else:
            obs_r = abs(nearest_obstacle_price - current_price) / max(1e-6, risk_distance)
            if obs_r >= 2.0:
                liquidity_score += 8.0
                score_audit.append({"pillar": "Liquidity & POIs", "rule": "Clean Path", "points": 8.0, "max": 10.0, "reason": f"Generous clear path ({obs_r:.1f}R to {nearest_obstacle_desc})"})
            elif obs_r >= 1.2:
                liquidity_score += 6.0
                score_audit.append({"pillar": "Liquidity & POIs", "rule": "Clean Path", "points": 6.0, "max": 10.0, "reason": f"Adequate clear path ({obs_r:.1f}R to {nearest_obstacle_desc})"})
            else:
                liquidity_score += 3.0
                score_audit.append({"pillar": "Liquidity & POIs", "rule": "Clean Path", "points": 3.0, "max": 10.0, "reason": f"Tight obstacle margin ({obs_r:.1f}R to {nearest_obstacle_desc})"})

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
        if nearest_obstacle_price is not None:
            obs_r = abs(nearest_obstacle_price - current_price) / max(1e-6, risk_distance)
            if obs_r < 1.2:
                penalties += 5.0
                score_audit.append({"pillar": "Penalties", "rule": "Near Obstacle", "points": -5.0, "max": 0.0, "reason": f"Obstacle at {obs_r:.2f}R (< 1.2R)"})

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
        # 9. Position Sizing & Pips Math (Fixes 5 & 6)
        # ------------------------------------------------------------------
        contract_size = 100.0
        broker_step = 0.01
        min_lot = 0.01

        account_balance = float(kwargs.get("account_balance", 10000.0))
        risk_percent = float(kwargs.get("risk_percent", 0.5))

        stop_distance_dollars = round(abs(current_price - stop_loss), 5)
        risk_pips = round(stop_distance_dollars / self.pip_size, 1)
        tp1_pips = round(abs(take_profit_1 - current_price) / self.pip_size, 1)
        tp2_pips = round(abs(take_profit_2 - current_price) / self.pip_size, 1)

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
        # 10. Assemble Strategy Result & Setup State
        # ------------------------------------------------------------------
        setup_state = "CONFIRMED_SETUP" if is_qualified else "POTENTIAL_SETUP"

        bias_str = "BULLISH" if direction == SignalDirection.BUY else "BEARISH"
        reasons.extend([
            f"CRT AMD Setup Confirmed ({direction.value}): {bias_str} Accumulation -> Manipulation -> Distribution",
            f"Accumulation: High={analysis.range_high:.5f}, Low={analysis.range_low:.5f}, Size=${range_size:.2f}",
            f"Manipulation: Extreme breach at {analysis.breach_point:.5f} ({analysis.manip_depth_pct:.1f}% depth >= {self.min_manip_pct:.1f}% min)",
            f"Distribution: Price closed back inside range at {current_price:.5f}",
            f"Risk Profile: Entry={current_price:.5f}, SL={stop_loss:.5f} ({risk_pips:.1f} pips | ${actual_risk_dollars:.2f} risk), TP1={take_profit_1:.5f} ({rr_tp1:.1f} R:R)",
            f"Confluence Score: {total_score:.1f}/100 (Structure: {structure_score:.0f}/35, Liquidity: {liquidity_score:.0f}/40, PriceAction: {price_action_score:.0f}/25)",
        ])

        if risk_warning:
            reasons.append(f"WARNING: {risk_warning}")

        metadata: Dict[str, Any] = {
            "entry_price": round(current_price, 5),
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
            "nearest_obstacle": nearest_obstacle_desc,
            "session_name": session_name,
            "score_audit": score_audit,
            "suggested_lot_size": suggested_lots,
            "risk_amount_usd": actual_risk_dollars,
            "risk_warning": risk_warning,
            "sweep_event_key": sweep_event_key,
            "gatekeeper_passed": is_qualified,
        }

        # If not qualified, map direction to WAIT
        result_dir = direction if is_qualified else SignalDirection.WAIT

        if is_qualified:
            self._emitted_sweep_events[sweep_event_key] = now_utc

        result = StrategyResult(
            strategy_name=self.name,
            direction=result_dir,
            score=total_score if is_qualified else 0.0,
            reasons=reasons,
            metadata=metadata,
            score_breakdown=score_breakdown,
            entry_price=round(current_price, 5),
            stop_loss=round(stop_loss, 5),
            take_profit_1=round(take_profit_1, 5),
            take_profit_2=round(take_profit_2, 5),
            risk_reward=rr_tp1,
            breach_point=analysis.breach_point,
        )

        return result
