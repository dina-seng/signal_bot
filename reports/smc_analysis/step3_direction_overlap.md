# SMC Analysis — Step 3: Direction, Overlap, Independence, and Stability

## 1. Overview & Protocol

- **Accepted Opportunities**: 1,491 total across 45 monthly replay checkpoints (`reports/smc_replay_extended/checkpoints/`).
- **Friction Model**: Flat \$0.40 round-trip spread deduction per trade (exact `simulate_outcome` parity).
- **Walk-forward Splits**: Calibration (60%), Validation (20%), Test (20%).
- **Data Hygiene Warning**: Validation and test splits were previously inspected in exploratory iterations (commits `4424a64`, `5b88873`, `2db6eb1`) and are **no longer clean out-of-sample data**.

---

## 2. Directional Performance (BUY vs SELL vs Drift)

To determine whether trade performance represents structural edge or market drift, accepted BUY and SELL trades are compared against the **Always-BUY** and **Always-SELL** benchmark controls from Step 1.

| Split | Signal Direction | Opportunities (n) | Win Rate | Mean R | Step 1 Always-BUY Mean R (WR) | Step 1 Always-SELL Mean R (WR) | Drift Assessment |
| :--- | :--- | ---: | ---: | ---: | :--- | :--- | :--- |
| Calibration | **BUY** | 630 (67.6%) | 45.56% | **+0.0836** | +0.1346 (46.78%) | -0.1834 (31.22%) | Underperformed Always-BUY |
| | **SELL** | 302 (32.4%) | 35.76% | **-0.0689** | *(same as above)* | *(same as above)* | Outperformed Always-SELL |
| Validation | **BUY** | 179 (67.3%) | 62.57% | **+0.6737** | +0.4894 (56.39%) | -0.5180 (19.17%) | Outperformed Always-BUY |
| | **SELL** | 87 (32.7%) | 21.84% | **-0.4691** | *(same as above)* | *(same as above)* | Outperformed Always-SELL |
| Test | **BUY** | 175 (59.7%) | 40.00% | **-0.0404** | -0.0686 (37.88%) | +0.2853 (47.44%) | Outperformed Always-BUY |
| | **SELL** | 118 (40.3%) | 47.46% | **+0.2377** | *(same as above)* | *(same as above)* | Underperformed Always-SELL |
| **Pooled** | **BUY** | 984 (66.0%) | 47.66% | **+0.1689** | +0.1580 (46.75%) | -0.1510 (32.26%) | Outperformed Always-BUY |
| | **SELL** | 507 (34.0%) | 36.09% | **-0.0662** | *(same as above)* | *(same as above)* | Outperformed Always-SELL |

> **Directional Verdict**:
> - **Calibration**: BUY trades (+0.0836R) underperformed Always-BUY (+0.1346R). SELL trades were negative (-0.0689R).
> - **Validation**: BUY trades (+0.6737R) were strongly positive, accompanied by Always-BUY (+0.4894R) during a massive gold bull drift; SELL trades suffered severely (-0.4691R).
> - **Test**: When market regime flipped, BUY trades lost money (-0.0404R). SELL trades (+0.2377R) underperformed Always-SELL (+0.2853R).
> - The strategy displays **no directional forecasting edge**: returns in each split are driven entirely by underlying market drift.

---

## 3. Overlap Analysis & Independent Signals

### A. Overlap Summary
- **Total Accepted Opportunities**: **1,491**
- **Trades entering while an earlier trade is still open**: **1,383 (92.8%)**
- **Trades entering with no prior trade active**: **108 (7.2%)**

### B. Independent Signals (First Trade of Each Overlapping Cluster)

Two definitions are reported:
1. **Connected Interval Clusters (Step 3b specification)**: A cluster spans the continuous duration during which at least one position remains active. The independent signal is the initial trade opening the cluster.
2. **Serial Non-Overlapping Trades (Portfolio Constraint)**: When a trade opens, all subsequent entries are ignored until that specific trade exits.

| Split | All Accepted Opps (Mean R) | Connected Cluster First Trades (Step 3b) | Mean R (Step 3b) | Serial Non-Overlapping Trades | Mean R (Serial) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Calibration | 932 (+0.0342) | **64** | **-0.0353** | 126 | +0.0369 |
| Validation | 266 (+0.2999) | **19** | **+0.1096** | 39 | +0.2274 |
| Test | 293 (+0.0716) | **25** | **+0.1184** | 43 | -0.1147 |
| **Pooled** | 1,491 (+0.0890) | **108** | **+0.0257** | 208 | +0.0413 |

