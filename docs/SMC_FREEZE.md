# SMC Strategy Freeze & Forward-Holdout Specification

## 1. Executive Freeze Summary & Non-Negotiable Rule

> **FREEZE MANDATE**: **NO PARAMETER CHANGES AFTER THIS COMMIT.**
>
> All strategy weights, qualification thresholds, deduplication rules, and evaluator floors are strictly frozen as of commit `73485d6` (and this freeze commit). No further optimization, parameter search, or threshold loosening is permitted on historical data.

---

## 2. Production Parameter Values (Live & Frozen)

| Parameter | Frozen Value | Production Code Citation | Description |
| :--- | :---: | :--- | :--- |
| `DEFAULT_MIN_SCORE` | **60.0** | `server/app/services/strategies/smc_strategy.py:30` | Minimum composite score required to emit an actionable setup. |
| `LTF_UNCONFIRMED_PENALTY` | **5.0** | `server/app/services/strategies/smc_strategy.py:34` | Flat point deduction when 15m LTF structure confirmation is missing. |
| `DIRECTIONAL_CONFLICT_PENALTY` | **15.0** | `server/app/services/signals/evaluators.py:53` | Flat point deduction when opposing directional indicators or candlestick patterns exist. |
| `PA_FLOOR` | **10.0** | `server/app/services/signals/evaluators.py:526` | Minimum price action pillar score (disqualifies setup if `< 10.0`). |
| `CONFLUENCE_FLOOR` | **20.0** | `server/app/services/signals/evaluators.py:544` | Minimum combined Structure + Liquidity score (disqualifies setup if `< 20.0`). |
| `SIGNAL_COOLDOWN_HOURS` | **2** | `server/app/core/config.py:129` | Directional broadcast cooldown window in hours. |
| `Friction Model` | **$0.40** | `server/scripts/crt_replay.py:simulate_outcome` | Round-trip spread and execution slippage deduction per trade. |

---

## 3. Fixed Walk-Forward Splits & Data Hygiene Notice

| Split | Start Timestamp (UTC) | End Timestamp (UTC) | Trading Days | Status / Cleanliness |
| :--- | :---: | :---: | ---: | :--- |
| **Calibration** | 2023-03-01 00:00 | 2025-05-21 08:15 | 689 | Used for baseline controls and candidate pre-registration. |
| **Validation** | 2025-05-21 08:15 | 2026-02-16 03:00 | 233 | **NOT CLEAN**: Inspected in earlier runs (`4424a64`, `5b88873`, `2db6eb1`). |
| **Test** | 2026-02-16 03:00 | 2026-11-15 15:00 | 231 | **NOT CLEAN**: Inspected in earlier runs (`4424a64`, `5b88873`, `2db6eb1`). |
| **Forward Holdout** | **After 2026-11-15 15:00** | *(Live forward collection)* | TBD | **Pristine Out-of-Sample**: Strictly quarantined until target sample size reached. |

---

## 4. Step 6 Candidate Outcomes & Freeze Rationale

In Step 5, five candidate hypotheses ($C1$ through $C5$) were pre-registered with a strict Bonferroni-corrected acceptance criterion. In Step 6, all 5 candidates were evaluated strictly on the Calibration split:
- **$C1$ (Per-direction sweep dedup)**: Generated 0.203 independent signals/day (failed $\ge 2.0$ target by 10-fold).
- **$C2$ (15m primary timeframe)**: Generated 0.129 independent signals/day, and control percentile was only 12.3% due to high spread drag.
- **$C3$ (Killzone session filter)**: Generated 0.181 independent signals/day (failed frequency target).
- **$C4$ (Limit order FVG entry)**: Generated 0.136 independent signals/day due to 78% order expiration rate (failed frequency target).
- **$C5$ (Composite 15m + Killzone + Limit)**: Generated 0.585 independent signals/day with negative mean R (-0.0557R) (failed both frequency and expectancy).

**Decision**: In strict adherence to Step 7(a), **no candidate qualified**. No candidate advanced to Validation or Test, and no experimental changes are wired into production. The production SMC implementation remains in its baseline state.

---

## 5. Forward-Holdout Evaluation Procedure

