# Canonical SMC Backtest Execution Model — Baseline v1
## Technical Implementation Proposal (investigation & planning only)

**Repository:** `D:\trade`  
**HEAD inspected:** `69e6992113a1c183f4bea836fd9c02be42069634` (2026-11-22 13:34:57 +0700)  
**Date:** 2026-11-22  
**Mode:** READ-ONLY. No source, test, configuration, report, checkpoint, or database file was modified. This document is the only new file. The pre-existing uncommitted `package.json` change (a harness-added `packageManager` field) was left untouched. No backtest script was run; no Python module was imported in a way that could rewrite `.rayu/settings.local.json`; no SQLite probe was executed (to avoid creating `-wal`/`-shm` sidecars). All findings below come from direct source inspection plus the already-present `establish.md` audit.

> **Guiding principle (unchanged):** We are not trying to make the backtest profitable. We are trying to make the backtest truthful.

---

## 0. Scope, status, and classification legend

This proposal formalizes **market-entry timing, execution costs, and gap-handling** for the canonical SMC engine. It is the planning input for the next milestone (implementation of the approved contract, regression tests, then a fresh canonical baseline run). **No baseline claim is validated by this document.**

### 0.1 Classification legend (applies to every finding below)

| Tag | Meaning |
| :--- | :--- |
| **CD — Confirmed defect** | Behaviour is wrong on current code; verified by reading the executing path (and, where noted, by the in-memory probes recorded in `establish.md` Appendix A.3). |
| **EL — Existing limitation** | Current behaviour is internally consistent but deliberately incomplete; not "wrong", but must be labelled and cannot support stronger claims. |
| **PD — Proposed design decision** | A specific convention this proposal recommends adopting; no code written yet. |
| **UQ — Unresolved question** | Requires a human decision before implementation; options and a recommended default are given in §11. |

### 0.2 Relationship to `establish.md`

`establish.md` is the canonical-engine establishment audit and remains the authoritative inventory of findings `BT-001…BT-045` and `N-01…N-30`. This proposal **does not re-litigate** those findings; it verifies them against current code (§2) and resolves the *new* execution-model decisions requested here:

- **Option B entry convention** (§3) — note the explicit tension with `establish.md` R2 (§11, U-1).
- **Equity-percentage cost model** (§4) — note that the current engine has no equity accounting (§11, U-4).
- **SL/TP gap convention and TP favourable-gap default** (§5).
- **Intrabar SL+TP, missing candle, non-monotonic input** (§3.4, §5.4, §8).
- **Versioned output directory** `reports/smc_baseline_v1/` (§8.4).

---

## 1. Current execution architecture (verified)

### 1.1 Canonical engine boundary (verified against `establish.md` §0.1)

| Role | Canonical implementation |
| :--- | :--- |
| Signal generation + per-trade simulation | `server/scripts/smc_replay.py` |
| Execution/data/metric primitives | `server/scripts/replay_harness.py` |
| Portfolio accounting — 2025 headline window | `server/scripts/smc_portfolio_2025.py` |
| Portfolio accounting — full range (C1 variant) | `server/scripts/smc_portfolio.py` |

Not canonical: sweep walk-forward (`server/app/services/sweep/backtest/`), legacy API backtester (`server/app/services/backtesting/`, `/api/v1/backtest/*`), client dashboard. This proposal does not touch them.

### 1.2 Verified call chain

```
backtest.db (read-only, source='twelvedata', 15m only)
  └─ replay_harness.load_full_15m_candles            :250-300
       ├─ _parse_ts (bar-OPEN UTC)                    :39-47
       ├─ dedupe by timestamp (keep first, no conflict check) :272-288
       └─ filter_open_market_candles                  :289
  └─ replay_harness.build_timeframe_series           :53-61  (resample 1h/4h, close = open+delta)
  └─ smc_replay.main                                  :855-1033
       └─ replay_chunk (per closed 15m bar)           :331-518
            ├─ decision_time = bars[i].timestamp + 15m     :352,360
            ├─ bisect_right slices c15/c1h/c4h by CLOSE   :361-366
            ├─ ConfluenceEngine._prepare_market_data       :371-377
            ├─ SMCStrategy.analyze                          :378-386
            ├─ _classify_smc (gate, direction, score)      :240-302
            ├─ indicators.current_price (= last CLOSED 1h close) :447; indicator_service.py:177-178
            ├─ build_market_trade → RiskManager geometry   :160-215; risk_manager.py:36-141
            └─ _simulate → simulate_outcome(bars, i, ...)   :218-234,479-496
                 └─ replay_harness.simulate_outcome        :124-244
                      ├─ market: fill_idx = signal_index           :176-177
                      ├─ fill_time = bars[fill_idx].timestamp      :179-180  (bar OPEN)
                      ├─ loop from fill_idx: SL → TP1 → TP2        :190-225
                      ├─ time expiry / end-of-data at last close   :227-234
                      ├─ net_price_pnl = booked − spread           :236-237  (ONE flat $0.40)
                      ├─ r_multiple = net / risk                    :238
                      └─ bars_held = exit_idx − fill_idx            :243
  └─ save_checkpoint (no provenance header)           :528-541
  └─ _metrics / trade_metrics                         :560-587; replay_harness.py:363-413
  └─ smc_portfolio_2025.main → apply_portfolio_rules  :237-296
                              → compute_metrics        :306-377
                              → simulate_control       :423-453
                              → control_block          :474-528
                              → verification gate      :588-604
```

### 1.3 Required investigation trace (task §6)

