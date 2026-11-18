# SMC — Real (Portfolio-Constrained) Backtest, 2025-01-01 → Latest

**Scope**: the already-produced SMC replay in `reports/exp_2025_smc/checkpoints` replayed through the frozen portfolio rules only. No threshold, score, gate or default was changed; SMC is frozen per `docs/SMC_FREEZE_V2.md`.

**Window**: 2025-01-01 00:00 → 2026-11-13 21:45 UTC (decision times). This is the last **open-market** bar: the database's closed-market placeholder bars (Friday 22:00 → Sunday 22:00 UTC) are filtered out at load time, so the raw table extends to 2026-11-15 15:00 but the analysable window ends on the Friday close.

**Input verification** (must hold before any metric is reported):

| Check | Expected | Observed | Result |
| :--- | ---: | ---: | :--- |
| Distinct trades (one per `opportunity_key`) | 688 | 688 | PASS |
| Unconstrained total R | +136.45 | +136.4464 | PASS |
| Re-simulated R == checkpoint R | 0 mismatches | 0 | PASS |

Data: `backtest.db` opened read-only (`mode=ro`), Twelve Data 15m bars, open-market bars only. `$0.40` round-trip friction is already inside every checkpoint `r_multiple`; controls re-use the same friction through the shared `simulate_outcome` engine.

---

## 1. Portfolio funnel (frozen rules, decision-time order)

| Funnel Stage | Count | Notes |
| :--- | ---: | :--- |
| Raw accepted signals (15m bars) | 2,687 | Every accepted 15m bar in the window |
| Skipped: repeat sweep (`ONE_ENTRY_PER_SWEEP`) | 1,999 | Later 15m bars from the same opportunity_key |
| Distinct opportunities (input to rules) | 688 | ONE_ENTRY_PER_SWEEP applied |
| Skipped: concurrency cap (`MAX_CONCURRENT=3`) | 422 | MAX_CONCURRENT=3 already open |
| Skipped: separation rule (`MIN_ENTRY_SEPARATION`) | 2 | < 1 ATR and < 1h from an open same-direction entry |
| Skipped: daily loss stop (`DAILY_LOSS_STOP=-3.0R`) | 15 | Day already at or below -3.0 R realized |
| Skipped: unfilled limit-zone order | 0 | n/a — all entries are market fills |
| **Portfolio entered trades** | 249 | Executed with $0.40 round-trip friction |

Rule attribution order is daily stop → concurrency → separation (frozen implementation). The accepted set is invariant to that order; only the attribution of a multi-cause skip moves.

### Funnel by half-year

| Period | Accepted bars | Repeat sweep | Distinct | Concurrency | Separation | Daily stop | Entered |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025-H1 | 645 | 483 | 162 | 102 | 1 | 0 | 59 |
| 2025-H2 | 749 | 558 | 191 | 120 | 0 | 4 | 67 |
| 2026-H1 | 744 | 551 | 193 | 114 | 0 | 6 | 73 |
| 2026-H2 | 549 | 407 | 142 | 86 | 1 | 5 | 50 |
| **Total** | 2,687 | 1,999 | 688 | 422 | 2 | 15 | 249 |

---

## 2. Constrained performance: whole window and by half-year

Trades are assigned to a half-year by **decision time**; within each group the equity curve, drawdown and exit ordering use **exit time**, not entry time. Holding time in *market bars* counts open-market 15m bars held; wall-clock hours run from decision time to the exit bar's open time (the checkpoint's `exit_time`).

| Period | Trades | Win rate | Avg R | Median R | Profit factor | Total R | Max DD (R) | Longest DD | Hold med (bars / h) | Hold p90 (bars / h) | Flag |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- | :--- | :--- |
| **Whole window** | 249 | 47.0% | +0.2059 | -0.4687 | 1.42 | +51.26 | 22.45 | 215.0 d (86 trades, open) | 314 / 129.0 | 500 / 178.5 |  |
| 2025-H1 | 59 | 45.8% | +0.2073 | -0.2439 | 1.45 | +12.23 | 8.01 | 62.5 d (20 trades, open) | 415 / 159.5 | 500 / 178.8 |  |
| 2025-H2 | 67 | 59.7% | +0.5503 | +0.6158 | 2.47 | +36.87 | 8.23 | 64.5 d (26 trades) | 371 / 144.2 | 500 / 178.5 |  |
| 2026-H1 | 73 | 35.6% | -0.0925 | -1.0035 | 0.85 | -6.76 | 19.63 | 79.6 d (36 trades, open) | 156 / 68.5 | 500 / 177.5 |  |
| 2026-H2 | 50 | 48.0% | +0.1784 | -0.4199 | 1.36 | +8.92 | 7.70 | 55.2 d (21 trades) | 296 / 125.0 | 500 / 178.5 |  |

