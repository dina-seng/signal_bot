# 2025-2026 Replay Comparison: CRT vs SMC Strategies

**Target Instrument:** XAU/USD (15m)  
**Database:** `backtest.db` (Twelve Data, read-only)  
**Evaluation Window:** 2025-01-01 23:15 UTC → 2026-11-13 22:00 UTC (44,181 closed 15m bars evaluated)  
**Warm-up Context:** 43,237 earlier 15m bars (2023-03-01 00:00 UTC → 2025-01-01 23:00 UTC)  
**Friction Model:** $0.40 round-trip spread per completed trade for both strategies  
**Execution Semantics:** Zero-lookahead strictly enforced (`bar.timestamp + timeframe_delta <= decision_time`), same-bar ambiguity resolved stop-loss first (conservative)

---

## 1. Window and Data Coverage

| Item | CRT Strategy | SMC Strategy |
| :--- | :--- | :--- |
| **First Evaluated Bar** | 2025-01-01 23:15:00 UTC | 2025-01-01 23:15:00 UTC |
| **Last Evaluated Bar** | 2026-11-13 22:00:00 UTC | 2026-11-13 22:00:00 UTC |
| **Bars Evaluated** | 44,181 | 44,181 |
| **Warm-up Context Bars** | 43,237 | 43,237 |
| **Resampled Context** | 21,811 1h buckets, 5,816 4h buckets | 21,811 1h buckets, 5,816 4h buckets |
| **Lookback Windows** | 200 × 15m, 200 × 1h, 100 × 4h | 200 × 15m, 200 × 1h, 100 × 4h |
| **Database Access** | SQLite `mode=ro` (read-only) | SQLite `mode=ro` (read-only) |

---

## 2. Signal Generation and Direction

| Metric | CRT Strategy | SMC Strategy |
| :--- | :--- | :--- |
| **Emitted Setups (`CONFIRMED_SETUP`)** | 1 signal (1 bar) | 688 opportunities (2,687 bars) |
| **Direction: BUY** | 1 (100.0%) | 456 (66.3%) |
| **Direction: SELL** | 0 (0.0%) | 232 (33.7%) |
| **Average Signals / Month** | 0.04 / month | 29.9 / month |

### Signals Emitted per Month

| Month | CRT Signals | SMC Signals (Distinct) |
| :--- | ---: | ---: |
| **2025-01** | 0 | 24 |
| **2025-02** | 0 | 27 |
| **2025-03** | 0 | 39 |
| **2025-04** | 0 | 29 |
| **2025-05** | 0 | 17 |
| **2025-06** | 0 | 26 |
| **2025-07** | 0 | 39 |
| **2025-08** | 0 | 36 |
| **2025-09** | 0 | 43 |
| **2025-10** | 0 | 21 |
| **2025-11** | 0 | 25 |
| **2025-12** | 1 | 27 |
| **2026-01** | 0 | 30 |
| **2026-02** | 0 | 41 |
| **2026-03** | 0 | 32 |
| **2026-04** | 0 | 41 |
| **2026-05** | 0 | 34 |
| **2026-06** | 0 | 15 |
| **2026-07** | 0 | 48 |
| **2026-08** | 0 | 25 |
| **2026-09** | 0 | 20 |
| **2026-10** | 0 | 27 |
| **2026-11** | 0 | 22 |
| **Total** | **1** | **688** |

---

## 3. Rejection Funnels

Counts reflect bar-evaluations (first-failure-wins). Distinct counts de-duplicate by `sweep_event_key` (CRT) or `opportunity_key` (SMC: symbol, timeframe, direction, 1h candle timestamp).

### CRT Strategy Funnel

