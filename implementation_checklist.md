# SMC Baseline v1 — Implementation Checklist

**Companion to:** `execution_contract_final.md` (authoritative contract)  
**Repository:** `D:\trade`  
**Date:** 2026-11-22  
**Status:** READY FOR APPROVAL — nothing below has been implemented.  
**Rule:** no task may begin before Phase 0 approval; no artifact may be written before Phase 5.

---

## 0. Pre-flight (approval gate)

| ID | Task | Affected files | Depends on | Acceptance criteria |
| :--- | :--- | :--- | :--- | :--- |
| 0.1 | Obtain written approval for U-1, U-5, U-6, U-7, U-8, U-9, U-11 and acknowledge supersessions C-1/C-2 | `execution_contract_final.md` §13 | — | Approval recorded in baseline manifest |
| 0.2 | Pin the data snapshot (hash, row counts, end timestamp) | new `reports/smc_baseline_v1/manifest.yaml` | 0.1 | Hash + 15m row count recorded; contamination status of 2026-11-15 holdout declared |
| 0.3 | Create clean working branch; confirm historical reports/checkpoints untouched | git | 0.1 | `git status` shows only intended new files |
| 0.4 | Triage the prior 5 failing tests (N-28) | `server/tests/` | 0.1 | Failure list documented with owners; suite baseline known |

---

## 1. Phase 1 — Execution correctness (hard blocker)

**Tests first.** All new test files must fail against current code before source changes.

| ID | Task | Affected files | Depends on | Acceptance criteria |
| :--- | :--- | :--- | :--- | :--- |
| 1.1 | Write execution fixtures: normal fill, in-trade SL/TP gaps, same-bar SL-first, pre-entry-bar non-stop, geometry immutability, R numerics, cost-once, timestamp/holding | new `server/tests/test_smc_replay_engine.py` | 0.1 | Tests written; confirmed failing on HEAD |
| 1.2 | Write loader-integrity fixtures: invalid OHLC, monotonic, conflicting duplicates, forming bar, session boundaries, source/calendar filters | new `server/tests/test_data_loader_validation.py` | 0.1 | Tests written; failing on HEAD |
| 1.3 | Change market fill: `fill_idx = signal_index + 1`; management loop starts at entry candle; `fill_price = bars[j].open`; `entry_time` distinct from `signal_time` | `server/scripts/replay_harness.py` `simulate_outcome` :176-191 | 1.1 | BT-004 probe no longer stops on signal bar; signal bar high/low never inspected |
| 1.4 | Implement void outcomes `VOID_ENTRY_BEYOND_SL`, `VOID_ENTRY_BEYOND_TP`, `NO_FILL_SESSION_BOUNDARY`, `NO_FILL_MISSING_NEXT_BAR`, `NO_FILL_END_OF_DATA`; no position, no R, no cost | `replay_harness.py` `simulate_outcome`; `smc_replay.py` `replay_chunk` | 1.3, U-9/U-6 approval | Fixtures §10 #7–10 pass; no fabricated price |
| 1.5 | In-trade gap fills: SL `min/max(open, SL)`, TP `max/min(open, TP)`; intended vs actual recorded; TP2-at-entry bypass | `replay_harness.py` :195-225 | 1.3 | R −1.38 (SL gap) and +2.52 (TP gap) reproduced |
| 1.6 | Geometry immutability: make `signal_price`, `structural_sl`, `tp1`, `tp2`, `planned_risk` write-once; never re-run RiskManager on fill | `replay_harness.py`; `smc_replay.py` `build_market_trade` :160-215 | 1.3 | Fixtures 1999/2000.5/2001 give identical levels; no field written after outcome |
| 1.7 | Add new record fields: `fill_price`, `entry_time`, `actual_risk_distance`, `price_unit_realized_pnl`, `monetary_realized_loss=null`, `void_reason`, `convention_version`; keep `crt_entry` alias for back-compat | `replay_harness.py` `SignalRecord` :67-95, `_signal_to_dict` :98-118; `smc_replay.py` `SmcRecord` :121-145 | 1.3 | Checkpoint round-trip preserves all fields; old checkpoints neither silently mixed nor crash |
| 1.8 | Fix limit branch stop-before-fill ordering (BT-002) in the same management loop | `replay_harness.py` :158-175 | 1.3 | BUY limit 100/SL 99, low 97 → filled then `STOP_LOSS ≈ −1R` |
| 1.9 | Loader validation: reject non-monotonic, conflicting duplicates, invalid OHLC, forming bars; emit `missing_intraday_bars` count; session-open tagging via `is_market_open(ts−15m)` | `replay_harness.py` `load_full_15m_candles` :250-300; `calendar.py` (read-only reference) | 1.2, U-5/U-6 approval | Injected bad rows fail deterministically; source/calendar filters preserved |
| 1.10 | Timestamp semantics: `exit_time >= entry_time`; `bars_held = (exit−entry)/15m` clamped ≥0; round R to same precision | `replay_harness.py` :180, :202, :224, :234, :243 | 1.3, 1.7 | No negative holding in fixture set; −0.2h symptom eliminated |
| 1.11 | Exit reason labels in report mapping (`TIME_EXPIRY`/`END_OF_DATA` vs old `TIMEOUT_MARK_TO_MARKET`) | `smc_replay.py` `build_report`; `smc_portfolio.py` :511,518 | 1.3 | Report labels match simulator output |

