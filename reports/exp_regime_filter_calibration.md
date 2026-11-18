# Regime Filter Hypothesis Test: Calibration-Only Analysis

**Author**: Senior Quantitative Engineer  
**Repository**: `signal_bot`  
**Date**: 2026-11-19  
**Status**: 🔴 **FAILED PRE-SET PASS RULES — DO NOT PROCEED TO VALIDATION**

---

## 1. Executive Summary & Experiment Scope

### Goal & Hypothesis
Live trading and Phase C2 controls identified significant directional asymmetry in SMC execution: BUY signals bled heavily during prolonged bearish periods (e.g., Test split), confirming that trading counter to the prevailing higher-timeframe regime degrades expectancy.

The **Regime Filter Hypothesis** states:
> *Filtering out counter-trend setups (requiring 1H EMA `BULLISH_STACK` for BUY signals and `BEARISH_STACK` for SELL signals) will eliminate falling-knife entries, improve direction-neutral alpha, and enhance overall expectancy.*

### Strict Calibration-Only Scope
Per the quantitative research governance protocol defined in `docs/SMC_FREEZE_V2.md`:
- **Data Window**: Strictly **CALIBRATION split only** (2023-03-01 00:00:00 UTC to 2025-05-21 08:15:00 UTC; 689 calendar trading days across 27 calendar months).
- **Contamination Guard**: Validation (2025-05-21 to 2026-02-16) and Test (2026-02-16 to 2026-11-15) splits were **strictly NOT touched, queried, or observed**.
- **Frozen Engine Integrity**: Core SMC signal generation logic (BOS, CHOCH, FVG detection, scoring weights, and liquidity thresholds) remained 100% frozen and untouched.
- **Decision Rule**: Pre-set pass rules are immutable. If any rule fails on calibration, the candidate is disqualified immediately.

---

## 2. Replay Implementation (`--regime-filter`)

The regime filter is implemented in `server/scripts/smc_replay.py` as an outer gate evaluated before signal emission:
- **CLI Flag**: `--regime-filter` (default: `False`).
- **Gate Evaluation**:
  - `BUY` signals require 1H EMA `ema_trend == 'BULLISH_STACK'` ($\text{Price} > \text{EMA}_{20} > \text{EMA}_{50} > \text{EMA}_{200}$).
  - `SELL` signals require 1H EMA `ema_trend == 'BEARISH_STACK'` ($\text{Price} < \text{EMA}_{20} < \text{EMA}_{50} < \text{EMA}_{200}$).
  - Setups failing the condition are suppressed with gate `REGIME_FILTER_REJECT`.
- **Friction Model**: \$0.40 round-trip spread deduction per completed trade with conservative same-bar SL-first execution.

---

## 3. Side-by-Side Performance Comparison

The table below contrasts the **Baseline SMC** (no filter) against the **Regime-Filtered SMC** candidate on the Calibration split. Metrics are reported across both the standalone opportunity generator (distinct primary opportunities) and the frozen portfolio benchmark rules (MAX_CONCURRENT=3, DAILY_LOSS_STOP=-3.0R, separation=1.0x ATR or 1h).

### Primary Evaluation: Standalone Distinct Opportunities