Max drawdown is peak-to-trough on the cumulative-R curve ordered by exit time. Longest drawdown is the wall-clock time from the equity peak to the first exit that regains it (or to the last exit if it never does); a duration marked `open` had not been recovered by the window end.

### Exit-reason breakdown

| Exit reason | Whole window | Share | Avg R | 2025-H1 | 2025-H2 | 2026-H1 | 2026-H2 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `STOP_LOSS` | 114 | 45.8% | -1.0079 | 24 | 21 | 46 | 23 |
| `TIMEOUT_MARK_TO_MARKET` | 86 | 34.5% | +0.7580 | 24 | 28 | 15 | 19 |
| `TP2` | 35 | 14.1% | +2.4897 | 6 | 15 | 7 | 7 |
| `TP1_BE_STOP` | 14 | 5.6% | +0.9884 | 5 | 3 | 5 | 1 |

### Concurrency exposure

Time-weighted over wall-clock time inside each window (closed-market hours included).

| Period | Window hours | Max concurrent | Mean concurrent | % time 0 open | % time 1 open | % time 2 open | % time 3 open |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Whole window** | 16,366 | 3 | 1.66 | 26.0% | 21.0% | 14.5% | 38.6% |
| 2025-H1 | 4,344 | 3 | 1.78 | 19.5% | 23.1% | 17.3% | 40.1% |
| 2025-H2 | 4,416 | 3 | 1.86 | 20.7% | 16.8% | 18.1% | 44.4% |
| 2026-H1 | 4,344 | 3 | 1.38 | 39.2% | 18.6% | 7.7% | 34.5% |
| 2026-H2 | 3,262 | 3 | 1.59 | 24.1% | 27.0% | 14.8% | 34.1% |

---

## 3. Direction split (constrained and unconstrained)

Unconstrained = the 688 de-duplicated opportunities with no portfolio rules. Constrained = the 249 trades that survived the rules.

### Unconstrained

| Direction | Trades | Share | Win rate | Avg R | Median R | Profit factor | Total R | Max DD (R) | Flag |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| BUY | 456 | 66.3% | 52.0% | +0.3158 | +0.0826 | 1.72 | +144.02 | 36.96 |  |
| SELL | 232 | 33.7% | 37.5% | -0.0326 | -1.0040 | 0.95 | -7.57 | 63.76 |  |

### Constrained

| Direction | Trades | Share | Win rate | Avg R | Median R | Profit factor | Total R | Max DD (R) | Flag |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| BUY | 166 | 66.7% | 50.0% | +0.2854 | -0.0145 | 1.63 | +47.38 | 19.36 |  |
| SELL | 83 | 33.3% | 41.0% | +0.0467 | -1.0026 | 1.08 | +3.88 | 14.77 |  |

The user-supplied unconstrained figures were BUY +0.316R (456 trades) vs SELL -0.033R (232 trades). Measured here: BUY 456 trades, +0.3158; SELL 232 trades, -0.0326. Confirmed.

---

## 4. Controls on the same constrained entries

Controls reuse the exact same entry timestamps, stop distances, TP ladder (mirrored to the opposite side) and `$0.40` friction. Two random-direction controls are reported, both over seeds `1..1000`:

1. **50/50 coin** — each entry independently assigned BUY/SELL.
2. **Ratio-preserving shuffle** — the period's BUY/SELL count ratio is kept exactly, only the assignment is shuffled (the pre-registered C2 control).

Percentile rank = share of the 1,000 random means at or below the real mean R. The pass rule is **percentile ≥ 97.5 on BOTH later half-years** (validation = 2026-H1, test = 2026-H2).

| Period | n | Real mean R | Always-BUY | Always-SELL | Coin mean ± sd | Coin pct | Shuffle mean ± sd | Shuffle pct | Flag |
| :--- | ---: | ---: | ---: | ---: | :---: | ---: | :---: | ---: | :--- |
| **Whole window** | 249 | +0.2059 | +0.2043 | -0.1284 | +0.0364 ± 0.0727 | 98.8% | +0.0956 ± 0.0687 | 94.7% |  |
| 2025-H1 | 59 | +0.2073 | +0.2041 | -0.2481 | -0.0244 ± 0.1373 | 95.5% | +0.0057 ± 0.1357 | 94.0% |  |
| 2025-H2 | 67 | +0.5503 | +0.7698 | -0.5329 | +0.1147 ± 0.1502 | 99.7% | +0.5026 ± 0.1041 | 67.7% |  |
| 2026-H1 | 73 | -0.0925 | -0.0735 | +0.0114 | -0.0278 ± 0.1349 | 33.0% | -0.0409 ± 0.1319 | 34.5% |  |
| 2026-H2 | 50 | +0.1784 | -0.1480 | +0.3506 | +0.1070 ± 0.1659 | 67.2% | +0.0149 ± 0.1512 | 84.8% |  |

### Half-year control detail (5%–95% bands and always-BUY/SELL win rates)

