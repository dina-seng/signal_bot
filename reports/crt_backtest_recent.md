# CRT Strategy Institutional Backtest Report — Recent Data

**Period**: 2025-01-01 to 2026-11-15 15:00 UTC (581 Trading Days)
**Symbol**: XAU/USD · **Timeframe**: 15m (Twelve Data)
**Execution Engine**: `simulate_outcome` with strict zero-lookahead, **$0.40 round-trip friction**
**Confirmation Engine**: Post-defect fix (Displacement prerequisite + Chronological MSS filtering)

## Executive Summary

| Metric | Value | Benchmark / Target | Status |
| :--- | :--- | :--- | :--- |
| **Total Realized Trades** | **1** | ≥ 30 for statistical power | UNDERPOWERED |
| **Win Rate (%)** | **100.00%** | > 40.0% | PASS |
| **Loss Rate (%)** | **0.00%** | - | - |
| **Expectancy per Trade** | **+0.6258 R** | > +0.2000 R | PASS |
| **Mean R** | **+0.6258 R** | > 0 | - |
| **Median R** | **+0.6258 R** | > 0 | - |
| **Profit Factor** | **99.99** | > 1.30 | PASS |
| **Total Net R** | **+0.63 R** | > 0 | - |
| **Max Drawdown (R)** | **0.00 R** | < 15.0 R | PASS |
| **Max Drawdown (%)** | **0.00%** | < 15.0% (1R=1%) | PASS |
| **Sharpe Ratio (Daily Ann.)** | **0.66** | > 1.00 | SUB-OPTIMAL |
| **Average Holding Time** | **1.5 hours** | < 48.0 hours | - |
| **Trades per Trading Day** | **0.002** | Target ~0.5 - 2.0 | - |

## Portfolio Constraints Breakdown (Phase C)

The portfolio simulation enforces the four strict institutional gates:
1. **MAX_CONCURRENT**: 3 open positions
2. **ONE_ENTRY_PER_SWEEP**: Exactly one entry per unique liquidity sweep event
3. **MIN_ENTRY_SEPARATION**: $\ge 1.0 \times \text{ATR}(14, 15\text{m})$ OR $\ge 1\text{h}$ since last same-direction entry
4. **DAILY_LOSS_STOP**: Realized PnL $\le -3.0\text{R}$ in a UTC calendar day halts new entries until next day

| Funnel Stage | Count | Notes |
| :--- | ---: | :--- |
| Raw Signals Emitted by Strategy | 1 | Pre-portfolio setup candidates |
| Skipped: Repeat Sweep (`ONE_ENTRY_PER_SWEEP`) | 0 | Multiple bars from same sweep key |
| Skipped: Concurrency Cap (`MAX_CONCURRENT=3`) | 0 | Blocked by 3 active positions |
| Skipped: Separation Rule (`MIN_ENTRY_SEPARATION`) | 0 | Too close in time/price to open position |
| Skipped: Daily Loss Stop (`DAILY_LOSS_STOP=-3.0R`) | 0 | Daily drawdown limit reached |
| Skipped: Unfilled Limit Zone Order | 0 | Expired or stopped out before limit touch |
| **Portfolio Entered Trades** | **1** | **Executed with $0.40 round-trip friction** |

## Strategy Rejection Funnel Analysis

- **Total 15m Bars Evaluated**: 44,081
- **Warmup Bars Skipped**: 100
- **Evaluation Errors**: 0

| Gate | Type | Bars Stopped | Description |
| :--- | :--- | ---: | :--- |
| `MISSING_HTF_CANDLES` | Pre-Sweep | 0 | |
| `OFF_SESSION` | Pre-Sweep | 0 | |
| `MISSING_TIMESTAMPS` | Pre-Sweep | 0 | |
| `NO_SWEEP` | Pre-Sweep | 37,822 | |
| `TREND_CONFLICT` | Post-Sweep | 2,796 | |
| `MICRO_RANGE` | Pre-Sweep | 236 | |
| `EXCESSIVE_RANGE` | Pre-Sweep | 0 | |
| `MICRO_SWEEP` | Post-Sweep | 1,212 | |
| `EXCESSIVE_MANIPULATION` | Post-Sweep | 386 | |
| `SWEEP_EXTREME_BROKEN` | Post-Sweep | 0 | |
| `CONFIRMATION_PENDING` | Post-Sweep | 1,602 | |
| `MISSED_SETUP` | Post-Sweep | 1 | |
| `INVALID_RISK_GEOMETRY` | Post-Sweep | 0 | |
| `EXCESSIVE_RISK_DISTANCE` | Post-Sweep | 2 | |
| `INSUFFICIENT_RR` | Post-Sweep | 0 | |
| `PATH_BLOCKED` | Post-Sweep | 1 | |
| `SCORE_BELOW_THRESHOLD` | Post-Sweep | 2 | |
| `DUPLICATE_SUPPRESSED` | Post-Sweep | 0 | |
| `OTHER_WAIT` | Post-Sweep | 0 | |
| `INVALID_ENTRY_ZONE` | Post-Sweep | 20 | |
| `CONFIRMED_SETUP` | **Emitted** | **1** | Validated setup |

### Confirmation Engine Breakdown

Observations from `CONFIRMATION_PENDING` (verifying recent bug fix effectiveness):

| Reason | Frequency |
| :--- | ---: |
| Analyzer: no close back inside range yet | 1,029 |
| Awaiting post-sweep confirmation candles. | 305 |
| Awaiting valid displacement candle after range re-entry. | 159 |
| Awaiting Market Structure Shift (MSS) after sweep. | 109 |

## Trade Execution & Outcome Breakdown

| Exit Reason | Count | Share (%) |
| :--- | ---: | ---: |
| `TP1_BE_STOP` | 1 | 100.0% |

### Sample Executed Trades (First 10)

| Date (UTC) | Dir | Entry | SL | TP1 | R-Multiple | Exit Reason | Holding (h) |
| :--- | :--- | ---: | ---: | ---: | ---: | :--- | ---: |
| 2025-12-10 05:45 | BUY | 4204.37 | 4201.15 | 4209.20 | +0.626R | `TP1_BE_STOP` | 1.5 |

## Institutional Findings & Verdict

1. **Trade Volume**: 1 trades executed across 581 days (0.002 entries/day).
2. **Expectancy**: Strategy delivered +0.6258 R per trade with 100.0% win rate.
3. **Capital Growth & Risk**: Total return +0.63 R with Max Drawdown of 0.00 R (0.0%).
4. **Friction Impact**: Fixed $0.40 round-trip spread deduction strictly reflected across all outcomes.
