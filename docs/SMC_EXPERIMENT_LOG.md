# SMC Strategy Experiment Log & Pre-Registered Hypotheses

## 1. Governance & Protocol

- **Protocol Rule**: Strict pre-registration before running experiments. No candidate may be added after observing results.
- **Multiple-Testing Budget**: Exactly **5 candidates total** ($C1$ through $C5$).
- **Calibration Split Only**: Candidates are evaluated strictly on the **Calibration split** (2023-03-01 00:00 UTC to 2025-05-21 08:15 UTC, 689 trading days across 27 months).
- **Fixed Qualification Criteria**:
  A candidate qualifies for one-shot validation **ONLY IF**, on **CALIBRATION**:
  1. **Frequency**: Independent signals per trading day $\ge \mathbf{2.0}$.
  2. **Expectancy / Edge**: Mean $R$ per independent signal is strictly above the **99th percentile** of the random-direction control (Bonferroni-style family-wise error control for 5 hypothesis tests).
  3. **Stability**: No single calendar month contributes more than **25.0%** of total $R$.
- **Forbidden Actions**:
  - Re-tuning score weights or minimum score floor based on observed test/validation results.
  - Removing risk management or path-validation safety gates.
  - Using validation or test results to select candidates.
  - Adding candidates post-hoc.

---

## 2. Pre-Registered Candidate Configurations

### Candidate 1: `C1_PER_DIRECTION_SWEEP_DEDUP`
- **ID**: `C1_PER_DIRECTION_SWEEP_DEDUP`
- **Allowed Lever**: Per-direction and per-sweep deduplication rules.
- **Hypothesis**: The baseline clustering algorithm enforces a global single-position block (`max(exit_time)`), silencing all subsequent signals even if they are in the opposite direction or tied to newly formed liquidity sweeps at distinct price levels. By decoupling BUY and SELL into separate tracks and allowing distinct structural levels ($\ge 1.0 \times \text{ATR}$ separation), the strategy can emit independent setups without artificial lockouts.
- **Exact Parameter Changes**:
  - Separate active position tracking for `BUY` and `SELL` directions.
  - Cluster key: `(direction, sweep_id)`.
  - Level separation: A new trade is independent if no open position exists in that direction with an entry price within $1.0 \times \text{ATR}$ of the new signal.
- **Expected Effect on Independent Signals/Day**:
  - Increases independent signals from **0.093 / day** to **~0.35 – 0.50 / day** on calibration.
- **Why It Adds Real Information**:
  - BUY and SELL setups trade distinct liquidity pools and structural order flows. A long swing position should not suppress an independent short reversal or liquidity sweep occurring at higher resistance.

---

### Candidate 2: `C2_TIMEFRAME_15M_PRIMARY`
- **ID**: `C2_TIMEFRAME_15M_PRIMARY`
- **Allowed Lever**: Evaluating SMC on additional primary timeframe (15m in addition to 1h) with per-timeframe independence.
- **Hypothesis**: The 1h primary timeframe produces candles only once per hour, resulting in long trade holding durations (15–30 hours) and severe signal scarcity. Evaluating SMC on the 15m primary timeframe (using 1h for HTF trend alignment and 4h for macro structure) captures faster intraday liquidity sweeps with tighter stop distances, resolving trades faster and dramatically multiplying signal capacity.
- **Exact Parameter Changes**:
  - Primary timeframe: `15m` (lookback: 200 bars).
  - HTF structure timeframe: `1h` (lookback: 200 bars).
  - Macro trend timeframe: `4h` (lookback: 100 bars).
  - Minimum score threshold: retained at `60.0`.
  - Dedup: Independent trade tracking per primary timeframe.
- **Expected Effect on Independent Signals/Day**:
  - Increases independent signals to **~1.8 – 2.5 / day** on calibration.
- **Why It Adds Real Information**:
  - SMC market structure is fractal. 15m liquidity sweeps, fair value gaps, and order blocks represent genuine intraday institutional order flow that is averaged out on 1h candles, providing distinct structural opportunities.

---

