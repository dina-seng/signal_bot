"""Unit tests for Strategy C (Range Sniper) mean-reversion strategy."""

from datetime import datetime, timezone
import pytest

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
from app.schemas.signal import SignalDirection
from app.schemas.structure import StructureAnalysisResponse, TrendDirection
from app.services.strategies.range_strategy import RangeStrategy
from app.services.strategies.strategy_manager import StrategyManager


def _build_indicators(
    rsi_value: float = 50.0,
    rsi_condition: str = "NEUTRAL",
    is_oversold: bool = False,
    is_overbought: bool = False,
    ema_50: float = 2000.0,
    current_price: float = 2000.0,
    atr_value: float = 5.0,
    atr_pips: float = 50.0,
    recent_patterns = None,
) -> IndicatorAnalysisResponse:
    now = datetime.now(timezone.utc)
    return IndicatorAnalysisResponse(
        symbol="XAU/USD",
        timeframe="1h",
        timestamp=now,
        current_price=current_price,
        ema=EMASnapshot(
            ema_fast=2005.0,
            ema_mid=ema_50,
            ema_slow=1990.0,
            ema_trend="NEUTRAL",
        ),
        rsi=RSISnapshot(
            rsi_value=rsi_value,
            condition=rsi_condition,
            is_oversold=is_oversold,
            is_overbought=is_overbought,
        ),
        atr=ATRSnapshot(
            atr_value=atr_value,
            atr_pips=atr_pips,
            volatility_state="NORMAL",
        ),
        divergences=[],
        recent_patterns=recent_patterns or [],
        active_fvgs=[],
        confluence_bias="NEUTRAL",
        confluence_score=0.0,
    )


def _build_structure(
    trend: TrendDirection = TrendDirection.RANGING,
    trend_strength: float = 0.5,
    latest_sweep = None,
    sr_zones = None,
    key_support: float = 1980.0,
    key_resistance: float = 2020.0,
) -> AdvancedStructureAnalysisResponse:
    now = datetime.now(timezone.utc)
    base = StructureAnalysisResponse(
        symbol="XAU/USD",
        timeframe="1h",
        trend=trend,
        trend_strength=trend_strength,
        key_support=key_support,
        key_resistance=key_resistance,
        total_candles=100,
        total_swings=10,
        timestamp=now,
    )
    return AdvancedStructureAnalysisResponse(
        symbol="XAU/USD",
        timeframe="1h",
        timestamp=now,
        current_price=2000.0,
        trend=trend,
        trend_strength=trend_strength,
        market_state="RANGING" if trend == TrendDirection.RANGING else "TRENDING",
        base_structure=base,
        latest_sweep=latest_sweep,
        sr_zones=sr_zones or [],
    )