| # | Question | Verified answer (code location) |
| :--: | :--- | :--- |
| 1 | Where signals are generated | `ConfluenceEngine._prepare_market_data` (`smc_replay.py:371-377`) → `SMCStrategy.analyze` (`:378-386`). Gate/price levels are *derived* in `_classify_smc` (`:240-302`) and `build_market_trade` (`:160-215`); the strategy emits no price levels. |
| 2 | Where 15m decision timestamps are assigned | `smc_replay.py:352` `bar_close[i] = bars[i].timestamp + TF_15M`; `decision_time = bar_close[i]` at `:360`; stored as `SmcRecord.decision_time` / `SignalRecord.signal_time` (`:200`, `:459-477`). |
| 3 | Where current entry price is obtained | `indicator_service.py:177-178` `latest_price = closes[-1]` of the **1h** primary series; passed as `current_price` at `smc_replay.py:447` and into `build_market_trade` at `:484`/`:503`. It is a 1h **close**, not a 15m price and not an executable open. |
| 4 | Where replay begins trade management | `replay_harness.py:177` `fill_idx = signal_index`; loop `for k in range(fill_idx, hard_end)` at `:191`. Management therefore includes the signal bar itself → **BT-004**. |
| 5 | Where SL/TP execution is calculated | `replay_harness.py:195-203` (SL first), `:205-215` (TP1 50% + BE), `:217-225` (TP2), `:227-234` (close at last close). All fills use the exact **level** (`stop`, `tp1`, `tp2`), never the bar open → **BT-006**. |
| 6 | Where execution costs are deducted | Once, at `replay_harness.py:236-238`: `net_price_pnl = booked_price_pnl - spread`; `r_mult = net / risk`. `spread` defaults to `0.40` (`smc_replay.py:822-826`) and is mirrored in `smc_portfolio_2025.py:88`. Portfolio consumes stored `r_multiple` (`:207`) and re-simulates controls with the same `SPREAD` (`:449-452`). No second deduction was found. |
| 7 | Where R-multiples and monetary values are calculated | R: `replay_harness.py:238` then rounded `:242`; monetary: **none in the canonical engine** — RiskManager computes `risk_amount_usd`/`suggested_lot_size` (`risk_manager.py:122-125`) but replay ignores lots and uses fixed 1R. The only dollar figures are the flat `$0.40` friction and the illustrative `$100` executability analysis in `smc_portfolio.py:90,108-120`. |
| 8 | Where portfolio filtering / metrics are computed | `smc_portfolio_2025.py:155-219` (load), `:222-231` (dedupe), `:237-296` (rules), `:302-377` (metrics), `:380-417` (exposure), `:474-528` (controls). Replay-level metrics: `smc_replay.py:560-587`, `replay_harness.py:363-413`. Two different DD orderings (signal-time vs exit-time) and BE-as-loss (`r <= 0`) are confirmed. |
| 9 | Which tests cover these behaviours | **None directly.** `grep` for `simulate_outcome\|replay_chunk\|build_market_trade\|apply_portfolio_rules\|control_block\|load_full_15m_candles` across `server/tests/` returns only `test_walk_forward_harness.py:100`, which calls a *different* harness. `test_smc_regime_filter.py:17` imports `smc_replay` only for `SmcRecord` and constants; it tests regime filtering (`:20-64`), the CLI flag (`:67-75`), and the split boundary (`:78-96`). `conftest.py:5-12,46-69` provides hermetic SQLite guards (preserve). |
| 10 | Which reports/checkpoints become invalid after a fix | See §9. Headline: `reports/exp_2025_smc_portfolio/report.md`; 23 checkpoints in `reports/exp_2025_smc/checkpoints/`; full-range artifacts in `reports/smc_replay_extended/`; exploratory `reports/smc_analysis_v2/stepC1…C6`; regime-filter copies. **Do not overwrite — write to `reports/smc_baseline_v1/`.** |

### 1.4 Verified data structures

- `SignalRecord` (`replay_harness.py:67-95`): `signal_time`, `direction`, `entry_mode`, `crt_entry` (geometry anchor **and** P&L entry — conflated), `stop_loss`, `take_profit_1/2`, `risk_price`, `filled`, `fill_time`, `exit_reason`, `exit_time`, `r_multiple`, `bars_held`, `spread_paid`, `sweep_key`. `entry` is a property returning `crt_entry` (`:93-95`).
- `SmcRecord` (`smc_replay.py:121-145`): one evaluated 15m bar, including `decision_time`, `opp_key`, `accepted`, `accepted_trade`, `counterfactual_trade`.
- Checkpoint JSON (`save_checkpoint`, `:528-536`): `{"month", "records": [asdict(SmcRecord)...]}`. **No schema/version/code/data/parameter provenance** (N-05).

---

## 2. Identified defects and affected files/functions

All entries below were re-verified against current code. `BT-…`/`N-…` IDs are from `establish.md`.

