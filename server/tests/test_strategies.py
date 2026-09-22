"""Unit tests for Strategy Engine architecture and Strategy A (SMC Sniper)."""

from datetime import datetime, timezone
import pytest

from app.schemas.indicators import (
    ATRSnapshot,
    EMASnapshot,
    IndicatorAnalysisResponse,
    RSISnapshot,
)
from app.schemas.liquidity import (
    AdvancedStructureAnalysisResponse,
)
from app.schemas.signal import SignalDirection, SignalResponse
from app.schemas.structure import StructureAnalysisResponse, TrendDirection
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


class TestStrategyArchitecture:
    """Verify Strategy A registration and execution within StrategyManager."""

    def test_strategy_names_are_standardized(self):
        strat_a = SMCStrategy()
        assert strat_a.name == "Strategy A (SMC Sniper)"

    def test_strategy_manager_registers_only_smc_strategy(self):
        manager = StrategyManager()
        names = [s.name for s in manager.strategies]
        assert "Strategy A (SMC Sniper)" in names
        assert len(names) == 1

    def test_strategy_manager_runs_registered_strategy(self):
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

        assert len(results) == 1
        assert results[0].strategy_name == "Strategy A (SMC Sniper)"

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
            reasons=["Bullish Breakout", "RSI Expansion"],
            strategy_name="Strategy Alpha (Experimental)",
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
            reasons=["Bearish Breakdown"],
            strategy_name="Strategy Alpha (Experimental)",
            timestamp=now,
        )

        # 1. Test Confluence formatting
        confluence_text = TelegramMessageFormatter.format_multi_strategy_alert([sig_a, sig_b_confluent])
        assert "STRATEGY CONFLUENCE" in confluence_text
        assert "Strategy A (SMC Sniper)" in confluence_text
        assert "Strategy Alpha (Experimental)" in confluence_text
        assert "82.0/100" in confluence_text
        assert "86.0/100" in confluence_text

        # 2. Test Conflict formatting
        conflict_text = TelegramMessageFormatter.format_multi_strategy_alert([sig_a, sig_b_conflicting])
        assert "STRATEGY CONFLICT" in conflict_text
        assert "Strategy A (SMC Sniper)" in conflict_text
        assert "Strategy Alpha (Experimental)" in conflict_text
        assert "BUY" in conflict_text
        assert "SELL" in conflict_text
