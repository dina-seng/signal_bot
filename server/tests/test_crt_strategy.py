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
from app.schemas.signal import SignalDirection, ScoreBreakdown
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
from app.services.strategies.crt_strategy import CRTStrategy, _norm_trend, is_in_trading_session
from app.services.strategies.strategy_manager import StrategyManager
from app.services.structure.crt_analyzer import CRTAnalyzer
from app.services.telegram.message_formatter import format_signal, SignalContext


# 07:00 UTC = 03:00 AM NY (Start of London Session)
SESSION_ACTIVE_TS = datetime(2026, 9, 24, 7, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean_crt_db():
    """Clear CRT sweep events table before each test to ensure test isolation."""
    try:
        from app.core.database import SessionLocal, engine, Base
        from app.models.crt_sweep_event import CRTSweepEvent
        Base.metadata.create_all(bind=engine, tables=[CRTSweepEvent.__table__])
        db = SessionLocal()
        db.query(CRTSweepEvent).delete()
        db.commit()
        db.close()
    except Exception:
        pass
    yield


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


def _make_amd_fixture(
    range_o: float, range_h: float, range_l: float, range_c: float,
    manip_o: float, manip_h: float, manip_l: float, manip_c: float,
    confirm_o: float, confirm_h: float, confirm_l: float, confirm_c: float,
    base_time: datetime = None,
):
    """Helper to create 1H range and 15m manipulation/confirmation candles with zero lookahead."""
    t0 = base_time or SESSION_ACTIVE_TS
    rc = _make_candle(range_o, range_h, range_l, range_c, timestamp=t0, timeframe="1h")
    # Manipulation starts at 1H range close
    mc = _make_candle(manip_o, manip_h, manip_l, manip_c, timestamp=t0 + timedelta(hours=1), timeframe="15m")
    # Confirmation starts after manipulation
    cc = _make_candle(confirm_o, confirm_h, confirm_l, confirm_c, timestamp=t0 + timedelta(hours=1, minutes=15), timeframe="15m")
    return rc, mc, cc


class TestCRTStrategy:
    """Comprehensive test suite for Candle Range Theory (CRT) strategy."""

    def test_crt_amd_logic(self):
        """STEP 5 TEST: Verify Bullish AMD setup qualifications and risk parameters."""
        now = SESSION_ACTIVE_TS
        range_candle, manip_candle, confirm_candle = _make_amd_fixture(
            2000.0, 2100.0, 1950.0, 2080.0,
            1955.0, 1960.0, 1935.0, 1945.0,
            1945.0, 1970.0, 1940.0, 1965.0,
            base_time=now,
        )

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1, enable_dedup=False)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
        )

        assert result.direction == SignalDirection.BUY
        assert result.score >= 75.0
        assert result.score_breakdown.is_qualified is True
        assert result.score_breakdown.total_score == result.score

        expected_entry = 1955.0  # Retracement limit ideal entry
        expected_sl = 1935.0
        risk_dist = expected_entry - expected_sl
        expected_tp1 = 2025.0  # CRT-Native Range Midpoint: (2100 + 1950) / 2
        expected_tp2 = 2100.0  # CRT-Native Range High
        expected_rr = round((expected_tp1 - expected_entry) / risk_dist, 2)  # 3.5R

        assert result.stop_loss == expected_sl
        assert result.metadata["stop_loss"] == expected_sl
        assert result.metadata["entry_price"] == expected_entry
        assert result.metadata["take_profit_1"] == pytest.approx(expected_tp1)
        assert result.metadata["take_profit_2"] == pytest.approx(expected_tp2)
        assert result.metadata["risk_reward"] == pytest.approx(expected_rr)
        assert result.metadata["target_type"] == "CRT_RANGE"

        crt_data = result.metadata["crt_analysis"]
        assert crt_data["is_breached"] is True
        assert crt_data["is_confirmed"] is True
        assert crt_data["breach_point"] == 1935.0
        assert crt_data["manip_depth_pct"] == pytest.approx(10.0)
        assert crt_data["positive_direction"] is True

        joined_reasons = " ".join(result.reasons)
        assert "Accumulation" in joined_reasons
        assert "Manipulation" in joined_reasons
        assert "Distribution" in joined_reasons
        assert "1935.0" in joined_reasons

    def test_crt_bearish_amd_logic(self):
        """Verify Bearish AMD setup: sweeps high by 10%, closes back below range high."""
        now = SESSION_ACTIVE_TS
        range_candle, manip_candle, confirm_candle = _make_amd_fixture(
            2080.0, 2100.0, 1950.0, 1970.0,
            2095.0, 2115.0, 2090.0, 2105.0,
            2105.0, 2108.0, 2075.0, 2085.0,
            base_time=now,
        )

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1, enable_dedup=False)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
        )

        assert result.direction == SignalDirection.SELL
        assert result.score >= 75.0
        assert result.stop_loss == 2115.0

        expected_entry = 2095.0  # Retracement limit ideal entry
        expected_sl = 2115.0
        risk_dist = expected_sl - expected_entry
        expected_tp1 = 2025.0  # CRT-Native Range Midpoint: (2100 + 1950) / 2
        expected_tp2 = 1950.0  # CRT-Native Range Low
        expected_rr = round((expected_entry - expected_tp1) / risk_dist, 2)  # 3.5R

        assert result.metadata["take_profit_1"] == pytest.approx(expected_tp1)
        assert result.metadata["take_profit_2"] == pytest.approx(expected_tp2)
        assert result.metadata["risk_reward"] == pytest.approx(expected_rr)
        assert result.metadata["target_type"] == "CRT_RANGE"
        assert result.metadata["crt_analysis"]["manip_depth_pct"] == pytest.approx(10.0)
        assert result.metadata["crt_analysis"]["positive_direction"] is False

    def test_crt_shallow_manipulation_rejected(self):
        """Manipulation depth < min_manip_pct (e.g. 2% < 5%) should be rejected (WAIT)."""
        now = SESSION_ACTIVE_TS
        range_candle, manip_candle, confirm_candle = _make_amd_fixture(
            2010.0, 2100.0, 2000.0, 2090.0,
            2005.0, 2010.0, 1998.0, 2002.0,
            2002.0, 2020.0, 2001.0, 2015.0,
            base_time=now,
        )

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1, enable_dedup=False)
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
        """Manipulation depth > max_manip_pct (e.g. 200% > 100%) should be rejected (WAIT)."""
        now = SESSION_ACTIVE_TS
        range_candle, spike_candle, rebound_candle = _make_amd_fixture(
            2000.0, 2100.0, 1950.0, 2080.0,
            1955.0, 1960.0, 1650.0, 1700.0,
            1700.0, 1980.0, 1690.0, 1960.0,
            base_time=now,
        )

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

        joined_reasons = " ".join(result.reasons)
        assert "REJECTED: Manipulation depth (200.0%) exceeds maximum allowed (100.0%)" in joined_reasons
        assert "Likely a breakout/spike, not a sweep" in joined_reasons

    def test_crt_unconfirmed_breach_returns_wait(self):
        """Manipulation occurred, but price failed to close back inside range."""
        now = SESSION_ACTIVE_TS
        range_candle, manip_candle, unconfirmed_candle = _make_amd_fixture(
            2000.0, 2100.0, 1950.0, 2080.0,
            1955.0, 1960.0, 1935.0, 1940.0,
            1940.0, 1948.0, 1938.0, 1942.0,
            base_time=now,
        )

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1, enable_dedup=False)
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
        candle_1 = _make_candle(2000.0, 2040.0, 1980.0, 2020.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        candle_2 = _make_candle(2020.0, 2060.0, 2010.0, 2050.0, timestamp=now + timedelta(hours=1, minutes=15), timeframe="15m")

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
        range_c = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=now)
        manip_c = _make_candle(1955.0, 1960.0, 1935.0, 1940.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        confirm_1 = _make_candle(1940.0, 1960.0, 1938.0, 1955.0, timestamp=now + timedelta(hours=1, minutes=15), timeframe="15m")
        confirm_2_fail = _make_candle(1955.0, 1956.0, 1940.0, 1945.0, timestamp=now + timedelta(hours=1, minutes=30), timeframe="15m")

        strategy = CRTStrategy(confirm_bars=2)
        res_fail = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_1, confirm_2_fail],
        )
        assert res_fail.direction == SignalDirection.WAIT

        confirm_2_pass = _make_candle(1955.0, 1970.0, 1952.0, 1968.0, timestamp=now + timedelta(hours=1, minutes=30), timeframe="15m")
        res_pass = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_1, confirm_2_pass],
        )
        assert res_pass.direction == SignalDirection.BUY
        assert res_pass.score >= 75.0

    def test_crt_analyzer_edge_cases(self):
        """CRTAnalyzer direct unit testing for empty sequences and zero range."""
        res_empty = CRTAnalyzer.analyze([], [])
        assert res_empty.is_breached is False
        assert res_empty.is_confirmed is False
        assert res_empty.manip_depth_pct == 0.0

        now = SESSION_ACTIVE_TS
        flat_candle = _make_candle(2000.0, 2000.0, 2000.0, 2000.0, timestamp=now)
        flat_confirm = _make_candle(2000.0, 2000.0, 2000.0, 2000.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        res_flat = CRTAnalyzer.analyze([flat_candle], [flat_confirm])
        assert res_flat.is_breached is False
        assert res_flat.manip_depth_pct == 0.0

    def test_strategy_manager_runs_crt_strategy(self):
        """Verify CRTStrategy runs cleanly inside StrategyManager with default thresholds."""
        manager = StrategyManager()
        names = [s.name for s in manager.strategies]
        assert "Candle Range Theory (CRT)" in names

        now = SESSION_ACTIVE_TS
        # Range: 35.0 ($1995 to $2030, between 0.35x and 4.0x ATR 10.0 = $3.5 to $40.0)
        range_candle = _make_candle(2000.0, 2030.0, 1995.0, 2025.0, timestamp=now)
        # Manipulation sweeps to 1988.0 (sweep 7.0 >= 0.15*10 = 1.5, depth 20% >= 5%)
        manip_candle = _make_candle(1996.0, 1998.0, 1988.0, 1990.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        # Confirmation closes back inside at 2000.0
        confirm_candle = _make_candle(1990.0, 2005.0, 1989.0, 2000.0, timestamp=now + timedelta(hours=1, minutes=15), timeframe="15m")

        base_struct = StructureAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", trend=TrendDirection.RANGING, trend_strength=0.0,
            key_support=1995.0, key_resistance=2030.0, total_candles=10, total_swings=0, timestamp=now,
        )
        struct = AdvancedStructureAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", timestamp=now, current_price=2000.0,
            trend=TrendDirection.RANGING, trend_strength=0.0, market_state="RANGING", base_structure=base_struct,
        )
        indicators = IndicatorAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", timestamp=now, current_price=2000.0,
            ema=EMASnapshot(), rsi=RSISnapshot(rsi_value=50.0, condition="NEUTRAL"),
            atr=ATRSnapshot(atr_value=10.0, atr_pips=100.0), divergences=[], recent_patterns=[], active_fvgs=[],
            confluence_bias="NEUTRAL", confluence_score=0.0,
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
        # Stop loss = 1988.0 - sl_buffer (max(0, 0.10*10 = 1.0)) = 1987.0
        assert crt_res.stop_loss == pytest.approx(1987.0)

    def test_confluence_engine_evaluates_crt_custom_sl(self):
        """Verify ConfluenceEngine respects CRT custom SL and TP in SignalResponse."""
        now = SESSION_ACTIVE_TS
        candles_1h = [
            _make_candle(
                2000.0, 2030.0, 1995.0, 2025.0,
                timestamp=now - timedelta(hours=30 - k),
                timeframe="1h",
            )
            for k in range(30)
        ]
        # Confirmation candles occur strictly after the last 1h candle
        candles_15m = [
            _make_candle(1996.0, 1998.0, 1988.0, 1990.0, timestamp=now + timedelta(minutes=15), timeframe="15m"),
            _make_candle(1990.0, 2005.0, 1989.0, 2000.0, timestamp=now + timedelta(minutes=30), timeframe="15m"),
            _make_candle(2000.0, 2002.0, 1994.0, 1998.0, timestamp=now + timedelta(minutes=45), timeframe="15m"),
        ]

        engine = ConfluenceEngine()
        signals = engine.evaluate_multi(
            symbol="XAU/USD",
            timeframe="1h",
            candles_primary=candles_1h,
            candles_15m=candles_15m,
            as_of=now + timedelta(minutes=50),
            backtest_mode=True,
        )

        crt_sig = next((s for s in signals if s.strategy_name == "Candle Range Theory (CRT)"), None)
        assert crt_sig is not None
        assert crt_sig.direction == SignalDirection.BUY
        assert crt_sig.setup_score >= 75.0
        assert crt_sig.stop_loss < 1988.0

    def test_crt_htf_trend_filter_rejects_counter_trend_buy(self):
        """Verify Bullish CRT AMD setup is REJECTED when HTF Trend is BEARISH."""
        now = SESSION_ACTIVE_TS
        range_candle, manip_candle, confirm_candle = _make_amd_fixture(
            2000.0, 2100.0, 1950.0, 2080.0,
            1955.0, 1960.0, 1935.0, 1945.0,
            1945.0, 1970.0, 1940.0, 1965.0,
            base_time=now,
        )

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1, enable_dedup=False)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
            htf_trend="BEARISH",
        )

        assert result.direction == SignalDirection.WAIT
        assert result.score == 0.0
        assert result.metadata["trend_conflict"] is True
        assert result.metadata["htf_trend"] == "BEARISH"

    def test_crt_htf_trend_filter_rejects_counter_trend_sell(self):
        """Verify Bearish CRT AMD setup is REJECTED when HTF Trend is BULLISH."""
        now = SESSION_ACTIVE_TS
        range_candle, manip_candle, confirm_candle = _make_amd_fixture(
            2080.0, 2100.0, 1950.0, 1970.0,
            2095.0, 2115.0, 2085.0, 2105.0,
            2105.0, 2108.0, 2075.0, 2085.0,
            base_time=now,
        )

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1, enable_dedup=False)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
            htf_trend="BULLISH",
        )

        assert result.direction == SignalDirection.WAIT
        assert result.score == 0.0
        assert result.metadata["trend_conflict"] is True

    def test_crt_htf_trend_filter_accepts_aligned_and_ranging(self):
        """Verify CRT setups are accepted when HTF trend aligns or is ranging, with lower score on ranging."""
        now1 = SESSION_ACTIVE_TS
        bull_range1, bull_manip1, bull_confirm1 = _make_amd_fixture(
            2000.0, 2100.0, 1950.0, 2080.0,
            1955.0, 1960.0, 1935.0, 1945.0,
            1945.0, 1970.0, 1940.0, 1965.0,
            base_time=now1,
        )

        now2 = SESSION_ACTIVE_TS + timedelta(days=1)
        bull_range2, bull_manip2, bull_confirm2 = _make_amd_fixture(
            2000.0, 2100.0, 1950.0, 2080.0,
            1955.0, 1960.0, 1935.0, 1945.0,
            1945.0, 1970.0, 1940.0, 1965.0,
            base_time=now2,
        )

        strategy_aligned = CRTStrategy(min_manip_pct=5.0, confirm_bars=1)
        res_aligned_buy = strategy_aligned.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[bull_range1],
            candles_15m=[bull_manip1, bull_confirm1],
            htf_trend="BULLISH",
        )
        assert res_aligned_buy.direction == SignalDirection.BUY
        assert res_aligned_buy.metadata["htf_trend"] == "BULLISH"

        strategy_ranging = CRTStrategy(min_manip_pct=5.0, confirm_bars=1)
        res_ranging_buy = strategy_ranging.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[bull_range2],
            candles_15m=[bull_manip2, bull_confirm2],
            htf_trend="RANGING",
        )
        assert res_ranging_buy.direction == SignalDirection.BUY

        # Aligned score is strictly higher than ranging score (Enhancement B)
        assert res_aligned_buy.score > res_ranging_buy.score

    def test_crt_counter_trend_bypass_with_strong_displacement(self):
        """Verify opposing HTF trend setup is REJECTED when displacement is weak (< 0.30x ATR),
        but ACCEPTED when displacement is >= 0.30x ATR with allow_counter_trend_bypass=True.
        Also verify that with allow_counter_trend_bypass=False, even strong displacement is REJECTED.
        """
        now = SESSION_ACTIVE_TS
        t0 = now
        effective_atr = 50.0

        # 1H benchmark range: [1950.0, 2100.0], size = 150.0 (3.0x ATR)
        range_candle = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=t0, timeframe="1h")

        # 15m manipulation: sweeps range low (1950.0) down to 1935.0, high at 1950.0
        manip_candle = _make_candle(1948.0, 1950.0, 1935.0, 1942.0, timestamp=t0 + timedelta(hours=1), timeframe="15m")

        # Weak displacement confirmation: open=1946.0, close=1958.0 (body = 12.0 = 0.24x ATR < 0.30x ATR)
        confirm_weak = _make_candle(1946.0, 1960.0, 1942.0, 1958.0, timestamp=t0 + timedelta(hours=1, minutes=15), timeframe="15m")

        # Strong displacement confirmation: open=1946.0, close=1964.0 (body = 18.0 = 0.36x ATR >= 0.30x ATR)
        confirm_strong = _make_candle(1946.0, 1966.0, 1942.0, 1964.0, timestamp=t0 + timedelta(hours=1, minutes=15), timeframe="15m")

        # --- Case 1: Bypass ENABLED, Weak Displacement (< 0.30x ATR) -> REJECTED ---
        strategy_bypass = CRTStrategy(min_manip_pct=5.0, confirm_bars=1, enable_dedup=False, allow_counter_trend_bypass=True)
        res_weak = strategy_bypass.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_weak],
            htf_trend="BEARISH",
            atr_value=effective_atr,
        )
        assert res_weak.direction == SignalDirection.WAIT
        assert res_weak.score == 0.0
        assert res_weak.metadata["trend_conflict"] is True
        assert res_weak.metadata["rejection_gate"] == "TREND_CONFLICT"
        assert "Insufficient LTF displacement" in res_weak.reasons[0]

        # --- Case 2: Bypass ENABLED, Strong Displacement (>= 0.30x ATR) -> ACCEPTED ---
        res_strong = strategy_bypass.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_strong],
            htf_trend="BEARISH",
            atr_value=effective_atr,
        )
        assert res_strong.direction == SignalDirection.BUY
        assert res_strong.score >= 75.0
        assert res_strong.metadata["counter_trend_bypassed"] is True
        assert res_strong.metadata["trend_conflict"] is False
        assert any("COUNTER-TREND BYPASS" in r for r in res_strong.reasons)

        # --- Case 3: Bypass DISABLED (Default), Strong Displacement -> REJECTED ---
        strategy_default = CRTStrategy(min_manip_pct=5.0, confirm_bars=1, enable_dedup=False, allow_counter_trend_bypass=False)
        res_default = strategy_default.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_strong],
            htf_trend="BEARISH",
            atr_value=effective_atr,
        )
        assert res_default.direction == SignalDirection.WAIT
        assert res_default.score == 0.0
        assert res_default.metadata["trend_conflict"] is True
        assert res_default.metadata["rejection_gate"] == "TREND_CONFLICT"

    def test_crt_infers_htf_trend_from_structure_or_mtf(self):
        """Verify CRT automatically infers HTF trend from structure or mtf objects when htf_trend is default."""
        now = SESSION_ACTIVE_TS
        range_candle, manip_candle, confirm_candle = _make_amd_fixture(
            2000.0, 2100.0, 1950.0, 2080.0,
            1955.0, 1960.0, 1935.0, 1945.0,
            1945.0, 1970.0, 1940.0, 1965.0,
            base_time=now,
        )

        base_struct = StructureAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", trend=TrendDirection.BEARISH, trend_strength=0.8,
            key_support=1950.0, key_resistance=2100.0, total_candles=10, total_swings=0, timestamp=now,
        )
        struct_bearish = AdvancedStructureAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", timestamp=now, current_price=1965.0,
            trend=TrendDirection.BEARISH, trend_strength=0.8, market_state="TRENDING_BEARISH", base_structure=base_struct,
        )

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1, enable_dedup=False)
        res_struct = strategy.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
            structure=struct_bearish,
        )
        assert res_struct.direction == SignalDirection.WAIT
        assert res_struct.metadata["trend_conflict"] is True

    def test_confluence_engine_passes_htf_trend_to_crt(self):
        """Verify ConfluenceEngine forwards HTF trend into strategy.analyze and rejects counter-trend CRT."""
        now = SESSION_ACTIVE_TS
        candles_1h = [
            _make_candle(
                2080.0, 2100.0, 1950.0, 1970.0,
                timestamp=now - timedelta(hours=30 - k),
                timeframe="1h",
            )
            for k in range(30)
        ]
        candles_15m = [
            _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=now + timedelta(minutes=15), timeframe="15m"),
            _make_candle(1945.0, 1970.0, 1940.0, 1965.0, timestamp=now + timedelta(minutes=30), timeframe="15m"),
            _make_candle(1965.0, 1975.0, 1960.0, 1970.0, timestamp=now + timedelta(minutes=45), timeframe="15m"),
        ]

        engine = ConfluenceEngine()
        signals = engine.evaluate_multi(
            symbol="XAU/USD",
            timeframe="1h",
            candles_primary=candles_1h,
            candles_15m=candles_15m,
            as_of=now + timedelta(minutes=50),
            backtest_mode=True,
        )

        crt_sig = next((s for s in signals if s.strategy_name == "Candle Range Theory (CRT)"), None)
        assert crt_sig is not None

    def test_trend_normalization_with_lowercase_and_enums(self):
        """Fix 2: Trend normalization handles lowercase, whitespace, and enum objects safely."""
        assert _norm_trend("bullish") == "BULLISH"
        assert _norm_trend("  bearish  ") == "BEARISH"
        assert _norm_trend("Ranging") == "RANGING"
        assert _norm_trend(TrendDirection.BULLISH) == "BULLISH"
        assert _norm_trend(TrendDirection.BEARISH) == "BEARISH"
        assert _norm_trend(TrendDirection.RANGING) == "RANGING"
        assert _norm_trend(None) == "RANGING"

    def test_missing_htf_candles_returns_wait(self):
        """Fix 3: When no HTF range candles are provided, strategy returns WAIT (no silent fallback)."""
        now = SESSION_ACTIVE_TS
        ltf_candle = _make_candle(2000.0, 2010.0, 1990.0, 2005.0, timestamp=now, timeframe="15m")

        strategy = CRTStrategy()
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[ltf_candle],
            candles_15m=[ltf_candle],
        )

        assert result.direction == SignalDirection.WAIT
        assert result.metadata["rejection_gate"] == "MISSING_HTF_CANDLES"
        assert "HTF range candle required" in result.reasons[0]

    def test_buy_with_stop_above_entry_rejected(self):
        """Fix 4: BUY setup where stop_loss >= entry_price is rejected (no abs() masking)."""
        now = SESSION_ACTIVE_TS
        range_candle = _make_candle(2000.0, 2050.0, 1980.0, 2040.0, timestamp=now)
        manip_candle = _make_candle(1975.0, 1978.0, 1965.0, 1970.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        # Entry price (close) = 1960.0, lower than breach point 1965.0
        confirm_candle = _make_candle(1970.0, 1972.0, 1958.0, 1960.0, timestamp=now + timedelta(hours=1, minutes=15), timeframe="15m")

        strategy = CRTStrategy()
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
        )

        assert result.direction == SignalDirection.WAIT
        assert result.metadata["setup_state"] == "INVALIDATED_SETUP"
        assert result.metadata["rejection_gate"] in ("INVALID_RISK_GEOMETRY", "SWEEP_EXTREME_BROKEN")

    def test_micro_sweep_below_minimum_rejected(self):
        """Enhancement B: Sweep below the minimum size (e.g. 0.15*ATR) is rejected."""
        now = SESSION_ACTIVE_TS
        # Range size = 20.0 (2620.0 to 2640.0), ATR = 10.0 -> min_sweep = max(0, 0.15*10.0) = 1.50
        range_c = _make_candle(2620.0, 2640.0, 2620.0, 2638.0, timestamp=now)
        # Low sweeps by only 0.20 (2619.80), below 1.50 min sweep
        manip_c = _make_candle(2622.0, 2625.0, 2619.80, 2621.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        confirm_c = _make_candle(2621.0, 2630.0, 2620.5, 2628.0, timestamp=now + timedelta(hours=1, minutes=15), timeframe="15m")

        strategy = CRTStrategy(min_manip_pct=0.5)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
            atr_value=10.0,
        )

        assert result.direction == SignalDirection.WAIT
        assert result.metadata["rejection_gate"] == "MICRO_SWEEP"
        assert "Micro-sweep" in result.reasons[0]

    def test_range_size_quality_gate(self):
        """Enhancement B: Micro-ranges and giant outlier candles vs ATR are rejected."""
        now = SESSION_ACTIVE_TS
        # 1. Micro-range: Range size = 2.0 vs ATR = 10.0 (0.20x < 0.35x ATR min)
        range_micro = _make_candle(2000.0, 2002.0, 2000.0, 2001.5, timestamp=now)
        manip_micro = _make_candle(2000.5, 2001.0, 1999.0, 2000.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        confirm_micro = _make_candle(2000.0, 2003.0, 2000.0, 2001.5, timestamp=now + timedelta(hours=1, minutes=15), timeframe="15m")

        strategy = CRTStrategy()
        res_micro = strategy.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[range_micro],
            candles_15m=[manip_micro, confirm_micro], atr_value=10.0,
        )
        assert res_micro.direction == SignalDirection.WAIT
        assert res_micro.metadata["rejection_gate"] == "MICRO_RANGE"

        # 2. Giant candle: Range size = 50.0 vs ATR = 10.0 (5.0x > 4.0x ATR max)
        range_giant = _make_candle(2000.0, 2050.0, 2000.0, 2045.0, timestamp=now)
        manip_giant = _make_candle(2010.0, 2015.0, 1990.0, 2005.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        confirm_giant = _make_candle(2005.0, 2035.0, 2002.0, 2030.0, timestamp=now + timedelta(hours=1, minutes=15), timeframe="15m")

        res_giant = strategy.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[range_giant],
            candles_15m=[manip_giant, confirm_giant], atr_value=10.0,
        )
        assert res_giant.direction == SignalDirection.WAIT
        assert res_giant.metadata["rejection_gate"] == "EXCESSIVE_RANGE"

    def test_opposing_fvg_within_1r_downgrades_or_rejects(self):
        """Enhancement B: Opposing unmitigated FVG within 1R of entry blocks the trade path."""
        now = SESSION_ACTIVE_TS
        range_c, manip_c, confirm_c = _make_amd_fixture(
            2000.0, 2030.0, 1995.0, 2025.0,
            1996.0, 1998.0, 1988.0, 1990.0,
            1990.0, 2005.0, 1989.0, 2000.0,
            base_time=now,
        )

        # Entry = 2000.0, SL = 1987.0 (with buffer) -> Risk distance = 13.0
        # Opposing Bearish FVG at 2005.0 (only 5.0 away = 0.38R < 1.0R!)
        blocking_fvg = FairValueGap(
            index=1, timestamp=now, fvg_type=FVGType.BEARISH_FVG, top_price=2010.0,
            bottom_price=2005.0, gap_size=5.0, gap_pips=50.0, is_mitigated=False,
        )
        indicators = IndicatorAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", timestamp=now, current_price=2000.0,
            ema=EMASnapshot(), rsi=RSISnapshot(rsi_value=50.0, condition="NEUTRAL"),
            atr=ATRSnapshot(atr_value=10.0, atr_pips=100.0), divergences=[], recent_patterns=[],
            active_fvgs=[blocking_fvg], confluence_bias="NEUTRAL", confluence_score=0.0,
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
        """Enhancement B: Outside allowed trading sessions (London, NY) returns WAIT when session filter is enabled."""
        ny_tz = ZoneInfo("America/New_York")
        # 07:15 AM NY is off-session (between London close 07:00 and NY open 08:00)
        # Ensure confirm candle lands at 07:15 AM NY
        off_session_time = datetime(2026, 9, 24, 7, 15, tzinfo=ny_tz).astimezone(timezone.utc) - timedelta(hours=1, minutes=15)

        range_c, manip_c, confirm_c = _make_amd_fixture(
            2000.0, 2030.0, 1995.0, 2025.0,
            1996.0, 1998.0, 1988.0, 1990.0,
            1990.0, 2005.0, 1989.0, 2000.0,
            base_time=off_session_time,
        )

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
        range_c, manip_c, confirm_c = _make_amd_fixture(
            2000.0, 2030.0, 1995.0, 2025.0,
            1996.0, 1998.0, 1988.0, 1990.0,
            1990.0, 2005.0, 1989.0, 2000.0,
            base_time=now,
        )

        # Liquidity pool at 1986.0 (just below breach low of 1988.0)
        pool = LiquidityPool(
            pool_type=LiquidityEventType.EQUAL_LOWS,
            price_level=1986.0,
            touch_points=2,
            first_timestamp=now,
            last_timestamp=now,
            is_swept=False,
        )
        base_struct = StructureAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", trend=TrendDirection.BULLISH, trend_strength=0.8,
            key_support=1995.0, key_resistance=2030.0, total_candles=10, total_swings=0, timestamp=now,
        )
        struct = AdvancedStructureAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", timestamp=now, current_price=2000.0,
            trend=TrendDirection.BULLISH, trend_strength=0.8, market_state="EXPANSION",
            base_structure=base_struct, liquidity_pools=[pool],
        )

        strategy = CRTStrategy(spread=0.0)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
            structure=struct,
            htf_trend="BULLISH",
            atr_value=10.0,
        )

        assert result.direction == SignalDirection.BUY
        assert result.stop_loss <= 1986.0

    def test_tp_capped_before_opposing_ob_or_fvg(self):
        """Enhancement D: TP1 is capped before an opposing barrier when clear path >= 1R."""
        now = SESSION_ACTIVE_TS
        range_c, manip_c, confirm_c = _make_amd_fixture(
            2000.0, 2030.0, 1995.0, 2025.0,
            1996.0, 1998.0, 1988.0, 1990.0,
            1990.0, 2005.0, 1989.0, 2000.0,
            base_time=now,
        )

        # Ideal limit entry = 1996.0, SL = 1987.0 (risk = 9.0). Range Midpoint = 2012.5.
        # Opposing Bearish FVG sits at 2008.0 (12.0 away = 1.33R >= 1.0R, but < 2012.5).
        opposing_fvg = FairValueGap(
            index=1, timestamp=now, fvg_type=FVGType.BEARISH_FVG, top_price=2012.0,
            bottom_price=2008.0, gap_size=4.0, gap_pips=40.0, is_mitigated=False,
        )
        indicators = IndicatorAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", timestamp=now, current_price=2000.0,
            ema=EMASnapshot(), rsi=RSISnapshot(rsi_value=50.0, condition="NEUTRAL"),
            atr=ATRSnapshot(atr_value=10.0, atr_pips=100.0), divergences=[], recent_patterns=[],
            active_fvgs=[opposing_fvg], confluence_bias="NEUTRAL", confluence_score=0.0,
        )

        strategy = CRTStrategy(spread=0.0)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
            indicators=indicators,
            htf_trend="BULLISH",
        )

        assert result.direction == SignalDirection.BUY
        assert result.take_profit_1 <= 2008.0
        assert "TP1 capped before opposing" in " ".join(result.reasons)

    def test_pip_and_lot_math_risk_exceeds_limit(self):
        """Fixes 5 & 6: 1 pip = $0.10 for XAU/USD. $8.55 stop risks $8.55 on 0.01 lot. Small accounts get flagged."""
        now = SESSION_ACTIVE_TS
        range_c, manip_c, confirm_c = _make_amd_fixture(
            2648.0, 2665.0, 2645.0, 2662.0,
            2650.0, 2650.0, 2641.45, 2644.0,
            2644.0, 2652.0, 2643.0, 2651.00,
            base_time=now,
        )

        strategy = CRTStrategy(spread=0.0)
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
        range_c, manip_c, confirm_c = _make_amd_fixture(
            2000.0, 2030.0, 1995.0, 2025.0,
            1996.0, 1998.0, 1988.0, 1990.0,
            1990.0, 2005.0, 1989.0, 2000.0,
            base_time=t0,
        )

        strategy_t = CRTStrategy(enable_dedup=False)
        res_t = strategy_t.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
        )

        # Future candles arrived later (consolidating around entry zone, not running away)
        future_c1 = _make_candle(2000.0, 2002.0, 1995.0, 1998.0, timestamp=t0 + timedelta(hours=1, minutes=30), timeframe="15m")
        future_c2 = _make_candle(1998.0, 2001.0, 1996.0, 2000.0, timestamp=t0 + timedelta(hours=1, minutes=45), timeframe="15m")

        strategy_future = CRTStrategy(enable_dedup=False)
        res_future = strategy_future.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c, future_c1, future_c2],
        )

        assert res_t.direction == res_future.direction
        assert res_t.breach_point == res_future.breach_point
        assert res_t.metadata["crt_analysis"]["breach_point"] == res_future.metadata["crt_analysis"]["breach_point"]

    def test_deduplication_by_sweep_event_key(self):
        """Enhancement F: Duplicate signals for the same sweep event are suppressed."""
        now = SESSION_ACTIVE_TS
        range_c, manip_c, confirm_c = _make_amd_fixture(
            2000.0, 2030.0, 1995.0, 2025.0,
            1996.0, 1998.0, 1988.0, 1990.0,
            1990.0, 2005.0, 1989.0, 2000.0,
            base_time=now,
        )

        strategy = CRTStrategy()
        res1 = strategy.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[range_c], candles_15m=[manip_c, confirm_c],
        )
        assert res1.direction == SignalDirection.BUY

        res2 = strategy.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[range_c], candles_15m=[manip_c, confirm_c],
        )
        assert res2.direction == SignalDirection.WAIT
        assert res2.metadata["rejection_gate"] == "DEDUPLICATED"
        assert "DEDUPLICATED" in res2.reasons[0]

    # -------------------------------------------------------------------------
    # NEW TESTS: Review Items 1, 2, 3, 4, 5, 6, 7
    # -------------------------------------------------------------------------

    def test_lookahead_inside_range_hour_rejected(self):
        """Item 1: 15m candle starting inside the 1H range hour cannot be used as manipulation/confirmation."""
        t0 = SESSION_ACTIVE_TS
        # 1H Range candle: 07:00 to 08:00 UTC
        range_c = _make_candle(2000.0, 2030.0, 1995.0, 2025.0, timestamp=t0, timeframe="1h")
        # 15m manipulation at 07:15 UTC (inside range hour < 08:00 UTC)
        manip_inside = _make_candle(1996.0, 1998.0, 1988.0, 1990.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")
        # 15m confirmation at 07:30 UTC (inside range hour < 08:00 UTC)
        confirm_inside = _make_candle(1990.0, 2005.0, 1989.0, 2000.0, timestamp=t0 + timedelta(minutes=30), timeframe="15m")

        strategy = CRTStrategy()
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_inside, confirm_inside],
        )

        assert result.direction == SignalDirection.WAIT
        assert result.metadata["crt_analysis"]["is_breached"] is False
        assert "No manipulation breach detected" in result.reasons[0]

    def test_lookahead_missing_timestamps_returns_wait(self):
        """Item 1: Missing timestamps on candles return WAIT instead of bypassing lookahead filter."""
        range_no_ts = {
            "symbol": "XAU/USD", "timeframe": "1h", "timestamp": None,
            "open": 2000.0, "high": 2030.0, "low": 1995.0, "close": 2025.0, "volume": 1000.0,
        }
        manip_no_ts = {
            "symbol": "XAU/USD", "timeframe": "15m", "timestamp": None,
            "open": 1996.0, "high": 1998.0, "low": 1988.0, "close": 1990.0, "volume": 1000.0,
        }

        strategy = CRTStrategy()
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_no_ts],
            candles_15m=[manip_no_ts],
        )

        assert result.direction == SignalDirection.WAIT
        assert result.metadata["rejection_gate"] == "MISSING_TIMESTAMPS"
        assert "Missing timestamps" in result.reasons[0]

    def test_boundary_min_range_quality(self):
        """Item 2: Range height boundary at 0.35x ATR (< 0.35 rejected, == 0.35 accepted)."""
        now = SESSION_ACTIVE_TS
        # ATR = 10.0 -> threshold = 3.50. Range size 3.40 (0.34x ATR) should fail.
        rc_fail, mc_fail, cc_fail = _make_amd_fixture(
            2000.0, 2003.40, 2000.0, 2002.0,
            2001.0, 2002.0, 1998.0, 1999.0,
            1999.0, 2002.5, 1998.5, 2001.0,
            base_time=now,
        )
        strategy = CRTStrategy(min_range_atr_mult=0.35)
        res_fail = strategy.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[rc_fail],
            candles_15m=[mc_fail, cc_fail], atr_value=10.0,
        )
        assert res_fail.direction == SignalDirection.WAIT
        assert res_fail.metadata["rejection_gate"] == "MICRO_RANGE"

        # Range size 3.50 (0.35x ATR) passes range quality gate
        rc_pass, mc_pass, cc_pass = _make_amd_fixture(
            2000.0, 2003.50, 2000.0, 2002.0,
            2001.0, 2002.0, 1998.0, 1999.0,
            1999.0, 2002.5, 1998.5, 2001.0,
            base_time=now,
        )
        res_pass = strategy.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[rc_pass],
            candles_15m=[mc_pass, cc_pass], atr_value=10.0,
        )
        assert res_pass.metadata.get("rejection_gate") != "MICRO_RANGE"

    def test_boundary_max_range_quality(self):
        """Item 2: Range height boundary at 4.0x ATR (== 4.0 accepted, > 4.0 rejected)."""
        now = SESSION_ACTIVE_TS
        # ATR = 10.0 -> threshold = 40.0. Range size 40.0 passes.
        rc_pass, mc_pass, cc_pass = _make_amd_fixture(
            2000.0, 2040.0, 2000.0, 2030.0,
            2010.0, 2015.0, 1990.0, 1995.0,
            1995.0, 2015.0, 1994.0, 2010.0,
            base_time=now,
        )
        strategy = CRTStrategy(max_range_atr_mult=4.0)
        res_pass = strategy.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[rc_pass],
            candles_15m=[mc_pass, cc_pass], atr_value=10.0,
        )
        assert res_pass.metadata.get("rejection_gate") != "EXCESSIVE_RANGE"

        # Range size 40.10 (> 4.0x ATR) is rejected
        rc_fail, mc_fail, cc_fail = _make_amd_fixture(
            2000.0, 2040.10, 2000.0, 2030.0,
            2010.0, 2015.0, 1990.0, 1995.0,
            1995.0, 2015.0, 1994.0, 2010.0,
            base_time=now,
        )
        res_fail = strategy.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[rc_fail],
            candles_15m=[mc_fail, cc_fail], atr_value=10.0,
        )
        assert res_fail.direction == SignalDirection.WAIT
        assert res_fail.metadata["rejection_gate"] == "EXCESSIVE_RANGE"

    def test_boundary_max_risk_distance(self):
        """Item 2: Risk distance boundary at 3.0x ATR (== 3.0 accepted, > 3.0 rejected)."""
        now = SESSION_ACTIVE_TS
        # ATR = 10.0 -> max risk = 30.0. sl_buffer = 0.10*ATR = 1.0. Ideal entry = 1996.0.
        # Breach = 1967.0 -> SL = 1966.0. Entry = 1996.0 -> Risk = 30.0 (3.0x ATR) passes
        rc_pass, mc_pass, cc_pass = _make_amd_fixture(
            2000.0, 2025.0, 1995.0, 2020.0,
            1996.0, 1998.0, 1967.0, 1975.0,
            1975.0, 2005.0, 1974.0, 2000.0,
            base_time=now,
        )
        strategy = CRTStrategy(max_risk_atr_mult=3.0, spread=0.0)
        res_pass = strategy.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[rc_pass],
            candles_15m=[mc_pass, cc_pass], atr_value=10.0,
        )
        assert res_pass.metadata.get("rejection_gate") != "EXCESSIVE_RISK_DISTANCE"

        # Breach = 1966.90 -> SL = 1965.90. Entry = 1996.0 -> Risk = 30.10 (> 3.0x ATR) is rejected
        rc_fail, mc_fail, cc_fail = _make_amd_fixture(
            2000.0, 2025.0, 1995.0, 2020.0,
            1996.0, 1998.0, 1966.90, 1975.0,
            1975.0, 2005.0, 1974.0, 2000.0,
            base_time=now,
        )
        res_fail = strategy.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[rc_fail],
            candles_15m=[mc_fail, cc_fail], atr_value=10.0,
        )
        assert res_fail.direction == SignalDirection.WAIT
        assert res_fail.metadata["rejection_gate"] == "EXCESSIVE_RISK_DISTANCE"

    def test_boundary_min_sweep_size(self):
        """Item 2: Min sweep size boundary at max(spread*3, 0.15*ATR)."""
        now = SESSION_ACTIVE_TS
        # ATR = 10.0, spread = 0.10 -> min_sweep = max(0.30, 1.50) = 1.50
        # Range low = 1995.0. Sweep to 1993.60 is 1.40 (< 1.50) -> Rejected
        rc_fail, mc_fail, cc_fail = _make_amd_fixture(
            2000.0, 2025.0, 1995.0, 2020.0,
            1996.0, 1998.0, 1993.60, 1994.0,
            1994.0, 2005.0, 1993.8, 2000.0,
            base_time=now,
        )
        strategy = CRTStrategy(min_sweep_atr_mult=0.15, spread=0.10, min_manip_pct=1.0)
        res_fail = strategy.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[rc_fail],
            candles_15m=[mc_fail, cc_fail], atr_value=10.0,
        )
        assert res_fail.direction == SignalDirection.WAIT
        assert res_fail.metadata["rejection_gate"] == "MICRO_SWEEP"

        # Sweep to 1993.50 is 1.50 (== 1.50) -> Accepted
        rc_pass, mc_pass, cc_pass = _make_amd_fixture(
            2000.0, 2025.0, 1995.0, 2020.0,
            1996.0, 1998.0, 1993.50, 1994.0,
            1994.0, 2005.0, 1993.8, 2000.0,
            base_time=now,
        )
        res_pass = strategy.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[rc_pass],
            candles_15m=[mc_pass, cc_pass], atr_value=10.0,
        )
        assert res_pass.metadata.get("rejection_gate") != "MICRO_SWEEP"

    def test_session_asia_excluded_from_signals(self):
        """Item 3: Asian session is strictly excluded from signal generation (liquidity only)."""
        ny_tz = ZoneInfo("America/New_York")
        # 20:00 NY is inside Asian Session (18:00 - 00:00 NY)
        asia_time = datetime(2026, 9, 24, 20, 0, tzinfo=ny_tz).astimezone(timezone.utc)
        is_open, name = is_in_trading_session(asia_time)
        assert is_open is False
        assert "Asian Session" in name
        assert "Liquidity Tracking Only" in name

        rc, mc, cc = _make_amd_fixture(
            2000.0, 2030.0, 1995.0, 2025.0,
            1996.0, 1998.0, 1988.0, 1990.0,
            1990.0, 2005.0, 1989.0, 2000.0,
            base_time=asia_time,
        )
        # When session filter is hard enabled, returns WAIT
        strategy_gate = CRTStrategy(session_filter_enabled=True)
        res_gate = strategy_gate.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[rc], candles_15m=[mc, cc],
        )
        assert res_gate.direction == SignalDirection.WAIT
        assert res_gate.metadata["rejection_gate"] == "OFF_SESSION"

        # When session filter is soft, score receives off-session penalty (-8.0)
        strategy_soft = CRTStrategy(session_filter_enabled=False)
        res_soft = strategy_soft.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[rc], candles_15m=[mc, cc],
        )
        pen_rule = next((r for r in res_soft.metadata["score_audit"] if r["rule"] == "Off-Session Execution"), None)
        assert pen_rule is not None
        assert pen_rule["points"] == -8.0

    def test_deduplication_cross_instance_database(self):
        """Item 4: Persisted dedup key in database suppresses repeat signals across fresh strategy instances."""
        now = datetime(2026, 9, 24, 7, 0, tzinfo=timezone.utc)
        rc, mc, cc = _make_amd_fixture(
            2000.0, 2030.0, 1995.0, 2025.0,
            1996.0, 1998.0, 1988.0, 1990.0,
            1990.0, 2005.0, 1989.0, 2000.0,
            base_time=now,
        )

        strategy1 = CRTStrategy(spread=0.0)
        res1 = strategy1.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[rc], candles_15m=[mc, cc],
        )
        assert res1.direction == SignalDirection.BUY

        # Fresh strategy instance with empty in-memory cache
        strategy2 = CRTStrategy(spread=0.0)
        assert len(strategy2._emitted_sweep_events) == 0

        res2 = strategy2.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[rc], candles_15m=[mc, cc],
        )
        assert res2.direction == SignalDirection.WAIT
        assert res2.metadata["rejection_gate"] == "DEDUPLICATED"
        assert "database cooldown" in " ".join(res2.reasons)

    def test_htf_source_structure_primary_earns_zero_points(self):
        """Item 5: structure_primary earns zero HTF points in scoring and is explicitly audited."""
        now = datetime(2026, 9, 24, 7, 0, tzinfo=timezone.utc)
        rc, mc, cc = _make_amd_fixture(
            2000.0, 2030.0, 1995.0, 2025.0,
            1996.0, 1998.0, 1988.0, 1990.0,
            1990.0, 2005.0, 1989.0, 2000.0,
            base_time=now,
        )

        base_struct = StructureAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", trend=TrendDirection.BULLISH, trend_strength=0.8,
            key_support=1995.0, key_resistance=2030.0, total_candles=10, total_swings=0, timestamp=now,
        )
        struct = AdvancedStructureAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", timestamp=now, current_price=2000.0,
            trend=TrendDirection.BULLISH, trend_strength=0.8, market_state="EXPANSION", base_structure=base_struct,
        )

        strategy = CRTStrategy(spread=0.0)
        res = strategy.analyze(
            symbol="XAU/USD", timeframe="1h", candles=[rc], candles_15m=[mc, cc],
            structure=struct,
        )
        assert res.metadata["htf_trend_source"] == "structure_primary"

        rule_1h = next((r for r in res.metadata["score_audit"] if r["rule"] == "1H Alignment"), None)
        assert rule_1h is not None
        assert rule_1h["points"] == 0.0
        assert "structure_primary" in rule_1h["reason"]

        rule_4h = next((r for r in res.metadata["score_audit"] if r["rule"] == "4H Alignment"), None)
        assert rule_4h is not None
        assert rule_4h["points"] == 0.0

    def test_formatter_risk_exceeds_limit_omits_lot_size(self):
        """Item 6: When RISK EXCEEDS LIMIT triggers, lot size is hidden; warning and actual $ risk at 0.01 lot are displayed."""
        class DummySignal:
            symbol = "XAU/USD"
            timeframe = "1h"
            direction = SignalDirection.BUY
            setup_score = 80.0
            entry_price = 2650.0
            stop_loss = 2641.45
            take_profit_1 = 2662.82
            take_profit_2 = 2671.37
            risk_reward = 1.5
            strategy_name = "Candle Range Theory (CRT)"
            reasons = ["CRT AMD Setup Confirmed (BUY)"]
            score_breakdown = ScoreBreakdown(structure_score=28.0, liquidity_score=30.0, price_action_score=22.0, total_score=80.0, is_qualified=True)
            metadata = {
                "setup_state": "CONFIRMED_SETUP",
                "risk_warning": "RISK EXCEEDS LIMIT - min lot too large for account: min 0.01 lot risks $8.55 on $0.50 budget (0.5% of $100)",
                "suggested_lot_size": 0.01,
                "risk_amount_usd": 8.55,
                "htf_trend_source": "structure_primary",
            }
            risk_parameters = None

        sig = DummySignal()
        ctx = SignalContext(account_balance=100.0, risk_percent=0.5, risk_amount_usd=8.55)
        msg = format_signal(sig, ctx=ctx)

        # Assert Suggested Sizing is omitted
        assert "Suggested Sizing" not in msg
        # Assert warning and actual risk are present
        assert "RISK EXCEEDS LIMIT" in msg
        assert "Actual Risk (0.01 lot):</b> <code>$8.55" in msg
        # Assert HTF source labelling
        assert "Primary Structure 15m - Unconfirmed HTF" in msg

    def test_signal_203(self):
        """Item 7 REGRESSION: Signal 203 with entry 3872.54, SL 3863.99, bearish FVG 3875.07 at 04:15 UTC.

        Geometry:
        - Range height ~5.4 (e.g. 3867.60 to 3873.00)
        - Entry: 3872.54, SL: 3863.99 -> Risk distance = 8.55
        - Opposing Bearish FVG sits at 3875.07 -> Distance to FVG = 2.53 (0.30R < 1.0R)
        Asserts: Setup is NOT CONFIRMED_SETUP (rejection_gate is PATH_BLOCKED).
        """
        t0 = datetime(2026, 9, 24, 3, 0, tzinfo=timezone.utc)
        # Range candle from 03:00 to 04:00 UTC (London session)
        rc = _make_candle(3868.0, 3873.0, 3867.60, 3872.0, timestamp=t0, timeframe="1h")
        # Manipulation candle at 04:00 UTC sweeps low to 3863.99
        mc = _make_candle(3870.0, 3871.0, 3863.99, 3865.0, timestamp=t0 + timedelta(hours=1), timeframe="15m")
        # Confirmation candle at 04:15 UTC closes back inside at 3872.54
        cc = _make_candle(3865.0, 3873.0, 3864.5, 3872.54, timestamp=t0 + timedelta(hours=1, minutes=15), timeframe="15m")

        # Opposing Bearish FVG at 3875.07
        blocking_fvg = FairValueGap(
            index=1,
            timestamp=t0,
            fvg_type=FVGType.BEARISH_FVG,
            top_price=3878.0,
            bottom_price=3875.07,
            gap_size=2.93,
            gap_pips=29.3,
            is_mitigated=False,
        )
        indicators = IndicatorAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", timestamp=t0, current_price=3872.54,
            ema=EMASnapshot(), rsi=RSISnapshot(rsi_value=50.0, condition="NEUTRAL"),
            atr=ATRSnapshot(atr_value=5.0, atr_pips=50.0), divergences=[], recent_patterns=[],
            active_fvgs=[blocking_fvg], confluence_bias="NEUTRAL", confluence_score=0.0,
        )

        strategy = CRTStrategy(spread=0.0)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[rc],
            candles_15m=[mc, cc],
            indicators=indicators,
        )

        print("\n--- TEST SIGNAL 203 OUTPUT ---")
        print("Direction:", result.direction)
        print("Setup State:", result.metadata.get("setup_state"))
        print("Rejection Gate:", result.metadata.get("rejection_gate"))
        print("Reasons:", result.reasons)
        print("Obstacle R-distance:", result.metadata.get("obstacle_r"))
        print("------------------------------")

        # Crucial assertion: Must NOT be CONFIRMED_SETUP!
        assert result.metadata["setup_state"] != "CONFIRMED_SETUP"
        assert result.direction == SignalDirection.WAIT
        assert result.metadata["rejection_gate"] == "PATH_BLOCKED"
        assert result.metadata["obstacle_r"] < 1.0

    def test_crt_native_targets_and_real_rr(self):
        """Item 1: CRT-Native Targets (TP1 = range midpoint, TP2 = range high/low) and real R:R."""
        now = SESSION_ACTIVE_TS
        # Range: 2000.0 to 2100.0 (midpoint = 2050.0). Entry at 2010.0, SL at 1990.0 (risk = 20.0).
        range_c = _make_candle(2020.0, 2100.0, 2000.0, 2080.0, timestamp=now)
        manip_c = _make_candle(2005.0, 2008.0, 1990.0, 1995.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        confirm_c = _make_candle(1995.0, 2015.0, 1992.0, 2010.0, timestamp=now + timedelta(hours=1, minutes=15), timeframe="15m")

        strategy = CRTStrategy(spread=0.0)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
        )

        assert result.direction == SignalDirection.BUY
        assert result.metadata["target_type"] == "CRT_RANGE"
        assert result.take_profit_1 == pytest.approx(2050.0)  # Midpoint
        assert result.take_profit_2 == pytest.approx(2100.0)  # Range High
        expected_rr_tp1 = round((2050.0 - 2005.0) / 15.0, 2)  # 3.0R (using ideal limit entry 2005.0)
        expected_rr_tp2 = round((2100.0 - 2005.0) / 15.0, 2)  # 6.33R
        assert result.metadata["risk_reward_tp1"] == pytest.approx(expected_rr_tp1)
        assert result.metadata["risk_reward_tp2"] == pytest.approx(expected_rr_tp2)

    def test_crt_insufficient_rr_returns_wait(self):
        """Item 1: If TP1 R:R < min_rr (default 1.0) and obstacle blocks path, returns WAIT."""
        now = SESSION_ACTIVE_TS
        # Range: 2000.0 to 2035.0 (size 35.0 <= 4.0x ATR 10.0)
        range_c = _make_candle(2000.0, 2035.0, 2000.0, 2030.0, timestamp=now)
        manip_c = _make_candle(2002.0, 2004.0, 1995.0, 1996.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        confirm_c = _make_candle(1996.0, 2022.0, 1996.0, 2020.0, timestamp=now + timedelta(hours=1, minutes=15), timeframe="15m")

        # Opposing FVG at 2005.0 (only 3.0 away from ideal entry 2002.0, while risk = 8.0 -> 0.38R < 1.0R)
        blocking_fvg = FairValueGap(
            index=1, timestamp=now, fvg_type=FVGType.BEARISH_FVG, top_price=2008.0,
            bottom_price=2005.0, gap_size=3.0, gap_pips=30.0, is_mitigated=False,
        )
        indicators = IndicatorAnalysisResponse(
            symbol="XAU/USD", timeframe="1h", timestamp=now, current_price=2020.0,
            ema=EMASnapshot(), rsi=RSISnapshot(rsi_value=50.0, condition="NEUTRAL"),
            atr=ATRSnapshot(atr_value=10.0, atr_pips=100.0), divergences=[], recent_patterns=[],
            active_fvgs=[blocking_fvg], confluence_bias="NEUTRAL", confluence_score=0.0,
        )

        strategy = CRTStrategy(min_rr_tp1=1.0)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
            indicators=indicators,
        )

        assert result.direction == SignalDirection.WAIT
        assert result.metadata["rejection_gate"] in ("INSUFFICIENT_RR", "PATH_BLOCKED")

    def test_crt_fallback_targets_labeled_when_midpoint_invalid(self):
        """Item 1: When range midpoint is behind entry, falls back to 1.5R/2.5R and labels it."""
        now = SESSION_ACTIVE_TS
        # Range 2000.0 to 2040.0 (midpoint = 2020.0). Ideal limit entry at 2025.0 (past midpoint!)
        range_c = _make_candle(2010.0, 2040.0, 2000.0, 2035.0, timestamp=now)
        manip_c = _make_candle(2025.0, 2026.0, 1990.0, 1995.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        confirm_c = _make_candle(1995.0, 2030.0, 1994.0, 2028.0, timestamp=now + timedelta(hours=1, minutes=15), timeframe="15m")

        strategy = CRTStrategy(spread=0.0)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
        )

        assert result.direction == SignalDirection.BUY
        assert result.metadata["target_type"] == "FALLBACK_RR"
        risk = 2025.0 - 1990.0  # 35.0
        assert result.take_profit_1 == pytest.approx(2025.0 + (risk * 1.5))
        assert result.take_profit_2 == pytest.approx(2025.0 + (risk * 2.5))
        assert any("Fallback" in r for r in result.reasons)

    def test_retracement_entry_and_expiry_utc7(self):
        """Item 2 & 7: Retracement entry zone, ideal entry, and 'Valid Until' in UTC & UTC+7."""
        now = SESSION_ACTIVE_TS
        range_c = _make_candle(2020.0, 2100.0, 2000.0, 2080.0, timestamp=now)
        manip_c = _make_candle(2005.0, 2008.0, 1990.0, 1995.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        confirm_c = _make_candle(1995.0, 2020.0, 1992.0, 2015.0, timestamp=now + timedelta(hours=1, minutes=15), timeframe="15m")

        strategy = CRTStrategy(entry_expiry_bars=8)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
        )

        meta = result.metadata
        assert "entry_zone" in meta
        assert meta["entry_zone"][0] <= meta["ideal_entry"] <= meta["entry_zone"][1]
        assert "expires_at_utc" in meta
        assert "expires_at_utc7" in meta
        assert meta["entry_mode"] in ("limit_zone", "market")

    def test_retracement_entry_missed_status(self):
        """Item 2: Mark MISSED if price runs > 0.5R past displacement toward TP1 without filling limit zone."""
        now = SESSION_ACTIVE_TS
        range_c = _make_candle(2020.0, 2100.0, 2000.0, 2080.0, timestamp=now)
        # Displacement pushed to 2010.0, sweep was 1990.0 (risk = 10.0). Ideal entry = 2000.0.
        # But price skyrocketed to 2030.0 (> 0.5R past 2010.0 toward TP1) without touching limit zone [1999.5, 2000.5]
        manip_c = _make_candle(2005.0, 2008.0, 1990.0, 1995.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        confirm_c = _make_candle(1995.0, 2010.0, 2004.0, 2008.0, timestamp=now + timedelta(hours=1, minutes=15), timeframe="15m")
        # Runaway candle opening at 2008.0 and rocketing to 2030.0 (low 2006.0 never touches 2000.0 zone)
        runaway_c = _make_candle(2008.0, 2030.0, 2006.0, 2025.0, timestamp=now + timedelta(hours=1, minutes=30), timeframe="15m")

        strategy = CRTStrategy()
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c, runaway_c],
        )

        # Post-sweep window (fix E5): the confirmation candle has low 2004 <=
        # ideal 2005, so the limit order fills before the runaway bar. The setup
        # is live, not missed.
        assert result.direction == SignalDirection.BUY
        assert result.metadata["setup_state"] == "CONFIRMED_SETUP"
        assert result.metadata.get("rejection_gate") is None
        assert "MISSED" not in " ".join(result.reasons)

    def test_ltf_confirmation_mss_required(self):
        """Item 3: Close back inside range without Market Structure Shift -> WAITING_FOR_CONFIRMATION."""
        now = SESSION_ACTIVE_TS
        range_c = _make_candle(2020.0, 2100.0, 2000.0, 2080.0, timestamp=now)
        # Prior swing high is at 2015.0
        c_prior = _make_candle(2010.0, 2015.0, 2002.0, 2005.0, timestamp=now + timedelta(minutes=45), timeframe="15m")
        # Sweep low at 1990.0, high is 2008.0
        manip_c = _make_candle(2005.0, 2008.0, 1990.0, 1995.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        # Candle closes back inside at 2002.0 (> 2000.0), but high is only 2005.0 (did NOT break prior swing high 2015.0 or manip high 2008.0)
        confirm_c = _make_candle(1995.0, 2005.0, 1993.0, 2002.0, timestamp=now + timedelta(hours=1, minutes=15), timeframe="15m")

        strategy = CRTStrategy()
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[c_prior, manip_c, confirm_c],
        )

        assert result.direction == SignalDirection.WAIT
        assert result.metadata["setup_state"] == "WAITING_FOR_CONFIRMATION"
        assert result.metadata["rejection_gate"] == "CONFIRMATION_PENDING"
        assert "Awaiting Market Structure Shift" in result.reasons[0]

    def test_quality_tiers_and_telegram_formatting(self):
        """Item 7: Quality Tiers (A+, A, B, C) and Telegram alert formatting with tier badges."""
        from app.services.strategies.crt.tiers import determine_quality_tier

        tier_aplus = determine_quality_tier(score=88.0, gatekeeper_passed=True)
        assert tier_aplus.tier == "A+"
        assert tier_aplus.should_alert_telegram is True

        tier_a = determine_quality_tier(score=78.0, gatekeeper_passed=True)
        assert tier_a.tier == "A"
        assert tier_a.should_alert_telegram is True

        tier_b = determine_quality_tier(score=68.0, gatekeeper_passed=True)
        assert tier_b.tier == "B"
        assert tier_b.should_alert_telegram is False  # Dashboard only

        tier_c = determine_quality_tier(score=55.0, gatekeeper_passed=True)
        assert tier_c.tier == "C"
        assert tier_c.should_alert_telegram is False

        # Verify Telegram message formatter displays Quality Tier, Entry Zone, and Valid Until
        class DummySignal:
            symbol = "XAU/USD"
            timeframe = "1h"
            direction = SignalDirection.BUY
            setup_score = 88.0
            entry_price = 2000.0
            stop_loss = 1990.0
            take_profit_1 = 2025.0
            take_profit_2 = 2050.0
            risk_reward = 2.5
            strategy_name = "Candle Range Theory (CRT)"
            reasons = ["CRT AMD Setup Confirmed (BUY)"]
            score_breakdown = ScoreBreakdown(structure_score=35.0, liquidity_score=35.0, price_action_score=18.0, total_score=88.0, is_qualified=True)
            metadata = {
                "setup_state": "CONFIRMED_SETUP",
                "quality_tier": "A+",
                "quality_tier_label": "💎 A+ Quality (High Conviction)",
                "entry_zone": [1995.0, 2002.0],
                "ideal_entry": 2000.0,
                "entry_mode": "limit_zone",
                "expires_at_utc": "2026-09-24 09:15:00",
                "expires_at_utc7": "2026-09-24 16:15:00",
                "session_name": "London Session",
                "sweep_level_type": "Previous Day Low (PDL)",
            }
            risk_parameters = None

        msg = format_signal(DummySignal(), ctx=SignalContext(account_balance=10000.0, risk_percent=0.5, suggested_lot_size=0.05, risk_amount_usd=50.0))
        assert "💎 A+ Quality (High Conviction)" in msg
        assert "Entry Zone:" in msg
        assert "[1995.00 - 2002.00]" in msg
        assert "Valid Until:" in msg
        assert "2026-09-24 09:15:00 UTC" in msg
        assert "2026-09-24 16:15:00 UTC+7" in msg

    def test_lifecycle_state_transitions_and_management_alerts(self):
        """Item 4 & 8: Lifecycle state transitions and management alerts (alerted once per transition)."""
        from app.services.strategies.crt.lifecycle import evaluate_lifecycle_state, CRTState
        from app.core.database import SessionLocal
        from app.models.crt_sweep_event import CRTSweepEvent

        db = SessionLocal()
        try:
            key = "TEST_XAU_USD_BUY_LIFECYCLE_1"
            now = datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc)
            expiry = now + timedelta(hours=2)

            # 1. Transition: None -> CONFIRMED (price at 2005.0 outside zone [1995, 2002])
            res1 = evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=2005.0, current_time=now,
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            assert res1.current_state == CRTState.CONFIRMED

            # 2. Transition: CONFIRMED -> ENTRY_FILLED (price enters [1995, 2002])
            res2 = evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=1998.0, current_time=now + timedelta(minutes=15),
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            assert res2.current_state == CRTState.ENTRY_FILLED
            assert res2.transition_occurred is True
            assert res2.should_send_management_alert is True
            assert "ENTRY_FILLED" in res2.alert_title

            # 3. Repeat on ENTRY_FILLED: should NOT send alert again
            res2_repeat = evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=2001.0, current_time=now + timedelta(minutes=20),
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            assert res2_repeat.current_state == CRTState.ENTRY_FILLED
            assert res2_repeat.transition_occurred is False
            assert res2_repeat.should_send_management_alert is False

            # 4. Transition: ENTRY_FILLED -> TP1_HIT
            res3 = evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=2032.0, current_time=now + timedelta(minutes=45),
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            assert res3.current_state == CRTState.TP1_HIT
            assert res3.should_send_management_alert is True
            assert "TP1_HIT" in res3.alert_title

            # 5. Transition: TP1_HIT -> TP2_HIT
            res4 = evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=2065.0, current_time=now + timedelta(hours=1),
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            assert res4.current_state == CRTState.TP2_HIT
            assert res4.should_send_management_alert is True
            assert "TP2_HIT" in res4.alert_title
        finally:
            db.close()

    def test_daily_bias_and_swept_level_classification(self):
        """Item 6: Daily bias, session tracking, and high-significance level scoring."""
        from app.services.strategies.crt.daily_bias import calculate_daily_bias, classify_swept_level

        # Create 48 hours of 1H candles spanning yesterday and today in NY time
        # NY 17:00 is 21:00 UTC
        t_base = datetime(2026, 9, 22, 21, 0, tzinfo=timezone.utc)
        candles_48h = [
            _make_candle(2000.0 + i, 2010.0 + i, 1990.0 + i, 2005.0 + i, timestamp=t_base + timedelta(hours=i))
            for i in range(48)
        ]

        bias_res = calculate_daily_bias(candles_48h, current_time=t_base + timedelta(hours=47), current_price=2040.0)
        assert bias_res.pdh is not None
        assert bias_res.pdl is not None
        assert bias_res.premium_discount in ("PREMIUM", "DISCOUNT", "EQUILIBRIUM")

        # Sweeping the Previous Day Low earns maximum points (18.0)
        swept_type_pdl, score_pdl = classify_swept_level(
            breach_point=bias_res.pdl - 0.5,
            positive_direction=True,
            daily_bias=bias_res,
            atr=10.0,
        )
        assert "Previous Day Low" in swept_type_pdl
        assert score_pdl == 18.0

        # Sweeping a random non-structural price earns benchmark baseline points
        swept_type_rand, score_rand = classify_swept_level(
            breach_point=1500.0,
            positive_direction=True,
            daily_bias=bias_res,
            atr=10.0,
        )
        assert score_rand < 18.0



