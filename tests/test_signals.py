"""Unit tests for Risk Management, Multi-Pillar Scoring, and Signal Generation."""

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
    BOSCHOCHType,
    BreakoutEvent,
    LiquidityEventType,
    LiquiditySweep,
)
from app.schemas.news import NewsBlackoutCheckResponse
from app.schemas.signal import SignalDirection, SignalStatus
from app.schemas.structure import StructureAnalysisResponse, TrendDirection
from app.services.signals.risk_manager import RiskManager
from app.services.signals.scoring_engine import SignalScoringEngine
from app.services.signals.signal_generator import SignalGenerator


def test_risk_manager_buy_and_sell_calculations():
    """Test RiskManager SL, TP1, TP2, R:R, and lot sizing."""
    rm = RiskManager()

    # 1. BUY Test
    risk_buy = rm.calculate_trade_risk(
        symbol="EUR/USD",
        direction=SignalDirection.BUY,
        entry_price=1.1000,
        atr_value=0.0020,
        key_support_low=1.0960,
        account_balance=10000.0,
        risk_percent=0.5,
        min_rr=2.0,
    )
    assert risk_buy.entry_price == 1.1000
    assert risk_buy.stop_loss == 1.0950
    assert risk_buy.take_profit_1 == 1.1100
    assert risk_buy.take_profit_2 == 1.1150
    assert risk_buy.risk_pips == 50.0
    assert risk_buy.reward_pips_tp1 == 100.0
    assert risk_buy.risk_reward_tp1 == 2.0
    assert risk_buy.risk_amount_usd == 50.0
    assert risk_buy.suggested_lot_size == 0.10

    # 2. SELL Test
    risk_sell = rm.calculate_trade_risk(
        symbol="EUR/USD",
        direction=SignalDirection.SELL,
        entry_price=1.1000,
        atr_value=0.0020,
        key_resistance_high=1.1040,
        account_balance=10000.0,
        risk_percent=0.5,
    )
    assert risk_sell.entry_price == 1.1000
    assert risk_sell.stop_loss == 1.1050
    assert risk_sell.take_profit_1 == 1.0900
    assert risk_sell.take_profit_2 == 1.0850
    assert risk_sell.risk_reward_tp1 == 2.0
    assert risk_sell.suggested_lot_size == 0.10


def test_scoring_engine_high_confluence_buy():
    """Test SignalScoringEngine generating a high score for a perfect bullish setup."""
    engine = SignalScoringEngine(min_score_threshold=75.0)
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

    base_struct = StructureAnalysisResponse(
        symbol="EUR/USD",
        timeframe="1h",
        timestamp=now,
        trend=TrendDirection.BULLISH,
        trend_strength=0.85,
        total_candles=50,
        total_swings=0,
        swings=[],
        key_support=1.0965,
        key_resistance=1.1080,
    )


    structure = AdvancedStructureAnalysisResponse(
        symbol="EUR/USD",
        timeframe="1h",
        trend=TrendDirection.BULLISH,
        trend_strength=0.85,
        market_state="BULLISH_TREND_CONTINUATION",
        bos_events=[],
        choch_events=[],
        latest_bos=BreakoutEvent(
            index=10,
            timestamp=now,
            event_type=BOSCHOCHType.BULLISH_BOS,
            breakout_price=1.1050,
            broken_swing_price=1.1020,
            broken_swing_index=5,
            broken_swing_timestamp=now,
            displacement_strength=0.8,
        ),
        liquidity_sweeps=[],
        latest_sweep=LiquiditySweep(
            index=8,
            timestamp=now,
            sweep_type=LiquidityEventType.SELL_SIDE_SWEEP,
            swept_level=1.0980,
            sweep_extreme=1.0965,
            close_price=1.1000,
            wick_ratio=0.7,
            pips_swept=1.5,
        ),
        liquidity_pools=[],
        sr_zones=[],
        base_structure=base_struct,
    )

    indicators = IndicatorAnalysisResponse(
        symbol="EUR/USD",
        timeframe="1h",
        timestamp=now,
        current_price=1.1050,
        ema=EMASnapshot(ema_trend="BULLISH_STACK", price_vs_ema200="ABOVE"),
        rsi=RSISnapshot(rsi_value=58.0, condition="BULLISH_ZONE"),
        atr=ATRSnapshot(atr_value=0.0020, atr_pips=20.0),
        divergences=[],
        recent_patterns=[
            PriceActionPattern(
                index=10,
                timestamp=now,
                pattern_type=PatternType.BULLISH_PIN_BAR,
                confidence=1.0,
                description="Bullish Pin Bar",
            )
        ],
        active_fvgs=[],
        confluence_bias="STRONG_BULLISH",
        confluence_score=75.0,
    )

    from app.schemas.structure import MultiTimeframeAlignment, MultiTimeframeStructureResponse

    mtf_mock = MultiTimeframeStructureResponse(
        symbol="EUR/USD",
        primary_timeframe="4h",
        primary_trend=TrendDirection.BULLISH,
        alignment=MultiTimeframeAlignment.BULLISH_ALIGNED,
        alignment_score=0.9,
        timeframes={"4h": base_struct, "1h": base_struct, "15m": base_struct},
        summary="All timeframes Bullish Aligned",
    )


    direction, score, breakdown, reasons = engine.evaluate_setup(
        symbol="EUR/USD",
        timeframe="1h",
        structure=structure,
        indicators=indicators,
        mtf=mtf_mock,
    )

    assert direction == SignalDirection.BUY
    assert score >= 75.0

    assert breakdown.is_qualified is True
    assert breakdown.structure_score > 0
    assert breakdown.liquidity_score > 0
    assert breakdown.indicators_score > 0
    assert breakdown.price_action_score > 0


