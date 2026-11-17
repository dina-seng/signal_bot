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
| calibration | `CONFIRMED_SETUP` | 149 | 111 | 38 | 44 |
| calibration | `CONFLUENCE_FLOOR` | 2,342 | 1,841 | 501 | 607 |
| calibration | `FATAL_CONFLICT` | 15,110 | 13,046 | 2,064 | 3,849 |
| calibration | `LTF_PENALTY` | 586 | 389 | 197 | 159 |
| calibration | `PA_FLOOR` | 1,041 | 691 | 350 | 261 |
| calibration | `SCORE_BELOW_THRESHOLD` | 32,706 | 21,809 | 10,897 | 8,237 |
| test | `CONFIRMED_SETUP` | 23 | 23 | 0 | 8 |
| test | `CONFLUENCE_FLOOR` | 987 | 814 | 173 | 252 |
| test | `FATAL_CONFLICT` | 5,068 | 4,388 | 680 | 1,292 |
| test | `LTF_PENALTY` | 186 | 105 | 81 | 56 |
| test | `PA_FLOOR` | 379 | 255 | 124 | 97 |
| test | `SCORE_BELOW_THRESHOLD` | 11,027 | 6,810 | 4,217 | 2,783 |
| validation | `CONFIRMED_SETUP` | 38 | 28 | 10 | 11 |
| validation | `CONFLUENCE_FLOOR` | 630 | 465 | 165 | 166 |
| validation | `FATAL_CONFLICT` | 5,680 | 5,141 | 539 | 1,447 |
| validation | `LTF_PENALTY` | 160 | 84 | 76 | 46 |
| validation | `PA_FLOOR` | 281 | 233 | 48 | 71 |
| validation | `SCORE_BELOW_THRESHOLD` | 10,925 | 7,521 | 3,404 | 2,755 |

## 3. Counterfactual vs accepted trades

For near-miss rejections the trade is re-priced as if the gate had passed, using the same `RiskManager` geometry and the same `simulate_outcome` friction. `n` counts de-duplicated trades with valid geometry; `filled` is the subset that filled. Expectancy = average R per filled trade. Near-miss set: LTF penalty (all), fatal conflict (all), score within 5 pts, PA floor within 2 pts, confluence floor within 5 pts.

| Split | Rejection reason | Candidate bars | Opportunities | n | Filled | No fill | Win rate | Avg R | Expectancy | Flag |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| calibration | `ACCEPTED (CONFIRMED_SETUP)` | 149 | 44 | 44 | 44 | 0 | 31.82% | -0.1231 | -0.1231 |  |
| calibration | `CONFLUENCE_FLOOR` | 806 | 223 | 223 | 223 | 0 | 43.95% | 0.1403 | 0.1403 |  |
| calibration | `FATAL_CONFLICT` | 15,110 | 3,849 | 3,849 | 3,849 | 0 | 46.25% | 0.2187 | 0.2187 |  |
| calibration | `LTF_PENALTY` | 586 | 159 | 159 | 159 | 0 | 44.03% | 0.0751 | 0.0751 |  |
| calibration | `SCORE_BELOW_THRESHOLD` | 1,046 | 286 | 286 | 286 | 0 | 39.86% | -0.0252 | -0.0252 |  |
| test | `ACCEPTED (CONFIRMED_SETUP)` | 23 | 8 | 8 | 8 | 0 | 87.50% | 1.4947 | 1.4947 |   n<30 |
| test | `CONFLUENCE_FLOOR` | 147 | 39 | 39 | 39 | 0 | 35.90% | 0.0023 | 0.0023 |  |
| test | `FATAL_CONFLICT` | 5,068 | 1,292 | 1,292 | 1,292 | 0 | 33.82% | -0.1089 | -0.1089 |  |
| test | `LTF_PENALTY` | 186 | 56 | 56 | 56 | 0 | 51.79% | 0.3129 | 0.3129 |  |
| test | `SCORE_BELOW_THRESHOLD` | 282 | 85 | 85 | 85 | 0 | 38.82% | -0.1063 | -0.1063 |  |
| validation | `ACCEPTED (CONFIRMED_SETUP)` | 38 | 11 | 11 | 11 | 0 | 54.55% | 0.4699 | 0.4699 |   n<30 |
| validation | `CONFLUENCE_FLOOR` | 169 | 50 | 50 | 50 | 0 | 38.00% | 0.0151 | 0.0151 |  |
| validation | `FATAL_CONFLICT` | 5,680 | 1,447 | 1,447 | 1,447 | 0 | 44.99% | 0.2805 | 0.2805 |  |
| validation | `LTF_PENALTY` | 160 | 46 | 46 | 46 | 0 | 41.30% | -0.0570 | -0.0570 |  |
| validation | `SCORE_BELOW_THRESHOLD` | 293 | 81 | 81 | 81 | 0 | 43.21% | 0.1673 | 0.1673 |  |

> 2 of 15 groups have fewer than 30 filled trades (flagged above). Treat every metric in those groups as descriptive only.

## 4. LTF 70% penalty

| Split | Bars with LTF penalty applied | Bars that passed all pre-LTF gates |
| :--- | ---: | ---: |
| calibration | 43,209 | 631 |
| validation | 14,692 | 178 |
| test | 14,744 | 199 |

---

No strategy threshold, scoring weight, evaluator floor or RiskManager default was modified; all SMC parameters are production defaults.
