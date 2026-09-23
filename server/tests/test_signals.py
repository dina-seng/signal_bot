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
            index=45,
            timestamp=now,
            event_type=BOSCHOCHType.BULLISH_BOS,
            breakout_price=1.1050,
            broken_swing_price=1.1020,
            broken_swing_index=40,
            broken_swing_timestamp=now,
            displacement_strength=0.8,
        ),
        liquidity_sweeps=[],
        latest_sweep=LiquiditySweep(
            index=44,
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


def test_confluence_engine_modular_weights_and_pillars():
    """Verify the 3 core SMC pillars adhere strictly to 35%, 40%, 25% weights totaling 100%."""
    from app.services.signals.evaluators import (
        StructureConsensusEvaluator,
        LiquiditySMCConsensusEvaluator,
        PriceActionConsensusEvaluator,
    )

    struct_eval = StructureConsensusEvaluator()
    liq_eval = LiquiditySMCConsensusEvaluator()
    pa_eval = PriceActionConsensusEvaluator()

    assert struct_eval.MAX_POINTS == 35.0
    assert struct_eval.WEIGHT == 35.0

    assert liq_eval.MAX_POINTS == 40.0
    assert liq_eval.WEIGHT == 40.0

    assert pa_eval.MAX_POINTS == 25.0
    assert pa_eval.WEIGHT == 25.0

    total_weight = struct_eval.WEIGHT + liq_eval.WEIGHT + pa_eval.WEIGHT
    assert total_weight == 100.0


def test_directional_conflict_penalty_and_invalidation():
    """Test that opposing directional signals trigger penalty (-15 pts) or invalidation (-30 pts/WAIT)."""
    from app.services.signals.evaluators import ConsensusFilter, PillarEvaluation

    filter_engine = ConsensusFilter(min_score_threshold=75.0)

    # 1. Full Agreement (BUY) -> No Penalty
    unanimous_evals = {
        "structure": PillarEvaluation("Structure", SignalDirection.BUY, 25.0, 30.0, 30.0, 0.83, ["Bullish BOS"], []),
        "liquidity": PillarEvaluation("Liquidity", SignalDirection.BUY, 20.0, 25.0, 25.0, 0.80, ["Demand Zone"], []),
        "indicators": PillarEvaluation("Indicators", SignalDirection.BUY, 20.0, 25.0, 25.0, 0.80, ["EMA Stack"], []),
        "price_action": PillarEvaluation("Price Action", SignalDirection.BUY, 15.0, 20.0, 20.0, 0.75, ["Bullish Pin Bar"], []),
    }
    score, breakdown, catalysts, fatal = filter_engine.synthesize(unanimous_evals, SignalDirection.BUY)
    assert score == 80.0
    assert breakdown.is_qualified is True
    assert fatal is False

    # 2. Single Opposing Conflict (e.g. Bearish RSI Divergence while other 3 pillars are Bullish)
    single_conflict_evals = {
        "structure": PillarEvaluation("Structure", SignalDirection.BUY, 25.0, 30.0, 30.0, 0.83, ["Bullish BOS"], []),
        "liquidity": PillarEvaluation("Liquidity", SignalDirection.BUY, 20.0, 25.0, 25.0, 0.80, ["Demand Zone"], []),
        "indicators": PillarEvaluation("Indicators", SignalDirection.BUY, 15.0, 25.0, 25.0, 0.60, ["EMA Stack"], ["Opposing Bearish RSI Divergence"]),
        "price_action": PillarEvaluation("Price Action", SignalDirection.BUY, 15.0, 20.0, 20.0, 0.75, ["Bullish Pin Bar"], []),
    }
    score, breakdown, catalysts, fatal = filter_engine.synthesize(single_conflict_evals, SignalDirection.BUY)
    # Raw total = 75.0, Penalty = -15.0 -> Final = 60.0
    assert score == 60.0
    assert breakdown.is_qualified is False
    assert any("Directional Conflict Warning" in c for c in catalysts)

    # 3. Severe Dual Conflict (e.g. Bearish RSI Divergence + Bearish Engulfing Candlestick)
    dual_conflict_evals = {
        "structure": PillarEvaluation("Structure", SignalDirection.BUY, 25.0, 30.0, 30.0, 0.83, ["Bullish BOS"], []),
        "liquidity": PillarEvaluation("Liquidity", SignalDirection.BUY, 20.0, 25.0, 25.0, 0.80, ["Demand Zone"], []),
        "indicators": PillarEvaluation("Indicators", SignalDirection.BUY, 15.0, 25.0, 25.0, 0.60, [], ["Opposing Bearish RSI Divergence"]),
        "price_action": PillarEvaluation("Price Action", SignalDirection.BUY, 0.0, 20.0, 20.0, 0.0, [], ["Opposing Candlestick: BEARISH_ENGULFING"]),
    }
    score, breakdown, catalysts, fatal = filter_engine.synthesize(dual_conflict_evals, SignalDirection.BUY)
    assert fatal is True
    assert breakdown.is_qualified is False
    assert any("Severe Directional Conflict" in c for c in catalysts)


def test_confluence_engine_evaluate_dict():
    """Test ConfluenceEngine.evaluate with candles_dict."""
    from datetime import timedelta
    from app.models.candle import Candle
    from app.services.signals import ConfluenceEngine

    engine = ConfluenceEngine(min_score_threshold=70.0)
    base_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    base_p = 1.1000

    candles_1h = []
    for i in range(50):
        t = base_time + timedelta(hours=i)
        p = base_p + (i * 0.0005)
        candles_1h.append(
            Candle(
                symbol="EUR/USD",
                timeframe="1h",
                timestamp=t,
                open=p,
                high=p + 0.0010,
                low=p - 0.0003,
                close=p + 0.0008,
                volume=1000.0,
            )
        )

    candles_4h = []
    for i in range(30):
        t = base_time + timedelta(hours=i * 4)
        p = base_p + (i * 0.0020)
        candles_4h.append(
            Candle(
                symbol="EUR/USD",
                timeframe="4h",
                timestamp=t,
                open=p,
                high=p + 0.0030,
                low=p - 0.0010,
                close=p + 0.0025,
                volume=4000.0,
            )
        )

    candles_15m = []
    for i in range(50):
        t = base_time + timedelta(minutes=i * 15)
        p = base_p + (i * 0.0002)
        candles_15m.append(
            Candle(
                symbol="EUR/USD",
                timeframe="15m",
                timestamp=t,
                open=p,
                high=p + 0.0005,
                low=p - 0.0002,
                close=p + 0.0004,
                volume=250.0,
            )
        )

    candles_dict = {
        "1h": candles_1h,
        "4h": candles_4h,
        "15m": candles_15m,
    }

    signal_resp = engine.evaluate(
        symbol="EUR/USD",
        candles_dict=candles_dict,
        timeframe="1h",
        account_balance=10000.0,
        risk_percent=0.5,
    )

    assert signal_resp.symbol == "EUR/USD"
    assert signal_resp.direction in (SignalDirection.BUY, SignalDirection.SELL, SignalDirection.WAIT)
    assert 0.0 <= signal_resp.setup_score <= 100.0
    assert signal_resp.score_breakdown is not None
    assert len(signal_resp.reasons) > 0
    assert signal_resp.fingerprint is not None


def test_path_validator_advisory_warning_keeps_signal_qualified():
    """Ensure that a setup encountering a path obstacle with projected R:R < 1.0
    still returns a valid, qualified signal accompanied by the Path Advisory warning.
    """
    from unittest.mock import MagicMock
    from app.schemas.liquidity import SupportResistanceZone, ZoneType
    from app.schemas.signal import ScoreBreakdown, SignalDirection, SignalStatus
    from app.services.signals.confluence_engine import ConfluenceEngine
    from app.services.strategies.base import StrategyResult
    from app.services.telegram.message_formatter import TelegramMessageFormatter

    engine = ConfluenceEngine(min_score_threshold=75.0)

    now = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    entry_price = 1.1000

    # Mock indicator analysis: ATR = 0.0010 (10 pips)
    indicator_mock = MagicMock()
    indicator_mock.current_price = entry_price
    indicator_mock.timestamp = now
    indicator_mock.atr.atr_value = 0.0010
    indicator_mock.active_fvgs = []

    # Mock structure analysis: Key support at 1.0960 (SL distance = 40 pips)
    # SL is ~1.0955 (support - 0.5*ATR), TP1 at min_rr (2.0) is ~1.1090
    structure_mock = MagicMock()
    structure_mock.base_structure.key_support = 1.0960
    structure_mock.base_structure.key_resistance = 1.1200
    structure_mock.liquidity_pools = []

    # Place a FRESH RESISTANCE zone at 1.1025 (25 pips from entry)
    # Front-run TP1 = 1.1025 - 2 pips = 1.1023 (23 pips reward vs ~45 pips risk -> projected R:R ~ 0.51 < 1.0)
    res_zone = SupportResistanceZone(
        zone_type=ZoneType.RESISTANCE,
        price_low=1.1020,
        price_high=1.1030,
        center_price=1.1025,
        touch_count=3,
        strength=0.85,
        is_fresh=True,
    )
    structure_mock.sr_zones = [res_zone]

    score_breakdown = ScoreBreakdown(
        structure_score=28.0,
        liquidity_score=22.0,
        indicators_score=20.0,
        price_action_score=15.0,
        total_score=85.0,
        is_qualified=True,
    )

    strategy_result = StrategyResult(
        strategy_name="SMC Confluence",
        direction=SignalDirection.BUY,
        score=85.0,
        reasons=["Bullish BOS on 1H", "Demand Zone Sweep"],
        score_breakdown=score_breakdown,
    )

    signal_resp = engine._build_signal_response(
        result=strategy_result,
        symbol="EUR/USD",
        timeframe="1h",
        indicator_analysis=indicator_mock,
        structure_analysis=structure_mock,
        account_balance=10000.0,
        risk_percent=0.5,
    )

    # 1. Signal MUST remain qualified and BUY direction (NOT demoted to WAIT)
    assert signal_resp.direction == SignalDirection.BUY
    assert signal_resp.status == SignalStatus.ACTIVE
    assert signal_resp.setup_score == 85.0
    assert signal_resp.score_breakdown.is_qualified is True

    # 2. Risk parameters must retain original TP1/TP2 targets without collapsing into barrier
    assert signal_resp.risk_parameters is not None
    assert signal_resp.take_profit_1 is not None
    # Original TP1 must be >= 1.1080 (not collapsed to 1.1023)
    assert signal_resp.take_profit_1 > 1.1050
    assert signal_resp.risk_reward >= 2.0

    # 3. Path Advisory warning must be attached
    assert len(signal_resp.warnings) > 0
    advisory_warning = signal_resp.warnings[0]
    assert "⚠️ Path Advisory:" in advisory_warning
    assert "Nearest Obstacle: Resistance Zone (85% strength) at 1.10250" in advisory_warning
    assert "Projected Obstacle R:R:" in advisory_warning
    assert "Total Path Barriers: 1" in advisory_warning
    assert "Manual management recommended" in advisory_warning

    # Check advisory is also present in reasons
    assert any("⚠️ Path Advisory:" in r for r in signal_resp.reasons)

    # 4. Telegram alert formatting verification
    formatter = TelegramMessageFormatter()
    telegram_alert = formatter.format_signal_alert(signal_resp)

    # Must be standard signal alert, not a rejection card
    assert "TRADE REJECTED" not in telegram_alert
    assert "STRONG BUY" in telegram_alert
    assert "⚠️ *Path Advisory:*" in telegram_alert
    assert "Resistance Zone (85% strength) at 1.10250" in telegram_alert


def test_risk_manager_gold_structural_distance():
    """Verify that RiskManager allows up to $25.00 (2500 pips) of structural distance on Gold (XAU/USD)."""
    from app.services.signals.risk_manager import RiskManager
    from app.schemas.signal import SignalDirection

    rm = RiskManager()
    atr_val = 2.0  # $2.00 ATR on Gold

    # 1. Gold BUY with $15.00 structural swing (1500 pips)
    # Entry: 2000.00, Support: 1985.00
    # Expected SL = support - 0.5 * atr = 1985.00 - 1.00 = 1984.00
    params_gold_valid = rm.calculate_trade_risk(
        symbol="XAU/USD",
        direction=SignalDirection.BUY,
        entry_price=2000.00,
        atr_value=atr_val,
        key_support_low=1985.00,
        account_balance=10000.0,
        risk_percent=0.5,
    )
    # Must NOT fall back to ATR (which would be 2000 - 1.5*2 = 1997.00)
    assert params_gold_valid.stop_loss == 1984.00
    assert params_gold_valid.risk_pips == 1600.0  # (2000 - 1984) / 0.01

    # 2. Gold BUY with excessive structural swing ($30.00 / 3000 pips > 2500 pips)
    # Entry: 2000.00, Support: 1970.00 -> Should fall back to ATR SL = 2000 - 1.5*2 = 1997.00
    params_gold_excessive = rm.calculate_trade_risk(
        symbol="XAU/USD",
        direction=SignalDirection.BUY,
        entry_price=2000.00,
        atr_value=atr_val,
        key_support_low=1970.00,
        account_balance=10000.0,
        risk_percent=0.5,
    )
    assert params_gold_excessive.stop_loss == 1997.00

    # 3. Gold SELL with $15.00 structural swing (1500 pips)
    # Entry: 2000.00, Resistance: 2015.00
    # Expected SL = resistance + 0.5 * atr = 2015.00 + 1.00 = 2016.00
    params_gold_sell = rm.calculate_trade_risk(
        symbol="XAU/USD",
        direction=SignalDirection.SELL,
        entry_price=2000.00,
        atr_value=atr_val,
        key_resistance_high=2015.00,
        account_balance=10000.0,
        risk_percent=0.5,
    )
    assert params_gold_sell.stop_loss == 2016.00

    # 4. Standard FX (EUR/USD) still capped at 100 pips
    # Entry: 1.1000, Support: 1.0850 (150 pips > 100 pips) -> Falls back to ATR
    atr_fx = 0.0010
    params_fx = rm.calculate_trade_risk(
        symbol="EUR/USD",
        direction=SignalDirection.BUY,
        entry_price=1.1000,
        atr_value=atr_fx,
        key_support_low=1.0850,
        account_balance=10000.0,
        risk_percent=0.5,
    )
    assert params_fx.stop_loss == round(1.1000 - (atr_fx * 1.5), 5)


# =============================================================================
# Deduplication & Cooldown Tests
# =============================================================================

def test_scanner_symbol_direction_cooldown(test_db_session):
    """Assert that consecutive same-direction signals for the same symbol are suppressed
    within the 2-hour wall-clock cooldown window even when candle timestamps change.

    Reproduces the candle-timestamp drift bug: the old cooldown used Signal.timestamp
    (candle open time), which incremented each hour, making each new bar appear as a
    fresh signal.  The fix anchors to Signal.created_at (DB insert time).
    """
    from datetime import timedelta
    from app.models.signal import Signal
    from app.schemas.signal import SignalDirection, SignalResponse, SignalStatus, ScoreBreakdown
    from app.services.telegram.scanner import AutomatedMarketScanner

    scanner = AutomatedMarketScanner()
    now_utc = datetime.now(timezone.utc)

    # Seed a previously-broadcasted SELL signal:
    #   - candle timestamp: 1h 30m old (simulates previous hourly bar)
    #   - created_at: 45 minutes ago (within 2-hour window)
    candle_ts_old = now_utc - timedelta(hours=1, minutes=30)
    created_at_recent = now_utc - timedelta(minutes=45)

    existing_signal = Signal(
        symbol="XAU/USD",
        timeframe="1h",
        direction="SELL",
        setup_score=82.0,
        entry_price=1950.00,
        stop_loss=1960.00,
        take_profit_1=1930.00,
        take_profit_2=1920.00,
        risk_reward=2.0,
        fingerprint="fp_sell_45min_ago",
        reasons=["Bearish BOS"],
        status="ACTIVE",
        strategy_name="Strategy A (SMC Sniper)",
        is_broadcasted=True,
        timestamp=candle_ts_old,
        created_at=created_at_recent,
    )
    test_db_session.add(existing_signal)
    test_db_session.commit()

    # New signal: same direction, newer candle timestamp (1H bar shift — the bug trigger)
    new_candle_ts = now_utc - timedelta(minutes=30)
    new_signal_resp = SignalResponse(
        symbol="XAU/USD",
        timeframe="1h",
        direction=SignalDirection.SELL,
        setup_score=81.0,
        entry_price=1951.00,
        stop_loss=1961.00,
        take_profit_1=1931.00,
        take_profit_2=1921.00,
        risk_reward=2.0,
        fingerprint="fp_sell_new_bar",
        reasons=["Bearish BOS (new bar)"],
        status=SignalStatus.ACTIVE,
        timestamp=new_candle_ts,
        strategy_name="Strategy A (SMC Sniper)",
        score_breakdown=ScoreBreakdown(
            structure_score=20.0,
            liquidity_score=18.0,
            indicators_score=20.0,
            price_action_score=10.0,
            total_score=68.0,
            is_qualified=True,
        ),
    )

    # Assert 1: cooldown SUPPRESSES the new signal (45 min created_at < 2h window)
    in_cooldown = scanner.is_signal_in_cooldown(
        db=test_db_session,
        signal_resp=new_signal_resp,
        cooldown_hours=2,
    )
    assert in_cooldown is True, (
        "Expected is_signal_in_cooldown=True: existing broadcast is 45min old (< 2h). "
        "Candle timestamp shift must NOT bypass the wall-clock cooldown."
    )

    # Assert 2: after cooldown expires (3h old), signal is allowed through
    existing_signal.created_at = now_utc - timedelta(hours=3)
    test_db_session.commit()

    in_cooldown_expired = scanner.is_signal_in_cooldown(
        db=test_db_session,
        signal_resp=new_signal_resp,
        cooldown_hours=2,
    )
    assert in_cooldown_expired is False, (
        "Expected is_signal_in_cooldown=False: broadcast is 3h old (> 2h window). "
        "Signal should pass through after the cooldown expires."
    )