> **Independence Finding**:
> 92.8% of accepted SMC signals are secondary/tertiary concurrent entries during ongoing trades. Under strict cluster independence, the strategy produces only **108 independent signals across 45 months** (~2.4 signals per MONTH, or ~0.11 signals per trading day). Furthermore, independent signal expectancy on Calibration drops to **-0.0353R**.

---

## 4. Cluster-Robust Standard Error of Mean R (Cluster = Calendar Day)

Standard OLS standard errors assume i.i.d. observations. When multiple trades execute on the same calendar day, intra-day correlation drastically inflates precision. Cluster-robust standard errors (clustering by calendar day) correct for intra-day clustering.

| Split | Trades (N) | Calendar Days (G) | Mean R | Naive SE (OLS) | Cluster-Robust SE | $t$-statistic | $p$-value | 95% Confidence Interval | Significant ($p < 0.05$)? |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: |
| Calibration | 932 | 308 | **+0.0342** | 0.0411 | **0.0776** | +0.44 | 0.6596 | [-0.1180, +0.1864] | **NO** |
| Validation | 266 | 88 | **+0.2999** | 0.0836 | **0.1636** | +1.83 | 0.0669 | [-0.0208, +0.6207] | **NO** |
| Test | 293 | 90 | **+0.0716** | 0.0786 | **0.1538** | +0.47 | 0.6415 | [-0.2299, +0.3731] | **NO** |
| **Pooled** | 1,491 | 486 | **+0.0890** | 0.0336 | **0.0643** | +1.38 | 0.1667 | [-0.0371, +0.2150] | **NO** |

> **Statistical Significance Verdict**:
> When clustering by calendar day, **not a single split achieves statistical significance at the 5% level**.
> - Calibration: $t = +0.44, p = 0.6599$ (95% CI: `[-0.1179, +0.1863]`)
> - Validation: $t = +1.83, p = 0.0667$ (95% CI: `[-0.0208, +0.6206]`)
> - Test: $t = +0.47, p = 0.6416$ (95% CI: `[-0.2299, +0.3731]`)
> - Pooled: $t = +1.28, p = 0.2003$ (95% CI: `[-0.0471, +0.2251]`)
> Intra-day clustering approximately doubles standard errors, demonstrating that the apparent consistency of SMC is an artifact of correlated multi-bar clustering.

---

## 5. Monthly Stability Over Full Range (45 Months)

### Summary Statistics
- **Total Months Evaluated**: 45 months (2023-03 through 2026-11)
- **Negative Months**: **20 / 45 (44.4%)**
- **Positive Months**: **25 / 45 (55.6%)**
- **Worst Month**: **2025-05 (validation)**: **-0.7354R** ($n=17$, total -12.50R)
- **Best Month**: **2026-08 (test)**: **+1.2908R** ($n=25$, total +32.27R)

### Monthly Return Table

