"""Run-manifest construction for SMC Baseline v1 (contract §9.2).

The manifest is the single provenance record that makes a published baseline
reproducible: code version, data snapshot, configuration hashes, conventions,
and expected verification values. It is emitted in Phase 5, never before.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

MANIFEST_FIELDS = [
    "baseline_id",
    "engine_commit",
    "created_utc",
    "data",
    "backtest_range",
    "strategy",
    "execution",
    "splits",
    "metrics",
    "expected",
    "artifacts",
]


def hash_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of a file, streamed so large snapshots are safe."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_paths(paths: Iterable[Path]) -> str:
    """Stable combined hash of a set of source/config files."""
    digest = hashlib.sha256()
    for path in sorted(Path(p) for p in paths):
        digest.update(str(path.name).encode("utf-8"))
        digest.update(hash_file(path).encode("ascii"))
    return digest.hexdigest()


def build_run_manifest(
    args: Any,
    meta: Dict[str, Any],
    engine_commit: str,
    strategy_hash: str,
    execution_hash: str,
    data_sha256: str,
    expected: Dict[str, Any],
    created_utc: Optional[str] = None,
) -> Dict[str, Any]:
    """Assemble a complete Baseline v1 run manifest."""
    start = getattr(args, "start_date", None) or "full_range"
    end = getattr(args, "end_date", None) or "latest"
    return {
        "baseline_id": "smc-baseline-v1",
        "engine_commit": engine_commit,
        "created_utc": created_utc or datetime.now(timezone.utc).isoformat(),
        "data": {
            "path": meta.get("db_path", "backtest.db"),
            "sha256": data_sha256,
            "symbol": getattr(args, "symbol", "XAU/USD"),
            "source": getattr(args, "source", "twelvedata"),
            "timeframe": "15m",
            "raw_rows": meta.get("raw_rows"),
            "open_market_rows": meta.get("open_market_bars"),
            "missing_intraday_bars": meta.get("missing_intraday_bars"),
            "first_bar_open_utc": _iso(meta.get("raw_first")),
            "last_bar_open_utc": _iso(meta.get("raw_last")),
        },
        "backtest_range": [start, end],
        "strategy": {
            "config_hash": strategy_hash,
            "frozen_commit": "87509a43ef6af26b6bb69de5310e5e2d44fb0581",
        },
        "execution": {
            "convention_version": "optionB-v1",
            "config_hash": execution_hash,
            "cadence": "15m_close",
            "fill": "next_15m_open",
            "price_anchor": "1h_close",
            "geometry": "signal_price_anchored_fixed",
            "r_denominator": "planned_risk",
            "gap_fill": "adverse_open / limit_or_better",
            "intrabar": "sl_first",
            "void_rules": [
                "VOID_ENTRY_BEYOND_SL", "VOID_ENTRY_BEYOND_TP",
                "NO_FILL_SESSION_BOUNDARY", "NO_FILL_MISSING_NEXT_BAR",
            ],
            "cost": {
                "value": float(getattr(args, "spread", 0.40)),
                "basis": "price_units_per_position_unit_round_trip",
                "deductions_per_trade": 1,
            },
        },
        "splits": {
            "calibration": ["2023-03-01", "2025-05-21T08:15"],
            "validation": ["2025-05-21T08:15", "2026-02-16T03:00"],
            "test": ["2026-02-16T03:00", "2026-11-15T15:00"],
            "holdout": {"after": "2026-11-15T15:00", "status": "contaminated_current_snapshot"},
        },
        "metrics": {
            "drawdown_basis": "exit_time",
            "breakeven_definition": "loss",
            "bootstrap": "day_cluster",
            "seed": 12345,
            "min_n_for_verdict": 100,
        },
        "expected": expected,
        "artifacts": {
            "checkpoints": "reports/smc_baseline_v1/checkpoints/",
            "report": "reports/smc_baseline_v1/report.md",
            "controls": "reports/smc_baseline_v1/controls.csv",
            "regression_fixtures": "server/tests/",
        },
    }


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