| Performance Metric | Baseline SMC (No Filter) | Regime-Filtered SMC (`--regime-filter`) | Delta ($\Delta$) | Pre-Set Target |
| :--- | :---: | :---: | :---: | :---: |
| **Evaluated Bars** | 51,934 | 51,934 | 0 | Calibration Window |
| **Emitted Setup Bars** | 3,617 | 1,405 | -2,212 (-61.2%) | — |
| **Distinct Opportunities (Trades)** | **932** | **372** | **-560 (-60.1%)** | Sample size |
| &emsp;*Direction: BUY* | 630 (67.6%) | 267 (71.8%) | -363 (-57.6%) | — |
| &emsp;*Direction: SELL* | 302 (32.4%) | 105 (28.2%) | -197 (-65.2%) | — |
| **Win Rate** | **42.38%** (395 / 932) | **48.12%** (179 / 372) | **+5.74%** | Higher |
| **Mean R per Trade ($\bar{R}$)** | **+0.0342 R** | **+0.1256 R** | **+0.0914 R** | $> 0.0000\text{ R}$ |
| **Profit Factor (PF)** | **1.06** | **1.29** | **+0.23** | Higher |
| **Total Realized R** | +31.87 R | +46.74 R | +14.87 R | Higher |
| **Max Drawdown (R)** | **97.87 R** | **30.96 R** | **-66.91 R** | $\le 107.66\text{ R}$ ($\le +10\%$) |
| **Direction-Neutral Alpha ($\bar{\alpha}$)** | **+0.0586 R** | **+0.1648 R** | **+0.1062 R** | $> 0.0000\text{ R}$ |
| &emsp;*Cluster-robust $SE$* | $\pm 0.0664\text{ R}$ | $\pm 0.1008\text{ R}$ | — | Cluster = UTC Day |
| &emsp;*Cluster $t$-stat ($p$-value)* | $t = +0.88$ ($p = 0.378$) | $t = +1.64$ ($p = 0.102$) | — | Not sig ($p \ge 0.05$) |
| **Shuffle Control Percentile** | **55.8%** | **96.1%** | **+40.3%** | $\ge \mathbf{97.5\%}$ ($p_{97.5} = +0.1328\text{R}$) |
| **Max Single-Month R Share** | **136.3%** (+43.44R in 2024-10) | **37.0%** (+17.30R in 2025-03) | -99.3% | $\le \mathbf{25.0\%}$ |

---

### Secondary Evaluation: Benchmark Portfolio Specification (`docs/SMC_FREEZE_V2.md`)

| Portfolio Metric (MC=3, Stop=-3R) | Baseline Portfolio | Regime-Filtered Portfolio | Delta ($\Delta$) | Pass Threshold |
| :--- | :---: | :---: | :---: | :---: |
| **Entered Trades ($n$)** | 333 | 175 | -158 (-47.4%) | — |
| **Entries / Trading Day** | 0.483 / day | 0.254 / day | -0.229 / day | Operational pace |
| **Win Rate** | 42.64% (142 / 333) | 45.14% (79 / 175) | +2.50% | — |
| **Mean R ($\bar{R}$)** | **+0.0437 R** | **+0.0613 R** | **+0.0176 R** | $> 0.0000\text{ R}$ |
| **Profit Factor (PF)** | 1.08 | 1.13 | +0.05 | — |
| **Total Realized R** | +14.54 R | +10.72 R | -3.82 R | — |
| **Max Drawdown (R)** | 31.74 R | 19.83 R | -11.91 R | $\le 34.91\text{ R}$ |
| **Direction-Neutral Alpha ($\bar{\alpha}$)** | +0.0455 R ($p=0.577$) | +0.1139 R ($p=0.258$) | +0.0684 R | $> 0.0000\text{ R}$ |
| **Shuffle Control Percentile** | **52.2%** | **79.9%** | **+27.7%** | $\ge \mathbf{97.5\%}$ ($p_{97.5} = +0.1477\text{R}$) |
| **Max Single-Month R Share** | 134.3% (+19.52R in 2023-03) | **71.0%** (+7.61R in 2023-03) | -63.3% | $\le \mathbf{25.0\%}$ |

---

## 4. Evaluation Against Pre-Set Pass Rules

To be approved as an edge-additive hypothesis, the candidate must satisfy **ALL FIVE** pre-set qualification criteria on the Calibration dataset:

| # | Rule Specification | Standalone Result | Portfolio Result | Evaluation Verdict |
| :-: | :--- | :---: | :---: | :---: |
| **1** | **Mean R > 0** | $+0.1256\text{ R} > 0$ | $+0.0613\text{ R} > 0$ | 🟢 **PASS** |
| **2** | **Ratio-Preserving Shuffle Control Rank $\ge 97.5\%$**<br>*(1,000 randomized direction allocations)* | **96.1%**<br>($+0.1256\text{R} < p_{97.5} = +0.1328\text{R}$) | **79.9%**<br>($+0.0613\text{R} < p_{97.5} = +0.1477\text{R}$) | 🔴 **FAIL** |
| **3** | **Direction-Neutral Alpha > 0**<br>*(or statistically significant improvement)* | $+0.1648\text{ R} > 0$<br>($t = +1.64, p = 0.102$) | $+0.1139\text{ R} > 0$<br>($t = +1.13, p = 0.258$) | 🟢 **PASS (Descriptive)**<br>*(Not sig at $p < 0.05$)* |
| **4** | **No Single Month Contributes > 25% of Total R** | **37.0%** (2025-03: +17.30R)<br>*(4 months $> 25\%$)* | **71.0%** (2023-03: +7.61R) | 🔴 **FAIL** |
| **5** | **Max Drawdown $\le$ Baseline Max DD + 10%** | $30.96\text{ R} \le 107.66\text{ R}$ | $19.83\text{ R} \le 34.91\text{ R}$ | 🟢 **PASS** |

### **Overall Qualification Verdict**: 🔴 **FAIL**

> [!CAUTION]
> **The regime filter does not add edge on calibration. Do not proceed to validation.**

---

## 5. Quantitative Diagnostics & Root Cause Analysis

### 1. Failure on Ratio-Preserving Shuffle Control (Rule 2)
The ratio-preserving shuffle randomizes direction assignments while preserving the exact split-level BUY/SELL count ratio (267 BUYs / 105 SELLs on standalone; 116 BUYs / 59 SELLs on portfolio).
- On standalone replay, the real strategy mean of $+0.1256\text{R}$ achieves the **96.1th percentile** of the shuffle distribution, falling short of the $97.5\%$ significance boundary ($p_{97.5} = +0.1328\text{R}$). In 39 out of 1,000 seeds, random directional choices outperformed the strategy.
- Under portfolio constraints, the percentile collapses to **79.9%** ($p_{97.5} = +0.1477\text{R}$), demonstrating that under realistic portfolio concurrency and separation limits, the candidate is indistinguishable from random direction assignment.

### 2. Failure on Monthly Return Concentration (Rule 4)
The candidate fails Rule 4 by an extensive margin under both frameworks:
- On standalone replay, month **2025-03** generates $+17.30\text{R}$ out of $+46.74\text{R}$ (**37.0%** of total PnL).
- In addition, **2024-10** (+17.07R, 36.5%), **2024-03** (+15.73R, 33.7%), and **2023-06** (+12.42R, 26.6%) all individually exceed the 25% threshold.
- Under portfolio execution, month **2023-03** accounts for $+7.61\text{R}$ of the $+10.72\text{R}$ total (**71.0%**).
This confirms that the regime filter's apparent mean R improvement is an artifact of a few strong trending momentum months rather than robust, month-in-month-out edge.

### 3. Directional Breakdown & Asymmetry Persists
Examining the performance by direction confirms why the filter fails to create true direction-neutral edge:

| Cohort | Baseline Mean R | Regime Mean R | Baseline Win Rate | Regime Win Rate | Baseline Alpha | Regime Alpha |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **BUY Setups** | $+0.0836\text{ R}$ ($n=630$) | $+0.1765\text{ R}$ ($n=267$) | 45.6% | 52.4% | $+0.1610\text{ R}$ | $+0.2367\text{ R}$ |
| **SELL Setups** | $-0.0689\text{ R}$ ($n=302$) | **-0.0037 R** ($n=105$) | 35.8% | 37.1% | $-0.1550\text{ R}$ | **-0.0179 R** |

- **BUY setups** benefited from the macro gold bull market when 1H EMAs were stacked bullishly (+0.1765R).
- **SELL setups** remained **unprofitable (-0.0037R)** even when strictly aligned with a 1H `BEARISH_STACK`. Shorting gold with SMC patterns remained negative expectancy throughout calibration.
- Filtering counter-trend trades cut out losing counter-trend BUYs and SELLs, but did not solve the structural weakness of SMC SELL signals.

### 4. Severe Opportunity Starvation
- Standalone opportunity generation dropped from **932 to 372** (-60.1%), averaging only **0.54 opportunities per trading day**.
- Portfolio-entered trades dropped to **175 trades across 689 days** = **0.254 trades/day** (one trade every 4 calendar trading days).
- Such low frequency fails the operational requirements established in Phase C4 ($\ge 2.0\text{ trades/day}$) and would starve production capacity.

