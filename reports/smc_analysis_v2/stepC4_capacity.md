# SMC Analysis v2 — Step C4: Capacity Analysis & Gap to 2 Entries/Day

> [!IMPORTANT]
> **Contamination Disclaimer**:
> Replay data covers Calibration (60%), Validation (20%), and Test (20%).
> As documented, validation and test splits were inspected in earlier rounds and are contaminated; clean forward holdout data begins strictly after 2026-11-15 15:00 UTC.

## 1. Setup Availability by Funnel Rejection Gate

Shows the number of distinct sweeps (opportunity keys) available at each gate of the strategy before portfolio rules are applied.

| Funnel Stage / Rejection Gate | Description | Calibration ($n=689\text{d}$) | Validation ($n=233\text{d}$) | Test ($n=231\text{d}$) | Pooled Total ($1,151\text{d}$) | Distinct Setups / Day |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| `CONFIRMED_SETUP` | Accepted Signals (Emitted by SMCStrategy) | 932 (1.35/d) | 266 (1.14/d) | 293 (1.27/d) | 1,491 | **1.295 / day** |
| `LTF_PENALTY` | LTF Unconfirmed Near-Miss (-5 pt penalty) | 490 (0.71/d) | 135 (0.58/d) | 130 (0.56/d) | 755 | **0.656 / day** |
| `CONFLUENCE_FLOOR` | Confluence Floor Rejection (Struct + Liq < 20) | 539 (0.78/d) | 139 (0.60/d) | 221 (0.96/d) | 899 | **0.781 / day** |
| `PA_FLOOR` | Price Action Floor Rejection (PA < 10) | 285 (0.41/d) | 91 (0.39/d) | 107 (0.46/d) | 483 | **0.420 / day** |
| `SCORE_BELOW_THRESHOLD` | Score Floor Rejection (Pre-LTF Score < 60) | 11,072 (16.07/d) | 3,909 (16.78/d) | 3,770 (16.32/d) | 18,750 | **16.290 / day** |

### Cumulative Setups Available If Upstream Gates Are Reached

1. **`CONFIRMED_SETUP` Only (Baseline Strategy Output)**: **1,491 distinct setups** (1.295 setups/day).
2. **`CONFIRMED_SETUP` + `LTF_PENALTY` (Unconfirmed Near-Miss)**: **2,246 distinct setups** (1.951 setups/day).
3. **All Filtered Setups (`PA_FLOOR` + `CONFLUENCE_FLOOR`)**: **3,628 distinct setups** (3.152 setups/day).
4. **Total Raw Sweeps Evaluated (`SCORE_BELOW_THRESHOLD` + all above)**: **22,378 distinct sweeps** (19.44 sweeps/day).

---

## 2. Sensitivity Analysis to Portfolio Parameters

> Evaluates sensitivity across all 1,491 accepted setups. Descriptive only; no winner is picked.

### A. Sensitivity to `MAX_CONCURRENT` (Positions Allowed: 1 to 5)
*Fixed: `MIN_ENTRY_SEPARATION = 1.0 ATR`, `DAILY_LOSS_STOP = -3.0R`*

| `MAX_CONCURRENT` | Calibration Entries/Day (Mean R) | Validation Entries/Day (Mean R) | Test Entries/Day (Mean R) | Pooled Entries/Day (Mean R) | Win Rate | Skipped by Concurrency Cap |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 0.183 (+0.0369R) | 0.167 (+0.2274R) | 0.186 (-0.1147R) | **0.181 entries/day** (+0.0413R) | 42.8% | 1,283 setups |
| **2** | 0.344 (+0.0544R) | 0.322 (+0.2459R) | 0.329 (-0.0572R) | **0.337 entries/day** (+0.0695R) | 42.3% | 1,100 setups |
| **3** | 0.483 (+0.0437R) | 0.438 (+0.3424R) | 0.446 (-0.0131R) | **0.467 entries/day** (+0.0894R) | 43.7% | 901 setups |
| **4** | 0.607 (+0.0404R) | 0.554 (+0.3523R) | 0.545 (+0.0429R) | **0.585 entries/day** (+0.1006R) | 43.7% | 746 setups |
| **5** | 0.707 (+0.0559R) | 0.644 (+0.3897R) | 0.636 (+0.0624R) | **0.681 entries/day** (+0.1210R) | 45.0% | 610 setups |

### B. Sensitivity to `MIN_ENTRY_SEPARATION` (OFF, 0.5 ATR, 1.0 ATR, 2.0 ATR)
*Fixed: `MAX_CONCURRENT = 3`, `DAILY_LOSS_STOP = -3.0R`*

| `MIN_ENTRY_SEPARATION` | Calibration Entries/Day (Mean R) | Validation Entries/Day (Mean R) | Test Entries/Day (Mean R) | Pooled Entries/Day (Mean R) | Win Rate | Skipped by Separation |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **OFF** | 0.482 (+0.0436R) | 0.438 (+0.3424R) | 0.450 (-0.0691R) | **0.467 entries/day** (+0.0785R) | 43.5% | 0 setups |
| **0.5 ATR** | 0.482 (+0.0424R) | 0.438 (+0.3424R) | 0.446 (-0.0131R) | **0.467 entries/day** (+0.0888R) | 43.8% | 3 setups |
| **1.0 ATR** | 0.483 (+0.0437R) | 0.438 (+0.3424R) | 0.446 (-0.0131R) | **0.467 entries/day** (+0.0894R) | 43.7% | 5 setups |
| **2.0 ATR** | 0.483 (+0.0437R) | 0.438 (+0.3424R) | 0.446 (-0.0131R) | **0.467 entries/day** (+0.0894R) | 43.7% | 6 setups |

