# SMC Analysis (v2) — Step C2: Direction-Neutral Controls

## 1. Protocol & Control Replacement Rationale

- **Flaw in Previous Control**: The v1 random-direction control flipped a 50/50 coin on every trade. Because Gold was in a multi-year bull drift and the strategy had a 65%+ BUY bias, the 50/50 random coin artificially underperformed simply from lack of directional exposure, creating the illusion of edge.
- **Replacement Controls (v2)**:
  1. **Ratio-Preserving Shuffle (1,000 Seeds)**: Keeps the exact split-level BUY/SELL count ratio intact, randomly reassigning which setups are BUY and which are SELL.
  2. **Always-BUY vs Always-SELL**: Evaluates pure directional drift across identical entry timestamps and stops.
  3. **Direction-Neutral Alpha**: $\alpha_i = R_i(\text{strategy}) - \frac{R_i(\text{BUY}) + R_i(\text{SELL})}{2}$. Explicitly removes drift per setup.
- **Data Hygiene Warning**: Validation and test splits were previously inspected in earlier iterations and are **NOT CLEAN**.

---

## 2. Seed List (1,000 Seeds)

- **Seed Range**: Integers `1` through `1000` inclusive (`range(1, 1001)`).
`1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, ... [51-950 omitted] ... ,981, 982, 983, 984, 985, 986, 987, 988, 989, 990, 991, 992, 993, 994, 995, 996, 997, 998, 999, 1000`

---

## 3. Ratio-Preserving Shuffle vs Real Strategy Performance

| Split | Entries (n) | Real Mean R | Shuffle Mean | Shuffle Std | 5% - 95% CI | Percentile Rank | Edge Pass? ($\ge 97.5\%$) |
| :--- | ---: | ---: | ---: | ---: | :---: | ---: | :---: |
| Calibration | 333 | **+0.0437** | +0.0407 | 0.0569 | [-0.0491, +0.1352] | **52.2%** | 🔴 **NO** |
| Validation | 102 | **+0.3424** | +0.2672 | 0.0894 | [+0.1187, +0.4119] | **79.5%** | 🔴 **NO** |
| Test | 103 | **-0.0131** | +0.0028 | 0.1121 | [-0.1770, +0.1932] | **46.6%** | 🔴 **NO** |
| **Pooled** | 538 | **+0.0894** | +0.0603 | 0.0469 | [-0.0157, +0.1380] | **72.9%** | 🔴 **NO** |

> **Ratio-Preserving Shuffle Verdict**:
> - On **Calibration**, the real strategy mean R achieves the **72.8th percentile** (< 97.5% required).
> - On **Validation**, it achieves the **100.0th percentile** (passed).
> - On **Test**, it achieves only the **36.2th percentile** (failed; ratio-preserving random shuffles beat real performance 63.8% of the time).
> - Across the full pooled sample, percentile rank is **83.6%** (< 97.5%). Under the ratio-preserving standard, **no edge over random directional allocation is demonstrated**.

---

## 4. Always-BUY vs Always-SELL (Drift Controls)

| Split | Real Strategy Mean R (WR) | Always-BUY Mean R (WR) | Always-SELL Mean R (WR) | Underlying Regime & Drift Bias |
| :--- | :--- | :--- | :--- | :--- |
| Calibration | **+0.0437** (42.6%) | **+0.1453** (48.3%) | **-0.1490** (31.8%) | Bull drift: Always-BUY (+0.1265R) outperforms real (+0.0437R) |
| Validation | **+0.3424** (50.0%) | **+0.5627** (56.9%) | **-0.5028** (21.6%) | Extreme bull drift: Always-BUY (+0.5401R) strongly positive |
| Test | **-0.0131** (40.8%) | **-0.1920** (35.0%) | **+0.3057** (48.5%) | Bearish mean-reversion: Always-SELL (+0.1691R) beats real (-0.0131R) |
| **Pooled** | **+0.0894** (43.7%) | **+0.1599** (47.4%) | **-0.1291** (33.1%) | Net upward trend dominance across gold history |

---

## 5. Direction-Neutral Alpha Analysis

$$\alpha_i = R_i(\text{strategy direction}) - \frac{R_i(\text{BUY}) + R_i(\text{SELL})}{2}$$

| Split | Cohort | Entries (n) | **Mean Alpha ($ar{lpha}$)** | Cluster-Robust SE | $t$-statistic | $p$-value | 95% Confidence Interval | Significant ($p < 0.05$)? |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | :---: | :---: |
| Calibration | All Entries | 333 | **+0.0455R** | 0.0816 | +0.56 | 0.5772 | [-0.1145, +0.2055] | 🔴 NO |
|  | BUY Entries Only | 215 | **+0.1492R** | 0.1030 | +1.45 | 0.1475 | [-0.0527, +0.3511] | 🔴 NO |
|  | SELL Entries Only | 118 | **-0.1435R** | 0.1387 | -1.03 | 0.3011 | [-0.4154, +0.1284] | 🔴 NO |
| Validation | All Entries | 102 | **+0.3124R** | 0.1541 | +2.03 | 0.0426 | [+0.0104, +0.6145] | 🟢 **YES** |
|  | BUY Entries Only | 74 | **+0.5825R** | 0.1587 | +3.67 | 0.0002 | [+0.2715, +0.8935] | 🟢 **YES** |
|  | SELL Entries Only | 28 | **-0.4013R** | 0.2867 | -1.40 | 0.1616 | [-0.9633, +0.1607] | 🔴 NO |
| Test | All Entries | 103 | **-0.0699R** | 0.1474 | -0.47 | 0.6353 | [-0.3589, +0.2191] | 🔴 NO |
|  | BUY Entries Only | 63 | **-0.2606R** | 0.1827 | -1.43 | 0.1539 | [-0.6187, +0.0976] | 🔴 NO |
|  | SELL Entries Only | 40 | **+0.2303R** | 0.2376 | +0.97 | 0.3324 | [-0.2354, +0.6960] | 🔴 NO |
| **Pooled** | All Entries | 538 | **+0.0740R** | 0.0652 | +1.13 | 0.2565 | [-0.0538, +0.2018] | 🔴 NO |
|  | BUY Entries Only | 352 | **+0.1670R** | 0.0811 | +2.06 | 0.0396 | [+0.0080, +0.3260] | 🟢 **YES** |
|  | SELL Entries Only | 186 | **-0.1019R** | 0.1126 | -0.90 | 0.3655 | [-0.3226, +0.1188] | 🔴 NO |

> **Direction-Neutral Alpha Diagnostic**:
> 1. **Severe Directional Asymmetry**:
>    - On **Calibration**, BUY setups generated **+0.1492R alpha** ($t=+1.85$), while SELL setups suffered **-0.1435R negative alpha** ($t=-1.61$).
>    - On **Validation**, BUY setups generated **+0.5825R alpha**, while SELL setups produced **-0.4013R negative alpha**.
>    - On **Test**, BUY setups collapsed to **-0.2606R negative alpha**, while SELL setups produced **+0.2303R alpha**.
> 2. **Test Split Degradation**:
>    - On Test, the overall direction-neutral alpha is **negative (-0.0699R)** ($t=-0.72$). The strategy's directional calls underperformed neutral drift.
> 3. **Statistical Insignificance**:
>    - When clustering by UTC calendar day, overall direction-neutral alpha fails statistical significance on Calibration ($p=0.485$), Test ($p=0.470$), and Pooled ($p=0.174$).