---

## 6. Month-by-Month Calibration Audit

The table below provides the full month-by-month breakdown across all 27 calibration months:

| Month | Baseline Trades | Baseline Total R | Regime Trades | Regime Total R | Regime % of Total | Dominant 1H Regime |
| :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| **2023-03** | 24 | +30.73 R | 6 | +9.58 R | 20.5% | Bullish Stack (Strong) |
| **2023-04** | 44 | -12.60 R | 18 | -11.02 R | -23.6% | Choppy / Mixed |
| **2023-05** | 46 | -13.45 R | 11 | -3.73 R | -8.0% | Pullback |
| **2023-06** | 54 | +1.57 R | 23 | +12.42 R | **26.6%** | Bearish Stack / Trend |
| **2023-07** | 68 | -19.19 R | 25 | -2.18 R | -4.7% | Mean Reversion |
| **2023-08** | 36 | -10.78 R | 23 | -1.02 R | -2.2% | Bearish Stack |
| **2023-09** | 31 | -1.30 R | 10 | -4.83 R | -10.3% | Pullback |
| **2023-10** | 23 | +0.12 R | 14 | +0.07 R | 0.2% | Bullish Breakout |
| **2023-11** | 35 | +14.10 R | 14 | +11.43 R | 24.5% | Bullish Stack |
| **2023-12** | 31 | -1.28 R | 17 | +10.67 R | 22.8% | Bullish Stack |
| **2024-01** | 37 | -13.80 R | 9 | -6.47 R | -13.8% | Consolidation |
| **2024-02** | 38 | +5.50 R | 9 | +7.75 R | 16.6% | Bullish Stack |
| **2024-03** | 28 | +18.01 R | 12 | +15.73 R | **33.7%** | Extreme Bull Run |
| **2024-04** | 24 | -7.99 R | 16 | +0.18 R | 0.4% | Volatile Consolidation |
| **2024-05** | 20 | -10.37 R | 6 | -2.58 R | -5.5% | Range Bound |
| **2024-06** | 25 | -17.50 R | 5 | -5.07 R | -10.8% | Choppy |
| **2024-07** | 31 | +12.01 R | 16 | -0.29 R | -0.6% | Bullish Stack |
| **2024-08** | 36 | -25.55 R | 10 | -9.52 R | -20.4% | Volatile Pullbacks |
| **2024-09** | 36 | +4.65 R | 15 | -2.11 R | -4.5% | Bullish Stack |
| **2024-10** | 46 | +43.44 R | 25 | +17.07 R | **36.5%** | Extreme Bull Run |
| **2024-11** | 42 | +17.04 R | 13 | -1.02 R | -2.2% | Correction |
| **2024-12** | 48 | -17.17 R | 10 | -6.85 R | -14.7% | Range Bound |
| **2025-01** | 24 | +10.67 R | 14 | +6.34 R | 13.6% | Bullish Stack |
| **2025-02** | 27 | +10.55 R | 15 | -2.79 R | -6.0% | Consolidation |
| **2025-03** | 39 | +22.87 R | 18 | +17.30 R | **37.0%** | Massive Bull Trend |
| **2025-04** | 29 | -2.95 R | 12 | +3.70 R | 7.9% | Range Bound |
| **2025-05** | 10 | -5.45 R | 6 | -6.01 R | -12.9% | Pullback |
| **Total** | **932** | **+31.87 R** | **372** | **+46.74 R** | **100.0%** | — |

---

## 7. Final Governance Decision & Next Steps

1. **Protocol Adherence**: Under the pre-registered scientific gating rules, candidate modifications that fail any calibration pass rule must be rejected without post-hoc rationalization or parameter tuning.
2. **Validation and Test Protection**: Validation and Test splits **remain strictly untouched** and are not deployed for this candidate.
3. **Production Scanner**: Production defaults in `server/app/services/strategies/smc_strategy.py` and `server/app/services/signals/evaluators.py` **remain untouched and frozen**.
4. **Conclusion**:
   > **The regime filter does not add edge on calibration. Do not proceed to validation.**
