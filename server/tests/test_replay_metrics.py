"""Baseline v1 metrics-bucket regression tests.

Void entries must be a distinct bucket: they are never merged into no-fills,
never counted as 0R losses, and never change the R denominator.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from replay_harness import SignalRecord, compute_metrics, trade_metrics


def _trade(filled=True, r=None, void=None):
    return {
        "filled": filled,
        "r_multiple": r,
        "void_reason": void,
        "exit_time": None if void else "2026-01-05T10:15:00+00:00",
    }


def test_trade_metrics_void_bucket_is_separate():
    trades = [
        _trade(True, 1.0),
        _trade(True, -0.5),
        _trade(False, None, "VOID_ENTRY_BEYOND_SL"),
        _trade(False, None, "VOID_ENTRY_BEYOND_TP"),
        _trade(False, None),  # legacy no-fill, no void_reason
    ]
    m = trade_metrics(trades)
    assert m["n_candidates"] == 5
    assert m["n_filled"] == 2
    assert m["n_void_entry"] == 2
    assert m["n_no_fill"] == 1
    assert m["void_rate"] == pytest.approx(40.0)
    assert m["void_reasons"] == {"VOID_ENTRY_BEYOND_SL": 1, "VOID_ENTRY_BEYOND_TP": 1}
    assert m["expectancy"] == pytest.approx(0.25)  # filled only


def test_compute_metrics_separates_voids():
    base = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    signals = [
        SignalRecord(signal_time=base, direction="BUY", tier=None, session=None,
                     entry_mode="market", crt_entry=100, stop_loss=99,
                     take_profit_1=102, take_profit_2=103, risk_price=1,
                     rr_planned=3, score=70, filled=True, r_multiple=1.0),
        SignalRecord(signal_time=base + timedelta(minutes=15), direction="BUY", tier=None,
                     session=None, entry_mode="market", crt_entry=100, stop_loss=99,
                     take_profit_1=102, take_profit_2=103, risk_price=1, rr_planned=3,
                     score=70, filled=False, void_reason="VOID_ENTRY_BEYOND_SL"),
    ]
    m = compute_metrics(signals)
    assert m.n_signals == 2
    assert m.n_filled == 1
    assert m.n_void_entry == 1
    assert m.n_no_fill == 0
    assert m.avg_r == pytest.approx(1.0)
    assert m.void_reasons == {"VOID_ENTRY_BEYOND_SL": 1}


def test_void_does_not_change_r_denominator():
    """Planned risk stays 5.00 for a gap entry; actual distance is recorded apart."""
    import replay_harness as rh
    from app.schemas.candle import CandleCreate

    def bar(ts, o, h, l, c):
        return CandleCreate(symbol="XAU/USD", timeframe="15m", timestamp=ts,
                            open=o, high=h, low=l, close=c, volume=1.0)

    base = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    bars = [
        bar(base, 2000, 2000.2, 1999.8, 2000),
        bar(base + timedelta(minutes=15), 2001, 2001.2, 2000.8, 2001),
        bar(base + timedelta(minutes=30), 1998, 1998.3, 1995, 1995.2),
    ]
    rec = SignalRecord(signal_time=base + timedelta(minutes=15), direction="BUY",
                       tier=None, session=None, entry_mode="market", crt_entry=2000,
                       stop_loss=1995, take_profit_1=2010, take_profit_2=2015,
                       risk_price=5, rr_planned=3, score=70)
    rh.simulate_outcome(rec, bars, 0, 0.40, 8, 50)
    assert rec.planned_risk == 5.0
    assert rec.actual_risk_distance == pytest.approx(6.0)
    assert rec.r_multiple == pytest.approx(-1.28)
    assert rec.gap_risk_divergence is True