| Stage | Gate | Evaluated Bars | Distinct Sweeps | % of Bars |
| :--- | :--- | ---: | ---: | ---: |
| Pre-sweep | `NO_SWEEP` | 37,902 | 0 | 85.79% |
| Post-sweep | `TREND_CONFLICT` | 2,806 | 1,995 | 6.35% |
| Post-sweep | `CONFIRMATION_PENDING` | 1,611 | 1,202 | 3.65% |
| Post-sweep | `MICRO_SWEEP` | 1,213 | 821 | 2.75% |
| Post-sweep | `EXCESSIVE_MANIPULATION` | 386 | 285 | 0.87% |
| Pre-sweep | `MICRO_RANGE` | 237 | 152 | 0.54% |
| Post-sweep | `INVALID_ENTRY_ZONE` | 20 | 17 | 0.05% |
| Post-sweep | `EXCESSIVE_RISK_DISTANCE` | 2 | 1 | <0.01% |
| Post-sweep | `SCORE_BELOW_THRESHOLD` | 2 | 1 | <0.01% |
| Post-sweep | `PATH_BLOCKED` | 1 | 1 | <0.01% |
| **Emitted** | `CONFIRMED_SETUP` | **1** | **1** | **<0.01%** |
| **Total** | | **44,181** | **4,476** | **100.00%** |

### SMC Strategy Funnel

| Gate | Evaluated Bars | Distinct Opportunities | % of Bars |
| :--- | ---: | ---: | ---: |
| `SCORE_BELOW_THRESHOLD` | 37,733 | 9,606 | 85.41% |
| `CONFIRMED_SETUP` (Emitted) | 2,687 | 688 | 6.08% |
| `CONFLUENCE_FLOOR` | 1,727 | 448 | 3.91% |
| `LTF_PENALTY` | 1,107 | 319 | 2.51% |
| `PA_FLOOR` | 927 | 238 | 2.10% |
| **Total** | **44,181** | **11,299** | **100.00%** |

---

## 4. Trade Outcomes and Performance Metrics

Friction: $0.40 round-trip spread per trade converted to R units via risk distance. Same-bar SL/TP ambiguity resolved conservative (SL first).

> [!WARNING]
> Groups with $n < 30$ filled trades are explicitly flagged with ⚠️ **n < 30 (descriptive only)**. No statistical inference, edge confirmation, or hypothesis testing can be concluded from samples with $n < 30$.

| Performance Metric | CRT Strategy | SMC Strategy |
| :--- | :--- | :--- |
| **Signals Emitted** | 1 | 688 |
| **Trades Filled** | 1 (100.0%) | 688 (100.0%) |
| **No Fill (Expired / Pre-stopped)** | 0 (0.0%) | 0 (0.0% — market entry) |
| **Sample Flag** | ⚠️ **n = 1 (<30, descriptive only)** | **n = 688 (adequate sample)** |
| **Win Rate** | 100.00% (1 win / 0 loss) | 47.09% (324 wins / 364 losses) |
| **Average R per Trade** | +0.6258 R | +0.1983 R |
| **Expectancy** | +0.6258 R | +0.1983 R |
| **Profit Factor** | $\infty$ (gross gain 0.63R / loss 0.00R) | 1.40 (gross gain 478.43R / loss 341.98R) |
| **Total R Accumulated** | +0.63 R | +136.45 R |
| **Max Drawdown (R)** | 0.00 R | 49.93 R |
| **Median Holding Time** | 6 bars (1.5 hours) | 320.5 bars (80.1 hours) |
| **Exit Reasons Breakdown** | TP1_BE_STOP: 1 (100.0%) | STOP_LOSS: 351 (51.0%)<br>TP2: 247 (35.9%)<br>TP1_BE_STOP: 77 (11.2%)<br>TIMEOUT_MARK_TO_MARKET: 13 (1.9%) |

---

## 5. Temporal Stability: Half-Year Breakdown

Breakdown of out-of-sample performance across consecutive half-year intervals:

| Strategy | Half-Year Period | Bars in Window | Signals | Filled Trades | Win Rate | Expectancy (Avg R) | Profit Factor | Total R | Max Drawdown | Sample Flag |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| **CRT** | 2025-H1 (Jan–Jun) | 11,420 | 0 | 0 | n/a | n/a | n/a | 0.00 R | 0.00 R | ⚠️ n = 0 |
| **CRT** | 2025-H2 (Jul–Dec) | 12,135 | 1 | 1 | 100.0% | +0.6258 R | $\infty$ | +0.63 R | 0.00 R | ⚠️ n = 1 |
| **CRT** | 2026-H1 (Jan–Jun) | 11,872 | 0 | 0 | n/a | n/a | n/a | 0.00 R | 0.00 R | ⚠️ n = 0 |
| **CRT** | 2026-H2 (Jul–Nov) | 8,754 | 0 | 0 | n/a | n/a | n/a | 0.00 R | 0.00 R | ⚠️ n = 0 |
| **SMC** | 2025-H1 (Jan–Jun) | 11,420 | 162 | 162 | 47.53% | +0.1812 R | 1.40 | +29.35 R | 22.90 R | n = 162 |
| **SMC** | 2025-H2 (Jul–Dec) | 12,135 | 191 | 191 | 52.36% | +0.3378 R | 1.76 | +64.51 R | 33.31 R | n = 191 |
| **SMC** | 2026-H1 (Jan–Jun) | 11,872 | 193 | 193 | 40.41% | +0.0572 R | 1.10 | +11.04 R | 34.55 R | n = 193 |
| **SMC** | 2026-H2 (Jul–Nov) | 8,754 | 142 | 142 | 48.59% | +0.2221 R | 1.46 | +31.55 R | 19.76 R | n = 142 |

### Observations on Stability
- **CRT Strategy:** Replay yields exactly one emitted signal in 23 months. There is no time-series sample to evaluate temporal stability.
- **SMC Strategy:** Generates consistent monthly volume (15–48 trades/month) across all 4 half-years. Expectancy remained positive across all half-years (+0.18R, +0.34R, +0.06R, +0.22R), although 2026-H1 experienced compressed profitability (PF 1.10 vs 1.76 in 2025-H2) and a 34.55R drawdown.

---

## 6. CRT Target Type Analysis

For CRT signals, targets are either calculated from the benchmark candle range (`CRT_RANGE`) or fall back to an ATR/risk multiplier structure (`FALLBACK_RR`):

| Target Type | Emitted Signals | % of Signals | Filled Trades | Win Rate | Average R | Realized Trades |
| :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| `CRT_RANGE` | 0 | 0.0% | 0 | n/a | n/a | None |
| `FALLBACK_RR` | 1 | 100.0% | 1 | 100.0% | +0.6258 R | BUY 2025-12-10 05:45 UTC (+0.6258 R) |
| **Total** | **1** | **100.0%** | **1** | **100.0%** | **+0.6258 R** | ⚠️ n = 1 (<30) |

The single emitted CRT trade relied on `FALLBACK_RR`. Zero trades utilized `CRT_RANGE`.

---

## 7. Counterfactual Expectancy of Top Rejected Gates

Counterfactual replay re-prices rejected setups through the exact production entry, stop, and target calculations, simulating what *would* have happened if that specific gate were bypassed:

### CRT Top Rejected Gates (Counterfactual Simulation)

| Gate Bypassed | Valid Candidates | Filled Trades | Win Rate | Expectancy (Avg R) | Sample Flag |
| :--- | ---: | ---: | ---: | ---: | :--- |
| `TREND_CONFLICT` | 221 | 134 | 38.81% | -0.1607 R | n = 134 |
| `CONFIRMATION_PENDING` | 119 | 70 | 41.43% | -0.0842 R | n = 70 |
| `MICRO_SWEEP` | 74 | 39 | 41.03% | -0.0569 R | n = 39 |
| `EXCESSIVE_MANIPULATION` | 61 | 34 | 14.71% | -0.5971 R | n = 34 |
| `MICRO_RANGE` | 20 | 12 | 0.00% | -1.2305 R | ⚠️ n = 12 (<30) |
| `INVALID_ENTRY_ZONE` | 3 | 2 | 100.00% | +0.5259 R | ⚠️ n = 2 (<30) |
| `SCORE_BELOW_THRESHOLD` | 2 | 2 | 0.00% | -1.0283 R | ⚠️ n = 2 (<30) |

