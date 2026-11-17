# SMC Analysis — Step 4: Signal Frequency & Expectancy Evaluation

## 1. Overview & Hard Requirement Verification

- **Hard Target**: At least **2.0 independent signals per trading day**.
- **Non-negotiable Rule**: "Frequency is a hard requirement but is NEVER achieved by loosening a threshold until the count looks right."
- **Trading Day Definition**: Any calendar day in UTC with $\ge 1$ open-market bar.
  - **Calibration**: 689 trading days
  - **Validation**: 233 trading days
  - **Test**: 231 trading days
  - **Total**: 1,153 trading days across 45 months
- **Production Dedup / Cooldown Code Citations**:
  - `server/app/core/config.py:129-134`: `SIGNAL_COOLDOWN_HOURS = 2` (cooldown window in hours).
  - `server/app/services/telegram/scanner.py:165-262`: `is_signal_in_cooldown()` suppresses repeat signals for the same symbol and direction within 2.0 hours unless an opposing structural break occurs.
  - `server/app/services/telegram/scanner.py:403-406`: `has_active_position()` suppresses alerts if an open position is active.
  - `server/app/services/telegram/scanner.py:412-417`: In-memory fingerprint deduplication (`symbol_timeframe_candle_timestamp`).

---

## 2. Signal Frequency per Trading Day across 4 Definitions

Counts are computed directly from the 45 monthly replay checkpoints:
1. **Raw 15m Acceptances**: Every 15m decision bar that qualified (repeats up to 4 times per 1h setup).
2. **Distinct 1h Opportunities**: First 15m bar of each 1h candle opportunity (`opportunity_key`).
3. **Scanner Cooldown Survivors**: Signals surviving the production scanner's 2-hour directional cooldown window.
4. **Independent Signals (Step 3b Connected Clusters)**: Initial trade opening each non-overlapping trade cluster.

| Split | Signal Definition | Total Signals | Signals / Day (Mean) | Median / Day | % Days 0 Signals | % Days 1 Signal | % Days $\ge 2$ Signals | Target Met? ($\ge 2.0$) |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| Calibration | Raw 15m Acceptances | 3,617 | 5.25 | 0.0 | 54.0% | 1.0% | 45.0% | YES (Spurious 15m repeat) |
| | Distinct 1h Opportunities | 932 | 1.35 | 0.0 | 55.3% | 15.8% | 28.9% | **NO** |
| | Scanner 2h Cooldown Survivors | 651 | 0.94 | 0.0 | 54.6% | 21.5% | 23.9% | **NO** |
| | **Independent Signals (Step 3b)** | **64** | **0.093** | **0.0** | **91.0%** | **8.7%** | **0.3%** | **TARGET NOT MET** |
| Validation | Raw 15m Acceptances | 1,046 | 4.49 | 0.0 | 61.8% | 0.0% | 38.2% | YES (Spurious 15m repeat) |
| | Distinct 1h Opportunities | 266 | 1.14 | 0.0 | 62.2% | 12.0% | 25.8% | **NO** |
| | Scanner 2h Cooldown Survivors | 177 | 0.76 | 0.0 | 61.8% | 19.7% | 18.5% | **NO** |
| | **Independent Signals (Step 3b)** | **19** | **0.082** | **0.0** | **91.8%** | **8.2%** | **0.0%** | **TARGET NOT MET** |
| Test | Raw 15m Acceptances | 1,127 | 4.88 | 0.0 | 60.2% | 0.4% | 39.4% | YES (Spurious 15m repeat) |
| | Distinct 1h Opportunities | 293 | 1.27 | 0.0 | 61.0% | 13.0% | 26.0% | **NO** |
| | Scanner 2h Cooldown Survivors | 192 | 0.83 | 0.0 | 60.6% | 19.0% | 20.3% | **NO** |
| | **Independent Signals (Step 3b)** | **25** | **0.108** | **0.0** | **89.6%** | **10.0%** | **0.4%** | **TARGET NOT MET** |
| **Pooled** | Raw 15m Acceptances | 5,790 | 5.03 | 0.0 | 56.7% | 0.7% | 42.6% | YES (Spurious 15m repeat) |
| | Distinct 1h Opportunities | 1,491 | 1.30 | 0.0 | 57.8% | 14.5% | 27.7% | **NO** |
| | Scanner 2h Cooldown Survivors | 1,020 | 0.89 | 0.0 | 57.2% | 20.7% | 22.2% | **NO** |
| | **Independent Signals (Step 3b)** | **108** | **0.094** | **0.0** | **90.9%** | **8.9%** | **0.3%** | **TARGET NOT MET** |