def test_scoring_engine_news_blackout_rejection():
    """Test that active news blackout forces WAIT and 0 score."""
    engine = SignalScoringEngine(min_score_threshold=75.0)
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

    base_struct = StructureAnalysisResponse(
        symbol="EUR/USD",
        timeframe="1h",
        timestamp=now,
        trend=TrendDirection.BULLISH,
        trend_strength=0.9,
        total_candles=50,
        total_swings=0,
        swings=[],
    )


    structure = AdvancedStructureAnalysisResponse(
        symbol="EUR/USD",
        timeframe="1h",
        trend=TrendDirection.BULLISH,
        trend_strength=0.9,
        market_state="BULLISH_TREND_CONTINUATION",
        bos_events=[],
        choch_events=[],
        liquidity_sweeps=[],
        liquidity_pools=[],
        sr_zones=[],
        base_structure=base_struct,
    )

    indicators = IndicatorAnalysisResponse(
        symbol="EUR/USD",
        timeframe="1h",
        timestamp=now,
        current_price=1.1050,
        ema=EMASnapshot(ema_trend="BULLISH_STACK"),
        rsi=RSISnapshot(rsi_value=60.0),
        atr=ATRSnapshot(atr_value=0.0020),
        confluence_bias="STRONG_BULLISH",
        confluence_score=80.0,
    )

    news_blackout = NewsBlackoutCheckResponse(
        symbol="EUR/USD",
        checked_time=now,
        is_blackout=True,
        trading_allowed=False,
        reason="TRADING BLOCKED: USD Non-Farm Payrolls imminent",
    )

    direction, score, breakdown, reasons = engine.evaluate_setup(
        symbol="EUR/USD",
        timeframe="1h",
        structure=structure,
        indicators=indicators,
        news_check=news_blackout,
    )

    assert direction == SignalDirection.WAIT
    assert score == 0.0
    assert breakdown.is_qualified is False
    assert any("NEWS BLACKOUT ACTIVE" in r for r in reasons)


def test_signal_generator_fingerprint_and_persistence(test_db_session):
    """Test SignalGenerator fingerprint generation and DB persistence."""
    generator = SignalGenerator()
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

    fp1 = generator.generate_fingerprint(
        symbol="EUR/USD",
        timeframe="1h",
        direction=SignalDirection.BUY,
        entry_price=1.1000,
        stop_loss=1.0950,
        timestamp=now,
    )
    fp2 = generator.generate_fingerprint(
        symbol="EUR/USD",
        timeframe="1h",
        direction=SignalDirection.BUY,
        entry_price=1.1000,
        stop_loss=1.0950,
        timestamp=now,
    )
    assert fp1 == fp2
    assert len(fp1) == 64
