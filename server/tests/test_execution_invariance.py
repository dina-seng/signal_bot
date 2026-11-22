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


def test_ltf_freeze_at_primary_close():
    """N-02: a 15m bar opening at the 1h close cannot change the LTF verdict."""
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


def test_accepted_setup_can_violate_floors():
    """N-03: floors are metadata, not vetoes; accepted BUY stays accepted."""
    result = _fake_result(SignalDirection.BUY, pa=1.0, struct_liq=1.0, total=70.0)
    gate = smc_replay._classify_smc(result, {}, 60.0)[0]
    assert gate == smc_replay.CONFIRMED_STATE


def test_fatal_conflict_gate_is_unreachable():
    """N-04: no fatal metadata -> FATAL_CONFLICT is never emitted."""
    result = _fake_result(SignalDirection.WAIT, total=50.0)
    gate = smc_replay._classify_smc(result, {"buy_fatal": False, "sell_fatal": False}, 60.0)[0]
    assert gate != "FATAL_CONFLICT"
