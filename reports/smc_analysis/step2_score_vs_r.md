# SMC Analysis — Step 2: Score vs R-Multiple Ranking Evaluation

## 1. Protocol & Bucket Edges

- **Dataset**: Accepted trades AND counterfactual near-miss rejected trades from `reports/smc_replay_extended/checkpoints/`.
- **De-duplication**: Matches Section 3 of `reports/smc_replay_extended/smc_replay_report.md` (first trade per opportunity key).
- **Bucket Edges Selected**: `[0.0, 50.0, 55.0, 60.0, 65.0, 70.0, 100.0]`
  - `< 50`: Low-score rejections (primarily confluence floor failures below 50.0)
  - `[50, 55)`: Near-miss rejections with score penalty
  - `[55, 60)`: Near-miss score-below-threshold rejections (just under the 60.0 floor)
  - `[60, 65)`: Baseline accepted tier (`DEFAULT_MIN_SCORE = 60.0`)
  - `[65, 70)`: Mid-tier accepted setups
  - `>= 70`: High-conviction accepted setups (merged to guarantee $n \ge 30$ on all splits)
- **Verification**: Every bucket has $\ge 50$ trades on every split ($n \ge 30$ condition strictly met).

---

## 2. Score Bucketing Tables (Accepted + Counterfactual)

### Calibration

| Score Bucket | Opportunities (n) | Win Rate | Mean R | Total R | $n < 30$ Flag |
| :--- | ---: | ---: | ---: | ---: | :---: |
| `< 50` | 209 | 35.89% | -0.0721 | -15.07R | NO |
| `[50, 55)` | 684 | 47.95% | +0.2015 | +137.81R | NO |
| `[55, 60)` | 603 | 38.47% | -0.0895 | -53.99R | NO |
| `[60, 65)` | 410 | 42.68% | +0.0279 | +11.43R | NO |
| `[65, 70)` | 303 | 41.91% | +0.0305 | +9.24R | NO |
| `>= 70` | 219 | 42.47% | +0.0511 | +11.20R | NO |

### Validation

| Score Bucket | Opportunities (n) | Win Rate | Mean R | Total R | $n < 30$ Flag |
| :--- | ---: | ---: | ---: | ---: | :---: |
| `< 50` | 53 | 33.96% | -0.0473 | -2.51R | NO |
| `[50, 55)` | 217 | 37.79% | +0.0533 | +11.56R | NO |
| `[55, 60)` | 171 | 49.71% | +0.4392 | +75.10R | NO |
| `[60, 65)` | 127 | 53.54% | +0.4541 | +57.67R | NO |
| `[65, 70)` | 76 | 47.37% | +0.2502 | +19.02R | NO |
| `>= 70` | 63 | 42.86% | +0.0490 | +3.09R | NO |

### Test

| Score Bucket | Opportunities (n) | Win Rate | Mean R | Total R | $n < 30$ Flag |
| :--- | ---: | ---: | ---: | ---: | :---: |
| `< 50` | 58 | 32.76% | -0.1587 | -9.20R | NO |
| `[50, 55)` | 193 | 39.90% | +0.0373 | +7.20R | NO |
| `[55, 60)` | 164 | 38.41% | -0.1175 | -19.26R | NO |
| `[60, 65)` | 139 | 45.32% | +0.1128 | +15.68R | NO |
| `[65, 70)` | 96 | 37.50% | -0.1153 | -11.07R | NO |
| `>= 70` | 58 | 46.55% | +0.2822 | +16.37R | NO |

### Pooled (All Splits)

