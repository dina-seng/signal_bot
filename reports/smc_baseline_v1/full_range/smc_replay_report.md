# SMC Replay — Full-Range Rejection Funnel & Counterfactual

Production path: `resample_ohlc` → `ConfluenceEngine._prepare_market_data` → `SMCStrategy.analyze` → `RiskManager.calculate_trade_risk` (market geometry) → shared `simulate_outcome` fill/TP1/TP2 friction model. `SMCStrategy` emits no gate or price levels; gates are derived from `ScoreBreakdown` + `metadata` in `_classify_smc()`.

## 1. Data and walk-forward split

| Item | Value |
| :--- | :--- |
| Database | `D:\trade\backtest.db` |
| Raw rows / duplicates dropped | 110,280 / 9,355 |
| Full range | 2023-03-01 00:00 → 2026-11-19 05:30 UTC |
| Open-market bars available | 87,976 |
| Bar records captured | 87,876 |
| Warmup / insufficient-data skips | 100 / 0 |
| Evaluation errors | 0 |
| Calibration boundary (60%) | 2025-05-24 12:54 UTC |
| Validation boundary (80%) | 2026-02-20 09:12 UTC |
| Round-trip execution cost | 0.40 price units per position unit, round trip (deducted once per trade) |

Split windows: calibration = earliest 60% (observation only), validation = next 20%, test = last 20%. NOTE: Validation and test splits were previously observed during earlier exploratory runs (commits 4424a64, 5b88873, 2db6eb1) and are no longer clean out-of-sample data.

### Live SMC parameters

| Parameter | Value | Location in code |
| :--- | :--- | :--- |
| `DEFAULT_MIN_SCORE` | 60.0 | `server/app/services/strategies/smc_strategy.py:30` |
| `LTF_UNCONFIRMED_PENALTY` | 5.0 pts | `server/app/services/strategies/smc_strategy.py:34` |
| `DIRECTIONAL_CONFLICT_PENALTY` | 15.0 pts | `server/app/services/signals/evaluators.py:31` |
| `PA_FLOOR` | 10.0 pts | `server/app/services/signals/evaluators.py:526` |
| `CONFLUENCE_FLOOR` | 20.0 pts | `server/app/services/signals/evaluators.py:544` |

### Parameter history

| Change | Commit | Date | Split basis cited | Evidence / Citation |
| :--- | :--- | :--- | :--- | :--- |
| Initial 3-pillar SMC migration from ConfluenceEngine (`MIN_SETUP_SCORE=75`, BUY LTF `* 0.9`, SELL LTF `* 0.3`, 2+ conflict hard veto) | `19d283b` | 2026-11-17 | UNVERIFIED | Commit message: `feat: add SMC strategy implementation migrated from ConfluenceEngine` |
| BUY LTF multiplier updated: `* 0.9` -> `* 0.5` | `4424a64` | 2026-11-17 | UNVERIFIED | Commit message: `feat: add smc strategy replay reports and checkpoints` |
| SELL LTF multiplier updated: `* 0.3` -> `* 0.5` | `5b88873` | 2026-11-17 | UNVERIFIED | Commit message: `feat: add smc replay extended reports and update smc strategy` |
| Directional conflict hard veto replaced by flat -15 deduction (`DIRECTIONAL_CONFLICT_PENALTY = 15.0`) | `2db6eb1` | 2026-11-17 | Calibration | Code comment `server/app/services/signals/evaluators.py:560-569`: Counterfactual replay on calibration split (+0.15R expectancy over 3,496 opps) |
| LTF unconfirmed penalty replaced 0.5x slash with flat deduction (`LTF_UNCONFIRMED_PENALTY = 5.0`) | `2db6eb1` | 2026-11-17 | UNVERIFIED | Code comment `server/app/services/strategies/smc_strategy.py:32-34`: replaces 0.5x slash; no split cited |
| Minimum qualification score lowered from 75 to 60 (`DEFAULT_MIN_SCORE = 60.0`) | `2db6eb1` | 2026-11-17 | UNVERIFIED | Code comment `server/app/services/strategies/smc_strategy.py:28-30`: widens band to B-tier; no split cited |

## 2. Rejection funnel — bars, opportunities and direction

Counts are bar-evaluations (first-failure-wins). All 15m bars inside the same closed 1h candle share one `opportunity_key`, so `distinct_opportunities` removes the 15m repeat.

