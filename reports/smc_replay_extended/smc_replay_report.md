# SMC Replay — Full-Range Rejection Funnel & Counterfactual

Production path: `resample_ohlc` → `ConfluenceEngine._prepare_market_data` → `SMCStrategy.analyze` → `RiskManager.calculate_trade_risk` (market geometry) → shared `simulate_outcome` fill/TP1/TP2 friction model. `SMCStrategy` emits no gate or price levels; gates are derived from `ScoreBreakdown` + `metadata` in `_classify_smc()`.

## 1. Data and walk-forward split

| Item | Value |
| :--- | :--- |
| Database | `D:\trade\backtest.db` |
| Raw rows / duplicates dropped | 100,408 / 96 |
| Full range | 2023-03-01 00:00 → 2026-11-15 15:00 UTC |
| Open-market bars available | 87,418 |
| Bar records captured | 87,318 |
| Warmup / insufficient-data skips | 0 / 0 |
| Evaluation errors | 0 |
| Calibration boundary (60%) | 2025-05-21 08:15 UTC |
| Validation boundary (80%) | 2026-02-16 03:00 UTC |
| Round-trip friction | \$0.40 per completed trade |

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
| calibration | `CONFIRMED_SETUP` | 3,617 | 2,445 | 1,172 | 932 |
| calibration | `CONFLUENCE_FLOOR` | 2,038 | 1,129 | 909 | 539 |
| calibration | `LTF_PENALTY` | 1,728 | 1,059 | 669 | 490 |
| calibration | `PA_FLOOR` | 1,105 | 588 | 517 | 285 |
| calibration | `SCORE_BELOW_THRESHOLD` | 43,446 | 24,744 | 18,702 | 11,072 |
| test | `CONFIRMED_SETUP` | 1,127 | 668 | 459 | 293 |
| test | `CONFLUENCE_FLOOR` | 860 | 508 | 352 | 221 |
| test | `LTF_PENALTY` | 455 | 251 | 204 | 130 |
| test | `PA_FLOOR` | 418 | 200 | 218 | 107 |
| test | `SCORE_BELOW_THRESHOLD` | 14,810 | 8,030 | 6,780 | 3,770 |
| validation | `CONFIRMED_SETUP` | 1,046 | 703 | 343 | 266 |
| validation | `CONFLUENCE_FLOOR` | 527 | 320 | 207 | 139 |
| validation | `LTF_PENALTY` | 465 | 322 | 143 | 135 |
| validation | `PA_FLOOR` | 349 | 237 | 112 | 91 |
| validation | `SCORE_BELOW_THRESHOLD` | 15,327 | 9,236 | 6,091 | 3,909 |

## 3. Counterfactual vs accepted trades

For near-miss rejections the trade is re-priced as if the gate had passed, using the same `RiskManager` geometry and the same `simulate_outcome` friction. `n` counts de-duplicated trades with valid geometry; `filled` is the subset that filled. Expectancy = average R per filled trade. Near-miss set: LTF penalty (all), fatal conflict (all), score within 5 pts, PA floor within 2 pts, confluence floor within 5 pts.

| Split | Rejection reason | Candidate bars | Opportunities | n | Filled | No fill | Win rate | Avg R | Expectancy | Flag |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| calibration | `ACCEPTED (CONFIRMED_SETUP)` | 3,617 | 932 | 932 | 932 | 0 | 42.38% | 0.0342 | 0.0342 |  |
| calibration | `CONFLUENCE_FLOOR` | 740 | 209 | 209 | 209 | 0 | 35.89% | -0.0721 | -0.0721 |  |
| calibration | `LTF_PENALTY` | 1,728 | 490 | 490 | 490 | 0 | 37.76% | -0.1083 | -0.1083 |  |
| calibration | `SCORE_BELOW_THRESHOLD` | 2,817 | 797 | 797 | 797 | 0 | 47.05% | 0.1718 | 0.1718 |  |
| test | `ACCEPTED (CONFIRMED_SETUP)` | 1,127 | 293 | 293 | 293 | 0 | 43.00% | 0.0716 | 0.0716 |  |
| test | `CONFLUENCE_FLOOR` | 222 | 58 | 58 | 58 | 0 | 32.76% | -0.1587 | -0.1587 |  |
| test | `LTF_PENALTY` | 455 | 130 | 130 | 130 | 0 | 41.54% | -0.0730 | -0.0730 |  |
| test | `SCORE_BELOW_THRESHOLD` | 799 | 227 | 227 | 227 | 0 | 37.89% | -0.0113 | -0.0113 |  |
| validation | `ACCEPTED (CONFIRMED_SETUP)` | 1,046 | 266 | 266 | 266 | 0 | 49.25% | 0.2999 | 0.2999 |  |
| validation | `CONFLUENCE_FLOOR` | 185 | 53 | 53 | 53 | 0 | 33.96% | -0.0473 | -0.0473 |  |
| validation | `LTF_PENALTY` | 465 | 135 | 135 | 135 | 0 | 50.37% | 0.4349 | 0.4349 |  |
| validation | `SCORE_BELOW_THRESHOLD` | 896 | 253 | 253 | 253 | 0 | 39.13% | 0.1104 | 0.1104 |  |

> 0 of 12 groups have fewer than 30 filled trades (flagged above). Treat every metric in those groups as descriptive only.

## 4. LTF penalty (flat -5.0 pts)

| Split | Bars with LTF penalty applied | Bars that passed all pre-LTF gates |
| :--- | ---: | ---: |
| calibration | 43,964 | 4,545 |
| validation | 14,831 | 1,322 |
| test | 14,923 | 1,341 |

---

Live SMC parameters: `DEFAULT_MIN_SCORE=60.0`, `LTF_UNCONFIRMED_PENALTY=5.0`, `DIRECTIONAL_CONFLICT_PENALTY=15.0`. As documented in the Parameter history table, these parameters were introduced in commit 2db6eb1. Prior runs observed validation and test sets; validation and test are no longer clean out-of-sample data.
