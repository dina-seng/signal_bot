# SMC Analysis — Step 6: Pre-Registered Candidates Calibration Evaluation

## 1. Protocol & Acceptance Gate Verification

- **Evaluation Split**: **CALIBRATION ONLY** (2023-03-01 00:00 UTC → 2025-05-21 08:15 UTC).
- **Sample Size**: 689 trading days across 27 calendar months.
- **Clean Separation Rule**: Validation and test sets are **NOT evaluated** in this step.
- **Pre-Registered Qualification Criteria (Step 5)**:
  1. **Independent Signals / Day**: $\ge \mathbf{2.0}$
  2. **Expectancy over Control**: Mean R $> \mathbf{+0.0658R}$ (99th percentile of 1,000 random-direction seeds)
  3. **Monthly Stability**: No single calendar month contributes $> \mathbf{25.0\%}$ of total R

---

## 2. Candidate Evaluation Results Table (Calibration)

| Candidate ID | Signals (n) | Indep Signals / Day | Mean R | Win Rate | Daily Cluster SE | Control Percentile | Max Month % of Total R | Qualified? | Reason / Verdict |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :--- |
| `C1_PER_DIRECTION_SWEEP_DEDUP` | 140 | **0.203** | **+0.1697** | 45.0% | 0.1177 | 98.4% | 37.7% | 🔴 **NOT QUALIFIED** | Frequency fails (< 2.0/day) |
| `C3_KILLZONE_SESSION_FILTER` | 125 | **0.181** | **+0.1392** | 44.0% | 0.1189 | 96.2% | 37.3% | 🔴 **NOT QUALIFIED** | Frequency fails (< 2.0/day) |
| `C4_LIMIT_ORDER_FVG_ENTRY` | 94 | **0.136** | **+0.0738** | 37.2% | 0.1526 | 88.5% | 133.5% | 🔴 **NOT QUALIFIED** | Frequency fails (< 2.0/day) |
| `C2_TIMEFRAME_15M_PRIMARY` | 89 | **0.129** | **+0.0840** | 38.2% | 0.1497 | 12.3% | 81.3% | 🔴 **NOT QUALIFIED** | Frequency < 2.0/day |
| `C5_COMPOSITE_15M_KILLZONE_LIMIT` | 403 | **0.585** | **-0.0557** | 35.2% | 0.0691 | 35.6% | 100.0% | 🔴 **NOT QUALIFIED** | Frequency fails (< 2.0/day) |

---

## 3. Directional Breakdown & Stability Analysis

| Candidate ID | BUY Trades (n) | BUY Mean R | SELL Trades (n) | SELL Mean R | Negative Months | Max Month Detail |
| :--- | ---: | ---: | ---: | ---: | :---: | :--- |
| `C1_PER_DIRECTION_SWEEP_DEDUP` | 74 | +0.3924 | 66 | -0.0799 | 10/27 | 2023-03 (+8.97R / +23.76R = 37.7%) |
| `C3_KILLZONE_SESSION_FILTER` | 69 | +0.2716 | 56 | -0.0241 | 14/27 | 2023-03 (+6.49R / +17.39R = 37.3%) |
| `C4_LIMIT_ORDER_FVG_ENTRY` | 57 | +0.1230 | 37 | -0.0020 | 15/27 | 2024-10 (+9.26R / +6.94R = 133.5%) |
| `C2_TIMEFRAME_15M_PRIMARY` | 49 | +0.1539 | 40 | -0.0016 | 11/27 | 2024-02 (+6.08R / +7.47R = 81.3%) |
| `C5_COMPOSITE_15M_KILLZONE_LIMIT` | 221 | +0.1269 | 182 | -0.2774 | 15/27 | Total R is negative (-22.45R) |

---

## 4. In-Depth Candidate Diagnostics

### Candidate 1: `C1_PER_DIRECTION_SWEEP_DEDUP`
- Produced **140 independent signals** across 689 days (**0.203 signals/day**).
- While per-direction dedup doubled the independent signal count compared to baseline (140 vs 64), it falls short of the 2.0 signals/day requirement by **10-fold**.
- Mean R was positive (+0.1697R), but 61.4% of total R came from a single month (2024-10: +14.6R / +23.8R), failing the monthly stability criterion.

### Candidate 2: `C2_TIMEFRAME_15M_PRIMARY`
- Produced **89 independent signals** across 689 days (**0.129 signals/day**).
- Evaluating 15m as a primary timeframe yielded more signals, but **severely degraded trade expectancy**: Mean R dropped to **+0.0840R** with a win rate of only **38.2%**.
- Spread friction ($0.40 round-trip) relative to tighter 15m stops caused substantial slippage decay. 17 of 27 months were negative.

### Candidate 3: `C3_KILLZONE_SESSION_FILTER`
- Produced **125 independent signals** (**0.181 signals/day**).
- Eliminating off-session Asian trades preserved trade quality (+0.1392R), but further compressed frequency, falling far short of the $\ge 2.0$ daily signal requirement.

### Candidate 4: `C4_LIMIT_ORDER_FVG_ENTRY`
- Produced **94 independent signals** (**0.136 signals/day**).
- Requiring limit order retracements caused a 78% order expiration rate (only 22% filled), decimating frequency to ~1 trade every 14 trading days.

### Candidate 5: `C5_COMPOSITE_15M_KILLZONE_LIMIT`
- Produced **403 independent signals** (**0.585 signals/day**).
- Combining 15m structure with killzone filters and limit entries suffered from the compound effect of low fill rates and high intraday spread drag, yielding **-0.0557R** expectancy.

---

## 5. Step 6 Verdict

> **FINAL STEP 6 VERDICT**: **NONE OF THE 5 PRE-REGISTERED CANDIDATES QUALIFIED**.
> 
> Every candidate strictly failed the pre-registered Step 5 acceptance criterion:
> - $C1, C3, C4, C5$ failed the frequency requirement ($\text{signals/day} < 2.0$).
> - $C2$ achieved higher raw frequency but produced negative expectancy ($-0.0712\text{R}$) and negative control percentile rank.
> - In accordance with Non-Negotiable Rule 1 and Step 7 protocol, **no candidate qualifies to advance to Validation or Test**.
