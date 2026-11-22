"""Baseline v1 Phase 3 regression fixtures: shared metrics, clustered inference,
split boundaries, checkpoint provenance, and run-manifest completeness.

These tests are written first and must fail until Phase 3 is implemented.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from replay_harness import split_of as harness_split_of
import smc_replay
import smc_portfolio_2025
from replay_metrics import compute_core_metrics, day_cluster_bootstrap_ci
from run_manifest import MANIFEST_FIELDS, build_run_manifest

BASE = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)


def _golden():
    return [1.0, -0.5, 0.0, 2.0]


def test_core_metrics_golden_sequence():
    m = compute_core_metrics(_golden())
    assert m["n"] == 4
    assert m["win_rate"] == pytest.approx(50.0)          # 2 of 4 positive
    assert m["avg_r"] == pytest.approx(0.625)
    assert m["total_r"] == pytest.approx(2.5)
    assert m["profit_factor"] == pytest.approx(6.0)      # 3.0 / 0.5, BE is a loss
    assert m["breakeven_count"] == 1
    assert m["max_drawdown_r"] == pytest.approx(0.5)


def test_all_producers_agree_on_golden_sequence():
    rs = _golden()
    core = compute_core_metrics(rs)
    trades = [
        {"filled": True, "r_multiple": r, "exit_time": (BASE + i * timedelta(minutes=15)).isoformat()}
        for i, r in enumerate(rs)
    ]
    from replay_harness import trade_metrics
    tm = trade_metrics(trades)
    rm = smc_replay._metrics(trades)
    pm = smc_portfolio_2025.compute_metrics(
        [
            {"r": r, "exit_dt": BASE + i * timedelta(minutes=15),
             "decision_dt": BASE, "key": str(i), "bars_held": i,
             "wall_hours": float(i), "exit_reason": "TP2"}
            for i, r in enumerate(rs)
        ],
        BASE,
    )
    pm_keys = {
        "win_rate": "win_rate", "avg_r": "avg_r", "profit_factor": "profit_factor",
        "total_r": "total_r", "max_drawdown_r": "max_dd_r",
    }
    for key in ("win_rate", "avg_r", "profit_factor", "total_r", "max_drawdown_r"):
        assert pytest.approx(tm[key]) == core[key]
        assert pytest.approx(rm[key]) == core[key]
        assert pytest.approx(pm[pm_keys[key]]) == core[key]


def test_day_cluster_bootstrap_wider_than_iid_and_deterministic():
    # 10 clusters of 5: alternating day means +/- 5 -> strong intra-day correlation.
    values, clusters = [], []
    for day in range(10):
        centre = 5.0 if day % 2 == 0 else -5.0
        for i in range(5):
            values.append(centre + 0.01 * i)
            clusters.append(day)
    lo_c, hi_c = day_cluster_bootstrap_ci(values, clusters, seed=7)
    from replay_harness import _bootstrap_ci
    lo_i, hi_i = _bootstrap_ci(values, seed=7)
    assert (hi_c - lo_c) > (hi_i - lo_i)
    assert day_cluster_bootstrap_ci(values, clusters, seed=7) == (lo_c, hi_c)


def test_split_boundaries_match_between_producers():
    b1 = datetime(2025, 5, 21, 8, 15, tzinfo=timezone.utc)
    b2 = datetime(2026, 2, 16, 3, 0, tzinfo=timezone.utc)
    bounds = (b1, b2)
    for ts in (b1 - timedelta(minutes=15), b1, b1 + timedelta(seconds=1), b2, b2 + timedelta(1)):
        assert harness_split_of(ts, bounds) == smc_replay.split_of(ts, bounds)


def test_checkpoint_provenance_roundtrip_and_mismatch(tmp_path):
    provenance = {"engine_commit": "abc", "data_sha256": "def", "execution_convention_version": "optionB-v1"}
    smc_replay.save_checkpoint(tmp_path, "2026-01", [], provenance=provenance)
    records, stats = smc_replay.load_checkpoint(tmp_path, "2026-01", expected_provenance=provenance)
    assert records == []
    assert stats.warmup_skipped == 0
    with pytest.raises(SystemExit, match="provenance mismatch"):
        smc_replay.load_checkpoint(
            tmp_path, "2026-01", expected_provenance={"engine_commit": "other"}
        )


def test_manifest_contains_all_required_fields():
    manifest = build_run_manifest(
        args=type("A", (), {
            "symbol": "XAU/USD", "source": "twelvedata", "start_date": "2025-01-01",
            "end_date": None, "spread": 0.40, "max_hold_bars": 500,
        })(),
        meta={"raw_rows": 100, "open_market_bars": 90, "raw_first": BASE, "raw_last": BASE},
        engine_commit="abc", strategy_hash="sh", execution_hash="eh",
        data_sha256="dh", expected={"n_filled": 1, "n_void_entry": 0, "total_r": 1.0},
    )
    for field in MANIFEST_FIELDS:
        assert field in manifest, f"manifest missing {field}"
    assert manifest["execution"]["convention_version"] == "optionB-v1"