| ID | Class | Finding | File / function (verified lines) | Effect on headline |
| :--- | :--- | :--- | :--- | :--- |
| BT-004 | **CD** | Market entry evaluates the signal bar: fill at its close but management starts at that bar's open-time range. A pre-entry wick can stop/TP a trade that was not yet active. | `replay_harness.py:176-191`; `smc_replay.py:493` | Direct. `establish.md` A.3 probe: entry 100, SL 99, signal-bar low 90 → `STOP_LOSS −1.0`. |
| BT-006 | **CD** | Exits fill at exact stop/limit levels even when the bar opens beyond them; gap risk omitted. | `replay_harness.py:195-225` | Direct. Probe: gap open 95 vs SL 99 → `STOP_LOSS −1.0` instead of worse. |
| BT-002 | **CD** | Limit branch checks stop before limit touch and voids filled-then-stopped outcomes. | `replay_harness.py:158-175` | Baseline is market-only, so headline unaffected; `run_step6` limit candidates wrong. Fix in same loop. |
| N-01 / N-19 | **CD** | Signal price is the last **closed 1h** close while decisions are taken at **15m** closes; intra-hour decisions mix as-of times and can use a stale price up to 45m old. | `smc_replay.py:447,484`; `indicator_service.py:177-178` | Direct to entry timing and holding stats. Central to Option B (§3). |
| BT-034 / N-07 | **CD** | `fill_time`/`exit_time` are bar **open** labels while `signal_time` is a bar **close**; `wall_hours = exit_dt − decision_dt` can be negative. | `replay_harness.py:180,202,224,234`; `smc_portfolio_2025.py:210` | Visible symptom: `stepC1_entries_per_day.md:61` min holding **−0.2h**. |
| BT-039 | **CD** | Flat `$0.40` round-trip deducted once in price units; no slippage, commission, per-leg accounting, or configurable percentage. | `replay_harness.py:236-238`; `smc_replay.py:822-826`; `smc_portfolio_2025.py:88`; `SMC_FREEZE_V2.md:23` | Direct to every R figure. Cost model §4. |
| BT-020 / N-09 / N-21 | **CD** | Two metric implementations with different DD ordering (signal-time vs exit-time); BE counted as a loss (`r <= 0`); PF-with-zero-loss handling differs. | `smc_replay.py:560-587`; `replay_harness.py:363-399`; `smc_portfolio_2025.py:306-377` | Direct to reported metrics. |
| BT-025 / N-20 | **CD** | Filled-only expectancy and IID trade-level bootstrap; project's own freeze reports day-cluster VIF ≈ 5.1 (`SMC_FREEZE_V2.md:85`). | `replay_harness.py:332-344,402-413`; `smc_replay.py:560-587` | Direct to any edge claim. |
| BT-027 / N-12 | **EL** | "Portfolio" is an ex-post capacity filter over independently simulated 1R trades; no shared capital, margin, or compounding. | `smc_portfolio_2025.py:237-296`; `smc_portfolio.py` | Headline 249 trades must be labelled "capacity-filtered", not account-level. |
| N-05 / N-14 | **CD** | Checkpoints have no provenance; resume silently reuses them. Current DB (110,280 rows to 2026-11-19 05:30 per `establish.md` A.2) differs from the report snapshot (100,408 rows to 2026-11-15 15:00). Old results are not reproducible. | `smc_replay.py:528-541,934-999`; reports metadata | Direct to reproducibility. |
| N-06 | **CD** | Hard-coded verification gate `EXPECTED_TRADES=688` / `EXPECTED_TOTAL_R=136.45` will fail after any correct fix. | `smc_portfolio_2025.py:92-95,596-604` | Blocks regeneration until versioned. |
| N-08 / N-16 | **CD** | Current simulator emits `TIME_EXPIRY`/`END_OF_DATA`; old reports/checkpoints use `TIMEOUT_MARK_TO_MARKET`. | `replay_harness.py:233`; `smc_portfolio.py:511,518`; `stepC1…md:68,73` | Report text is wrong. |
| N-15 | **EL** | Portfolio loader assumes `exit_time` present; no-fill/`INVALID_RISK` records would crash. | `smc_portfolio_2025.py:179` | Latent (baseline market fills all). |
| BT-021 / N-29 | **CD** | Loader has no OHLC validation, no monotonic assertion, no duplicate-conflict resolution, no forming-bar drop. | `replay_harness.py:250-300` | Input-integrity risk. |
| N-13 | **CD** | Controls call the same `simulate_outcome`, so real and control R are internally consistent but **both biased** by BT-004/BT-006. | `smc_portfolio_2025.py:423-453` | Fix real + control together. |
| N-02 / N-03 / N-04 / N-18 | **EL** | LTF filter frozen at 1h close; PA/confluence floors are metadata not vetoes; `FATAL_CONFLICT` gate unreachable. | `ltf_confirmation.py:45-98`; `evaluators.py:531-598`; `smc_replay.py:255-291` | Strategy behaviour — **frozen; do not change**. Characterize only. |

**Cost double-count check (verified):** the `$0.40` is subtracted once at `replay_harness.py:237`; checkpoint `r_multiple` already contains it (`smc_portfolio_2025.py:207`); controls re-simulate with the same single `SPREAD` (`:449-452`). **No double-count exists today.** The risk of double-counting arises only if per-leg costs or portfolio-level deductions are added later — §4.3 forbids that without an explicit pre-registration.

---

## 3. Proposed canonical execution contract — Option B

### 3.1 Definitions and timestamp convention (PD)

Adopt a single, explicit convention. All timestamps are timezone-aware UTC.

| Symbol | Definition | Source |
| :--- | :--- | :--- |
| `decision_time` (signal timestamp) | The **close** of the 15m signal candle `i`: `bars[i].timestamp + 15m`. | `smc_replay.py:352,360` |
| `signal_price` | The price on which the signal/geometry is evaluated. See **U-2** — default proposal: `bars[i].close` (the decision bar close), replacing the current 1h close. | new field |
| `entry_time` (execution timestamp) | The **open** timestamp of the next eligible 15m candle `i+1`. In a contiguous series this equals `decision_time`, but it is a distinct field and may differ across data gaps. | new field |
| `fill_price` (actual entry) | `bars[i+1].open` — the executable market price. | new field |
| `intended_levels` | `stop_loss`, `take_profit_1`, `take_profit_2` as generated by `RiskManager` from `signal_price`. Unchanged by filling. | existing |
| `exit_time` | The **open** timestamp of the candle whose prices caused the exit (execution instant), for every exit type including time/end-of-data. | `replay_harness.py:202,224,234` |

