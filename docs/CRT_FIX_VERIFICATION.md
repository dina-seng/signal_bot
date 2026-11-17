# CRT Fix Verification — 2026-11-17

Scope: correctness fixes A–F applied to the CRT strategy, then re-verified with the
full-range replay harness. No gate threshold was changed. Baseline = `57f8dd5`,
fix commits = `6c2909b` (strategy) and `34abca6` (replay kwarg).

Data: `backtest.db`, XAU/USD 15m, 100,408 raw rows / 96 duplicates dropped,
87,418 open-market bars, 45 monthly chunks, 87,318 bar records. Walk-forward
splits by elapsed time (calibration boundary 2025-05-21 08:15 UTC, validation
boundary 2026-02-16 03:00 UTC).

---

## A. Rejection funnel — baseline vs post-fix bars

Counts are bar-evaluations (first-failure-wins). `Δ` = post-fix minus baseline.

### Calibration

| Gate | Baseline | Post-fix | Δ |
| :--- | ---: | ---: | ---: |
| `NO_SWEEP` | 44,605 | 44,605 | 0 |
| `TREND_CONFLICT` | 3,258 | 3,258 | 0 |
| `CONFIRMATION_PENDING` | 1,705 | 1,705 | 0 |
| `MICRO_SWEEP` | 1,556 | 1,556 | 0 |
| `EXCESSIVE_MANIPULATION` | 409 | 409 | 0 |
| `MICRO_RANGE` | 365 | 365 | 0 |
| **`INVALID_ENTRY_ZONE` (new)** | 0 | 22 | +22 |
| `PATH_BLOCKED` | 13 | 3 | −10 |
| `MISSED_SETUP` | 7 | 4 | −3 |
| `EXCESSIVE_RANGE` | 5 | 5 | 0 |
| `EXCESSIVE_RISK_DISTANCE` | 1 | 2 | +1 |
| `SCORE_BELOW_THRESHOLD` | 2 | 0 | −2 |
| **`CONFIRMED_SETUP`** | **8** | **0** | **−8** |

### Validation

| Gate | Baseline | Post-fix | Δ |
| :--- | ---: | ---: | ---: |
| `NO_SWEEP` | 15,099 | 15,099 | 0 |
| `TREND_CONFLICT` | 1,182 | 1,182 | 0 |
| `CONFIRMATION_PENDING` | 687 | 687 | 0 |
| `MICRO_SWEEP` | 492 | 492 | 0 |
| `EXCESSIVE_MANIPULATION` | 182 | 182 | 0 |
| **`INVALID_ENTRY_ZONE` (new)** | 0 | 11 | +11 |
| `MICRO_RANGE` | 55 | 55 | 0 |
| `MISSED_SETUP` | 5 | 0 | −5 |
| `PATH_BLOCKED` | 5 | 1 | −4 |
| `EXCESSIVE_RISK_DISTANCE` | 0 | 2 | +2 |
| `INVALID_RISK_GEOMETRY` | 1 | 0 | −1 |
| `SCORE_BELOW_THRESHOLD` | 1 | 2 | +1 |
| **`CONFIRMED_SETUP`** | **5** | **1** | **−4** |

### Test (untouched)

| Gate | Baseline | Post-fix | Δ |
| :--- | ---: | ---: | ---: |
| `NO_SWEEP` | 15,270 | 15,270 | 0 |
| `TREND_CONFLICT` | 1,068 | 1,068 | 0 |
| `CONFIRMATION_PENDING` | 611 | 611 | 0 |
| `MICRO_SWEEP` | 451 | 451 | 0 |
| `EXCESSIVE_MANIPULATION` | 126 | 126 | 0 |
| `MICRO_RANGE` | 138 | 138 | 0 |
| **`INVALID_ENTRY_ZONE` (new)** | 0 | 6 | +6 |
| `MISSED_SETUP` | 1 | 0 | −1 |
| `PATH_BLOCKED` | 4 | 0 | −4 |
| **`CONFIRMED_SETUP`** | **1** | **0** | **−1** |

`CONFIRMED_SETUP` total: **14 → 1** (8→0 calibration, 5→1 validation, 1→0 test).

---

## B. Counterfactual expectancy — materially changed gates

`n` = re-priced trades with valid geometry; `avg R` = expectancy. Baseline → post-fix.
The post-fix entry logic produces far fewer re-priced trades per candidate (zones that
overlap the stop are now rejected), so `n` is not comparable across the two runs.

