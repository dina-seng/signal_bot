"""Unit tests for Candle Range Theory (CRT) Strategy and AMD Framework."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from app.schemas.candle import CandleBase
from app.schemas.indicators import (
    ATRSnapshot,
    EMASnapshot,
    FairValueGap,
    FVGType,
    IndicatorAnalysisResponse,
    RSISnapshot,
)
from app.schemas.liquidity import (
    AdvancedStructureAnalysisResponse,
    BOSCHOCHType,
    BreakoutEvent,
    LiquidityEventType,
    LiquidityPool,
    SupportResistanceZone,
    ZoneType,
)
from app.schemas.signal import SignalDirection
from app.schemas.structure import (
    CRTAnalysis,
    MultiTimeframeAlignment,
    MultiTimeframeStructureResponse,
    StructureAnalysisResponse,
    StructureLabel,
    SwingPoint,
    SwingType,
    TrendDirection,
)
from app.services.signals.confluence_engine import ConfluenceEngine
from app.services.strategies.crt_strategy import CRTStrategy, _norm_trend
from app.services.strategies.strategy_manager import StrategyManager
from app.services.structure.crt_analyzer import CRTAnalyzer


SESSION_ACTIVE_TS = datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc)


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
        timestamp=timestamp or SESSION_ACTIVE_TS,
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
        - Stop loss is placed at manipulation breach point (1935.0).
        - Take profit 1 is placed at 1.5 R:R (1965.0 + 30.0 * 1.5 = 2010.0).
        - Score is computed dynamically and is qualified (>= 75.0).
        """
        now = SESSION_ACTIVE_TS

        # 1. Bullish 1H Range Candle (Accumulation)
        range_candle = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)

        # 2. 15m Candle Sweeping the Low by 10% (Manipulation)
        manip_candle = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=now)

        # 3. Subsequent 15m Candle Closing Back Inside Range (Distribution)
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
        assert result.score >= 75.0
        assert result.score_breakdown.is_qualified is True
        assert result.score_breakdown.total_score == result.score

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
        now = SESSION_ACTIVE_TS

        # 1. Bearish 1H Range Candle (Close < Open)
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
        assert result.score >= 75.0
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
        now = SESSION_ACTIVE_TS

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

    def test_crt_excessive_manipulation_rejected(self):
        """Manipulation depth > max_manip_pct (e.g. 200% > 100%) should be rejected (WAIT).

        Prevents news spikes or massive breakouts from generating absurd Stop Losses.
        """
        now = SESSION_ACTIVE_TS

        # Range size = 150.0 (1950.0 to 2100.0)
        range_candle = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)

        # Extreme news spike / massive drop to 1650.0 (depth = 300.0 / 150.0 = 200.0%)
        spike_candle = _make_candle(1955.0, 1960.0, 1650.0, 1700.0, timestamp=now)
        # Rebound closes back inside range
        rebound_candle = _make_candle(1700.0, 1980.0, 1690.0, 1960.0, timestamp=now)

        strategy = CRTStrategy(min_manip_pct=5.0, max_manip_pct=100.0, confirm_bars=1)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            candles_15m=[spike_candle, rebound_candle],
        )

        assert result.direction == SignalDirection.WAIT
        assert result.score == 0.0
        assert result.metadata["gatekeeper_passed"] is False
        assert result.metadata["crt_analysis"]["manip_depth_pct"] == pytest.approx(200.0)

        # Check explicit rejection reason
        joined_reasons = " ".join(result.reasons)
        assert "REJECTED: Manipulation depth (200.0%) exceeds maximum allowed (100.0%)" in joined_reasons
        assert "Likely a breakout/spike, not a sweep" in joined_reasons

    def test_crt_unconfirmed_breach_returns_wait(self):
        """Manipulation occurred, but price failed to close back inside range."""
        now = SESSION_ACTIVE_TS

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
        now = SESSION_ACTIVE_TS
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
        now = SESSION_ACTIVE_TS
        range_candle = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)
        manip_candle = _make_candle(1955.0, 1960.0, 1935.0, 1940.0, timestamp=now)
        confirm_1 = _make_candle(1940.0, 1960.0, 1938.0, 1955.0, timestamp=now)  # Inside
        confirm_2_fail = _make_candle(1955.0, 1956.0, 1940.0, 1945.0, timestamp=now)  # Outside

        strategy = CRTStrategy(confirm_bars=2)
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
        assert res_pass.score >= 75.0

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

        now = SESSION_ACTIVE_TS
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
        assert crt_res.score >= 75.0
        # Stop loss placed beyond sweep extreme with ATR buffer (0.10 * 5.0 = 0.50): 1935.0 - 0.50 = 1934.50
        assert crt_res.stop_loss == pytest.approx(1934.50)

    def test_confluence_engine_evaluates_crt_custom_sl(self):
        """Verify ConfluenceEngine respects CRT custom SL and TP in SignalResponse."""
        now = datetime.now(timezone.utc)
        candles_1h = [
            _make_candle(
                2000.0, 2100.0, 1950.0, 2080.0,
                timestamp=now - timedelta(hours=31 - k),
                timeframe="1h",
            )
            for k in range(30)
        ]
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
        assert crt_sig.setup_score >= 75.0
        assert crt_sig.stop_loss < 1935.0  # Buffer included
        assert crt_sig.trend_alignment == "CRT / AMD EXPANSION"

    def test_crt_htf_trend_filter_rejects_counter_trend_buy(self):
        """Verify Bullish CRT AMD setup is REJECTED when HTF Trend is BEARISH."""
        now = SESSION_ACTIVE_TS
        range_candle = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)
        manip_candle = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=now)
        confirm_candle = _make_candle(1945.0, 1970.0, 1940.0, 1965.0, timestamp=now)

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
            htf_trend="BEARISH",
        )

        assert result.direction == SignalDirection.WAIT
        assert result.score == 0.0
        assert result.score_breakdown.is_qualified is False
        assert result.metadata["gatekeeper_passed"] is False
        assert result.metadata["trend_conflict"] is True
        assert result.metadata["htf_trend"] == "BEARISH"
        assert result.stop_loss == 0.0

        joined_reasons = " ".join(result.reasons)
        assert "REJECTED (Trend Conflict): HTF Trend is BEARISH. Ignoring Bullish CRT setup." in joined_reasons

    def test_crt_htf_trend_filter_rejects_counter_trend_sell(self):
        """Verify Bearish CRT AMD setup is REJECTED when HTF Trend is BULLISH."""
        now = SESSION_ACTIVE_TS
        range_candle = _make_candle(2080.0, 2100.0, 1950.0, 1970.0, timestamp=now)
        manip_candle = _make_candle(2095.0, 2115.0, 2085.0, 2105.0, timestamp=now)
        confirm_candle = _make_candle(2105.0, 2108.0, 2075.0, 2085.0, timestamp=now)

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
            htf_trend="BULLISH",
        )

        assert result.direction == SignalDirection.WAIT
        assert result.score == 0.0
        assert result.score_breakdown.is_qualified is False
        assert result.metadata["gatekeeper_passed"] is False
        assert result.metadata["trend_conflict"] is True
        assert result.metadata["htf_trend"] == "BULLISH"

        joined_reasons = " ".join(result.reasons)
        assert "REJECTED (Trend Conflict): HTF Trend is BULLISH. Ignoring Bearish CRT setup." in joined_reasons

    def test_crt_htf_trend_filter_accepts_aligned_and_ranging(self):
        """Verify CRT setups are accepted when HTF trend aligns or is ranging, with lower score on ranging."""
        now = SESSION_ACTIVE_TS
        bull_range = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)
        bull_manip = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=now)
        bull_confirm = _make_candle(1945.0, 1970.0, 1940.0, 1965.0, timestamp=now)

        strategy_aligned = CRTStrategy(min_manip_pct=5.0, confirm_bars=1)

        # Bullish setup with BULLISH HTF -> BUY
        res_aligned_buy = strategy_aligned.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[bull_range],
            candles_15m=[bull_manip, bull_confirm],
            htf_trend="BULLISH",
        )
        assert res_aligned_buy.direction == SignalDirection.BUY
        assert res_aligned_buy.metadata["htf_trend"] == "BULLISH"

        # Bullish setup with RANGING HTF -> BUY (separate instance to avoid duplicate event suppression)
        strategy_ranging = CRTStrategy(min_manip_pct=5.0, confirm_bars=1)
        res_ranging_buy = strategy_ranging.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[bull_range],
            candles_15m=[bull_manip, bull_confirm],
            htf_trend="RANGING",
        )
        assert res_ranging_buy.direction == SignalDirection.BUY

        # Aligned score is strictly higher than ranging score (Enhancement B)
        assert res_aligned_buy.score > res_ranging_buy.score

        # Bearish setup with BEARISH HTF -> SELL
        bear_range = _make_candle(2080.0, 2100.0, 1950.0, 1970.0, timestamp=now)
        bear_manip = _make_candle(2095.0, 2115.0, 2085.0, 2105.0, timestamp=now)
        bear_confirm = _make_candle(2105.0, 2108.0, 2075.0, 2085.0, timestamp=now)

        res_aligned_sell = strategy_aligned.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[bear_range],
            candles_15m=[bear_manip, bear_confirm],
            htf_trend="BEARISH",
        )
        assert res_aligned_sell.direction == SignalDirection.SELL
        assert res_aligned_sell.score >= 75.0
        assert res_aligned_sell.metadata["htf_trend"] == "BEARISH"

    def test_crt_infers_htf_trend_from_structure_or_mtf(self):
        """Verify CRT automatically infers HTF trend from structure or mtf objects when htf_trend is default."""
        now = SESSION_ACTIVE_TS
        range_candle = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)
        manip_candle = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=now)
        confirm_candle = _make_candle(1945.0, 1970.0, 1940.0, 1965.0, timestamp=now)

        base_struct = StructureAnalysisResponse(
            symbol="XAU/USD",
            timeframe="1h",
            trend=TrendDirection.BEARISH,
            trend_strength=0.8,
            key_support=1950.0,
            key_resistance=2100.0,
            total_candles=10,
            total_swings=0,
            timestamp=now,
        )
        struct_bearish = AdvancedStructureAnalysisResponse(
            symbol="XAU/USD",
            timeframe="1h",
            timestamp=now,
            current_price=1965.0,
            trend=TrendDirection.BEARISH,
            trend_strength=0.8,
            market_state="TRENDING_BEARISH",
            base_structure=base_struct,
        )

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1)

        # Inferred from structure (BEARISH blocks BUY)
        res_struct = strategy.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
            structure=struct_bearish,
        )
        assert res_struct.direction == SignalDirection.WAIT
        assert res_struct.metadata["trend_conflict"] is True
        assert "REJECTED (Trend Conflict): HTF Trend is BEARISH" in " ".join(res_struct.reasons)

        # Inferred from mtf (BEARISH blocks BUY)
        mtf_bearish = MultiTimeframeStructureResponse(
            symbol="XAU/USD",
            primary_timeframe="4h",
            primary_trend=TrendDirection.BEARISH,
            alignment=MultiTimeframeAlignment.BEARISH_ALIGNED,
            alignment_score=1.0,
            timeframes={"1h": base_struct},
            summary="Strong HTF downtrend",
        )
        res_mtf = strategy.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
            mtf=mtf_bearish,
        )
        assert res_mtf.direction == SignalDirection.WAIT
        assert res_mtf.metadata["trend_conflict"] is True
        assert "REJECTED (Trend Conflict): HTF Trend is BEARISH" in " ".join(res_mtf.reasons)

    def test_confluence_engine_passes_htf_trend_to_crt(self):
        """Verify ConfluenceEngine forwards HTF trend into strategy.analyze and rejects counter-trend CRT."""
        now = datetime.now(timezone.utc)
        candles_1h = [
            _make_candle(
                2000.0, 2100.0, 1950.0, 2080.0,
                timestamp=now - timedelta(hours=31 - k),
                timeframe="1h",
            )
            for k in range(30)
        ]
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
            htf_trend="BEARISH",
        )

        crt_sig = next((s for s in signals if s.strategy_name == "Candle Range Theory (CRT)"), None)
        assert crt_sig is not None
        assert crt_sig.direction == SignalDirection.WAIT
        assert crt_sig.setup_score == 0.0
        assert crt_sig.htf_trend == "BEARISH"
        joined_reasons = " ".join(crt_sig.reasons)
        assert "REJECTED (Trend Conflict): HTF Trend is BEARISH. Ignoring Bullish CRT setup." in joined_reasons

    # ==================================================================
    # NEW TESTS: Addressing All Required Enhancements & Fixes
    # ==================================================================

    def test_trend_normalization_with_lowercase_and_enums(self):
        """Fix 2: Test trend normalization helper across lowercase strings and enums."""
        assert _norm_trend("bullish") == "BULLISH"
        assert _norm_trend("Bearish") == "BEARISH"
        assert _norm_trend("ranging") == "RANGING"
        assert _norm_trend(TrendDirection.BULLISH) == "BULLISH"
        assert _norm_trend(TrendDirection.BEARISH) == "BEARISH"
        assert _norm_trend(TrendDirection.RANGING) == "RANGING"
        assert _norm_trend(None) == "RANGING"

        # Verify lowercase trend string in analyze() rejects counter-trend properly
        now = SESSION_ACTIVE_TS
        range_candle = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)
        manip_candle = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=now)
        confirm_candle = _make_candle(1945.0, 1970.0, 1940.0, 1965.0, timestamp=now)

        strategy = CRTStrategy()
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
            htf_trend="bearish",  # lowercase string
        )
        assert result.direction == SignalDirection.WAIT
        assert result.metadata["trend_conflict"] is True
        assert result.metadata["htf_trend"] == "BEARISH"

    def test_missing_htf_candles_returns_wait(self):
        """Fix 3: When no HTF accumulation candles are supplied, return WAIT with an explicit reason."""
        now = SESSION_ACTIVE_TS
        c15m = [_make_candle(2650.0, 2655.0, 2645.0, 2652.0, timestamp=now, timeframe="15m")]

        strategy = CRTStrategy()
        # Call with 15m candles as primary and no HTF range candles
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=c15m,
            candles_15m=c15m,  # Silent fallback attempt
        )

        assert result.direction == SignalDirection.WAIT
        assert result.score == 0.0
        assert result.metadata["gatekeeper_passed"] is False
        assert result.metadata["rejection_gate"] == "MISSING_HTF_CANDLES"
        assert "Missing HTF accumulation range candles" in result.reasons[0]

    def test_buy_with_stop_above_entry_rejected(self):
        """Fix 4: BUY setup where stop loss >= entry price must be rejected (no abs() masking)."""
        now = SESSION_ACTIVE_TS
        # Range candle
        range_c = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)
        # Manip sweeps low to 1935.0
        manip_c = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=now)
        # Confirm close at 1930.0 (below stop loss 1935.0!)
        confirm_c = _make_candle(1935.0, 1936.0, 1928.0, 1930.0, timestamp=now)

        strategy = CRTStrategy()
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
        )

        assert result.direction == SignalDirection.WAIT
        assert result.metadata["setup_state"] in ("WAITING_FOR_CONFIRMATION", "INVALIDATED_SETUP")
        assert result.score == 0.0

    def test_micro_sweep_below_minimum_rejected(self):
        """Enhancement B: Sweep below absolute minimum or ATR fraction must be rejected."""
        now = SESSION_ACTIVE_TS
        # Range size = 100.0 (2600 to 2700)
        range_c = _make_candle(2620.0, 2700.0, 2600.0, 2680.0, timestamp=now)
        # Low sweeps only by $0.10 (0.1% depth, less than min 5%)
        manip_c = _make_candle(2605.0, 2610.0, 2599.90, 2602.0, timestamp=now)
        confirm_c = _make_candle(2602.0, 2615.0, 2601.0, 2610.0, timestamp=now)

        strategy = CRTStrategy(min_sweep_atr_mult=0.15)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
            atr_value=10.0,  # 0.15 * 10 = $1.50 minimum sweep required
        )

        assert result.direction == SignalDirection.WAIT
        assert result.metadata["rejection_gate"] == "MICRO_SWEEP"
        assert "REJECTED (Micro-sweep)" in result.reasons[0]

    def test_range_size_quality_gate(self):
        """Enhancement B: Ranges that are too narrow (micro-range) or too wide (outlier volatility) are rejected."""
        now = SESSION_ACTIVE_TS
        strategy = CRTStrategy(min_range_atr_mult=0.5, max_range_atr_mult=3.0)

        # 1. Micro-range: Range size = 2.0 with ATR = 10.0 (< 0.5x ATR)
        micro_range = _make_candle(2650.0, 2652.0, 2650.0, 2651.5, timestamp=now)
        c1 = _make_candle(2650.0, 2651.0, 2649.0, 2650.5, timestamp=now)
        res_micro = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[micro_range],
            candles_15m=[c1],
            atr_value=10.0,
        )
        assert res_micro.direction == SignalDirection.WAIT
        assert res_micro.metadata["rejection_gate"] == "MICRO_RANGE"

        # 2. Giant candle: Range size = 45.0 with ATR = 10.0 (> 3.0x ATR)
        giant_range = _make_candle(2600.0, 2645.0, 2600.0, 2640.0, timestamp=now)
        c2 = _make_candle(2605.0, 2610.0, 2595.0, 2605.0, timestamp=now)
        res_giant = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[giant_range],
            candles_15m=[c2],
            atr_value=10.0,
        )
        assert res_giant.direction == SignalDirection.WAIT
        assert res_giant.metadata["rejection_gate"] == "EXCESSIVE_RANGE"

    def test_opposing_fvg_within_1r_downgrades_or_rejects(self):
        """Enhancement B: Opposing unmitigated FVG within 1R of entry blocks the trade path."""
        now = SESSION_ACTIVE_TS
        range_c = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)
        manip_c = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=now)
        confirm_c = _make_candle(1945.0, 1970.0, 1940.0, 1965.0, timestamp=now)

        # Entry is 1965.0, SL is 1935.0 -> Risk distance = 30.0.
        # An opposing Bearish FVG sits at 1975.0 (only 10.0 away = 0.33R < 1.0R!)
        blocking_fvg = FairValueGap(
            index=1,
            timestamp=now,
            fvg_type=FVGType.BEARISH_FVG,
            top_price=1980.0,
            bottom_price=1975.0,
            gap_size=5.0,
            gap_pips=50.0,
            is_mitigated=False,
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
            active_fvgs=[blocking_fvg],
            confluence_bias="NEUTRAL",
            confluence_score=0.0,
        )

        strategy = CRTStrategy()
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
            indicators=indicators,
        )

        assert result.direction == SignalDirection.WAIT
        assert result.metadata["setup_state"] == "POTENTIAL_SETUP"
        assert result.metadata["rejection_gate"] == "PATH_BLOCKED"
        assert "Clear Path Blocked" in result.reasons[0]

    def test_off_session_returns_wait(self):
        """Enhancement B: Outside allowed trading sessions (Asia, London, NY) returns WAIT when session filter is enabled."""
        ny_tz = ZoneInfo("America/New_York")
        # 08:15 AM NY is off-session (between London close 07:00 and NY open 09:30)
        off_session_time = datetime(2026, 9, 24, 8, 15, tzinfo=ny_tz).astimezone(timezone.utc)

        range_c = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=off_session_time)
        manip_c = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=off_session_time)
        confirm_c = _make_candle(1945.0, 1970.0, 1940.0, 1965.0, timestamp=off_session_time)

        strategy = CRTStrategy(session_filter_enabled=True)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
        )

        assert result.direction == SignalDirection.WAIT
        assert result.metadata["rejection_gate"] == "OFF_SESSION"
        assert "Session Gate" in result.reasons[0]

    def test_stop_moves_beyond_nearby_liquidity_pool(self):
        """Enhancement C: SL is extended beyond an adjacent resting liquidity pool within 1R."""
        now = SESSION_ACTIVE_TS
        range_c = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)
        # Breach point is 1935.0
        manip_c = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=now)
        confirm_c = _make_candle(1945.0, 1970.0, 1940.0, 1965.0, timestamp=now)

        # Equal lows liquidity pool sits just below the breach point at 1933.0
        pool = LiquidityPool(
            pool_type=LiquidityEventType.EQUAL_LOWS,
            price_level=1933.0,
            touch_points=2,
            first_timestamp=now,
            last_timestamp=now,
            is_swept=False,
        )
        base_struct = StructureAnalysisResponse(
            symbol="XAU/USD",
            timeframe="1h",
            trend=TrendDirection.BULLISH,
            trend_strength=0.8,
            total_candles=10,
            total_swings=0,
            timestamp=now,
        )
        struct = AdvancedStructureAnalysisResponse(
            symbol="XAU/USD",
            timeframe="1h",
            timestamp=now,
            current_price=1965.0,
            trend=TrendDirection.BULLISH,
            trend_strength=0.8,
            market_state="EXPANSION",
            base_structure=base_struct,
            liquidity_pools=[pool],
        )

        strategy = CRTStrategy()
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
            structure=struct,
            atr_value=5.0,
        )

        assert result.direction == SignalDirection.BUY
        # Stop loss should be moved below the 1933.0 liquidity pool
        assert result.stop_loss <= 1933.0

    def test_tp_capped_before_opposing_ob_or_fvg(self):
        """Enhancement D: TP1 is capped before an opposing barrier when clear path >= 1R."""
        now = SESSION_ACTIVE_TS
        range_c = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)
        manip_c = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=now)
        confirm_c = _make_candle(1945.0, 1970.0, 1940.0, 1965.0, timestamp=now)

        # Entry = 1965.0, SL = 1935.0 -> Risk = 30.0. Base TP1 would be 1965 + 45 = 2010.0.
        # An opposing Bearish FVG sits at 2005.0 (40.0 away = 1.33R >= 1.0R, but < 2010.0).
        opposing_fvg = FairValueGap(
            index=1,
            timestamp=now,
            fvg_type=FVGType.BEARISH_FVG,
            top_price=2015.0,
            bottom_price=2005.0,
            gap_size=10.0,
            gap_pips=100.0,
            is_mitigated=False,
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
            active_fvgs=[opposing_fvg],
            confluence_bias="NEUTRAL",
            confluence_score=0.0,
        )

        strategy = CRTStrategy()
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
            indicators=indicators,
        )

        assert result.direction == SignalDirection.BUY
        assert result.take_profit_1 <= 2005.0  # Capped before the FVG!
        assert "TP1 capped before opposing" in " ".join(result.reasons)

    def test_pip_and_lot_math_risk_exceeds_limit(self):
        """Fixes 5 & 6: 1 pip = $0.10 for XAU/USD. $8.55 stop risks $8.55 on 0.01 lot. Small accounts get flagged."""
        now = SESSION_ACTIVE_TS
        # Range: 2645.0 to 2665.0 (size $20.00)
        # Breach: low 2641.45 ($3.55 below range low, depth 17.75% >= 5%)
        # Entry / Confirm close: 2650.00 (cleanly inside range > 2645.0)
        range_c = _make_candle(2648.0, 2665.0, 2645.0, 2662.0, timestamp=now)
        manip_c = _make_candle(2646.0, 2648.0, 2641.45, 2644.0, timestamp=now + timedelta(minutes=15))
        confirm_c = _make_candle(2644.0, 2652.0, 2643.0, 2650.00, timestamp=now + timedelta(minutes=30))

        strategy = CRTStrategy(spread=0.0)

        # Account: $100.00, 0.5% risk = $0.50 risk budget.
        # Stop distance: $8.55 -> $8.55 / 0.10 = 85.5 pips.
        # Minimum lot: 0.01 lot (1 oz). 1 oz * $8.55 = $8.55 risk.
        # $8.55 > $0.50 budget -> Must flag RISK EXCEEDS LIMIT!
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
            account_balance=100.0,
            risk_percent=0.5,
        )

        meta = result.metadata
        assert meta["risk_pips"] == pytest.approx(85.5, rel=1e-2)
        assert meta["risk_amount_usd"] == pytest.approx(8.55, rel=1e-2)
        assert meta["suggested_lot_size"] == 0.01
        assert "RISK EXCEEDS LIMIT - min lot too large for account" in meta["risk_warning"]
        assert "WARNING: RISK EXCEEDS LIMIT" in " ".join(result.reasons)

    def test_no_lookahead_future_candles_do_not_alter_past_decision(self):
        """Enhancement G: Decision at bar T must never be changed by appending future candles T+1, T+2."""
        t0 = SESSION_ACTIVE_TS
        range_c = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=t0)
        manip_c = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=t0 + timedelta(minutes=15))
        confirm_c = _make_candle(1945.0, 1970.0, 1940.0, 1965.0, timestamp=t0 + timedelta(minutes=30))

        strategy_t = CRTStrategy()
        res_t = strategy_t.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
        )

        # Future candles arrived later (still within London session)
        future_c1 = _make_candle(1965.0, 1980.0, 1962.0, 1975.0, timestamp=t0 + timedelta(minutes=45))
        future_c2 = _make_candle(1975.0, 1990.0, 1970.0, 1985.0, timestamp=t0 + timedelta(minutes=60))

        strategy_future = CRTStrategy()
        res_future = strategy_future.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c, future_c1, future_c2],
        )

        # Past decision core parameters remain consistent and intact
        assert res_t.direction == res_future.direction
        assert res_t.breach_point == res_future.breach_point
        assert res_t.metadata["crt_analysis"]["breach_point"] == res_future.metadata["crt_analysis"]["breach_point"]

    def test_deduplication_by_sweep_event_key(self):
        """Enhancement F: Duplicate signals for the same sweep event are suppressed."""
        t0 = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
        range_c = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=t0)
        manip_c = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=t0 + timedelta(minutes=15))
        confirm_c = _make_candle(1945.0, 1970.0, 1940.0, 1965.0, timestamp=t0 + timedelta(minutes=30))

        strategy = CRTStrategy()
        # First call: Confirmed BUY setup
        res1 = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
        )
        assert res1.direction == SignalDirection.BUY

        # Second call with the same sweep event: must be deduplicated
        res2 = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
        )
        assert res2.direction == SignalDirection.WAIT
        assert res2.metadata["rejection_gate"] == "DEDUPLICATED"
        assert "DEDUPLICATED" in res2.reasons[0]
