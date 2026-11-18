# Regime Filter Hypothesis Test: Calibration-Only Analysis

**Author**: Senior Quantitative Engineer  
**Repository**: `signal_bot`  
**Date**: 2026-11-19  
**Data Source**: Local SQLite database (`server/backtest.db`)  
**Calibration Window**: 2025-01-01 to 2025-05-21 (Clean Calibration Split)  
**Status**: 🔴 **FAILED PRE-SET PASS RULES — DO NOT PROCEED TO VALIDATION**

---

## 1. Executive Summary & Experiment Scope

### Goal & Hypothesis
Live trading observations and preliminary diagnostics identified directional drawdowns in SMC execution during counter-trend market states. 

The **Regime Filter Hypothesis** states:
> *Filtering out counter-trend setups (rejecting BUY signals when the 1H EMA stack is bearish, and rejecting SELL signals when the 1H EMA stack is bullish) will improve direction-neutral alpha and overall expectancy.*

### Strict Calibration-Only Scope
Per the quantitative research governance protocol defined in `docs/SMC_FREEZE_V2.md`:
- **Data Source**: Strictly the newly populated local SQLite database at `server/backtest.db`. No network requests to the live Neon database or Twelve Data API were performed.
- **Data Window**: Strictly the **CALIBRATION window** (2025-01-01 23:00:00 UTC to 2025-05-21 08:15:00 UTC; 8,697 evaluated 15m bars across 5 calendar months).
- **Contamination Guard**: Validation (bars on or after 2025-05-21 08:15:00 UTC) and Test splits were **strictly NOT touched, queried, or observed**.
- **Frozen Engine Integrity**: Core SMC signal generation logic (BOS, CHOCH, FVG detection, scoring weights, and liquidity thresholds) remained 100% frozen and untouched.
- **Pre-Set Pass Rules**: Candidate must satisfy all 5 quantitative gating rules on the calibration set to proceed to out-of-sample validation.

---

## 2. Replay Implementation (`--regime-filter`)

The regime filter was implemented in `server/scripts/smc_replay.py` as an outer gate evaluated before signal emission:
- **CLI Flag**: `--regime-filter` (default: `False`).
- **Gate Logic**:
  - Before a signal is emitted, inspect the primary 1H EMA trend (`indicators.ema.ema_trend`).
  - If `direction == 'BUY'`, require `ema_trend == 'BULLISH_STACK'`.
  - If `direction == 'SELL'`, require `ema_trend == 'BEARISH_STACK'`.
  - If the requirement is not met, reject the signal with gate `REGIME_FILTER_REJECT`.
- **Friction Model**: \$0.40 round-trip spread deduction per completed trade with conservative same-bar SL-first execution.
- **De-duplication**: Trades are de-duplicated by `opportunity_key` (`symbol_timeframe_direction_bucket`) to remove multi-bar 15m repeats within the same 1H setup.

---

## 3. Side-by-Side Performance Comparison

The table below contrasts the **Baseline SMC** (no filter) against the **Regime-Filtered SMC** candidate on the Calibration window (`server/backtest.db`):

| Performance Metric | Baseline SMC (No Filter) | Regime-Filtered SMC (`--regime-filter`) | Delta ($\Delta$) | Pre-Set Target |
| :--- | :---: | :---: | :---: | :---: |
| **Evaluated Bars** | 8,697 | 8,697 | 0 | Calibration Window |
| **Emitted Setup Bars** | 510 | 272 | -238 (-46.7%) | — |
| **Distinct Opportunities (Trades)** | **128** | **70** | **-58 (-45.3%)** | Sample size |
| &emsp;*Direction: BUY* | 96 (75.0%) | 61 (87.1%) | -35 (-36.5%) | — |
| &emsp;*Direction: SELL* | 32 (25.0%) | 9 (12.9%) | -23 (-71.9%) | — |
| **Win Rate** | **47.66%** (61 / 128) | **54.29%** (38 / 70) | **+6.63%** | Higher |
| **Mean R per Trade ($\bar{R}$)** | **+0.1703 R** | **+0.1925 R** | **+0.0222 R** | $> 0.0000\text{ R}$ |
| **Profit Factor (PF)** | **1.36** | **1.53** | **+0.17** | Higher |
| **Total Realized R** | **+21.80 R** | **+13.48 R** | **-8.32 R (-38.2%)** | Higher |
| **Max Drawdown (R)** | **12.29 R** | **7.56 R** | **-4.73 R (-38.5%)** | $\le 13.52\text{ R}$ ($\le +10\%$) |
| **Direction-Neutral Alpha ($\bar{\alpha}$)** | **+0.1409 R** | **+0.1858 R** | **+0.0449 R** | $> 0.0000\text{ R}$ |
| &emsp;*Cluster-robust $SE$* | $\pm 0.6333\text{ R}$ | $\pm 0.9070\text{ R}$ | — | Cluster = UTC Day |
| &emsp;*Cluster $t$-stat ($p$-value)* | $t = +0.22$ ($p = 0.824$) | $t = +0.20$ ($p = 0.838$) | — | Not sig ($p \ge 0.05$) |
| **Ratio-Preserving Shuffle Percentile** | **78.2%** | **11.2%** | **-67.0%** | $\ge \mathbf{97.5\%}$ ($p_{97.5} = +0.4349\text{R}$) |
| **Max Single-Month R Share** | **104.9%** (+22.87R in 2025-03) | **128.4%** (+17.30R in 2025-03) | +23.5% | $\le \mathbf{25.0\%}$ |

