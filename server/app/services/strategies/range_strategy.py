"""Strategy C (Range Sniper) — Mean-Reversion Sideways/Ranging Market Strategy.

Captures high-probability mean-reversion trades within sideways/ranging markets,
complementing trend-following Smart Money Concepts (SMC) strategies.

Architecture:
    - ZERO API CALLS: Pure in-memory calculation based entirely on inputs.
    - READ-ONLY: No mutation of incoming candle, structure, or indicator data.
    - SCHEMA AWARENESS: Uses only verified fields from indicators and structure schemas.
    - PYDANTIC SAFETY: Strictly caps all scores within ScoreBreakdown bounds:
        * Structure: Max 30.0 pts
        * Liquidity: Max 25.0 pts
        * Indicators: Max 25.0 pts
        * Price Action: Max 20.0 pts
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.core.logging import logger
from app.schemas.indicators import (
    ATRSnapshot,
    EMASnapshot,
    IndicatorAnalysisResponse,
    PatternType,
    PriceActionPattern,
    RSISnapshot,
)
from app.schemas.liquidity import (
    AdvancedStructureAnalysisResponse,
    LiquidityEventType,
    LiquiditySweep,
    SupportResistanceZone,
    ZoneType,
)
from app.schemas.signal import ScoreBreakdown, SignalDirection
from app.schemas.structure import (
    MultiTimeframeStructureResponse,
    TrendDirection,
)
from app.services.strategies.base import BaseStrategy, StrategyResult


class RangeStrategy(BaseStrategy):
    """Strategy C: Mean-reversion range sniper for sideways market regimes.

    Identifies overextended price action (RSI oversold/overbought and EMA stretch)
    at key Support/Resistance boundaries confirmed by liquidity sweeps and
    reversal candlestick patterns.
    """

    def __init__(self, min_score_threshold: Optional[float] = None) -> None:
        self._min_score_threshold: float = (
            min_score_threshold if min_score_threshold is not None else settings.MIN_SETUP_SCORE
        )

    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Human-readable strategy identifier."""
        return "Strategy C (Range Sniper)"

    def analyze(
        self,
        symbol: str,
        timeframe: str,
        candles: Sequence[Any],
        indicators: IndicatorAnalysisResponse,
        structure: AdvancedStructureAnalysisResponse,
        mtf: Optional[MultiTimeframeStructureResponse] = None,
        candles_15m: Optional[Sequence[Any]] = None,
        **kwargs: Any,
    ) -> StrategyResult:
        """Evaluate BUY and SELL mean-reversion setups in ranging markets."""

        # --------------------------------------------------------------
        # 1. The "No Trend" Gatekeeper (Crucial)
        # --------------------------------------------------------------
        is_ranging = (
            structure.trend == TrendDirection.RANGING
            or str(structure.trend).upper() == "RANGING"
        )
        if not is_ranging:
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=0.0,
                reasons=["Market trending. Range strategy disabled."],
                metadata={
                    "trend": getattr(structure.trend, "value", str(structure.trend)),
                    "gatekeeper_passed": False,
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=0.0,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=0.0,
                    is_qualified=False,
                ),
            )

        # --------------------------------------------------------------
        # Determine Current Price (Read-only, no mutation)
        # --------------------------------------------------------------
        current_price: float = indicators.current_price
        if candles and len(candles) > 0:
            last_c = candles[-1]
            if hasattr(last_c, "close") and last_c.close is not None:
                current_price = float(last_c.close)
            elif isinstance(last_c, dict) and "close" in last_c and last_c["close"] is not None:
                current_price = float(last_c["close"])

        # --------------------------------------------------------------
        # 2. The Extremes Trigger (RSI Extremes + EMA Distance)
        # --------------------------------------------------------------
        rsi: Optional[RSISnapshot] = getattr(indicators, "rsi", None)
        rsi_val: Optional[float] = getattr(rsi, "rsi_value", None) if rsi else None
        rsi_cond: str = getattr(rsi, "condition", "").upper() if rsi else ""
        is_oversold: bool = getattr(rsi, "is_oversold", False) if rsi else False
        is_overbought: bool = getattr(rsi, "is_overbought", False) if rsi else False

        buy_rsi_extreme = (
            (rsi_val is not None and rsi_val < 30.0)
            or rsi_cond == "OVERSOLD"
            or is_oversold
        )
        sell_rsi_extreme = (
            (rsi_val is not None and rsi_val > 70.0)
            or rsi_cond == "OVERBOUGHT"
            or is_overbought
        )

        # Optional Enhancement: EMA 50 distance / overextension check
        ema: Optional[EMASnapshot] = getattr(indicators, "ema", None)
        ema_50 = getattr(ema, "ema_50", None)
        if ema_50 is None and ema is not None:
            ema_50 = getattr(ema, "ema_mid", None)

        buy_ema_overextended = self._check_ema_overextension(
            current_price=current_price,
            ema_value=ema_50,
            atr_snapshot=getattr(indicators, "atr", None),
            symbol=symbol,
        )
        sell_ema_overextended = self._check_ema_overextension(
            current_price=current_price,
            ema_value=ema_50,
            atr_snapshot=getattr(indicators, "atr", None),
            symbol=symbol,
        )

        # If neither BUY nor SELL extreme is active, return WAIT immediately
        if not buy_rsi_extreme and not sell_rsi_extreme:
            base_struct_score = 15.0  # Trend is RANGING (+15 pts)
            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=base_struct_score,
                reasons=[
                    "RSI in neutral range (mean-reversion trigger not active).",
                    f"Market State: {getattr(structure, 'market_state', 'RANGING')}",
                ],
                metadata={
                    "trend": "RANGING",
                    "rsi_value": rsi_val,
                    "rsi_condition": rsi_cond,
                    "current_price": current_price,
                    "gatekeeper_passed": True,
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=base_struct_score,
                    liquidity_score=0.0,
                    indicators_score=0.0,
                    price_action_score=0.0,
                    total_score=base_struct_score,
                    is_qualified=False,
                ),
            )

        # --------------------------------------------------------------
        # 3. Liquidity Sweep Confirmation (The SMC Edge)
        # --------------------------------------------------------------
        latest_sweep: Optional[LiquiditySweep] = getattr(structure, "latest_sweep", None)
        buy_sweep_confirmed = False
        sell_sweep_confirmed = False

        if latest_sweep is not None:
            sweep_type = latest_sweep.sweep_type
            sweep_val = getattr(sweep_type, "value", str(sweep_type))
            if sweep_val == LiquidityEventType.SELL_SIDE_SWEEP.value:
                buy_sweep_confirmed = True
            elif sweep_val == LiquidityEventType.BUY_SIDE_SWEEP.value:
                sell_sweep_confirmed = True

        # --------------------------------------------------------------
        # 4. Price Action Confirmation (The Safety Net)
        # --------------------------------------------------------------
        recent_patterns: List[PriceActionPattern] = getattr(indicators, "recent_patterns", []) or []
        immediate_patterns = recent_patterns[-3:]

        buy_pa_candidates = [
            p for p in immediate_patterns
            if p.pattern_type in (PatternType.BULLISH_PIN_BAR, PatternType.BULLISH_ENGULFING)
            or getattr(p.pattern_type, "value", str(p.pattern_type)) in (
                PatternType.BULLISH_PIN_BAR.value,
                PatternType.BULLISH_ENGULFING.value,
            )
        ]
        sell_pa_candidates = [
            p for p in immediate_patterns
            if p.pattern_type in (PatternType.BEARISH_PIN_BAR, PatternType.BEARISH_ENGULFING)
            or getattr(p.pattern_type, "value", str(p.pattern_type)) in (
                PatternType.BEARISH_PIN_BAR.value,
                PatternType.BEARISH_ENGULFING.value,
            )
        ]

        buy_best_pa: Optional[PriceActionPattern] = (
            max(buy_pa_candidates, key=lambda p: getattr(p, "confidence", 1.0))
            if buy_pa_candidates else None
        )
        sell_best_pa: Optional[PriceActionPattern] = (
            max(sell_pa_candidates, key=lambda p: getattr(p, "confidence", 1.0))
            if sell_pa_candidates else None
        )

        # --------------------------------------------------------------
        # 5. Support / Resistance Zone Proximity
        # --------------------------------------------------------------
        atr_val = getattr(indicators.atr, "atr_value", None) if getattr(indicators, "atr", None) else None
        key_support = getattr(structure.base_structure, "key_support", None) if hasattr(structure, "base_structure") else None
        key_resistance = getattr(structure.base_structure, "key_resistance", None) if hasattr(structure, "base_structure") else None

        near_support, supp_desc = self._is_near_sr_zone(
            price=current_price,
            sr_zones=getattr(structure, "sr_zones", []) or [],
            target_type=ZoneType.SUPPORT,
            atr_val=atr_val,
            key_level=key_support,
        )
        near_resistance, res_desc = self._is_near_sr_zone(
            price=current_price,
            sr_zones=getattr(structure, "sr_zones", []) or [],
            target_type=ZoneType.RESISTANCE,
            atr_val=atr_val,
            key_level=key_resistance,
        )

        # --------------------------------------------------------------
        # 6. Scoring & Breakdown Calculation
        # --------------------------------------------------------------
        # Determine candidate direction
        if buy_rsi_extreme and not sell_rsi_extreme:
            candidate_dir = SignalDirection.BUY
        elif sell_rsi_extreme and not buy_rsi_extreme:
            candidate_dir = SignalDirection.SELL
        else:
            # Symmetrical extreme edge-case: select side with better structural / PA alignment
            buy_edge = (15.0 if near_support else 0.0) + (25.0 if buy_sweep_confirmed else 0.0) + (20.0 if buy_best_pa else 0.0)
            sell_edge = (15.0 if near_resistance else 0.0) + (25.0 if sell_sweep_confirmed else 0.0) + (20.0 if sell_best_pa else 0.0)
            candidate_dir = SignalDirection.BUY if buy_edge >= sell_edge else SignalDirection.SELL

        if candidate_dir == SignalDirection.BUY:
            near_zone = near_support
            zone_desc = supp_desc
            sweep_confirmed = buy_sweep_confirmed
            ema_overextended = buy_ema_overextended
            best_pa = buy_best_pa
            opposing_pa_req = "BULLISH_PIN_BAR or BULLISH_ENGULFING"
        else:
            near_zone = near_resistance
            zone_desc = res_desc
            sweep_confirmed = sell_sweep_confirmed
            ema_overextended = sell_ema_overextended
            best_pa = sell_best_pa
            opposing_pa_req = "BEARISH_PIN_BAR or BEARISH_ENGULFING"

        # Structure Score (Max 30): 15 pts for RANGING, +15 pts if near key S/R zone
        raw_struct_score = 15.0 + (15.0 if near_zone else 0.0)
        structure_score = round(max(0.0, min(30.0, raw_struct_score)), 1)

        # Liquidity Score (Max 25): 25 pts if sweep matches direction, 0 otherwise
        raw_liq_score = 25.0 if sweep_confirmed else 0.0
        liquidity_score = round(max(0.0, min(25.0, raw_liq_score)), 1)

        # Indicators Score (Max 25): 15 pts for RSI Extreme, +10 pts for EMA overextension
        raw_ind_score = 15.0 + (10.0 if ema_overextended else 0.0)
        indicators_score = round(max(0.0, min(25.0, raw_ind_score)), 1)

        # Price Action Score (Max 20): 20 pts * confidence if reversal pattern found
        raw_pa_score = (20.0 * getattr(best_pa, "confidence", 1.0)) if best_pa else 0.0
        price_action_score = round(max(0.0, min(20.0, raw_pa_score)), 1)

        total_score = round(
            max(0.0, min(100.0, structure_score + liquidity_score + indicators_score + price_action_score)),
            1,
        )

        # --------------------------------------------------------------
        # Gate: Price Action Confirmation is Required
        # --------------------------------------------------------------
        if best_pa is None:
            reasons = [
                f"Market Ranging (Structure: {structure_score:.1f}/30.0 pts).",
                f"RSI Extreme detected ({rsi_cond}, RSI: {rsi_val:.1f} - Indicators: {indicators_score:.1f}/25.0 pts).",
            ]
            if near_zone and zone_desc:
                reasons.append(f"S/R Confluence: {zone_desc}.")
            if sweep_confirmed and latest_sweep:
                sweep_name = getattr(latest_sweep.sweep_type, "value", str(latest_sweep.sweep_type))
                reasons.append(f"Liquidity Sweep: {sweep_name} (+25.0 pts).")
            reasons.append(f"No price action confirmation (requires {opposing_pa_req} in last 3 candles).")

            return StrategyResult(
                strategy_name=self.name,
                direction=SignalDirection.WAIT,
                score=total_score,
                reasons=reasons,
                metadata={
                    "trend": "RANGING",
                    "candidate_direction": candidate_dir.value,
                    "rsi_value": rsi_val,
                    "rsi_condition": rsi_cond,
                    "current_price": current_price,
                    "ema_50": ema_50,
                    "ema_overextended": ema_overextended,
                    "near_sr_zone": near_zone,
                    "sweep_confirmed": sweep_confirmed,
                    "price_action_confirmed": False,
                },
                score_breakdown=ScoreBreakdown(
                    structure_score=structure_score,
                    liquidity_score=liquidity_score,
                    indicators_score=indicators_score,
                    price_action_score=0.0,
                    total_score=total_score,
                    is_qualified=False,
                ),
            )

        # --------------------------------------------------------------
        # Score Qualification Filter
        # --------------------------------------------------------------
        is_qualified = total_score >= self._min_score_threshold

        reasons = [
            f"Strategy: {self.name} ({candidate_dir.value} Mean Reversion)",
            f"Market Structure: RANGING consolidation (+15.0 pts)",
        ]
        if near_zone and zone_desc:
            reasons.append(f"Key S/R Confluence: {zone_desc} (+15.0 pts)")
        if sweep_confirmed and latest_sweep:
            sweep_name = getattr(latest_sweep.sweep_type, "value", str(latest_sweep.sweep_type))
            reasons.append(f"Liquidity Sweep Confirmation: {sweep_name} (+25.0 pts)")
        reasons.append(f"RSI Extreme: {rsi_cond} (RSI: {rsi_val:.1f}) (+15.0 pts)")
        if ema_overextended:
            reasons.append("EMA Overextension: Price stretched from 50 EMA (> 1.5x ATR) (+10.0 pts)")

        pa_name = getattr(best_pa.pattern_type, "value", str(best_pa.pattern_type))
        reasons.append(f"Price Action Confirmation: {pa_name} (conf: {best_pa.confidence:.2f}) (+{price_action_score:.1f} pts)")

        if not is_qualified:
            final_dir = SignalDirection.WAIT
            reasons.insert(0, f"Range setup score {total_score:.1f}/100 below qualifying threshold ({self._min_score_threshold:.1f}).")
        else:
            final_dir = candidate_dir

        return StrategyResult(
            strategy_name=self.name,
            direction=final_dir,
            score=total_score,
            reasons=reasons,
            metadata={
                "trend": "RANGING",
                "direction": final_dir.value,
                "candidate_direction": candidate_dir.value,
                "rsi_value": rsi_val,
                "rsi_condition": rsi_cond,
                "current_price": current_price,
                "ema_50": ema_50,
                "ema_overextended": ema_overextended,
                "near_sr_zone": near_zone,
                "sweep_confirmed": sweep_confirmed,
                "reversal_pattern": pa_name,
                "pattern_confidence": best_pa.confidence,
                "is_qualified": is_qualified,
            },
            score_breakdown=ScoreBreakdown(
                structure_score=structure_score,
                liquidity_score=liquidity_score,
                indicators_score=indicators_score,
                price_action_score=price_action_score,
                total_score=total_score,
                is_qualified=is_qualified,
            ),
        )

    # ------------------------------------------------------------------
    # Analytical Helper Functions (Zero-API, Pure, Read-Only)
    # ------------------------------------------------------------------

    @staticmethod
    def _check_ema_overextension(
        current_price: float,
        ema_value: Optional[float],
        atr_snapshot: Optional[ATRSnapshot],
        symbol: str,
    ) -> bool:
        """Check if price is significantly overextended from EMA 50 (> 1.5 * ATR)."""
        if ema_value is None or atr_snapshot is None:
            return False

        price_diff = abs(current_price - ema_value)

        # Pip multiplier for asset class
        s = symbol.upper()
        pip_size = 0.01 if ("JPY" in s or "XAU" in s or "GOLD" in s) else 0.0001

        atr_val = getattr(atr_snapshot, "atr_value", None)
        atr_pips = getattr(atr_snapshot, "atr_pips", None)

        if atr_val is None and atr_pips is not None:
            atr_val = atr_pips * pip_size

        if atr_val is not None and atr_val > 0:
            threshold_price = 1.5 * atr_val
            if price_diff > threshold_price:
                return True

        if atr_pips is not None and atr_pips > 0:
            distance_pips = price_diff / pip_size
            if distance_pips > 1.5 * atr_pips:
                return True
            if price_diff > 1.5 * atr_pips:
                return True

        return False

    @staticmethod
    def _is_near_sr_zone(
        price: float,
        sr_zones: Sequence[SupportResistanceZone],
        target_type: ZoneType,
        atr_val: Optional[float] = None,
        key_level: Optional[float] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Verify if current price is within or near a target S/R zone or key structural extreme."""
        target_str = target_type.value if hasattr(target_type, "value") else str(target_type)
        matching_zones = [
            z for z in sr_zones
            if z.zone_type == target_type or getattr(z.zone_type, "value", str(z.zone_type)) == target_str
        ]

        for z in matching_zones:
            # 1. Price is inside the zone boundaries
            if z.price_low <= price <= z.price_high:
                return True, f"Price inside {target_str} zone [{z.price_low:.5f} - {z.price_high:.5f}]"

            # 2. Price is within proximity buffer of zone
            zone_width = abs(z.price_high - z.price_low)
            buffer = max(
                zone_width * 1.5,
                (atr_val * 0.5) if (atr_val and atr_val > 0) else (price * 0.001),
            )
            if (
                abs(price - z.center_price) <= buffer
                or abs(price - z.price_low) <= buffer
                or abs(price - z.price_high) <= buffer
            ):
                return True, f"Price near {target_str} zone [{z.price_low:.5f} - {z.price_high:.5f}]"

        # 3. Fallback: Check key structural extreme level
        if key_level is not None:
            buffer = (atr_val * 0.75) if (atr_val and atr_val > 0) else (price * 0.002)
            if abs(price - key_level) <= buffer:
                return True, f"Price near key structural {target_str.lower()} ({key_level:.5f})"

        return False, None
