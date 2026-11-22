"""Baseline v2 strategy regressions: N-03 hard floors and N-02 LTF cadence.

Hermetic, deterministic fixtures. Each test fails against the Baseline v1
strategy logic and passes against the v2 logic.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.schemas.indicators import (
    ATRSnapshot,
    EMASnapshot,
    IndicatorAnalysisResponse,
    RSISnapshot,
)
from app.schemas.liquidity import (
    AdvancedStructureAnalysisResponse,
    BOSCHOCHType,
    BreakoutEvent,
    LiquidityEventType,
    LiquiditySweep,
    SupportResistanceZone,
    ZoneType,
)
from app.schemas.signal import SignalDirection
from app.schemas.structure import (
    MultiTimeframeAlignment,
    MultiTimeframeStructureResponse,
    StructureAnalysisResponse,
    TrendDirection,
)
from app.services.structure.ltf_confirmation import LTFConfirmationEngine
from app.services.strategies.smc_strategy import SMCStrategy

NOW = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)


def _high_score_no_pa_inputs():
    """Structure 35 + Liquidity 30 + PA 0 = 65 (>= 60), but PA floor unmet."""
    base = StructureAnalysisResponse(
        symbol="XAU/USD", timeframe="1h", trend=TrendDirection.BULLISH,
        trend_strength=1.0, key_support=1990.0, key_resistance=2030.0,
        total_candles=50, total_swings=6, timestamp=NOW,
    )
    structure = AdvancedStructureAnalysisResponse(
        symbol="XAU/USD", timeframe="1h", trend=TrendDirection.BULLISH,
        trend_strength=1.0, market_state="BULLISH_TREND_CONTINUATION",
        base_structure=base,
        latest_bos=BreakoutEvent(
            index=46, timestamp=NOW, event_type=BOSCHOCHType.BULLISH_BOS,
            breakout_price=2015.0, broken_swing_price=2010.0,
            broken_swing_index=40, broken_swing_timestamp=NOW,
            displacement_strength=0.9,
        ),
        latest_sweep=LiquiditySweep(
            index=45, timestamp=NOW, sweep_type=LiquidityEventType.SELL_SIDE_SWEEP,
            swept_level=1995.0, sweep_extreme=1992.0, close_price=2000.0,
            wick_ratio=0.75, pips_swept=30.0,
        ),
        sr_zones=[SupportResistanceZone(
            zone_type=ZoneType.SUPPORT, price_low=1990.0, price_high=2010.0,
            center_price=2000.0, touch_count=3, strength=1.0, is_fresh=True,
        )],
        liquidity_pools=[],
    )
    mtf = MultiTimeframeStructureResponse(
        symbol="XAU/USD", primary_timeframe="4h",
        primary_trend=TrendDirection.BULLISH,
        alignment=MultiTimeframeAlignment.BULLISH_ALIGNED,
        alignment_score=1.0, timeframes={}, summary="Bullish aligned",
    )
    indicators = IndicatorAnalysisResponse(
        symbol="XAU/USD", timeframe="1h", timestamp=NOW, current_price=2000.0,
        ema=EMASnapshot(ema_trend="NEUTRAL"),
        rsi=RSISnapshot(rsi_value=50.0, condition="NEUTRAL"),
        atr=ATRSnapshot(atr_value=5.0, atr_pips=50.0),
        divergences=[], recent_patterns=[], active_fvgs=[],
        confluence_bias="NEUTRAL", confluence_score=0.0,
    )
    return structure, mtf, indicators


def test_n03_pa_floor_blocks_acceptance():
    """A 65-pt BUY with zero price-action confirmation must not be accepted."""
    structure, mtf, indicators = _high_score_no_pa_inputs()
    result = SMCStrategy().analyze(
        symbol="XAU/USD", timeframe="1h", candles=[],
        indicators=indicators, structure=structure, mtf=mtf,
        candles_15m=None,
    )

    assert result.score_breakdown.price_action_score == 0.0
    assert result.score_breakdown.is_qualified is False
    # v1 returned BUY here; v2 must return WAIT.
    assert result.direction == SignalDirection.WAIT
    assert any("Floor Not Met" in r for r in result.reasons)


# Proven OHLC sequence: swing high at bar 7, bullish breakout at bar 12.
_LTF_OHLC = [
    (1.0980, 1.0990, 1.0970, 1.0980),
    (1.0980, 1.0990, 1.0970, 1.0980),
    (1.0980, 1.0990, 1.0970, 1.0980),
    (1.0990, 1.1000, 1.0980, 1.0990),
    (1.1000, 1.1010, 1.0990, 1.1000),
    (1.1000, 1.1030, 1.0990, 1.1020),
    (1.1020, 1.1050, 1.1010, 1.1040),
    (1.1040, 1.1120, 1.1030, 1.1100),  # swing high 1.1120
    (1.1100, 1.1110, 1.1050, 1.1060),
    (1.1060, 1.1070, 1.1020, 1.1030),
    (1.1030, 1.1050, 1.1020, 1.1040),
    (1.1040, 1.1080, 1.1030, 1.1070),
    (1.1070, 1.1160, 1.1060, 1.1150),  # breakout, opens 10:15 / closes 10:30
    (1.1150, 1.1170, 1.1140, 1.1160),
    (1.1160, 1.1200, 1.1150, 1.1180),
]


def _ltf_candles():
    from app.schemas.candle import CandleCreate
    start = datetime(2026, 1, 5, 7, 15, tzinfo=timezone.utc)
    return [
        CandleCreate(
            symbol="XAU/USD", timeframe="15m",
            timestamp=start + timedelta(minutes=15 * i),
            open=o, high=h, low=l, close=c, volume=100.0,
            is_closed=(i < 14),
        )
        for i, (o, h, l, c) in enumerate(_LTF_OHLC)
    ]


def test_n02_ltf_window_tracks_15m_decision_close():
    """LTF confirmation must see a breakout that closes at the decision time."""
    from app.schemas.candle import CandleCreate
    engine = LTFConfirmationEngine()
    primary = [CandleCreate(
        symbol="XAU/USD", timeframe="1h",
        timestamp=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
        open=1.1000, high=1.1050, low=1.0990, close=1.1040, volume=1.0,
    )]  # closes at 10:00
    ltf = _ltf_candles()

    def check(at):
        return engine.check_ltf_confirmation(
            "1h", TrendDirection.BULLISH, primary, ltf,
            max_bars_ago=5, decision_time=at,
        )

    # v1 (no decision_time -> 1h close at 10:00) cannot see the 10:15 breakout.
    assert check(None)[0] is False
    # 10:15 cutoff excludes the bar opening exactly at 10:15: no lookahead.
    assert check(datetime(2026, 1, 5, 10, 15, tzinfo=timezone.utc))[0] is False
    # 10:45 cutoff admits the breakout and the bar closing exactly at 10:45.
    confirmed, reason = check(datetime(2026, 1, 5, 10, 45, tzinfo=timezone.utc))
    assert confirmed is True
    assert "Bullish" in reason


def test_strategy_passes_15m_decision_close_to_ltf_engine():
    """SMCStrategy derives the cutoff from the last closed 15m bar."""
    structure, mtf, indicators = _high_score_no_pa_inputs()
    strategy = SMCStrategy()
    seen = {}

    def fake_check(**kwargs):
        seen["decision_time"] = kwargs.get("decision_time")
        return True, "forced confirmation"

    strategy.ltf_confirmation_engine.check_ltf_confirmation = MagicMock(side_effect=fake_check)
    strategy.analyze(
        symbol="XAU/USD", timeframe="1h", candles=[],
        indicators=indicators, structure=structure, mtf=mtf,
        candles_15m=_ltf_candles(),
    )

    assert seen["decision_time"] == datetime(2026, 1, 5, 10, 45, tzinfo=timezone.utc)
    assert strategy.ltf_confirmation_engine.check_ltf_confirmation.call_count == 2