| Month | Split | Trades (n) | Win Rate | Mean R | Total R | Verdict |
| :--- | :--- | ---: | ---: | ---: | ---: | :---: |
| `2023-03` | calibration | 24 | 79.2% | **+1.2806** | +30.73R | 🟢 POSITIVE |
| `2023-04` | calibration | 44 | 27.3% | **-0.2863** | -12.60R | 🔴 NEGATIVE |
| `2023-05` | calibration | 46 | 26.1% | **-0.2925** | -13.45R | 🔴 NEGATIVE |
| `2023-06` | calibration | 54 | 42.6% | **+0.0291** | +1.57R | 🟢 POSITIVE |
| `2023-07` | calibration | 68 | 41.2% | **-0.2822** | -19.19R | 🔴 NEGATIVE |
| `2023-08` | calibration | 36 | 36.1% | **-0.2995** | -10.78R | 🔴 NEGATIVE |
| `2023-09` | calibration | 31 | 35.5% | **-0.0419** | -1.30R | 🔴 NEGATIVE |
| `2023-10` | calibration | 23 | 47.8% | **+0.0050** | +0.12R | 🟢 POSITIVE |
| `2023-11` | calibration | 35 | 57.1% | **+0.4028** | +14.10R | 🟢 POSITIVE |
| `2023-12` | calibration | 31 | 38.7% | **-0.0414** | -1.28R | 🔴 NEGATIVE |
| `2024-01` | calibration | 37 | 29.7% | **-0.3728** | -13.80R | 🔴 NEGATIVE |
| `2024-02` | calibration | 38 | 50.0% | **+0.1448** | +5.50R | 🟢 POSITIVE |
| `2024-03` | calibration | 28 | 60.7% | **+0.6431** | +18.01R | 🟢 POSITIVE |
| `2024-04` | calibration | 24 | 37.5% | **-0.3328** | -7.99R | 🔴 NEGATIVE |
| `2024-05` | calibration | 20 | 15.0% | **-0.5186** | -10.37R | 🔴 NEGATIVE |
| `2024-06` | calibration | 25 | 16.0% | **-0.6999** | -17.50R | 🔴 NEGATIVE |
| `2024-07` | calibration | 31 | 61.3% | **+0.3873** | +12.01R | 🟢 POSITIVE |
| `2024-08` | calibration | 36 | 11.1% | **-0.7097** | -25.55R | 🔴 NEGATIVE |
| `2024-09` | calibration | 36 | 52.8% | **+0.1291** | +4.65R | 🟢 POSITIVE |
| `2024-10` | calibration | 46 | 71.7% | **+0.9443** | +43.44R | 🟢 POSITIVE |
| `2024-11` | calibration | 42 | 45.2% | **+0.4058** | +17.04R | 🟢 POSITIVE |
| `2024-12` | calibration | 48 | 20.8% | **-0.3578** | -17.17R | 🔴 NEGATIVE |
| `2025-01` | calibration | 24 | 75.0% | **+0.4448** | +10.67R | 🟢 POSITIVE |
| `2025-02` | calibration | 27 | 51.9% | **+0.3907** | +10.55R | 🟢 POSITIVE |
| `2025-03` | calibration | 39 | 64.1% | **+0.5863** | +22.87R | 🟢 POSITIVE |
| `2025-04` | calibration | 29 | 27.6% | **-0.1017** | -2.95R | 🔴 NEGATIVE |
| `2025-05` | validation | 17 | 11.8% | **-0.7354** | -12.50R | 🔴 NEGATIVE |
| `2025-06` | validation | 26 | 38.5% | **+0.0274** | +0.71R | 🟢 POSITIVE |
| `2025-07` | validation | 39 | 20.5% | **-0.5820** | -22.70R | 🔴 NEGATIVE |
| `2025-08` | validation | 37 | 45.9% | **+0.2302** | +8.52R | 🟢 POSITIVE |
| `2025-09` | validation | 42 | 90.5% | **+1.1102** | +46.63R | 🟢 POSITIVE |
| `2025-10` | validation | 21 | 57.1% | **+0.3744** | +7.86R | 🟢 POSITIVE |
| `2025-11` | validation | 25 | 44.0% | **+0.2522** | +6.31R | 🟢 POSITIVE |
| `2025-12` | validation | 27 | 51.9% | **+0.6629** | +17.90R | 🟢 POSITIVE |
| `2026-01` | validation | 30 | 66.7% | **+1.0555** | +31.67R | 🟢 POSITIVE |
| `2026-02` | test | 41 | 36.6% | **-0.0569** | -2.33R | 🔴 NEGATIVE |
| `2026-03` | test | 32 | 50.0% | **-0.2853** | -9.13R | 🔴 NEGATIVE |
| `2026-04` | test | 41 | 24.4% | **-0.3371** | -13.82R | 🔴 NEGATIVE |
| `2026-05` | test | 34 | 32.4% | **-0.0002** | -0.01R | 🔴 NEGATIVE |
| `2026-06` | test | 16 | 37.5% | **+0.2286** | +3.66R | 🟢 POSITIVE |
| `2026-07` | test | 47 | 53.2% | **+0.1023** | +4.81R | 🟢 POSITIVE |
| `2026-08` | test | 25 | 76.0% | **+1.2908** | +32.27R | 🟢 POSITIVE |
| `2026-09` | test | 20 | 40.0% | **+0.0739** | +1.48R | 🟢 POSITIVE |
| `2026-10` | test | 27 | 25.9% | **-0.2842** | -7.67R | 🔴 NEGATIVE |
| `2026-11` | test | 22 | 45.5% | **+0.0758** | +1.67R | 🟢 POSITIVE |
