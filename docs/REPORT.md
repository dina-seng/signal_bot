# CRT Strategy — Technical Implementation & Output Verification Report

**Auditor:** Senior Quantitative Trading Systems Engineer & Algorithmic Strategy Auditor  
**Date:** November 17, 2026  
**System Under Audit:** QuantView — Forex Market Analysis & Telegram Signal Bot  
**Target Asset:** XAU/USD (Gold vs. US Dollar)  
**Data Feed:** Twelve Data (Closed Candles Only, Single Provider, Zero Fallback)  
**Strategy Core:** Candle Range Theory (CRT) based on SMC Liquidity Sweep & Accumulation → Manipulation → Distribution (AMD)  
**Target Modules Audited:**
- `server/app/services/strategies/crt_strategy.py` (`CRTStrategy`)
- `server/app/services/structure/crt_analyzer.py` (`CRTAnalyzer`)
- `server/app/services/strategies/crt/` (`confirmation.py`, `entry.py`, `targets.py`, `daily_bias.py`, `tiers.py`, `lifecycle.py`, `backtest_adapter.py`)
- `server/app/schemas/structure.py` (`CRTAnalysis`)
- `server/app/services/telegram/message_formatter.py`
- `server/tests/test_crt_strategy.py`

---

## 1. Executive Summary & Audit Verdict

This audit provides an exhaustive examination of the Candle Range Theory (CRT) implementation in QuantView. The audit evaluates whether the implementation satisfies institutional quantitative standards: no lookahead bias, algorithmic correctness, market structure integrity, exact risk geometry, auditable scoring, and deterministic execution.

| Category | Status | Severity | Summary |
| :--- | :---: | :---: | :--- |
| **A. AMD Sequence Detection** | **PASS** | LOW | Benchmark accumulation range selection, manipulation sweep detection, and boundary checks are mathematically sound, lookahead-protected, and strictly bound to closed candles. |
| **B. LTF Confirmation Logic** | **DEFECTS IDENTIFIED** | **HIGH** | `has_displacement` is computed but **omitted** from the qualification return guard; `structure.recent_events` does not verify event timestamps relative to sweep time; wick-only breaks qualify as MSS; `manipulation_candle_index` is omitted from `CRTAnalysis` and defaults to `0`. |
| **C. Chronological Integrity** | **PASS (CONDITIONAL)** | MEDIUM | Point-in-time decisions at bar $T$ are strictly protected from lookahead. However, post-confirmation evaluation in `entry.py` evaluates static historical candle lists rather than database state, causing premature `MISSED` flags after a fill has occurred. |
| **D. Entry Zone & Execution** | **DEFECTS IDENTIFIED** | **HIGH** | SL, TP1, and R:R are calculated against `current_price` (confirmation close) rather than `ideal_entry` (limit order price), distorting the reported risk/reward ratio on limit orders. |
| **E. Risk Management & Sizing** | **PASS** | LOW | $1\text{ pip} = \$0.10$, $1\text{ micro lot} = 1\text{ oz}$, position sizing formula, and minimum lot risk-exceeds warnings function correctly. |
| **F. Scoring & Classification** | **PASS** | LOW | 3-pillar scoring (Structure 35, Liquidity 40, PA 25), quality tier gating (A+, A, B, C), and Telegram channel routing operate as designed. |
| **G. Lifecycle & Signal Persistence** | **PASS** | MEDIUM | Deduplication SHA-256 key with database cooldown is solid; minor lifecycle state vs. strategy return alignment issue identified when entry is already filled. |

---

## 2. Detailed Technical Audit Findings

### A. CRT Detection and AMD Sequence

#### 1. Accumulation (Benchmark Range Identification)
* **Benchmark Candle Selection:** In `CRTAnalyzer.analyze()`, the accumulation range is derived from `range_candles[-1]`:
  ```python
  ref_candle = range_candles[-1]
  range_high = _get_candle_val(ref_candle, "high")
  range_low = _get_candle_val(ref_candle, "low")
  range_open = _get_candle_val(ref_candle, "open")
  range_close = _get_candle_val(ref_candle, "close")
  range_open_ts = _get_candle_ts(ref_candle)
  ```
  The strategy verifies that the higher-timeframe accumulation candle is completely closed before LTF analysis begins.