> [!NOTE]
> Every top rejected CRT gate with adequate sample size ($n \ge 30$) exhibits **negative counterfactual expectancy** (from -0.06R to -0.60R). In the baseline CRT pipeline, these gates effectively filter out losing setups.

### SMC Top Near-Miss Rejected Gates (Counterfactual Simulation)

Near-miss windows: `SCORE_BELOW_THRESHOLD` within 5 pts of threshold (60.0), `LTF_PENALTY` (-5.0 deduction), `CONFLUENCE_FLOOR` within 5 pts.

| Gate Bypassed | Distinct Opps | Filled Trades | Win Rate | Expectancy (Avg R) | Sample Flag |
| :--- | ---: | ---: | ---: | ---: | :--- |
| `SCORE_BELOW_THRESHOLD` (score 55–59.9) | 581 | 581 | 41.31% | +0.0993 R | n = 581 |
| `LTF_PENALTY` (qualified pre-LTF) | 319 | 319 | 42.95% | +0.1083 R | n = 319 |
| `CONFLUENCE_FLOOR` (score 15–19.9) | 153 | 153 | 35.29% | -0.0714 R | n = 153 |

---

## 8. What the Data Shows and What It Cannot Show

### What the Data Shows:
1. **CRT Emits Insufficient Trades in Live Production Form:** Across 44,181 15m bars from January 2025 to November 2026, CRT emitted exactly 1 trade. 85.8% of bars fail at `NO_SWEEP` and the remaining 14.2% are almost entirely blocked by `TREND_CONFLICT` (2,806 bars), `CONFIRMATION_PENDING` (1,611 bars), and `MICRO_SWEEP` (1,213 bars).
2. **CRT Sample Size is Statistically Unusable ($n=1$):** With a single filled trade, win rate, expectancy, and profit factor cannot be estimated.
3. **Existing CRT Gates Filter Unprofitable Trades:** Re-simulating rejected sweeps under counterfactual conditions reveals negative expectancy across all major gates: `TREND_CONFLICT` (-0.16R), `CONFIRMATION_PENDING` (-0.08R), `MICRO_SWEEP` (-0.06R), and `EXCESSIVE_MANIPULATION` (-0.60R).
4. **SMC Generates Continuous Trading Volume:** SMC emitted 688 distinct trades (29.9/month) with a 47.09% win rate, +0.1983R expectancy, and a 1.40 profit factor after $0.40 round-trip spread deduction.
5. **SMC Suffers Substantial Drawdowns:** SMC incurred a peak-to-trough drawdown of 49.93R and experienced extended holding periods (median 80.1 hours).

### What the Data Cannot Show:
1. **Edge or Lack of Edge for CRT:** The data cannot confirm whether CRT has a true statistical edge on XAU/USD 15m because the sample size is $n=1$.
2. **Generalizability Across Other Timeframes/Instruments:** These results strictly represent XAU/USD 15m with 1h primary and 4h higher-timeframe inputs under the stated spread ($0.40).
3. **Execution Slippage Beyond Fixed Spread:** Replay models limit execution and partial exits under idealized tick fill rules; real broker slippage during high-volatility events cannot be assessed.

---

## 9. CRT Both-Sides Sweep Experiment (`--crt-both-sides`)

