# SMC — Real (Portfolio-Constrained) Backtest, 2025-01-01 → Latest

**Scope**: the already-produced SMC replay in `reports/exp_2025_smc/checkpoints` replayed through the frozen portfolio rules only. No threshold, score, gate or default was changed; SMC is frozen per `docs/SMC_FREEZE_V2.md`.

**Window**: 2025-01-01 00:00 → 2026-11-19 05:30 UTC (decision times). This is the last **open-market** bar: the database's closed-market placeholder bars (Friday 22:00 → Sunday 22:00 UTC) are filtered out at load time, so the raw table extends to 2026-11-15 15:00 but the analysable window ends on the Friday close.

**Input verification** (must hold before any metric is reported):

| Check | Expected | Observed | Result |
| :--- | ---: | ---: | :--- |
| Distinct trades (one per `opportunity_key`) | 695 | 695 | PASS |
| Voided entries (excluded) | 42 | 42 | PASS |
| Unconstrained total R | +136.4979 | +136.4979 | PASS |
| Re-simulated R == checkpoint R | 0 mismatches | 0 | PASS |

Data: `backtest.db` opened read-only (`mode=ro`), Twelve Data 15m bars, open-market bars only. The flat 0.40 price-unit-per-position-unit round-trip execution cost is already inside every checkpoint `r_multiple`; controls re-use the same convention through the shared `simulate_outcome` engine.

---

## 1. Portfolio funnel (frozen rules, decision-time order)

| Funnel Stage | Count | Notes |
| :--- | ---: | :--- |
| Raw accepted signals (15m bars) | 2,673 | Every accepted 15m bar in the window |
| Skipped: repeat sweep (`ONE_ENTRY_PER_SWEEP`) | 1,978 | Later 15m bars from the same opportunity_key |
| Distinct opportunities (input to rules) | 695 | ONE_ENTRY_PER_SWEEP applied |
| Skipped: concurrency cap (`MAX_CONCURRENT=3`) | 434 | MAX_CONCURRENT=3 already open |
| Skipped: separation rule (`MIN_ENTRY_SEPARATION`) | 2 | < 1 ATR and < 1h from an open same-direction entry |
| Skipped: daily loss stop (`DAILY_LOSS_STOP=-3.0R`) | 10 | Day already at or below -3.0 R realized |
| Skipped: unfilled limit-zone order | 0 | n/a — all entries are market fills |
| **Portfolio entered trades** | 249 | Capacity-filtered 1R entries; 0.40 price units/position round trip |

Rule attribution order is daily stop → concurrency → separation (frozen implementation). The accepted set is invariant to that order; only the attribution of a multi-cause skip moves.

### Funnel by half-year

| Period | Accepted bars | Repeat sweep | Distinct | Concurrency | Separation | Daily stop | Entered |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025-H1 | 627 | 465 | 162 | 103 | 1 | 0 | 58 |
| 2025-H2 | 739 | 548 | 191 | 120 | 0 | 4 | 67 |
| 2026-H1 | 738 | 545 | 193 | 115 | 0 | 5 | 73 |
| 2026-H2 | 569 | 420 | 149 | 96 | 1 | 1 | 51 |
| **Total** | 2,673 | 1,978 | 695 | 434 | 2 | 10 | 249 |

---

## 2. Constrained performance: whole window and by half-year

Trades are assigned to a half-year by **decision time**; within each group the equity curve, drawdown and exit ordering use **exit time**, not entry time. Holding time in *market bars* counts open-market 15m bars held; wall-clock hours run from decision time to the exit bar's open time (the checkpoint's `exit_time`).

| Period | Trades | Win rate | Avg R | Median R | Profit factor | Total R | Max DD (R) | Longest DD | Hold med (bars / h) | Hold p90 (bars / h) | Flag |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- | :--- | :--- |
| **Whole window** | 249 | 46.6% | +0.2092 | -0.3611 | 1.42 | +52.10 | 23.72 | 220.3 d (87 trades, open) | 323 / 133.5 | 499 / 178.8 |  |
| 2025-H1 | 58 | 46.6% | +0.2387 | -0.2253 | 1.53 | +13.85 | 8.15 | 62.6 d (20 trades, open) | 420 / 159.8 | 499 / 179.0 |  |
| 2025-H2 | 67 | 59.7% | +0.5528 | +0.6196 | 2.47 | +37.04 | 8.69 | 64.5 d (26 trades) | 369 / 144.2 | 499 / 178.8 |  |
| 2026-H1 | 73 | 34.2% | -0.1060 | -1.0012 | 0.84 | -7.74 | 20.77 | 79.6 d (36 trades, open) | 154 / 68.0 | 499 / 177.8 |  |
| 2026-H2 | 51 | 47.1% | +0.1756 | -0.4335 | 1.35 | +8.96 | 8.29 | 75.4 d (26 trades) | 378 / 146.5 | 499 / 178.8 |  |

Max drawdown is peak-to-trough on the cumulative-R curve ordered by exit time. Longest drawdown is the wall-clock time from the equity peak to the first exit that regains it (or to the last exit if it never does); a duration marked `open` had not been recovered by the window end.

