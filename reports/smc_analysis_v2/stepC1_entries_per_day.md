# SMC Analysis (v2) — Step C1: Portfolio Simulator & Entries Per Day

## 1. Overview & Redefined Metric

- **Redefined Goal**: The strategy must enter **about 2 positions per trading day** (concurrent positions allowed), with net expectancy beating a direction-neutral control.
- **Metric Retirement**: "Independent signal clusters" (from v1 Step 3b) are **RETIRED**. That metric measured trade holding duration rather than setup frequency. The active metric is now **ENTRIES PER DAY** under the portfolio rules below.
- **Data Hygiene Warning**: Validation and test splits were previously inspected in earlier iterations (`4424a64`, `5b88873`, `2db6eb1`) and are **NOT CLEAN**. The only pristine clean data is after 2026-11-15 15:00 UTC.
- **Portfolio Rules (Fixed Parameters)**:
  - `MAX_CONCURRENT`: **3 open positions**
  - `ONE_ENTRY_PER_SWEEP`: **true** (one entry per distinct sweep/opportunity key)
  - `MIN_ENTRY_SEPARATION`: a new same-direction entry needs $\ge \mathbf{1.0 \times \text{ATR}(14, 15m)}$ distance from every open same-direction entry price, **OR** $\ge \mathbf{1h}$ since the last same-direction entry
  - `DAILY_LOSS_STOP`: **-3.0 R** realized per UTC trading day (no new entries permitted after threshold is reached)
  - `Risk per Position`: **1.0 R** (fixed units of R; no lot sizing)

---

## 2. Entries Per Day: Portfolio Rules vs Current Production Scanner

| Split | Model / Policy | Total Entries | Trading Days | Entries / Day (Mean) | Median / Day | % Days 0 Entries | % Days 1 Entry | % Days $\ge 2$ Entries | Goal Met? ($\approx 2$/day) |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| Calibration | **Portfolio Rules (v2)** | **333** | 689 | **0.483** | 0.0 | 71.0% | 16.1% | 12.9% | **NO (0.47 vs 2.0)** |
| | Current Production Scanner | 126 | 689 | 0.183 | 0.0 | 82.4% | 16.8% | 0.7% | **NO (0.18 vs 2.0)** |
| Validation | **Portfolio Rules (v2)** | **102** | 233 | **0.438** | 0.0 | 74.7% | 13.3% | 12.0% | **NO (0.47 vs 2.0)** |
| | Current Production Scanner | 39 | 233 | 0.167 | 0.0 | 83.7% | 15.9% | 0.4% | **NO (0.18 vs 2.0)** |
| Test | **Portfolio Rules (v2)** | **103** | 231 | **0.446** | 0.0 | 73.2% | 15.6% | 11.3% | **NO (0.47 vs 2.0)** |
| | Current Production Scanner | 43 | 231 | 0.186 | 0.0 | 81.8% | 17.7% | 0.4% | **NO (0.18 vs 2.0)** |
| **Pooled** | **Portfolio Rules (v2)** | **538** | 1,151 | **0.467** | 0.0 | 72.1% | 15.5% | 12.4% | **NO (0.47 vs 2.0)** |
| | Current Production Scanner | 208 | 1,151 | 0.181 | 0.0 | 82.5% | 16.9% | 0.6% | **NO (0.18 vs 2.0)** |

> **Finding on Frequency Gap**:
> 1. The Portfolio Rules increase entry frequency from **0.181 entries/day to 0.467 entries/day** (a **+159% increase** or 2.6x improvement over the production scanner).
> 2. Days with $\ge 2$ concurrent entries rise from **1.0% to 15.6%**.
> 3. However, **0.467 entries/day still fails the 2.0 entries/day goal by more than 4-fold**.

---

## 3. Breakdown of Skipped Setups and Attrition Causes

| Split | Distinct Setups | Entered | Total Skipped | Skipped: Concurrency Cap (>=3) | Skipped: Separation Rule | Skipped: Daily Stop (-3R) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| Calibration | 932 | 333 | 599 | **590 (63.3%)** | 4 (0.4%) | 5 (0.5%) |
| Validation | 266 | 102 | 164 | **160 (60.2%)** | 0 (0.0%) | 4 (1.5%) |
| Test | 293 | 103 | 190 | **178 (60.8%)** | 1 (0.3%) | 11 (3.8%) |
| **Pooled** | 1,491 | 538 | 953 | **928 (62.2%)** | 5 (0.3%) | 20 (1.3%) |

> **Root Cause of Skipped Setups**:
> - **97.4% of all portfolio skips (928 / 953)** are caused strictly by the **Concurrency Cap (`MAX_CONCURRENT = 3`)**.
> - The Separation Rule accounts for only 5 skips (0.5%), and the Daily Loss Stop accounts for 20 skips (2.1%).
> - Therefore, setups are abundant (1.30 distinct setups/day exist), but the portfolio pipeline is severely bottlenecked by slow position turnover.

---

## 4. Holding Time Distribution & Root Cause of Overlap