---

## 4. Evaluation Against Pre-Set Pass Rules

To be approved as an edge-additive hypothesis, the candidate must satisfy **ALL FIVE** pre-set qualification criteria on the calibration dataset:

| # | Rule Specification | Candidate Result | Threshold / Boundary | Evaluation Verdict |
| :-: | :--- | :---: | :---: | :---: |
| **1** | **Mean R > 0** | $+0.1925\text{ R}$ | $> 0.0000\text{ R}$ | 🟢 **PASS** |
| **2** | **Ratio-Preserving Shuffle Control $\ge 97.5\%$**<br>*(1,000 randomized direction allocations)* | **11.2%** | $\ge 97.5\%$<br>($p_{97.5} = +0.4349\text{R}$) | 🔴 **FAIL** |
| **3** | **Direction-Neutral Alpha > 0**<br>*(or statistically significant improvement)* | $+0.1858\text{ R} > 0$<br>($\Delta\alpha = +0.0449\text{R}, t = +0.05, p = 0.96$) | $> 0.0000\text{ R}$ or $p < 0.05$ | 🟡 **PASS (Descriptive Only)**<br>*(No statistically significant edge)* |
| **4** | **No Single Month Contributes > 25% of Total R** | **128.4%** (2025-03: +17.30 R)<br>**27.4%** (2025-04: +3.70 R) | $\le 25.0\%$ | 🔴 **FAIL** |
| **5** | **Max Drawdown $\le$ Baseline Max DD + 10%** | $7.56\text{ R}$ | $\le 13.52\text{ R}$ ($12.29\text{ R} + 10\%$) | 🟢 **PASS** |

### **Overall Qualification Verdict**: 🔴 **FAIL**

> [!CAUTION]
> **The regime filter does not add edge on calibration. Do not proceed to validation.**

---

## 5. Quantitative Diagnostics & Root Cause Analysis

### 1. Collapse of Ratio-Preserving Shuffle Control (Rule 2)
The ratio-preserving shuffle control preserves the candidate's exact BUY/SELL ratio (61 BUYs / 9 SELLs) and evaluates 1,000 randomized directional assignments against counterfactual trades simulated at identical decision bars.
- In the Regime-Filtered candidate, real mean R (+0.1925 R) ranks at only the **11.2th percentile** of the shuffle distribution. In **888 out of 1,000 random allocations**, random directional assignments outperformed the strategy.
- The 97.5th percentile of the shuffle distribution is **+0.4349 R**.
- **Root Cause**: During the persistent gold bull trend of early 2025, taking long positions at almost any random opportunity was overwhelmingly profitable due to macro beta. The regime filter merely forced an 87.1% long bias (61 BUYs vs 9 SELLs). When benchmarked against random direction assignments with that same long bias, the strategy's entry timing demonstrated **negative selection skill**.

### 2. Extreme Monthly PnL Concentration (Rule 4)
The candidate violates the monthly concentration limit by an extraordinary margin:
- Month **2025-03** generates **+17.30 R** out of a total **+13.48 R** (**128.4%** of total PnL).
- Month **2025-04** also exceeds the threshold at **+3.70 R** (**27.4%** of total PnL).
- Without March 2025, the strategy's total return across the other 4 calibration months is **-3.83 R**.
- In February 2025, the baseline SMC was profitable (+10.55 R across 27 trades), but the regime filter turned February into a **losing month (-2.79 R across 15 trades)**.