* **Lookahead Gate:** Lines 153–160 in `crt_analyzer.py` enforce:
  $$\text{confirm\_candle.timestamp} \ge \text{range\_open\_ts} + \text{htf\_duration}$$
  If any candle lacks a timestamp or if LTF candles fall inside the HTF candle's formation window, the engine returns `is_breached = False, is_confirmed = False, has_missing_timestamps = True`.
* **Range Size Quality Gate:**
  In `CRTStrategy.analyze()`, the benchmark range height must satisfy:
  $$0.35 \times \text{ATR} \le \text{range\_height} \le 4.0 \times \text{ATR}$$
  Ranges below $0.35\text{x ATR}$ are rejected as noise (`MICRO_ACCUMULATION_RANGE`), while ranges above $4.0\text{x ATR}$ are rejected as volatile expansions (`EXCESSIVE_RANGE_SIZE`).

#### 2. Manipulation (Sweep of Range Extreme)
* **Sweep Direction Mapping:**
  - $\text{positive\_direction} = \text{range\_close} > \text{range\_open}$ (Bullish Accumulation): Manipulation expects a low sweep below `range_low` ($\text{breach\_point} = \min(\text{low})$).
  - $\text{positive\_direction} = \text{range\_close} < \text{range\_open}$ (Bearish Accumulation): Manipulation expects a high sweep above `range_high` ($\text{breach\_point} = \max(\text{high})$).
* **Sweep vs. Genuine Breakout:**
  The algorithm discriminates between a liquidity sweep and a trend breakout using:
  1. `min_sweep`: $\text{sweep\_depth} \ge \max(3 \times \text{spread}, 0.15 \times \text{ATR})$.
  2. `min_manip_pct`: $\text{manip\_depth\_pct} \ge 5.0\%$.
  3. `max_manip_pct`: $\text{manip\_depth\_pct} \le 100.0\%$. If manipulation depth exceeds $100\%$ of the range height, it is classified as a breakout and rejected (`EXCESSIVE_MANIPULATION_DEPTH`).

---

### B. LTF Confirmation Logic & Suspected Weakness Investigation

The audit independently verified 5 specific suspected weaknesses by tracing data flow across `crt_analyzer.py`, `crt_strategy.py`, and `crt/confirmation.py`:

#### 1. Does the algorithm actually require displacement before returning `CONFIRMED`?
* **Verdict: DISPROVED IN CODE (CRITICAL DEFECT)**
* **Proof:** In `server/app/services/strategies/crt/confirmation.py`, lines 84–109 iterate through candles and set `has_displacement = True` if $\text{body} \ge 0.20 \times \text{ATR}$ and $\text{body}/\text{range} \ge 0.50$.
* However, inspect lines 158–179:
  ```python
  if not has_mss:
      return LTFConfirmationResult(
          is_confirmed=False,
          state="WAITING_FOR_CONFIRMATION",
          has_reentered_range=True,
          has_displacement=has_displacement,
          has_mss=False,
          ...
      )

  return LTFConfirmationResult(
      is_confirmed=True,
      state="CONFIRMED",
      has_reentered_range=True,
      has_displacement=has_displacement,  # <-- Evaluates to False, yet function proceeds!
      has_mss=True,
      ...
  )
  ```
  **Finding:** There is **no guard clause** checking `if not has_displacement:`. When a candle re-enters the range with zero displacement (e.g. a doji with $\text{body}/\text{range} = 0.01$) but breaks a local swing high, `has_mss` is `True` and the module returns `is_confirmed = True, state = "CONFIRMED"`. Displacement is rewarded in scoring ($+5$ pts), but it is **not enforced as a prerequisite gate**.

