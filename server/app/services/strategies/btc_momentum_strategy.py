"""BTC/USD Momentum Strategy — fresh crossover events + ADX regime gate.

Pluggable ``BaseStrategy`` implementation for 1h/4h BTC/USD. A signal is only
considered on the bar where a FRESH momentum event occurs:

    - BUY: RSI(14) crosses ABOVE 55 or EMA50 crosses ABOVE EMA200.
    - SELL: RSI(14) crosses BELOW 45 or EMA50 crosses BELOW EMA200.

EMA alignment and price location are confirmations that award score points;
they are never standalone triggers. ADX(14) below 25 rejects ranging markets.

Scoring (per direction, graded 0-100 sub-scores):
    - EMA stack / price location:        40% weight
    - RSI(14) context vs trend:          30% weight
    - ADX(14) trend strength:            30% weight

The old boolean 40+35+25 pills always summed to exactly 100 on a perfectly
aligned bar; ``confluence_scoring`` now grades each pillar so the displayed
score is dynamic and 100/100 is structurally unreachable.

This strategy never places SL/TP itself: the Signal Engine supplies the entry
and the Risk Engine resolves levels, as with every other registered strategy.

Academic basis (Proelss et al. (2025), "Do risk preferences drive momentum in
cryptocurrencies?"):
    BTC and ETH are the large-cap segment where the paper finds significant
    positive momentum (beta_1 = 0.34 at 30d and 0.173 at 7d), attributed to
    institutional investors with higher risk aversion. Small- and mid-cap
    cryptocurrencies instead show significant REVERSAL (contrarian) effects
    because retail investors with lower risk aversion engage in noisy trading.
    This is the academic justification for restricting the strategy to BTC/USD:
    target the momentum-confirmed large-cap universe and avoid the
    reversal-prone small/mid-cap universe.

Timeframe disclaimer:
    The paper tests 7-day, 30-day, weekly, and monthly horizons. It provides NO
    empirical evidence for 1H intraday momentum. The 1H timeframe is a purely
    empirical engineering choice to capture shorter-term trend persistence.
    The 4h execution timeframe is likewise an engineering choice, not tested by
    the paper. EMA50/EMA200, RSI(14) and the ADX(14) gate are also heuristics;
    they are validated empirically by the backtest, not by the paper.

Paper filters vs. this implementation:
    The paper's pump-and-dump filter excludes assets whose absolute DAILY log
    returns are >= 2 (approximately a 639% daily move) in more than 10% of
    observations. Its liquidity filter requires at least $10,000 daily trading
    volume or a $5M market cap. Our 5% hourly price-change cap and per-bar
    volume floor are HEURISTIC PROXIES adapted to intraday data, NOT the exact
    filters from the paper. They are execution sanity checks only.
"""

from typing import Any, Optional, Sequence

from app.schemas.indicators import IndicatorAnalysisResponse
from app.schemas.liquidity import AdvancedStructureAnalysisResponse
from app.schemas.signal import ScoreBreakdown, SignalDirection
from app.schemas.structure import MultiTimeframeStructureResponse
from app.services.indicators.adx_calculator import ADXCalculator
from app.services.signals.confluence_scoring import (
    ADX_WEIGHT,
    EMA_WEIGHT,
    RSI_WEIGHT,
    ConfluenceResult,
    calculate_confluence,
)
from app.services.strategies.base import BaseStrategy, StrategyResult

DEFAULT_MIN_SCORE: float = 65.0
DEFAULT_ADX_THRESHOLD: float = 25.0
RSI_BUY_LEVEL: float = 55.0
RSI_SELL_LEVEL: float = 45.0

VALID_TIMEFRAMES = ("1h", "4h")

# Momentum pillar weights (also documented in the module docstring).
TREND_POINTS: float = 40.0
RSI_POINTS: float = 35.0
LOCATION_POINTS: float = 25.0

# Provenance metadata: only large-cap momentum and small/mid-cap reversal
# avoidance are paper-supported; every 1H rule is an engineering heuristic.
HEURISTIC_PROVENANCE: str = "empirical_1h_not_paper_validated"
PAPER_SUPPORTED: list[str] = ["btc_largecap_momentum", "smallcap_reversal_avoidance"]
HEURISTIC_PROXIES: list[str] = [
    "hourly_noise_cap_5pct",
    "intraday_volume_gate",
    "1h_timeframe",
    "ema_rsi_adx_thresholds",
]
FILTERS_APPLIED: list[str] = ["retail_noise_5pct", "liquidity_gate"]
RETAIL_NOISE_MAX_CHANGE: float = 0.05
DEFAULT_MIN_VOLUME: float = 1.0


