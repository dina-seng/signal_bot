# SMC Baseline v1 — Canonical Execution Contract (Final)

**Repository:** `D:\trade`  
**HEAD inspected:** `69e6992113a1c183f4bea836fd9c02be42069634`  
**Date:** 2026-11-22  
**Status:** **FINAL DESIGN — implementation readiness. Nothing in this document has been implemented. No baseline is validated.**  
**Mode:** Read-only consolidation. No source, test, configuration, report, checkpoint, or database file was modified.

**Consolidates:** `establish.md`, `execution_contract_proposal.md`, `execution_contract_review.md`. Where these documents disagree, §0 records the contradiction and the resolution directed by the approved design direction; nothing is silently reconciled.

> **Guiding principle:** We are not trying to make the backtest profitable. We are trying to make the backtest truthful.

### Classification legend

| Tag | Meaning |
| :--- | :--- |
| **RULE** | Authoritative contract for v1; to be implemented exactly. |
| **CD** | Confirmed defect in current code that the rule fixes. |
| **EL** | Existing limitation retained and explicitly labelled (not fixed in v1). |
| **DECISION** | A decision now formalized from the approved design direction. |
| **UQ** | Still requires human approval before implementation / publication. |

---

## 0. Authority, supersession, and flagged contradictions

This contract is governed by the 11 approved design directions supplied for this task. They override earlier recommendations wherever the two differ. The following contradictions are recorded explicitly rather than silently resolved.

| ID | Source documents in conflict | Contradiction | Resolution in this contract | Status |
| :--- | :--- | :--- | :--- | :--- |
| **C-1** | `establish.md` §6 R2 vs approved direction 1 | R2 recommended *evaluating signals only at 1h closes* to align with the 1h-close price. Option B evaluates at every closed **15m** bar and fills at the next 15m open. | **Option B supersedes R2** for v1 cadence and fill timing. The 1h-close *price anchor* is retained (see C-2), so R2's underlying staleness concern is *documented*, not "fixed" by changing evaluation cadence. | DECISION — human must acknowledge R2 is superseded (U-1) |
| **C-2** | `execution_contract_proposal.md` U-2 sub-recommendation vs `execution_contract_review.md` §3.2 vs approved direction 3 | Proposal recommended the 15m decision-bar close as signal price; review withdrew this and kept the existing 1h-close reference. | **1h-close reference retained.** The proposal's "(a) use 15m close" is formally withdrawn. Changing it would alter `risk_price`, TP levels, and potentially the $250 structural cap → a frozen-strategy change. | DECISION — resolved by approved direction 3 |
| **C-3** | `execution_contract_proposal.md` §4.3 (configurable `execution_cost_pct` + equity reference) vs approved direction 7 | Proposal added a percentage-cost layer; direction 7 requires preserving flat `$0.40` and accurate labelling only. | **Percentage cost layer is deferred, not implemented in v1.** Keep literal `0.40` price-unit deduction; add only documentation/metadata fields. | DECISION — resolved by approved direction 7 |
| **C-4** | `execution_contract_proposal.md` §5.4 (entry gap through SL → R −5.4) vs `execution_contract_review.md` §2.4 vs approved direction 9 | Proposal conflated an in-trade stop gap with an entry-candle gap through SL. | **Corrected:** entry beyond SL/TP → deterministic `VOID_*` outcome (no trade). In-trade gaps keep adverse/favourite fill rules. The −5.4 example is withdrawn. | DECISION — resolved by approved direction 9 |
| **C-5** | `establish.md` Appendix C (`friction_usd_roundtrip: 0.40`) vs `execution_contract_review.md` §5.4 | "USD round trip" implies account currency; the code deducts 0.40 **price units per unit of position** (≈$40 per XAU standard lot). | Keep the number; **correct the label** to price units per position unit in all manifests/reports. | EL — disclosure change, no numeric change |
| **C-6** | `docs/SMC_FREEZE_V2.md` §3/§5 (clean forward holdout after 2026-11-15 15:00) vs `establish.md` N-14 (current DB extends to 2026-11-19 05:30) | The declared "strictly clean" holdout window has been observed in the current snapshot. | Treat the holdout as **contaminated** until a genuinely new snapshot is pinned. No one-shot holdout claim in v1 on current data. | UQ — human decision on snapshot policy (U-11) |