### Exit-reason breakdown

| Exit reason | Whole window | Share | Avg R | 2025-H1 | 2025-H2 | 2026-H1 | 2026-H2 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `STOP_LOSS` | 114 | 45.8% | -1.0173 | 23 | 21 | 46 | 24 |
| `TIME_EXPIRY` | 83 | 33.3% | +0.7636 | 24 | 28 | 15 | 16 |
| `TP2` | 35 | 14.1% | +2.5061 | 6 | 15 | 7 | 7 |
| `TP1_BE_STOP` | 14 | 5.6% | +0.9919 | 5 | 3 | 5 | 1 |
| `END_OF_DATA` | 3 | 1.2% | +1.0347 | 0 | 0 | 0 | 3 |

### Concurrency exposure

Time-weighted over wall-clock time inside each window (closed-market hours included).

| Period | Window hours | Max concurrent | Mean concurrent | % time 0 open | % time 1 open | % time 2 open | % time 3 open |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Whole window** | 16,494 | 3 | 1.66 | 26.3% | 20.3% | 14.2% | 39.2% |
| 2025-H1 | 4,344 | 3 | 1.78 | 19.5% | 23.0% | 17.5% | 40.0% |
| 2025-H2 | 4,416 | 3 | 1.86 | 20.7% | 16.8% | 18.1% | 44.4% |
| 2026-H1 | 4,344 | 3 | 1.37 | 39.1% | 19.8% | 6.5% | 34.6% |
| 2026-H2 | 3,390 | 3 | 1.64 | 25.8% | 21.9% | 14.9% | 37.4% |

---

## 3. Direction split (constrained and unconstrained)

Unconstrained = the 695 de-duplicated opportunities with no portfolio rules. Constrained = the 249 trades that survived the rules. This is a capacity-filtered 1R trade set, not a capital-aware account simulation.

### Unconstrained

| Direction | Trades | Share | Win rate | Avg R | Median R | Profit factor | Total R | Max DD (R) | Flag |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| BUY | 462 | 66.5% | 51.7% | +0.3044 | +0.0951 | 1.69 | +140.63 | 38.55 |  |
| SELL | 233 | 33.5% | 37.3% | -0.0177 | -1.0007 | 0.97 | -4.13 | 64.72 |  |

### Constrained

| Direction | Trades | Share | Win rate | Avg R | Median R | Profit factor | Total R | Max DD (R) | Flag |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| BUY | 163 | 65.5% | 50.3% | +0.3090 | +0.0546 | 1.69 | +50.37 | 18.23 |  |
| SELL | 86 | 34.5% | 39.5% | +0.0202 | -0.9993 | 1.03 | +1.74 | 15.68 |  |

The user-supplied unconstrained figures were BUY +0.316R (456 trades) vs SELL -0.033R (232 trades). Measured here: BUY 462 trades, +0.3044; SELL 233 trades, -0.0177. Corrected — see numbers above.

---

## 4. Controls on the same constrained entries

Controls reuse the exact same entry timestamps, stop distances, TP ladder (mirrored to the opposite side) and the flat 0.40 price-unit-per-position-unit round-trip cost. Two random-direction controls are reported, both over seeds `1..1000`:

1. **50/50 coin** — each entry independently assigned BUY/SELL.
2. **Ratio-preserving shuffle** — the period's BUY/SELL count ratio is kept exactly, only the assignment is shuffled (the pre-registered C2 control).

If a mirrored control direction would void at entry under the Option B contract, it contributes 0R (no position exists). Voided baseline entries are excluded from both the real and control populations.

Percentile rank = share of the 1,000 random means at or below the real mean R. The pass rule is **percentile ≥ 97.5 on BOTH later half-years** (validation = 2026-H1, test = 2026-H2).

| Period | n | Real mean R | Always-BUY | Always-SELL | Coin mean ± sd | Coin pct | Shuffle mean ± sd | Shuffle pct | Flag |
| :--- | ---: | ---: | ---: | ---: | :---: | ---: | :---: | ---: | :--- |
| **Whole window** | 249 | +0.2092 | +0.2180 | -0.1510 | +0.0347 ± 0.0718 | 99.3% | +0.0945 ± 0.0728 | 95.3% |  |
| 2025-H1 | 58 | +0.2387 | +0.2399 | -0.3374 | -0.0461 ± 0.1491 | 98.0% | -0.0149 ± 0.1434 | 97.0% |  |
| 2025-H2 | 67 | +0.5528 | +0.7706 | -0.5345 | +0.1148 ± 0.1505 | 99.7% | +0.5029 ± 0.1042 | 68.2% |  |
| 2026-H1 | 73 | -0.1060 | -0.0595 | +0.0008 | -0.0250 ± 0.1365 | 28.5% | -0.0377 ± 0.1324 | 29.9% |  |
| 2026-H2 | 51 | +0.1756 | -0.1357 | +0.3477 | +0.1128 ± 0.1662 | 65.2% | +0.0462 ± 0.1575 | 78.8% |  |

### Half-year control detail (5%–95% bands and always-BUY/SELL win rates)