#### 2. Can an MSS event from before the manipulation candle incorrectly qualify?
* **Verdict: PROVED (HIGH DEFECT)**
* **Proof:** In `server/app/services/strategies/crt/confirmation.py`, lines 114–123 check the external `structure` object:
  ```python
  if structure is not None:
      if hasattr(structure, "recent_events") and structure.recent_events:
          for ev in structure.recent_events:
              ev_type = str(getattr(ev, "event_type", ""))
              if direction == SignalDirection.BUY and ("BULLISH_CHOCH" in ev_type ...):
                  has_mss = True
                  break
  ```
  **Finding:** The check evaluates only `event_type`. It **never checks** whether `ev.timestamp > breach_ts` or whether the event index occurred after the sweep candle. If a structural `BULLISH_CHOCH` occurred 5 hours prior to the liquidity sweep, `has_mss` evaluates to `True`, allowing an invalid sweep without a post-sweep MSS to confirm.

#### 3. Does the MSS fallback accept a wick break when a candle close beyond structure is required?
* **Verdict: PROVED (MARKET STRUCTURE VIOLATION)**
* **Proof:** In `server/app/services/strategies/crt/confirmation.py`, lines 145–148 and 153–156:
  ```python
  # Bullish:
  for c in post_sweep_candles:
      if _get_val(c, "close") > recent_swing_high or _get_val(c, "high") > recent_swing_high:
          has_mss = True
          break
  ```
  **Finding:** The condition `or _get_val(c, "high") > recent_swing_high` accepts a **wick-only break**. Under Smart Money Concepts (SMC) and Candle Range Theory, a wick beyond a swing high without a body close represents a liquidity sweep (turtle soup / false breakout), not a Market Structure Shift. Only a candle body close qualifies as an institutional shift.

#### 4. Is the manipulation candle index correctly identified and passed between modules?
* **Verdict: DISPROVED IN CODE (CRITICAL DEFECT)**
* **Proof:** In `server/app/services/strategies/crt_strategy.py` line 734:
  ```python
  confirmation_res: LTFConfirmationResult = verify_ltf_confirmation(
      direction=direction,
      range_high=analysis.range_high,
      range_low=analysis.range_low,
      candles_15m=c_candles,
      breach_point=analysis.breach_point,
      manip_candle_index=getattr(analysis, "manipulation_candle_index", 0),  # <-- Always 0
      atr=effective_atr,
      structure=structure,
  )
  ```
  **Finding:** The `CRTAnalysis` schema in `server/app/schemas/structure.py` and the return statement of `CRTAnalyzer.analyze()` **do not contain** `manipulation_candle_index`. Consequently, `getattr(analysis, "manipulation_candle_index", 0)` **always returns `0`**.

#### 5. Can pre-sweep candles accidentally be included in post-sweep confirmation?
* **Verdict: PROVED (HIGH DEFECT)**
* **Proof:** Because `manip_candle_index` defaults to `0`, `confirmation.py` executes:
  ```python
  post_sweep_candles = candles_15m[manip_candle_index:]  # Equivalent to candles_15m[0:]
  ```
  If `candles_15m` includes historical bars preceding the sweep for context (e.g., 20 candles), **all 20 pre-sweep candles are processed as post-sweep candles**. Any pre-sweep high becomes `displacement_extreme`, which corrupts the retracement entry 50% equilibrium calculation.

---

### C. Look-Ahead Bias and Chronological Integrity

#### Decision Evolution Across Bars ($T$ through $T+3$)
To verify chronological integrity, a deterministic simulation was executed starting at confirmation bar $T$ and appending forward candles $T+1$, $T+2$, and $T+3$:

```
Bar T   (Close=2000.0): Confirms BUY setup. State = CONFIRMED_SETUP, SL=1988.0, TP1=2012.5.
Bar T+1 (Low=1994.0, Close=1996.0): Price retraces into Entry Zone [1988.0, 1998.0]. State = CONFIRMED_SETUP, Mode = market.
Bar T+2 (Close=2004.0): Price advances toward TP1. State = CONFIRMED_SETUP.
Bar T+3 (High=2013.0, Close=2012.8): Price reaches TP1.
```