---

## 1. Canonical execution lifecycle

### 1.1 Lifecycle (RULE)

For each 15m bar `i` in the calendar-filtered series:

1. **Close gate.** Only evaluate after bar `i` has fully closed. `decision_time = bars[i].timestamp + 15m` (`smc_replay.py:352,360`).
2. **Lookback slice.** Pass only candles closed at or before `decision_time` (existing `bisect_right` mechanism, `:361-366`). Preserve as a positive zero-lookahead control.
3. **Signal + geometry.** Run the frozen production detection/scoring path; if accepted, compute SL/TP once from the existing signal-price reference (§2). Store `signal_time = decision_time`, `signal_price`, `structural_sl`, `tp1`, `tp2`, `planned_risk`.
4. **No management of bar `i`.** Its high/low occurred before the decision (fixes BT-004).
5. **Locate next eligible candle `j`** per §7.3. If ineligible/missing/new-session → emit the corresponding void outcome (§3.3, §7.3) and stop.
6. **Entry fill.** `fill_price = bars[j].open`; `entry_time = bars[j].timestamp`. Record separately from step 3.
7. **Entry validity.** Apply void rules §3.3 before opening any position.
8. **Management from bar `j` onward.** Resolve open-price gaps (§6.1/§6.2), then apply the intra-bar ladder SL → TP1 → TP2 (§6.3), with the TP1 50% / break-even / TP2 runner specification frozen.
9. **Exit.** Record `exit_time` as the open timestamp of the causing candle; close residual positions at the last bar close (`TIME_EXPIRY` / `END_OF_DATA`).
10. **Cost + R.** Deduct the single round-trip cost (§5); compute R with the planned denominator (§4).
11. **Persist.** Write signal time, entry time, signal price, actual fill, structural SL, planned risk, actual risk, price-unit P&L, cost, R, and reason fields into the checkpoint with a provenance header (§9).
12. **Aggregate.** De-duplicate by `opportunity_key` before funnel/metrics/portfolio processing (existing behaviour, preserved).

### 1.2 Timestamp convention (RULE)

| Field | Meaning | Existing analogue |
| :--- | :--- | :--- |
| `signal_time` | **Close** of the signal 15m candle | `SmcRecord.decision_time` |
| `entry_time` | **Open** of the next eligible 15m candle | new (currently conflated with `fill_time`) |
| `exit_time` | **Open** of the candle whose prices caused the exit | `SignalRecord.exit_time` |
| `bars_held` | `(exit_time − entry_time) / 15m`, clamped `>= 0` | `replay_harness.py:243` |

Decision timestamps are candle closes; execution timestamps are candle opens. Never label one as the other (fixes BT-034/N-07 and the −0.2h symptom in `stepC1_entries_per_day.md:61`).

### 1.3 U-1 — Option B vs R2 (DECISION, approval U-1)

| | Older R2 (`establish.md` §6) | **Option B (final, approved)** |
| :--- | :--- | :--- |
| Evaluation cadence | 1h closes only | Every closed 15m bar |
| Fill timing | same-bar market fill | Next eligible 15m candle **open** |
| Price anchor | 1h close | 1h close (**retained** — C-2) |
| Management start | signal bar (defective) | entry candle `j` |
| Dedup consequence | one trade per 1h candle | `opportunity_key` dedup still applied; bar-level funnel counts rise |
| Recorded difference | — | Must be documented as a delta in the baseline manifest |

Option B is the new execution convention. Its difference from R2 is: **cadence + fill timing changed; price anchor unchanged.** A human must acknowledge that R2 is superseded before implementation.

---

## 2. Signal-price and structural SL/TP geometry

### 2.1 Structural derivation (RULE — unchanged)

```
SwingDetector.detect_swings (1h, N=2 right-confirmed)
  → StructureEngine: key_support = min(last ≤5 swing lows)
                     key_resistance = max(last ≤5 swing highs)
  → RiskManager.calculate_trade_risk(entry_price = last closed 1h close,
                                     atr_value = 1h ATR,
                                     key_support/key_resistance)
  → BUY:  SL = support − 0.5×ATR   (cap: distance > $250 → SL = entry − 1.5×ATR)
     SELL: SL = resistance + 0.5×ATR (mirror)
     TP1 = entry ± 2×planned_risk ; TP2 = entry ± 3×planned_risk
```