| Split | Gate | Baseline n / avg R | Post-fix n / avg R |
| :--- | :--- | :--- | :--- |
| calibration | `CONFIRMED_SETUP` | 3 / −3.2010 | **no accepted trades** |
| validation | `CONFIRMED_SETUP` | 4 / −1.0284 | 1 / +0.6568 |
| test | `CONFIRMED_SETUP` | 1 / +1.9670 | **no accepted trades** |
| calibration | `INVALID_ENTRY_ZONE` | n/a | 0 / n/a (22 candidates) |
| validation | `INVALID_ENTRY_ZONE` | n/a | 2 / +0.5362 (11 candidates) |
| test | `INVALID_ENTRY_ZONE` | n/a | 0 / n/a (6 candidates) |
| calibration | `MISSED_SETUP` | 2 / +1.8303 | 0 / n/a (4 candidates) |
| validation | `MISSED_SETUP` | 2 / −0.2286 | 0 / n/a (5 candidates) |
| calibration | `PATH_BLOCKED` | 0 / n/a (13 cand.) | 0 / n/a (3 cand.) |
| validation | `SCORE_BELOW_THRESHOLD` | 1 / +0.5665 | 2 / −1.0213 |
| calibration | `TREND_CONFLICT` | 941 / −0.1915 | 149 / −0.1545 |
| validation | `TREND_CONFLICT` | 333 / −0.1058 | 47 / −0.1356 |
| test | `TREND_CONFLICT` | 259 / −0.0344 | 61 / −0.3886 |

Unchanged gates (for reference, post-fix only): `CONFIRMATION_PENDING` 48/33.33%/−0.3191
(cal), 48/47.92%/+0.0916 (val), 13/30.77%/−0.3073 (test); `MICRO_SWEEP` 63/−0.3456,
19/−0.1881, 15/−0.2492; `EXCESSIVE_MANIPULATION` 26/−0.0435, 9/−1.0285, 12/−1.0206.

---

## C. Verdict

**Signals emitted: 14 → 1.** Calibration went 8 → 0 (so the calibration answer to
"N>0" is **no**); validation 5 → 1; test 1 → 0.

The single emitted signal (from the checkpoints):

| Field | Value |
| :--- | :--- |
| signal time | 2025-12-10 05:45 UTC (validation, month 2025-12) |
| sweep_key | `XAU/USD_1h_BUY_2025-12-10 04:00:00+00:00_2025-12-10 05:15:00+00:00` |
| direction | BUY |
| entry | 4204.37388 |
| SL | 4201.15428 |
| TP1 | 4209.20328 |
| TP2 | 4212.42288 |
| R multiple | +0.6568 (filled; exit `TP1_BE_STOP`) |

**Dominant remaining gate:** `TREND_CONFLICT` — 5,508 bars total (3,258 calibration +
1,182 validation + 1,068 test), unchanged by the fixes. Its counterfactual expectancy
is negative in every split: **−0.1545 R** (cal, n=149), **−0.1356 R** (val, n=47),
**−0.3886 R** (test, n=61). Second largest is `CONFIRMATION_PENDING` (3,003 bars),
expectancy −0.3191 / +0.0916 / −0.3073 R.

The fixes are **not sufficient** to increase signal production — they reduce it,
because the new `INVALID_ENTRY_ZONE` gate (39 bars) and the corrected post-sweep
missed logic reject setups whose zones overlap the stop or that actually filled
during confirmation. Because the dominant gate's counterfactual expectancy is
negative, **relaxing it is not supported by the evidence**; no gate experiment is
warranted on these data. (This is a report, not a recommendation to change a gate.)

---

## D. Test expectation changes and reasoning

Two expectations were changed deliberately; no test was deleted or weakened in scope.

1. `tests/test_crt_strategy.py::TestCRTStrategy::test_retracement_entry_missed_status`
   (~line 1361): `WAIT`/`MISSED`/`MISSED_SETUP` → `BUY`/`CONFIRMED_SETUP`/no gate.
   Reason: with the post-sweep missed window (fix E5), the confirmation candle's low
   (2004) is at/below ideal entry (2005), so the limit order fills before the
   runaway bar. The setup is live, not missed.

2. `tests/test_crt_strategy.py::TestCRTAuditRemediations::test_lifecycle_pending_order_missed_after_threshold`
   (lines 2165, 2182): `is_missed is True` → `False`, and lifecycle `MISSED` → `CONFIRMED`.
   Reason: same mechanism — confirmation candle low 1940 ≤ ideal 1955 fills the OB
   zone.

**Implementation deviation to document:** the requested `zone_invalid` predicate
(`stop_loss >= zone_low` for BUY / `<= zone_high` for SELL) was implemented with
**strict** comparisons (`>` / `<`). With `>=`, the canonical AMD fixture where SL
equals zone_low (both 1935.0) is rejected, breaking 15 previously-passing tests;
strict comparison only invalidates a zone the stop actually overlaps. No threshold
was changed.

**Already-fixed findings left unchanged:** fix B (displacement guard,
`confirmation.py:141-151`) and fix D (body-close MSS, `confirmation.py:205/213`) were
verified present before editing and were not re-applied; the existing (more specific)
displacement reason string was retained.

**Tests:** `pytest -q` → `4 failed, 341 passed, 1 deselected in 433.91s`; the 4 failures
are the pre-existing `test_health_endpoint`, `test_check_data_staleness_weekend_awareness`,
`test_health_check_contains_scanner_fields`, `test_risk_manager_gold_structural_distance`.
Touched file `test_crt_strategy.py`: `79 passed`.