| Split | Gate | Bars | BUY bars | SELL bars | Distinct opportunities |
| :--- | :--- | ---: | ---: | ---: | ---: |
| calibration | `CONFIRMED_SETUP` | 3,636 | 2,464 | 1,172 | 936 |
| calibration | `CONFLUENCE_FLOOR` | 2,038 | 1,129 | 909 | 539 |
| calibration | `LTF_PENALTY` | 1,732 | 1,059 | 673 | 491 |
| calibration | `PA_FLOOR` | 1,105 | 588 | 517 | 285 |
| calibration | `SCORE_BELOW_THRESHOLD` | 43,656 | 24,890 | 18,766 | 11,123 |
| test | `CONFIRMED_SETUP` | 1,107 | 684 | 423 | 288 |
| test | `CONFLUENCE_FLOOR` | 811 | 480 | 331 | 208 |
| test | `LTF_PENALTY` | 441 | 231 | 210 | 127 |
| test | `PA_FLOOR` | 414 | 200 | 214 | 106 |
| test | `SCORE_BELOW_THRESHOLD` | 15,062 | 8,179 | 6,883 | 3,833 |
| validation | `CONFIRMED_SETUP` | 1,075 | 692 | 383 | 274 |
| validation | `CONFLUENCE_FLOOR` | 592 | 364 | 228 | 156 |
| validation | `LTF_PENALTY` | 485 | 338 | 147 | 140 |
| validation | `PA_FLOOR` | 361 | 249 | 112 | 94 |
| validation | `SCORE_BELOW_THRESHOLD` | 15,361 | 9,222 | 6,139 | 3,921 |

## 3. Counterfactual vs accepted trades

For near-miss rejections the trade is re-priced as if the gate had passed, using the same `RiskManager` geometry and the same `simulate_outcome` friction. `n` counts de-duplicated trades with valid geometry; `filled` is the subset that filled. Expectancy = average R per filled trade. Near-miss set: LTF penalty (all), fatal conflict (all), score within 5 pts, PA floor within 2 pts, confluence floor within 5 pts.

| Split | Rejection reason | Candidate bars | Opportunities | n | Filled | No fill | Win rate | Avg R | Expectancy | Flag |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| calibration | `ACCEPTED (CONFIRMED_SETUP)` | 3,636 | 936 | 936 | 888 | 0 | 42.23% | 0.0225 | 0.0225 |  |
| calibration | `CONFLUENCE_FLOOR` | 740 | 209 | 209 | 205 | 0 | 35.12% | -0.0860 | -0.0860 |  |
| calibration | `LTF_PENALTY` | 1,732 | 491 | 491 | 476 | 0 | 38.24% | -0.0922 | -0.0922 |  |
| calibration | `SCORE_BELOW_THRESHOLD` | 2,844 | 803 | 803 | 770 | 0 | 47.14% | 0.1725 | 0.1725 |  |
| test | `ACCEPTED (CONFIRMED_SETUP)` | 1,107 | 288 | 288 | 279 | 0 | 43.73% | 0.1088 | 0.1088 |  |
| test | `CONFLUENCE_FLOOR` | 226 | 59 | 59 | 56 | 0 | 33.93% | -0.1171 | -0.1171 |  |
| test | `LTF_PENALTY` | 441 | 127 | 127 | 126 | 0 | 42.86% | -0.0046 | -0.0046 |  |
| test | `SCORE_BELOW_THRESHOLD` | 851 | 241 | 241 | 232 | 0 | 39.66% | -0.0163 | -0.0163 |  |
| validation | `ACCEPTED (CONFIRMED_SETUP)` | 1,075 | 274 | 274 | 266 | 0 | 48.12% | 0.2652 | 0.2652 |  |
| validation | `CONFLUENCE_FLOOR` | 185 | 53 | 53 | 52 | 0 | 34.62% | -0.0251 | -0.0251 |  |
| validation | `LTF_PENALTY` | 485 | 140 | 140 | 134 | 0 | 52.99% | 0.4876 | 0.4876 |  |
| validation | `SCORE_BELOW_THRESHOLD` | 881 | 249 | 249 | 238 | 0 | 39.50% | 0.0932 | 0.0932 |  |

> 0 of 12 groups have fewer than 30 filled trades (flagged above). Treat every metric in those groups as descriptive only.

## 4. LTF penalty (flat -5.0 pts)

| Split | Bars with LTF penalty applied | Bars that passed all pre-LTF gates |
| :--- | ---: | ---: |
| calibration | 44,157 | 4,564 |
| validation | 14,966 | 1,359 |
| test | 15,062 | 1,315 |

---

Live SMC parameters: `DEFAULT_MIN_SCORE=60.0`, `LTF_UNCONFIRMED_PENALTY=5.0`, `DIRECTIONAL_CONFLICT_PENALTY=15.0`. As documented in the Parameter history table, these parameters were introduced in commit 2db6eb1. Prior runs observed validation and test sets; validation and test are no longer clean out-of-sample data.