class TestRangeStrategy:
    """Comprehensive test suite for Strategy C (Range Sniper)."""

    def test_strategy_name(self):
        strategy = RangeStrategy()
        assert strategy.name == "Strategy C (Range Sniper)"

    def test_no_trend_gatekeeper_blocks_bullish_and_bearish(self):
        strategy = RangeStrategy()

        # 1. Bullish trend block
        bull_struct = _build_structure(trend=TrendDirection.BULLISH)
        indicators = _build_indicators(rsi_value=25.0, rsi_condition="OVERSOLD")
        res_bull = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[],
            indicators=indicators,
            structure=bull_struct,
        )
        assert res_bull.direction == SignalDirection.WAIT
        assert res_bull.score == 0.0
        assert "Market trending. Range strategy disabled." in res_bull.reasons

        # 2. Bearish trend block
        bear_struct = _build_structure(trend=TrendDirection.BEARISH)
        res_bear = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[],
            indicators=indicators,
            structure=bear_struct,
        )
        assert res_bear.direction == SignalDirection.WAIT
        assert res_bear.score == 0.0
        assert "Market trending. Range strategy disabled." in res_bear.reasons

    def test_neutral_rsi_returns_wait(self):
        strategy = RangeStrategy()
        indicators = _build_indicators(rsi_value=50.0, rsi_condition="NEUTRAL")
        structure = _build_structure(trend=TrendDirection.RANGING)

        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[],
            indicators=indicators,
            structure=structure,
        )
        assert result.direction == SignalDirection.WAIT
        assert any("RSI in neutral range" in r for r in result.reasons)
        assert result.score == 15.0  # Trend ranging gives 15 pts
        assert result.score_breakdown.structure_score == 15.0
        assert result.score_breakdown.indicators_score == 0.0
        assert not result.score_breakdown.is_qualified

    def test_missing_price_action_confirmation_returns_wait(self):
        strategy = RangeStrategy()
        now = datetime.now(timezone.utc)
        # RSI oversold (BUY trigger), but no reversal candlestick pattern
        indicators = _build_indicators(
            rsi_value=24.0,
            rsi_condition="OVERSOLD",
            is_oversold=True,
            recent_patterns=[],
        )
        structure = _build_structure(trend=TrendDirection.RANGING)

        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[],
            indicators=indicators,
            structure=structure,
        )
        assert result.direction == SignalDirection.WAIT
        assert any("No price action confirmation" in r for r in result.reasons)
        assert not result.score_breakdown.is_qualified
        assert result.score_breakdown.price_action_score == 0.0

    def test_qualified_buy_setup(self):
        strategy = RangeStrategy()
        now = datetime.now(timezone.utc)

        # 1. Price is stretched far below 50 EMA: price=1975, EMA=2000, ATR=5.0
        # distance = 25.0 > 1.5 * 5.0 (7.5) -> EMA overextended (+10 pts)
        # 2. Bullish Pin Bar pattern (+20 pts)
        pin_bar = PriceActionPattern(
            index=99,
            timestamp=now,
            pattern_type=PatternType.BULLISH_PIN_BAR,
            confidence=1.0,
            description="Bullish hammer rejection at support",
        )
        indicators = _build_indicators(
            rsi_value=22.0,
            rsi_condition="OVERSOLD",
            current_price=1975.0,
            ema_50=2000.0,
            atr_value=5.0,
            atr_pips=50.0,
            recent_patterns=[pin_bar],
        )

        # 3. Support zone at 1970 - 1980 (+15 pts) -> Structure 30 pts
        supp_zone = SupportResistanceZone(
            zone_type=ZoneType.SUPPORT,
            price_low=1970.0,
            price_high=1980.0,
            center_price=1975.0,
            touch_count=3,
            strength=0.9,
            is_fresh=True,
        )

        # 4. Sell-side sweep (+25 pts)
        sweep = LiquiditySweep(
            index=98,
            timestamp=now,
            sweep_type=LiquidityEventType.SELL_SIDE_SWEEP,
            swept_level=1980.0,
            sweep_extreme=1972.0,
            close_price=1975.0,
            wick_ratio=0.65,
            pips_swept=8.0,
        )
        structure = _build_structure(
            trend=TrendDirection.RANGING,
            latest_sweep=sweep,
            sr_zones=[supp_zone],
        )

        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[],
            indicators=indicators,
            structure=structure,
        )

        assert result.direction == SignalDirection.BUY
        assert result.score == 100.0
        assert result.score_breakdown.is_qualified
        assert result.score_breakdown.structure_score == 30.0
        assert result.score_breakdown.liquidity_score == 25.0
        assert result.score_breakdown.indicators_score == 25.0
        assert result.score_breakdown.price_action_score == 20.0
        assert result.score_breakdown.total_score == 100.0

    def test_qualified_sell_setup(self):
        strategy = RangeStrategy()
        now = datetime.now(timezone.utc)

        # 1. Price stretched far above 50 EMA: price=2025, EMA=2000
        # 2. Bearish Engulfing pattern (+20 pts)
        engulfing = PriceActionPattern(
            index=99,
            timestamp=now,
            pattern_type=PatternType.BEARISH_ENGULFING,
            confidence=1.0,
            description="Bearish outside engulfing candle",
        )
        indicators = _build_indicators(
            rsi_value=78.0,
            rsi_condition="OVERBOUGHT",
            current_price=2025.0,
            ema_50=2000.0,
            atr_value=5.0,
            atr_pips=50.0,
            recent_patterns=[engulfing],
        )

        # 3. Resistance zone at 2020 - 2030 (+15 pts) -> Structure 30 pts
        res_zone = SupportResistanceZone(
            zone_type=ZoneType.RESISTANCE,
            price_low=2020.0,
            price_high=2030.0,
            center_price=2025.0,
            touch_count=2,
            strength=0.85,
            is_fresh=True,
        )

        # 4. Buy-side sweep (+25 pts)
        sweep = LiquiditySweep(
            index=98,
            timestamp=now,
            sweep_type=LiquidityEventType.BUY_SIDE_SWEEP,
            swept_level=2020.0,
            sweep_extreme=2028.0,
            close_price=2024.0,
            wick_ratio=0.6,
            pips_swept=8.0,
        )
        structure = _build_structure(
            trend=TrendDirection.RANGING,
            latest_sweep=sweep,
            sr_zones=[res_zone],
        )

        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[],
            indicators=indicators,
            structure=structure,
        )

        assert result.direction == SignalDirection.SELL
        assert result.score == 100.0
        assert result.score_breakdown.is_qualified
        assert result.score_breakdown.structure_score == 30.0
        assert result.score_breakdown.liquidity_score == 25.0
        assert result.score_breakdown.indicators_score == 25.0
        assert result.score_breakdown.price_action_score == 20.0

    def test_pydantic_score_capping(self):
        """Verify that score components never exceed their max bounds."""
        strategy = RangeStrategy()
        now = datetime.now(timezone.utc)
        pattern = PriceActionPattern(
            index=99,
            timestamp=now,
            pattern_type=PatternType.BULLISH_ENGULFING,
            confidence=1.0,
            description="Test engulfing",
        )
        indicators = _build_indicators(
            rsi_value=20.0,
            rsi_condition="OVERSOLD",
            current_price=1970.0,
            ema_50=2000.0,
            atr_value=4.0,
            recent_patterns=[pattern],
        )
        supp = SupportResistanceZone(
            zone_type=ZoneType.SUPPORT,
            price_low=1965.0,
            price_high=1975.0,
            center_price=1970.0,
            touch_count=4,
            strength=1.0,
            is_fresh=True,
        )
        sweep = LiquiditySweep(
            index=98,
            timestamp=now,
            sweep_type=LiquidityEventType.SELL_SIDE_SWEEP,
            swept_level=1975.0,
            sweep_extreme=1960.0,
            close_price=1970.0,
            wick_ratio=0.7,
            pips_swept=15.0,
        )
        structure = _build_structure(
            trend=TrendDirection.RANGING,
            latest_sweep=sweep,
            sr_zones=[supp],
        )

        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[],
            indicators=indicators,
            structure=structure,
        )

        b = result.score_breakdown
        assert b is not None
        assert b.structure_score <= 30.0
        assert b.liquidity_score <= 25.0
        assert b.indicators_score <= 25.0
        assert b.price_action_score <= 20.0
        assert b.total_score <= 100.0

    def test_clean_integration_with_strategy_manager(self):
        """Verify RangeStrategy registers and runs via StrategyManager without breaking existing SMC strategy."""
        manager = StrategyManager()
        range_strat = RangeStrategy()
        manager.register(range_strat)

        names = [s.name for s in manager.strategies]
        assert "Strategy A (SMC Sniper)" in names
        assert "Strategy C (Range Sniper)" in names
        assert len(names) == 2

        now = datetime.now(timezone.utc)
        pattern = PriceActionPattern(
            index=99,
            timestamp=now,
            pattern_type=PatternType.BULLISH_PIN_BAR,
            confidence=0.9,
            description="Hammer",
        )
        indicators = _build_indicators(
            rsi_value=25.0,
            rsi_condition="OVERSOLD",
            current_price=1975.0,
            ema_50=2000.0,
            atr_value=5.0,
            recent_patterns=[pattern],
        )
        supp = SupportResistanceZone(
            zone_type=ZoneType.SUPPORT,
            price_low=1970.0,
            price_high=1980.0,
            center_price=1975.0,
            touch_count=2,
            strength=0.8,
            is_fresh=True,
        )
        sweep = LiquiditySweep(
            index=98,
            timestamp=now,
            sweep_type=LiquidityEventType.SELL_SIDE_SWEEP,
            swept_level=1980.0,
            sweep_extreme=1972.0,
            close_price=1975.0,
            wick_ratio=0.6,
            pips_swept=8.0,
        )
        structure = _build_structure(
            trend=TrendDirection.RANGING,
            latest_sweep=sweep,
            sr_zones=[supp],
        )

        results = manager.run_all_strategies(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[],
            indicators=indicators,
            structure=structure,
        )

        assert len(results) == 2
        smc_res = next(r for r in results if r.strategy_name == "Strategy A (SMC Sniper)")
        range_res = next(r for r in results if r.strategy_name == "Strategy C (Range Sniper)")

        assert smc_res is not None
        assert range_res is not None
        assert range_res.direction == SignalDirection.BUY
        assert range_res.score >= 75.0
        assert range_res.score_breakdown.is_qualified

    def test_telegram_message_formatter_market_regime(self):
        """Verify cosmetic Market Regime display in Telegram alert based on strategy_name."""
        from app.schemas.signal import SignalResponse
        from app.services.telegram.message_formatter import TelegramMessageFormatter

        formatter = TelegramMessageFormatter()
        now = datetime.now(timezone.utc)

        # 1. Strategy C (Range Sniper) signal -> RANGING / MEAN REVERSION
        range_sig = SignalResponse(
            symbol="XAU/USD",
            timeframe="1h",
            direction=SignalDirection.BUY,
            setup_score=85.0,
            entry_price=1975.0,
            stop_loss=1965.0,
            take_profit_1=1995.0,
            fingerprint="fp_range",
            reasons=["RSI Oversold", "Sell-Side Sweep"],
            strategy_name="Strategy C (Range Sniper)",
            timestamp=now,
        )
        range_alert = formatter.format_signal_alert(range_sig)
        assert "Market Regime:" in range_alert
        assert "RANGING / MEAN REVERSION" in range_alert
        assert "🔄" in range_alert

        # 2. Strategy A (SMC Sniper) or other trend signal -> TREND FOLLOWING
        trend_sig = SignalResponse(
            symbol="XAU/USD",
            timeframe="1h",
            direction=SignalDirection.BUY,
            setup_score=85.0,
            entry_price=1975.0,
            stop_loss=1965.0,
            take_profit_1=1995.0,
            fingerprint="fp_trend",
            reasons=["Bullish BOS Continuation"],
            strategy_name="Strategy A (SMC Sniper)",
            timestamp=now,
        )
        trend_alert = formatter.format_signal_alert(trend_sig)
        assert "Market Regime:" in trend_alert
        assert "TREND FOLLOWING" in trend_alert
        assert "🎯" in trend_alert