| Period | n | Real mean R (WR) | Always-BUY mean R (WR) | Always-SELL mean R (WR) | Coin 5–95% | Shuffle 5–95% |
| :--- | ---: | :--- | :--- | :--- | :---: | :---: |
| 2025-H1 | 58 | +0.2387 (46.6%) | +0.2399 (48.3%) | -0.3374 (32.8%) | [-0.2925, +0.1976] | [-0.2542, +0.2142] |
| 2025-H2 | 67 | +0.5528 (59.7%) | +0.7706 (64.2%) | -0.5345 (20.9%) | [-0.1344, +0.3701] | [+0.3339, +0.6748] |
| 2026-H1 | 73 | -0.1060 (34.2%) | -0.0595 (37.0%) | +0.0008 (35.6%) | [-0.2485, +0.1978] | [-0.2466, +0.1839] |
| 2026-H2 | 51 | +0.1756 (47.1%) | -0.1357 (39.2%) | +0.3477 (52.9%) | [-0.1646, +0.3933] | [-0.2164, +0.2922] |

### Pass/fail verdict

| Control | Validation 2026-H1 | Test 2026-H2 | Both ≥ 97.5%? |
| :--- | ---: | ---: | :--- |
| Ratio-preserving shuffle (pre-registered) | 29.9% | 78.8% | **FAIL** |
| 50/50 random direction | 28.5% | 65.2% | **FAIL** |

**Verdict: FAIL.** Under the pre-registered ratio-preserving control the real mean R must beat 97.5% of random direction assignments in both 2026-H1 and 2026-H2; it reaches 29.9% and 78.8% respectively. The 50/50 coin control also fails.

### Secondary: controls under the frozen walk-forward split labels

The checkpoint `split` field follows `docs/SMC_FREEZE_V2.md` (calibration ends 2025-05-21 08:15 UTC, validation ends 2026-02-16 03:00 UTC). These windows are wider than the half-years and are shown only for continuity with earlier reports.

| Split | n | Real mean R | Always-BUY | Always-SELL | Coin pct | Shuffle pct |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| calibration | 45 | +0.3819 | +0.2932 | -0.3980 | 99.8% | 97.5% |
| validation | 103 | +0.3301 | +0.6004 | -0.5210 | 99.3% | 75.9% |
| test | 101 | +0.0091 | -0.2055 | +0.3365 | 34.1% | 49.4% |

---

## 5. Honest limits — what this backtest cannot show

1. **Not clean out-of-sample.** 2025-01-01 onward overlaps data that was already observed while SMC was developed and tuned (see the parameter history and the contamination table in `docs/SMC_FREEZE_V2.md`). The only strictly unseen window begins after 2026-11-15 15:00 UTC. This report is a re-analysis of already-seen data, not a validation of the frozen strategy.
2. **Single instrument, single source.** One symbol (XAU/USD), one vendor (Twelve Data), 15m bars; HTFs are resampled, not independent data. Survivorship or vendor-specific bar construction cannot be ruled out.
3. **Small validation/test halves.** 2026-H1 carries 73 constrained trades and 2026-H2 carries 51. A 97.5% percentile threshold on ~50–70 trades has wide sampling error, and any half-year with n<30 is flagged descriptive-only above.
4. **Simulation, not execution.** Under the Option B contract, entry fills at the next 15m open, in-trade gaps fill at executable prices, same-bar ambiguity resolves stop-first, and SL/TP levels stay fixed after signal generation. 50% is booked at TP1 with break-even stop; residual positions close at the 500-bar limit or end of data. Cost is a flat 0.40 price units per position unit round trip. This is a capacity-filtered 1R simulation: shared capital, margin, compounding, weekend financing, broker lot sizes and news voids are not modelled.
5. **Rule interpretation.** `MIN_ENTRY_SEPARATION` is implemented exactly as the frozen code (skip if *any* open same-direction entry is both <1h and <1 ATR away). The alternative reading — a global 1h escape after the last same-direction entry — was not silently substituted; it is noted here because it changes the separation skip count (2 under the frozen reading).
6. **Concurrency dominates the funnel.** The gap between 695 unconstrained and the constrained set is almost entirely the 3-slot cap, not the strategy signal count. Holding times are long (median 323 market bars), so the portfolio is capacity-bound; results say as much about the cap as about the edge.
7. **Direction asymmetry is confounded with drift.** Always-BUY beats Always-SELL in 2025-H1 (+0.204 vs -0.248) and 2025-H2 (+0.770 vs -0.533), consistent with gold's upward drift, but the ordering reverses in 2026-H1 (-0.073 vs +0.011) and 2026-H2 (-0.148 vs +0.351). The real strategy trails Always-BUY in 2025-H2 and leads it in 2026-H2. The BUY/SELL split therefore describes this window's drift and regime, not a stable directional edge.
8. **No tuning was performed.** Nothing was optimised on this window: the funnel, metrics and controls are deterministic given the checkpoints, the read-only candles and seeds 1..1000.

---

Generated by `server/scripts/smc_portfolio_2025.py` (23 checkpoint files, 1,000 seeds; run at 2026-11-22 08:21 UTC).
