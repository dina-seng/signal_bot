# Execution Contract Review & Stop-Loss Geometry Validation — Baseline v1

**Repository:** `D:\trade`  
**HEAD inspected:** `69e6992113a1c183f4bea836fd9c02be42069634`  
**Date:** 2026-11-22  
**Mode:** READ-ONLY investigation. No source, test, configuration, report, checkpoint, or database file was modified. This document and `execution_contract_proposal.md` are the only new files. The pre-existing uncommitted `package.json` change was left untouched. No backtest script or DB probe was run.

**Priorities:** accuracy → reliability → reproducibility. Not profitability.

---

## 0. Executive summary

1. **`$0.40` is confirmed to be execution cost only** — it never appears in SL geometry. A repo-wide search finds it exclusively in `spread=0.40` arguments, `SPREAD` constants, and friction documentation. SL distance is structural (swing-derived support/resistance ± ATR buffer), typically several dollars for XAU/USD.
2. **U-2 is resolved (recommendation): Option A — signal-price anchored geometry.** SL/TP levels are fixed at decision time from the structural reference price and never re-derived from the fill. This is the only option that preserves the frozen SMC strategy and avoids look-ahead/strategy drift.
3. **U-3 is resolved (recommendation): canonical R denominator = planned risk `|signal_price − structural SL|`**, fixed before the fill is known. Actual risk distance and monetary/price-unit P&L are recorded separately and never used to silently change R.
4. **A correction to the prior proposal is required:** its §5.4 "adverse SL gap" example conflated an *in-trade* stop gap with an *entry-candle* gap through SL. These are different events with different correct treatments (§2.4, §2.5).
5. **Cost model for v1:** preserve the flat `$0.40` round-trip exactly as implemented; do not convert it to an equity percentage; do not treat it as SL distance. Its implementation (one deduction in price units) is correct as written; the only issue is a documentation label (§5).

Nothing in this review changes strategy rules; all recommendations are proposals pending approval and implementation in the next milestone.

### Classification legend

| Tag | Meaning |
| :--- | :--- |
| **CD** | Confirmed defect |
| **EL** | Existing limitation (consistent but incomplete / mislabelled) |
| **PD** | Proposed design decision (recommendation, not implemented) |
| **UQ** | Unresolved question requiring human approval |

---

## 1. How SL is actually derived from market structure (task §1)

### 1.1 Verified derivation chain

```
smc_replay.replay_chunk :371-377
  └─ ConfluenceEngine._prepare_market_data :293-297
       └─ LiquidityService.analyze_liquidity_and_structure(c_prim = 1h candles)
            └─ StructureEngine.analyze_structure :200-278
                 ├─ SwingDetector.detect_swings :39-147  (N-bar fractal, right-confirmed)
                 ├─ classify_swings :35-106  (HH/HL/LH/LL/EH/EL, tol 0.05%)
                 ├─ determine_trend :108-198
                 └─ key_resistance = max(last ≤5 swing-high prices)   :250-252
                    key_support    = min(last ≤5 swing-low prices)    :254-256
  └─ smc_replay :445-450  structure.base_structure.key_support / key_resistance
  └─ build_market_trade :160-215
       └─ RiskManager.calculate_trade_risk :36-141
```

### 1.2 Structural inputs — precise rules (verified)

