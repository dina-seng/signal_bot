# SMC Experiment Log v2 — Pre-Registration

**Date**: 2026-11-17  
**Commit Status**: Pre-registered BEFORE any candidate replay or evaluation run.  
**Scope**: CALIBRATION split only (2023-03-01 to 2025-05-21 08:15 UTC; $n = 689$ calendar trading days).  
**Contamination Disclaimer**: Validation and test splits were exposed in earlier research rounds and are strictly disqualified from candidate selection. Forward clean holdout begins strictly after 2026-11-15 15:00 UTC.

---

## 1. Fixed Qualification Criteria (Calibration Only)

To qualify for consideration in Step C7, a candidate MUST pass **ALL FOUR** of the following quantitative criteria on the Calibration split:

1. **Frequency**: Realized entries per day $\ge 2.000$ under the portfolio rules.
2. **Expectancy vs Control**: Mean $R$ net of friction ($0.40 round-trip) above the 99th percentile ($p_{99}$) of the 1,000-seed ratio-preserving direction shuffle control (Step C2).
3. **Direction-Neutral Alpha**: Direction-neutral alpha $\bar{\alpha} = R_i - 0.5(R_{\text{BUY}} + R_{\text{SELL}}) > 0$ for **BOTH** BUY and SELL directions, OR the weaker direction disabled and entries/day $\ge 2.000$ still holds with the remaining direction(s).
4. **Risk & Monthly Stability**:
   - No single calendar month contributes $> 25.0\%$ of total realized $R$.
   - Worst single trading day realized $R \ge -4.00R$.
   - Maximum portfolio drawdown reported.

---

## 2. Pre-Registered Candidate Specifications (Max 4 Candidates)

### Candidate V2-C1: Concurrency Expansion + Fast Exit Geometry

- **ID**: `V2-C1`
- **Hypothesis**: Step C1 and C4 proved that the primary throughput choke is trade duration (mean 103.4h, median 95.8h; 34.2% timeout after 500 bars), which blocks 928 out of 1,491 setups (62.2%) under `MAX_CONCURRENT = 3`. An active 24-hour time stop (`max_hold_bars = 96` bars of 15m) combined with expanding concurrency to `MAX_CONCURRENT = 5` unchokes slot availability without modifying entry scoring or risk floors.
- **Allowed Levers**:
  - Exit geometry: 24-hour active time stop (`max_hold_bars = 96`).
  - Portfolio rules: `MAX_CONCURRENT = 5`.
- **Implementation (Default-OFF)**:
  - Config flag: `PORTFOLIO_V2_FAST_EXIT = True` (default `False`), `PORTFOLIO_MAX_CONCURRENT = 5` (default `3`).
  - No changes to `smc_strategy.py` scoring weights, floors, or `DEFAULT_MIN_SCORE`.
- **Why It Adds Information**: It directly eliminates stagnant capital lockup in trades that drift without momentum, replacing dead holding time with opportunity turnover.
- **Predicted Entries/Day Derivation**:
  - Baseline distinct accepted setups on calibration = 932 ($1.353\text{ setups/day}$).
  - Mean holding time drops from $103.4\text{h}$ to $\approx 20.0\text{h}$.
  - Under Little's Law / Capacity Theorem, slot capacity expands to $\frac{5 \times 24}{20.0} = 6.00\text{ entries/day}$.
  - However, total input opportunity pool is bounded at 1.353 setups/day. With $\approx 75\text{--}80\%$ cluster capture efficiency under $C=5$, predicted entries/day = $1.353 \times 0.77 \approx \mathbf{1.04\text{ entries/day}}$ (predicted to fall short of the 2.0/day requirement due to raw signal deficit).

---

### Candidate V2-C2: Near-Miss Ingestion (`LTF_PENALTY` Recovery) + Fast Exit Geometry

- **ID**: `V2-C2`
- **Hypothesis**: Step C4 revealed that `CONFIRMED_SETUP` only produces 1.295 raw setups/day, creating an insurmountable 35% deficit to the 2.0/day goal. The 755 distinct `LTF_PENALTY` setups (490 on calibration) represent high-conviction 1h setups that passed structure, liquidity, and price action floors ($\text{score} \ge 60.0$) but missed an immediate 15m lower-timeframe trigger. Ingesting this cohort expands the raw pool to 1,384 distinct calibration setups (2.009/day). Pairing this with a 24-hour time stop (`max_hold_bars = 96`) and `MAX_CONCURRENT = 5` maximizes throughput toward 2.0/day.
- **Allowed Levers**:
  - Evaluator/gate ingestion: Accept `LTF_PENALTY` cohort (`is_qualified_pre_ltf = True`).
  - Exit geometry: 24-hour active time stop (`max_hold_bars = 96`).
  - Portfolio rules: `MAX_CONCURRENT = 5`.
- **Implementation (Default-OFF)**:
  - Config flag: `SMC_ACCEPT_LTF_PENALTY = True` (default `False`), `PORTFOLIO_V2_FAST_EXIT = True`, `PORTFOLIO_MAX_CONCURRENT = 5`.
  - In `smc_strategy.py:181`, evaluate qualification on `pre_ltf_score >= 60.0` when flag is enabled.