### Hypothesis and Objective
In the production `CRTAnalyzer` (`crt_analyzer.py:112` and `:192-237`), sweep side is strictly tied to the HTF benchmark candle color:
- Bullish HTF candle (`close > open`) $\rightarrow$ evaluates only sweeps below `range_low` (Bullish AMD).
- Bearish HTF candle (`close < open`) $\rightarrow$ evaluates only sweeps above `range_high` (Bearish AMD).

The goal of this flag-gated experiment is to test whether this color coupling is "hiding setups" by missing counter-color sweeps (e.g., sweeping the high of a bullish candle or the low of a bearish candle). 

Under `--crt-both-sides`, a replay-local subclass `CRTBothSidesAnalyzer(CRTAnalyzer)` evaluates sweeps of **EITHER** side of the HTF benchmark candle, setting trade direction from the swept side (swept low $\rightarrow$ BUY, swept high $\rightarrow$ SELL), regardless of HTF candle color. Production defaults and code paths were left unmodified.

### Comparison: Baseline CRT vs CRT Both-Sides

| Metric | Baseline CRT | CRT Both-Sides (`--crt-both-sides`) | Delta |
| :--- | :--- | :--- | :--- |
| **Bars Evaluated** | 44,181 | 44,181 | 0 |
| **Warm-up Context Bars** | 43,237 | 43,237 | 0 |
| **`NO_SWEEP` Bars** | 37,902 (85.79%) | 21,317 (48.25%) | -16,585 bars (-43.8%) |
| **Bars with Validated Sweep** | 6,279 (14.21%) | 22,864 (51.75%) | +16,585 bars (+264.1%) |
| **Signals Emitted (`CONFIRMED_SETUP`)** | 1 | 1 | 0 |
| **Emitted Trade Details** | BUY 2025-12-10 05:45 UTC | BUY 2026-05-08 12:45 UTC | Distinct event |
| **Filled Trades** | 1 (100.0%) | 0 (0.0%) | -1 filled trade |
| **Unfilled / Expired Trades** | 0 (0.0%) | 1 (100.0% — `NO_FILL_EXPIRED`) | +1 expired |
| **Sample Flag** | ⚠️ **n = 1 (<30, descriptive only)** | ⚠️ **n = 0 (no filled trades)** | Purely descriptive |
| **Realized R / Expectancy** | +0.6258 R | n/a (0 fills) | n/a |

### Rejection Funnel Comparison (Bars and Distinct Sweeps)

| Gate | Baseline Bars | Baseline Sweeps | Both-Sides Bars | Both-Sides Sweeps | Bar Delta | Sweep Delta |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `NO_SWEEP` | 37,902 | 0 | 21,317 | 0 | -16,585 | 0 |
| `TREND_CONFLICT` | 2,806 | 1,995 | 10,254 | 7,191 | +7,448 | +5,196 |
| `CONFIRMATION_PENDING` | 1,611 | 1,202 | 6,727 | 4,801 | +5,116 | +3,599 |
| `MICRO_SWEEP` | 1,213 | 821 | 4,165 | 2,763 | +2,952 | +1,942 |
| `EXCESSIVE_MANIPULATION` | 386 | 285 | 1,244 | 932 | +858 | +647 |
| `MICRO_RANGE` | 237 | 152 | 443 | 304 | +206 | +152 |
| `EXCESSIVE_RANGE` | 0 | 0 | 26 | 15 | +26 | +15 |
| `INVALID_ENTRY_ZONE` | 20 | 17 | 4 | 3 | -16 | -14 |
| `EXCESSIVE_RISK_DISTANCE` | 2 | 1 | 0 | 0 | -2 | -1 |
| `SCORE_BELOW_THRESHOLD` | 2 | 1 | 0 | 0 | -2 | -1 |
| `PATH_BLOCKED` | 1 | 1 | 0 | 0 | -1 | -1 |
| `CONFIRMED_SETUP` | 1 | 1 | 1 | 1 | 0 | 0 |
| **Total** | **44,181** | **4,476** | **44,181** | **16,010** | **0** | **+11,534** |

