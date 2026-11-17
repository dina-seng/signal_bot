# SMC Replay — Full-Range Rejection Funnel & Counterfactual (No Thresholds Changed)

Production path: `resample_ohlc` → `ConfluenceEngine._prepare_market_data` → `SMCStrategy.analyze` → `RiskManager.calculate_trade_risk` (market geometry) → shared `simulate_outcome` fill/TP1/TP2 friction model. `SMCStrategy` emits no gate or price levels; gates are derived from `ScoreBreakdown` + `metadata` in `_classify_smc()`.

## 1. Data and walk-forward split

| Item | Value |
| :--- | :--- |
| Database | `D:\trade\backtest.db` |
| Raw rows / duplicates dropped | 100,408 / 96 |
| Full range | 2023-03-01 00:00 → 2026-11-15 15:00 UTC |
| Open-market bars available | 87,418 |
| Bar records captured | 5,772 |
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
| calibration | `CONFLUENCE_FLOOR` | 187 | 84 | 103 | 53 |
| calibration | `FATAL_CONFLICT` | 1,190 | 667 | 523 | 313 |
| calibration | `LTF_PENALTY` | 74 | 48 | 26 | 19 |
| calibration | `PA_FLOOR` | 140 | 80 | 60 | 35 |
| calibration | `SCORE_BELOW_THRESHOLD` | 4,181 | 2,423 | 1,758 | 1,041 |

## 3. Counterfactual vs accepted trades

For near-miss rejections the trade is re-priced as if the gate had passed, using the same `RiskManager` geometry and the same `simulate_outcome` friction. `n` counts de-duplicated trades with valid geometry; `filled` is the subset that filled. Expectancy = average R per filled trade. Near-miss set: LTF penalty (all), fatal conflict (all), score within 5 pts, PA floor within 2 pts, confluence floor within 5 pts.

| Split | Rejection reason | Candidate bars | Opportunities | n | Filled | No fill | Win rate | Avg R | Expectancy | Flag |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| calibration | `CONFLUENCE_FLOOR` | 86 | 26 | 26 | 26 | 0 | 26.92% | -0.3440 | -0.3440 |   n<30 |
| calibration | `FATAL_CONFLICT` | 1,190 | 313 | 313 | 313 | 0 | 53.35% | 0.3661 | 0.3661 |  |
| calibration | `LTF_PENALTY` | 74 | 19 | 19 | 19 | 0 | 26.32% | -0.3074 | -0.3074 |   n<30 |
| calibration | `SCORE_BELOW_THRESHOLD` | 138 | 32 | 32 | 32 | 0 | 34.38% | -0.0320 | -0.0320 |  |

> 2 of 4 groups have fewer than 30 filled trades (flagged above). Treat every metric in those groups as descriptive only.

## 4. LTF 70% penalty

| Split | Bars with LTF penalty applied | Bars that passed all pre-LTF gates |
| :--- | ---: | ---: |
| calibration | 4,711 | 74 |
| validation | 0 | 0 |
| test | 0 | 0 |

---

No strategy threshold, scoring weight, evaluator floor or RiskManager default was modified; all SMC parameters are production defaults.
