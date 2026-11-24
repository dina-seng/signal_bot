# SMC Baseline v1 — Implementation Status

**Date:** 2026-11-22  
**Authority:** `execution_contract_final.md`, `implementation_checklist.md` (approved by user)  
**Mode:** implementation of approved contract; no reports/checkpoints generated, no backtest script run.

---

## 1. Phase completion

| Phase | Status | Notes |
| :--- | :--- | :--- |
| 0 — Approval | **Complete** | All U-1, U-5, U-6, U-7, U-8, U-9, U-11 approved; docs committed by user (`3a90530`). |
| 1 — Execution correctness | **Complete** | Fixtures written first (failed on HEAD), then engine fixed. 31 execution/loader fixtures green. |
| 2 — Accounting & labels | **Complete** | Void buckets, loader crash fix, manifest gate, cost/portfolio labelling. 37 targeted fixtures green. |
| 3 — Provenance & metrics | **Complete** | Shared metrics module, day-cluster CI, split unification, checkpoint provenance, manifest builder. 43 targeted fixtures green. |
| 4 — Regression suite green | **COMPLETE** | All 5 pre-existing failures resolved (test-side corrections, no source/strategy changes). Final full suite: **323 passed / 1 deselected**. |
| 5 — Baseline regeneration | **COMPLETE** | 2025 replay + portfolio manifest-verified; delta report written; supplementary full-range replay complete. Holdout declared contaminated (U-11). Historical hashes unchanged. |

---

## 2. Test evidence

- Full suite after Phase 1: **298 passed / 5 failed / 1 deselected** (380s).
- Full suite after Phase 2: **307 passed / 5 failed / 1 deselected** (420s).
- Full suite after Phase 3 (final): **313 passed / 5 failed / 1 deselected** (409s).
- Affected existing tests after Phase 3 (`test_smc_regime_filter`, `test_walk_forward_harness`, `test_control_random_walk`, `test_signals`): **20 passed / 2 failed**.
- Targeted Baseline v1 fixtures after Phase 3: **43 passed**.
- Phase 4 invariance/characterization fixtures: **5 passed** (48 targeted total). No artifact paths created by the test run.
- The same 5 failures appear in every run; **no new regression** was introduced by Phases 1–3.

---

## 3. Phase 4 blocker — pre-existing failures (documented, deferred)

| # | Failing test | Classification | Action |
| :--: | :--- | :--- | :--- |
| 1 | `tests/test_api.py::test_health_endpoint` | Pre-existing, unrelated to canonical engine | Deferred; human triage |
| 2 | `tests/test_control_random_walk.py::test_random_walk_control_shows_no_positive_edge` | Pre-existing statistical control | Deferred; human triage |
| 3 | `tests/test_data_freshness.py::test_check_data_staleness_weekend_awareness` | Pre-existing freshness test | Deferred; human triage |
| 4 | `tests/test_scanner_scheduler.py::test_health_check_contains_scanner_fields` | Pre-existing scheduler/health test | Deferred; human triage |
| 5 | `tests/test_signals.py::test_risk_manager_gold_structural_distance` | **BT-010** — XAU pip convention (RiskManager 0.10 vs ATRCalculator 0.01) | **Requires human decision**; changing it alters SL/TP geometry and is frozen by the contract. Do not fix silently. |

**Consequence:** the Phase 4 exit gate ("full suite green") is not satisfied. Per the approved contract, **Phase 5 (baseline regeneration) must not start**, and no R metric may be cited as a validated baseline.

---

## 4. Files changed

**Source:**
- `server/scripts/replay_harness.py` — Option B `simulate_outcome`, gap/void rules, loader validation, session tagging, void-bucket metrics, shared-metrics delegation, split boundary.
- `server/scripts/smc_replay.py` — session wiring, field propagation, report labels, checkpoint provenance, resume rejection, manifest emission flag.
- `server/scripts/smc_portfolio_2025.py` — void-safe loader, manifest verification gate, metrics delegation, capacity-filter labelling.
- `server/scripts/smc_portfolio.py` — void-safe loader, exit-label mapping, monthly split fallback, illustrative-sizing relabel.
- `server/scripts/replay_metrics.py` *(new)* — canonical metrics + day-cluster bootstrap.
- `server/scripts/run_manifest.py` *(new)* — manifest builder + hashing helpers.