### Counterfactual Expectancy: Baseline vs Both-Sides

Counterfactual simulation re-prices rejected setups through the full trade geometry:

| Gate | Baseline Candidates | Baseline Filled | Baseline Win Rate | Baseline Expectancy | Both-Sides Candidates | Both-Sides Filled | Both-Sides Win Rate | Both-Sides Expectancy | Sample Flag |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| `TREND_CONFLICT` | 221 | 134 | 38.81% | -0.1607 R | 789 | 488 | 32.17% | -0.1834 R | n $\ge$ 30 |
| `CONFIRMATION_PENDING` | 119 | 70 | 41.43% | -0.0842 R | 638 | 389 | 36.50% | -0.0909 R | n $\ge$ 30 |
| `MICRO_SWEEP` | 74 | 39 | 41.03% | -0.0569 R | 316 | 206 | 36.89% | -0.0595 R | n $\ge$ 30 |
| `EXCESSIVE_MANIPULATION` | 61 | 34 | 14.71% | -0.5971 R | 160 | 85 | 20.00% | -0.4937 R | n $\ge$ 30 |
| `MICRO_RANGE` | 20 | 12 | 0.00% | -1.2305 R | 39 | 26 | 15.38% | -0.8677 R | ⚠️ n < 30 |
| `EXCESSIVE_RANGE` | 0 | 0 | n/a | n/a | 5 | 3 | 100.00% | +0.7043 R | ⚠️ n < 30 |

### What the Both-Sides Data Shows:
1. **Sweep Detection Multiplies 3.6x:** Decoupling the sweep side from candle color dropped `NO_SWEEP` bars from 37,902 down to 21,317, capturing 16,585 additional sweep bars (+264%) and increasing distinct sweep events from 4,476 to 16,010.
2. **Downstream Gates Block the New Sweeps:** The newly uncovered sweeps did not translate into confirmed setups. Instead, they cascaded into existing downstream rejection gates:
   - `TREND_CONFLICT` increased by +7,448 bars (+5,196 distinct sweeps).
   - `CONFIRMATION_PENDING` increased by +5,116 bars (+3,599 distinct sweeps).
   - `MICRO_SWEEP` increased by +2,952 bars (+1,942 distinct sweeps).
   - `EXCESSIVE_MANIPULATION` increased by +858 bars (+647 distinct sweeps).
3. **Emitted Signals Remain at Exactly 1 ($n=1$):** Both-sides produced 1 emitted signal (BUY on 2026-05-08 12:45 UTC), which expired unfilled (`NO_FILL_EXPIRED`), resulting in 0 filled trades.
4. **Attribution of Baseline Signal Divergence:** The single baseline emitted trade (BUY on 2025-12-10 05:45 UTC) was not emitted in both-sides because a subsequent high breach occurred at 05:30 UTC. Both-sides prioritized the more recent high sweep, switching direction to SELL, which was subsequently rejected by `TREND_CONFLICT`.
5. **Counterfactual Expectancy Remains Uniformly Negative:** All major gates with $n \ge 30$ in the both-sides run show negative expectancy:
   - `TREND_CONFLICT`: -0.1834 R (488 fills, 32.17% win rate)
   - `CONFIRMATION_PENDING`: -0.0909 R (389 fills, 36.50% win rate)
   - `MICRO_SWEEP`: -0.0595 R (206 fills, 36.89% win rate)
   - `EXCESSIVE_MANIPULATION`: -0.4937 R (85 fills, 20.00% win rate)
6. **Conclusion on Hypothesis:** The data indicates that tying sweep side to candle color is **not** hiding positive-expectancy setups. Decoupling it introduces thousands of sweeps that are heavily filtered by downstream trend and confirmation gates, and counterfactual simulation of those bypassed gates yields net negative returns across large samples.

