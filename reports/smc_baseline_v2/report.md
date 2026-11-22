# SMC — Real (Portfolio-Constrained) Backtest, 2025-01-01 → Latest

**Scope**: the already-produced SMC replay in `reports/exp_2025_smc/checkpoints` replayed through the frozen portfolio rules only. No threshold, score, gate or default was changed; SMC is frozen per `docs/SMC_FREEZE_V2.md`.

**Window**: 2025-01-01 00:00 → 2026-11-19 05:30 UTC (decision times). This is the last **open-market** bar: the database's closed-market placeholder bars (Friday 22:00 → Sunday 22:00 UTC) are filtered out at load time, so the raw table extends to 2026-11-15 15:00 but the analysable window ends on the Friday close.

**Input verification** (must hold before any metric is reported):

| Check | Expected | Observed | Result |
| :--- | ---: | ---: | :--- |
| Distinct trades (one per `opportunity_key`) | 735 | 735 | PASS |
| Voided entries (excluded) | 42 | 42 | PASS |
| Unconstrained total R | +157.9203 | +157.9203 | PASS |
| Re-simulated R == checkpoint R | 0 mismatches | 0 | PASS |

Data: `backtest.db` opened read-only (`mode=ro`), Twelve Data 15m bars, open-market bars only. The flat 0.40 price-unit-per-position-unit round-trip execution cost is already inside every checkpoint `r_multiple`; controls re-use the same convention through the shared `simulate_outcome` engine.

---

## 1. Portfolio funnel (frozen rules, decision-time order)

| Funnel Stage | Count | Notes |
| :--- | ---: | :--- |
| Raw accepted signals (15m bars) | 2,701 | Every accepted 15m bar in the window |
| Skipped: repeat sweep (`ONE_ENTRY_PER_SWEEP`) | 1,966 | Later 15m bars from the same opportunity_key |
| Distinct opportunities (input to rules) | 735 | ONE_ENTRY_PER_SWEEP applied |
| Skipped: concurrency cap (`MAX_CONCURRENT=3`) | 463 | MAX_CONCURRENT=3 already open |
| Skipped: separation rule (`MIN_ENTRY_SEPARATION`) | 2 | < 1 ATR and < 1h from an open same-direction entry |
| Skipped: daily loss stop (`DAILY_LOSS_STOP=-3.0R`) | 12 | Day already at or below -3.0 R realized |
| Skipped: unfilled limit-zone order | 0 | n/a — all entries are market fills |
| **Portfolio entered trades** | 258 | Capacity-filtered 1R entries; 0.40 price units/position round trip |

Rule attribution order is daily stop → concurrency → separation (frozen implementation). The accepted set is invariant to that order; only the attribution of a multi-cause skip moves.

### Funnel by half-year

| Period | Accepted bars | Repeat sweep | Distinct | Concurrency | Separation | Daily stop | Entered |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025-H1 | 626 | 459 | 167 | 107 | 1 | 0 | 59 |
| 2025-H2 | 762 | 555 | 207 | 131 | 0 | 4 | 72 |
| 2026-H1 | 743 | 539 | 204 | 124 | 0 | 7 | 73 |
| 2026-H2 | 570 | 413 | 157 | 101 | 1 | 1 | 54 |
| **Total** | 2,701 | 1,966 | 735 | 463 | 2 | 12 | 258 |

---

## 2. Constrained performance: whole window and by half-year

Trades are assigned to a half-year by **decision time**; within each group the equity curve, drawdown and exit ordering use **exit time**, not entry time. Holding time in *market bars* counts open-market 15m bars held; wall-clock hours run from decision time to the exit bar's open time (the checkpoint's `exit_time`).

| Period | Trades | Win rate | Avg R | Median R | Profit factor | Total R | Max DD (R) | Longest DD | Hold med (bars / h) | Hold p90 (bars / h) | Flag |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- | :--- | :--- |
| **Whole window** | 258 | 48.8% | +0.2547 | -0.2253 | 1.52 | +65.71 | 20.77 | 220.3 d (89 trades, open) | 312 / 124.4 | 499 / 178.8 |  |
| 2025-H1 | 59 | 45.8% | +0.2177 | -0.2543 | 1.47 | +12.84 | 8.15 | 62.6 d (20 trades, open) | 428 / 160.0 | 499 / 179.0 |  |
| 2025-H2 | 72 | 62.5% | +0.5897 | +0.7984 | 2.64 | +42.46 | 6.97 | 63.7 d (28 trades) | 303 / 122.8 | 499 / 178.8 |  |
| 2026-H1 | 73 | 38.4% | +0.0040 | -1.0007 | 1.01 | +0.29 | 20.77 | 79.6 d (35 trades, open) | 156 / 69.5 | 499 / 177.8 |  |
| 2026-H2 | 54 | 48.1% | +0.1873 | -0.3973 | 1.38 | +10.11 | 8.29 | 73.8 d (27 trades) | 348 / 139.0 | 499 / 178.8 |  |

Max drawdown is peak-to-trough on the cumulative-R curve ordered by exit time. Longest drawdown is the wall-clock time from the equity peak to the first exit that regains it (or to the last exit if it never does); a duration marked `open` had not been recovered by the window end.