**Phase 1 exit gate:** tests 1–17 of contract §10 pass; no strategy file changed; no artifacts regenerated; no R metric cited.

---

## 2. Phase 2 — Accounting, buckets, and labels

| ID | Task | Affected files | Depends on | Acceptance criteria |
| :--- | :--- | :--- | :--- | :--- |
| 2.1 | Add `n_void_entry` bucket (split by reason); keep voids out of `n_no_fill` and out of 0R expectancy; report `void_rate` | `replay_harness.py` `trade_metrics` :402-413, `compute_metrics` :363-399; `smc_replay.py` `_metrics` :560-587 | 1.4 | Funnel totals reconcile; expectancy unchanged by void count |
| 2.2 | Skip void records before `exit_time` dereference; count them; exclude consistently from controls | `smc_portfolio_2025.py` `load_checkpoint_trades` :155-219 (esp. :179), `attach_controls` :456-467 | 2.1 | No crash on void; real/control populations identical |
| 2.3 | Cost convention: keep 0.40 single deduction; change label to "0.40 price units per position unit, round trip" in reports/manifest; add cost metadata fields | `smc_replay.py` `build_report` :714; `smc_portfolio_2025.py` report text :752,814,967,1078; new manifest | 1.5 | Number unchanged; label accurate; `spread_paid` recorded once |
| 2.4 | Record `actual_risk_distance` and `monetary_realized_loss=NOT_MODELED`; `GAP_RISK_DIVERGENCE` flag; no rescale | `replay_harness.py` :236-244; `smc_replay.py` `SmcRecord` | 1.7 | Divergent-gap fixture keeps planned denominator; both fields persisted |
| 2.5 | Portfolio labelling: "capacity-filtered / portfolio-constrained 1R trade set"; relabel/remove `$100` executability claims | `smc_portfolio_2025.py` header/docstrings; `smc_portfolio.py` :90,108-120 | 2.2 | No language implying capital-aware account simulation |
| 2.6 | Replace hard-coded verification gate with manifest + deterministic fixtures | `smc_portfolio_2025.py` :92-95, :596-604 | 0.1, 2.1 | Old 688/+136.45 constants gone; gate reads manifest |
| 2.7 | Align `smc_portfolio.py` with canonical rule/metric implementation; fix monthly split fallback | `smc_portfolio.py` :508-515, :582-586 | 2.1, 2.5 | Parity test passes; no stale exit-label assumptions |

**Phase 2 exit gate:** voids counted and excluded from R; time semantics consistent; cost labelled correctly; gate versioned.

---

## 3. Phase 3 — Provenance and metrics

| ID | Task | Affected files | Depends on | Acceptance criteria |
| :--- | :--- | :--- | :--- | :--- |
| 3.1 | Single metrics module (exit-ordered DD, BE definition, PF with zero losses) | `replay_harness.py` or new `server/scripts/replay_metrics.py`; `smc_replay.py`; `smc_portfolio_2025.py` | 2.1 | Golden R sequence → identical metrics from every producer |
| 3.2 | Day-cluster bootstrap (cluster = UTC day), fixed seed, SE/VIF reporting | metrics module; reports | 3.1 | CI wider than IID on clustered synthetic data; deterministic |
| 3.3 | Unify split boundary (`<=` vs `<`) and warmup policy | `smc_replay.py` `split_of` :95-101; `replay_harness.py` `split_of` :310-316 | 2.7 | Boundary fixtures pass in both producers |
| 3.4 | Checkpoint provenance header + resume mismatch rejection + cached gap counters | `smc_replay.py` `save_checkpoint`/`load_checkpoint` :528-541, `main` :934-999 | 1.7, 0.2 | Resume from different code/data hash fails explicitly; stats identical cached vs computed |
| 3.5 | Emit full run manifest (all §9.2 fields) | new `reports/smc_baseline_v1/manifest.yaml`; report writers | 3.4 | Every required field present and non-placeholder |
| 3.6 | No-fill/invalid handling in loader and reports; no-fill rate reported | `smc_portfolio_2025.py`; `smc_replay.py` | 2.2, 3.1 | No-fill records do not crash; rate reported |

**Phase 3 exit gate:** artifacts fully traceable; metrics comparable across producers.

---

## 4. Phase 4 — Regression suite green

