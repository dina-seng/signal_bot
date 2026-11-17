# CRT Replay — Full-Range Rejection Funnel & Counterfactual (No Thresholds Changed)

Production path: `resample_ohlc` → `ConfluenceEngine._prepare_market_data` → `StrategyManager.run_all_strategies` → `CRTStrategy` (dedup disabled). Every rejected sweep is counterfactually re-priced through the same `verify_ltf_confirmation` → `calculate_retracement_entry` → `calculate_crt_targets` → `simulate_outcome` logic with its gate ignored.

## 1. Data and walk-forward split

| Item | Value |
| :--- | :--- |
| Database | `D:\trade\backtest.db` |
| Raw rows / duplicates dropped | 100,408 / 96 |
| Full range | 2023-03-01 00:00 → 2026-11-15 15:00 UTC |
| Open-market bars replayed | 87,418 |
| Bar records captured | 87,318 |
| Calibration boundary (60%) | 2025-05-21 08:15 UTC |
| Validation boundary (80%) | 2026-02-16 03:00 UTC |

Split windows: calibration = earliest 60% (observation only), validation = next 20%, test = last 20% (untouched). No threshold was tuned on any split.

## 2. Rejection funnel — bars and distinct sweeps by gate and direction

Counts are bar-evaluations (first-failure-wins). A single sweep that survives many bars is counted on every bar; `distinct_sweeps` de-duplicates by the production `sweep_event_key`.

| Split | Gate | Bars | BUY bars | SELL bars | Distinct sweeps |
| :--- | :--- | ---: | ---: | ---: | ---: |
| calibration | `CONFIRMATION_PENDING` | 1,705 | 962 | 743 | 1,316 |
| calibration | `EXCESSIVE_MANIPULATION` | 409 | 222 | 187 | 334 |
| calibration | `EXCESSIVE_RANGE` | 5 | 5 | 0 | 5 |
| calibration | `EXCESSIVE_RISK_DISTANCE` | 2 | 0 | 2 | 0 |
| calibration | `INVALID_ENTRY_ZONE` | 22 | 11 | 11 | 20 |
| calibration | `MICRO_RANGE` | 365 | 183 | 182 | 245 |
| calibration | `MICRO_SWEEP` | 1,556 | 899 | 657 | 1,066 |
| calibration | `MISSED_SETUP` | 4 | 2 | 2 | 3 |
| calibration | `NO_SWEEP` | 44,605 | 23,295 | 21,310 | 0 |
| calibration | `PATH_BLOCKED` | 3 | 0 | 3 | 0 |
| calibration | `TREND_CONFLICT` | 3,258 | 1,216 | 2,042 | 2,357 |
| test | `CONFIRMATION_PENDING` | 611 | 295 | 316 | 463 |
| test | `EXCESSIVE_MANIPULATION` | 126 | 71 | 55 | 102 |
| test | `INVALID_ENTRY_ZONE` | 6 | 0 | 6 | 5 |
| test | `MICRO_RANGE` | 138 | 103 | 35 | 84 |
| test | `MICRO_SWEEP` | 451 | 202 | 249 | 310 |
| test | `NO_SWEEP` | 15,270 | 7,507 | 7,763 | 0 |
| test | `TREND_CONFLICT` | 1,068 | 507 | 561 | 776 |
| validation | `CONFIRMATION_PENDING` | 687 | 420 | 267 | 501 |
| validation | `CONFIRMED_SETUP` | 1 | 1 | 0 | 1 |
| validation | `EXCESSIVE_MANIPULATION` | 182 | 119 | 63 | 125 |
| validation | `EXCESSIVE_RISK_DISTANCE` | 2 | 0 | 2 | 0 |
| validation | `INVALID_ENTRY_ZONE` | 11 | 10 | 1 | 9 |
| validation | `MICRO_RANGE` | 55 | 30 | 25 | 40 |
| validation | `MICRO_SWEEP` | 492 | 315 | 177 | 334 |
| validation | `NO_SWEEP` | 15,099 | 8,042 | 7,057 | 0 |
| validation | `PATH_BLOCKED` | 1 | 0 | 1 | 0 |
| validation | `SCORE_BELOW_THRESHOLD` | 2 | 0 | 2 | 1 |
| validation | `TREND_CONFLICT` | 1,182 | 400 | 782 | 824 |

