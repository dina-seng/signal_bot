"""Unit tests for Candle Range Theory (CRT) Strategy and AMD Framework."""

from datetime import datetime, timezone
import pytest

from app.schemas.candle import CandleBase
from app.schemas.indicators import ATRSnapshot, EMASnapshot, IndicatorAnalysisResponse, RSISnapshot
from app.schemas.liquidity import AdvancedStructureAnalysisResponse
from app.schemas.signal import SignalDirection
from app.schemas.structure import CRTAnalysis, StructureAnalysisResponse, TrendDirection
from app.services.signals.confluence_engine import ConfluenceEngine
from app.services.strategies.crt_strategy import CRTStrategy
from app.services.strategies.strategy_manager import StrategyManager
from app.services.structure.crt_analyzer import CRTAnalyzer


def _make_candle(
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
    timestamp: datetime = None,
    volume: float = 1000.0,
    symbol: str = "XAU/USD",
    timeframe: str = "1h",
) -> CandleBase:
    """Helper to create a CandleBase instance."""
    return CandleBase(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp or datetime.now(timezone.utc),
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        volume=volume,
    )



class TestCRTStrategy:
    """Comprehensive test suite for Candle Range Theory (CRT) strategy."""

    def test_crt_amd_logic(self):
        """STEP 5 TEST: Verify Bullish AMD setup qualifications and risk parameters.

        Mocks:
        - A bullish 1H range candle: range 1950.0 to 2100.0 (size 150.0, close > open).
        - A 15m candle that sweeps the low by 10% of the range (low = 1935.0, sweep depth = 15.0).
        - A subsequent 15m candle that closes back above the range low (close = 1965.0).

        Asserts:
        - Strategy returns qualified BUY signal.
        - Stop loss is placed exactly at the manipulation breach point (1935.0).
        - Take profit 1 is placed at 1.5 R:R (1965.0 + 30.0 * 1.5 = 2010.0).
        - Base score is 80.0.
        """
        now = datetime.now(timezone.utc)

        # 1. Bullish 1H Range Candle (Accumulation)
        # Open=2000, High=2100, Low=1950, Close=2080 -> Range Size = 150, positive_direction = True
        range_candle = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)

        # 2. 15m Candle Sweeping the Low by 10% (Manipulation)
        # 10% of 150 = 15. Low = 1950 - 15 = 1935.0
        manip_candle = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=now)

        # 3. Subsequent 15m Candle Closing Back Inside Range (Distribution)
        # Close = 1965.0 (> range_low 1950.0)
        confirm_candle = _make_candle(1945.0, 1970.0, 1940.0, 1965.0, timestamp=now)

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
        )

        # Assertions
        assert result.direction == SignalDirection.BUY
        assert result.score == 80.0
        assert result.score_breakdown.is_qualified is True
        assert result.score_breakdown.total_score == 80.0

        # Risk Management Assertions
        expected_entry = 1965.0
        expected_sl = 1935.0  # breach point
        risk_dist = expected_entry - expected_sl  # 30.0
        expected_tp1 = expected_entry + (risk_dist * 1.5)  # 2010.0

        assert result.stop_loss == expected_sl
        assert result.metadata["stop_loss"] == expected_sl
        assert result.metadata["entry_price"] == expected_entry
        assert result.metadata["take_profit_1"] == pytest.approx(expected_tp1)
        assert result.metadata["risk_reward"] == 1.5

        # Metadata & CRT Analysis Assertions
        crt_data = result.metadata["crt_analysis"]
        assert crt_data["is_breached"] is True
        assert crt_data["is_confirmed"] is True
        assert crt_data["breach_point"] == 1935.0
        assert crt_data["manip_depth_pct"] == pytest.approx(10.0)
        assert crt_data["positive_direction"] is True

        # Reasons mention AMD phases
        joined_reasons = " ".join(result.reasons)
        assert "Accumulation" in joined_reasons
        assert "Manipulation" in joined_reasons
        assert "Distribution" in joined_reasons
        assert "1935.0" in joined_reasons

    def test_crt_bearish_amd_logic(self):
        """Verify Bearish AMD setup: sweeps high by 10%, closes back below range high."""
        now = datetime.now(timezone.utc)

        # 1. Bearish 1H Range Candle (Close < Open)
        # Open=2080, High=2100, Low=1950, Close=1970 -> Range Size = 150, positive_direction = False
        range_candle = _make_candle(2080.0, 2100.0, 1950.0, 1970.0, timestamp=now)

        # 2. 15m Manipulation: sweeps range_high (2100.0) by 10% (15.0) -> High = 2115.0
        manip_candle = _make_candle(2095.0, 2115.0, 2085.0, 2105.0, timestamp=now)

        # 3. 15m Confirmation: closes back below range_high (2100.0) -> Close = 2085.0
        confirm_candle = _make_candle(2105.0, 2108.0, 2075.0, 2085.0, timestamp=now)

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
        )

        assert result.direction == SignalDirection.SELL
        assert result.score == 80.0
        assert result.stop_loss == 2115.0

        expected_entry = 2085.0
        expected_sl = 2115.0
        risk_dist = expected_sl - expected_entry  # 30.0
        expected_tp1 = expected_entry - (risk_dist * 1.5)  # 2040.0

        assert result.metadata["take_profit_1"] == pytest.approx(expected_tp1)
        assert result.metadata["crt_analysis"]["manip_depth_pct"] == pytest.approx(10.0)
        assert result.metadata["crt_analysis"]["positive_direction"] is False

    def test_crt_shallow_manipulation_rejected(self):
        """Manipulation depth < min_manip_pct (e.g. 2% < 5%) should be rejected (WAIT)."""
        now = datetime.now(timezone.utc)

        # Range size = 100.0 (2000.0 to 2100.0)
        range_candle = _make_candle(2010.0, 2100.0, 2000.0, 2090.0, timestamp=now)

        # Sweep low by only 2.0 (2.0%) -> Low = 1998.0
        manip_candle = _make_candle(2005.0, 2010.0, 1998.0, 2002.0, timestamp=now)
        confirm_candle = _make_candle(2002.0, 2020.0, 2001.0, 2015.0, timestamp=now)

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
        )

        assert result.direction == SignalDirection.WAIT
        assert result.score == 0.0
        assert result.metadata["gatekeeper_passed"] is False
        assert result.metadata["crt_analysis"]["manip_depth_pct"] == pytest.approx(2.0)

    def test_crt_unconfirmed_breach_returns_wait(self):
        """Manipulation occurred, but price failed to close back inside range."""
        now = datetime.now(timezone.utc)

        # Range: 1950.0 to 2100.0
        range_candle = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)

        # Sweeps low to 1935.0 (10%)
        manip_candle = _make_candle(1955.0, 1960.0, 1935.0, 1940.0, timestamp=now)

        # Subsequent candle STILL closes below range_low (Close = 1942.0 < 1950.0)
        unconfirmed_candle = _make_candle(1940.0, 1948.0, 1938.0, 1942.0, timestamp=now)

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            candles_15m=[manip_candle, unconfirmed_candle],
        )

        assert result.direction == SignalDirection.WAIT
        assert result.score == 0.0
        assert result.metadata["crt_analysis"]["is_confirmed"] is False

    def test_crt_no_breach_returns_wait(self):
        """No manipulation breach occurred (confirm candles strictly inside range)."""
        now = datetime.now(timezone.utc)
        range_candle = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)
        candle_1 = _make_candle(2000.0, 2040.0, 1980.0, 2020.0, timestamp=now)
        candle_2 = _make_candle(2020.0, 2060.0, 2010.0, 2050.0, timestamp=now)

        strategy = CRTStrategy()
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            candles_15m=[candle_1, candle_2],
        )

        assert result.direction == SignalDirection.WAIT
        assert result.score == 0.0
        assert result.metadata["crt_analysis"]["is_breached"] is False

    def test_crt_multi_bar_confirmation(self):
        """When confirm_bars=2, all last 2 candles must close inside the range."""
        now = datetime.now(timezone.utc)
        range_candle = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)
        manip_candle = _make_candle(1955.0, 1960.0, 1935.0, 1940.0, timestamp=now)
        confirm_1 = _make_candle(1940.0, 1960.0, 1938.0, 1955.0, timestamp=now)  # Inside (1955 > 1950)
        confirm_2_fail = _make_candle(1955.0, 1956.0, 1940.0, 1945.0, timestamp=now)  # Outside (1945 < 1950)

        strategy = CRTStrategy(confirm_bars=2)
        # Should fail because 2nd bar closed outside
        res_fail = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_1, confirm_2_fail],
        )
        assert res_fail.direction == SignalDirection.WAIT

        confirm_2_pass = _make_candle(1955.0, 1970.0, 1952.0, 1968.0, timestamp=now)  # Inside
        res_pass = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_1, confirm_2_pass],
        )
        assert res_pass.direction == SignalDirection.BUY
        assert res_pass.score == 80.0

    def test_crt_analyzer_edge_cases(self):
        """CRTAnalyzer direct unit testing for empty sequences and zero range."""
        res_empty = CRTAnalyzer.analyze([], [])
        assert res_empty.is_breached is False
        assert res_empty.is_confirmed is False
        assert res_empty.manip_depth_pct == 0.0

        # Flat range candle (high == low)
        flat_candle = _make_candle(2000.0, 2000.0, 2000.0, 2000.0)
        res_flat = CRTAnalyzer.analyze([flat_candle], [flat_candle])
        assert res_flat.is_breached is False
        assert res_flat.manip_depth_pct == 0.0

    def test_strategy_manager_runs_crt_strategy(self):
        """Verify CRTStrategy runs cleanly inside StrategyManager alongside other strategies."""
        manager = StrategyManager()
        names = [s.name for s in manager.strategies]
        assert "Candle Range Theory (CRT)" in names

        now = datetime.now(timezone.utc)
        range_candle = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)
        manip_candle = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=now)
        confirm_candle = _make_candle(1945.0, 1970.0, 1940.0, 1965.0, timestamp=now)

        base_struct = StructureAnalysisResponse(
            symbol="XAU/USD",
            timeframe="1h",
            trend=TrendDirection.RANGING,
            trend_strength=0.0,
            key_support=1950.0,
            key_resistance=2100.0,
            total_candles=10,
            total_swings=0,
            timestamp=now,
        )
        struct = AdvancedStructureAnalysisResponse(
            symbol="XAU/USD",
            timeframe="1h",
            timestamp=now,
            current_price=1965.0,
            trend=TrendDirection.RANGING,
            trend_strength=0.0,
            market_state="RANGING",
            base_structure=base_struct,
        )
        indicators = IndicatorAnalysisResponse(
            symbol="XAU/USD",
            timeframe="1h",
            timestamp=now,
            current_price=1965.0,
            ema=EMASnapshot(),
            rsi=RSISnapshot(rsi_value=50.0, condition="NEUTRAL"),
            atr=ATRSnapshot(atr_value=5.0, atr_pips=50.0),
            divergences=[],
            recent_patterns=[],
            active_fvgs=[],
            confluence_bias="NEUTRAL",
            confluence_score=0.0,
        )

        results = manager.run_all_strategies(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            indicators=indicators,
            structure=struct,
            candles_15m=[manip_candle, confirm_candle],
        )

        crt_res = next((r for r in results if r.strategy_name == "Candle Range Theory (CRT)"), None)
        assert crt_res is not None
        assert crt_res.direction == SignalDirection.BUY
        assert crt_res.score == 80.0
        assert crt_res.stop_loss == 1935.0

    def test_confluence_engine_evaluates_crt_custom_sl(self):
        """Verify ConfluenceEngine respects CRT custom SL and 1.5 RR TP1 in SignalResponse."""
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        # Create 30 closed 1H candles; last one started 1 hour ago
        candles_1h = [
            _make_candle(
                2000.0, 2100.0, 1950.0, 2080.0,
                timestamp=now - timedelta(hours=31 - k),
                timeframe="1h",
            )
            for k in range(30)
        ]
        # Create closed 15m candles; manipulation and confirmation
        candles_15m = [
            _make_candle(
                1955.0, 1960.0, 1935.0, 1945.0,
                timestamp=now - timedelta(minutes=45),
                timeframe="15m",
            ),
            _make_candle(
                1945.0, 1970.0, 1940.0, 1965.0,
                timestamp=now - timedelta(minutes=30),
                timeframe="15m",
            ),
            _make_candle(
                1965.0, 1975.0, 1960.0, 1970.0,
                timestamp=now - timedelta(minutes=15),
                timeframe="15m",
            ),
        ]

        engine = ConfluenceEngine()
        signals = engine.evaluate_multi(
            symbol="XAU/USD",
            timeframe="1h",
            candles_primary=candles_1h,
            candles_15m=candles_15m,
        )

        crt_sig = next((s for s in signals if s.strategy_name == "Candle Range Theory (CRT)"), None)
        assert crt_sig is not None
        assert crt_sig.direction == SignalDirection.BUY
        assert crt_sig.setup_score == 80.0
        assert crt_sig.stop_loss == 1935.0
        assert crt_sig.trend_alignment == "CRT / AMD EXPANSION"