Verified locations: `swing_detector.py:39-147`; `structure_engine.py:250-256`; `liquidity_service.py:111-141`; `risk_manager.py:36-112`; `symbols.py:31-40` (XAU `pip_size=0.10`, cap `$250`); `smc_replay.py:445-491`.

### 2.2 Geometry immutability (RULE)

`structural_sl`, `tp1`, `tp2`, and `planned_risk` are computed **once** at signal generation and are write-once fields. They must not be recomputed from the actual fill, from bar high/low, or after outcome resolution. This is Option A from `execution_contract_review.md` §3. Re-running `RiskManager` on the fill can move the structural SL (e.g. BUY fill 1994 below support 1996 → fallback SL 1991 instead of 1995) and changes TP distances — a frozen-strategy violation.

### 2.3 Scope of structure (EL — disclose, do not change)

Canonical SL comes solely from swing-derived key support/resistance ± ATR buffer and the $250 cap. SR zones, liquidity pools, FVGs and order-block concepts are advisory-only in the production path and are **not** invoked by the canonical replay at all. The 0.10 (RiskManager) vs 0.01 (ATRCalculator) pip inconsistency for XAU remains an open limitation (**BT-010**); do not silently unify it.

### 2.4 Numerical base geometry (fixture)

Signal price `P_s = 2000.00` (1h close), ATR = 2.00:
- BUY: support 1996.00 → SL **1995.00**, planned risk **5.00**, TP1 **2010.00**, TP2 **2015.00**.
- SELL: resistance 2004.00 → SL **2005.00**, planned risk **5.00**, TP1 **1990.00**, TP2 **1985.00**.

---

## 3. Entry and exit execution rules

### 3.1 Entry (RULE)

`fill_price = bars[j].open`; `entry_time = bars[j].timestamp`. Normal-range entry requires, strictly: `SL < F < TP1` for BUY, `TP1 < F < SL` for SELL. Management begins at bar `j`.

### 3.2 Exit (RULE)

Per managed bar: first resolve any open-price gap (§6), then SL, then TP1 (book 50%, stop → break-even), then TP2 (close runner). Residual at `hard_end` closes at the last bar close with `TIME_EXPIRY`/`END_OF_DATA`. Same-bar SL+TP resolves **SL-first** (conservative, deterministic, BT-042 preserved).

### 3.3 Deterministic void-entry outcomes (U-9 — DECISION, approval required)

| Outcome | Trigger | Effect |
| :--- | :--- | :--- |
| `VOID_ENTRY_BEYOND_SL` | BUY `F <= SL` / SELL `F >= SL` — structural invalidation already breached at entry | No position, no R, no cost |
| `VOID_ENTRY_BEYOND_TP` | BUY `F >= TP1` / SELL `F <= TP1` — planned ladder no longer ahead of price | No position, no R, no cost |

**Counting and metric semantics (RULE):**
- Signal funnel is unchanged: the bar remains `accepted=True`, `gate=CONFIRMED_SETUP`. The signal was valid; the *entry* was voided.
- `n_candidates` includes void entries so funnel totals reconcile. Add a distinct bucket `n_void_entry` (split by reason) alongside `n_filled` and `n_no_fill`; **never merge voids into `n_no_fill` or count them as 0R** (that would bias expectancy).
- Win rate, expectancy, PF and DD remain computed on `filled` trades only. Report `void_rate = n_void_entry / n_candidates`.
- `smc_portfolio_2025.load_checkpoint_trades:179` currently dereferences `exit_time` unconditionally and would crash on void records (N-15). It must skip void records **before** that line and count them.
- Controls: for v1, exclude void entries from the control population consistently (both real and control), so the control distribution remains over filled trades only. Document the exclusion.
- The verification manifest must pin expected `n_filled`, `n_void_entry`, and `total_r` together.

Worked numeric examples: BUY `F=1994.00` (SL 1995) → `VOID_ENTRY_BEYOND_SL`; BUY `F=2016.00` or `2012.00` (TP1 2010) → `VOID_ENTRY_BEYOND_TP`. In both cases `R = n/a`, cost not charged.

---

## 4. Planned R versus actual execution loss