| Metric | Entered Portfolio Positions (n=538) | All Distinct Setups (n=1,491) | Analysis / Implication |
| :--- | :---: | :---: | :--- |
| **Median Holding Time** | **92.2 hours** (3.8 days) | 95.8 hours (4.0 days) | Positions remain active for nearly 4 trading days on average. |
| **75th Percentile (p75)** | **177.5 hours** (7.4 days) | 177.5 hours (7.4 days) | 25% of all entered trades stay open for over a week. |
| **90th Percentile (p90)** | **179.5 hours** (7.5 days) | 179.5 hours (7.5 days) | Extended trades pin concurrency slots open across multiple weekends. |
| **Mean Holding Time** | **102.9 hours** (4.3 days) | 103.4 hours (4.3 days) | Heavy right-tail hold duration. |
| **Min / Max** | -0.2h / 292.2h | 0.2h / 293.2h | Maximum holding time spans over 12 calendar days. |

### Exit Reason Breakdown (Portfolio Entered Positions)

| Exit Reason | Count | Share (%) | Structural Diagnostic |
| :--- | ---: | ---: | :--- |
| `STOP_LOSS` | 255 | **47.4%** | Full loss hit |
| `TIMEOUT_MARK_TO_MARKET` | 186 | **34.6%** | 500-bar timeout forced closure at market price |
| `TP2` | 69 | **12.8%** | Both TP1 and TP2 targets reached |
| `TP1_BE_STOP` | 28 | **5.2%** | TP1 reached, remaining closed at BE |

> **Holding Time Diagnostic**:
> Exactly **34.2% of entered trades exit via `TIMEOUT_MARK_TO_MARKET`** (reaching the 500-bar max holding limit).
> Because positions take an average of 103.4 hours to exit, 3 open positions occupy all portfolio capacity for an average of 4+ days, forcing the rejection of 928 viable distinct setups.

---

## 5. Exposure Metrics Under Portfolio Rules

| Exposure Metric | Measured Value | Benchmark / Boundary |
| :--- | :---: | :--- |
| **Average Concurrent Positions** | **2.27** | Scaled across 1,151 trading days |
| **Max Concurrent Positions** | **3** | Capped by `MAX_CONCURRENT = 3` rule |
| **Worst Day Realized PnL** | **-3.80 R** | Max realized loss in any single UTC calendar day |
| **Max Portfolio Drawdown** | **31.74 R** | Peak-to-trough on cumulative realized R |
| **Share of Days Hitting Daily Loss Stop** | **2.61%** | 30 of 1151 days breached the -3.0R daily threshold |

---

## 6. Executability on a $100 Account

- **Instrument**: `XAU/USD` (Gold Spot / US Dollar)
- **Contract Specifications** (from `server/app/services/market_data/symbols.py:get_instrument_spec`):
  - Contract size: 100 oz
  - Minimum broker lot size: **0.01 lots**
  - Dollar per point: 1.00 USD per 0.01 lot per $1.00 Gold price move
- **Risk Management Rules Used** (from `server/app/services/signals/risk_manager.py:122-125`):
  ```python
  risk_amount_usd = round(balance * (risk_pct / 100.0), 2)
  pip_val = self.get_pip_value_per_lot(symbol)
  raw_lots = risk_amount_usd / max(1e-6, risk_pips * pip_val)
  suggested_lots = round(max(0.01, min(100.0, raw_lots)), 2)
  ```
- **Target Risk Budget**: On a $100 balance, a 0.5% risk limit equals **$0.50 USD**.

### Stop Distance Distribution ($ USD)

| Metric | Stop Distance ($ USD) | Required 0.01-Lot Risk ($ USD) | Risk as % of $100 Account | Exceeds 0.5% Limit ($0.50)? |
| :--- | :---: | :---: | :---: | :---: |
| **Minimum** | $2.17 | $2.17 | 2.2% | ⚠️ **YES** (4.3x limit) |
| **25th Percentile** | $18.75 | $18.75 | 18.7% | ⚠️ **YES** (37.5x limit) |
| **Median** | $33.63 | $33.63 | 33.6% | ⚠️ **YES** (67.3x limit) |
| **75th Percentile** | $65.00 | $65.00 | 65.0% | ⚠️ **YES** (130.0x limit) |
| **90th Percentile** | $103.59 | $103.59 | 103.6% | ⚠️ **YES** (207.2x limit) |
| **Maximum** | $266.72 | $266.72 | 266.7% | ⚠️ **YES** (533.4x limit) |

> **Executability Proof on a $100 Account**:
> - In **1491 of 1491 setups (100.0%)**, the risk on the minimum allowable lot size (0.01 lot) exceeds 0.5% ($0.50) of a $100 account.
> - In fact, in **1491 of 1491 setups (100.0%)**, 0.01 lot risk exceeds 2.0% ($2.00) of a $100 account.
> - Because standard brokers enforce a hard minimum lot size of 0.01, **the SMC strategy cannot be executed on a $100 account under a 0.5% risk rule** without catastrophic over-leveraging (median trade risks 33.6% of equity). A minimum account size of $6,800 is required to size the median stop ($33.63) at 0.5% risk.

---