### C. Sensitivity to `DAILY_LOSS_STOP` (OFF, -2.0R, -3.0R, -5.0R)
*Fixed: `MAX_CONCURRENT = 3`, `MIN_ENTRY_SEPARATION = 1.0 ATR`*

| `DAILY_LOSS_STOP` | Calibration Entries/Day (Mean R) | Validation Entries/Day (Mean R) | Test Entries/Day (Mean R) | Pooled Entries/Day (Mean R) | Win Rate | Trading Days Loss Stop Hit | Setups Skipped by Stop |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **OFF** | 0.488 (+0.0309R) | 0.459 (+0.2668R) | 0.455 (-0.0308R) | **0.476 entries/day** (+0.0651R) | 42.3% | 0 days | 0 setups |
| **-2.0R** | 0.466 (+0.0141R) | 0.425 (+0.3833R) | 0.442 (+0.0011R) | **0.454 entries/day** (+0.0816R) | 43.5% | 39 days | 113 setups |
| **-3.0R** | 0.483 (+0.0437R) | 0.438 (+0.3424R) | 0.446 (-0.0131R) | **0.467 entries/day** (+0.0894R) | 43.7% | 16 days | 47 setups |
| **-5.0R** | 0.488 (+0.0309R) | 0.459 (+0.2668R) | 0.455 (-0.0308R) | **0.476 entries/day** (+0.0651R) | 42.3% | 0 days | 0 setups |

---

## 3. Gap to 2 Entries/Day: Decomposition & Bottleneck Analysis

The target frequency is **2.000 entries per trading day**.

### A. Step-by-Step Gap Closure

| Step | Configuration / Mechanism | Realized Entries/Day | Absolute Gain | Gap Closed (% of 1.819 gap) | Remaining Gap to 2.0/day |
| :---: | :--- | :---: | :---: | :---: | :---: |
| Baseline | Current production scanner (`has_active_position` + 2h cooldown) | 0.181 | — | 0.0% | 1.819 entries/day |
| Step (i) | Remove `has_active_position` block, allow `MAX_CONCURRENT = 3` | 0.467 | +0.287 | 15.8% | 1.533 entries/day |
| Step (ii) | Shorten 2h cooldown (allow entries with >= 1h or 1.0 ATR separation) | 0.467 | +0.000 | 0.0% | 1.533 entries/day |
| Theoretical Max | Remove ALL concurrency & cooldown caps (`MAX_CONCURRENT = \infty`) | 1.295 | +0.828 | 45.5% | 0.705 entries/day |
| **Shortfall** | **Gap remaining even with infinite slots and zero cooldown** | — | — | — | **0.705 entries/day** |

### B. The Dual Bottlenecks: Raw Frequency Deficit & Holding Time Choke

Achieving 2.0 entries/day is constrained by two distinct structural barriers:

#### Bottleneck 1: Raw Signal Generation Shortfall (35% Deficit)
- The production SMC strategy logic (`DEFAULT_MIN_SCORE = 60`, `PA_FLOOR = 10`, `CONFLUENCE_FLOOR = 20`) emits exactly **1,491 distinct opportunities** across 1,151 trading days, which is **1.295 setups/day**.
- Even if every single emitted signal were executed instantly with zero risk limits, zero cooldown, and unlimited capital, the strategy physically falls short of 2.0/day by **0.705 setups/day** (a 35.2% deficit).
- **Where raw setups exist**: Incorporating the **755 distinct `LTF_PENALTY` near-misses** (0.656/day) would bring the raw pool to **2,246 setups** (1.951 setups/day, within 2.4% of 2.0/day).

#### Bottleneck 2: Holding Time Concurrency Choke (Mathematical Capacity Limit)
- Under the portfolio rules (`MAX_CONCURRENT = 3`), the mathematical relationship between entries per day ($E$), concurrency ($C$), and mean holding time in hours ($H$) is:
  $$E_{\max} = \frac{C \times 24}{H}$$
- With $C = 3$ and measured SMC mean holding time $H = 103.4\text{ hours}$ (median 95.8h; 34.2% timeout after 500 bars):
  $$E_{\max} = \frac{3 \times 24}{103.4} = \mathbf{0.696\text{ entries/day}}$$
- This proves that even if raw signals were unlimited, **3 concurrency slots with 103-hour holding times can physically never exceed 0.70 entries/day**!
- To enter **2.0 entries/day** under $C = 3$, mean holding time MUST be reduced to:
  $$H \le \frac{3 \times 24}{2.0} = \mathbf{36.0\text{ hours}}$$
  (A 65% reduction from the current 103.4h hold!).

### C. What Remains Uncovered (Actionable Levers for Phase C2)

To reach ~2 entries/day with positive net expectancy in Phase C2, any viable candidate MUST address both levers simultaneously:
1. **Expand Raw Setup Ingestion**: Ingest the `LTF_PENALTY` cohort (755 setups, bringing raw pool from 1.295 to 1.951/day) or incorporate high-expectancy near-miss cohorts without loosening core floors.
2. **Shorten Trade Duration**: Introduce an active time stop (e.g., exit if unresolved after 24-36h) or tighter partial TP to reduce mean holding time from 103.4h down to <= 36.0h, unchoking the 3 concurrency slots.
3. **Production Scanner Refactoring Required**:
   - `server/app/services/telegram/scanner.py:273`: Remove `has_active_position` global block; replace with `len(active_positions) < MAX_CONCURRENT`.
   - `server/app/services/telegram/scanner.py:38`: Replace `SIGNAL_COOLDOWN_HOURS = 2` with ATR-based separation and sweep de-duplication.