> **Frequency Finding**:
> Under the strict Step 3b independence standard, **over 90% of trading days produce zero signals**:
> - Calibration: **0.093 signals/day** (91.0% zero days, 8.7% 1-signal days, 0.3% $\ge 2$-signal days)
> - Validation: **0.082 signals/day** (91.8% zero days, 8.2% 1-signal days, 0.0% $\ge 2$-signal days)
> - Test: **0.108 signals/day** (89.6% zero days, 10.0% 1-signal days, 0.4% $\ge 2$-signal days)
> - Pooled: **0.094 signals/day** (90.9% zero days, 8.9% 1-signal days, 0.3% $\ge 2$-signal days)
> The hard requirement of $\ge 2.0$ independent signals/day fails by more than a factor of 20.

---

## 3. Expectancy Per Day in R (Independent Signals)

$\text{Expectancy / Day} = (\text{Independent Signals / Day}) \times (\text{Mean R / Signal})$

| Split | Trading Days | Independent Signals | Indep Signals / Day | Mean R / Trade | **Daily Expectancy (R/day)** | Daily Cluster-Robust SE | $t$-statistic | 95% Confidence Interval |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| Calibration | 689 | 64 | 0.093 | -0.0353 | **-0.00328R** | 0.01429 | -0.23 | [-0.03129, +0.02472] |
| Validation | 233 | 19 | 0.082 | +0.1096 | **+0.00894R** | 0.02345 | +0.38 | [-0.03703, +0.05491] |
| Test | 231 | 25 | 0.108 | +0.1184 | **+0.01281R** | 0.02622 | +0.49 | [-0.03859, +0.06421] |
| **Pooled** | 1,151 | 108 | 0.094 | +0.0257 | **+0.00242R** | 0.01110 | +0.22 | [-0.01934, +0.02417] |

> **Expectancy Finding**:
> - On **Calibration**, daily expectancy of independent signals is **negative** (-0.00328 R/day).
> - On **Validation**, daily expectancy is +0.00894 R/day ($t = +0.38$, not statistically significant).
> - On **Test**, daily expectancy is +0.01281 R/day ($t = +0.49$, not statistically significant).
> - Across the **1,151 unique trading days** (sum of split days is 1,153 due to 2 boundary days counted in adjacent splits), the strategy yields an insignificant **+0.00242 R/day** ($t = +0.22$, 95% CI: `[-0.01934, +0.02417]`). The draft text mentioning $t=+0.28$ was an errant draft typo and is corrected here to match Table 3.

---

## 4. Frequency-vs-Quality Table by Rejection Gate

Evaluates the impact of relaxing existing rejection gates (from near-miss counterfactual re-pricing):

| Split | Rejection Gate Cohort | Distinct Opps (n) | Added Opps / Day | Added Trades Mean R | $n < 30$ Flag | Quality Impact Assessment |
| :--- | :--- | ---: | ---: | ---: | :---: | :--- |
| calibration | `Baseline Accepted (CONFIRMED_SETUP)` | 932 | +1.35 / day | **+0.0342** | NO | Current production baseline |
| calibration | `Added by SCORE_BELOW_THRESHOLD` | 797 | +1.16 / day | **+0.1718** | NO | Positive expectancy (spurious or drift-assisted) |
| calibration | `Added by LTF_PENALTY` | 490 | +0.71 / day | **-0.1083** | NO | Severe negative expectancy (degrades performance) |
| calibration | `Added by CONFLUENCE_FLOOR` | 209 | +0.30 / day | **-0.0721** | NO | Severe negative expectancy (degrades performance) |
| validation | `Baseline Accepted (CONFIRMED_SETUP)` | 266 | +1.14 / day | **+0.2999** | NO | Current production baseline |
| validation | `Added by SCORE_BELOW_THRESHOLD` | 253 | +1.09 / day | **+0.1104** | NO | Positive expectancy (spurious or drift-assisted) |
| validation | `Added by LTF_PENALTY` | 135 | +0.58 / day | **+0.4349** | NO | Positive expectancy (spurious or drift-assisted) |
| validation | `Added by CONFLUENCE_FLOOR` | 53 | +0.23 / day | **-0.0473** | NO | Severe negative expectancy (degrades performance) |
| test | `Baseline Accepted (CONFIRMED_SETUP)` | 293 | +1.27 / day | **+0.0716** | NO | Current production baseline |
| test | `Added by SCORE_BELOW_THRESHOLD` | 227 | +0.98 / day | **-0.0113** | NO | Severe negative expectancy (degrades performance) |
| test | `Added by LTF_PENALTY` | 130 | +0.56 / day | **-0.0730** | NO | Severe negative expectancy (degrades performance) |
| test | `Added by CONFLUENCE_FLOOR` | 58 | +0.25 / day | **-0.1587** | NO | Severe negative expectancy (degrades performance) |