To evaluate the SMC strategy on genuine, uncompromised out-of-sample data, the following protocol must be executed:
1. **Quarantine Window**: Collect live market data strictly **after 2026-11-15 15:00 UTC**.
2. **Trigger Condition**: Execute the evaluation **ONLY ONCE** when $\ge \mathbf{150}$ new independent signals have been recorded under the frozen production path.
3. **Execution Rule**: Run `server/scripts/smc_replay.py` across the forward holdout window without modifying any parameters, scoring weights, or code.
4. **Pass / Fail Criterion**:
   - Independent signals per trading day $\ge 2.0$.
   - Realized Mean R $> 0$ with percentile rank $\ge 97.5\%$ against the 1,000-seed random-direction control.

---

## 6. Sample Size Required to Detect $+0.05R$ at 95% Confidence

To detect an incremental true edge of $\Delta = +0.05R$ at $95\%$ confidence, the required sample size $N$ is derived as follows:

### A. Mathematical Formulas

#### 1. Confidence Interval Precision Approach
To bound the $95\%$ confidence interval half-width to $E = \pm 0.05R$:
$$E = Z_{\alpha/2} \cdot \frac{\sigma}{\sqrt{N}} \le 0.05$$
Solving for $N$:
$$N \ge \left(\frac{Z_{\alpha/2} \cdot \sigma}{\Delta}\right)^2$$

#### 2. Hypothesis Testing Approach ($80\%$ Statistical Power)
To achieve $80\%$ statistical power ($\beta = 0.20$, $Z_\beta = 0.8416$) to reject $H_0: \mu \le 0$ at two-sided significance level $\alpha = 0.05$ ($Z_{\alpha/2} = 1.960$):
$$N = \frac{\left(Z_{\alpha/2} + Z_\beta\right)^2 \cdot \sigma^2}{\Delta^2}$$

---

### B. Empirical Inputs from Historical Replay

1. **Target Edge Size ($\Delta$)**: $+0.05R$
2. **Confidence Level**: $95\%$ ($\alpha = 0.05 \implies Z_{\alpha/2} = 1.960$)
3. **Statistical Power**: $80\%$ ($1 - \beta = 0.80 \implies Z_\beta = 0.8416$)
4. **Measured Per-Trade R Standard Deviation ($\sigma$)**:
   - **Independent Trades ($n = 108$)**: $\sigma_{\text{indep}} = \mathbf{1.2433}$
   - **Pooled Accepted Trades ($n = 5,790$)**: $\sigma_{\text{pooled}} = \mathbf{1.3046}$

---

### C. Sample Size Computations

#### Based on Independent Signals ($\sigma = 1.2433$):
1. **Confidence Interval Precision ($\pm 0.05R$ at $95\%$ Confidence)**:
   $$N = \left(\frac{1.960 \times 1.2433}{0.05}\right)^2 = \left(\frac{2.4369}{0.05}\right)^2 = 48.737^2 \approx \mathbf{2,375 \text{ trades}}$$

2. **Hypothesis Testing ($80\%$ Power at $\alpha = 0.05$, Two-Sided)**:
   $$N = \frac{(1.960 + 0.8416)^2 \times 1.2433^2}{0.05^2} = \frac{7.8490 \times 1.5458}{0.0025} \approx \mathbf{4,853 \text{ trades}}$$

3. **Hypothesis Testing ($80\%$ Power at $\alpha = 0.05$, One-Sided $Z_\alpha = 1.645$)**:
   $$N = \frac{(1.645 + 0.8416)^2 \times 1.2433^2}{0.05^2} = \frac{6.1832 \times 1.5458}{0.0025} \approx \mathbf{3,824 \text{ trades}}$$

#### Based on Pooled Accepted Trades ($\sigma = 1.3046$):
1. **Confidence Interval Precision**: $N \approx \mathbf{2,615 \text{ trades}}$
2. **Hypothesis Testing ($80\%$ Power, Two-Sided)**: $N \approx \mathbf{5,343 \text{ trades}}$

> **Implication for Forward Testing (OBSOLETE ESTIMATE)**:
> *(Note: The 98-year estimate below is OBSOLETE as of Phase C, because it was derived from the retired single-position connected cluster metric that measured holding time rather than setup entries. Under the Phase C portfolio framework with up to 3 concurrent positions targeting ~2 entries/day, collecting 150 forward entries requires approximately 75 trading days (~3.5 months). See Phase C plan.)*
> 
> *Historical Reference*: At the strategy's previous frequency of ~0.094 independent signals per day (~24 independent trades per year), gathering 2,375 serial non-overlapping trades would have required approximately 98 years of trading. Under the new Phase C portfolio rules, frequency is re-evaluated using entry capacity.