**Rule T1:** decision timestamps are candle *closes*; execution timestamps (`entry_time`, `exit_time`) are candle *opens*. A record must never label a decision as an execution or vice versa.  
**Rule T2:** `entry_time >= decision_time` for contiguous data; `exit_time >= entry_time`; `holding = exit_time − entry_time >= 0` always.

### 3.2 Lifecycle (PD)

1. Evaluate signals only after candle `i` has fully closed, at `decision_time`.
2. **No management of candle `i`.** Its high/low occurred before the decision and must never be evaluated as if the trade were active (fixes BT-004, BT-006-at-entry, and both SL/TP "before entry" test scenarios).
3. Locate the **next eligible candle** `j = i + 1` in the filtered 15m series. Fill a market order at `bars[j].open`.
4. Management starts at `j` (the entry candle) and continues bar by bar. Price action within `j` *after* its open is legitimately manageable.
5. On each managed bar: (a) resolve any gap at the open (§5), then (b) apply the intra-bar ladder SL → TP1 → TP2 (§5.4).
6. If `j` does not exist or is ineligible (§3.4), emit `NO_FILL_MISSING_NEXT_BAR`; record signal fields only; **never** use `bars[i].close` or any older price as a fabricated fill.
7. Record `signal_time`, `entry_time`, `signal_price`, `fill_price`, `intended stop/TP`, `actual fill prices`, `exit_time`, and R separately.

### 3.3 Required field additions / changes (PD)

`SignalRecord` (`replay_harness.py:67-95`) and `_signal_to_dict` (`:98-118`):

- Add `signal_price: float` (geometry anchor; `crt_entry` retained as alias for checkpoint back-compat).
- Add `fill_price: Optional[float]` (actual execution price; P&L uses this, not `crt_entry`).
- Add `entry_time: Optional[datetime]` distinct from `signal_time`.
- Add `actual_stop_fill: Optional[float]`, `actual_tp_fill: Optional[float]` (or a per-leg fill list) so intended vs actual levels are both auditable.
- Add `equity_reference: float` and `execution_cost_usd: float` (§4.3).
- Add `execution_convention_version: str` (e.g. `"optionB-v1"`).
- `fill_time` is redefined as `entry_time`; `bars_held = exit_time − entry_time` expressed in 15m bars, clamped to `>= 0`.

Checkpoint JSON gains a provenance header (§8.2) and a schema version; readers of old checkpoints must either migrate explicitly or be rejected — never silently mixed.

### 3.4 Defined edge behaviour (PD / UQ)

| Case | Contract |
| :--- | :--- |
| Signal bar touches SL before entry | No trade management on the signal bar. Covered by regression test. |
| Signal bar touches TP before entry | No trade management on the signal bar. Covered by regression test. |
| Next candle opens normally | `fill_price = bars[j].open`; management begins at `j`. |
| Next candle opens beyond SL | Adverse gap fill at open (§5.1). |
| Next candle opens beyond TP | Favourable gap fill convention (§5.2). |
| Missing next candle | `NO_FILL_MISSING_NEXT_BAR`; no trade, no fabricated price. "Eligible" means the next bar in the calendar-filtered series; an expected weekend/maintenance gap is a legitimate next bar, but an unexplained hole *within market hours* must be flagged by the data-integrity layer (§8.1) — strictness is **U-6**. |
| Non-monotonic timestamps | Reject the dataset with an explicit error; do not silently sort. **U-5** covers the alternative. |
| Duplicate timestamps | Identical duplicates collapse; conflicting duplicates reject. |
| Forming candle | Reject any bar with `timestamp + 15m > as_of`. |

---

## 4. Execution cost model

### 4.1 Current implementation (verified)

`replay_harness.py:236-238`:

```python
net_price_pnl = booked_price_pnl - spread   # spread = 0.40, in PRICE units
r_mult = net_price_pnl / risk               # risk = |entry - sl|
```

- Deducted **once per completed trade**, at the end, in price units — not through individual execution events, not per TP leg.
- `spread` is configurable only via `--spread` (`smc_replay.py:822-826`) and duplicated as a constant in `smc_portfolio_2025.py:88` and in `SMC_FREEZE_V2.md:23` (whose line reference to `smc_replay.py:793` is stale — actual is `:822-826`).
- The freeze doc calls it a "round-trip" cost. There is **no slippage, commission, or bid/ask model**.

### 4.2 Why an equity-percentage cost is not currently computable (CD/EL)

The proposed formula `execution_cost = equity_at_entry × execution_cost_pct / 100` cannot be evaluated truthfully today:

1. `RiskManager` computes `account_balance=10000.0`, `risk_amount_usd`, and `suggested_lot_size` (`risk_manager.py:49-52,122-125`), but the replay **ignores all of them** and uses fixed 1R (`establish.md` §1.7/§1.9). There is no account state, no position notional, and no evolving equity.
2. The engine divides the dollar cost by `risk` (a **price** distance) to get R. A cost expressed as a fraction of *equity* is in **dollars**; converting it to price units requires a notional/lot-size assumption that does not exist. (Today this works only because `$0.40` is already treated as a price-unit quantity, not as a true dollar amount.)
3. If equity were allowed to evolve with realised R while risk stayed fixed at 1R, the cost as a fraction of risk would drift with equity — inconsistent with a fixed-risk R simulation.