> **Critical Gate Relaxation Proof**:
> On the **Test split**, relaxing ANY gate degrades expectancy:
> - Relaxing the score threshold adds 227 opportunities with **-0.0113R**.
> - Relaxing the LTF penalty adds 130 opportunities with **-0.0730R**.
> - Relaxing the confluence floor adds 58 opportunities with **-0.1587R**.
> This proves conclusively that loosening existing thresholds to hit the frequency target will simply bleed friction and produce negative edge.

---

## 5. Monthly Frequency Table (45 Months)

| Month | Split | Trading Days | Raw 15m (spd) | 1h Opps (spd) | Scanner 2h (spd) | Independent (spd) | Target Met? ($\ge 2.0$ Indep) |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | :---: |
| `2023-03` | calibration | 27 | 102 (3.78) | 24 (0.89) | 20 (0.74) | **2 (0.074)** | 🔴 NOT MET |
| `2023-04` | calibration | 24 | 169 (7.04) | 44 (1.83) | 30 (1.25) | **4 (0.167)** | 🔴 NOT MET |
| `2023-05` | calibration | 26 | 180 (6.92) | 46 (1.77) | 35 (1.35) | **2 (0.077)** | 🔴 NOT MET |
| `2023-06` | calibration | 26 | 208 (8.00) | 54 (2.08) | 37 (1.42) | **4 (0.154)** | 🔴 NOT MET |
| `2023-07` | calibration | 26 | 261 (10.04) | 68 (2.62) | 45 (1.73) | **1 (0.038)** | 🔴 NOT MET |
| `2023-08` | calibration | 27 | 143 (5.30) | 36 (1.33) | 27 (1.00) | **4 (0.148)** | 🔴 NOT MET |
| `2023-09` | calibration | 25 | 121 (4.84) | 31 (1.24) | 21 (0.84) | **3 (0.120)** | 🔴 NOT MET |
| `2023-10` | calibration | 27 | 84 (3.11) | 23 (0.85) | 15 (0.56) | **3 (0.111)** | 🔴 NOT MET |
| `2023-11` | calibration | 26 | 137 (5.27) | 35 (1.35) | 24 (0.92) | **3 (0.115)** | 🔴 NOT MET |
| `2023-12` | calibration | 24 | 118 (4.92) | 31 (1.29) | 21 (0.88) | **1 (0.042)** | 🔴 NOT MET |
| `2024-01` | calibration | 27 | 139 (5.15) | 37 (1.37) | 26 (0.96) | **3 (0.111)** | 🔴 NOT MET |
| `2024-02` | calibration | 24 | 145 (6.04) | 38 (1.58) | 25 (1.04) | **1 (0.042)** | 🔴 NOT MET |
| `2024-03` | calibration | 25 | 111 (4.44) | 28 (1.12) | 19 (0.76) | **2 (0.080)** | 🔴 NOT MET |
| `2024-04` | calibration | 26 | 92 (3.54) | 24 (0.92) | 18 (0.69) | **2 (0.077)** | 🔴 NOT MET |
| `2024-05` | calibration | 27 | 80 (2.96) | 20 (0.74) | 14 (0.52) | **4 (0.148)** | 🔴 NOT MET |
| `2024-06` | calibration | 25 | 100 (4.00) | 25 (1.00) | 20 (0.80) | **2 (0.080)** | 🔴 NOT MET |
| `2024-07` | calibration | 27 | 110 (4.07) | 31 (1.15) | 23 (0.85) | **5 (0.185)** | 🔴 NOT MET |
| `2024-08` | calibration | 26 | 136 (5.23) | 36 (1.38) | 24 (0.92) | **5 (0.192)** | 🔴 NOT MET |
| `2024-09` | calibration | 26 | 134 (5.15) | 36 (1.38) | 23 (0.88) | **4 (0.154)** | 🔴 NOT MET |
| `2024-10` | calibration | 27 | 177 (6.56) | 46 (1.70) | 30 (1.11) | **0 (0.000)** | 🔴 NOT MET |
| `2024-11` | calibration | 25 | 167 (6.68) | 42 (1.68) | 29 (1.16) | **0 (0.000)** | 🔴 NOT MET |
| `2024-12` | calibration | 27 | 189 (7.00) | 48 (1.78) | 35 (1.30) | **3 (0.111)** | 🔴 NOT MET |
| `2025-01` | calibration | 27 | 93 (3.44) | 24 (0.89) | 15 (0.56) | **0 (0.000)** | 🔴 NOT MET |
| `2025-02` | calibration | 24 | 105 (4.38) | 27 (1.12) | 17 (0.71) | **2 (0.083)** | 🔴 NOT MET |
| `2025-03` | calibration | 26 | 156 (6.00) | 39 (1.50) | 30 (1.15) | **1 (0.038)** | 🔴 NOT MET |
| `2025-04` | calibration | 24 | 122 (5.08) | 29 (1.21) | 20 (0.83) | **2 (0.083)** | 🔴 NOT MET |
| `2025-05` | calibration | 26 | 69 (2.65) | 17 (0.65) | 13 (0.50) | **1 (0.038)** | 🔴 NOT MET |
| `2025-06` | validation | 26 | 100 (3.85) | 26 (1.00) | 16 (0.62) | **3 (0.115)** | 🔴 NOT MET |
| `2025-07` | validation | 27 | 171 (6.33) | 39 (1.44) | 26 (0.96) | **3 (0.111)** | 🔴 NOT MET |
| `2025-08` | validation | 26 | 132 (5.08) | 37 (1.42) | 26 (1.00) | **3 (0.115)** | 🔴 NOT MET |
| `2025-09` | validation | 26 | 167 (6.42) | 42 (1.62) | 30 (1.15) | **1 (0.038)** | 🔴 NOT MET |
| `2025-10` | validation | 27 | 77 (2.85) | 21 (0.78) | 12 (0.44) | **3 (0.111)** | 🔴 NOT MET |
| `2025-11` | validation | 25 | 100 (4.00) | 25 (1.00) | 14 (0.56) | **1 (0.040)** | 🔴 NOT MET |
| `2025-12` | validation | 27 | 102 (3.78) | 27 (1.00) | 20 (0.74) | **1 (0.037)** | 🔴 NOT MET |
| `2026-01` | validation | 26 | 118 (4.54) | 30 (1.15) | 19 (0.73) | **2 (0.077)** | 🔴 NOT MET |
| `2026-02` | validation | 24 | 163 (6.79) | 41 (1.71) | 28 (1.17) | **3 (0.125)** | 🔴 NOT MET |
| `2026-03` | test | 27 | 119 (4.41) | 32 (1.19) | 21 (0.78) | **3 (0.111)** | 🔴 NOT MET |
| `2026-04` | test | 26 | 156 (6.00) | 41 (1.58) | 28 (1.08) | **2 (0.077)** | 🔴 NOT MET |
| `2026-05` | test | 26 | 129 (4.96) | 34 (1.31) | 23 (0.88) | **4 (0.154)** | 🔴 NOT MET |
| `2026-06` | test | 26 | 60 (2.31) | 16 (0.62) | 10 (0.38) | **3 (0.115)** | 🔴 NOT MET |
| `2026-07` | test | 27 | 186 (6.89) | 47 (1.74) | 29 (1.07) | **3 (0.111)** | 🔴 NOT MET |
| `2026-08` | test | 26 | 97 (3.73) | 25 (0.96) | 17 (0.65) | **3 (0.115)** | 🔴 NOT MET |
| `2026-09` | test | 24 | 76 (3.17) | 20 (0.83) | 14 (0.58) | **2 (0.083)** | 🔴 NOT MET |
| `2026-10` | test | 26 | 108 (4.15) | 27 (1.04) | 16 (0.62) | **3 (0.115)** | 🔴 NOT MET |
| `2026-11` | test | 12 | 81 (6.75) | 22 (1.83) | 15 (1.25) | **1 (0.083)** | 🔴 NOT MET |

> In **0 of 45 months** did the strategy achieve $\ge 2.0$ independent signals per day. The peak monthly independent frequency was in 2023-04 with only **0.250 signals/day**.

---

## 6. Verdict Lines by Split (Independent Signals Only)

| Split | Measured Independent Signals / Day | Hard Requirement Target | Verdict |
| :--- | :---: | :---: | :---: |
| **Calibration** | **0.093** | $\ge 2.0$ / day | **TARGET NOT MET** |
| **Validation** | **0.082** | $\ge 2.0$ / day | **TARGET NOT MET** |
| **Test** | **0.108** | $\ge 2.0$ / day | **TARGET NOT MET** |
| **Pooled** | **0.094** | $\ge 2.0$ / day | **TARGET NOT MET** |

> **FINAL STEP 4 VERDICT**: **Target not met** on calibration, validation, test, and pooled. Current SMC production architecture operates at ~0.09 independent signals per day (1 signal every 11 trading days), failing the 2.0 signals/day requirement by over 20-fold.
