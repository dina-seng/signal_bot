# SMC Replay — Full-Range Rejection Funnel & Counterfactual

Production path: `resample_ohlc` → `ConfluenceEngine._prepare_market_data` → `SMCStrategy.analyze` → `RiskEngine.calculate_trade_risk` (market geometry) → shared `simulate_outcome` fill/TP1/TP2 friction model. `SMCStrategy` emits no gate or price levels; gates are derived from `ScoreBreakdown` + `metadata` in `_classify_smc()`.

## 1. Data and walk-forward split

| Item | Value |
| :--- | :--- |
| Database | `D:\trade\server\backtest.db` |
| Raw rows / duplicates dropped | 67,043 / 9,355 |
| Full range | 2025-01-01 23:00 → 2026-11-19 05:30 UTC |
| Replay start date | 2025-01-01 UTC |
| Warm-up bars available | 0 |
| Open-market bars available | 44,739 |
| Bar records captured | 44,639 |
| Warmup / insufficient-data skips | 100 / 0 |
| Evaluation errors | 0 |
| Calibration boundary (60%) | 2026-02-17 17:18 UTC |
| Validation boundary (80%) | 2026-07-04 23:24 UTC |
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
| calibration | `CONFIRMED_SETUP` | 1,627 | 1,105 | 522 | 431 |
| calibration | `CONFLUENCE_FLOOR` | 906 | 504 | 402 | 253 |
| calibration | `LTF_PENALTY` | 644 | 445 | 199 | 212 |
| calibration | `PA_FLOOR` | 515 | 340 | 175 | 140 |
| calibration | `SCORE_BELOW_THRESHOLD` | 22,869 | 13,798 | 9,071 | 5,997 |
| test | `CONFIRMED_SETUP` | 515 | 324 | 191 | 141 |
| test | `CONFLUENCE_FLOOR` | 319 | 214 | 105 | 87 |
| test | `LTF_PENALTY` | 221 | 108 | 113 | 72 |
| test | `PA_FLOOR` | 243 | 124 | 119 | 63 |
| test | `SCORE_BELOW_THRESHOLD` | 7,745 | 4,132 | 3,613 | 2,045 |
| validation | `CONFIRMED_SETUP` | 597 | 361 | 236 | 162 |
| validation | `CONFLUENCE_FLOOR` | 521 | 267 | 254 | 146 |
| validation | `LTF_PENALTY` | 239 | 146 | 93 | 73 |
| validation | `PA_FLOOR` | 181 | 89 | 92 | 49 |
| validation | `SCORE_BELOW_THRESHOLD` | 7,497 | 4,147 | 3,350 | 1,963 |

## 3. Counterfactual vs accepted trades

For near-miss rejections the trade is re-priced as if the gate had passed, using the same `RiskEngine` geometry and the same `simulate_outcome` friction. `n` counts de-duplicated trades with valid geometry; `filled` is the subset that filled. Expectancy = average R per filled trade. Near-miss set: LTF penalty (all), fatal conflict (all), score within 5 pts, PA floor within 2 pts, confluence floor within 5 pts.

| Split | Rejection reason | Candidate bars | Opportunities | n | Filled | No fill | Win rate | Avg R | Expectancy | Flag |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| calibration | `ACCEPTED (CONFIRMED_SETUP)` | 1,627 | 431 | 431 | 414 | 0 | 43.24% | 0.2160 | 0.2160 |  |
| calibration | `CONFLUENCE_FLOOR` | 340 | 102 | 102 | 99 | 0 | 24.24% | -0.2444 | -0.2444 |  |
| calibration | `LTF_PENALTY` | 644 | 212 | 212 | 206 | 0 | 39.81% | 0.1867 | 0.1867 |  |
| calibration | `SCORE_BELOW_THRESHOLD` | 1,262 | 355 | 355 | 340 | 0 | 37.35% | 0.1675 | 0.1675 |  |
| test | `ACCEPTED (CONFIRMED_SETUP)` | 515 | 141 | 141 | 137 | 0 | 49.64% | 0.3643 | 0.3643 |  |
| test | `CONFLUENCE_FLOOR` | 85 | 24 | 24 | 23 | 0 | 47.83% | 0.3648 | 0.3648 |   n<30 |
| test | `LTF_PENALTY` | 221 | 72 | 72 | 71 | 0 | 54.93% | 0.2986 | 0.2986 |  |
| test | `SCORE_BELOW_THRESHOLD` | 459 | 130 | 130 | 122 | 0 | 41.80% | 0.0595 | 0.0595 |  |
| validation | `ACCEPTED (CONFIRMED_SETUP)` | 597 | 162 | 162 | 157 | 0 | 40.13% | 0.0608 | 0.0608 |  |
| validation | `CONFLUENCE_FLOOR` | 145 | 41 | 41 | 39 | 0 | 28.21% | -0.2027 | -0.2027 |  |
| validation | `LTF_PENALTY` | 239 | 73 | 73 | 73 | 0 | 30.14% | -0.1657 | -0.1657 |  |
| validation | `SCORE_BELOW_THRESHOLD` | 392 | 111 | 111 | 110 | 0 | 32.73% | -0.0341 | -0.0341 |  |

> 1 of 12 groups have fewer than 30 filled trades (flagged above). Treat every metric in those groups as descriptive only.

## 4. LTF penalty (flat -5.0 pts)

| Split | Bars with LTF penalty applied | Bars that passed all pre-LTF gates |
| :--- | ---: | ---: |
| calibration | 22,232 | 1,932 |
| validation | 7,617 | 735 |
| test | 7,637 | 618 |

---

Live SMC parameters: `DEFAULT_MIN_SCORE=60.0`, `LTF_UNCONFIRMED_PENALTY=5.0`, `DIRECTIONAL_CONFLICT_PENALTY=15.0`. As documented in the Parameter history table, these parameters were introduced in commit 2db6eb1. Prior runs observed validation and test sets; validation and test are no longer clean out-of-sample data.