| ID | Task | Affected files | Depends on | Acceptance criteria |
| :--- | :--- | :--- | :--- | :--- |
| 4.1 | Portfolio-rule fixtures (dedupe, cap, separation, daily stop, exit-ordered DD, deterministic controls) | new `server/tests/test_smc_portfolio_rules.py` | 2.x | Deterministic rule funnel reproduced |
| 4.2 | Metrics golden set (win rate, avg/median R, PF, DD, BE, cluster CI, seed) | new `server/tests/test_replay_metrics.py` | 3.1, 3.2 | Golden values stable |
| 4.3 | Prefix invariance and future padding; LTF cadence characterization; strategy characterization N-03/N-04 | `test_smc_replay_engine.py` | 1.x | Bit-identical outputs truncated vs padded; no strategy behaviour change |
| 4.4 | Resolve previously failing tests; run full suite | `server/tests/` | 0.4, 4.1–4.3 | `python -m pytest tests/` green; hermetic guards intact |
| 4.5 | Verify no writes occur during tests | `conftest.py` guards | 4.4 | No live API/Postgres/artifact writes |

**Phase 4 exit gate:** full suite green; canonical coverage complete.

---

## 5. Phase 5 — Baseline regeneration (only phase allowed to write artifacts)

| ID | Task | Affected files | Depends on | Acceptance criteria |
| :--- | :--- | :--- | :--- | :--- |
| 5.1 | Create `reports/smc_baseline_v1/` with versioned checkpoint subdir; never touch historical dirs | `reports/smc_baseline_v1/` (new) | 4.4, 0.2 | Old report/checkpoint hashes unchanged |
| 5.2 | Run full-range and 2025-window replays with pinned snapshot and manifest | `smc_replay.py`, `smc_portfolio_2025.py` | 5.1 | Manifest-based verification gate passes |
| 5.3 | Publish pre/post deltas and explain every changed metric | new delta report in `reports/smc_baseline_v1/` | 5.2 | No strategy parameter tuned to improve delta |
| 5.4 | Re-run controls with corrected simulator; report cluster-robust inference | portfolio report | 5.2, 3.2 | Controls pass on pre-registered holdout **or** baseline declared "no edge" |
| 5.5 | Holdout policy per U-11: no one-shot claim on contaminated current data | docs/manifest | 0.2, U-11 | Contamination status explicit |
| 5.6 | Documentation: update stale references, commit BT register, point docs to manifest | `docs/SMC_FREEZE_V2.md`, `RAYU.md`, `REPORT.md`, `docs/` audit register | 5.2 | Docs match code and artifacts |

**Phase 5 exit gate:** clean checkout + pinned snapshot reproduces every published number; headline labelled per U-7; no edge claim without passing controls.

---

## 6. File impact matrix

| File | Phase 1 | Phase 2 | Phase 3 | Phase 5 |
| :--- | :--- | :--- | :--- | :--- |
| `server/scripts/replay_harness.py` | **Primary** — simulate_outcome, loader, SignalRecord | metrics buckets, cost label | metrics module, split_of | — |
| `server/scripts/smc_replay.py` | replay_chunk wiring, field propagation, exit labels | report cost label | checkpoints, resume, manifest | regeneration |
| `server/scripts/smc_portfolio_2025.py` | — | void loader, gate, labels | metrics, controls | regeneration |
| `server/scripts/smc_portfolio.py` | exit labels | monetary claims, parity | — | regeneration if inputs change |
| `server/scripts/run_step1/3/c2/c6/6.py` | update only if harness signatures change | — | — | relabel limit vs market results |
| new `server/tests/test_*.py` (4 files) | execution + loader | portfolio | metrics | — |
| new `reports/smc_baseline_v1/` | — | — | manifest | **all artifacts** |
| `docs/*.md`, audit register | — | — | — | documentation |

**Explicitly unchanged (frozen):** `smc_strategy.py`, `evaluators.py` weights/floors/penalties, `structure/`, `liquidity/`, `indicators/` detection rules, TP1=2R/TP2=3R, 50% TP1, break-even, 500-bar hold, volume confirmation (not implemented). Any task that appears to require one of these → **stop and escalate**.

---

## 7. Dependency order (critical path)

```
0.1 approval → 0.2 snapshot → 1.1/1.2 tests → 1.3–1.11 execution (hard blocker)
     → 2.1–2.7 accounting/labels → 3.1–3.6 provenance/metrics → 4.1–4.5 suite green
     → 5.1–5.6 versioned regeneration → published baseline
```

- Phase 4 tests can be authored in parallel with Phase 1 but must be green before Phase 5.
- Phase 2 consumes corrected exit times and R; Phase 3 consumes corrected buckets; Phase 5 consumes everything.

---

## 8. Definition of done

- [ ] All approvals in contract §13 recorded.
- [ ] Contract §10 regression tests green, including void/session/gap/cost/timestamp cases.
- [ ] Full test suite green; hermetic guards intact.
- [ ] No historical report, checkpoint, config, database, or source behaviour overwritten.
- [ ] `reports/smc_baseline_v1/` complete with manifest; old artifact hashes unchanged.
- [ ] Headline labelled per U-7; portfolio labelled capacity-filtered; cost convention labelled accurately.
- [ ] Controls pass on a clean pre-registered holdout, or the baseline is explicitly declared descriptive-only.
- [ ] No frozen strategy rule changed; any required change escalated, not silently applied.
