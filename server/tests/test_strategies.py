"""Unit tests for Strategy A (SMC Sniper) and Strategy B (Momentum Catcher) independent architecture."""

from datetime import datetime, timezone
import pytest

from app.schemas.indicators import (
    ATRSnapshot,
    DivergenceType,
    EMASnapshot,
    IndicatorAnalysisResponse,
    RSIDivergence,
    RSISnapshot,
)
from app.schemas.liquidity import (
    AdvancedStructureAnalysisResponse,
    BOSCHOCHType,
    BreakoutEvent,
    LiquidityEventType,
    LiquiditySweep,
)
from app.schemas.signal import SignalDirection, SignalResponse
from app.schemas.structure import StructureAnalysisResponse, TrendDirection
from app.services.signals.confluence_engine import ConfluenceEngine
from app.services.signals.signal_generator import SignalGenerator
from app.services.strategies.momentum_strategy import MomentumStrategy
from app.services.strategies.smc_strategy import SMCStrategy
from app.services.strategies.strategy_manager import StrategyManager
from app.services.telegram.message_formatter import TelegramMessageFormatter


def _build_mock_indicators(
    golden_cross: bool = False,
    death_cross: bool = False,
    ema_trend: str = "NEUTRAL",
    price_vs_ema200: str = "AT",
    rsi_value: float = 50.0,
    rsi_condition: str = "NEUTRAL",
    divergences = None,
    volatility_state: str = "NORMAL",
) -> IndicatorAnalysisResponse:
    now = datetime.now(timezone.utc)
    return IndicatorAnalysisResponse(
        symbol="XAU/USD",
        timeframe="1h",
        timestamp=now,
        current_price=2000.0,
        ema=EMASnapshot(
            ema_20=2005.0,
            ema_50=2000.0,
            ema_200=1990.0,
            ema_trend=ema_trend,
            price_vs_ema200=price_vs_ema200,
            golden_cross=golden_cross,
            death_cross=death_cross,
        ),
        rsi=RSISnapshot(
            rsi_value=rsi_value,
            condition=rsi_condition,
        ),
        atr=ATRSnapshot(
            atr_value=5.0,
            atr_pips=50.0,
            volatility_state=volatility_state,
        ),
        divergences=divergences or [],
        recent_patterns=[],
        active_fvgs=[],
        confluence_bias="NEUTRAL",
        confluence_score=0.0,
    )


def _build_mock_structure(
    trend: TrendDirection = TrendDirection.RANGING,
    trend_strength: float = 0.5,
    latest_bos = None,
    latest_sweep = None,
) -> AdvancedStructureAnalysisResponse:
    now = datetime.now(timezone.utc)
    base = StructureAnalysisResponse(
        symbol="XAU/USD",
        timeframe="1h",
        trend=trend,
        trend_strength=trend_strength,
        key_support=1980.0,
        key_resistance=2020.0,
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
        market_state="TRENDING" if trend != TrendDirection.RANGING else "RANGING",
        base_structure=base,
        latest_bos=latest_bos,
        latest_sweep=latest_sweep,
    )