## 3. Counterfactual vs accepted trades

For every rejected candidate with a validated sweep, the trade is re-priced as if the gate had passed (same SL/TP/limit-zone logic, same spread). `n` counts trades with valid geometry; `candidates` includes those that could not be re-priced. Expectancy = average R per filled trade.

| Split | Rejection reason | Candidates | n | Filled | No fill | Win rate | Avg R | Expectancy | Flag |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| calibration | `CONFIRMATION_PENDING` | 1,705 | 113 | 48 | 65 | 33.33% | -0.3191 | -0.3191 |  |
| calibration | `EXCESSIVE_MANIPULATION` | 409 | 50 | 26 | 24 | 42.31% | -0.0435 | -0.0435 |   ⚠️ n<30 |
| calibration | `EXCESSIVE_RANGE` | 5 | 0 | 0 | 0 | n/a% | n/a | n/a |   ⚠️ n<30 |
| calibration | `INVALID_ENTRY_ZONE` | 22 | 0 | 0 | 0 | n/a% | n/a | n/a |   ⚠️ n<30 |
| calibration | `MICRO_RANGE` | 365 | 29 | 19 | 10 | 15.79% | -0.8210 | -0.8210 |   ⚠️ n<30 |
| calibration | `MICRO_SWEEP` | 1,556 | 96 | 63 | 33 | 31.75% | -0.3456 | -0.3456 |  |
| calibration | `MISSED_SETUP` | 4 | 1 | 0 | 1 | n/a% | n/a | n/a |   ⚠️ n<30 |
| calibration | `TREND_CONFLICT` | 3,258 | 228 | 149 | 79 | 35.57% | -0.1545 | -0.1545 |  |
| test | `CONFIRMATION_PENDING` | 611 | 20 | 13 | 7 | 30.77% | -0.3073 | -0.3073 |   ⚠️ n<30 |
| test | `EXCESSIVE_MANIPULATION` | 126 | 24 | 12 | 12 | 0.00% | -1.0206 | -1.0206 |   ⚠️ n<30 |
| test | `INVALID_ENTRY_ZONE` | 6 | 1 | 0 | 1 | n/a% | n/a | n/a |   ⚠️ n<30 |
| test | `MICRO_RANGE` | 138 | 7 | 4 | 3 | 0.00% | -1.0388 | -1.0388 |   ⚠️ n<30 |
| test | `MICRO_SWEEP` | 451 | 25 | 15 | 10 | 33.33% | -0.2492 | -0.2492 |   ⚠️ n<30 |
| test | `TREND_CONFLICT` | 1,068 | 91 | 61 | 30 | 27.87% | -0.3886 | -0.3886 |  |
| validation | `CONFIRMATION_PENDING` | 687 | 74 | 48 | 26 | 47.92% | 0.0916 | 0.0916 |  |
| validation | `EXCESSIVE_MANIPULATION` | 182 | 18 | 9 | 9 | 0.00% | -1.0285 | -1.0285 |   ⚠️ n<30 |
| validation | `INVALID_ENTRY_ZONE` | 11 | 2 | 2 | 0 | 100.00% | 0.5362 | 0.5362 |   ⚠️ n<30 |
| validation | `MICRO_RANGE` | 55 | 10 | 5 | 5 | 0.00% | -1.3733 | -1.3733 |   ⚠️ n<30 |
| validation | `MICRO_SWEEP` | 492 | 38 | 19 | 19 | 36.84% | -0.1881 | -0.1881 |   ⚠️ n<30 |
| validation | `SCORE_BELOW_THRESHOLD` | 2 | 2 | 2 | 0 | 0.00% | -1.0213 | -1.0213 |   ⚠️ n<30 |
| validation | `TREND_CONFLICT` | 1,182 | 86 | 47 | 39 | 42.55% | -0.1356 | -0.1356 |  |
| validation | `ACCEPTED (CONFIRMED_SETUP)` | 1 | 1 | 1 | 0 | 100.00% | 0.6568 | 0.6568 |   ⚠️ n<30 |

> 16 of 22 groups have fewer than 30 filled trades (⚠️ flagged above). Treat every metric in those groups as descriptive only.

---

No strategy threshold was modified; all CRT parameters are production defaults.