### 4.1 Canonical R (RULE)

`R = (booked_price_pnl_from_actual_fills − execution_cost_price_units) / planned_risk`

`planned_risk = |signal_price − structural_sl|` is fixed at signal time, before the fill is known. This is the strategy's own unit (TP1=2R, TP2=3R) and prevents any outcome-dependent denominator change.

### 4.2 Separately recorded quantities (RULE)

| Field | Definition | Example: BUY, `F=2001`, SL 1995 |
| :--- | :--- | :--- |
| `planned_risk` | `|signal_price − SL|`, fixed | 5.00 |
| `actual_risk_distance` | `|fill_price − SL|`, known at entry | 6.00 |
| `price_unit_realized_pnl` | `(exit_fill − fill_price)` weighted by partial sizes | SL hit: −6.00 |
| `monetary_realized_loss` | price-unit P&L × position notional | **`null` / `NOT_MODELED`** — the R engine has no lot/notional accounting; do not invent it |
| `r_multiple` | numerator above ÷ planned risk | −1.28 (with cost) |

Gaps therefore appear in the numerator only: a worse fill genuinely lowers R; a better fill raises it. Using actual risk as denominator would report −1.0R and hide the gap. Do not rescale R or drop trades when planned and actual risk diverge; attach a descriptive `GAP_RISK_DIVERGENCE` flag and report the distribution.

R numerics for the base fixture (cost 0.40 = 0.08R): BUY normal → TP2 **+2.32R**, SL **−1.18R**; SELL normal → **+2.32R / −1.18R**; BUY favourable fill 1999.00 → **+2.62R / −0.88R**; BUY adverse fill 2001.00 → **+2.22R / −1.28R**.

---

## 5. Execution cost convention

### 5.1 v1 rule (RULE — DECISION)

- Keep the existing flat **`0.40`** round-trip deduction, applied **once** per completed trade in `replay_harness.py:236-238`. Implementation is correct as written; no evidence of a bug. Record `spread_paid` (`:244`).
- **Accurate label:** `0.40` **price units per unit of position, round trip** (not `$0.40` of account equity; for XAU at 100 oz/lot that is $40 per standard lot). Correct wording in reports and manifest (C-5).
- **Round trip, not per leg.** No slippage, commission, bid/ask, portfolio-level, or second deduction.
- **No equity-percentage conversion in v1** (C-3). The engine is R-based fixed-risk; it has no equity/lot state (`risk_manager.py:122-125` values are computed but ignored).
- Continue printing the assumption in reports (`smc_replay.py:714`).
- `$0.40` is **never** a stop distance — exhaustive search shows it only in cost contexts.

---

## 6. Gap handling and intrabar ambiguity

### 6.1 In-trade stop gap (RULE)

On a managed candle opening beyond the stop: BUY `stop_fill = min(open, SL)`, SELL `stop_fill = max(open, SL)`. Record intended SL and actual fill separately; compute loss from the actual fill. Example: entered 2000.50, later open 1994 vs SL 1995 → P&L `−6.50`, net `−6.90`, **R −1.38**.

### 6.2 In-trade TP gap (RULE)

A favourable gap must not fill worse than the limit: BUY `tp_fill = max(open, TP)`, SELL `tp_fill = min(open, TP)`. If the entry candle opens beyond TP2, that is an **entry** void (§3.3), not an in-trade gap. Example: entered 2000.50, later open 2012 through TP1 → TP1 leg 5.75, BE stop, TP2 7.25, net 12.60 → **R +2.52**.

### 6.3 Intrabar ambiguity (RULE)

Candle touches both SL and TP with no lower-timeframe ordering → **SL-first**, conservative and deterministic; never select the favourable outcome. Applied on every managed bar including the entry bar. No randomness.

---

## 7. Invalid and missing candle handling

### 7.1 U-5 — timestamp and candle integrity (DECISION, approval required)

At load (`replay_harness.py:250-300`), reject with an explicit error — do **not** silently sort or repair:

- non-monotonic timestamps;
- duplicate timestamps with conflicting OHLC (identical duplicates may collapse, as today);
- invalid OHLC (`high >= max(open, close)`, `low <= min(open, close)`, `high >= low`, positive prices);
- forming bars (`timestamp + 15m > as_of`) — the run must use a closed snapshot.