### Exit-reason breakdown

| Exit reason | Whole window | Share | Avg R | 2025-H1 | 2025-H2 | 2026-H1 | 2026-H2 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `STOP_LOSS` | 114 | 44.2% | -1.0237 | 23 | 22 | 44 | 25 |
| `TIME_EXPIRY` | 85 | 32.9% | +0.7820 | 25 | 28 | 14 | 18 |
| `TP2` | 39 | 15.1% | +2.4946 | 6 | 16 | 10 | 7 |
| `TP1_BE_STOP` | 17 | 6.6% | +0.9440 | 5 | 6 | 5 | 1 |
| `END_OF_DATA` | 3 | 1.2% | +0.8680 | 0 | 0 | 0 | 3 |

### Concurrency exposure

Time-weighted over wall-clock time inside each window (closed-market hours included).

| Period | Window hours | Max concurrent | Mean concurrent | % time 0 open | % time 1 open | % time 2 open | % time 3 open |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Whole window** | 16,494 | 3 | 1.70 | 24.7% | 20.3% | 14.9% | 40.0% |
| 2025-H1 | 4,344 | 3 | 1.83 | 19.3% | 20.7% | 17.8% | 42.1% |
| 2025-H2 | 4,416 | 3 | 1.90 | 19.3% | 18.2% | 16.2% | 46.3% |
| 2026-H1 | 4,344 | 3 | 1.40 | 37.1% | 21.4% | 5.9% | 35.6% |
| 2026-H2 | 3,390 | 3 | 1.68 | 22.9% | 21.2% | 21.1% | 34.8% |

---

## 3. Direction split (constrained and unconstrained)

Unconstrained = the 735 de-duplicated opportunities with no portfolio rules. Constrained = the 258 trades that survived the rules. This is a capacity-filtered 1R trade set, not a capital-aware account simulation.

### Unconstrained

| Direction | Trades | Share | Win rate | Avg R | Median R | Profit factor | Total R | Max DD (R) | Flag |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| BUY | 487 | 66.3% | 52.6% | +0.3166 | +0.1221 | 1.72 | +154.20 | 40.53 |  |
| SELL | 248 | 33.7% | 39.1% | +0.0150 | -0.9999 | 1.03 | +3.72 | 64.29 |  |

### Constrained

| Direction | Trades | Share | Win rate | Avg R | Median R | Profit factor | Total R | Max DD (R) | Flag |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| BUY | 162 | 62.8% | 53.1% | +0.3561 | +0.1507 | 1.83 | +57.69 | 15.69 |  |
| SELL | 96 | 37.2% | 41.7% | +0.0836 | -0.9972 | 1.14 | +8.02 | 9.52 |  |

The user-supplied unconstrained figures were BUY +0.316R (456 trades) vs SELL -0.033R (232 trades). Measured here: BUY 487 trades, +0.3166; SELL 248 trades, +0.0150. Corrected — see numbers above.

---

## 4. Controls on the same constrained entries

Controls reuse the exact same entry timestamps, stop distances, TP ladder (mirrored to the opposite side) and the flat 0.40 price-unit-per-position-unit round-trip cost. Two random-direction controls are reported, both over seeds `1..1000`:

1. **50/50 coin** — each entry independently assigned BUY/SELL.
2. **Ratio-preserving shuffle** — the period's BUY/SELL count ratio is kept exactly, only the assignment is shuffled (the pre-registered C2 control).

If a mirrored control direction would void at entry under the Option B contract, it contributes 0R (no position exists). Voided baseline entries are excluded from both the real and control populations.

Percentile rank = share of the 1,000 random means at or below the real mean R. The pass rule is **percentile ≥ 97.5 on BOTH later half-years** (validation = 2026-H1, test = 2026-H2).

| Period | n | Real mean R | Always-BUY | Always-SELL | Coin mean ± sd | Coin pct | Shuffle mean ± sd | Shuffle pct | Flag |
| :--- | ---: | ---: | ---: | ---: | :---: | ---: | :---: | ---: | :--- |
| **Whole window** | 258 | +0.2547 | +0.2023 | -0.1545 | +0.0226 ± 0.0717 | 99.9% | +0.0749 ± 0.0673 | 99.5% |  |
| 2025-H1 | 59 | +0.2177 | +0.2188 | -0.3448 | -0.0651 ± 0.1505 | 97.0% | -0.0226 ± 0.1432 | 96.0% |  |
| 2025-H2 | 72 | +0.5897 | +0.6527 | -0.4196 | +0.1056 ± 0.1426 | 99.8% | +0.4053 ± 0.1062 | 95.2% |  |
| 2026-H1 | 73 | +0.0040 | -0.0500 | -0.0432 | -0.0450 ± 0.1357 | 63.9% | -0.0465 ± 0.1357 | 63.6% |  |
| 2026-H2 | 54 | +0.1873 | -0.0750 | +0.2562 | +0.0927 ± 0.1633 | 73.3% | +0.0555 ± 0.1563 | 80.0% |  |

### Half-year control detail (5%–95% bands and always-BUY/SELL win rates)