### Candidate 3: `C3_KILLZONE_SESSION_FILTER`
- **ID**: `C3_KILLZONE_SESSION_FILTER`
- **Allowed Lever**: Session / killzone context filter (London & NY killzones, America/New_York DST-aware).
- **Hypothesis**: Off-hours and Asian session trading on Gold (XAU/USD) is characterized by low volume, wider relative spreads, and frequent false breakout sweeps that revert without follow-through. Filtering signals to London (08:00–16:00 UTC) and New York (13:00–21:00 UTC) sessions will eliminate negative-drift chop and concentrate trade setups during high-momentum institutional liquidity injections.
- **Exact Parameter Changes**:
  - Session filter: Active between 08:00 and 21:00 UTC (America/New_York 03:00–16:00, DST-aware).
  - Outside this window, setups are classified as `OUT_OF_SESSION` and suppressed.
  - Evaluated with per-direction dedup.
- **Expected Effect on Independent Signals/Day**:
  - Yields **~0.20 – 0.35 / day** by eliminating ~40% of overnight noise while improving trade quality.
- **Why It Adds Real Information**:
  - Institutional market participants execute bulk order flow during London and New York overlaps. Off-session price movement lacks structural sponsorship and introduces noise that degrades expectancy.

---

### Candidate 4: `C4_LIMIT_ORDER_FVG_ENTRY`
- **ID**: `C4_LIMIT_ORDER_FVG_ENTRY`
- **Allowed Lever**: Entry model (limit order at FVG / OB boundary instead of market entry at candle close), SL/TP geometry within RiskManager.
- **Hypothesis**: Market orders at candle close chase impulsive moves after momentum has already expanded, resulting in wide stop losses and unfavorable risk-to-reward ratios. Placing a limit order at the nearest Fair Value Gap (FVG) boundary or 50% consequent encroachment allows execution at a structural discount with tighter risk geometry.
- **Exact Parameter Changes**:
  - Entry mode: `limit` order placed at `active_fvg.mitigation_price` (nearest boundary of active FVG in the direction of the setup).
  - Order cancellation / expiry: 4 bars (1 hour on 15m).
  - Stop loss: Structural swing low (BUY) / swing high (SELL) calculated by `RiskManager`.
  - Target geometry: TP1 at 2.0R, TP2 at 3.0R.
- **Expected Effect on Independent Signals/Day**:
  - Modulated by pending order fill rate (~50–65%), producing **~0.10 – 0.20 / day** on 1h.
- **Why It Adds Real Information**:
  - Institutional SMC methodology relies on entering at discount/premium imbalances rather than buying at market highs or selling at market lows. It drastically improves entry precision and realized R-multiples.

---

### Candidate 5: `C5_COMPOSITE_15M_KILLZONE_LIMIT`
- **ID**: `C5_COMPOSITE_15M_KILLZONE_LIMIT`
- **Allowed Lever**: Composite integration of 15m primary timeframe + London/NY killzone filter + limit/discounted entry + per-direction dedup.
- **Hypothesis**: Combining high-frequency 15m fractal structure with institutional killzone timing and limit-order entry optimization simultaneously addresses the frequency requirement ($\ge 2.0$ signals/day) while protecting against off-session chop and poor execution geometry.
- **Exact Parameter Changes**:
  - Primary timeframe: `15m` (with 1h HTF structure).
  - Session filter: London & NY killzones (08:00–21:00 UTC, America/New_York DST-aware).
  - Entry model: Limit order at active FVG boundary with 4-bar expiry.
  - Dedup: Per-direction independent trade tracking.
- **Expected Effect on Independent Signals/Day**:
  - Directly targets the $\ge 2.0$ independent signals/day requirement (expected **2.0 – 2.8 / day** on calibration).
- **Why It Adds Real Information**:
  - Operates at the intersection of institutional liquidity: fractal 15m structure during peak volume hours with discounted limit execution.

---

## 3. Fixed Acceptance Criterion

| Metric | Required Threshold on CALIBRATION | Rationale |
| :--- | :---: | :--- |
| **Independent Signals / Day** | $\ge \mathbf{2.0}$ | Hard project requirement (at least 2 distinct trades/day). |
| **Mean R per Independent Signal** | $> \mathbf{99\text{th percentile}}$ of Random Direction | Bonferroni-corrected significance across 5 candidate tests ($\alpha = 0.05 / 5 = 0.01$). |
| **Monthly Stability** | $\le \mathbf{25.0\%}$ of total R from any single month | Prevents flukes / outlier-month overfitting. |

No candidate will proceed to Validation or Test unless ALL THREE criteria are strictly satisfied on Calibration.
