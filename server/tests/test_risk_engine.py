"""Risk Engine actor tests: entry-only Signal Engine, 15m structural SL, 3R TP."""

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.signal import ScoreBreakdown, SignalDirection
from app.services.strategies.base import StrategyResult
from app.services.signals.risk_engine import RiskEngine
from app.services.signals import SignalGenerator
from app.schemas.candle import CandleBase


ENTRY = 3638.19


def _swing(price, side):
    from app.schemas.structure import SwingPoint, SwingType
    return SwingPoint(index=0, timestamp=datetime(2026, 11, 24, 12, tzinfo=timezone.utc),
                      price=price, swing_type=side, bar_high=price + 0.5, bar_low=price - 0.5)


def test_buy_sl_is_nearest_15m_swing_low_and_tp_is_exactly_3r():
    from app.schemas.structure import SwingType
    levels = RiskEngine().resolve_levels(
        symbol="XAU/USD", direction=SignalDirection.BUY, entry_price=ENTRY,
        timeframe="15m",
        swings=[_swing(3600.0, SwingType.SWING_LOW), _swing(3550.0, SwingType.SWING_LOW)],
    )
    assert levels.entry_price == ENTRY
    assert levels.stop_loss == 3600.0
    assert levels.take_profit_1 == round(ENTRY + 3 * (ENTRY - 3600.0), 5)
    assert levels.take_profit_2 is None
    assert levels.rr_multiple == 3.0
    assert levels.lot_size == pytest.approx(0.01)
    assert "15m_swing_low" in levels.source


def test_sell_sl_is_nearest_15m_swing_high_and_tp_is_exactly_3r():
    from app.schemas.structure import SwingType
    levels = RiskEngine().resolve_levels(
        symbol="XAU/USD", direction=SignalDirection.SELL, entry_price=ENTRY,
        timeframe="15m",
        swings=[_swing(3685.88, SwingType.SWING_HIGH), _swing(3700.0, SwingType.SWING_HIGH)],
    )
    assert levels.entry_price == ENTRY
    assert levels.stop_loss == 3685.88
    assert levels.take_profit_1 == round(ENTRY - 3 * (3685.88 - ENTRY), 5)
    assert levels.take_profit_2 is None
    assert levels.lot_size == pytest.approx(0.01)
    assert "15m_swing_high" in levels.source


def test_missing_swing_uses_fixed_10_price_unit_gap_not_atr():
    for direction, expected_sl in (
        (SignalDirection.BUY, ENTRY - 10.0),
        (SignalDirection.SELL, ENTRY + 10.0),
    ):
        levels = RiskEngine().resolve_levels(
            symbol="XAU/USD", direction=direction, entry_price=ENTRY,
            timeframe="15m", candles=[], swings=[],
        )
        assert levels.stop_loss == pytest.approx(expected_sl)
        assert levels.take_profit_1 == pytest.approx(ENTRY + (3 * 10.0 if direction == SignalDirection.BUY else -3 * 10.0))
        assert "fixed_gap" in levels.source


def test_risk_engine_never_changes_entry_or_accepts_atr():
    levels = RiskEngine().resolve_levels(
        symbol="XAU/USD", direction="BUY", entry_price=ENTRY, timeframe="15m",
        swings=[], balance=200.0, risk_percent=5.0,
    )
    assert levels.entry_price == ENTRY
    assert levels.risk_amount_usd == pytest.approx(10.0)
    assert levels.lot_size == pytest.approx(0.01)


def test_risk_engine_rejects_non_15m_timeframe_and_bad_direction():
    with pytest.raises(ValueError):
        RiskEngine().resolve_levels(symbol="XAU/USD", direction="BUY",
                                    entry_price=ENTRY, timeframe="1h", swings=[])
    with pytest.raises(ValueError):
        RiskEngine().resolve_levels(symbol="XAU/USD", direction="HOLD",
                                    entry_price=ENTRY, timeframe="15m", swings=[])


def _candles():
    out = []
    start = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)
    for i in range(60):
        o = 3600.0 + i * 0.6
        out.append(CandleBase(symbol="XAU/USD", timeframe="15m",
                              timestamp=start + timedelta(minutes=15 * i),
                              open=o, high=o + 1.5, low=o - 1.5, close=o + 0.4,
                              volume=100.0, is_closed=True))
    return out


class _StubStrategyManager:
    def run_all_strategies(self, **kwargs):
        return [StrategyResult(
            strategy_name="AUDIT", direction=SignalDirection.BUY, score=80.0,
            reasons=[], metadata={},
            score_breakdown=ScoreBreakdown(structure_score=20.0, liquidity_score=20.0,
                                           indicators_score=0.0, price_action_score=20.0,
                                           total_score=80.0, is_qualified=True),
        )]


def test_signal_path_delegates_sl_tp_to_risk_engine():
    gen = SignalGenerator()
    gen.confluence_engine.strategy_manager = _StubStrategyManager()
    # Signal Engine no longer owns SL/TP/lot calculation.
    assert not hasattr(gen.confluence_engine, "structural_level_engine")
    assert hasattr(gen.confluence_engine, "risk_engine")
    sig = gen.evaluate_market_signal(candles_primary=_candles(), symbol="XAU/USD",
                                     timeframe="15m", account_balance=200.0,
                                     risk_percent=5.0,
                                     as_of=datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc))
    rp = sig.risk_parameters
    assert rp is not None
    assert rp.suggested_lot_size == pytest.approx(0.01)
    assert rp.take_profit_2 is None
    assert abs(rp.take_profit_1 - sig.entry_price) == pytest.approx(
        3 * abs(sig.entry_price - sig.stop_loss), abs=1e-5
    )
    assert rp.risk_amount_usd == pytest.approx(10.0)
