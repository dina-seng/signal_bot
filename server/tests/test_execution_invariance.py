"""Phase 4 characterization tests: look-ahead invariance and frozen behaviour.

These lock current behaviour without changing any strategy rule (N-02/N-03/N-04).
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from app.schemas.candle import CandleCreate
from app.schemas.signal import SignalDirection
from app.schemas.structure import TrendDirection
from app.services.structure.ltf_confirmation import LTFConfirmationEngine
from replay_harness import SignalRecord, simulate_outcome
import smc_replay

BASE = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
TF = timedelta(minutes=15)


def _bar(ts, o, h, l, c, tf="15m"):
    return CandleCreate(symbol="XAU/USD", timeframe=tf, timestamp=ts,
                        open=o, high=h, low=l, close=c, volume=1.0)


def _fixture_bars(n=20):
    bars = [_bar(BASE, 2000, 2000.2, 1999.8, 2000)]
    bars.append(_bar(BASE + TF, 2000.5, 2000.7, 2000.3, 2000.6))
    bars.append(_bar(BASE + 2 * TF, 1994, 1994.5, 1993.5, 1994.2))  # stop gap -> exit
    for i in range(3, n):
        bars.append(_bar(BASE + i * TF, 1994, 1994.5, 1993.5, 1994.2))
    return bars


def _record():
    return SignalRecord(
        signal_time=BASE + TF, direction="BUY", tier=None, session=None,
        entry_mode="market", crt_entry=2000, stop_loss=1995,
        take_profit_1=2010, take_profit_2=2015, risk_price=5,
        rr_planned=3, score=70,
    )


def test_prefix_invariance_truncated_vs_full():
    full = _fixture_bars(20)
    truncated = _fixture_bars(5)
    a, b = _record(), _record()
    simulate_outcome(a, full, 0, 0.40, 8, 50)
    simulate_outcome(b, truncated, 0, 0.40, 8, 50)
    assert a.__dict__ == b.__dict__


def test_future_padding_does_not_change_outcome():
    full = _fixture_bars(5)
    padded = full + [_bar(BASE + (5 + i) * TF, 1, 10000, 0.01, 9999) for i in range(6)]
    a, b = _record(), _record()
    simulate_outcome(a, full, 0, 0.40, 8, 50)
    simulate_outcome(b, padded, 0, 0.40, 8, 50)
    assert a.__dict__ == b.__dict__


def test_ltf_legacy_default_uses_primary_close():
    """Legacy default (no ``decision_time``) still anchors the LTF window at
    the 1h close. v2 callers pass the 15m decision close instead; the corrected
    cadence is locked in ``test_strategy_floor_and_ltf_cadence.py``.
    """
    primary = [_bar(BASE, 2000, 2001, 1999, 2000, tf="1h")]  # closes at 11:00
    ltf = [_bar(BASE - (12 - i) * TF, 2000, 2000.5, 1999.5, 2000) for i in range(12)]
    engine = LTFConfirmationEngine()
    before = engine.check_ltf_confirmation("1h", TrendDirection.BULLISH, primary, ltf)
    after = engine.check_ltf_confirmation(
        "1h", TrendDirection.BULLISH, primary,
        ltf + [_bar(BASE + TF, 2000, 9999, 1, 9998)],  # opens exactly at 1h close
    )
    assert before == after


def _fake_result(direction, pa=5.0, struct_liq=5.0, total=30.0):
    bd = SimpleNamespace(
        total_score=total, price_action_score=pa, structure_score=struct_liq / 2,
        liquidity_score=struct_liq / 2, is_qualified=False,
    )
    return SimpleNamespace(
        direction=direction, score=total, score_breakdown=bd,
        metadata={}, reasons=[],
    )


def test_accepted_setup_cannot_violate_floors():
    """N-03 fixed: a floor-unqualified result can no longer be accepted.

    The frozen classifier still labels any BUY/SELL result CONFIRMED_SETUP, so
    the guard has to live in SMCStrategy itself. We stub the consensus result
    to isolate that guard from the pillar math.
    """
    from app.schemas.signal import ScoreBreakdown
    from app.services.signals.evaluators import ConsensusFilter
    from app.services.strategies.smc_strategy import SMCStrategy

    breakdown = ScoreBreakdown(
        structure_score=35.0, liquidity_score=40.0, indicators_score=0.0,
        price_action_score=0.0, total_score=70.0, is_qualified=False,
    )

    def _unqualified(self, evaluations, candidate_direction):
        return 70.0, breakdown, ["⛔ Price Action Floor Not Met"], False

    original = ConsensusFilter.synthesize
    ConsensusFilter.synthesize = _unqualified
    try:
        indicators = SimpleNamespace(
            current_price=2000.0, active_fvgs=[], recent_patterns=[],
            confluence_bias="NEUTRAL", confluence_score=0.0,
        )
        structure = SimpleNamespace(
            trend=None, trend_strength=0.0, market_state="RANGING",
            base_structure=None, latest_bos=None, latest_choch=None,
            latest_sweep=None, sr_zones=[], liquidity_pools=[],
        )
        result = SMCStrategy().analyze(
            symbol="XAU/USD", timeframe="15m", candles=[],
            indicators=indicators, structure=structure, mtf=None,
            candles_15m=None,
        )
        assert result.direction == SignalDirection.WAIT
        assert any("Floor Not Met" in r for r in result.reasons)
    finally:
        ConsensusFilter.synthesize = original


def test_fatal_conflict_gate_is_unreachable():
    """N-04: no fatal metadata -> FATAL_CONFLICT is never emitted."""
    result = _fake_result(SignalDirection.WAIT, total=50.0)
    gate = smc_replay._classify_smc(result, {"buy_fatal": False, "sell_fatal": False}, 60.0)[0]
    assert gate != "FATAL_CONFLICT"