### 3. Destruction of SELL Trade Expectancy
Analyzing the directional breakdown reveals the critical structural failure of the 1H EMA stack filter:

| Cohort | Baseline SMC | Regime-Filtered SMC | Delta ($\Delta$) |
| :--- | :---: | :---: | :---: |
| **BUY Trades ($n$)** | 96 | 61 | -35 (-36.5%) |
| &emsp;*Win Rate* | 51.04% | 59.02% | +7.98% |
| &emsp;*Mean R ($\bar{R}$)* | +0.2258 R | +0.3044 R | +0.0786 R |
| &emsp;*Total Realized R* | +21.68 R | +18.57 R | -3.11 R |
| **SELL Trades ($n$)** | 32 | 9 | -23 (-71.9%) |
| &emsp;*Win Rate* | 37.50% | 22.22% | -15.28% |
| &emsp;*Mean R ($\bar{R}$)* | **+0.0038 R** | **-0.5658 R** | **-0.5696 R** |
| &emsp;*Total Realized R* | **+0.12 R** | **-5.09 R** | **-5.21 R** |

- While BUY win rate and mean R improved, filtering eliminated 35 valid BUY trades, causing total realized BUY R to decline from +21.68 R to +18.57 R.
- More importantly, **SELL performance collapsed catastrophically**. Under baseline, SMC SELL setups broke even (+0.0038 R, 37.5% WR). Under the regime filter, SELL trades plunged to a **22.22% win rate and -0.5658 R mean expectancy** (-5.09 R total loss across 9 trades).
- **Mechanism**: In a strong secular trend, when the 1H EMA stack turns bearish, it represents a temporary counter-trend liquidity sweep or pullback. Shorting when the 1H EMA stack is bearish enters right at the exhaustion of the pullback before the dominant higher-timeframe trend aggressively resumes, triggering stops.

### 4. Trade Opportunity Starvation
- Distinct trade opportunities fell from **128 to 70** (-45.3%).
- Across 98 active trading days in the calibration window, trade frequency fell to **0.71 trades/day** (from 1.31 trades/day), failing the strategy capacity standards.

---

## 6. Month-by-Month Calibration Audit

Full breakdown across all calibration months (`server/backtest.db`):

| Month | Baseline Trades | Baseline Total R | Filtered Trades | Filtered Total R | Filtered % of Total | Dominant Regime / Behavior |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **2025-01** | 23 | -2.80 R | 19 | +1.28 R | 9.5% | Mixed / Early Consolidation |
| **2025-02** | 27 | +10.55 R | 15 | -2.79 R | -20.7% | Bullish Breakout (Filtered cut winning counter-trend setups) |
| **2025-03** | 39 | +22.87 R | 18 | +17.30 R | **128.4%** | Strong Trend (Concentrated PnL driver) |
| **2025-04** | 29 | -2.95 R | 12 | +3.70 R | **27.4%** | Pullback Consolidation |
| **2025-05\*** | 10 | -5.86 R | 6 | -6.01 R | -44.6% | Pullback before Calibration Boundary (May 21 08:15 UTC) |
| **Total** | **128** | **+21.80 R** | **70** | **+13.48 R** | **100.0%** | — |

*\* 2025-05 evaluates strictly bars prior to 2025-05-21 08:15:00 UTC (exact calibration boundary).*

---

## 7. Final Governance Decision & Next Steps

1. **Protocol Rejection**: Under the pre-registered scientific gating rules (`docs/SMC_FREEZE_V2.md`), candidates that fail any calibration pass rule must be rejected without post-hoc rationalization.
2. **Definitive Finding**: The 1H EMA trend stack filter acts as a lagging indicator that cuts winning early entries, severely degrades short trade expectancy (-0.57R), and fails the shuffle control (11.2th percentile).
3. **Protection of Out-of-Sample Sets**: Validation and Test splits **remain strictly untouched** and are not deployed for this candidate.
4. **Production Code Freeze**: Production defaults in `server/app/services/strategies/smc_strategy.py` and `server/app/services/signals/evaluators.py` **remain untouched and frozen**.
5. **Conclusion**:
   > **The regime filter does not add edge on calibration. Do not proceed to validation.**