**Conclusion:** the current engine cannot calculate a meaningful equity-based cost. Required minimum assumptions are listed as **U-4** in §11. Do not invent them.

### 4.3 Proposed cost convention (PD)

For **Baseline v1**, keep the existing assumption visible and add a reproducible, configurable percentage layer **without pretending equity evolves**:

- `execution_cost_pct` (config, default `0.004` ≡ `$0.40` on a `$10,000` reference) and `equity_reference_usd` (config, default `10000.0`, **constant — not a running balance**).
- `execution_cost_usd = equity_reference_usd × execution_cost_pct / 100`.
- Convert to the price-unit deduction by dividing by the instrument's USD-per-price-unit-per-notional factor. **U-4 must resolve this factor**; until then the implementation must keep the literal price-unit `spread` path and record `equity_reference_usd` only as metadata.
- Document explicitly: **round-trip, not per-leg**. Deduct once per trade at R calculation. No portfolio-level or per-leg deduction.
- Record on every trade: `equity_reference`, `execution_cost_pct`, `execution_cost_usd`, and the price-unit deduction used.
- Reports and the run manifest must print the cost assumption (`spread`, or the pct + reference pair) exactly as in `smc_replay.py:714` today.

### 4.4 Migration implications — dollar → percentage (shown, not silently converted)

Worked example using the frozen sample geometry from `establish.md` A.4 (`risk_price = 8.339`, TP ladder `0.5×2R + 0.5×3R = 2.5R`):

| Model | Cost input | Cost in price units | R drag | Net R |
| :--- | :--- | :--- | :--- | :--- |
| Current flat (baseline) | `$0.40` | 0.400 | 0.400 / 8.339 = **0.04797R** | 2.5 − 0.04797 = **2.452R** (matches checkpoint) |
| Proposed pct, const $10k ref | 0.004% of $10,000 | $0.40 → 0.400 (once conversion factor fixed) | 0.04797R | **2.452R** (identical by construction at $10k) |
| Proposed pct, 0.01% of $10k | $1.00 | 1.000 | 0.11992R | **2.380R** |
| Hypothetical running equity $11,000 at 0.004% | $0.44 | 0.440 | 0.05277R | **2.447R** — *not supported by current accounting; illustrative only* |

**Migration approach:** keep `$0.40` as the default round-trip assumption so Baseline v1 numbers differ from the old run *only* because of timing/gap fixes, not because of a silent cost change. Add `execution_cost_pct`/`equity_reference_usd` as explicit, versioned metadata and expose both in reports. Any change to the numeric cost must be a new experiment version with its own manifest, never an in-place conversion.

---

## 5. Stop-loss and take-profit gap-handling rules

### 5.1 Stop-loss adverse gap (PD)

If a managed candle opens beyond the stop:

- BUY: `actual_stop_fill = min(bar.open, stop_loss)`.
- SELL: `actual_stop_fill = max(bar.open, stop_loss)`.
- Record `intended_stop = stop_loss` and `actual_stop_fill` separately.
- Loss uses the actual fill: `pnl = (actual_stop_fill − fill_price)` for BUY, `(fill_price − actual_stop_fill)` for SELL.
- Never assume the original stop price when the open is worse.

### 5.2 Take-profit favourable gap (PD)

If a managed candle opens beyond a TP level, a limit order must not fill worse than its limit:

- BUY (sell-limit at TP): `actual_tp_fill = max(bar.open, tp)`.
- SELL (buy-limit at TP): `actual_tp_fill = min(bar.open, tp)`.
- Record intended TP and actual fill separately; book P&L from the actual fill.
- Special case: if the **entry candle** opens beyond TP2 (both rungs gap through at once), close the **entire** position at `bar.open` (one deterministic fill, no ladder re-entry), and label the exit accordingly. This avoids ambiguous partial fills at a single price.
- This is the "favourable gap should not produce an artificially worse fill than the limit" default requested by the task, and it also corrects the current code's under-crediting of favourable gaps (which fills at the exact limit).

### 5.3 Intrabar ambiguity (PD)

- If a candle touches both SL and TP (and no lower-timeframe data can order them), apply **SL-first** — conservative, deterministic, never the favourable outcome. This preserves the existing conservative rule (`replay_harness.py:195`) and `BT-042`.
- Applied on **every** managed bar including the entry bar.
- Same-bar TP1+TP2+SL: stop wins; TP1/TP2 are not booked. No randomness.

### 5.4 Numerical examples (regression golden values)

All examples use `fill_price = 100.00`, `stop = 99.00`, `risk = 1.00`, `tp1 = 102.00`, `tp2 = 103.00`, round-trip cost `$0.40` (price units), and a BUY trade.

| Scenario | Example | Correct result | Current (buggy) result |
| :--- | :--- | :--- | :--- |
| **Adverse SL gap** | Next candle opens `95.00` (through SL) | `actual_stop_fill = 95.00`; P&L `= 95−100 = −5.00`; net `−5.40`; **R = −5.4** | `−1.0 − 0.4 = −1.4R` (understates loss by 4R) |
| **Favourable TP1 gap** | Later candle opens `102.50` (through TP1, below TP2); TP2 later reached at `103.00` | TP1 leg `0.5×(102.5−100)=1.25`; TP2 leg `0.5×(103−100)=1.50`; gross `2.75`; net `2.35`; **R = +2.35** | TP1 filled at 102 → `1.0 + 1.5 − 0.4 = +2.1R` |
| **Favourable gap through both TPs at entry** | Entry candle opens `104.00` | Entire position closed at 104 → P&L `4.00`; net `3.60`; **R = +3.6** | ladder fills at exact 102/103 → `2.5 − 0.4 = +2.1R` |
| **Intrabar SL+TP** | Managed candle low `98`, high `104` | SL-first at stop (or gap-adjusted open); **≈ −1.4R or worse**, no TP booked | same SL-first result (conservative rule already correct — preserve) |
| **Cost, exact-once** | normal TP2, no gaps | `spread_paid = 0.40`, appears once in `r_multiple`; **R = +2.10** (2.5 − 0.4/1.0) | identical — verifies no regression / no double count |