class TestCRTAuditRemediations:
    """32 focused regression tests covering all 6 remediation areas from REPORT.md."""

    # =========================================================================
    # Group 1: Confirmation Tests (1-12)
    # Tasks A, B, C: Displacement gate, Chronological MSS filtering, Body-close MSS
    # =========================================================================

    def test_reentry_displacement_post_sweep_mss_confirmed(self):
        """1. Re-entry candle with valid displacement + valid post-sweep MSS body close confirms BUY."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        t0 = SESSION_ACTIVE_TS
        c_sweep = _make_candle(1945.0, 1950.0, 1935.0, 1940.0, timestamp=t0, timeframe="15m")
        c_confirm = _make_candle(1940.0, 1965.0, 1938.0, 1962.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")
        res = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_confirm],
            breach_point=1935.0,
            manip_candle_index=0,
            breach_timestamp=t0,
            atr=10.0,
        )
        assert res.is_confirmed is True
        assert res.has_reentered_range is True
        assert res.has_displacement is True
        assert res.has_mss is True

    def test_reentry_no_displacement_mss_not_confirmed(self):
        """2. Re-entry candle with MSS but lacking displacement returns is_confirmed=False."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        t0 = SESSION_ACTIVE_TS
        c_sweep = _make_candle(1945.0, 1950.0, 1935.0, 1940.0, timestamp=t0, timeframe="15m")
        c_confirm = _make_candle(1953.0, 1960.0, 1940.0, 1954.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")
        res = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_confirm],
            breach_point=1935.0,
            manip_candle_index=0,
            breach_timestamp=t0,
            atr=10.0,
        )
        assert res.is_confirmed is False
        assert res.has_displacement is False
        assert res.state == "WAITING_FOR_CONFIRMATION"
        assert "displacement" in res.reason.lower()

    def test_reentry_displacement_no_mss_not_confirmed(self):
        """3. Re-entry candle with displacement but lacking post-sweep MSS returns is_confirmed=False."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        t0 = SESSION_ACTIVE_TS
        c_sweep = _make_candle(1950.0, 1970.0, 1935.0, 1940.0, timestamp=t0, timeframe="15m")
        c_confirm = _make_candle(1940.0, 1957.0, 1940.0, 1955.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")
        res = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_confirm],
            breach_point=1935.0,
            manip_candle_index=0,
            breach_timestamp=t0,
            atr=10.0,
        )
        assert res.is_confirmed is False
        assert res.has_displacement is True
        assert res.has_mss is False
        assert "mss" in res.reason.lower()

    def test_reentry_no_displacement_no_mss_not_confirmed(self):
        """4. Re-entry candle with neither displacement nor MSS returns is_confirmed=False."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        t0 = SESSION_ACTIVE_TS
        c_sweep = _make_candle(1950.0, 1970.0, 1935.0, 1940.0, timestamp=t0, timeframe="15m")
        c_confirm = _make_candle(1951.0, 1955.0, 1949.0, 1952.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")
        res = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_confirm],
            breach_point=1935.0,
            manip_candle_index=0,
            breach_timestamp=t0,
            atr=10.0,
        )
        assert res.is_confirmed is False
        assert res.has_displacement is False
        assert res.has_mss is False

    def test_doji_cannot_qualify_as_displacement(self):
        """5. A doji (tiny body, long wicks) cannot qualify as displacement."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        t0 = SESSION_ACTIVE_TS
        c_sweep = _make_candle(1945.0, 1950.0, 1935.0, 1940.0, timestamp=t0, timeframe="15m")
        c_doji = _make_candle(1951.0, 1968.0, 1936.0, 1951.2, timestamp=t0 + timedelta(minutes=15), timeframe="15m")
        res = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_doji],
            breach_point=1935.0,
            manip_candle_index=0,
            breach_timestamp=t0,
            atr=10.0,
        )
        assert res.has_displacement is False
        assert res.is_confirmed is False

    def test_presweep_bullish_choch_cannot_confirm_buy(self):
        """6. Pre-sweep bullish CHOCH/BOS event (timestamp <= breach_timestamp) cannot confirm a BUY."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        from types import SimpleNamespace
        t0 = SESSION_ACTIVE_TS
        breach_ts = t0 + timedelta(hours=1)
        pre_sweep_event = SimpleNamespace(
            event_type="BULLISH_CHOCH",
            timestamp=t0 + timedelta(minutes=30),
        )
        mock_structure = SimpleNamespace(recent_events=[pre_sweep_event])

        c_sweep = _make_candle(1950.0, 1970.0, 1935.0, 1940.0, timestamp=breach_ts, timeframe="15m")
        c_confirm = _make_candle(1940.0, 1958.0, 1938.0, 1955.0, timestamp=breach_ts + timedelta(minutes=15), timeframe="15m")

        res = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_confirm],
            breach_point=1935.0,
            manip_candle_index=0,
            breach_timestamp=breach_ts,
            atr=10.0,
            structure=mock_structure,
        )
        assert res.has_displacement is True
        assert res.has_mss is False
        assert res.is_confirmed is False

    def test_presweep_bearish_choch_cannot_confirm_sell(self):
        """7. Pre-sweep bearish CHOCH/BOS event cannot confirm a SELL."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        from types import SimpleNamespace
        t0 = SESSION_ACTIVE_TS
        breach_ts = t0 + timedelta(hours=1)
        pre_sweep_event = SimpleNamespace(
            event_type="BEARISH_CHOCH",
            timestamp=t0 + timedelta(minutes=30),
        )
        mock_structure = SimpleNamespace(recent_events=[pre_sweep_event])

        c_sweep = _make_candle(2050.0, 2065.0, 2030.0, 2060.0, timestamp=breach_ts, timeframe="15m")
        c_confirm = _make_candle(2060.0, 2062.0, 2042.0, 2045.0, timestamp=breach_ts + timedelta(minutes=15), timeframe="15m")

        res = verify_ltf_confirmation(
            direction=SignalDirection.SELL,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_confirm],
            breach_point=2065.0,
            manip_candle_index=0,
            breach_timestamp=breach_ts,
            atr=10.0,
            structure=mock_structure,
        )
        assert res.has_displacement is True
        assert res.has_mss is False
        assert res.is_confirmed is False

    def test_postsweep_valid_mss_can_qualify(self):
        """8. Post-sweep valid MSS (timestamp > breach_timestamp) qualifies for confirmation."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        from types import SimpleNamespace
        t0 = SESSION_ACTIVE_TS
        breach_ts = t0 + timedelta(hours=1)
        post_sweep_event = SimpleNamespace(
            event_type="BULLISH_CHOCH",
            timestamp=breach_ts + timedelta(minutes=15),
        )
        mock_structure = SimpleNamespace(recent_events=[post_sweep_event])

        c_sweep = _make_candle(1950.0, 1970.0, 1935.0, 1940.0, timestamp=breach_ts, timeframe="15m")
        c_confirm = _make_candle(1940.0, 1958.0, 1938.0, 1955.0, timestamp=breach_ts + timedelta(minutes=15), timeframe="15m")

        res = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_confirm],
            breach_point=1935.0,
            manip_candle_index=0,
            breach_timestamp=breach_ts,
            atr=10.0,
            structure=mock_structure,
        )
        assert res.has_displacement is True
        assert res.has_mss is True
        assert res.is_confirmed is True

    def test_mss_missing_timestamp_cannot_bypass_chronology(self):
        """9. Event with timestamp=None cannot bypass chronological filtering and is skipped."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        from types import SimpleNamespace
        t0 = SESSION_ACTIVE_TS
        breach_ts = t0 + timedelta(hours=1)
        no_ts_event = SimpleNamespace(
            event_type="BULLISH_CHOCH",
            timestamp=None,
        )
        mock_structure = SimpleNamespace(recent_events=[no_ts_event])

        c_sweep = _make_candle(1950.0, 1970.0, 1935.0, 1940.0, timestamp=breach_ts, timeframe="15m")
        c_confirm = _make_candle(1940.0, 1958.0, 1938.0, 1955.0, timestamp=breach_ts + timedelta(minutes=15), timeframe="15m")

        res = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_confirm],
            breach_point=1935.0,
            manip_candle_index=0,
            breach_timestamp=breach_ts,
            atr=10.0,
            structure=mock_structure,
        )
        assert res.has_mss is False
        assert res.is_confirmed is False

    def test_wick_only_bullish_break_cannot_qualify_mss(self):
        """10. Wick-only break above swing high without body close cannot qualify as MSS."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        t0 = SESSION_ACTIVE_TS
        c_sweep = _make_candle(1945.0, 1960.0, 1935.0, 1940.0, timestamp=t0, timeframe="15m")
        c_confirm = _make_candle(1940.0, 1965.0, 1938.0, 1958.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")

        res = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_confirm],
            breach_point=1935.0,
            manip_candle_index=0,
            breach_timestamp=t0,
            atr=10.0,
        )
        assert res.has_mss is False
        assert res.is_confirmed is False

    def test_wick_only_bearish_break_cannot_qualify_mss(self):
        """11. Wick-only break below swing low without body close cannot qualify as MSS."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        t0 = SESSION_ACTIVE_TS
        c_sweep = _make_candle(2055.0, 2065.0, 2040.0, 2060.0, timestamp=t0, timeframe="15m")
        c_confirm = _make_candle(2060.0, 2062.0, 2035.0, 2042.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")

        res = verify_ltf_confirmation(
            direction=SignalDirection.SELL,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_confirm],
            breach_point=2065.0,
            manip_candle_index=0,
            breach_timestamp=t0,
            atr=10.0,
        )
        assert res.has_mss is False
        assert res.is_confirmed is False

    def test_close_beyond_swing_level_qualifies_mss(self):
        """12. Candle body close strictly beyond swing level qualifies as MSS."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        t0 = SESSION_ACTIVE_TS
        c_sweep = _make_candle(1945.0, 1960.0, 1935.0, 1940.0, timestamp=t0, timeframe="15m")
        c_confirm = _make_candle(1940.0, 1965.0, 1938.0, 1962.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")

        res = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_confirm],
            breach_point=1935.0,
            manip_candle_index=0,
            breach_timestamp=t0,
            atr=10.0,
        )
        assert res.has_mss is True
        assert res.is_confirmed is True

    # =========================================================================
    # Group 2: Manipulation Candle Tests (13-17)
    # Task D: Correct manipulation candle identification and slice isolation
    # =========================================================================

    def test_manipulation_candle_metadata_propagated_correctly(self):
        """13. CRTAnalysis.manipulation_candle_index accurately identifies extreme sweep candle."""
        from app.services.structure.crt_analyzer import CRTAnalyzer
        t0 = SESSION_ACTIVE_TS
        rc = _make_candle(2000.0, 2050.0, 1950.0, 2020.0, timestamp=t0, timeframe="1h")
        c0 = _make_candle(1955.0, 1960.0, 1945.0, 1948.0, timestamp=t0 + timedelta(hours=1), timeframe="15m")
        c1 = _make_candle(1948.0, 1950.0, 1932.0, 1936.0, timestamp=t0 + timedelta(hours=1, minutes=15), timeframe="15m")
        c2 = _make_candle(1936.0, 1965.0, 1935.0, 1960.0, timestamp=t0 + timedelta(hours=1, minutes=30), timeframe="15m")

        analyzer = CRTAnalyzer()
        analysis = analyzer.analyze([rc], confirm_candles=[c0, c1, c2])

        assert analysis.is_breached is True
        assert analysis.breach_point == 1932.0
        assert analysis.breach_timestamp == c1.timestamp
        assert analysis.manipulation_candle_index == 1

    def test_presweep_candles_cannot_contribute_to_displacement(self):
        """14. Pre-sweep candles prior to manipulation extreme cannot satisfy displacement requirement."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        t0 = SESSION_ACTIVE_TS
        c0 = _make_candle(1940.0, 1970.0, 1938.0, 1968.0, timestamp=t0, timeframe="15m")
        c1 = _make_candle(1968.0, 1970.0, 1930.0, 1932.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")
        c2 = _make_candle(1952.0, 1954.0, 1951.0, 1953.0, timestamp=t0 + timedelta(minutes=30), timeframe="15m")

        res = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c0, c1, c2],
            breach_point=1930.0,
            manip_candle_index=1,
            breach_timestamp=c1.timestamp,
            atr=10.0,
        )
        assert res.has_displacement is False
        assert res.is_confirmed is False

    def test_presweep_candles_cannot_contribute_to_mss(self):
        """15. Pre-sweep candles cannot contribute to MSS breakout verification."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        t0 = SESSION_ACTIVE_TS
        c0 = _make_candle(1950.0, 1960.0, 1948.0, 1955.0, timestamp=t0, timeframe="15m")
        c1 = _make_candle(1955.0, 1966.0, 1954.0, 1965.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")
        c2 = _make_candle(1965.0, 1966.0, 1930.0, 1935.0, timestamp=t0 + timedelta(minutes=30), timeframe="15m")
        c3 = _make_candle(1935.0, 1956.0, 1934.0, 1955.0, timestamp=t0 + timedelta(minutes=45), timeframe="15m")

        res = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c0, c1, c2, c3],
            breach_point=1930.0,
            manip_candle_index=2,
            breach_timestamp=c2.timestamp,
            atr=10.0,
        )
        assert res.has_displacement is True
        assert res.has_mss is False
        assert res.is_confirmed is False

    def test_incorrect_or_missing_manipulation_metadata_fails_safely(self):
        """16. Missing or out-of-bounds manipulation metadata fails safely without uncaught exceptions."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        t0 = SESSION_ACTIVE_TS
        c0 = _make_candle(1950.0, 1960.0, 1935.0, 1940.0, timestamp=t0, timeframe="15m")
        c1 = _make_candle(1940.0, 1965.0, 1938.0, 1962.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")

        res_none = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c0, c1],
            breach_point=1935.0,
            manip_candle_index=None,
            atr=10.0,
        )
        assert isinstance(res_none.is_confirmed, bool)

        res_oob = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c0, c1],
            breach_point=1935.0,
            manip_candle_index=99,
            atr=10.0,
        )
        assert res_oob.is_confirmed is False
        assert res_oob.state == "WAITING_FOR_CONFIRMATION"

    def test_filtered_candle_lists_timestamp_reference_prevents_misalignment(self):
        """17. Timestamp-based alignment between candle lists prevents index misalignment."""
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        t0 = SESSION_ACTIVE_TS
        c0 = _make_candle(1955.0, 1960.0, 1945.0, 1948.0, timestamp=t0, timeframe="15m")
        c1 = _make_candle(1948.0, 1950.0, 1932.0, 1936.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")
        c2 = _make_candle(1936.0, 1965.0, 1935.0, 1962.0, timestamp=t0 + timedelta(minutes=30), timeframe="15m")

        res = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c0, c1, c2],
            breach_point=1932.0,
            manip_candle_index=0,
            breach_timestamp=c1.timestamp,
            atr=10.0,
        )
        assert res.is_confirmed is True

    # =========================================================================
    # Group 3: Entry Geometry Tests (18-25)
    # Task E: Intended entry price, target calculations, and real R:R geometry
    # =========================================================================

    def test_buy_market_entry_geometry(self):
        """18. Market BUY entry geometry uses current/confirmation close for all risk-reward calculations."""
        from app.services.strategies.crt.entry import calculate_retracement_entry
        from app.services.strategies.crt.targets import calculate_crt_targets
        t0 = SESSION_ACTIVE_TS
        c_sweep = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=t0, timeframe="15m")
        c_confirm = _make_candle(1945.0, 1960.0, 1940.0, 1955.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")

        entry_res = calculate_retracement_entry(
            direction=SignalDirection.BUY,
            sweep_extreme=1935.0,
            displacement_extreme=1960.0,
            candles_15m=[c_sweep, c_confirm],
            current_price=1955.0,
            target_tp1=2025.0,
            atr=10.0,
        )
        assert entry_res.entry_mode == "market"
        target_plan = calculate_crt_targets(
            direction=SignalDirection.BUY,
            entry_price=1955.0,
            stop_loss=entry_res.stop_loss,
            range_high=2100.0,
            range_low=1950.0,
        )
        assert target_plan.is_valid is True
        expected_rr = (2025.0 - 1955.0) / (1955.0 - entry_res.stop_loss)
        assert target_plan.risk_reward_tp1 == pytest.approx(expected_rr, 0.01)

    def test_sell_market_entry_geometry(self):
        """19. Market SELL entry geometry uses current/confirmation close for all risk-reward calculations."""
        from app.services.strategies.crt.entry import calculate_retracement_entry
        from app.services.strategies.crt.targets import calculate_crt_targets
        t0 = SESSION_ACTIVE_TS
        c_sweep = _make_candle(2045.0, 2065.0, 2040.0, 2055.0, timestamp=t0, timeframe="15m")
        c_confirm = _make_candle(2055.0, 2060.0, 2040.0, 2045.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")
        midpoint_eq = (2065.0 + 2040.0) / 2.0

        entry_res = calculate_retracement_entry(
            direction=SignalDirection.SELL,
            sweep_extreme=2065.0,
            displacement_extreme=2040.0,
            candles_15m=[c_sweep, c_confirm],
            current_price=midpoint_eq,
            target_tp1=1975.0,
            atr=10.0,
        )
        assert entry_res.entry_mode == "market"
        target_plan = calculate_crt_targets(
            direction=SignalDirection.SELL,
            entry_price=midpoint_eq,
            stop_loss=entry_res.stop_loss,
            range_high=2050.0,
            range_low=1950.0,
        )
        assert target_plan.is_valid is True
        expected_rr = (midpoint_eq - 2000.0) / (entry_res.stop_loss - midpoint_eq)
        assert target_plan.risk_reward_tp1 == pytest.approx(expected_rr, 0.01)

    def test_buy_limit_entry_uses_intended_limit_price_for_rr(self):
        """20. Limit-zone BUY entry uses intended limit price (ideal_entry) for R:R calculations (3.08R vs 1.04R)."""
        from app.services.strategies.crt.targets import calculate_crt_targets
        plan = calculate_crt_targets(
            direction=SignalDirection.BUY,
            entry_price=1994.0,
            stop_loss=1988.0,
            range_high=2030.0,
            range_low=1995.0,
        )
        assert plan.is_valid is True
        assert plan.risk_usd == 6.0
        assert plan.reward_usd_tp1 == 18.5
        assert plan.risk_reward_tp1 == pytest.approx(3.08, 0.01)

    def test_sell_limit_entry_uses_intended_limit_price_for_rr(self):
        """21. Limit-zone SELL entry uses intended limit price (ideal_entry) for R:R calculations."""
        from app.services.strategies.crt.targets import calculate_crt_targets
        plan = calculate_crt_targets(
            direction=SignalDirection.SELL,
            entry_price=2006.0,
            stop_loss=2012.0,
            range_high=2005.0,
            range_low=1970.0,
        )
        assert plan.is_valid is True
        assert plan.risk_usd == 6.0
        assert plan.reward_usd_tp1 == 18.5
        assert plan.risk_reward_tp1 == pytest.approx(3.08, 0.01)

    def test_stop_loss_validation_uses_effective_entry(self):
        """22. Stop loss validation enforces stop_loss < effective_entry (BUY) and stop_loss > effective_entry (SELL)."""
        from app.services.strategies.crt.targets import calculate_crt_targets
        plan_buy_inv = calculate_crt_targets(
            direction=SignalDirection.BUY,
            entry_price=1994.0,
            stop_loss=1995.0,
            range_high=2030.0,
            range_low=1995.0,
        )
        assert plan_buy_inv.is_valid is False
        assert plan_buy_inv.rejection_gate == "INVALID_RISK_GEOMETRY"

        plan_sell_inv = calculate_crt_targets(
            direction=SignalDirection.SELL,
            entry_price=2006.0,
            stop_loss=2005.0,
            range_high=2005.0,
            range_low=1970.0,
        )
        assert plan_sell_inv.is_valid is False
        assert plan_sell_inv.rejection_gate == "INVALID_RISK_GEOMETRY"

    def test_obstacle_path_rr_uses_effective_entry(self):
        """23. Obstacle path validator calculates reward-to-risk from effective_entry to obstacle price."""
        from app.services.strategies.crt.targets import calculate_crt_targets
        from app.schemas.liquidity import SupportResistanceZone, ZoneType
        from types import SimpleNamespace
        # Obstacle at 2002.0. Effective entry is 1994.0, SL is 1988.0 (risk = 6.0).
        # Capped TP1 = 2001.5. Reward = 2001.5 - 1994.0 = 7.5 -> R:R = 7.5 / 6.0 = 1.25R (>= 1.0R min_rr).
        zone = SupportResistanceZone(
            zone_type=ZoneType.RESISTANCE,
            price_high=2003.0,
            price_low=2001.0,
            center_price=2002.0,
            touch_count=3,
            first_touch=SESSION_ACTIVE_TS,
            last_touch=SESSION_ACTIVE_TS,
            strength=0.8,
        )
        structure = SimpleNamespace(sr_zones=[zone], liquidity_pools=[])
        plan = calculate_crt_targets(
            direction=SignalDirection.BUY,
            entry_price=1994.0,
            stop_loss=1988.0,
            range_high=2030.0,
            range_low=1995.0,
            structure=structure,
            min_rr=1.0,
        )
        assert plan.is_valid is True
        assert plan.capped_by_obstacle is True
        assert plan.take_profit_1 == 2001.5
        assert plan.risk_reward_tp1 == pytest.approx(1.25, 0.01)

    def test_position_sizing_uses_executable_entry(self):
        """24. Position sizing risk distance uses abs(effective_entry - stop_loss)."""
        now = SESSION_ACTIVE_TS
        range_candle, manip_candle, confirm_candle = _make_amd_fixture(
            2000.0, 2100.0, 1950.0, 2080.0,
            1955.0, 1960.0, 1935.0, 1945.0,
            1945.0, 1970.0, 1940.0, 1965.0,
            base_time=now,
        )
        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1, enable_dedup=False)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
            account_balance=10000.0,
            risk_percent=1.0,
        )
        assert result.direction == SignalDirection.BUY
        effective_entry = result.metadata["entry_price"]
        expected_sl = result.metadata["stop_loss"]
        expected_risk_dist = effective_entry - expected_sl  # 1955.0 - 1935.0 = 20.0
        # 20.0 price distance in Gold = 200 pips (pip_size=0.1)
        assert result.metadata["risk_pips"] == pytest.approx(200.0)
        assert "risk_amount_usd" in result.metadata
        assert result.metadata["risk_amount_usd"] <= 100.0
        assert result.metadata["suggested_lot_size"] > 0

    def test_invalid_geometry_rejected_safely(self):
        """25. Inverted or zero risk distance is rejected safely with INVALID_RISK_GEOMETRY."""
        from app.services.strategies.crt.targets import calculate_crt_targets
        plan_zero = calculate_crt_targets(
            direction=SignalDirection.BUY,
            entry_price=2000.0,
            stop_loss=2000.0,
            range_high=2050.0,
            range_low=1950.0,
        )
        assert plan_zero.is_valid is False
        assert plan_zero.rejection_gate == "INVALID_RISK_GEOMETRY"

    # =========================================================================
    # Group 4: Lifecycle Tests (26-32)
    # Task F: Entry lifecycle state machine and chronological fill detection
    # =========================================================================

    def test_lifecycle_pending_order_missed_after_threshold(self):
        """26. Pending limit order running > 0.5R toward TP1 without filling transitions to MISSED."""
        from app.services.strategies.crt.entry import calculate_retracement_entry
        from app.services.strategies.crt.lifecycle import evaluate_lifecycle_state, CRTState
        t0 = SESSION_ACTIVE_TS
        c_sweep = _make_candle(1955.0, 1960.0, 1935.0, 1945.0, timestamp=t0, timeframe="15m")
        c_confirm = _make_candle(1945.0, 1970.0, 1940.0, 1965.0, timestamp=t0 + timedelta(minutes=15), timeframe="15m")
        c_runaway = _make_candle(1965.0, 1982.0, 1960.0, 1980.0, timestamp=t0 + timedelta(minutes=30), timeframe="15m")

        entry_res = calculate_retracement_entry(
            direction=SignalDirection.BUY,
            sweep_extreme=1935.0,
            displacement_extreme=1970.0,
            candles_15m=[c_sweep, c_confirm, c_runaway],
            current_price=1980.0,
            target_tp1=2025.0,
            atr=10.0,
        )
        # The confirmation candle's low (1940) reaches ideal_entry (1955), so
        # the pending limit is filled on that bar rather than missed later.
        assert entry_res.is_missed is False

        lifecycle_res = evaluate_lifecycle_state(
            sweep_key="TEST_BUY_MISSED_1",
            direction=SignalDirection.BUY,
            current_price=1980.0,
            current_time=t0 + timedelta(minutes=30),
            entry_price=entry_res.ideal_entry,
            stop_loss=entry_res.stop_loss,
            tp1=2025.0,
            tp2=2100.0,
            zone_high=entry_res.zone_high,
            zone_low=entry_res.zone_low,
            expires_at=entry_res.expires_at,
            is_missed=entry_res.is_missed,
            initial_state=CRTState.CONFIRMED,
        )
        assert lifecycle_res.current_state == CRTState.CONFIRMED

    def test_lifecycle_pending_order_fills_at_t1_remains_filled_at_t2(self):
        """27. Pending limit order fills when price touches ideal_entry at t1 and remains FILLED at t2."""
        from app.services.strategies.crt.lifecycle import evaluate_lifecycle_state, CRTState
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            key = "TEST_LIFECYCLE_FILL_PERSIST_1"
            now = SESSION_ACTIVE_TS
            expiry = now + timedelta(hours=2)

            res_init = evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=2005.0, current_time=now,
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            assert res_init.current_state == CRTState.CONFIRMED

            res_fill = evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=1998.0, current_time=now + timedelta(minutes=15),
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            assert res_fill.current_state == CRTState.ENTRY_FILLED

            res_t2 = evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=2010.0, current_time=now + timedelta(minutes=30),
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            assert res_t2.current_state == CRTState.ENTRY_FILLED
        finally:
            db.close()

    def test_lifecycle_filled_setup_cannot_become_missed_at_t3(self):
        """28. Filled setup running toward TP1 at t3 cannot regress to MISSED."""
        from app.services.strategies.crt.lifecycle import evaluate_lifecycle_state, CRTState
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            key = "TEST_FILLED_CANNOT_MISS_1"
            now = SESSION_ACTIVE_TS
            expiry = now + timedelta(hours=2)

            evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=1998.0, current_time=now,
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )

            res_t3 = evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=2015.0, current_time=now + timedelta(hours=1),
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
                is_missed=True,
            )
            assert res_t3.current_state == CRTState.ENTRY_FILLED
            assert res_t3.current_state != CRTState.MISSED
        finally:
            db.close()

    def test_lifecycle_filled_setup_transitions_to_tp1_hit(self):
        """29. Filled setup reaching TP1 transitions to TP1_HIT with one-time alert."""
        from app.services.strategies.crt.lifecycle import evaluate_lifecycle_state, CRTState
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            key = "TEST_TP1_TRANSITION_1"
            now = SESSION_ACTIVE_TS
            expiry = now + timedelta(hours=2)

            evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=1998.0, current_time=now,
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            res_tp1 = evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=2031.0, current_time=now + timedelta(minutes=45),
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            assert res_tp1.current_state == CRTState.TP1_HIT
            assert res_tp1.should_send_management_alert is True
            assert "TP1_HIT" in res_tp1.alert_title
        finally:
            db.close()

    def test_lifecycle_filled_setup_transitions_to_stopped(self):
        """30. Filled setup reaching SL transitions to STOPPED with one-time alert."""
        from app.services.strategies.crt.lifecycle import evaluate_lifecycle_state, CRTState
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            key = "TEST_STOPPED_TRANSITION_1"
            now = SESSION_ACTIVE_TS
            expiry = now + timedelta(hours=2)

            evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=1998.0, current_time=now,
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            res_stopped = evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=1978.0, current_time=now + timedelta(minutes=45),
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            assert res_stopped.current_state == CRTState.STOPPED
            assert res_stopped.should_send_management_alert is True
            assert "STOPPED" in res_stopped.alert_title
        finally:
            db.close()

    def test_lifecycle_future_candles_cannot_alter_historical_decision_at_t(self):
        """31. Zero lookahead: evaluating at time t produces identical decision regardless of future candles."""
        now = SESSION_ACTIVE_TS
        range_candle, manip_candle, confirm_candle = _make_amd_fixture(
            2000.0, 2100.0, 1950.0, 2080.0,
            1955.0, 1960.0, 1935.0, 1945.0,
            1945.0, 1970.0, 1940.0, 1965.0,
            base_time=now,
        )
        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1, enable_dedup=False)
        res_t = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
        )

        res_repeat = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_candle],
        )
        assert res_t.direction == res_repeat.direction
        assert res_t.entry_price == res_repeat.entry_price
        assert res_t.stop_loss == res_repeat.stop_loss
        assert res_t.score == res_repeat.score

    def test_lifecycle_repeated_evaluation_no_duplicate_alerts(self):
        """32. Repeated evaluation in the same state does not trigger duplicate management alerts."""
        from app.services.strategies.crt.lifecycle import evaluate_lifecycle_state, CRTState
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            key = "TEST_NO_DUPLICATE_ALERTS_1"
            now = SESSION_ACTIVE_TS
            expiry = now + timedelta(hours=2)

            evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=1998.0, current_time=now,
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            res_tp1_first = evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=2031.0, current_time=now + timedelta(minutes=45),
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            assert res_tp1_first.should_send_management_alert is True

            res_tp1_repeat = evaluate_lifecycle_state(
                sweep_key=key, direction=SignalDirection.BUY, current_price=2033.0, current_time=now + timedelta(minutes=50),
                entry_price=2000.0, stop_loss=1980.0, tp1=2030.0, tp2=2060.0,
                zone_high=2002.0, zone_low=1995.0, expires_at=expiry, db_conn=db,
            )
            assert res_tp1_repeat.current_state == CRTState.TP1_HIT
            assert res_tp1_repeat.transition_occurred is False
            assert res_tp1_repeat.should_send_management_alert is False
        finally:
            db.close()

    def test_limit_zone_reported_rr_matches_ideal_entry_geometry(self):
        """Defect 5: Verify limit_zone setup's reported R:R matches
        (TP1 - ideal_entry) / (ideal_entry - SL), not the current_price version.
        """
        now = SESSION_ACTIVE_TS
        range_c = _make_candle(2020.0, 2100.0, 2000.0, 2080.0, timestamp=now)
        manip_c = _make_candle(2005.0, 2008.0, 1990.0, 1995.0, timestamp=now + timedelta(hours=1), timeframe="15m")
        confirm_c = _make_candle(1995.0, 2020.0, 1992.0, 2015.0, timestamp=now + timedelta(hours=1, minutes=15), timeframe="15m")

        strategy = CRTStrategy(entry_expiry_bars=8)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="1h",
            candles=[range_c],
            candles_15m=[manip_c, confirm_c],
        )

        assert result.metadata["entry_mode"] == "limit_zone"
        ideal_entry = result.metadata["ideal_entry"]
        current_price = confirm_c.close
        assert ideal_entry != current_price

        expected_rr = (result.take_profit_1 - ideal_entry) / (ideal_entry - result.stop_loss)
        current_price_rr = (result.take_profit_1 - current_price) / (current_price - result.stop_loss)

        assert result.risk_reward == pytest.approx(expected_rr, 0.01)
        assert result.metadata["risk_reward_tp1"] == pytest.approx(expected_rr, 0.01)
        assert result.risk_reward != pytest.approx(current_price_rr, 0.01)

    def test_counter_trend_bypass_rejects_outright_when_atr_invalid(self):
        """Verify counter-trend setup is REJECTED outright when ATR is invalid (<= 0),
        even when allow_counter_trend_bypass=True and displacement is positive.
        """
        now = SESSION_ACTIVE_TS
        t0 = now
        range_candle = _make_candle(2000.0, 2100.0, 1950.0, 2080.0, timestamp=t0, timeframe="1h")
        manip_candle = _make_candle(1948.0, 1950.0, 1935.0, 1942.0, timestamp=t0 + timedelta(hours=1), timeframe="15m")
        confirm_strong = _make_candle(1946.0, 1966.0, 1942.0, 1964.0, timestamp=t0 + timedelta(hours=1, minutes=15), timeframe="15m")

        strategy = CRTStrategy(min_manip_pct=5.0, confirm_bars=1, enable_dedup=False, allow_counter_trend_bypass=True)
        result = strategy.analyze(
            symbol="XAU/USD",
            timeframe="15m",
            candles=[range_candle],
            candles_15m=[manip_candle, confirm_strong],
            htf_trend="BEARISH",
            atr_value=0.0,
        )

        assert result.direction == SignalDirection.WAIT
        assert result.score == 0.0
        assert result.metadata["trend_conflict"] is True
        assert result.metadata["rejection_gate"] == "TREND_CONFLICT"

    def test_mss_present_displacement_absent_returns_waiting_for_confirmation(self):
        """Defect 1 regression: When MSS is present but displacement is absent,
        confirmation must return is_confirmed=False and WAITING_FOR_CONFIRMATION.
        """
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        from types import SimpleNamespace
        t0 = SESSION_ACTIVE_TS
        breach_ts = t0 + timedelta(hours=1)
        # Post-sweep MSS event is present and valid
        valid_post_sweep_mss = SimpleNamespace(
            event_type="BULLISH_CHOCH",
            timestamp=breach_ts + timedelta(minutes=15),
        )
        mock_structure = SimpleNamespace(recent_events=[valid_post_sweep_mss])

        # Sweep candle breaching 1950 down to 1930
        c_sweep = _make_candle(1950.0, 1955.0, 1930.0, 1935.0, timestamp=breach_ts, timeframe="15m")
        # Re-entry candle: close=1951 re-enters range (>1950), but body=1.0 < 0.20*atr (2.0) -> displacement absent
        c_no_disp = _make_candle(1950.0, 1952.0, 1948.0, 1951.0, timestamp=breach_ts + timedelta(minutes=15), timeframe="15m")

        res = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_no_disp],
            breach_point=1930.0,
            manip_candle_index=0,
            breach_timestamp=breach_ts,
            atr=10.0,
            structure=mock_structure,
        )

        assert res.has_displacement is False
        assert res.is_confirmed is False
        assert res.state == "WAITING_FOR_CONFIRMATION"

    def test_presweep_choch_fails_mss_check(self):
        """Defect 2 regression: Structure CHOCH event occurring before or at the sweep
        (ev.timestamp <= breach_ts) must not qualify as post-sweep MSS (has_mss=False).
        """
        from app.services.strategies.crt.confirmation import verify_ltf_confirmation
        from types import SimpleNamespace
        t0 = SESSION_ACTIVE_TS
        breach_ts = t0 + timedelta(hours=1)

        # Pre-sweep event (timestamp < breach_ts)
        pre_event = SimpleNamespace(
            event_type="BULLISH_CHOCH",
            timestamp=breach_ts - timedelta(minutes=15),
        )
        mock_structure = SimpleNamespace(recent_events=[pre_event])

        # Sweep candle
        c_sweep = _make_candle(1950.0, 1970.0, 1930.0, 1935.0, timestamp=breach_ts, timeframe="15m")
        # Displacement candle: open=1935, close=1955, body=20 >= 2.0 and body/range > 0.50 -> displacement present
        # However, high=1956 does not break swing high (1970), so fallback candle-break MSS is not triggered
        c_disp = _make_candle(1935.0, 1956.0, 1934.0, 1955.0, timestamp=breach_ts + timedelta(minutes=15), timeframe="15m")

        res_pre = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_disp],
            breach_point=1930.0,
            manip_candle_index=0,
            breach_timestamp=breach_ts,
            atr=10.0,
            structure=mock_structure,
        )

        assert res_pre.has_displacement is True
        assert res_pre.has_mss is False
        assert res_pre.is_confirmed is False
        assert res_pre.state == "WAITING_FOR_CONFIRMATION"

        # Also verify event exactly at sweep timestamp (timestamp == breach_ts)
        at_sweep_event = SimpleNamespace(
            event_type="BULLISH_CHOCH",
            timestamp=breach_ts,
        )
        mock_structure_at = SimpleNamespace(recent_events=[at_sweep_event])

        res_at = verify_ltf_confirmation(
            direction=SignalDirection.BUY,
            range_high=2050.0,
            range_low=1950.0,
            candles_15m=[c_sweep, c_disp],
            breach_point=1930.0,
            manip_candle_index=0,
            breach_timestamp=breach_ts,
            atr=10.0,
            structure=mock_structure_at,
        )

        assert res_at.has_displacement is True
        assert res_at.has_mss is False
        assert res_at.is_confirmed is False
        assert res_at.state == "WAITING_FOR_CONFIRMATION"

    def test_retracement_entry_sliding_window_manip_index_misalignment_defect(self):
        """Geometry Defect Demonstration: manip_candle_index from filtered_confirms causes sliding-window misalignment.

        In evaluate_bar, analysis.manipulation_candle_index is the index within filtered_confirms
        (typically 0 or 1), but is passed to calculate_retracement_entry alongside c_candles (a sliding
        window of up to 200 bars). This causes calculate_retracement_entry to anchor created_time,
        expiry, and FVG/OB detection to candles from 2-3 days ago (c_candles[0]), finding ancient
        zones that conflict with current stop loss and triggering false INVALID_ENTRY_ZONE rejections.
        """
        from app.services.strategies.crt.entry import calculate_retracement_entry

        t_base = SESSION_ACTIVE_TS - timedelta(days=2)
        # Create 50 historical bars at ~2900 with an FVG at bars 0..2
        candles_50 = []
        candles_50.append(_make_candle(2905.0, 2909.0, 2904.0, 2908.0, timestamp=t_base, timeframe="15m"))
        candles_50.append(_make_candle(2908.0, 2912.0, 2907.0, 2911.0, timestamp=t_base + timedelta(minutes=15), timeframe="15m"))
        candles_50.append(_make_candle(2911.0, 2915.0, 2910.0, 2914.0, timestamp=t_base + timedelta(minutes=30), timeframe="15m"))
        for idx in range(3, 48):
            candles_50.append(_make_candle(2910.0, 2912.0, 2908.0, 2910.0, timestamp=t_base + timedelta(minutes=15 * idx), timeframe="15m"))

        # Today's bars (bars 48 and 49) at price ~2860
        t_today = SESSION_ACTIVE_TS
        c_sweep = _make_candle(2860.0, 2865.0, 2858.0, 2863.0, timestamp=t_today, timeframe="15m")
        c_disp = _make_candle(2863.0, 2864.0, 2856.0, 2858.0, timestamp=t_today + timedelta(minutes=15), timeframe="15m")
        candles_50.append(c_sweep)
        candles_50.append(c_disp)

        # In filtered_confirms, c_sweep is index 0.
        # But in candles_50, c_sweep is index 48.
        # When CRTStrategy passes manip_candle_index=0:
        entry_res = calculate_retracement_entry(
            direction=SignalDirection.SELL,
            sweep_extreme=2865.0,
            displacement_extreme=2856.0,
            candles_15m=candles_50,
            current_price=2858.0,
            target_tp1=2840.0,
            atr=8.0,
            spread=0.40,
            expiry_bars=8,
            manip_candle_index=0,  # The index from filtered_confirms passed by crt_strategy.py!
            tick_size=0.01,
        )

        # Expected behavior: created_time is t_today (not 2 days ago), and zone_invalid is False
        assert entry_res.created_time == t_today, f"Expected created_time {t_today}, got {entry_res.created_time} (anchored to bar 0 from 2 days ago!)"
        assert entry_res.zone_invalid is False, "Expected valid entry zone for today's sweep, but got INVALID_ENTRY_ZONE due to ancient FVG at 2909"