Keep the `source='twelvedata'` filter and the calendar filter. Missing OHLC/monotonic validation is BT-021/N-29; fixing it is in scope.

### 7.2 Session model (RULE, derived from `calendar.py:21-63`)

XAU/NY: Fri close 17:00, Sat closed, Sun open 18:00, Mon–Thu maintenance 17:00–18:00. A bar is a **session-open bar** iff `is_market_open(bar.timestamp − 15m) == False`. Closed/placeholder bars are already removed by `filter_open_market_candles`.

### 7.3 U-6 — next eligible candle (DECISION, approval required)

For signal bar `i`, the next eligible candle is `j = i+1` in the filtered series, subject to:

| Case | Condition | Outcome |
| :--- | :--- | :--- |
| Normal | `bars[j].timestamp − bars[i].timestamp == 15m`, same session | Enter at `bars[j].open` |
| **New trading session** | `j` is a session-open bar (weekend or maintenance break) | `NO_FILL_SESSION_BOUNDARY` — **void, no trade, no cost**. Stale signals must **not** execute across a new session. Override only by explicit human config `allow_cross_session_entry=True`; default `False`. |
| **Unexpected missing intraday bar** | gap `> 15m` while `is_market_open(bars[i].timestamp + 15m)` is True | `NO_FILL_MISSING_NEXT_BAR`; flag dataset `DATA_INTEGRITY_WARNING`; never fabricate a fill. Baseline publication requires zero such holes or written authorization. |
| End of data | no `j` | `NO_FILL_END_OF_DATA` |

This defines session boundaries, weekend closures, and unexpected intraday holes, and forbids cross-session stale execution by default. The new outcome names are part of U-6 and must be approved.

---

## 8. Portfolio simulation limitations

### 8.1 Retained model (RULE)

Keep the capacity-filtered approach: `MAX_CONCURRENT=3`, `DAILY_LOSS_STOP=−3.0R` realised, one entry per `opportunity_key`, 1ATR/1h separation, fixed 1R per position (`smc_portfolio_2025.py:80-85,237-296`). Feed it the corrected exit times and R from this contract; re-simulate controls with the same corrected engine.

### 8.2 Accurate labelling (RULE)

Describe results as a **"capacity-filtered / portfolio-constrained 1R trade set"**, not a capital-aware account simulator. No shared margin, lot sizing, compounding, or broker contract execution. Remove or relabel the illustrative `$100` executability section (`smc_portfolio.py:90,108-120`) so no dollar figure implies account accounting.

### 8.3 U-7 — headline artifact (DECISION, approval required)

| Artifact | Role | Why separate |
| :--- | :--- | :--- |
| `reports/exp_2025_smc_portfolio/report.md` (2025 window, start 2025-01-01) | **Primary comparable headline** | 688 distinct opportunities → 249 portfolio-entered trades; single well-defined window |
| Full-range replay (`reports/smc_replay_extended/`) | Supplementary funnel/context analysis | 1,491 opportunities → 538 entered across the whole history; different population and window |

They are **different evaluation windows and populations**; never mix their counts or R in one headline table. Both currently show direction-control **FAIL** (34.5% validation / 84.8% test vs 97.5% in the 2025 report) → descriptive only, not an edge claim.

---

## 9. Run manifest and checkpoint provenance

### 9.1 U-8 — verification gate (DECISION, approval required)

Replace the hard-coded `EXPECTED_TRADES=688` / `EXPECTED_TOTAL_R=136.45` (`smc_portfolio_2025.py:92-95,596-604`) with a **versioned run manifest** plus **deterministic regression fixtures**. Any correct fix will break the old constants; do not edit them silently.

### 9.2 Required manifest fields (RULE)