class BTCMomentumStrategy(BaseStrategy):
    """EMA/RSI momentum strategy restricted to BTC/USD on 1h or 4h.

    Universe restriction (academic justification, Proelss et al. 2025):
        BTC and ETH show significant positive momentum (beta_1 = 0.34 at 30d,
        0.173 at 7d) because institutional investors with higher risk aversion
        trade them. Small- and mid-cap cryptocurrencies exhibit significant
        REVERSAL effects because retail investors with lower risk aversion
        engage in noisy trading. Hardcoding ``symbol == "BTC/USD"`` selects the
        paper's momentum-confirmed large-cap segment and avoids the
        reversal-prone small/mid-cap segment.

    The 1h/4h execution timeframes are empirical engineering choices only; the
    paper tests 7d/30d, weekly and monthly horizons, never intraday bars.
    """

    DEFAULT_MIN_SCORE = DEFAULT_MIN_SCORE

    def __init__(
        self,
        min_score_threshold: Optional[float] = None,
        min_volume: float = DEFAULT_MIN_VOLUME,
        adx_threshold: float = DEFAULT_ADX_THRESHOLD,
    ) -> None:
        self._min_score_threshold = (
            min_score_threshold if min_score_threshold is not None else DEFAULT_MIN_SCORE
        )
        self.min_volume = float(min_volume)
        self.adx_threshold = float(adx_threshold)

    @property
    def name(self) -> str:
        return "BTC Momentum"

    @staticmethod
    def _candle_field(candle: Any, field: str, default: Any = None) -> Any:
        """Read a candle field from either a mapping or an object."""
        if isinstance(candle, dict):
            return candle.get(field, default)
        return getattr(candle, field, default)

    def _latest_closed_candle(self, candles: Optional[Sequence[Any]]) -> Optional[Any]:
        """Return the most recent closed candle; skip any forming bar."""
        if not candles:
            return None
        for candle in reversed(candles):
            if self._candle_field(candle, "is_closed", None) is False:
                continue
            return candle
        return None

    @staticmethod
    def _previous_value(kwargs: dict[str, Any], name: str, series_name: str) -> Any:
        """Read a previous-bar indicator from kwargs, or derive it from a series."""
        value = kwargs.get(name)
        if value is None:
            series = kwargs.get(series_name)
            if series is not None and len(series) >= 2:
                value = series[-2]
        return value

    @staticmethod
    def _breakdown(
        total_score: float,
        trend_score: float,
        rsi_score: float,
        location_score: float,
        is_qualified: bool,
    ) -> ScoreBreakdown:
        """Build a schema-valid ScoreBreakdown.

        ``ScoreBreakdown`` caps structure_score at 35 and indicators_score at 25,
        which are lower than this strategy's 40-pt trend and 35-pt RSI weights.
        The breakdown is therefore illustrative: components are capped to their
        schema bounds while ``total_score`` (and ``StrategyResult.score``) carry
        the authoritative uncapped momentum score. Exact pillar values are also
        exposed via ``StrategyResult.metadata``.
        """
        return ScoreBreakdown(
            structure_score=min(float(trend_score), 35.0),
            liquidity_score=0.0,
            indicators_score=min(float(rsi_score), 25.0),
            price_action_score=min(float(location_score), 25.0),
            total_score=round(float(total_score), 1),
            is_qualified=bool(is_qualified),
        )

    def _wait_result(
        self,
        reasons: list[str],
        *,
        symbol: str,
        timeframe: str,
        indicators: Optional[IndicatorAnalysisResponse] = None,
        score: float = 0.0,
        buy_score: float = 0.0,
        sell_score: float = 0.0,
        trend_score: float = 0.0,
        rsi_score: float = 0.0,
        location_score: float = 0.0,
        adx: Optional[float] = None,
        confluence: Optional[ConfluenceResult] = None,
    ) -> StrategyResult:
        """Uniform WAIT result carrying a valid breakdown and metadata.

        ``score`` is the confirmation readiness score (0-100) computed from the
        same EMA/RSI/location pillars used for actionable setups. It is reported
        even on WAIT so the dashboard never has to render a blank "-- / 100".
        """
        current_price = getattr(indicators, "current_price", None) if indicators else None
        rsi_value = (
            getattr(getattr(indicators, "rsi", None), "rsi_value", None)
            if indicators
            else None
        )
        ema = getattr(indicators, "ema", None) if indicators else None
        confluence_meta: dict[str, Any] = {}
        if confluence is not None:
            # On WAIT, `score` is the graded confluence of the dominant trend,
            # not the binary readiness score, so the card never shows 100/100.
            score = confluence.score
            confluence_meta = {
                "confluence_score": confluence.score,
                "confluence_ema_score": confluence.ema_score,
                "confluence_rsi_score": confluence.rsi_score,
                "confluence_adx_score": confluence.adx_score,
                "ema_trend": confluence.ema_trend,
            }
        return StrategyResult(
            strategy_name=self.name,
            direction=SignalDirection.WAIT,
            score=float(score),
            reasons=reasons,
            metadata={
                "symbol": symbol,
                "timeframe": timeframe,
                "min_score_threshold": self._min_score_threshold,
                "buy_score": round(buy_score, 1),
                "sell_score": round(sell_score, 1),
                **confluence_meta,
                "ema_50": getattr(ema, "ema_mid", None),
                "ema_200": getattr(ema, "ema_slow", None),
                "ema_trend": confluence_meta.get("ema_trend") or getattr(ema, "ema_trend", None),
                "rsi_14": rsi_value,
                "current_price": current_price,
                "adx_14": adx,
                "adx_threshold": self.adx_threshold,
                "heuristic_provenance": HEURISTIC_PROVENANCE,
                "heuristic_note": (
                    "1H rules are empirical heuristics; paper tests 7d/30d, "
                    "weekly and monthly horizons, not intraday"
                ),
                "paper_supported": list(PAPER_SUPPORTED),
                "heuristic_proxies": list(HEURISTIC_PROXIES),
                "filters_applied": list(FILTERS_APPLIED),
            },
            score_breakdown=self._breakdown(
                float(score), trend_score, rsi_score, location_score, is_qualified=False
            ),
        )

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
        """Score EMA/RSI momentum for BUY and SELL and select the best setup.

        The BTC/USD-only universe gate below is the paper-backed restriction:
        Proelss et al. (2025) find large-cap momentum (BTC/ETH) and small/mid-cap
        reversal, driven by institutional vs. retail risk preferences.
        """

        # ----- Hard eligibility gates -----
        # ACADEMIC UNIVERSE RESTRICTION: BTC/USD is the large-cap segment where
        # Proelss et al. (2025) report positive momentum (beta_1 = 0.34 at 30d,
        # 0.173 at 7d) from institutions' higher risk aversion. Small/mid-cap
        # coins show retail-driven reversal, so they are excluded by design.
        if symbol != "BTC/USD":
            return self._wait_result(
                [f"INELIGIBLE_SYMBOL: BTC Momentum only evaluates BTC/USD (got {symbol})."],
                symbol=symbol,
                timeframe=timeframe,
            )

        # 1h/4h are purely empirical engineering timeframes, NOT paper-tested:
        # the paper covers 7d/30d, weekly and monthly horizons only.
        tf = str(timeframe or "").lower().strip()
        if tf not in VALID_TIMEFRAMES:
            return self._wait_result(
                [f"INELIGIBLE_TIMEFRAME: BTC Momentum requires 1h or 4h (got {timeframe})."],
                symbol=symbol,
                timeframe=timeframe,
            )

        # ----- Empirical pre-scoring sanity filters (HEURISTIC PROXIES) -----
        # These are adapted for 1H intraday bars, NOT the exact paper filters:
        #   Paper pump-and-dump filter: exclude assets whose absolute DAILY log
        #   returns >= 2 (approx 639% daily move) in >10% of observations.
        #   Paper liquidity filter: >= $10,000 daily volume OR $5M market cap.
        # Our 5% hourly cap and per-bar volume floor are engineering heuristics to approximate the paper's daily filters on an intraday timeframe.
        # Momentum scoring below is unchanged.
        candle = self._latest_closed_candle(candles)
        if candle is None:
            return self._wait_result(
                ["INSUFFICIENT_CANDLE_DATA: No closed candle available for heuristic filters."],
                symbol=symbol,
                timeframe=timeframe,
                indicators=indicators,
            )

        candle_open = self._candle_field(candle, "open", None)
        candle_close = self._candle_field(candle, "close", None)
        candle_volume = self._candle_field(candle, "volume", None)

        try:
            open_price = float(candle_open)
            close_price = float(candle_close)
        except (TypeError, ValueError):
            open_price = 0.0
            close_price = 0.0
        if open_price <= 0.0 or close_price <= 0.0:
            return self._wait_result(
                ["INSUFFICIENT_CANDLE_DATA: Latest closed candle has invalid OHLC values."],
                symbol=symbol,
                timeframe=timeframe,
                indicators=indicators,
            )

        # 5% HOURLY price-change cap — heuristic proxy for the paper's DAILY
        # |log return| >= 2 pump-and-dump screen; not an exact paper filter.
        price_change = abs(close_price - open_price) / open_price
        if price_change > RETAIL_NOISE_MAX_CHANGE:
            return self._wait_result(
                [
                    "RETAIL_NOISE_FILTER: 1H candle price change exceeds 5% "
                    "institutional momentum threshold."
                ],
                symbol=symbol,
                timeframe=timeframe,
                indicators=indicators,
            )

        try:
            volume_value = float(candle_volume) if candle_volume is not None else 0.0
        except (TypeError, ValueError):
            volume_value = 0.0
        # Per-bar volume floor — heuristic proxy for the paper's liquidity
        # screen ($10,000 daily volume or $5M market cap), not its exact rule.
        if volume_value <= 0.0 or volume_value < self.min_volume:
            return self._wait_result(
                ["LIQUIDITY_FILTER: Insufficient trading volume for economic viability."],
                symbol=symbol,
                timeframe=timeframe,
                indicators=indicators,
            )

        # ----- Pre-computed indicator inputs -----
        ema = getattr(indicators, "ema", None)
        rsi_snapshot = getattr(indicators, "rsi", None)
        ema_50 = getattr(ema, "ema_mid", None)  # ema_mid is the 50-period EMA
        ema_200 = getattr(ema, "ema_slow", None)  # ema_slow is the 200-period EMA
        rsi_14 = getattr(rsi_snapshot, "rsi_value", None)  # RSI(14)
        current_price = getattr(indicators, "current_price", None)

        missing = [
            name
            for name, value in (
                ("EMA50", ema_50),
                ("EMA200", ema_200),
                ("RSI14", rsi_14),
                ("current_price", current_price),
            )
            if value is None
        ]
        if missing:
            return self._wait_result(
                [f"INSUFFICIENT_INDICATOR_DATA: Missing {', '.join(missing)}."],
                symbol=symbol,
                timeframe=timeframe,
                indicators=indicators,
            )

        ema_50 = float(ema_50)
        ema_200 = float(ema_200)
        rsi_14 = float(rsi_14)
        current_price = float(current_price)

        # ----- ADX snapshot (a caller may supply a causal value for sweeps) -----
        adx_14 = kwargs.get("adx_14")
        if adx_14 is None:
            adx_14 = ADXCalculator().calculate_adx_from_candles(candles, period=14)
        else:
            adx_14 = float(adx_14)

        # ----- Graded confluence score (40% EMA / 30% RSI / 30% ADX) -----
        # Replaces the old binary 40+35+25 = exactly 100 pillar sum. Each
        # sub-score is graded 0-100, so 100/100 is structurally unreachable and
        # RSI in the neutral zone can no longer masquerade as a perfect setup.
        ema_fast = getattr(ema, "ema_fast", None)
        buy_cf = calculate_confluence(
            price=current_price, ema_fast=ema_fast, ema_mid=ema_50,
            rsi=rsi_14, adx=adx_14, ema_slow=ema_200, direction="BUY",
        )
        sell_cf = calculate_confluence(
            price=current_price, ema_fast=ema_fast, ema_mid=ema_50,
            rsi=rsi_14, adx=adx_14, ema_slow=ema_200, direction="SELL",
        )
        best_cf = buy_cf if buy_cf.score >= sell_cf.score else sell_cf
        best_score = best_cf.score
        best_trend = best_cf.ema_score
        best_rsi = best_cf.rsi_score
        best_location = best_cf.adx_score

        # Legacy boolean readiness is retained only as a fresh-trigger detail
        # in the reasons; it no longer drives the displayed score.
        buy_readiness = (
            (TREND_POINTS if ema_50 > ema_200 else 0.0)
            + (RSI_POINTS if rsi_14 > 55.0 else 0.0)
            + (LOCATION_POINTS if current_price > ema_50 else 0.0)
        )
        sell_readiness = (
            (TREND_POINTS if ema_50 < ema_200 else 0.0)
            + (RSI_POINTS if rsi_14 < 45.0 else 0.0)
            + (LOCATION_POINTS if current_price < ema_50 else 0.0)
        )

        if adx_14 is None:
            return self._wait_result(
                ["INSUFFICIENT_INDICATOR_DATA: ADX(14) unavailable (need >= 28 candles)."],
                symbol=symbol, timeframe=timeframe, indicators=indicators,
                score=best_score, buy_score=buy_readiness, sell_score=sell_readiness,
                trend_score=best_trend, rsi_score=best_rsi, location_score=best_location,
                confluence=best_cf,
            )
        if adx_14 < self.adx_threshold:
            return self._wait_result(
                [f"REGIME_FILTER: ADX below {self.adx_threshold:g}, ranging market."],
                symbol=symbol, timeframe=timeframe, indicators=indicators, adx=adx_14,
                score=best_score, buy_score=buy_readiness, sell_score=sell_readiness,
                trend_score=best_trend, rsi_score=best_rsi, location_score=best_location,
                confluence=best_cf,
            )

        # ----- Fresh-event detection (state alone is never a trigger) -----
        prev_rsi = self._previous_value(kwargs, "prev_rsi", "rsi_series")
        prev_ema50 = self._previous_value(kwargs, "prev_ema50", "ema50_series")
        prev_ema200 = self._previous_value(kwargs, "prev_ema200", "ema200_series")
        try:
            prev_rsi = float(prev_rsi)
            prev_ema50 = float(prev_ema50)
            prev_ema200 = float(prev_ema200)
        except (TypeError, ValueError):
            return self._wait_result(
                [
                    "INSUFFICIENT_INDICATOR_DATA: previous-bar RSI/EMA values "
                    "are required for fresh-trigger detection."
                ],
                symbol=symbol, timeframe=timeframe, indicators=indicators, adx=adx_14,
                score=best_score, buy_score=buy_readiness, sell_score=sell_readiness,
                trend_score=best_trend, rsi_score=best_rsi, location_score=best_location,
                confluence=best_cf,
            )

        rsi_cross_up = prev_rsi <= RSI_BUY_LEVEL and rsi_14 > RSI_BUY_LEVEL
        rsi_cross_down = prev_rsi >= RSI_SELL_LEVEL and rsi_14 < RSI_SELL_LEVEL
        ema_cross_up = prev_ema50 <= prev_ema200 and ema_50 > ema_200
        ema_cross_down = prev_ema50 >= prev_ema200 and ema_50 < ema_200
        buy_trigger = rsi_cross_up or ema_cross_up
        sell_trigger = rsi_cross_down or ema_cross_down
        if not buy_trigger and not sell_trigger:
            return self._wait_result(
                ["NO_FRESH_TRIGGER: no RSI or EMA crossover on the latest closed bar."],
                symbol=symbol, timeframe=timeframe, indicators=indicators, adx=adx_14,
                score=best_score, buy_score=buy_readiness, sell_score=sell_readiness,
                trend_score=best_trend, rsi_score=best_rsi, location_score=best_location,
                confluence=best_cf,
            )

        is_qualified = best_score >= self._min_score_threshold
        buy_trigger_label = (
            "RSI crossed above 55" if rsi_cross_up else "EMA50 crossed above EMA200"
        )
        sell_trigger_label = (
            "RSI crossed below 45" if rsi_cross_down else "EMA50 crossed below EMA200"
        )
        buy_ok = buy_trigger and is_qualified
        sell_ok = sell_trigger and is_qualified

        if buy_ok and (not sell_ok or buy_cf.score >= sell_cf.score):
            direction = SignalDirection.BUY
            score = buy_cf.score
            fresh_trigger = buy_trigger_label
            trend_score, rsi_score, location_score = (
                buy_cf.ema_score, buy_cf.rsi_score, buy_cf.adx_score
            )
            chosen_cf = buy_cf
            reasons = [
                f"FRESH TRIGGER (BUY): {fresh_trigger}.",
                f"EMA CONFLUENCE: {buy_cf.ema_trend}, {buy_cf.ema_score:.1f}/100 "
                f"(weight {EMA_WEIGHT:.0%}).",
                f"RSI CONFLUENCE: RSI14 {rsi_14:.1f} -> {buy_cf.rsi_score:.1f}/100 "
                f"(weight {RSI_WEIGHT:.0%}).",
                f"ADX CONFLUENCE: {adx_14:.2f} -> {buy_cf.adx_score:.1f}/100 "
                f"(weight {ADX_WEIGHT:.0%}).",
                f"BUY TECHNICAL CONFLUENCE: {buy_cf.score:.1f}/100 "
                f"(min {self._min_score_threshold:.1f}).",
            ]
        elif sell_ok:
            direction = SignalDirection.SELL
            score = sell_cf.score
            fresh_trigger = sell_trigger_label
            trend_score, rsi_score, location_score = (
                sell_cf.ema_score, sell_cf.rsi_score, sell_cf.adx_score
            )
            chosen_cf = sell_cf
            reasons = [
                f"FRESH TRIGGER (SELL): {fresh_trigger}.",
                f"EMA CONFLUENCE: {sell_cf.ema_trend}, {sell_cf.ema_score:.1f}/100 "
                f"(weight {EMA_WEIGHT:.0%}).",
                f"RSI CONFLUENCE: RSI14 {rsi_14:.1f} -> {sell_cf.rsi_score:.1f}/100 "
                f"(weight {RSI_WEIGHT:.0%}).",
                f"ADX CONFLUENCE: {adx_14:.2f} -> {sell_cf.adx_score:.1f}/100 "
                f"(weight {ADX_WEIGHT:.0%}).",
                f"SELL TECHNICAL CONFLUENCE: {sell_cf.score:.1f}/100 "
                f"(min {self._min_score_threshold:.1f}).",
            ]
        else:
            return self._wait_result(
                [
                    f"MOMENTUM BELOW FLOOR: best confluence score {best_score:.1f}/100 "
                    f"(min required {self._min_score_threshold:.1f}).",
                    f"EMA50={ema_50:.2f}, EMA200={ema_200:.2f}, RSI14={rsi_14:.1f}, "
                    f"price={current_price:.2f}, ADX={adx_14:.2f}.",
                ],
                symbol=symbol,
                timeframe=timeframe,
                indicators=indicators,
                score=best_score,
                buy_score=buy_readiness,
                sell_score=sell_readiness,
                trend_score=best_trend,
                rsi_score=best_rsi,
                location_score=best_location,
                adx=adx_14,
                confluence=best_cf,
            )

        return StrategyResult(
            strategy_name=self.name,
            direction=direction,
            score=score,
            reasons=reasons,
            metadata={
                "symbol": symbol,
                "timeframe": tf,
                "min_score_threshold": self._min_score_threshold,
                "buy_score": round(buy_readiness, 1),
                "sell_score": round(sell_readiness, 1),
                **{
                    "confluence_score": chosen_cf.score,
                    "confluence_ema_score": chosen_cf.ema_score,
                    "confluence_rsi_score": chosen_cf.rsi_score,
                    "confluence_adx_score": chosen_cf.adx_score,
                    "ema_trend": chosen_cf.ema_trend,
                },
                "trend_score": trend_score,
                "rsi_score": rsi_score,
                "location_score": location_score,
                "ema_50": ema_50,
                "ema_200": ema_200,
                "rsi_14": rsi_14,
                "current_price": current_price,
                "adx_14": adx_14,
                "adx_threshold": self.adx_threshold,
                "fresh_trigger": fresh_trigger,
                "prev_rsi": prev_rsi,
                "prev_ema50": prev_ema50,
                "prev_ema200": prev_ema200,
                "entry_mode": "market",
                "heuristic_provenance": HEURISTIC_PROVENANCE,
                "heuristic_note": (
                    "1H rules are empirical heuristics; paper tests 7d/30d, "
                    "weekly and monthly horizons, not intraday"
                ),
                "paper_supported": list(PAPER_SUPPORTED),
                "heuristic_proxies": list(HEURISTIC_PROXIES),
                "filters_applied": list(FILTERS_APPLIED),
            },
            score_breakdown=self._breakdown(
                score,
                trend_score,
                rsi_score,
                location_score,
                is_qualified=True,
            ),
            entry_price=current_price,
        )