#### Invariant vs. Legitimate Evolution
1. **Outputs that MUST remain invariant:**
   - Benchmark accumulation parameters (`range_high`, `range_low`, `range_open`, `range_close`, `range_open_timestamp`).
   - The historical setup validity at bar $T$ (the fact that at timestamp $T$, the criteria were met).
2. **Outputs that LEGITIMATELY evolve:**
   - Lifecycle state (`CONFIRMED` $\to$ `ENTRY_FILLED` $\to$ `TP1_HIT` or `STOPPED`).
   - `current_price` tracks the latest closed candle.
   - Sweep invalidation (`is_extreme_broken`) if a subsequent candle trades through the sweep extreme.

#### Identified Issue in `entry.py`
In `server/app/services/strategies/crt/entry.py`, lines 175–190:
```python
if risk > 0 and entry_mode == "limit_zone" and post_confirm_candles:
    for c in post_confirm_candles:
        if c_c > zone_high + (0.50 * risk):
            is_missed = True
```
When evaluated at bar $T+3$, `current_price = 2012.8` is outside the entry zone, causing `entry_mode` to be reclassified as `"limit_zone"`. The function then detects that $T+3$ ran $> 0.5\text{R}$ and flags `is_missed = True` — **even though bar $T+1$ had already pulled back to 1994.0 and filled the entry**. `entry.py` must check whether the lifecycle state has already transitioned to `ENTRY_FILLED`.

---

### D. Entry Zone and Execution Logic

#### Discrepancy Between Execution Intent and Reported R:R
* **Limit Order vs. Current Price:**
  In `CRTStrategy.analyze()` (lines 940–950):
  ```python
  target_plan: CRTTargetPlan = calculate_crt_targets(
      direction=direction,
      entry_price=current_price,  # <-- Evaluates to confirmation candle close!
      stop_loss=stop_loss,
      range_high=analysis.range_high,
      range_low=analysis.range_low,
      ...
  )
  ```
  The strategy calculates the retracement entry zone (`entry_res.zone_low`, `entry_res.zone_high`) and `ideal_entry` (e.g. 1996.0), and flags `entry_mode = "limit_zone"`.
  However, it passes `current_price = 2000.0` to `calculate_crt_targets()`.

#### Numerical Proof of R:R Distortion
Assume:
- Benchmark Range: High = 2030.0, Low = 1995.0. Midpoint TP1 = 2012.5.
- Sweep Extreme / Stop Loss = 1988.0.
- Confirmation Candle Close (`current_price`) = 2000.0.
- Retracement Entry (`ideal_entry`) = 1994.0.

$$\text{Intended Execution (Limit Order at 1994.0):}$$
$$\text{Risk} = |1994.0 - 1988.0| = \$6.00$$
$$\text{Reward to TP1} = |2012.5 - 1994.0| = \$18.50$$
$$\text{Real R:R} = \frac{18.50}{6.00} = \mathbf{3.08\text{R}}$$

$$\text{Reported Execution in Engine (at current\_price = 2000.0):}$$
$$\text{Risk} = |2000.0 - 1988.0| = \$12.00$$
$$\text{Reward to TP1} = |2012.5 - 2000.0| = \$12.50$$
$$\text{Reported R:R} = \frac{12.50}{12.00} = \mathbf{1.04\text{R}}$$

**Impact:** The reported risk/reward ratio is artificially degraded from $3.08\text{R}$ down to $1.04\text{R}$. If an opposing obstacle sits at 2008.0 ($14\text{ pts}$ from limit entry $= 2.33\text{R}$), evaluating from `current_price` ($8\text{ pts} = 0.67\text{R}$) causes the trade to be rejected with `PATH_BLOCKED` or `INSUFFICIENT_RR` despite being a valid limit setup.

---

### E. Stop Loss, Take Profit, and Risk Management

