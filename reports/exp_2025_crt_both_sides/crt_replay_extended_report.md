# CRT Replay — Full-Range Rejection Funnel & Counterfactual (No Thresholds Changed)

Production path: `resample_ohlc` → `ConfluenceEngine._prepare_market_data` → `StrategyManager.run_all_strategies` → `CRTStrategy` (dedup disabled). Every rejected sweep is counterfactually re-priced through the same `verify_ltf_confirmation` → `calculate_retracement_entry` → `calculate_crt_targets` → `simulate_outcome` logic with its gate ignored.

## 1. Data and walk-forward split

| Item | Value |
| :--- | :--- |
| Database | `..\backtest.db` |
| Raw rows / duplicates dropped | 100,408 / 96 |
| Full range | 2023-03-01 00:00 → 2026-11-15 15:00 UTC |
| Replay start date | 2025-01-01 UTC |
| Warm-up bars available | 43,237 |
| Experiment option | `--crt-both-sides` active (sweep side sets direction, HTF color ignored) |
| Open-market bars replayed | 87,418 |
| Bar records captured | 44,181 |
| Calibration boundary (60%) | 2025-05-21 08:15 UTC |
| Validation boundary (80%) | 2026-02-16 03:00 UTC |

Split windows: calibration = earliest 60% (observation only), validation = next 20%, test = last 20% (untouched). No threshold was tuned on any split.

## 2. Rejection funnel — bars and distinct sweeps by gate and direction

Counts are bar-evaluations (first-failure-wins). A single sweep that survives many bars is counted on every bar; `distinct_sweeps` de-duplicates by the production `sweep_event_key`.

| Split | Gate | Bars | BUY bars | SELL bars | Distinct sweeps |
| :--- | :--- | ---: | ---: | ---: | ---: |
| calibration | `CONFIRMATION_PENDING` | 1,379 | 778 | 601 | 961 |
| calibration | `EXCESSIVE_MANIPULATION` | 236 | 164 | 72 | 190 |
| calibration | `EXCESSIVE_RANGE` | 3 | 3 | 0 | 1 |
| calibration | `MICRO_RANGE` | 67 | 47 | 20 | 49 |
| calibration | `MICRO_SWEEP` | 868 | 475 | 393 | 571 |
| calibration | `NO_SWEEP` | 4,176 | 2,175 | 2,001 | 0 |
| calibration | `TREND_CONFLICT` | 2,068 | 624 | 1,444 | 1,470 |
| test | `CONFIRMATION_PENDING` | 2,768 | 1,390 | 1,378 | 1,994 |
| test | `CONFIRMED_SETUP` | 1 | 1 | 0 | 1 |
| test | `EXCESSIVE_MANIPULATION` | 489 | 243 | 246 | 375 |
| test | `EXCESSIVE_RANGE` | 14 | 8 | 6 | 9 |
| test | `MICRO_RANGE` | 220 | 125 | 95 | 143 |
| test | `MICRO_SWEEP` | 1,719 | 900 | 819 | 1,140 |
| test | `NO_SWEEP` | 8,465 | 4,210 | 4,255 | 0 |
| test | `TREND_CONFLICT` | 3,994 | 2,043 | 1,951 | 2,782 |
| validation | `CONFIRMATION_PENDING` | 2,580 | 1,492 | 1,088 | 1,846 |
| validation | `EXCESSIVE_MANIPULATION` | 519 | 327 | 192 | 367 |
| validation | `EXCESSIVE_RANGE` | 9 | 0 | 9 | 5 |
| validation | `INVALID_ENTRY_ZONE` | 4 | 1 | 3 | 3 |
| validation | `MICRO_RANGE` | 156 | 66 | 90 | 112 |
| validation | `MICRO_SWEEP` | 1,578 | 882 | 696 | 1,052 |
| validation | `NO_SWEEP` | 8,676 | 4,395 | 4,281 | 0 |
| validation | `TREND_CONFLICT` | 4,192 | 1,289 | 2,903 | 2,939 |