| Input | Rule | Source |
| :--- | :--- | :--- |
| Swing high at `i` | `High[i] >= High[i-k]` for `k=1..2` **and** `High[i] > High[i+k]` for `k=1..2` (default lookback 2 each side; right confirmation ⇒ no look-ahead) | `swing_detector.py:39-147` |
| Swing low at `i` | mirror with `Low` and inequalities `<=` / `<` | `swing_detector.py:119-143` |
| `key_support` | **Minimum of the last up-to-5 confirmed swing-low prices** on the 1h series | `structure_engine.py:250-252`, `:254-256` |
| `key_resistance` | **Maximum of the last up-to-5 confirmed swing-high prices** on the 1h series | `structure_engine.py:250-252` |
| ATR buffer | `atr_value = indicators.atr.atr_value` (Wilder ATR on 1h closes/highs/lows), used as `0.5×ATR` structural buffer or `1.5×ATR` fallback | `atr_calculator.py:18-38`; `risk_manager.py:55-57,81-108` |
| Direction | BUY uses `key_support_low`; SELL uses `key_resistance_high` | `risk_manager.py:74-112` |
| Max structural distance | XAU: `max_sl_pips=2500` × `pip_size=0.10` = **$250 price distance**; beyond this → SL falls back to `entry ± 1.5×ATR` | `risk_manager.py:65-72`; `symbols.py:31-40` |
| Pip/point convention | `RiskManager.get_pip_size("XAU/USD") = 0.10`; `point_value_per_lot = 10.0` (100 oz × $0.10); `ATRCalculator._get_pip_size` uses **0.01** for XAU — an existing unresolved inconsistency (**BT-010**, **EL**) | `symbols.py:31-40`; `atr_calculator.py:10-16` |
| TP geometry | `TP1 = entry ± 2 × risk_price`, `TP2 = entry ± 3 × risk_price` where `risk_price = |entry − SL|` | `risk_manager.py:90-92,110-112` |

### 1.3 RiskManager SL branches (verified — unchanged by this review)

**BUY** (`risk_manager.py:74-92`):
```
if key_support < entry and (entry − key_support) <= $250:   SL = key_support − 0.5×ATR
else:                                                        SL = entry − 1.5×ATR
if SL >= entry:                                              SL = entry − 1.5×ATR
risk = entry − SL;  TP1 = entry + 2×risk;  TP2 = entry + 3×risk
```
**SELL** (`:94-112`) is the exact mirror with `key_resistance`.

Critical observation: **the structural SL level `support − 0.5×ATR` is independent of entry price** whenever the $250 cap check does not flip. The entry price affects only `risk_price` and the derived TP levels — and it *can* flip the cap check, which then changes the SL level itself. This is the key reason re-anchoring geometry to the fill is unsafe (§3, Option B).

### 1.4 Order blocks / zones — where they do and do not appear

- `LiquidityService` computes `sr_zones` and `liquidity_pools` (`:136-141`) and stores them on `structure_analysis`.
- In the production path, `ConfluenceEngine._build_signal_response` uses them **only for informational "path validation" advisories** (`:420-474`); the code explicitly says "signal stays qualified" (`:460`) and never modifies `risk_params.stop_loss` or TPs.
- **The canonical replay never calls `_build_signal_response`** — it calls `RiskManager` directly (`smc_replay.py:480-491`). 
- `SMCStrategy` emits **no** `stop_loss`/`take_profit` metadata (grep: no matches), so the "custom SL" branch at `confluence_engine.py:346-392` is not taken. There is a scoring docstring mentioning "order block/SR zones" (`evaluators.py:182`) but no order-block SL placement.

**Finding (EL):** In the canonical path, **SL is determined solely by swing-derived key support/resistance ± ATR buffer and the $250 cap. SR zones, liquidity pools, FVGs, and order-block concepts do not set the SL.** This should be stated explicitly in reports so readers do not attribute structural meaning the engine does not implement.

### 1.5 `$0.40` is not SL distance (confirmed, CD if conflated)

Repo-wide search results (exhaustive):
- `smc_replay.py:822-826` — `--spread` CLI default, help text "Round-trip spread/slippage in USD"
- `smc_portfolio_2025.py:88` — `SPREAD = 0.40` (frozen execution constant), used at `:449-452`
- `run_step1/3/4/c2/c3/c6/6.py` — `spread=0.40` simulation arguments and friction reports
- `docs/SMC_FREEZE_V2.md:23` — `ROUND_TRIP_SPREAD | $0.40`
- `replay_harness.py:236-244` — the single deduction and `spread_paid` field

No occurrence in `risk_manager.py`, `structure_engine.py`, `swing_detector.py`, `symbols.py`, or any SL/TP calculation. **Keep execution cost and SL distance as separate concepts in all reports and manifests.**

