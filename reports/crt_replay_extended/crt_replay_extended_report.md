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
| calibration | `CONFIRMED_SETUP` | 8 | 6 | 2 | 8 |
| calibration | `EXCESSIVE_MANIPULATION` | 409 | 222 | 187 | 334 |
| calibration | `EXCESSIVE_RANGE` | 5 | 5 | 0 | 5 |
| calibration | `EXCESSIVE_RISK_DISTANCE` | 1 | 0 | 1 | 0 |
| calibration | `MICRO_RANGE` | 365 | 183 | 182 | 245 |
| calibration | `MICRO_SWEEP` | 1,556 | 899 | 657 | 1,066 |
| calibration | `MISSED_SETUP` | 7 | 3 | 4 | 7 |
| calibration | `NO_SWEEP` | 44,605 | 23,295 | 21,310 | 0 |
| calibration | `PATH_BLOCKED` | 13 | 0 | 13 | 0 |
| calibration | `SCORE_BELOW_THRESHOLD` | 2 | 2 | 0 | 1 |
| calibration | `TREND_CONFLICT` | 3,258 | 1,216 | 2,042 | 2,357 |
| test | `CONFIRMATION_PENDING` | 611 | 295 | 316 | 463 |
| test | `CONFIRMED_SETUP` | 1 | 0 | 1 | 1 |
| test | `EXCESSIVE_MANIPULATION` | 126 | 71 | 55 | 102 |
| test | `MICRO_RANGE` | 138 | 103 | 35 | 84 |
| test | `MICRO_SWEEP` | 451 | 202 | 249 | 310 |
| test | `MISSED_SETUP` | 1 | 0 | 1 | 1 |
| test | `NO_SWEEP` | 15,270 | 7,507 | 7,763 | 0 |
| test | `PATH_BLOCKED` | 4 | 0 | 4 | 0 |
| test | `TREND_CONFLICT` | 1,068 | 507 | 561 | 776 |
| validation | `CONFIRMATION_PENDING` | 687 | 420 | 267 | 501 |
| validation | `CONFIRMED_SETUP` | 5 | 4 | 1 | 4 |
| validation | `EXCESSIVE_MANIPULATION` | 182 | 119 | 63 | 125 |
| validation | `INVALID_RISK_GEOMETRY` | 1 | 1 | 0 | 1 |
| validation | `MICRO_RANGE` | 55 | 30 | 25 | 40 |
| validation | `MICRO_SWEEP` | 492 | 315 | 177 | 334 |
| validation | `MISSED_SETUP` | 5 | 2 | 3 | 4 |
| validation | `NO_SWEEP` | 15,099 | 8,042 | 7,057 | 0 |
| validation | `PATH_BLOCKED` | 5 | 0 | 5 | 0 |
| validation | `SCORE_BELOW_THRESHOLD` | 1 | 1 | 0 | 1 |
| validation | `TREND_CONFLICT` | 1,182 | 400 | 782 | 824 |

## 3. Counterfactual vs accepted trades

For every rejected candidate with a validated sweep, the trade is re-priced as if the gate had passed (same SL/TP/limit-zone logic, same spread). `n` counts trades with valid geometry; `candidates` includes those that could not be re-priced. Expectancy = average R per filled trade.

| Split | Rejection reason | Candidates | n | Filled | No fill | Win rate | Avg R | Expectancy | Flag |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| calibration | `CONFIRMATION_PENDING` | 1,705 | 737 | 504 | 233 | 38.89% | -0.1620 | -0.1620 |  |
| calibration | `EXCESSIVE_MANIPULATION` | 409 | 98 | 71 | 27 | 39.44% | -0.2456 | -0.2456 |  |
| calibration | `EXCESSIVE_RANGE` | 5 | 0 | 0 | 0 | n/a% | n/a | n/a |   ⚠️ n<30 |
| calibration | `MICRO_RANGE` | 365 | 186 | 145 | 41 | 37.93% | -0.2585 | -0.2585 |  |
| calibration | `MICRO_SWEEP` | 1,556 | 774 | 509 | 265 | 42.44% | 0.0132 | 0.0132 |  |
| calibration | `MISSED_SETUP` | 7 | 2 | 2 | 0 | 100.00% | 1.8303 | 1.8303 |   ⚠️ n<30 |
| calibration | `SCORE_BELOW_THRESHOLD` | 2 | 2 | 2 | 0 | 100.00% | 0.4413 | 0.4413 |   ⚠️ n<30 |
| calibration | `TREND_CONFLICT` | 3,258 | 1,337 | 941 | 396 | 38.58% | -0.1915 | -0.1915 |  |
| test | `CONFIRMATION_PENDING` | 611 | 244 | 188 | 56 | 33.51% | -0.2498 | -0.2498 |  |
| test | `EXCESSIVE_MANIPULATION` | 126 | 28 | 23 | 5 | 26.09% | -0.2593 | -0.2593 |   ⚠️ n<30 |
| test | `MICRO_RANGE` | 138 | 56 | 33 | 23 | 45.45% | 0.1127 | 0.1127 |  |
| test | `MICRO_SWEEP` | 451 | 204 | 137 | 67 | 35.04% | -0.1701 | -0.1701 |  |
| test | `MISSED_SETUP` | 1 | 0 | 0 | 0 | n/a% | n/a | n/a |   ⚠️ n<30 |
| test | `TREND_CONFLICT` | 1,068 | 381 | 259 | 122 | 39.38% | -0.0344 | -0.0344 |  |
| validation | `CONFIRMATION_PENDING` | 687 | 301 | 219 | 82 | 44.75% | 0.0857 | 0.0857 |  |
| validation | `EXCESSIVE_MANIPULATION` | 182 | 43 | 35 | 8 | 25.71% | -0.2928 | -0.2928 |  |
| validation | `INVALID_RISK_GEOMETRY` | 1 | 0 | 0 | 0 | n/a% | n/a | n/a |   ⚠️ n<30 |
| validation | `MICRO_RANGE` | 55 | 16 | 14 | 2 | 21.43% | -0.5089 | -0.5089 |   ⚠️ n<30 |
| validation | `MICRO_SWEEP` | 492 | 241 | 175 | 66 | 44.00% | -0.0308 | -0.0308 |  |
| validation | `MISSED_SETUP` | 5 | 4 | 2 | 2 | 50.00% | -0.2286 | -0.2286 |   ⚠️ n<30 |
| validation | `SCORE_BELOW_THRESHOLD` | 1 | 1 | 1 | 0 | 100.00% | 0.5665 | 0.5665 |   ⚠️ n<30 |
| validation | `TREND_CONFLICT` | 1,182 | 478 | 333 | 145 | 36.94% | -0.1058 | -0.1058 |  |
| calibration | `ACCEPTED (CONFIRMED_SETUP)` | 8 | 8 | 3 | 5 | 0.00% | -3.2010 | -3.2010 |   ⚠️ n<30 |
| test | `ACCEPTED (CONFIRMED_SETUP)` | 1 | 1 | 1 | 0 | 100.00% | 1.9670 | 1.9670 |   ⚠️ n<30 |
| validation | `ACCEPTED (CONFIRMED_SETUP)` | 5 | 5 | 4 | 1 | 0.00% | -1.0284 | -1.0284 |   ⚠️ n<30 |

> 12 of 25 groups have fewer than 30 filled trades (⚠️ flagged above). Treat every metric in those groups as descriptive only.

---

No strategy threshold was modified; all CRT parameters are production defaults.