## 3. Counterfactual vs accepted trades

For every rejected candidate with a validated sweep, the trade is re-priced as if the gate had passed (same SL/TP/limit-zone logic, same spread). `n` counts trades with valid geometry; `candidates` includes those that could not be re-priced. Expectancy = average R per filled trade.

| Split | Rejection reason | Candidates | n | Filled | No fill | Win rate | Avg R | Expectancy | Flag |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| calibration | `CONFIRMATION_PENDING` | 1,379 | 135 | 68 | 67 | 44.12% | 0.1272 | 0.1272 |  |
| calibration | `EXCESSIVE_MANIPULATION` | 236 | 36 | 25 | 11 | 24.00% | -0.4027 | -0.4027 |   ⚠️ n<30 |
| calibration | `EXCESSIVE_RANGE` | 3 | 0 | 0 | 0 | n/a% | n/a | n/a |   ⚠️ n<30 |
| calibration | `MICRO_RANGE` | 67 | 5 | 5 | 0 | 20.00% | -0.6953 | -0.6953 |   ⚠️ n<30 |
| calibration | `MICRO_SWEEP` | 868 | 68 | 48 | 20 | 35.42% | 0.0985 | 0.0985 |  |
| calibration | `TREND_CONFLICT` | 2,068 | 134 | 84 | 50 | 34.52% | -0.1031 | -0.1031 |  |
| test | `CONFIRMATION_PENDING` | 2,768 | 215 | 131 | 84 | 32.06% | -0.1546 | -0.1546 |  |
| test | `EXCESSIVE_MANIPULATION` | 489 | 63 | 27 | 36 | 7.41% | -0.7681 | -0.7681 |   ⚠️ n<30 |
| test | `EXCESSIVE_RANGE` | 14 | 5 | 3 | 2 | 100.00% | 0.7043 | 0.7043 |   ⚠️ n<30 |
| test | `MICRO_RANGE` | 220 | 8 | 5 | 3 | 20.00% | -0.4501 | -0.4501 |   ⚠️ n<30 |
| test | `MICRO_SWEEP` | 1,719 | 124 | 76 | 48 | 38.16% | -0.1439 | -0.1439 |  |
| test | `TREND_CONFLICT` | 3,994 | 319 | 202 | 117 | 28.22% | -0.2505 | -0.2505 |  |
| validation | `CONFIRMATION_PENDING` | 2,580 | 288 | 190 | 98 | 36.84% | -0.1251 | -0.1251 |  |
| validation | `EXCESSIVE_MANIPULATION` | 519 | 61 | 33 | 28 | 27.27% | -0.3382 | -0.3382 |  |
| validation | `EXCESSIVE_RANGE` | 9 | 0 | 0 | 0 | n/a% | n/a | n/a |   ⚠️ n<30 |
| validation | `INVALID_ENTRY_ZONE` | 4 | 0 | 0 | 0 | n/a% | n/a | n/a |   ⚠️ n<30 |
| validation | `MICRO_RANGE` | 156 | 26 | 16 | 10 | 12.50% | -1.0521 | -1.0521 |   ⚠️ n<30 |
| validation | `MICRO_SWEEP` | 1,578 | 124 | 82 | 42 | 36.59% | -0.0736 | -0.0736 |  |
| validation | `TREND_CONFLICT` | 4,192 | 336 | 202 | 134 | 35.15% | -0.1497 | -0.1497 |  |
| test | `ACCEPTED (CONFIRMED_SETUP)` | 1 | 1 | 0 | 1 | n/a% | n/a | n/a |   ⚠️ n<30 |

> 10 of 20 groups have fewer than 30 filled trades (⚠️ flagged above). Treat every metric in those groups as descriptive only.

---

No strategy threshold was modified; all CRT parameters are production defaults.
