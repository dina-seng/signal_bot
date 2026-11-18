# SMC Replay — Full-Range Rejection Funnel & Counterfactual

Production path: `resample_ohlc` → `ConfluenceEngine._prepare_market_data` → `SMCStrategy.analyze` → `RiskManager.calculate_trade_risk` (market geometry) → shared `simulate_outcome` fill/TP1/TP2 friction model. `SMCStrategy` emits no gate or price levels; gates are derived from `ScoreBreakdown` + `metadata` in `_classify_smc()`.

## 1. Data and walk-forward split

| Item | Value |
| :--- | :--- |
| Database | `server\backtest.db` |
| Raw rows / duplicates dropped | 9,259 / 0 |
| Full range | 2025-01-01 23:00 → 2025-05-21 23:45 UTC |
| Open-market bars available | 8,857 |
| Bar records captured | 8,697 |
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
| calibration | `CONFIRMED_SETUP` | 272 | 236 | 36 | 70 |
| calibration | `CONFLUENCE_FLOOR` | 340 | 149 | 191 | 88 |
| calibration | `LTF_PENALTY` | 202 | 143 | 59 | 58 |
| calibration | `PA_FLOOR` | 160 | 92 | 68 | 40 |
| calibration | `REGIME_FILTER_REJECT` | 238 | 146 | 92 | 58 |
| calibration | `SCORE_BELOW_THRESHOLD` | 7,485 | 4,546 | 2,939 | 1,899 |

## 3. Counterfactual vs accepted trades

For near-miss rejections the trade is re-priced as if the gate had passed, using the same `RiskManager` geometry and the same `simulate_outcome` friction. `n` counts de-duplicated trades with valid geometry; `filled` is the subset that filled. Expectancy = average R per filled trade. Near-miss set: LTF penalty (all), fatal conflict (all), score within 5 pts, PA floor within 2 pts, confluence floor within 5 pts.

| Split | Rejection reason | Candidate bars | Opportunities | n | Filled | No fill | Win rate | Avg R | Expectancy | Flag |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| calibration | `ACCEPTED (CONFIRMED_SETUP)` | 272 | 70 | 70 | 70 | 0 | 54.29% | 0.1925 | 0.1925 |  |
| calibration | `CONFLUENCE_FLOOR` | 155 | 42 | 42 | 42 | 0 | 40.48% | 0.0191 | 0.0191 |  |
| calibration | `LTF_PENALTY` | 202 | 58 | 58 | 58 | 0 | 24.14% | -0.3577 | -0.3577 |  |
| calibration | `SCORE_BELOW_THRESHOLD` | 354 | 100 | 100 | 100 | 0 | 50.00% | 0.2429 | 0.2429 |  |

> 0 of 4 groups have fewer than 30 filled trades (flagged above). Treat every metric in those groups as descriptive only.

## 4. LTF penalty (flat -5.0 pts)

| Split | Bars with LTF penalty applied | Bars that passed all pre-LTF gates |
| :--- | ---: | ---: |
| calibration | 7,285 | 616 |
| validation | 0 | 0 |
| test | 0 | 0 |

---

Live SMC parameters: `DEFAULT_MIN_SCORE=60.0`, `LTF_UNCONFIRMED_PENALTY=5.0`, `DIRECTIONAL_CONFLICT_PENALTY=15.0`. As documented in the Parameter history table, these parameters were introduced in commit 2db6eb1. Prior runs observed validation and test sets; validation and test are no longer clean out-of-sample data.