- **Why It Adds Information**: Recovers high-scoring institutional setups that failed only a rigid 5-bar LTF lookback window, testing whether HTF confluence alone provides edge.
- **Predicted Entries/Day Derivation**:
  - Raw distinct opportunities on calibration = 932 (`CONFIRMED_SETUP`) + 452 (`LTF_PENALTY`) = 1,384 setups across 689 days = **2.009 raw setups/day**.
  - With 20.0h mean hold and $C=5$, slot capacity is $6.00\text{/day}$.
  - Accounting for same-bar and intra-hour clustering (separation rule and daily stop), capture rate is $\approx 68\%$. Predicted entries/day = $2.009 \times 0.68 \approx \mathbf{1.37\text{ entries/day}}$.

---

### Candidate V2-C3: Friction-Geometry & Volatility Filter (Surviving C3 Features)

- **ID**: `V2-C3`
- **Hypothesis**: Step C3 proved that internal strategy scores have zero ranking power, whereas friction geometry (`stop_distance` and `spread_to_stop_ratio`) dominates realized outcome ($p_{\text{adj}} < 10^{-4}$). Setups with stop distance $< \$20$ suffered negative expectancy ($T_1 = -0.3013R$ BUY, $-0.3812R$ SELL), while stops $\ge \$20$ achieved strong positive expectancy ($T_3 = +0.5120R$ BUY, $+0.1840R$ SELL). Filtering out setups where $\text{stop\_distance} < \$20.0$ and requiring above-median 15m ATR eliminates friction-vulnerable noise.
- **Allowed Levers**:
  - Features that survived Step C3: Minimum stop distance $\ge \$20.0$, High-ATR regime filter (`atr_regime = 1`).
  - Portfolio rules: Baseline `MAX_CONCURRENT = 3`.
- **Implementation (Default-OFF)**:
  - Config flag: `SMC_MIN_STOP_DISTANCE = 20.0` (default `0.0`), `SMC_FILTER_LOW_VOLATILITY = True` (default `False`).
- **Why It Adds Information**: Directly incorporates the only statistically significant empirical drivers from Step C3 to eliminate trades where fixed spread ($0.40) destroys edge.
- **Predicted Entries/Day Derivation**:
  - Filtering for stop $\ge \$20.0$ and above-median ATR retains $\approx 280$ distinct calibration setups (0.406 setups/day).
  - Through $C=3$ portfolio simulation, predicted entries = $\approx 160$ trades across 689 days = **0.232 entries/day**.
  - Expected to fail Criterion 1 ($\ge 2.0\text{/day}$), but tests maximum expectancy and alpha quality.

---

### Candidate V2-C4: Directional Asymmetry Handling (BUY-Only Focus + Volatility Filter + 36h Time Stop)

- **ID**: `V2-C4`
- **Hypothesis**: Step C2 demonstrated severe directional asymmetry: SELL trades suffered negative alpha across all splits ($\bar{\alpha} = -0.1435R$ calibration, $-0.4013R$ validation, $-0.1198R$ pooled). Step C5 explicitly permits disabling the weaker direction if justified by C2 results. Disabling SELL signals entirely and pairing BUY signals with a minimum stop distance filter ($\ge \$20.0$) and a 36-hour time stop (`max_hold_bars = 144`) tests whether a dedicated long-only institutional trend-follower can pass the ratio-preserving control and alpha criteria.
- **Allowed Levers**:
  - Per-direction handling: Disable SELL signals (`SignalDirection.SELL -> SignalDirection.WAIT`).
  - Features that survived C3: Minimum stop distance $\ge \$20.0$.
  - Exit geometry: 36-hour active time stop (`max_hold_bars = 144`).
- **Implementation (Default-OFF)**:
  - Config flag: `SMC_ENABLE_SELL = False` (default `True`), `SMC_MIN_STOP_DISTANCE = 20.0`, `PORTFOLIO_HOLD_HOURS = 36`.
- **Why It Adds Information**: Isolates the proven structural regime of XAU/USD (gold institutional accumulation), eliminating toxic short trades that fight higher-timeframe drift.
- **Predicted Entries/Day Derivation**:
  - Calibration BUY accepted setups = 630. With stop $\ge \$20.0$: 420 setups ($0.610\text{ setups/day}$).
  - Through $C=3$ with 36h hold, predicted entries = $\approx 228$ trades across 689 days = **0.331 entries/day**.
  - Expected to fail Criterion 1 ($\ge 2.0\text{/day}$), but pre-registered to evaluate whether Criterion 2 (p99 control) and Criterion 3 (BUY alpha) can be achieved.

---

## 3. Pre-Registration Commitment

- **No further candidates may be added** after this commit.
- **No qualification criteria may be relaxed or modified** after this commit.
- All 4 candidates will be evaluated strictly on the **CALIBRATION split** in Step C6.