| Score Bucket | Opportunities (n) | Win Rate | Mean R | Total R | $n < 30$ Flag |
| :--- | ---: | ---: | ---: | ---: | :---: |
| `< 50` | 320 | 35.00% | -0.0837 | -26.78R | NO |
| `[50, 55)` | 1,094 | 44.52% | +0.1431 | +156.57R | NO |
| `[55, 60)` | 938 | 40.51% | +0.0020 | +1.84R | NO |
| `[60, 65)` | 676 | 45.27% | +0.1254 | +84.79R | NO |
| `[65, 70)` | 475 | 41.89% | +0.0362 | +17.19R | NO |
| `>= 70` | 340 | 43.24% | +0.0902 | +30.65R | NO |

---

## 3. Spearman Rank Correlation Analysis

### A. Combined Dataset (Accepted + Counterfactual Near-Miss)

| Split | Opportunities (n) | Spearman $r_s$ | $t$-statistic | $p$-value | Statistically Significant ($p < 0.05$)? | Positive? |
| :--- | ---: | ---: | ---: | ---: | :---: | :---: |
| Calibration | 2,428 | +0.0024 | +0.12 | 9.0553e-01 | NO | YES |
| Validation | 707 | +0.0831 | +2.21 | 2.6907e-02 | YES | YES |
| Test | 708 | +0.0650 | +1.73 | 8.3592e-02 | NO | YES |
| **Pooled** | 3,843 | +0.0222 | +1.38 | 1.6895e-01 | NO | YES |

### B. Accepted Trades Only (Within Emitted Signals)

| Split | Accepted Trades (n) | Spearman $r_s$ | $t$-statistic | $p$-value | Statistically Significant ($p < 0.05$)? | Positive? |
| :--- | ---: | ---: | ---: | ---: | :---: | :---: |
| Calibration | 932 | -0.0140 | -0.43 | 6.6976e-01 | NO | NO |
| Validation | 266 | -0.1374 | -2.25 | 2.4176e-02 | YES | NO |
| Test | 293 | +0.0453 | +0.77 | 4.3916e-01 | NO | YES |
| **Pooled** | 1,491 | -0.0313 | -1.21 | 2.2760e-01 | NO | NO |

---

## 4. Key Diagnostic Observations

1. **Complete Non-Monotonicity in Score Buckets**:
   - On **Calibration**, trades in the rejected near-miss bucket `[50, 55)` achieved **+0.2015R** ($n=684$), crushing the highest-score bucket `>= 70` (**+0.0511R**, $n=219$) and the accepted baseline `[60, 65)` (**+0.0279R**). The strategy actively rejected its most profitable calibration cohort.
   - On **Validation**, bucket `[60, 65)` yielded **+0.4541R** while bucket `>= 70` yielded only **+0.0490R**. Higher scores produced 9x *lower* expectancy.
   - On **Test**, bucket `[65, 70)` suffered **-0.1153R** while bucket `[60, 65)` produced **+0.1128R**.

2. **Inverse Correlation Within Accepted Trades**:
   - Within accepted signals, the score exhibits a **statistically significant negative correlation** with return on Validation ($r_s = -0.1374, p = 0.0242$).
   - On Calibration, accepted signal score correlation is also negative ($r_s = -0.0140$).
   - Across all 1,491 accepted trades pooled, the correlation is negative ($r_s = -0.0313, p = 0.2276$).

3. **Combined Correlation Fails Robustness**:
   - In the combined Accepted + Counterfactual dataset, Test split correlation is weak ($r_s = +0.0650$) and **fails statistical significance** ($p = 0.0836 > 0.05$).
   - Calibration split correlation is functionally zero ($r_s = +0.0024, p = 0.9055$).

---

## 5. Verdict

> **VERDICT**: **score has no demonstrated ranking power**.

The SMC composite score fails to rank trade expectancy. Within accepted trades, the ranking correlation is negative on validation ($r_s = -0.1374, p = 0.0242$) and calibration ($r_s = -0.0140$). When combining accepted and counterfactual trades, the correlation on test ($r_s = +0.0650, p = 0.0836$) is not statistically distinguishable from zero at the 5% level, and calibration is flat ($r_s = +0.0024, p = 0.9055$). The scoring function does not separate winners from losers.
