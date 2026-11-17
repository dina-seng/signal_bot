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
| calibration | `CONFLUENCE_FLOOR` | 2,250 | 1,534 | 716 | 587 |
| calibration | `FATAL_CONFLICT` | 13,624 | 9,821 | 3,803 | 3,496 |
| calibration | `LTF_PENALTY` | 631 | 434 | 197 | 169 |
| calibration | `PA_FLOOR` | 998 | 599 | 399 | 251 |
| calibration | `SCORE_BELOW_THRESHOLD` | 34,327 | 21,454 | 12,873 | 8,641 |
| test | `CONFIRMED_SETUP` | 10 | 10 | 0 | 4 |
| test | `CONFLUENCE_FLOOR` | 914 | 663 | 251 | 232 |
| test | `FATAL_CONFLICT` | 4,618 | 3,274 | 1,344 | 1,191 |
| test | `LTF_PENALTY` | 199 | 118 | 81 | 59 |
| test | `PA_FLOOR` | 355 | 227 | 128 | 89 |
| test | `SCORE_BELOW_THRESHOLD` | 11,574 | 6,724 | 4,850 | 2,919 |
| validation | `CONFIRMED_SETUP` | 20 | 10 | 10 | 6 |
| validation | `CONFLUENCE_FLOOR` | 640 | 402 | 238 | 169 |
| validation | `FATAL_CONFLICT` | 5,009 | 3,788 | 1,221 | 1,292 |
| validation | `LTF_PENALTY` | 178 | 102 | 76 | 50 |
| validation | `PA_FLOOR` | 287 | 211 | 76 | 73 |
| validation | `SCORE_BELOW_THRESHOLD` | 11,580 | 7,460 | 4,120 | 2,916 |

## 3. Counterfactual vs accepted trades

For near-miss rejections the trade is re-priced as if the gate had passed, using the same `RiskManager` geometry and the same `simulate_outcome` friction. `n` counts de-duplicated trades with valid geometry; `filled` is the subset that filled. Expectancy = average R per filled trade. Near-miss set: LTF penalty (all), fatal conflict (all), score within 5 pts, PA floor within 2 pts, confluence floor within 5 pts.

| Split | Rejection reason | Candidate bars | Opportunities | n | Filled | No fill | Win rate | Avg R | Expectancy | Flag |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| calibration | `ACCEPTED (CONFIRMED_SETUP)` | 104 | 29 | 29 | 29 | 0 | 34.48% | -0.0423 | -0.0423 |   n<30 |
| calibration | `CONFLUENCE_FLOOR` | 799 | 222 | 222 | 222 | 0 | 40.54% | 0.0212 | 0.0212 |  |
| calibration | `FATAL_CONFLICT` | 13,624 | 3,496 | 3,496 | 3,496 | 0 | 44.16% | 0.1503 | 0.1503 |  |
| calibration | `LTF_PENALTY` | 631 | 169 | 169 | 169 | 0 | 42.60% | 0.0411 | 0.0411 |  |
| calibration | `SCORE_BELOW_THRESHOLD` | 1,046 | 286 | 286 | 286 | 0 | 39.86% | -0.0252 | -0.0252 |  |
| test | `ACCEPTED (CONFIRMED_SETUP)` | 10 | 4 | 4 | 4 | 0 | 75.00% | 0.5967 | 0.5967 |   n<30 |
| test | `CONFLUENCE_FLOOR` | 159 | 42 | 42 | 42 | 0 | 30.95% | -0.1535 | -0.1535 |  |
| test | `FATAL_CONFLICT` | 4,618 | 1,191 | 1,191 | 1,191 | 0 | 37.87% | 0.0030 | 0.0030 |  |
| test | `LTF_PENALTY` | 199 | 59 | 59 | 59 | 0 | 54.24% | 0.4169 | 0.4169 |  |
| test | `SCORE_BELOW_THRESHOLD` | 282 | 85 | 85 | 85 | 0 | 38.82% | -0.1063 | -0.1063 |  |
| validation | `ACCEPTED (CONFIRMED_SETUP)` | 20 | 6 | 6 | 6 | 0 | 16.67% | -0.7888 | -0.7888 |   n<30 |
| validation | `CONFLUENCE_FLOOR` | 180 | 52 | 52 | 52 | 0 | 28.85% | -0.2115 | -0.2115 |  |
| validation | `FATAL_CONFLICT` | 5,009 | 1,292 | 1,292 | 1,292 | 0 | 42.41% | 0.2022 | 0.2022 |  |
| validation | `LTF_PENALTY` | 178 | 50 | 50 | 50 | 0 | 46.00% | 0.0958 | 0.0958 |  |
| validation | `SCORE_BELOW_THRESHOLD` | 293 | 81 | 81 | 81 | 0 | 43.21% | 0.1673 | 0.1673 |  |

> 3 of 15 groups have fewer than 30 filled trades (flagged above). Treat every metric in those groups as descriptive only.

## 4. LTF 70% penalty

| Split | Bars with LTF penalty applied | Bars that passed all pre-LTF gates |
| :--- | ---: | ---: |
| calibration | 42,648 | 631 |
| validation | 14,443 | 178 |
| test | 14,500 | 199 |

---

No strategy threshold, scoring weight, evaluator floor or RiskManager default was modified; all SMC parameters are production defaults.
