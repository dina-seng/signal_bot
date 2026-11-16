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
| Replay window (0.5 months) | 2026-10-31 09:45 → 2026-11-15 15:00 UTC |
| Bars in window | 1,462 |
| Closed-market bars dropped | 542 |
| Open-market bars replayed | 920 |

## 2. Rejection funnel

Bars evaluated: **820** · sweep candidates: **27** · emitted signals: **0**

| Stage | Gate | Bars |
| :--- | :--- | ---: |
| pre-sweep | `MISSING_HTF_CANDLES` | 0 |
| pre-sweep | `OFF_SESSION` | 0 |
| pre-sweep | `MISSING_TIMESTAMPS` | 0 |
| post-sweep | `NO_SWEEP` | 711 |
| pre-sweep | `MICRO_RANGE` | 0 |
| pre-sweep | `EXCESSIVE_RANGE` | 0 |
| pre-sweep | `MICRO_SWEEP` | 14 |
| pre-sweep | `EXCESSIVE_MANIPULATION` | 9 |
| post-sweep | `SWEEP_EXTREME_BROKEN` | 0 |
| post-sweep | `CONFIRMATION_PENDING` | 27 |
| post-sweep | `MISSED_SETUP` | 0 |
| post-sweep | `INVALID_RISK_GEOMETRY` | 0 |
| post-sweep | `EXCESSIVE_RISK_DISTANCE` | 0 |
| post-sweep | `INSUFFICIENT_RR` | 0 |
| post-sweep | `PATH_BLOCKED` | 0 |
| post-sweep | `SCORE_BELOW_THRESHOLD` | 0 |
| post-sweep | `DUPLICATE_SUPPRESSED` | 0 |
| post-sweep | `OTHER_WAIT` | 159 |
| **emitted** | `CONFIRMED_SETUP` | **0** |

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

## 6. Exit reasons

| Exit reason | Count |
| :--- | ---: |

---

No strategy threshold was modified; all CRT parameters are production defaults.