class TestStrategyIndependence:
    """Verify Strategy A and Strategy B produce independent, uncorrupted results."""

    def test_strategy_names_are_standardized(self):
        strat_a = SMCStrategy()
        strat_b = MomentumStrategy()
        assert strat_a.name == "Strategy A (SMC Sniper)"
        assert strat_b.name == "Strategy B (Momentum Catcher)"

    def test_strategy_manager_registers_both_strategies(self):
        manager = StrategyManager()
        names = [s.name for s in manager.strategies]
        assert "Strategy A (SMC Sniper)" in names
        assert "Strategy B (Momentum Catcher)" in names

    def test_momentum_strategy_sell_without_death_cross(self):
        """MomentumStrategy should evaluate SELL momentum based on stack + divergence even without death cross."""
        strat_b = MomentumStrategy()
        now = datetime.now(timezone.utc)
        bear_div = RSIDivergence(
            divergence_type=DivergenceType.REGULAR_BEARISH,
            start_index=10,
            end_index=20,
            start_timestamp=now,
            end_timestamp=now,
            price_start=2010.0,
            price_end=2015.0,
            rsi_start=72.0,
            rsi_end=65.0,
            strength=0.9,
        )
        indicators = _build_mock_indicators(
            death_cross=False,
            ema_trend="BEARISH_STACK",
            price_vs_ema200="BELOW",
            rsi_value=35.0,
            rsi_condition="BEARISH_ZONE",
            divergences=[bear_div],
            volatility_state="HIGH",
        )
        structure = _build_mock_structure()

        result = strat_b.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[],
            indicators=indicators,
            structure=structure,
        )

        assert result.strategy_name == "Strategy B (Momentum Catcher)"
        assert result.direction == SignalDirection.SELL
        assert result.score >= 70.0
        assert any("RSI Bearish Divergence" in r for r in result.reasons)
        assert any("Bearish EMA Stack" in r for r in result.reasons)
        assert any("ATR Volatility Expansion" in r for r in result.reasons)

    def test_momentum_strategy_buy_without_golden_cross(self):
        """MomentumStrategy should evaluate BUY momentum based on stack + divergence."""
        strat_b = MomentumStrategy()
        now = datetime.now(timezone.utc)
        bull_div = RSIDivergence(
            divergence_type=DivergenceType.REGULAR_BULLISH,
            start_index=10,
            end_index=20,
            start_timestamp=now,
            end_timestamp=now,
            price_start=1990.0,
            price_end=1985.0,
            rsi_start=28.0,
            rsi_end=35.0,
            strength=0.9,
        )
        indicators = _build_mock_indicators(
            golden_cross=False,
            ema_trend="BULLISH_STACK",
            price_vs_ema200="ABOVE",
            rsi_value=60.0,
            rsi_condition="BULLISH_ZONE",
            divergences=[bull_div],
            volatility_state="HIGH",
        )
        structure = _build_mock_structure()

        result = strat_b.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[],
            indicators=indicators,
            structure=structure,
        )

        assert result.strategy_name == "Strategy B (Momentum Catcher)"
        assert result.direction == SignalDirection.BUY
        assert result.score >= 70.0
        assert any("RSI Bullish Divergence" in r for r in result.reasons)

    def test_strategy_manager_runs_both_independently(self):
        manager = StrategyManager()
        indicators = _build_mock_indicators(
            ema_trend="BEARISH_STACK",
            price_vs_ema200="BELOW",
            rsi_condition="BEARISH_ZONE",
        )
        structure = _build_mock_structure()

        results = manager.run_all_strategies(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[],
            indicators=indicators,
            structure=structure,
        )

        assert len(results) == 2
        strat_names = {r.strategy_name for r in results}
        assert "Strategy A (SMC Sniper)" in strat_names
        assert "Strategy B (Momentum Catcher)" in strat_names

    def test_telegram_formatter_multi_strategy_confluence_and_conflict(self):
        now = datetime.now(timezone.utc)
        sig_a = SignalResponse(
            symbol="XAU/USD",
            timeframe="1h",
            direction=SignalDirection.BUY,
            setup_score=82.0,
            entry_price=2000.0,
            stop_loss=1985.0,
            take_profit_1=2030.0,
            take_profit_2=2045.0,
            risk_reward=2.0,
            fingerprint="fp_a",
            reasons=["Confirmed Bullish BOS", "Sell-Side Liquidity Sweep"],
            strategy_name="Strategy A (SMC Sniper)",
            timestamp=now,
        )
        sig_b_confluent = SignalResponse(
            symbol="XAU/USD",
            timeframe="1h",
            direction=SignalDirection.BUY,
            setup_score=86.0,
            entry_price=2000.0,
            stop_loss=1985.0,
            take_profit_1=2030.0,
            take_profit_2=2045.0,
            risk_reward=2.0,
            fingerprint="fp_b",
            reasons=["Bullish EMA Stack", "RSI Bullish Divergence"],
            strategy_name="Strategy B (Momentum Catcher)",
            timestamp=now,
        )
        sig_b_conflicting = SignalResponse(
            symbol="XAU/USD",
            timeframe="1h",
            direction=SignalDirection.SELL,
            setup_score=88.0,
            entry_price=2000.0,
            stop_loss=2015.0,
            take_profit_1=1970.0,
            take_profit_2=1955.0,
            risk_reward=2.0,
            fingerprint="fp_b_conf",
            reasons=["Bearish EMA Stack", "RSI Bearish Divergence"],
            strategy_name="Strategy B (Momentum Catcher)",
            timestamp=now,
        )

        # 1. Test Confluence formatting
        confluence_text = TelegramMessageFormatter.format_multi_strategy_alert([sig_a, sig_b_confluent])
        assert "STRATEGY CONFLUENCE" in confluence_text
        assert "Strategy A (SMC Sniper)" in confluence_text
        assert "Strategy B (Momentum Catcher)" in confluence_text
        assert "82.0/100" in confluence_text
        assert "86.0/100" in confluence_text

        # 2. Test Conflict formatting
        conflict_text = TelegramMessageFormatter.format_multi_strategy_alert([sig_a, sig_b_conflicting])
        assert "STRATEGY CONFLICT" in conflict_text
        assert "Strategy A (SMC Sniper)" in conflict_text
        assert "Strategy B (Momentum Catcher)" in conflict_text
        assert "BUY" in conflict_text
        assert "SELL" in conflict_text

    def test_momentum_strategy_score_breakdown_validation(self):
        """Verify ScoreBreakdown does not fail Pydantic validation when final_score is high."""
        strat_b = MomentumStrategy()
        now = datetime.now(timezone.utc)
        bull_div = RSIDivergence(
            divergence_type=DivergenceType.REGULAR_BULLISH,
            start_index=10,
            end_index=20,
            start_timestamp=now,
            end_timestamp=now,
            price_start=1990.0,
            price_end=1985.0,
            rsi_start=28.0,
            rsi_end=35.0,
            strength=0.9,
        )
        indicators = _build_mock_indicators(
            golden_cross=True,
            ema_trend="BULLISH_STACK",
            price_vs_ema200="ABOVE",
            rsi_value=60.0,
            rsi_condition="BULLISH_ZONE",
            divergences=[bull_div],
            volatility_state="HIGH",
        )
        structure = _build_mock_structure()

        result = strat_b.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[],
            indicators=indicators,
            structure=structure,
        )

        assert result.score_breakdown is not None
        assert result.score_breakdown.indicators_score <= 25.0
        assert result.score_breakdown.total_score <= 100.0
        assert result.score_breakdown.structure_score <= 30.0
        assert result.score_breakdown.liquidity_score <= 25.0
        assert result.score_breakdown.price_action_score <= 20.0