```yaml
baseline_id: smc-baseline-v1
engine_commit: <git sha>                 # code version / git commit
created_utc: <timestamp>                 # report generation timestamp
data:
  path: backtest.db
  sha256: <hash>                         # data snapshot identifier/hash
  symbol: XAU/USD
  source: twelvedata
  timeframe: 15m                         # timeframe
  raw_rows: <n>
  open_market_rows: <n>
  missing_intraday_bars: <n>
  first_bar_open_utc: <ts>
  last_bar_open_utc: <ts>
backtest_range: [<start_utc>, <end_utc>]  # backtest date range
strategy:
  config_hash: <hash>                    # strategy configuration hash
  frozen_commit: 87509a4...
execution:
  convention_version: optionB-v1         # execution convention version
  config_hash: <hash>                    # execution configuration hash
  cadence: 15m_close ; fill: next_15m_open ; price_anchor: 1h_close
  gap_fill: adverse_open / limit_or_better
  intrabar: sl_first
  void_rules: [VOID_ENTRY_BEYOND_SL, VOID_ENTRY_BEYOND_TP, NO_FILL_SESSION_BOUNDARY]
  cost: 0.40 price_units_per_position_unit_round_trip   # cost assumptions
splits: {calibration: [...], validation: [...], test: [...], holdout: <ts + contamination status>}
metrics: {drawdown_basis: exit_time, breakeven: loss, bootstrap: day_cluster, seed: <n>, min_n: 100}
expected: {n_filled: <n>, n_void_entry: <n>, total_r: <n>}
artifacts: {checkpoints: <path>, report: <path>, controls: <path>, regression_fixtures: <path>}
```

### 9.3 Checkpoint provenance (RULE)

Add `schema_version`, `execution_convention_version`, `engine_commit`, `data_sha256`, `strategy_config_hash`, `execution_config_hash`, `split_id`, `created_utc` to every checkpoint header. Resume (`smc_replay.py:934-999`) must reject mismatches; cached chunks must contribute identical gap counters (N-05/N-11).

---

## 10. Regression test requirements

Hermetic tests only (`conftest.py:5-69` guards preserved). New files: `test_smc_replay_engine.py`, `test_data_loader_validation.py`, `test_replay_metrics.py`, `test_smc_portfolio_rules.py`.

| # | Scenario | Expected |
| :--: | :--- | :--- |
| 1 | Signal bar touches SL before entry | No management on signal bar |
| 2 | Signal bar touches TP before entry | No management on signal bar |
| 3 | Next bar opens normally | Fill at `bars[j].open`, management from `j` |
| 4 | In-trade SL gap (open 1994, SL 1995) | `stop_fill=1994`, R −1.38 |
| 5 | In-trade TP1 gap (open 2012) | fill 2012, R +2.52 |
| 6 | Both SL and TP in one bar | SL-first, no TP booked |
| 7 | Entry `F=1994` | `VOID_ENTRY_BEYOND_SL`, no R/cost |
| 8 | Entry `F=2016` / `2012` | `VOID_ENTRY_BEYOND_TP`, no R/cost |
| 9 | Entry at Sunday 18:00 / post-maintenance 18:00 | `NO_FILL_SESSION_BOUNDARY`; no cross-session fill |
| 10 | Unexpected missing intraday bar | `NO_FILL_MISSING_NEXT_BAR`, never fabricated |
| 11 | Non-monotonic / conflicting duplicate / invalid OHLC / forming bar | Rejected deterministically |
| 12 | Entry gap fixtures 1999/2000.5/2001 | SL/TP/TP1/TP2 unchanged (geometry immutability) |
| 13 | R numerics §4.2 | Exact values ±0.0001 |
| 14 | Actual vs planned risk divergence | Both recorded; R denominator unchanged |
| 15 | Cost | `spread_paid=0.40`, deducted exactly once, no portfolio/metric re-deduction |
| 16 | Timestamps | `signal_time != entry_time` fields distinct; `exit_time >= entry_time`; no negative holding |
| 17 | Replay restart | Byte-identical outputs; prefix invariance (truncate vs pad future) |
| 18 | Portfolio loader with void records | No crash; voids counted, excluded from R stats |
| 19 | Verification gate | Manifest-based expected values; deterministic fixtures reproduce counts |
| 20 | Frozen-strategy characterization | N-03/N-04 behaviour locked; no strategy file changed |

Additional gates: `python -m pytest tests/` green (prior status 270 passed / 5 failed — triage first); no live API/Postgres; canonical tests green before regeneration.

---

## 11. Historical artifact migration rules