---

## 6. Portfolio semantics — Baseline v1 (PD/EL)

- **Retain** the current capacity-filtered approach: `MAX_CONCURRENT=3`, `DAILY_LOSS_STOP=−3.0R` realised, one entry per `opportunity_key`, 1ATR/1h separation (`smc_portfolio_2025.py:80-85,237-296`).
- **Label results accurately:** "portfolio-constrained / capacity-filtered 1R trade set", **not** a fully capital-aware account simulator. No shared margin, lot sizing, compounding, or broker contract execution in this milestone.
- Corrected exit times/R from §3–§5 flow into the filter; controls must be re-simulated with the same corrected engine (`smc_portfolio_2025.py:423-453`) so real and control remain comparable.
- Replace the hard-coded verification gate (`EXPECTED_TRADES=688`, `EXPECTED_TOTAL_R=136.45`, `:92-95,596-604`) with a **versioned manifest**; do not edit the numbers silently.
- Do not add volume confirmation, change confluence thresholds, or touch strategy defaults (`SMC_FREEZE_V2.md` §1–2 remain frozen).

---

## 7. Regression test plan

New hermetic test files: `server/tests/test_smc_replay_engine.py`, `test_data_loader_validation.py`, `test_replay_metrics.py`, `test_smc_portfolio_rules.py`. Use the `conftest.py` guards (in-memory SQLite, XAU-only, no Neon). Tests must fail on old behaviour and pass on corrected behaviour.

### 7.1 Execution scenarios (required table, extended)

| # | Scenario | Expected behaviour |
| :--: | :--- | :--- |
| 1 | Signal candle touches SL before entry | No management on signal candle; no stop-out. |
| 2 | Signal candle touches TP before entry | No management on signal candle; no TP booked. |
| 3 | Next candle opens normally | `fill_price = bars[j].open`; management begins at `j`. |
| 4 | Next candle opens beyond SL | Adverse gap: fill at open; `R = −5.4` (§5.4). |
| 5 | Next candle opens beyond TP | Favourable gap: `R = +2.35` / `+3.6` per §5.4. |
| 6 | Candle touches both SL and TP | Deterministic SL-first; conservative; no favourable selection. |
| 7 | Missing next candle | `NO_FILL_MISSING_NEXT_BAR`; no fabricated entry. |
| 8 | Non-monotonic timestamps | Reject with explicit error (U-5). |
| 9 | Execution cost | Deducted exactly once; `spread_paid = 0.40`; no portfolio/metrics re-deduction. |
| 10 | Trade timestamps | `signal_time` (close) ≠ `entry_time` (open) as distinct fields; both recorded. |
| 11 | Holding duration | `exit_time >= entry_time`; `bars_held >= 0` for every trade (no −0.2h). |
| 12 | Replay restart / determinism | Two runs on same fixture → byte-identical records/checkpoints. |
| 13 | Same-bar SL+TP ladder (entry bar) | SL-first, no TP1/TP2 booked (BT-042 preserved). |
| 14 | Limit fill-then-stop (BT-002) | Filled then `STOP_LOSS ≈ −1R` — fix shared loop. |
| 15 | Prefix invariance | Truncate at `T` vs pad future bars → identical output up to `T`. |
| 16 | Forming bar | `timestamp + 15m > as_of` excluded. |
| 17 | Gate characterization (N-03/N-04) | Accepted setups may violate floors; `FATAL_CONFLICT` unreachable — lock current behaviour, do not change. |

### 7.2 Data-integrity tests

- OHLC validity: `high >= max(open, close)`, `low <= min(open, close)`, `high >= low`, positive prices.
- Duplicate timestamps: identical collapsed; conflicting rejected.
- Source filter `twelvedata`; calendar filter (Fri 17:00 → Sun 18:00 NY; daily 17:00–18:00).
- Monotonic timestamps; snapshot hash/row-count match to manifest.
- `split_of` boundary consistency between `smc_replay.py:95-101` (`<= b1`) and `replay_harness.py:310-316` (`< b1`) — unify or document (N-10).

### 7.3 Metrics / portfolio tests

- Golden R sequence → identical win rate, avg/median R, PF, total R, exit-ordered DD across producers.
- BE definition (`r <= 0`) documented or separated; PF with zero losses.
- Day-cluster bootstrap deterministic with fixed seed; CI wider than IID on clustered synthetic data.
- Portfolio: dedupe, `MAX_CONCURRENT=3`, separation, daily stop, no-fill records don't crash, versioned verification gate.

---

## 8. Data integrity, checkpoints, and reproducibility

### 8.1 Loader requirements (PD)

Add to `load_full_15m_candles` (`replay_harness.py:250-300`): OHLC validity checks; monotonic-time assertion; conflicting-duplicate rejection; forming-bar exclusion (`timestamp + 15m <= as_of`); retain source and calendar filters. Keep the `meta` dictionary but compute raw range labels before/after the calendar filter distinctly (N-30).

