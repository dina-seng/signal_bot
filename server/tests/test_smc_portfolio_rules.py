"""Baseline v1 portfolio-loader and verification-gate regression tests."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from app.schemas.candle import CandleCreate
import smc_portfolio_2025 as pf

BASE = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
TF = timedelta(minutes=15)


def _checkpoint_records():
    valid = {
        "decision_time": (BASE + TF).isoformat(),
        "month": "2026-01",
        "split": "test",
        "score": 70.0,
        "opportunity_key": "XAU/USD_1h_BUY_key1",
        "accepted": True,
        "accepted_trade": {
            "direction": "BUY", "crt_entry": 2000.0, "stop_loss": 1995.0,
            "take_profit_1": 2010.0, "take_profit_2": 2015.0,
            "risk_price": 5.0, "rr_planned": 3.0, "r_multiple": 2.0,
            "exit_reason": "TP2", "exit_time": (BASE + 4 * TF).isoformat(),
            "bars_held": 3, "filled": True,
        },
    }
    void = {
        "decision_time": (BASE + 2 * TF).isoformat(),
        "month": "2026-01",
        "split": "test",
        "score": 68.0,
        "opportunity_key": "XAU/USD_1h_BUY_key2",
        "accepted": True,
        "accepted_trade": {
            "direction": "BUY", "crt_entry": 2000.0, "stop_loss": 1995.0,
            "take_profit_1": 2010.0, "take_profit_2": 2015.0,
            "risk_price": 5.0, "rr_planned": 3.0, "r_multiple": None,
            "exit_reason": "VOID_ENTRY_BEYOND_SL", "exit_time": None,
            "bars_held": 0, "filled": False,
            "void_reason": "VOID_ENTRY_BEYOND_SL",
        },
    }
    return [valid, void]


def _setup_checkpoint_dir(tmp_path):
    ckpt = tmp_path / "checkpoints"
    ckpt.mkdir()
    (ckpt / "2026-01.json").write_text(
        json.dumps({"month": "2026-01", "records": _checkpoint_records()}),
        encoding="utf-8",
    )
    bars = [
        CandleCreate(symbol="XAU/USD", timeframe="15m", timestamp=BASE + i * TF,
                     open=2000, high=2000.2, low=1999.8, close=2000,
                     volume=1.0, source="twelvedata")
        for i in range(5)
    ]
    bar_close_index = {b.timestamp + TF: i for i, b in enumerate(bars)}
    return ckpt, bars, bar_close_index


def test_loader_skips_void_records_without_crash(tmp_path):
    ckpt, bars, index = _setup_checkpoint_dir(tmp_path)
    raw, n_files, n_records, void_count, reasons = pf.load_checkpoint_trades(
        ckpt, bars, [2.0] * len(bars), index, BASE, BASE + 10 * TF,
    )
    assert n_files == 1
    assert n_records == 2
    assert void_count == 1
    assert reasons["VOID_ENTRY_BEYOND_SL"] == 1
    assert len(raw) == 1
    assert raw[0]["key"] == "XAU/USD_1h_BUY_key1"


def test_manifest_gate_reads_versioned_expected_values(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "expected:\n  n_filled: 249\n  n_void_entry: 7\n  total_r: 51.26\n  r_tol: 0.005\n",
        encoding="utf-8",
    )
    exp = pf.load_manifest_expected(manifest)
    assert exp["n_filled"] == 249
    assert exp["n_void_entry"] == 7
    assert exp["total_r"] == pytest.approx(51.26)
    assert exp["r_tol"] == pytest.approx(0.005)


def test_manifest_gate_rejects_missing_and_incomplete(tmp_path):
    with pytest.raises(SystemExit, match="manifest not found"):
        pf.load_manifest_expected(tmp_path / "absent.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("expected:\n  n_filled: 1\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="missing expected fields"):
        pf.load_manifest_expected(bad)