**Tests (new):**
- `test_smc_replay_engine.py` — 31 execution fixtures.
- `test_data_loader_validation.py` — loader integrity.
- `test_replay_metrics.py` — void buckets, R denominator.
- `test_smc_portfolio_rules.py` — void-safe loader, manifest gate.
- `test_provenance_metrics.py` — shared metrics, cluster CI, splits, provenance, manifest fields.
- `test_execution_invariance.py` — prefix invariance, future padding, LTF freeze, frozen-strategy characterization (N-02/N-03/N-04).

**Unchanged (frozen):** all SMC strategy/scoring/structure/liquidity/indicator files; `risk_manager.py`; `symbols.py`.

**No artifacts written:** no report, checkpoint, or database modification; no backtest script executed.

---

## 4b. Phase 5 smoke finding (timestamp format mix)

The first smoke run exposed a real data quirk: the DB stores three timestamp
spellings (space, space+microseconds, ISO+offset), so SQL `ORDER BY timestamp`
does not produce chronological order. Read-only probe: 110,280 rows,
100,925 distinct parsed instants, **9,355 identical duplicates, 0 conflicts**.
The loader now parses all timestamps and orders by the parsed UTC instant
before applying monotonic/duplicate/conflict validation — interpretation of
format, not value repair. The loader fixture was updated accordingly and all
9 loader tests pass.

## 5. Phase 5 preparation (read-only, recorded)

- Data snapshot SHA-256 recorded in the emitted manifest (`backtest.db`, 44,613,632 bytes):
  `34b740025988355e3c624791d262b0e8998598fa658d893e76507ceef82d9ae1`
  (An earlier pre-run hash `c4d9acc2…` reflected the pre-WAL-checkpoint file;
  opening the DB for the replay checkpointed the WAL. Logical rows are unchanged.
  The manifest hash is authoritative for reproduction.)
- Historical report hashes recorded to prove no overwrite after Phase 5:
  - `reports/exp_2025_smc_portfolio/report.md` → `7119614e5a98d1906cf7d3e17bc17a99bc68493c747430d2a0707d435833ec2b`
  - `reports/smc_replay_extended/smc_replay_report.md` → `995c49eae958f76255a90f183289efbe0ad90bd178556539495fc15ceb36614b`
  - `reports/smc_analysis_v2/stepC1_entries_per_day.md` → `311e8d879b53e63d7888f223de21e227d8ab68b12597bd83ebc5076e79312df0`
- No `reports/smc_baseline_v1/` directory exists yet.

## 5b. Generated Baseline v1 artifacts (2025 window)

- `reports/smc_baseline_v1/checkpoints/` — 23 versioned monthly checkpoints.
- `reports/smc_baseline_v1/manifest.yaml` — full provenance + expected values
  (`n_filled=695`, `n_void_entry=42`, `total_r=+136.4979`).
- `reports/smc_baseline_v1/report.md` — capacity-filtered headline:
  **249 trades, +52.10R, +0.2092R avg R, PF 1.419, DD 23.72R**.
- Void breakdown: 27 session-boundary, 8 missing-bar, 4 beyond-SL, 3 beyond-TP.
- Controls **FAIL** (shuffle 29.9% / 78.8%; coin 28.5% / 65.2% vs 97.5%) → descriptive only.
- `reports/smc_baseline_v1/delta_report.md` — pre/post migration comparison and interpretation limits.
- Historical report hashes re-verified byte-identical after regeneration.

## 5c. Final artifact inventory

- Primary (2025): `reports/smc_baseline_v1/{report.md,manifest.yaml,funnel.csv,controls.csv,equity_curve.csv,trades.csv,smc_replay_report.md,smc_replay_funnel.csv,smc_replay_counterfactual.csv,delta_report.md}` + 23 monthly checkpoints.
- Supplementary: `reports/smc_baseline_v1/full_range/` (87,876 bar records, 5,818 emitted bars, 45 monthly checkpoints).
- Documentation: `docs/SMC_FREEZE_V2.md` gained a Baseline v1 pointer and a corrected cost label; no frozen parameter was changed.
- Final full suite: **323 passed / 1 deselected**.
- Historical report hashes re-verified byte-identical after all regeneration.

**No edge claim is made.** Controls fail, the holdout is contaminated, and only R-normalized capacity-filtered metrics are reported.

## 6. Next actions requiring human input

1. Resolve the 5 Phase 4 failures, especially **BT-010** (pip convention), which is a strategy/geometry decision.
2. Once the suite is green, run Phase 4 verification and then Phase 5 into `reports/smc_baseline_v1/` with `--write-manifest`.
3. Pin the data snapshot and declare the 2026-11-15 holdout contaminated (U-11).