### 8.2 Checkpoint provenance (PD)

Every checkpoint gains a header: `schema_version`, `execution_convention_version`, `engine_commit`, `data_sha256`, `strategy_config_hash`, `execution_config_hash`, `split_id`, `created_utc`. Resume (`smc_replay.py:934-999`) must reject mismatches instead of reusing silently; cached chunks must reproduce gap counters (N-11).

### 8.3 Run manifest (PD) — required fields

```yaml
baseline_id: smc-baseline-v1
engine_commit: <git sha>                  # code version
created_utc: <timestamp>                  # report generation timestamp
data:
  path: backtest.db
  sha256: <hash>                          # data snapshot identifier/hash
  symbol: XAU/USD
  source: twelvedata
  timeframe: 15m                          # timeframe
  raw_rows: <n>
  open_market_rows: <n>
  first_bar_open_utc: <ts>
  last_bar_open_utc: <ts>
strategy:
  config_hash: <hash>                     # strategy configuration hash
  frozen_commit: 87509a4...
execution:
  convention_version: optionB-v1         # execution convention version
  config_hash: <hash>                     # execution configuration hash
  entry_price_convention: <U-2 decision>
  fill_timing: next_15m_open
  gap_fill: adverse_open / favourable_limit_or_better
  sl_intrabar: sl_first
  cost_usd_roundtrip: 0.40
  cost_pct: 0.004
  equity_reference_usd: 10000.0
  cost_basis: round_trip
splits:
  calibration: [...]
  validation: [...]
  test: [...]
  holdout_after: <ts>
metrics:
  drawdown_basis: exit_time
  breakeven_definition: <loss | separate>
  bootstrap: day_cluster
  seed: <seed>
artifacts:
  checkpoints: reports/smc_baseline_v1/checkpoints/
  report: reports/smc_baseline_v1/report.md
```

### 8.4 Versioned outputs (PD)

- All corrected artifacts go to **`reports/smc_baseline_v1/`** (and a sibling versioned checkpoint directory). **Never overwrite** `reports/exp_2025_smc*`, `reports/smc_replay_extended/`, `reports/smc_analysis_v2/`, or any historical checkpoint.
- Pin the data snapshot (N-14). The current DB extends past the freeze's "clean holdout" start of 2026-11-15 15:00 (`SMC_FREEZE_V2.md:50`, A.2); that window is no longer clean and must be declared as such.

---

## 9. Migration impact on historical reports (PD/EL)

| Artifact | Why invalid / affected | Action |
| :--- | :--- | :--- |
| `reports/exp_2025_smc_portfolio/report.md` | Headline **249 trades, +0.2059R, PF 1.42, max DD 22.45R**, controls FAIL (34.5%/84.8% vs 97.5%). Produced by simulator with BT-004/BT-006/BT-039, older snapshot, older labels. | Treat as **provisional**. Regenerate into `reports/smc_baseline_v1/`; record pre/post deltas. |
| `reports/exp_2025_smc_portfolio/{funnel,controls,equity_curve,trades}.csv` | Same R values / exit labels. | Regenerate versioned. |
| `reports/exp_2025_smc/checkpoints/*.json` (23) | Pre-entry-bar management, no provenance, old snapshot. | Supersede with versioned checkpoints; keep originals. |
| `reports/smc_replay_extended/{report.md,funnel.csv,counterfactual.csv,checkpoints/}` | Same defects; counterfactuals inherit bias (N-13). | Regenerate versioned. |
| `reports/smc_analysis_v2/stepC1_entries_per_day.md` | **−0.2h** min holding (`:61`), `TIMEOUT_MARK_TO_MARKET` labels (`:68,73`), `$100` executability section (`:90-120`) rests on old sizing assumptions. | Regenerate/relabel; keep original. |
| `reports/smc_analysis_v2/stepC2…C6` | Re-simulate candidates/controls with the same biased engine; limit-zone candidates affected by BT-002 (N-25). | Re-run only after Phase 1; keep market vs limit sections separate. |
| `reports/smc_replay_regime_filter/*`, smoke/baseline_cal reports | Derived from old checkpoints. | Regenerate only if the regime-filter path is retained. |
| `docs/SMC_FREEZE_V2.md` | `$0.40` line reference stale (`:23`); holdout boundary nowPast; audit register not in repo. | Update references; add manifest pointer; commit BT register (Phase 5). |

**Expected direction of change (not a prediction of profit):** removal of impossible pre-entry exits will change R on trades whose signal bar had an adverse wick; adverse gap fills will worsen stopped trades; favourable gap fills will improve gapped TP trades; consistent timestamps will eliminate negative holding. Net R may move either way — this is a truthfulness change, not an optimisation.

---

## 10. Ordered implementation phases

| Phase | Scope | Gate |
| :--: | :--- | :--- |
| **0 — Approve decisions** | Resolve §11 U-1…U-8 with a human owner. Freeze the execution contract and cost/gap policy. | Written approval recorded in the manifest. |
| **1 — Execution correctness** | Implement §3–§5 in `replay_harness.py` (`simulate_outcome`, loader) and `smc_replay.py` (`replay_chunk` fill at `j`, field additions). Fix BT-002 in same loop. Add §7.1/§7.2 tests first. | All execution probes pass; no strategy file changed; no artefact regenerated. |
| **2 — Accounting & labels** | Portfolio label change, versioned verification gate, time semantics, no-fill handling, monetary claim relabel (EL). Keep cost pct metadata-only until U-4 resolved. | Ex-post filter labelled truthfully; no negative holdings; single cost deduction. |
| **3 — Metrics & provenance** | Single metrics module, day-cluster bootstrap, split unification, checkpoint manifest, resume rejection (BT-020/025/N-05/N-10/N-20). | Golden metrics identical across producers; artifacts traceable. |
| **4 — Regression suite green** | Complete §7 test files; triage the prior 5 failing tests (N-28). | `python -m pytest tests/` green; targeted canonical tests green; hermetic guards intact. |
| **5 — Baseline regeneration** | Pin snapshot; write `reports/smc_baseline_v1/` with manifest; re-run controls on corrected engine; one-shot holdout with clean labelling; docs update. | Clean checkout + pinned snapshot reproduces every published number; controls determine whether an edge claim is allowed. |