| Period | n | Real mean R (WR) | Always-BUY mean R (WR) | Always-SELL mean R (WR) | Coin 5–95% | Shuffle 5–95% |
| :--- | ---: | :--- | :--- | :--- | :---: | :---: |
| 2025-H1 | 59 | +0.2073 (45.8%) | +0.2041 (47.5%) | -0.2481 (33.9%) | [-0.2548, +0.1958] | [-0.2108, +0.2179] |
| 2025-H2 | 67 | +0.5503 (59.7%) | +0.7698 (64.2%) | -0.5329 (20.9%) | [-0.1330, +0.3718] | [+0.3325, +0.6719] |
| 2026-H1 | 73 | -0.0925 (35.6%) | -0.0735 (38.4%) | +0.0114 (34.2%) | [-0.2495, +0.1898] | [-0.2523, +0.1809] |
| 2026-H2 | 50 | +0.1784 (48.0%) | -0.1480 (34.0%) | +0.3506 (54.0%) | [-0.1614, +0.3926] | [-0.2403, +0.2593] |

### Pass/fail verdict

| Control | Validation 2026-H1 | Test 2026-H2 | Both ≥ 97.5%? |
| :--- | ---: | ---: | :--- |
| Ratio-preserving shuffle (pre-registered) | 34.5% | 84.8% | **FAIL** |
| 50/50 random direction | 33.0% | 67.2% | **FAIL** |

**Verdict: FAIL.** Under the pre-registered ratio-preserving control the real mean R must beat 97.5% of random direction assignments in both 2026-H1 and 2026-H2; it reaches 34.5% and 84.8% respectively. The 50/50 coin control also fails.

### Secondary: controls under the frozen walk-forward split labels

The checkpoint `split` field follows `docs/SMC_FREEZE_V2.md` (calibration ends 2025-05-21 08:15 UTC, validation ends 2026-02-16 03:00 UTC). These windows are wider than the half-years and are shown only for continuity with earlier reports.

| Split | n | Real mean R | Always-BUY | Always-SELL | Coin pct | Shuffle pct |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| calibration | 44 | +0.4019 | +0.3008 | -0.2767 | 99.4% | 95.9% |
| validation | 102 | +0.3424 | +0.5627 | -0.5028 | 99.8% | 79.8% |
| test | 103 | -0.0131 | -0.1920 | +0.3057 | 28.7% | 44.4% |

---

## 5. Honest limits — what this backtest cannot show

1. **Not clean out-of-sample.** 2025-01-01 onward overlaps data that was already observed while SMC was developed and tuned (see the parameter history and the contamination table in `docs/SMC_FREEZE_V2.md`). The only strictly unseen window begins after 2026-11-15 15:00 UTC. This report is a re-analysis of already-seen data, not a validation of the frozen strategy.
2. **Single instrument, single source.** One symbol (XAU/USD), one vendor (Twelve Data), 15m bars; HTFs are resampled, not independent data. Survivorship or vendor-specific bar construction cannot be ruled out.
3. **Small validation/test halves.** 2026-H1 carries 73 constrained trades and 2026-H2 carries 50. A 97.5% percentile threshold on ~50–70 trades has wide sampling error, and any half-year with n<30 is flagged descriptive-only above.
4. **Simulation, not execution.** Fills are conservative same-bar stop-first, 50% booked at TP1 with break-even stop, timeout mark-to-market at 500 bars, and a constant $0.40 round-trip. Real slippage, gaps, weekend financing, broker minimum lot sizes and news voids are not modelled.
5. **Rule interpretation.** `MIN_ENTRY_SEPARATION` is implemented exactly as the frozen code (skip if *any* open same-direction entry is both <1h and <1 ATR away). The alternative reading — a global 1h escape after the last same-direction entry — was not silently substituted; it is noted here because it changes the separation skip count (2 under the frozen reading).
6. **Concurrency dominates the funnel.** The gap between 688 unconstrained and the constrained set is almost entirely the 3-slot cap, not the strategy signal count. Holding times are long (median 314 market bars), so the portfolio is capacity-bound; results say as much about the cap as about the edge.
7. **Direction asymmetry is confounded with drift.** Always-BUY beats Always-SELL in 2025-H1 (+0.204 vs -0.248) and 2025-H2 (+0.770 vs -0.533), consistent with gold's upward drift, but the ordering reverses in 2026-H1 (-0.073 vs +0.011) and 2026-H2 (-0.148 vs +0.351). The real strategy trails Always-BUY in 2025-H2 and leads it in 2026-H2. The BUY/SELL split therefore describes this window's drift and regime, not a stable directional edge.
8. **No tuning was performed.** Nothing was optimised on this window: the funnel, metrics and controls are deterministic given the checkpoints, the read-only candles and seeds 1..1000.

---

Generated by `server/scripts/smc_portfolio_2025.py` (23 checkpoint files, 1,000 seeds; run at 2026-11-18 05:41 UTC).