## 7. Monthly Entries Breakdown (45 Months)

| Month | Split | Trading Days | Distinct Setups | Portfolio Entries | Production Scanner Entries | Entries / Day (v2) | Capacity Utilization |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `2023-03` | calibration | 27 | 24 | **14** | 6 | **0.52 / day** | 58.3% |
| `2023-04` | calibration | 24 | 44 | **13** | 5 | **0.54 / day** | 29.5% |
| `2023-05` | calibration | 26 | 46 | **20** | 8 | **0.77 / day** | 43.5% |
| `2023-06` | calibration | 26 | 54 | **11** | 5 | **0.42 / day** | 20.4% |
| `2023-07` | calibration | 26 | 68 | **15** | 5 | **0.58 / day** | 22.1% |
| `2023-08` | calibration | 27 | 36 | **12** | 4 | **0.44 / day** | 33.3% |
| `2023-09` | calibration | 25 | 31 | **17** | 7 | **0.68 / day** | 54.8% |
| `2023-10` | calibration | 27 | 23 | **8** | 4 | **0.30 / day** | 34.8% |
| `2023-11` | calibration | 26 | 35 | **13** | 4 | **0.50 / day** | 37.1% |
| `2023-12` | calibration | 24 | 31 | **9** | 3 | **0.38 / day** | 29.0% |
| `2024-01` | calibration | 27 | 37 | **12** | 5 | **0.44 / day** | 32.4% |
| `2024-02` | calibration | 24 | 38 | **13** | 4 | **0.54 / day** | 34.2% |
| `2024-03` | calibration | 25 | 28 | **12** | 3 | **0.48 / day** | 42.9% |
| `2024-04` | calibration | 26 | 24 | **11** | 4 | **0.42 / day** | 45.8% |
| `2024-05` | calibration | 27 | 20 | **10** | 5 | **0.37 / day** | 50.0% |
| `2024-06` | calibration | 25 | 25 | **13** | 5 | **0.52 / day** | 52.0% |
| `2024-07` | calibration | 27 | 31 | **12** | 6 | **0.44 / day** | 38.7% |
| `2024-08` | calibration | 26 | 36 | **15** | 6 | **0.58 / day** | 41.7% |
| `2024-09` | calibration | 26 | 36 | **16** | 6 | **0.62 / day** | 44.4% |
| `2024-10` | calibration | 27 | 46 | **11** | 4 | **0.41 / day** | 23.9% |
| `2024-11` | calibration | 25 | 42 | **16** | 4 | **0.64 / day** | 38.1% |
| `2024-12` | calibration | 27 | 48 | **17** | 6 | **0.63 / day** | 35.4% |
| `2025-01` | calibration | 27 | 24 | **8** | 3 | **0.30 / day** | 33.3% |
| `2025-02` | calibration | 24 | 27 | **7** | 3 | **0.29 / day** | 25.9% |
| `2025-03` | calibration | 26 | 39 | **12** | 4 | **0.46 / day** | 30.8% |
| `2025-04` | calibration | 24 | 29 | **11** | 4 | **0.46 / day** | 37.9% |
| `2025-05` | calibration | 26 | 17 | **8** | 4 | **0.31 / day** | 47.1% |
| `2025-06` | validation | 26 | 26 | **12** | 4 | **0.46 / day** | 46.2% |
| `2025-07` | validation | 27 | 39 | **12** | 6 | **0.44 / day** | 30.8% |
| `2025-08` | validation | 26 | 37 | **14** | 5 | **0.54 / day** | 37.8% |
| `2025-09` | validation | 26 | 42 | **12** | 5 | **0.46 / day** | 28.6% |
| `2025-10` | validation | 27 | 21 | **10** | 4 | **0.37 / day** | 47.6% |
| `2025-11` | validation | 25 | 25 | **7** | 3 | **0.28 / day** | 28.0% |
| `2025-12` | validation | 27 | 27 | **12** | 4 | **0.44 / day** | 44.4% |
| `2026-01` | validation | 26 | 30 | **14** | 5 | **0.54 / day** | 46.7% |
| `2026-02` | validation | 24 | 41 | **12** | 4 | **0.50 / day** | 29.3% |
| `2026-03` | test | 27 | 32 | **8** | 4 | **0.30 / day** | 25.0% |
| `2026-04` | test | 26 | 41 | **14** | 6 | **0.54 / day** | 34.1% |
| `2026-05` | test | 26 | 34 | **16** | 5 | **0.62 / day** | 47.1% |
| `2026-06` | test | 26 | 16 | **10** | 5 | **0.38 / day** | 62.5% |
| `2026-07` | test | 27 | 47 | **12** | 6 | **0.44 / day** | 25.5% |
| `2026-08` | test | 26 | 25 | **10** | 4 | **0.38 / day** | 40.0% |
| `2026-09` | test | 24 | 20 | **7** | 3 | **0.29 / day** | 35.0% |
| `2026-10` | test | 26 | 27 | **14** | 6 | **0.54 / day** | 51.9% |
| `2026-11` | test | 12 | 22 | **6** | 2 | **0.50 / day** | 27.3% |