---

## 2. Signal-to-entry transition and numerical examples (task §2)

### 2.1 Conventions used in the examples

- **Signal price `P_s`** = last closed **1h** close = **2000.00** (the existing engine's reference for geometry — see §3.2). The 15m decision closes at the same instant but is not the price anchor.
- **Planned entry/reference** = `P_s` (identical in the current engine).
- **Actual fill `F`** = next eligible 15m candle open.
- **Structural ATR** = 2.00 (1h); max structural distance $250 → structural branch always used below.
- **Cost** = 0.40 price units = **0.08R** in every entered example (0.40 / 5.00).
- **TP2 result** shows the 50% TP1 / 50% TP2 ladder; **SL result** shows the stop-out. R uses planned risk (§4).

Base geometry:
- **BUY:** key support 1996.00 → SL = 1996.00 − 0.5×2.00 = **1995.00**; planned risk = **5.00**; TP1 = **2010.00**, TP2 = **2015.00**.
- **SELL:** key resistance 2004.00 → SL = 2004.00 + 0.5×2.00 = **2005.00**; planned risk = **5.00**; TP1 = **1990.00**, TP2 = **1985.00**.

### 2.2 Results matrix (8 required distinctions × 6 scenarios)

| # | Distinction | BUY normal | SELL normal | BUY favourable entry gap | BUY adverse entry gap | BUY opens beyond SL | BUY opens beyond TP |
| :--: | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Signal price `P_s` | 2000.00 | 2000.00 | 2000.00 | 2000.00 | 2000.00 | 2000.00 |
| 2 | Planned entry / reference | 2000.00 | 2000.00 | 2000.00 | 2000.00 | 2000.00 | 2000.00 |
| 3 | Actual fill `F` | 2000.50 | 1999.50 | **1999.00** (better) | **2001.00** (worse) | **1994.00** | **2016.00** |
| 4 | Structural SL | 1995.00 | 2005.00 | 1995.00 | 1995.00 | 1995.00 | 1995.00 |
| 5 | Initial planned risk | 5.00 | 5.00 | 5.00 | 5.00 | 5.00 | 5.00 |
| 6 | Actual risk distance `|F−SL|` | 5.50 | 5.50 | 4.00 | 6.00 | −1.00 *(invalid)* | 21.00 *(invalid plan)* |
| 7 | TP1 / TP2 | 2010 / 2015 | 1990 / 1985 | 2010 / 2015 | 2010 / 2015 | 2010 / 2015 *(below/above invalid)* | 2010 / 2015 *(both below fill)* |
| 8 | R (TP2 / SL) | **+2.32 / −1.18** | **+2.32 / −1.18** | **+2.62 / −0.88** | **+2.22 / −1.28** | **n/a — void** | **n/a — void** |

Worked R arithmetic (denominator = planned risk 5.00; cost 0.40):
- BUY normal TP2: `0.5×(2010−2000.5) + 0.5×(2015−2000.5) = 12.00`; `12.00−0.40 = 11.60`; `11.60/5 = +2.32`. SL: `1995−2000.5 = −5.50`; `−5.90/5 = −1.18`.
- SELL normal TP2: `0.5×(1999.5−1990) + 0.5×(1999.5−1985) = 12.00`; `+2.32`. SL: `1999.5−2005 = −5.50`; `−1.18`.
- Favourable gap TP2: `0.5×11 + 0.5×16 = 13.50`; `13.10/5 = +2.62`. SL: `−4.40/5 = −0.88`.
- Adverse gap TP2: `0.5×9 + 0.5×14 = 11.50`; `11.10/5 = +2.22`. SL: `−6.40/5 = −1.28`.

**Interpretation (PD):** with levels fixed at decision time and R measured from the actual fill, a *favourable* entry gap (better fill) genuinely improves R and an *adverse* entry gap worsens it. The gap appears in the **numerator**, the denominator stays fixed. No outcome-dependent arithmetic.

### 2.3 Entry beyond SL / beyond TP — deterministic void (PD/UQ)

When `F` breaches the structural SL at entry (BUY `F <= 1995`), the structural invalidation level was crossed **before the trade existed**. Entering would leave SL above entry (invalid geometry) or manufacture a nonsense zero-P&L exit. Recommended rule:

- `VOID_ENTRY_BEYOND_SL` — no position, no R, no cost; record signal price, intended fill, SL, and reason.
- `VOID_ENTRY_BEYOND_TP` — if `F` has already crossed TP1 (BUY `F >= 2010`, including the 2012–2015 band and beyond), the planned ladder is no longer ahead of price; void rather than chase.
- General form: **enter only if `SL < F < TP1` (BUY) or `TP1 < F < SL` (SELL)**, strictly.

This is conservative, deterministic, and consistent with the existing limit-order convention (`NO_FILL_STOPPED_OUT`, `replay_harness.py:162-168`). It must be approved (U-9) and regression-tested.

### 2.4 Correction to prior proposal §5.4 (CD in the proposal, not in engine code)

The prior document's "Adverse SL gap" example used `fill_price = 100.00` and then a next-candle open of `95.00`, computing `R = −5.4`. That mixed two distinct events:

| Event | When | Correct treatment |
| :--- | :--- | :--- |
| **In-trade stop gap** | After entry, a managed bar opens beyond SL | Exit at the open (adverse), loss measured **from the actual fill**. Example: entered 2000.50, later bar opens 1994 vs SL 1995 → stop fill 1994, P&L `1994−2000.5 = −6.50`, net `−6.90`, R `−1.38`. |
| **Entry-candle gap through SL** | At the moment of entry | Void per §2.3 — no trade. |

Likewise an in-trade **favourable TP gap** (entered 2000.50, later bar opens 2012 through TP1): TP1 leg fills at 2012 (`max(open,tp1)`) = `0.5×11.50 = 5.75`; stop→BE; TP2 at 2015 = `0.5×14.50 = 7.25`; total 13.00; net 12.60; **R = +2.52** (vs +2.32 with exact-level fills). These values replace the earlier mixed examples.

---

## 3. Resolve U-2 — signal-price anchor for SL/TP geometry (task §3)

### 3.1 Option comparison

| Criterion | **A — Signal-price anchored** | **B — Actual-fill anchored** | **C — Hybrid structural** |
| :--- | :--- | :--- | :--- |
| Preserves original SMC strategy | **Yes.** Levels are exactly what the frozen `RiskManager` produces at decision time. | **No.** Re-running `RiskManager(F)` changes `risk_price`, hence TP1/TP2; can also flip the $250 cap and change the SL level itself. | Partially — SL preserved, but TP/R need a second convention. |
| Changes structural invalidation level | **No.** SL = support ± 0.5 ATR computed once. | **Yes, potentially.** Example: BUY fill 1994 < support 1996 → `key_support < entry` fails → SL falls back to `1994 − 1.5×2 = 1991`, not 1995. The structure-derived invalidation level silently moves. | No for SL; depends on the TP convention. |
| Gap effect on trade | Realised through P&L (numerator); entry beyond SL/TP → void. | Rewrites the plan after execution; gap effects partly or wholly absorbed into new TP distances and (if denominator re-anchored) hidden. | Depends on documented convention; must be specified. |
| Look-ahead bias | **None.** All levels derived from data closed at decision time; fill known at entry. | No strict future-data peek, but a **strategy/execution conflation**: strategy levels become a function of execution noise, which is not what was validated. Unsafe. | Depends. |
| R calculation | Denominator fixed at planned risk; gaps visible in R. Comparable across trades. | If denominator re-anchored to actual risk, R hides gap cost (a −6.00 loss becomes −1.0R). Misleading. | Must be fixed; see §4. |
| Regression tests needed | Fixed-level-across-gap fixtures; void rules; R numerics; cap-boundary unchanged; no post-outcome recompute. | Cap-flip test, TP-shift tests, denominator tests — a materially larger and strategy-changing test burden. | Same as A plus explicit TP/R convention tests. |

### 3.2 Recommendation (PD) — Option A, with an important clarification

**Adopt Option A.** SL and TP levels are computed once, at decision time, from the strategy's existing decision-time reference price and are never re-derived from the fill.

**Clarification that revises the prior proposal's U-2 sub-recommendation:** the "signal price" anchor must remain the **existing 1h-close reference** (`indicator_service.py:177-178`, passed at `smc_replay.py:447,484`), **not** the 15m decision-bar close. Reasons:

1. The 1h close is what the production strategy uses as its market-entry reference (`confluence_engine.py:336,401`); switching to a 15m close changes `risk_price`, TP1/TP2, and can flip the $250 structural cap check → **changes strategy behaviour**, which is forbidden.
2. The 15m decision timestamp and the 1h-close price anchor are different fields. Keeping them distinct and recording both is the truthful treatment of **N-01/N-19**: document the mixed as-of as a known limitation rather than silently "fixing" it by changing the strategy.

So the earlier recommendation "(a) use decision-bar 15m close" is **withdrawn** in favour of "keep the existing 1h-close reference; document the staleness". Entry timing (next 15m open) changes independently of the price anchor.

**Required tests for Option A:** (i) SL/TP identical for normal/favourable/adverse fill fixtures; (ii) void at entry beyond SL/TP; (iii) R numerics of §2.2; (iv) cap-boundary unchanged by fill; (v) proof that no field feeding R is written after outcome resolution.

---

## 4. Resolve U-3 — R denominator under gaps (task §4)

### 4.1 Three separate quantities (must be recorded independently)

| Quantity | Definition | Value in BUY adverse-gap example (`F=2001`, SL `1995`) |
| :--- | :--- | :--- |
| **Planned risk** | `|signal_price − structural SL|`, fixed at decision time | **5.00** |
| **Actual risk distance** | `|actual fill − structural SL|`, known at entry | **6.00** |
| **Monetary / price-unit realised loss** | `(exit_fill − F)` per unit × position notional; in the R engine only the price-unit figure exists | `1995 − 2001 = −6.00` price units per unit; monetary conversion requires notional (**not available — U-4/out of scope**) |

### 4.2 Recommendation (PD) — planned risk is the canonical R denominator

`R = (booked_price_pnl_from_actual_fills − execution_cost) / planned_risk`

Reasons:
1. **It is the strategy's own unit.** TP1=2R and TP2=3R are defined against planned risk; changing the denominator would silently redefine what "2R" means.
2. **It is fixed before the fill is known**, so the engine never changes R after seeing the outcome — exactly the requirement in task §4.
3. **Truth is preserved in the numerator.** With `F=2001`, a stop-out yields `−6.40/5 = −1.28R` — correctly reflecting the worse entry. Using actual risk would report `−1.0R` and **hide the gap cost**.
4. **Comparability.** Every trade is measured against its own pre-registered plan, independent of entry noise.

### 4.3 Material divergence handling (PD)

If `|actual risk − planned risk| / planned risk` is large (e.g. the §2.2 adverse-gap case is +20%), record both values and attach a descriptive flag such as `GAP_RISK_DIVERGENCE` to the trade and to report distributions. **Do not** re-scale R, drop the trade, or introduce a numeric threshold filter in v1 — that would be a new tunable parameter. If a threshold is later desired, it requires separate approval. The engine must expose the full distribution of planned-vs-actual risk so the reader can judge materiality.

---

## 5. Execution-cost model review (task §5)

1. **Preserve `$0.40` for v1 (PD).** Implementation at `replay_harness.py:236-238` is internally correct: one flat round-trip deduction in price units, applied once at R calculation; `spread_paid` recorded at `:244`; portfolio consumes the stored `r_multiple` (`smc_portfolio_2025.py:207`) and re-simulates controls with the same `SPREAD` (`:449-452`). **No double-count found.** No evidence of an implementation bug → no change.
2. **Not a stop distance (confirmed).** §1.5.
3. **No equity-percentage conversion (PD).** Do not implement `equity × pct`. The engine has no equity/lot accounting (`risk_manager.py:122-125` values are computed but ignored by replay). Any conversion would require invented assumptions.
4. **Documentation limitation (EL):** the deduction is in **price units per ounce**, while freeze/report text calls it "`$0.40` round-trip" in account-currency terms. For XAU (100 oz/lot) that is $40 per standard lot, not $0.40 of account equity. Keep the numeric assumption unchanged for v1 but label it precisely as "0.40 price units per unit of position (round trip)" in the manifest and reports. Flag as a disclosure item, not a bug fix.
5. **Report visibility (PD):** continue printing the cost assumption in reports (`smc_replay.py:714` already does: "Round-trip friction | $0.40 per completed trade").

---

## 6. Updated decision status

| ID | Status after this review | Next action |
| :--- | :--- | :--- |
| U-1 (Option B entry vs R2 cadence) | **Still UQ** | Human approval; Option B entry timing remains the proposal, with 1h-close price anchor (§3.2) — the two are now separated cleanly. |
| U-2 (geometry anchor) | **Resolved → Option A** (PD, awaits approval) | Implement fixed levels at decision time; never re-anchor to fill. |
| U-2b (which price is "signal price") | **Resolved → keep 1h close** (PD, revision of prior proposal) | Document N-01/N-19 as a limitation, not a fix. |
| U-3 (R denominator) | **Resolved → planned risk** (PD, awaits approval) | Add actual-risk + monetary fields for separate recording. |
| U-4 (equity cost) | **Resolved for v1 → flat $0.40, no % conversion** (per task §5) | Keep metadata-only; accounting simulator is a separate milestone. |
| U-5 (non-monotonic input) | **Still UQ** | Recommend reject. |
| U-6 ("next eligible candle") | **Still UQ** | Recommend next bar in filtered series + intra-session hole flagging. |
| U-7 (headline artifact) | **Still UQ** | Recommend 2025 portfolio headline + full-range context. |
| U-8 (verification gate) | **Still UQ** | Recommend versioned manifest. |
| **U-9 (new)** entry beyond SL/TP behaviour | **UQ — recommend deterministic void** (§2.3) | Approve `VOID_ENTRY_BEYOND_SL` / `VOID_ENTRY_BEYOND_TP`. |
| **U-10 (new)** cost-unit label | **EL — disclosure only** (§5.4) | Update report/manifest wording; do not change number. |

---

## 7. Required regression tests (additions to prior proposal §7)

1. **Geometry invariance across fills** — `F ∈ {1999.00, 2000.50, 2001.00}` ⇒ identical SL 1995.00 / TP1 2010.00 / TP2 2015.00.
2. **R numerics** — exact values from §2.2 matrix (±0.0001), both TP2 and SL exits.
3. **Entry void rules** — `F=1994.00` → `VOID_ENTRY_BEYOND_SL`; `F=2016.00` and `F=2012.00` → `VOID_ENTRY_BEYOND_TP`; no R, no cost.
4. **No post-outcome denominator write** — snapshot all geometry fields before and after `simulate_outcome`; assert unchanged.
5. **Structural-SL provenance** — fixture with support 1996 / ATR 2 ⇒ SL 1995; verify $250 cap fallback unchanged by fill.
6. **In-trade gap separation** — in-trade SL gap 1994 → R −1.38; in-trade TP1 gap 2012 → R +2.52; distinct from entry-gap fixtures.
7. **Cost exactly once** — `spread_paid == 0.40`; R drag `0.08` at planned risk 5.00; no portfolio/metric re-deduction.
8. **SELL mirror** — all BUY fixtures mirrored with resistance 2004 / SL 2005.

---

## 8. Integrity statement

This review read source, documentation, the prior proposal, and existing reports only. It did not modify any file other than creating this document; did not run backtests, tests, DB probes, or any script that could write artifacts; and did not overwrite historical results. All line numbers were read from the current checkout at the HEAD recorded above. All recommendations are proposals — **no option has been implemented**, and no baseline is validated by this review.
