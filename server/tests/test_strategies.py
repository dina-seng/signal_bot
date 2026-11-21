"""Unit tests for Strategy Engine architecture and Strategy A (SMC Sniper)."""

from datetime import datetime, timezone
import pytest

from app.schemas.indicators import (
    ATRSnapshot,
    EMASnapshot,
    FairValueGap,
    FVGType,
    IndicatorAnalysisResponse,
    PatternType,
    PriceActionPattern,
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
from app.schemas.structure import (
    MultiTimeframeAlignment,
    MultiTimeframeStructureResponse,
    StructureAnalysisResponse,
    TrendDirection,
)
from app.services.signals.evaluators import (
    LiquiditySMCConsensusEvaluator,
    StructureConsensusEvaluator,
)
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

    def test_strategy_manager_registers_default_strategies(self):
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
        strat_names = [r.strategy_name for r in results]
        assert "Strategy A (SMC Sniper)" in strat_names


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

    def test_smc_strategy_3_pillar_high_confluence_qualification(self):
        """Verify Strategy A qualifies without momentum indicators under the 3-pillar 35/40/25 scoring."""
        now = datetime.now(timezone.utc)
        base_struct = StructureAnalysisResponse(
            symbol="XAU/USD",
            timeframe="1h",
            trend=TrendDirection.BULLISH,
            trend_strength=1.0,
            key_support=1990.0,
            key_resistance=2030.0,
            total_candles=50,
            total_swings=6,
            timestamp=now,
        )
        structure = AdvancedStructureAnalysisResponse(
            symbol="XAU/USD",
            timeframe="1h",
            trend=TrendDirection.BULLISH,
            trend_strength=1.0,
            market_state="BULLISH_TREND_CONTINUATION",
            base_structure=base_struct,
            latest_bos=BreakoutEvent(
                index=46,  # 3 bars ago -> recent
                timestamp=now,
                event_type=BOSCHOCHType.BULLISH_BOS,
                breakout_price=2015.0,
                broken_swing_price=2010.0,
                broken_swing_index=40,
                broken_swing_timestamp=now,
                displacement_strength=0.9,
            ),
            latest_sweep=LiquiditySweep(
                index=45,  # 4 bars ago -> recent
                timestamp=now,
                sweep_type=LiquidityEventType.SELL_SIDE_SWEEP,
                swept_level=1995.0,
                sweep_extreme=1992.0,
                close_price=2000.0,
                wick_ratio=0.75,
                pips_swept=30.0,
            ),
            liquidity_pools=[],
            sr_zones=[],
        )
        mtf = MultiTimeframeStructureResponse(
            symbol="XAU/USD",
            primary_timeframe="4h",
            primary_trend=TrendDirection.BULLISH,
            alignment=MultiTimeframeAlignment.BULLISH_ALIGNED,
            alignment_score=1.0,
            timeframes={"4h": base_struct, "1h": base_struct, "15m": base_struct},
            summary="All timeframes Bullish Aligned",
        )
        active_fvg = FairValueGap(
            index=44,
            timestamp=now,
            fvg_type=FVGType.BULLISH_FVG,
            top_price=2005.0,
            bottom_price=1995.0,
            gap_size=10.0,
            gap_pips=100.0,
            is_mitigated=False,
        )
        indicators = IndicatorAnalysisResponse(
            symbol="XAU/USD",
            timeframe="1h",
            timestamp=now,
            current_price=2000.0,  # inside the FVG (1995 <= 2000 <= 2005)
            ema=EMASnapshot(ema_trend="NEUTRAL"),
            rsi=RSISnapshot(rsi_value=50.0, condition="NEUTRAL"),
            atr=ATRSnapshot(atr_value=5.0, atr_pips=50.0),
            divergences=[],
            recent_patterns=[
                PriceActionPattern(
                    index=49,
                    timestamp=now,
                    pattern_type=PatternType.BULLISH_PIN_BAR,
                    confidence=1.0,
                    description="Strong Bullish Pin Bar",
                )
            ],
            active_fvgs=[active_fvg],
            confluence_bias="NEUTRAL",
            confluence_score=0.0,
        )

        strat = SMCStrategy(min_score_threshold=75.0)
        res = strat.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[],
            indicators=indicators,
            structure=structure,
            mtf=mtf,
        )

        assert res.direction == SignalDirection.BUY
        assert res.score >= 75.0
        assert res.score_breakdown.indicators_score == 0.0
        assert res.score_breakdown.structure_score == 35.0  # 10 trend + 10 MTF + 15 BOS
        assert res.score_breakdown.liquidity_score >= 30.0  # 20 sweep + 10 active FVG
        assert res.score_breakdown.price_action_score == 25.0  # 25 pin bar

    def test_fvg_active_retracement_logic(self):
        """Verify FVG points are awarded only when current price actively retraces into the FVG zone."""
        now = datetime.now(timezone.utc)
        evaluator = LiquiditySMCConsensusEvaluator(max_bars_ago=15)
        base_struct = StructureAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", trend=TrendDirection.RANGING,
            trend_strength=0.0, key_support=None, key_resistance=None, total_candles=50,
            total_swings=0, timestamp=now,
        )
        structure = AdvancedStructureAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", trend=TrendDirection.RANGING,
            trend_strength=0.0, market_state="RANGING", base_structure=base_struct,
        )
        fvg = FairValueGap(
            index=40, timestamp=now, fvg_type=FVGType.BULLISH_FVG,
            top_price=2005.0, bottom_price=1995.0, gap_size=10.0, gap_pips=100.0,
            is_mitigated=False,
        )

        # 1. Price is INSIDE FVG zone (2000.0 is between 1995 and 2005) -> Points awarded
        eval_inside = evaluator.evaluate(
            direction=SignalDirection.BUY,
            structure=structure,
            current_price=2000.0,
            active_fvgs=[fvg],
        )
        assert eval_inside.score == 10.0
        assert any("Price Retraced into Active Bullish FVG" in c for c in eval_inside.catalysts)

        # 2. Price is OUTSIDE FVG zone (2015.0 is above 2005) -> Points NOT awarded
        eval_outside = evaluator.evaluate(
            direction=SignalDirection.BUY,
            structure=structure,
            current_price=2015.0,
            active_fvgs=[fvg],
        )
        assert eval_outside.score == 0.0

    def test_recency_window_stale_events_ignored(self):
        """Verify BOS and Sweeps older than 15 bars are ignored and do not trigger opposing penalties."""
        now = datetime.now(timezone.utc)
        struct_eval = StructureConsensusEvaluator(max_bars_ago=15)
        liq_eval = LiquiditySMCConsensusEvaluator(max_bars_ago=15)

        base_struct = StructureAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", trend=TrendDirection.RANGING,
            trend_strength=0.0, key_support=None, key_resistance=None, total_candles=50,
            total_swings=0, timestamp=now,
        )
        # Event at index 25 in a 50-candle series is 24 bars ago (> 15 bars)
        stale_bos = BreakoutEvent(
            index=25, timestamp=now, event_type=BOSCHOCHType.BULLISH_BOS,
            breakout_price=2000.0, broken_swing_price=1990.0, broken_swing_index=20,
            broken_swing_timestamp=now, displacement_strength=1.0,
        )
        stale_sweep = LiquiditySweep(
            index=25, timestamp=now, sweep_type=LiquidityEventType.SELL_SIDE_SWEEP,
            swept_level=1990.0, sweep_extreme=1985.0, close_price=1992.0,
            wick_ratio=0.8, pips_swept=20.0,
        )
        stale_opposing_choch = BreakoutEvent(
            index=25, timestamp=now, event_type=BOSCHOCHType.BEARISH_CHOCH,
            breakout_price=1980.0, broken_swing_price=1990.0, broken_swing_index=20,
            broken_swing_timestamp=now, displacement_strength=1.0,
        )

        struct = AdvancedStructureAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", trend=TrendDirection.RANGING,
            trend_strength=0.0, market_state="RANGING", base_structure=base_struct,
            latest_bos=stale_bos, latest_sweep=stale_sweep, latest_choch=stale_opposing_choch,
        )

        # Stale BOS should NOT award 15 pts
        res_struct = struct_eval.evaluate(SignalDirection.BUY, struct)
        assert res_struct.score == 4.0  # Only ranging baseline, 0 for stale BOS

        # Stale opposing CHOCH should NOT be added to opposing signals
        assert not any("Opposing Bearish CHOCH" in o for o in res_struct.opposing_signals)

        # Stale sweep should NOT award 20 pts
        res_liq = liq_eval.evaluate(SignalDirection.BUY, struct, current_price=2000.0)
        assert res_liq.score == 0.0