1. **Never overwrite.** All corrected outputs → `reports/smc_baseline_v1/` (and sibling versioned checkpoint dir). Keep `reports/exp_2025_smc*`, `reports/smc_replay_extended/`, `reports/smc_analysis_v2/`, `reports/smc_replay_regime_filter/` intact.
2. **Pin the snapshot.** Current DB (110,280 15m rows to 2026-11-19 05:30) differs from the report snapshot (100,408 rows to 2026-11-15 15:00). Old numbers are not reproducible; publish a hash and row counts.
3. **Record deltas.** For every regenerated metric, publish pre/post values and explain each change (timing, gaps, voids, cost label). Do not tune strategy parameters to improve the delta.
4. **Contaminated holdout.** The 2026-11-15 15:00 forward holdout is no longer clean on current data (C-6). Do not make a one-shot holdout claim until a new snapshot is pinned and authorized.
5. **Exit labels.** Current simulator emits `TIME_EXPIRY`/`END_OF_DATA`; old artifacts use `TIMEOUT_MARK_TO_MARKET`. Version the mapping; do not hand-edit historical reports.
6. **Documentation.** Update stale line references (`SMC_FREEZE_V2.md:23`), commit the BT register, and point docs to the new manifest.

---

## 12. Final implementation phases

| Phase | Scope | Exit gate |
| :--: | :--- | :--- |
| **0 — Approve** | Human approval of U-1, U-5, U-6, U-7, U-8, U-9, U-11; acknowledge C-1/C-2 supersessions | Written approval recorded in manifest |
| **1 — Execution correctness + tests first** | `replay_harness.simulate_outcome`: fill at `j`, no signal-bar management, gap fills, void outcomes, fixed geometry; loader validation; `smc_replay.replay_chunk` wiring; new test files | §10 tests 1–17 green; no strategy file touched; no artifacts regenerated |
| **2 — Accounting & labels** | Portfolio void handling (N-15), metric bucket separation, cost-label correction (C-5), monetary/actual-risk fields, portfolio labelling, manifest-based gate | No crash on voids; no negative holdings; single cost deduction; gate uses manifest |
| **3 — Provenance & metrics** | Checkpoint headers, resume rejection, single metrics module, day-cluster bootstrap, split unification, run manifest emission | Artifacts traceable; golden metrics identical across producers |
| **4 — Full regression suite** | Complete §10; triage prior 5 failures | Full suite green; hermetic guards intact |
| **5 — Baseline regeneration** | Pin snapshot; write `reports/smc_baseline_v1/`; record deltas; re-run controls; **no holdout claim on current data** | Clean checkout + pinned snapshot reproduces every published number |

Phase 1 is a hard blocker: no R metric may be cited before it passes. Phase 5 is the only phase that writes reports/checkpoints.

---

## 13. Decisions still requiring human approval

| ID | Decision | Recommendation |
| :--- | :--- | :--- |
| **U-1** | Adopt Option B cadence/fill; acknowledge R2 is superseded (C-1) | Approve Option B; retain 1h-close price anchor |
| **U-5** | Reject non-monotonic timestamps and conflicting duplicates | Reject, do not sort/repair |
| **U-6** | Next-eligible-candle rules: new session void, missing-bar void, cross-session forbidden by default | Approve `NO_FILL_SESSION_BOUNDARY` / `NO_FILL_MISSING_NEXT_BAR`; default `allow_cross_session_entry=False` |
| **U-7** | Headline artifact | 2025 portfolio = primary; full range = supplementary; never mix |
| **U-8** | Verification gate | Replace hard-coded values with versioned manifest + deterministic fixtures |
| **U-9** | Void-entry outcomes and their count/funnel/metric semantics | Approve §3.3 exactly |
| **U-11** | Snapshot policy given contaminated holdout (C-6) | Pin a new snapshot or publish holdout as contaminated; no one-shot claim on current data |

Resolved by the approved design direction (no further action): U-2 (Option A geometry, 1h-close anchor), U-3 (planned-risk denominator), U-4 (flat `$0.40`, no % conversion), portfolio capacity-filter labelling, versioned outputs.

---

## 14. Integrity statement

This document was produced by reading `establish.md`, `execution_contract_proposal.md`, `execution_contract_review.md`, canonical source files, tests, reports, and the market calendar. It did not modify any source, test, configuration, report, checkpoint, or database file; did not run backtests or tests; did not generate artifacts; and did not overwrite existing documents. **No option has been implemented and no baseline is validated by this document.**