| Period | n | Real mean R (WR) | Always-BUY mean R (WR) | Always-SELL mean R (WR) | Coin 5–95% | Shuffle 5–95% |
| :--- | ---: | :--- | :--- | :--- | :---: | :---: |
| 2025-H1 | 59 | +0.2177 (45.8%) | +0.2188 (47.5%) | -0.3448 (32.2%) | [-0.3083, +0.1848] | [-0.2539, +0.2019] |
| 2025-H2 | 72 | +0.5897 (62.5%) | +0.6527 (61.1%) | -0.4196 (25.0%) | [-0.1246, +0.3404] | [+0.2389, +0.5863] |
| 2026-H1 | 73 | +0.0040 (38.4%) | -0.0500 (38.4%) | -0.0432 (32.9%) | [-0.2578, +0.1693] | [-0.2661, +0.1670] |
| 2026-H2 | 54 | +0.1873 (48.1%) | -0.0750 (40.7%) | +0.2562 (50.0%) | [-0.1744, +0.3650] | [-0.2102, +0.3068] |

### Pass/fail verdict

| Control | Validation 2026-H1 | Test 2026-H2 | Both ≥ 97.5%? |
| :--- | ---: | ---: | :--- |
| Ratio-preserving shuffle (pre-registered) | 63.6% | 80.0% | **FAIL** |
| 50/50 random direction | 63.9% | 73.3% | **FAIL** |

**Verdict: FAIL.** Under the pre-registered ratio-preserving control the real mean R must beat 97.5% of random direction assignments in both 2026-H1 and 2026-H2; it reaches 63.6% and 80.0% respectively. The 50/50 coin control also fails.

### Secondary: controls under the frozen walk-forward split labels

The checkpoint `split` field follows `docs/SMC_FREEZE_V2.md` (calibration ends 2025-05-21 08:15 UTC, validation ends 2026-02-16 03:00 UTC). These windows are wider than the half-years and are shown only for continuity with earlier reports.

| Split | n | Real mean R | Always-BUY | Always-SELL | Coin pct | Shuffle pct |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| calibration | 46 | +0.3518 | +0.2650 | -0.4061 | 99.0% | 97.7% |
| validation | 109 | +0.3970 | +0.5289 | -0.4448 | 100.0% | 98.6% |
| test | 103 | +0.0608 | -0.1712 | +0.2650 | 57.7% | 63.5% |

---

## 5. Honest limits — what this backtest cannot show

1. **Not clean out-of-sample.** 2025-01-01 onward overlaps data that was already observed while SMC was developed and tuned (see the parameter history and the contamination table in `docs/SMC_FREEZE_V2.md`). The only strictly unseen window begins after 2026-11-15 15:00 UTC. This report is a re-analysis of already-seen data, not a validation of the frozen strategy.
2. **Single instrument, single source.** One symbol (XAU/USD), one vendor (Twelve Data), 15m bars; HTFs are resampled, not independent data. Survivorship or vendor-specific bar construction cannot be ruled out.
3. **Small validation/test halves.** 2026-H1 carries 73 constrained trades and 2026-H2 carries 54. A 97.5% percentile threshold on ~50–70 trades has wide sampling error, and any half-year with n<30 is flagged descriptive-only above.
4. **Simulation, not execution.** Under the Option B contract, entry fills at the next 15m open, in-trade gaps fill at executable prices, same-bar ambiguity resolves stop-first, and SL/TP levels stay fixed after signal generation. 50% is booked at TP1 with break-even stop; residual positions close at the 500-bar limit or end of data. Cost is a flat 0.40 price units per position unit round trip. This is a capacity-filtered 1R simulation: shared capital, margin, compounding, weekend financing, broker lot sizes and news voids are not modelled.
5. **Rule interpretation.** `MIN_ENTRY_SEPARATION` is implemented exactly as the frozen code (skip if *any* open same-direction entry is both <1h and <1 ATR away). The alternative reading — a global 1h escape after the last same-direction entry — was not silently substituted; it is noted here because it changes the separation skip count (2 under the frozen reading).
6. **Concurrency dominates the funnel.** The gap between 735 unconstrained and the constrained set is almost entirely the 3-slot cap, not the strategy signal count. Holding times are long (median 312 market bars), so the portfolio is capacity-bound; results say as much about the cap as about the edge.
7. **Direction asymmetry is confounded with drift.** Always-BUY beats Always-SELL in 2025-H1 (+0.204 vs -0.248) and 2025-H2 (+0.770 vs -0.533), consistent with gold's upward drift, but the ordering reverses in 2026-H1 (-0.073 vs +0.011) and 2026-H2 (-0.148 vs +0.351). The real strategy trails Always-BUY in 2025-H2 and leads it in 2026-H2. The BUY/SELL split therefore describes this window's drift and regime, not a stable directional edge.
8. **No tuning was performed.** Nothing was optimised on this window: the funnel, metrics and controls are deterministic given the checkpoints, the read-only candles and seeds 1..1000.

---

Generated by `server/scripts/smc_portfolio_2025.py` (23 checkpoint files, 1,000 seeds; run at 2026-11-22 09:31 UTC).