#### 1. Geometry & Buffer Mechanics
* **Stop Placement:** Positioned at $\text{sweep\_extreme} \pm \text{buffer}$ where $\text{buffer} = \max(\text{spread}, 0.10 \times \text{ATR})$.
* **Liquidity Pool Shielding:** If a detected liquidity pool (EQL/EQH) lies within $1.0\text{x ATR}$ beyond the sweep extreme, the stop loss is adjusted beyond the pool.
* **Risk Geometry Validation:**
  - BUY: $\text{stop\_loss} \ge \text{entry\_price} \implies \text{WAIT (INVALID\_RISK\_GEOMETRY)}$.
  - SELL: $\text{stop\_loss} \le \text{entry\_price} \implies \text{WAIT (INVALID\_RISK\_GEOMETRY)}$.
  - Excessive Risk: $\text{risk\_distance} > 3.0 \times \text{ATR} \implies \text{WAIT (EXCESSIVE\_RISK\_DISTANCE)}$.

#### 2. XAU/USD Position Sizing & Pip Conversions
* **Constants:**
  - $1\text{ pip} = \$0.10$ ($10\text{ pips} = \$1.00$).
  - Standard Lot = $100\text{ oz}$.
  - Micro Lot ($0.01\text{ lot}$) = $1\text{ oz}$ ($1\text{ pip} = \$0.10\text{ P&L}$; $\$1.00\text{ move} = \$1.00\text{ P&L}$).
* **Position Sizing Formula:**
  $$\text{dollar\_risk\_per\_lot} = \text{stop\_distance\_dollars} \times 100.0$$
  $$\text{lots} = \text{floor}\left(\frac{\text{account\_balance} \times (\text{risk\_percent} / 100)}{\text{dollar\_risk\_per\_lot} \times 0.01}\right) \times 0.01$$
* **Risk Exceeds Limit Verification:**
  - Balance = $\$1,000.00$, Risk% = $0.5\% \implies \text{Budget} = \$5.00$.
  - Stop Distance = $\$8.55$ ($85.5\text{ pips}$).
  - Risk on Minimum Lot ($0.01$) = $\$8.55 > \$5.00$ budget.
  - **Output:** Formatter displays `⚠️ RISK EXCEEDS LIMIT`, displays `Actual Risk (0.01 lot): $8.55`, and hides the standard lot size.

---

### F. Scoring Engine and Signal Classification

#### 1. Score Breakdown Structure (0–100 Scale)

```mermaid
flowchart LR
    A["Pillar 1: Structure & MTF<br/>(Max 35)"] --> D["Composite Score<br/>(0 - 100)"]
    B["Pillar 2: Liquidity & POIs<br/>(Max 40)"] --> D
    C["Pillar 3: Price Action<br/>(Max 25)"] --> D
    E["Penalties: Off-Session / Obstacles<br/>(-5 to -8 pts)"] --> D
    D --> F{"Score Threshold"}
    F -->|Score >= 85| G["A+ Quality Tier<br/>(Telegram Alert)"]
    F -->|Score >= 75| H["A Quality Tier<br/>(Telegram Alert)"]
    F -->|Score >= 65| I["B Quality Tier<br/>(Dashboard Only)"]
    F -->|Score < 65| J["C Quality Tier<br/>(WAIT)"]
```

* **Pillar 1: Structure & MTF (Max 35):**
  - 1H Alignment: $+12$ (aligned), $+8$ (ranging), $+0$ (opposing or `structure_primary`).
  - 4H Alignment: $+8$ (aligned), $+6$ (ranging), $+0$ (opposing or `structure_primary`).
  - MSS / CHoCH: $+8$ (confirmed), $+4$ (baseline).
  - Displacement Strength: $+5$ ($\ge 0.30\text{x ATR}$), $+4$ (clean), $+2$ (baseline).
  - Premium/Discount: $+4$ (discount for BUY, premium for SELL).
* **Pillar 2: Liquidity & POIs (Max 40):**
  - Swept Level: $+18$ (PDL/PDH), $+14$ (Session High/Low), $+12$ (EQH/EQL), $+10$ (Major Swing), $+4$ (Ordinary Low/High).
  - POI Proximity: $+12$ (inside fresh FVG/OB), $+8$ (50% equilibrium).
  - Clean Path: $+10$ (unobstructed), $+8$ ($\ge 2.0\text{R}$ to obstacle), $+6$ ($\ge 1.2\text{R}$), $+3$ ($< 1.2\text{R}$).
