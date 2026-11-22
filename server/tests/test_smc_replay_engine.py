"""Canonical SMC execution-engine regression tests (Baseline v1, Option B).

These fixtures encode the approved execution contract:
  - signal at a closed 15m bar; fill at the NEXT eligible 15m bar open;
  - SL/TP geometry fixed at signal time (never re-derived from the fill);
  - planned risk is the only R denominator;
  - deterministic void outcomes for invalid entries;
  - in-trade gap fills at executable market prices;
  - one flat round-trip cost, deducted once.

Every test is hermetic (in-memory bars + SignalRecord); no DB, no I/O.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from app.schemas.candle import CandleCreate
from replay_harness import SignalRecord, simulate_outcome

BASE = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)  # Monday
TF = timedelta(minutes=15)


def _bar(ts, o, h, l, c):
    return CandleCreate(
        symbol="XAU/USD", timeframe="15m", timestamp=ts,
        open=o, high=h, low=l, close=c, volume=100.0, source="twelvedata",
    )


def _series(spec, start=BASE):
    return [_bar(start + i * TF, *ohlc) for i, ohlc in enumerate(spec)]


def _neutral(n):
    return [(2000.0, 2000.2, 1999.8, 2000.0) for _ in range(n)]


def _buy_record(signal_index=0, signal_price=2000.0, sl=1995.0, tp1=2010.0, tp2=2015.0):
    return SignalRecord(
        signal_time=BASE + signal_index * TF + TF,
        direction="BUY",
        tier=None,
        session=None,
        entry_mode="market",
        crt_entry=signal_price,
        stop_loss=sl,
        take_profit_1=tp1,
        take_profit_2=tp2,
        risk_price=abs(signal_price - sl),
        rr_planned=3.0,
        score=70.0,
    )


def _sell_record(signal_index=0, signal_price=2000.0, sl=2005.0, tp1=1990.0, tp2=1985.0):
    return SignalRecord(
        signal_time=BASE + signal_index * TF + TF,
        direction="SELL", tier=None, session=None, entry_mode="market",
        crt_entry=signal_price, stop_loss=sl, take_profit_1=tp1, take_profit_2=tp2,
        risk_price=abs(sl - signal_price), rr_planned=3.0, score=70.0,
    )


def _run(spec, record=None, spread=0.40, max_hold_bars=50, session_ids=None, entry_mode="market"):
    bars = _series(spec)
    record = record or _buy_record()
    record.entry_mode = entry_mode
    simulate_outcome(
        record, bars=bars, signal_index=0, spread=spread,
        expiry_bars=8, max_hold_bars=max_hold_bars,
        session_ids=session_ids,
    )
    return record, bars


# --- Entry timing ---------------------------------------------------------

def test_market_entry_fills_at_next_bar_open():
    spec = _neutral(6)
    spec[1] = (2000.5, 2000.7, 2000.3, 2000.6)
    rec, bars = _run(spec)
    assert rec.filled is True
    assert rec.fill_price == 2000.5
    assert rec.fill_time == bars[1].timestamp
    assert rec.fill_time == rec.entry_time


def test_signal_bar_low_not_managed_before_entry():
    """BT-004: signal bar wick below SL must not stop a not-yet-active trade."""
    spec = _neutral(6)
    spec[0] = (2000.0, 2100.0, 1900.0, 2000.0)  # huge pre-entry range
    spec[1] = (2000.5, 2000.7, 2000.3, 2000.6)
    rec, _ = _run(spec)
    assert rec.filled is True
    assert rec.exit_reason != "STOP_LOSS"
    assert rec.exit_reason == "END_OF_DATA"


def test_signal_bar_high_not_managed_before_entry():
    spec = _neutral(6)
    spec[0] = (2000.0, 2100.0, 1900.0, 2000.0)  # pre-entry high above TP2
    spec[1] = (2000.5, 2000.7, 2000.3, 2000.6)
    rec, _ = _run(spec)
    assert rec.exit_reason != "TP2"
    assert rec.exit_reason == "END_OF_DATA"


def test_no_next_bar_is_end_of_data_void():
    rec, _ = _run(_neutral(1))
    assert rec.filled is False
    assert rec.exit_reason == "NO_FILL_END_OF_DATA"
    assert rec.r_multiple is None


# --- Void entry rules -----------------------------------------------------

def test_entry_beyond_sl_voids():
    spec = _neutral(6)
    spec[1] = (1994.0, 1994.3, 1993.7, 1994.1)
    rec, _ = _run(spec)
    assert rec.filled is False
    assert rec.exit_reason == "VOID_ENTRY_BEYOND_SL"
    assert rec.r_multiple is None
    assert rec.spread_paid == 0.0


def test_entry_beyond_tp_voids():
    spec = _neutral(6)
    spec[1] = (2016.0, 2016.3, 2015.7, 2016.1)
    rec, _ = _run(spec)
    assert rec.filled is False
    assert rec.exit_reason == "VOID_ENTRY_BEYOND_TP"
    assert rec.r_multiple is None


def test_session_boundary_voids():
    spec = _neutral(6)
    spec[1] = (2000.5, 2000.7, 2000.3, 2000.6)
    rec, _ = _run(spec, session_ids=[0, 1, 1, 1, 1, 1])
    assert rec.filled is False
    assert rec.exit_reason == "NO_FILL_SESSION_BOUNDARY"


def test_missing_intraday_bar_voids():
    bars = _series(_neutral(6))
    bars[1] = _bar(bars[0].timestamp + 2 * TF, 2000.5, 2000.7, 2000.3, 2000.6)
    rec = _buy_record()
    simulate_outcome(
        rec, bars=bars, signal_index=0, spread=0.40,
        expiry_bars=8, max_hold_bars=50, session_ids=[0, 0, 0, 0, 0, 0],
    )
    assert rec.filled is False
    assert rec.exit_reason == "NO_FILL_MISSING_NEXT_BAR"


# --- In-trade gap fills ---------------------------------------------------

def test_intrade_stop_gap_fills_at_open():
    spec = _neutral(6)
    spec[1] = (2000.5, 2000.7, 2000.3, 2000.6)
    spec[2] = (1994.0, 1994.5, 1993.5, 1994.2)
    rec, _ = _run(spec)
    assert rec.exit_reason == "STOP_LOSS"
    assert rec.actual_exit_fill == 1994.0
    assert rec.intended_stop == 1995.0
    assert rec.r_multiple == pytest.approx(-1.38)


def test_intrade_tp1_gap_fills_at_open():
    spec = _neutral(6)
    spec[1] = (2000.5, 2000.7, 2000.3, 2000.6)
    spec[2] = (2012.0, 2013.0, 2011.0, 2012.5)  # gaps through TP1, below TP2
    spec[3] = (2012.5, 2016.0, 2011.5, 2015.5)  # reaches TP2
    rec, _ = _run(spec)
    assert rec.exit_reason == "TP2"
    assert rec.r_multiple == pytest.approx(2.52)


def test_same_bar_sl_and_tp_resolves_sl_first():
    spec = _neutral(6)
    spec[1] = (2000.5, 2016.0, 1994.0, 2000.6)  # touches SL and TP in entry bar
    rec, _ = _run(spec)
    assert rec.exit_reason == "STOP_LOSS"


# --- Geometry immutability / R denominator --------------------------------

@pytest.mark.parametrize("fill", [1999.0, 2000.5, 2001.0])
def test_geometry_immutable_across_entry_fills(fill):
    spec = _neutral(6)
    spec[1] = (fill, fill + 0.2, fill - 0.2, fill + 0.1)
    rec, _ = _run(spec)
    assert rec.crt_entry == 2000.0
    assert rec.stop_loss == 1995.0
    assert rec.take_profit_1 == 2010.0
    assert rec.take_profit_2 == 2015.0
    assert rec.risk_price == 5.0


def test_planned_and_actual_risk_recorded_separately():
    spec = _neutral(6)
    spec[1] = (2001.0, 2001.2, 2000.8, 2001.1)  # adverse entry gap, still valid
    spec[2] = (1998.0, 1998.3, 1995.0, 1995.2)  # retest of SL, no further gap
    rec, _ = _run(spec)
    assert rec.planned_risk == 5.0
    assert rec.actual_risk_distance == pytest.approx(6.0)
    assert rec.r_multiple == pytest.approx(-1.28)  # -6.00 - 0.40 over 5.00


def test_priced_unit_pnl_and_cost_recorded_once():
    spec = _neutral(6)
    spec[1] = (2000.5, 2000.7, 2000.3, 2000.6)
    for i in range(2, 6):  # flat after entry -> zero gross P&L
        spec[i] = (2000.5, 2000.6, 2000.4, 2000.5)
    rec, _ = _run(spec)
    assert rec.spread_paid == 0.40
    assert rec.price_unit_realized_pnl == pytest.approx(0.0)  # gross, before cost
    assert rec.r_multiple == pytest.approx(-0.08)  # (0.00 - 0.40) / 5.00
    assert rec.monetary_realized_loss is None


# --- Timestamps and determinism ------------------------------------------

def test_signal_and_execution_timestamps_distinct_and_holding_non_negative():
    spec = _neutral(6)
    spec[1] = (2000.5, 2000.7, 2000.3, 2000.6)
    rec, bars = _run(spec)
    assert rec.signal_time == bars[0].timestamp + TF
    assert rec.entry_time == bars[1].timestamp
    assert rec.exit_time >= rec.entry_time
    assert rec.bars_held >= 0


def test_replay_is_deterministic():
    spec = _neutral(6)
    spec[1] = (2000.5, 2000.7, 2000.3, 2000.6)
    a, _ = _run(spec)
    b, _ = _run(spec)
    assert a.__dict__ == b.__dict__


# --- Limit-fill-then-stop (BT-002) ---------------------------------------

def test_limit_fill_then_stop_not_voided():
    spec = _neutral(6)
    spec[1] = (100.0, 100.5, 97.0, 100.2)  # trades through limit 100 then stop 99
    rec = _buy_record(signal_price=100.0, sl=99.0, tp1=102.0, tp2=103.0)
    rec, _ = _run(spec, record=rec, entry_mode="limit_zone")
    assert rec.filled is True
    assert rec.exit_reason == "STOP_LOSS"
    assert rec.r_multiple == pytest.approx(-1.4)


# --- SELL mirror ----------------------------------------------------------

def test_sell_normal_tp2_uses_planned_risk():
    spec = _neutral(6)
    spec[0] = (2000.0, 2000.2, 1999.8, 2000.0)
    spec[1] = (1999.5, 1999.7, 1999.3, 1999.4)
    spec[2] = (1999.0, 1999.2, 1989.0, 1989.5)   # TP1
    spec[3] = (1989.0, 1989.2, 1984.0, 1984.5)   # TP2
    rec, _ = _run(spec, record=_sell_record())
    assert rec.fill_price == 1999.5
    assert rec.planned_risk == 5.0
    assert rec.actual_risk_distance == pytest.approx(5.5)
    assert rec.exit_reason == "TP2"
    assert rec.r_multiple == pytest.approx(2.32)


def test_sell_intrade_stop_gap_fills_at_open():
    spec = _neutral(6)
    spec[0] = (2000.0, 2000.2, 1999.8, 2000.0)
    spec[1] = (1999.5, 1999.7, 1999.3, 1999.4)
    spec[2] = (2006.0, 2006.5, 2005.5, 2006.2)   # gaps above SL 2005
    rec, _ = _run(spec, record=_sell_record())
    assert rec.exit_reason == "STOP_LOSS"
    assert rec.actual_exit_fill == 2006.0
    assert rec.r_multiple == pytest.approx(-1.38)


def test_void_record_serializes_without_fabricated_exit_time():
    from replay_harness import _signal_to_dict
    spec = _neutral(6)
    spec[1] = (1994.0, 1994.3, 1993.7, 1994.1)
    rec, _ = _run(spec)
    d = _signal_to_dict(rec)
    assert d["exit_reason"] == "VOID_ENTRY_BEYOND_SL"
    assert d["void_reason"] == "VOID_ENTRY_BEYOND_SL"
    assert d["exit_time"] is None
    assert d["r_multiple"] is None
    assert d["execution_convention_version"] == "optionB-v1"
