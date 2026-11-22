# SMC Replay — Full-Range Rejection Funnel & Counterfactual

Production path: `resample_ohlc` → `ConfluenceEngine._prepare_market_data` → `SMCStrategy.analyze` → `RiskManager.calculate_trade_risk` (market geometry) → shared `simulate_outcome` fill/TP1/TP2 friction model. `SMCStrategy` emits no gate or price levels; gates are derived from `ScoreBreakdown` + `metadata` in `_classify_smc()`.

## 1. Data and walk-forward split

| Item | Value |
| :--- | :--- |
| Database | `D:\trade\backtest.db` |
| Raw rows / duplicates dropped | 110,280 / 9,355 |
| Full range | 2023-03-01 00:00 → 2026-11-19 05:30 UTC |
| Replay start date | 2025-01-01 UTC |
| Warm-up bars available | 43,237 |
| Open-market bars available | 87,976 |
| Bar records captured | 44,739 |
| Warmup / insufficient-data skips | 0 / 0 |
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
| calibration | `CONFIRMED_SETUP` | 532 | 427 | 105 | 138 |
| calibration | `CONFLUENCE_FLOOR` | 329 | 147 | 182 | 89 |
| calibration | `LTF_PENALTY` | 192 | 144 | 48 | 61 |
| calibration | `PA_FLOOR` | 165 | 97 | 68 | 42 |
| calibration | `SCORE_BELOW_THRESHOLD` | 7,812 | 4,793 | 3,019 | 2,039 |
| test | `CONFIRMED_SETUP` | 1,104 | 677 | 427 | 300 |
| test | `CONFLUENCE_FLOOR` | 826 | 481 | 345 | 228 |
| test | `LTF_PENALTY` | 444 | 238 | 206 | 140 |
| test | `PA_FLOOR` | 413 | 202 | 211 | 109 |
| test | `SCORE_BELOW_THRESHOLD` | 15,048 | 8,157 | 6,891 | 3,957 |
| validation | `CONFIRMED_SETUP` | 1,107 | 710 | 397 | 297 |
| validation | `CONFLUENCE_FLOOR` | 591 | 357 | 234 | 169 |
| validation | `LTF_PENALTY` | 453 | 320 | 133 | 152 |
| validation | `PA_FLOOR` | 361 | 254 | 107 | 101 |
| validation | `SCORE_BELOW_THRESHOLD` | 15,362 | 9,213 | 6,149 | 4,039 |

## 3. Counterfactual vs accepted trades

For near-miss rejections the trade is re-priced as if the gate had passed, using the same `RiskManager` geometry and the same `simulate_outcome` friction. `n` counts de-duplicated trades with valid geometry; `filled` is the subset that filled. Expectancy = average R per filled trade. Near-miss set: LTF penalty (all), fatal conflict (all), score within 5 pts, PA floor within 2 pts, confluence floor within 5 pts.

| Split | Rejection reason | Candidate bars | Opportunities | n | Filled | No fill | Win rate | Avg R | Expectancy | Flag |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| calibration | `ACCEPTED (CONFIRMED_SETUP)` | 532 | 138 | 138 | 130 | 0 | 49.23% | 0.2191 | 0.2191 |  |
| calibration | `CONFLUENCE_FLOOR` | 154 | 43 | 43 | 41 | 0 | 36.59% | -0.0782 | -0.0782 |  |
| calibration | `LTF_PENALTY` | 192 | 61 | 61 | 61 | 0 | 26.23% | -0.3518 | -0.3518 |  |
| calibration | `SCORE_BELOW_THRESHOLD` | 389 | 108 | 108 | 104 | 0 | 50.96% | 0.2822 | 0.2822 |  |
| test | `ACCEPTED (CONFIRMED_SETUP)` | 1,104 | 300 | 300 | 291 | 0 | 46.05% | 0.1527 | 0.1527 |  |
| test | `CONFLUENCE_FLOOR` | 230 | 65 | 65 | 62 | 0 | 35.48% | -0.0472 | -0.0472 |  |
| test | `LTF_PENALTY` | 444 | 140 | 140 | 139 | 0 | 43.17% | 0.0235 | 0.0235 |  |
| test | `SCORE_BELOW_THRESHOLD` | 851 | 241 | 241 | 232 | 0 | 39.66% | -0.0163 | -0.0163 |  |
| validation | `ACCEPTED (CONFIRMED_SETUP)` | 1,107 | 297 | 297 | 289 | 0 | 49.48% | 0.2851 | 0.2851 |  |
| validation | `CONFLUENCE_FLOOR` | 186 | 59 | 59 | 58 | 0 | 31.03% | -0.1650 | -0.1650 |  |
| validation | `LTF_PENALTY` | 453 | 152 | 152 | 146 | 0 | 53.42% | 0.4767 | 0.4767 |  |
| validation | `SCORE_BELOW_THRESHOLD` | 881 | 249 | 249 | 238 | 0 | 39.50% | 0.0932 | 0.0932 |  |

> 0 of 12 groups have fewer than 30 filled trades (flagged above). Treat every metric in those groups as descriptive only.

## 4. LTF penalty (flat -5.0 pts)

| Split | Bars with LTF penalty applied | Bars that passed all pre-LTF gates |
| :--- | ---: | ---: |
| calibration | 7,542 | 612 |
| validation | 14,969 | 1,324 |
| test | 15,050 | 1,337 |

---

Live SMC parameters: `DEFAULT_MIN_SCORE=60.0`, `LTF_UNCONFIRMED_PENALTY=5.0`, `DIRECTIONAL_CONFLICT_PENALTY=15.0`. As documented in the Parameter history table, these parameters were introduced in commit 2db6eb1. Prior runs observed validation and test sets; validation and test are no longer clean out-of-sample data.
