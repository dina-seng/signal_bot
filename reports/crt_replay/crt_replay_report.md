# CRT Replay — No-Lookahead Diagnostic

Production path: `resample_ohlc` → `ConfluenceEngine._prepare_market_data` → `StrategyManager.run_all_strategies` → `CRTStrategy` (dedup disabled).

## 1. Data

| Item | Value |
| :--- | :--- |
| Database | `D:\trade\backtest.db` |
| Symbol / timeframe / source | XAU/USD · 15m · twelvedata |
| Raw rows read | 100,408 |
| Duplicate timestamps dropped | 96 |
| Full DB range | 2023-03-01 00:00 → 2026-11-15 15:00 UTC |
| Replay window (3 months) | 2026-08-16 07:30 → 2026-11-15 15:00 UTC |
| Bars in window | 8,387 |
| Closed-market bars dropped | 2,662 |
| Open-market bars replayed | 5,725 |

## 2. Rejection funnel

Counts are **bar-evaluations**, not distinct setups: a single sweep that stays open for many 15m bars is counted on every bar it survives.

- Bars in window: 5,725
- Warm-up bars skipped: 100
- Insufficient data (need ≥20 1h / ≥50 15m bars): 0
- Evaluation errors: 0
- Bars actually evaluated: **5,625**
- Sweep candidates: **724** · emitted signals: **0**

| Stage | Gate | Bars |
| :--- | :--- | ---: |
| pre-sweep | `MISSING_HTF_CANDLES` | 0 |
| pre-sweep | `OFF_SESSION` | 0 |
| pre-sweep | `MISSING_TIMESTAMPS` | 0 |
| pre-sweep | `NO_SWEEP` | 4,846 |
| post-sweep | `TREND_CONFLICT` | 390 |
| pre-sweep | `MICRO_RANGE` | 55 |
| pre-sweep | `EXCESSIVE_RANGE` | 0 |
| post-sweep | `MICRO_SWEEP` | 119 |
| post-sweep | `EXCESSIVE_MANIPULATION` | 35 |
| post-sweep | `SWEEP_EXTREME_BROKEN` | 0 |
| post-sweep | `CONFIRMATION_PENDING` | 179 |
| post-sweep | `MISSED_SETUP` | 0 |
| post-sweep | `INVALID_RISK_GEOMETRY` | 0 |
| post-sweep | `EXCESSIVE_RISK_DISTANCE` | 0 |
| post-sweep | `INSUFFICIENT_RR` | 0 |
| post-sweep | `PATH_BLOCKED` | 1 |
| post-sweep | `SCORE_BELOW_THRESHOLD` | 0 |
| post-sweep | `DUPLICATE_SUPPRESSED` | 0 |
| post-sweep | `OTHER_WAIT` | 0 |
| **emitted** | `CONFIRMED_SETUP` | **0** |

### Confirmation-pending sub-reasons

`CONFIRMATION_PENDING` is the dominant post-sweep gate. Its internal reason breakdown:

| Sub-reason | Bars |
| :--- | ---: |
| Analyzer: no close back inside range yet | 118 |
| Awaiting post-sweep confirmation candles. | 41 |
| Awaiting valid displacement candle (insufficient body size or range ratio). | 14 |
| Awaiting Market Structure Shift (MSS) after sweep. | 6 |

## 3. Signals by quality tier and session

| Tier | Signals |
| :--- | ---: |

| Session | Signals |
| :--- | ---: |

## 4. Outcome simulation

Assumptions: spread **$0.30** round-trip, limit expiry **8** bars, max hold **500** bars, 50% at TP1 → stop to break-even → 50% at TP2, same-bar SL-first.

| Metric | Value |
| :--- | ---: |
| Signals emitted | 0 |
| Filled | 0 |
| No fill (expired / stopped before fill) | 0 |
| Win rate | n/a% |
| Average R | n/a |
| Expectancy (R per trade) | n/a |
| Profit factor | n/a |
| Total R | n/a |
| Max drawdown (R) | n/a |
| Bootstrap 95% CI of mean R | [n/a, n/a] |

> **No filled trades — sample too small for any inference.**

## 5. Exit reasons

| Exit reason | Count |
| :--- | ---: |

---

No strategy threshold was modified; all CRT parameters are production defaults.