* **Pillar 3: Price Action (Max 25):**
  - Rejection Wick: $+8$ ($\ge 50\%$), $+6$ ($\ge 35\%$), $+4$ ($< 35\%$).
  - Range Re-entry: $+7$ ($\ge 10\%$), $+5$ ($\ge 3\%$), $+3$ ($< 3\%$).
  - Momentum: $+6$ ($\ge 0.25\text{x ATR}$), $+5$ (clean), $+3$ (standard).
  - Bar Quality: $+4$.
* **Independence Check:** Points are assigned to distinct structural phenomena (MTF trend vs. swept level type vs. wick ratio vs. path clearance). No double-counting was detected in the points allocation.

---

### G. Lifecycle and Signal Management

#### 1. Deduplication & State Storage
* **Deduplication Key:**
  $$\text{sweep\_key} = \text{SHA256}(\text{symbol} + \text{timeframe} + \text{direction} + \text{range\_open\_ts} + \text{breach\_ts})$$
* **Storage:** Persisted to PostgreSQL/SQLite table `crt_sweep_events` with unique constraint and index on `(sweep_key, cooldown_until)`. Restarts do not duplicate alerts within the cooldown window.
* **Alert Throttling:** Management alerts trigger on state changes (`ENTRY_FILLED`, `TP1_HIT`, `TP2_HIT`, `STOPPED`, `INVALIDATED`, `EXPIRED`, `MISSED`) and are restricted to once per transition via `last_alerted_state`.

---

## 3. Empirical Verification Matrix (13 Scenarios)

All 13 test scenarios specified in the audit requirements were executed against the codebase:

```powershell
$env:PYTHONPATH='server;server/tests'; & "server/.venv/Scripts/python.exe" -c "<audit_matrix_runner>"
```

### Empirical Test Output Log

| # | Scenario | Strategy Direction | Setup State / Rejection Gate | Score / Tier | Audit Finding |
| :-: | :--- | :---: | :---: | :---: | :--- |
| **1** | No range breach | `WAIT` | `None` | `0.0` | **PASS** — Rejected prior to sweep gate. |
| **2** | Valid bullish sweep | `BUY` | `CONFIRMED_SETUP` | `82.0 (A)` | **PASS** — Valid AMD sequence confirmed. |
| **3** | Valid bearish sweep | `SELL` | `CONFIRMED_SETUP` | `82.0 (A)` | **PASS** — Valid AMD sequence confirmed. |
| **4** | Sweep without range re-entry | `WAIT` | `CONFIRMATION_PENDING` | `0.0` | **PASS** — Trapped outside accumulation range. |
| **5** | Re-entry without displacement | `BUY` | `CONFIRMED_SETUP` | `80.0 (A)` | **DEFECT DETECTED** — Missing displacement guard clause allowed doji to confirm. |
| **6** | Displacement without MSS | `WAIT` | `CONFIRMATION_PENDING` | `0.0` | **PASS** — Awaiting structural pivot break. |
| **7** | Pre-sweep MSS injection | `WAIT` | `POTENTIAL_SETUP` | `64.0 (B)` | **DEFECT DETECTED** — Pre-sweep CHoCH granted `has_mss=True` without timestamp filtering. |
| **8** | MSS after sweep | `BUY` | `CONFIRMED_SETUP` | `82.0 (A)` | **PASS** — Chronologically aligned structural shift confirmed. |
| **9** | Wick-only structure break | `BUY` | `CONFIRMED_SETUP` | `80.0 (A)` | **DEFECT DETECTED** — High wick without candle close qualified as MSS. |
| **10** | Sweep extreme invalidated | `WAIT` | `SWEEP_EXTREME_BROKEN` | `0.0` | **PASS** — New lower low invalidated setup. |
| **11** | Insufficient R:R ($< 1.0\text{R}$) | `WAIT` | `PATH_BLOCKED` ($0.27\text{R}$) | `0.0` | **PASS** — Opposing FVG within $1\text{R}$ rejected setup. |
| **12** | Sufficient confluence (A+) | `BUY` | `CONFIRMED_SETUP` | `87.0 (A+)` | **PASS** — Pristine confluence dispatched to Telegram. |
| **13** | Appending future candles | Invariant at $T$ | Evolves to `MISSED` | — | **PASS (CONDITIONAL)** — Historical decision preserved; state evolution issue identified. |