Phase 1 is a hard blocker: no R metric may be cited before it passes. Phase 5 is the only phase that writes reports/checkpoints.

---

## 11. Risks and unresolved decisions requiring human approval

| ID | Class | Decision | Why it matters | Options | Recommended default | Blocks |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **U-1** | **UQ** | **Option B vs `establish.md` R2.** Task Option B keeps 15m decision frequency and fills at the next 15m open; R2 recommended evaluating only at 1h closes to align with the 1h-close price. These are different contracts. | Determines evaluation cadence, funnel counts, and the dedup set. | (a) Adopt Option B (task-authoritative) and record the delta from R2; (b) revert to 1h-close evaluation; (c) run both as separate labelled variants. | **(a)** — Option B is the task's explicit instruction; document that it supersedes R2 for Baseline v1. | Phase 0 |
| **U-2** | **UQ** | **Signal-price source for geometry.** Current `signal_price` is the 1h close (`indicator_service.py:177-178`). Option B implies the decision-bar (15m) close. Changing it affects frozen geometry. | "Signal price vs actual entry price" must be recorded separately; which anchor builds SL/TP changes R. | (a) use decision-bar 15m close; (b) keep 1h close and document divergence; (c) re-anchor to fill price (changes geometry). | **(a)** for replay only, *if* approved as an execution-convention clarification; otherwise (b). Do not change the production scanner. | Phase 1 |
| **U-3** | **UQ** | **R denominator under gaps.** Use planned risk `|signal_price − SL|` (keeps R comparable) or actual risk `|fill_price − SL|` (reflects real exposure at fill)? | Changes every R figure after a gap fill. | (a) planned risk; (b) actual risk; (c) both reported. | **(a)** planned risk, with actual fill prices recorded separately; document. | Phase 1 |
| **U-4** | **UQ** | **Equity-based cost accounting.** Need: what `equity_at_entry` is; whether it evolves; the USD-per-price-unit/notional conversion factor; and pct-vs-dollar equivalence. | Without these, `equity × pct` is not computable and any conversion would be invented. | (a) keep flat `$0.40` for v1, add pct+reference metadata only; (b) define fixed $10k reference and a conversion factor, no compounding; (c) full account simulator (out of scope). | **(a)** for Baseline v1; open a separate accounting milestone for (b)/(c). | Phase 2 |
| **U-5** | **UQ** | **Non-monotonic input:** reject or sort-and-handle? | Silent sorting can hide data corruption. | (a) reject; (b) sort + flag. | **(a) reject.** | Phase 1 |
| **U-6** | **UQ** | **"Next eligible candle" across expected market closures vs unexplained holes.** | Affects whether weekend-gap fills are allowed and how missing data is flagged. | (a) next bar in filtered series is eligible; flag only intra-session holes; (b) require contiguous 15m slot. | **(a)** with explicit data-integrity flagging. | Phase 1 |
| **U-7** | **UQ** | **Which artifact is "Baseline v1" headline?** 2025 portfolio window vs full-range funnel. | Prevent mixing windows/populations. | (a) 2025 portfolio headline + full-range context; (b) both equal; (c) full-range only. | **(a)**, per `establish.md` R1. | Phase 5 |
| **U-8** | **UQ** | **Verification gate after correction.** `688`/`+136.45` will fail. | Blocks regeneration. | (a) versioned manifest; (b) delete; (c) manual bump. | **(a)** versioned manifest. | Phase 2/5 |

### Additional risks (no decision required, but track)

- **Risk of appearing validated:** the current controls already FAIL; a corrected simulator does not create an edge. Any edge claim still requires cluster-robust inference and a clean one-shot holdout (Phase 5).
- **Strategy freeze:** U-2/U-3 must be framed as execution-convention clarifications, not strategy parameter changes. If a fix appears to require touching `smc_strategy.py`, `evaluators.py`, structure/liquidity/indicator rules, TP1=2R/TP2=3R, 50% TP1, BE, or the 500-bar hold — **stop and escalate**.
- **Historical report integrity:** do not overwrite or hand-edit any existing report or checkpoint. All corrected outputs are versioned.
- **Read-only milestone:** this document deliberately ran no backtest and no DB probe; all numbers here are from static inspection and `establish.md`'s recorded probes. They are planning estimates, not new results.

---

## 12. Integrity statement

This investigation read source, docs, tests, and existing reports; inspected the working tree; and wrote only this new proposal file. It did **not** modify source, tests, configuration, database contents, reports, or checkpoints; did **not** run `smc_replay.py`, `smc_portfolio*.py`, or any `run_step*.py`; did **not** run a full pytest suite (prior status per `establish.md`: 270 passed / 5 failed); and did **not** overwrite historical artifacts. The pre-existing `package.json` modification was left untouched. All line numbers were read from the current checkout at the HEAD recorded above.
