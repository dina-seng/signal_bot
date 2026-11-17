# SMC Replay — Full-Range Rejection Funnel & Counterfactual (No Thresholds Changed)

Production path: `resample_ohlc` → `ConfluenceEngine._prepare_market_data` → `SMCStrategy.analyze` → `RiskManager.calculate_trade_risk` (market geometry) → shared `simulate_outcome` fill/TP1/TP2 friction model. `SMCStrategy` emits no gate or price levels; gates are derived from `ScoreBreakdown` + `metadata` in `_classify_smc()`.

## 1. Data and walk-forward split

| Item | Value |
| :--- | :--- |
| Database | `D:\trade\backtest.db` |
| Raw rows / duplicates dropped | 100,408 / 96 |
| Full range | 2023-03-01 00:00 → 2026-11-15 15:00 UTC |
| Open-market bars available | 87,418 |
| Bar records captured | 87,318 |
| Warmup / insufficient-data skips | 100 / 0 |
| Evaluation errors | 0 |
| Calibration boundary (60%) | 2025-05-21 08:15 UTC |
| Validation boundary (80%) | 2026-02-16 03:00 UTC |
| Round-trip friction | \$0.40 per completed trade |

Split windows: calibration = earliest 60% (observation only), validation = next 20%, test = last 20% (untouched). No threshold or weight was tuned on any split.

## 2. Rejection funnel — bars, opportunities and direction

Counts are bar-evaluations (first-failure-wins). All 15m bars inside the same closed 1h candle share one `opportunity_key`, so `distinct_opportunities` removes the 15m repeat.

| Split | Gate | Bars | BUY bars | SELL bars | Distinct opportunities |
| :--- | :--- | ---: | ---: | ---: | ---: |
| calibration | `CONFIRMED_SETUP` | 104 | 66 | 38 | 29 |
| calibration | `CONFLUENCE_FLOOR` | 2,118 | 1,192 | 926 | 559 |
| calibration | `FATAL_CONFLICT` | 13,411 | 7,144 | 6,267 | 3,461 |
| calibration | `LTF_PENALTY` | 631 | 434 | 197 | 169 |
| calibration | `PA_FLOOR` | 992 | 547 | 445 | 250 |
| calibration | `SCORE_BELOW_THRESHOLD` | 34,678 | 20,648 | 14,030 | 8,725 |
| test | `CONFIRMED_SETUP` | 10 | 10 | 0 | 4 |
| test | `CONFLUENCE_FLOOR` | 862 | 524 | 338 | 221 |
| test | `FATAL_CONFLICT` | 4,602 | 2,365 | 2,237 | 1,186 |
| test | `LTF_PENALTY` | 199 | 118 | 81 | 59 |
| test | `PA_FLOOR` | 344 | 192 | 152 | 86 |
| test | `SCORE_BELOW_THRESHOLD` | 11,653 | 6,439 | 5,214 | 2,934 |
| validation | `CONFIRMED_SETUP` | 20 | 10 | 10 | 6 |
| validation | `CONFLUENCE_FLOOR` | 601 | 319 | 282 | 158 |
| validation | `FATAL_CONFLICT` | 4,957 | 2,714 | 2,243 | 1,272 |
| validation | `LTF_PENALTY` | 178 | 102 | 76 | 50 |
| validation | `PA_FLOOR` | 280 | 196 | 84 | 71 |
| validation | `SCORE_BELOW_THRESHOLD` | 11,678 | 7,291 | 4,387 | 2,942 |

## 3. Counterfactual vs accepted trades

For near-miss rejections the trade is re-priced as if the gate had passed, using the same `RiskManager` geometry and the same `simulate_outcome` friction. `n` counts de-duplicated trades with valid geometry; `filled` is the subset that filled. Expectancy = average R per filled trade. Near-miss set: LTF penalty (all), fatal conflict (all), score within 5 pts, PA floor within 2 pts, confluence floor within 5 pts.

| Split | Rejection reason | Candidate bars | Opportunities | n | Filled | No fill | Win rate | Avg R | Expectancy | Flag |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| calibration | `ACCEPTED (CONFIRMED_SETUP)` | 104 | 29 | 29 | 29 | 0 | 34.48% | -0.0423 | -0.0423 |   n<30 |
| calibration | `CONFLUENCE_FLOOR` | 785 | 219 | 219 | 219 | 0 | 39.73% | -0.0125 | -0.0125 |  |
| calibration | `FATAL_CONFLICT` | 13,411 | 3,461 | 3,461 | 3,461 | 0 | 40.08% | 0.0342 | 0.0342 |  |
| calibration | `LTF_PENALTY` | 631 | 169 | 169 | 169 | 0 | 42.60% | 0.0411 | 0.0411 |  |
| calibration | `SCORE_BELOW_THRESHOLD` | 1,046 | 286 | 286 | 286 | 0 | 39.86% | -0.0252 | -0.0252 |  |
| test | `ACCEPTED (CONFIRMED_SETUP)` | 10 | 4 | 4 | 4 | 0 | 75.00% | 0.5967 | 0.5967 |   n<30 |
| test | `CONFLUENCE_FLOOR` | 178 | 47 | 47 | 47 | 0 | 29.79% | -0.1714 | -0.1714 |  |
| test | `FATAL_CONFLICT` | 4,602 | 1,186 | 1,186 | 1,186 | 0 | 39.12% | 0.0420 | 0.0420 |  |
| test | `LTF_PENALTY` | 199 | 59 | 59 | 59 | 0 | 54.24% | 0.4169 | 0.4169 |  |
| test | `SCORE_BELOW_THRESHOLD` | 282 | 85 | 85 | 85 | 0 | 38.82% | -0.1063 | -0.1063 |  |
| validation | `ACCEPTED (CONFIRMED_SETUP)` | 20 | 6 | 6 | 6 | 0 | 16.67% | -0.7888 | -0.7888 |   n<30 |
| validation | `CONFLUENCE_FLOOR` | 182 | 52 | 52 | 52 | 0 | 26.92% | -0.2847 | -0.2847 |  |
| validation | `FATAL_CONFLICT` | 4,957 | 1,272 | 1,272 | 1,272 | 0 | 36.95% | 0.0399 | 0.0399 |  |
| validation | `LTF_PENALTY` | 178 | 50 | 50 | 50 | 0 | 46.00% | 0.0958 | 0.0958 |  |
| validation | `SCORE_BELOW_THRESHOLD` | 293 | 81 | 81 | 81 | 0 | 43.21% | 0.1673 | 0.1673 |  |

> 3 of 15 groups have fewer than 30 filled trades (flagged above). Treat every metric in those groups as descriptive only.

## 4. LTF 70% penalty

| Split | Bars with LTF penalty applied | Bars that passed all pre-LTF gates |
| :--- | ---: | ---: |
| calibration | 42,216 | 631 |
| validation | 14,290 | 178 |
| test | 14,284 | 199 |

---

No strategy threshold, scoring weight, evaluator floor or RiskManager default was modified; all SMC parameters are production defaults.