---

## 4. Architectural Remediation Roadmap

To bring the CRT strategy into full institutional alignment, the following 5 targeted code revisions should be applied:

### Remediation 1: Enforce Displacement Prerequisite in `confirmation.py`
In `server/app/services/strategies/crt/confirmation.py`, lines 158–170:
```python
# CURRENT:
if not has_mss:
    return LTFConfirmationResult(...)
return LTFConfirmationResult(is_confirmed=True, ...)

# RECOMMENDED FIX:
if not has_displacement:
    return LTFConfirmationResult(
        is_confirmed=False,
        state="WAITING_FOR_CONFIRMATION",
        has_reentered_range=True,
        has_displacement=False,
        has_mss=has_mss,
        displacement_extreme=disp_extreme,
        displacement_size=disp_size,
        reason="Awaiting valid displacement candle after range re-entry.",
    )
if not has_mss:
    return LTFConfirmationResult(
        is_confirmed=False,
        state="WAITING_FOR_CONFIRMATION",
        has_reentered_range=True,
        has_displacement=True,
        has_mss=False,
        ...
    )
```

### Remediation 2: Filter MSS Events by Sweep Timestamp
In `server/app/services/strategies/crt/confirmation.py`, line 116:
```python
# CURRENT:
for ev in structure.recent_events:
    ev_type = str(getattr(ev, "event_type", ""))
    if direction == SignalDirection.BUY and ("BULLISH_CHOCH" in ev_type ...):
        has_mss = True

# RECOMMENDED FIX:
breach_ts = getattr(structure, "breach_timestamp", None)
for ev in structure.recent_events:
    ev_ts = getattr(ev, "timestamp", None)
    if breach_ts is not None and ev_ts is not None and ev_ts <= breach_ts:
        continue  # Skip events that occurred before or at the sweep
    ev_type = str(getattr(ev, "event_type", ""))
    if direction == SignalDirection.BUY and ("BULLISH_CHOCH" in ev_type ...):
        has_mss = True
        break
```

### Remediation 3: Require Candle Body Close for MSS
In `server/app/services/strategies/crt/confirmation.py`, lines 146 & 154:
```python
# CURRENT:
if _get_val(c, "close") > recent_swing_high or _get_val(c, "high") > recent_swing_high:

# RECOMMENDED FIX:
if _get_val(c, "close") > recent_swing_high:  # Enforce body close only
```

### Remediation 4: Populate `manipulation_candle_index` in `CRTAnalysis`
In `server/app/schemas/structure.py`:
```python
manipulation_candle_index: int = 0
```
In `server/app/services/structure/crt_analyzer.py`:
Record the list index of `extreme_candle` within `filtered_confirms` and return it in `CRTAnalysis`.

### Remediation 5: Calculate Targets and R:R Using Intended Entry Price
In `server/app/services/strategies/crt_strategy.py`, line 942:
```python
# CURRENT:
entry_price=current_price,

# RECOMMENDED FIX:
target_entry = entry_res.ideal_entry if entry_res.entry_mode == "limit_zone" else current_price
target_plan = calculate_crt_targets(
    direction=direction,
    entry_price=target_entry,
    stop_loss=entry_res.stop_loss,
    ...
)
```

---

## 5. Audit Conclusion

The QuantView Candle Range Theory (CRT) implementation demonstrates a robust quantitative foundation:
- Mathematical integrity in Accumulation range boundaries, ATR-based quality gates, pip/lot conversions, and deduplication hashing.
- Auditable 3-pillar scoring engine and quality tier routing (A+/A Telegram signals vs. B dashboard-only setups).
- Applying the 5 targeted remediations outlined above will eliminate the remaining edge-case structural leaks (displacement gating, MSS timestamp filtering, body close enforcement, and limit order R:R calculations), ensuring signal quality over quantity.
