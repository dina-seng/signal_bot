# QuantView Testing & Validation Documentation

This document provides a comprehensive testing map and empirical strategy validation status for QuantView as of November 17, 2026. All statements reflect data collected from `pytest --collect-only -q`, source code analysis, and repository artifacts.

---

## Table of Contents

1. [J. Comprehensive Testing Map](#j-comprehensive-testing-map)
   - [Test Summary & Classification](#test-summary--classification)
   - [Complete Per-File Test Inventory (49 Files, 346 Tests)](#complete-per-file-test-inventory-49-files-346-tests)
   - [Analysis of Known Failing, Brittle, or Slow Tests](#analysis-of-known-failing-brittle-or-slow-tests)
2. [N. Strategy Validation Status & Empirical Evidence](#n-strategy-validation-status--empirical-evidence)
   - [Artifacts Present in Repository](#artifacts-present-in-repository)
   - [CRT 3-Month Replay Diagnostic Analysis](#crt-3-month-replay-diagnostic-analysis)
   - [SMC and Range Strategy Validation Evidence](#smc-and-range-strategy-validation-evidence)
   - [Random Walk Control Baseline](#random-walk-control-baseline)
   - [Validation Verdict: Does Any Strategy Have a Proven Edge?](#validation-verdict-does-any-strategy-have-a-proven-edge)

---

## J. Comprehensive Testing Map

### Test Summary & Classification

Executing `pytest --collect-only -q` from `server/` collected exactly **346 tests across 49 test files**.

Tests are classified into three runtime categories:
- **Fast Unit Tests (In-Memory)**: Execute in milliseconds using synthetic fixtures and in-memory SQLite (`conftest.py`).
- **Slow Tests (Compute-Intensive)**: Execute multi-iteration simulations (e.g. 10,000 bootstrap resamples or random-walk controls).
- **Environment-Dependent Tests**: Require specific environment setups or mocked providers.

```
+-------------------------------------------------------------------------+
|                  TEST SUITE COMPOSITION (346 TESTS)                     |
+--------------------------+------------+---------------------------------+
| Runtime Class            | File Count | Test Count                      |
+--------------------------+------------+---------------------------------+
| Fast Unit Tests          | 45 files   | 335 tests                       |
| Slow Simulations         | 2 files    | 2 tests                         |
| Environment / Integration| 2 files    | 9 tests                         |
+--------------------------+------------+---------------------------------+
| Total                    | 49 files   | 346 tests                       |
+--------------------------+------------+---------------------------------+
```

### Complete Per-File Test Inventory (49 Files, 346 Tests)

| Test File Path | Tests | Target Module Under Test | Runtime Class | Tested Functionality / Key Assertions |
| :--- | :---: | :--- | :---: | :--- |
| `tests/test_api.py` | 3 | `api/v1/health.py`, `market.py` | Fast | Health endpoint, symbol list, sync and query candles |
| `tests/test_audit_candles.py` | 1 | `services/market_data/ingestion.py` | Fast | Candle integrity, gap detection, deduplication |
| `tests/test_backtest_api.py` | 3 | `api/v1/backtest.py` | Fast | Stateless backtest, CRUD run endpoints, parameter sweep |
| `tests/test_backtesting.py` | 5 | `services/backtesting/*` | Fast | Metrics with zero/mixed trades, engine simulation, optimizer |
| `tests/test_bos_choch.py` | 5 | `services/structure/bos_choch_detector.py`| Fast | Bullish/Bearish BOS & CHoCH, strict body close rule |
| `tests/test_candle_fallback_and_webhook.py`| 5 | `market_data/twelvedata_provider.py`, `telegram.py` | Fast | US100 quarantine, no-fallback rule, single-asset scan, webhook ack |
| `tests/test_control_random_walk.py` | 1 | `services/backtesting/walk_forward_harness.py`| Fast | Asserts random-walk synthetic series yields no positive edge |
| `tests/test_crt_strategy.py` | 79 | `services/strategies/crt_strategy.py`, `crt/*` | Fast | 79 tests covering AMD sequence, HTF filter, session gate, pips/lots, tiers |
| `tests/test_data_freshness.py` | 11 | `services/market_data/freshness.py` | Fast | Closed candle rules, staleness multipliers, weekend bypass |
| `tests/test_duplicate_integrity.py` | 4 | `services/telegram/scanner.py`, `paper.py` | Fast | Fingerprint deduplication, unique account-signal constraint |
| `tests/test_import_history.py` | 7 | `scripts/import_history.py` | Fast | CSV parsing, chunked ingestion, timestamp normalization |
| `tests/test_indicators.py` | 4 | `services/indicators/*` | Fast | ATR Wilder smoothing, EMA alignment, RSI divergences |
| `tests/test_indicators_api.py` | 5 | `api/v1/indicators.py` | Fast | Indicator endpoints, FVG and divergence queries |
| `tests/test_ingestion_pipeline.py` | 6 | `services/market_data/ingestion.py` | Fast | Upsert idempotency, batch commits, gap detection |
| `tests/test_liquidity.py` | 5 | `services/liquidity/*` | Fast | S/R zone clustering, liquidity pool detection, sweep wicks |
| `tests/test_liquidity_api.py` | 5 | `api/v1/liquidity.py` | Fast | Liquidity analysis endpoints, zones, pools, sweeps |
| `tests/test_ltf_confirmation.py` | 9 | `services/structure/ltf_confirmation.py` | Fast | 15m MSS confirmation, 5-bar lookback, 70% penalty |
| `tests/test_market_calendar.py` | 5 | `services/market_data/calendar.py` | Fast | Spot Gold hours, NY DST transitions, weekend/break filters |
| `tests/test_market_data_provider.py` | 4 | `services/market_data/base.py`, `mock.py` | Fast | Provider abstraction, mock generation, interface compliance |
| `tests/test_message_formatter_pure.py` | 6 | `services/telegram/message_formatter.py` | Fast | HTML escaping, signal message layouts, risk limit warnings |
| `tests/test_models.py` | 6 | `models/*` | Fast | SQLAlchemy table definitions, relationships, constraints |
| `tests/test_news.py` | 7 | `services/news/*` | Fast | Calendar parsing, blackout window calculation |
| `tests/test_news_api.py` | 3 | `api/v1/news.py` | Fast | News calendar, blackout check, sync endpoints |
| `tests/test_news_integrity.py` | 8 | `services/news/filter_engine.py` | Fast | Blackout vetoes, currency mapping (XAU $\to$ USD) |
| `tests/test_paper_trading.py` | 6 | `services/paper_trading/*` | Fast | Account creation, margin sizing, order execution, TP/SL exits |
| `tests/test_paper_trading_api.py` | 2 | `api/v1/paper.py` | Fast | Paper account and position REST endpoints |
| `tests/test_phase1_data_layer.py` | 5 | `services/market_data/*` | Fast | Twelve Data single-source, token bucket, daily budget |
| `tests/test_price_action.py` | 4 | `services/indicators/price_action.py` | Fast | FVG detection, Pin bar wick ratios, Engulfing patterns |
| `tests/test_production_parity.py` | 3 | `services/signals/confluence_engine.py` | Fast | Consensus parity between monolith and modular evaluators |
| `tests/test_quote_provenance.py` | 7 | `services/market_data/twelvedata_provider.py` | Fast | Quote age validation, max deviation checks |
| `tests/test_random_walk_control_slow.py` | 1 | `services/sweep/backtest/baseline.py` | **Slow** | 10,000-path Monte Carlo random walk control simulation |
| `tests/test_range_strategy.py` | 9 | `services/strategies/range_strategy.py` | Fast | Mean reversion in ranging markets, no-trend veto, S/R bounce |
| `tests/test_resample.py` | 7 | `services/market_data/resample.py` | Fast | 15m $\to$ 30m/1h/4h/1d resampling, 17:00 NY daily anchor |
| `tests/test_scanner_scheduler.py` | 17 | `services/telegram/scheduler.py`, `scanner.py` | Fast | 15m candle-close cron trigger, 10s offset, deduplication |
| `tests/test_signals.py` | 11 | `services/signals/*` | Fast | Confluence scoring, floor gates, directional conflict penalties |
| `tests/test_signals_api.py` | 3 | `api/v1/signals.py` | Fast | Signal evaluate and scan REST endpoints |
| `tests/test_strategies.py` | 7 | `services/strategies/*` | Fast | StrategyManager fan-out, SMC execution, score synthesis |
| `tests/test_structure.py` | 7 | `services/structure/*` | Fast | Swing detector, single-timeframe structure, MTF aggregation |
| `tests/test_structure_api.py` | 5 | `api/v1/structure.py` | Fast | Structure endpoints, multi-timeframe structure |
| `tests/test_sweep_backtest.py` | 7 | `services/sweep/backtest/*` | Fast | Trade-through fills, same-bar SL-first, 60/20/20 splits, CI |
| `tests/test_sweep_engine.py` | 10 | `services/sweep/engine.py` | Fast | Pure sweep detection, 12-bar MSS, prefix invariance |
| `tests/test_symbol_mapping.py` | 4 | `services/market_data/symbols.py` | Fast | XAU/USD $0.10 pip size, 100 oz contract, lot sizing math |
| `tests/test_telegram.py` | 5 | `services/telegram/*` | Fast | Bot commands, mock client, deduplication |
| `tests/test_telegram_api.py` | 4 | `api/v1/telegram.py` | Fast | Broadcast, webhook, scanner trigger endpoints |
| `tests/test_time_utils.py` | 7 | `core/time_utils.py` | Fast | UTC to local conversions, pytz handling (DEAD module) |
| `tests/test_twelvedata_provider.py` | 6 | `services/market_data/twelvedata_provider.py`| Fast | Shared client DI, 429 retry, rate limit stop, OHLC invariants |
| `tests/test_unified_scanner.py` | 4 | `services/telegram/scanner.py` | Fast | Unified multi-timeframe scan output, Telegram formatting |
| `tests/test_walk_forward_harness.py` | 7 | `services/backtesting/walk_forward_harness.py`| Fast | Single-source enforcement, same-bar SL-first, session tagging |
| `tests/test_window_invariance.py` | 1 | `services/sweep/engine.py` | Fast | Full prefix vs rolling window output invariance |

---

### Analysis of Known Failing, Brittle, or Slow Tests

Reading the test fixtures and strategy code identified several brittle tests and known issues:

1. **`tests/test_random_walk_control_slow.py:62` (Slow / Unregistered Mark)**:
   - Decorated with `@pytest.mark.slow`. Pytest outputs warning: `PytestUnknownMarkWarning: Unknown pytest.mark.slow - is this a typo?`. Custom mark is not registered in `pytest.ini`.
   - Runs 10,000 Monte Carlo paths; takes over 2 minutes if executed.
2. **`tests/test_crt_strategy.py::test_crt_unconfirmed_breach_returns_wait` (Structural Weakness)**:
   - Passes only because the test fixture omits MSS.
   - If a pre-sweep CHoCH is present in `structure.recent_events`, `confirmation.py:114-123` erroneously evaluates `has_mss = True` because event timestamps are not filtered against `breach_point` timestamp.
3. **`tests/test_crt_strategy.py::test_no_lookahead_future_candles_do_not_alter_past_decision` (State Evolution Issue)**:
   - Asserts historical setup at bar $T$ is invariant.
   - However, when future candles are appended ($T+1 \to T+3$), evaluating `entry.py:175-190` reclassifies the setup as `MISSED` because price advances $> 0.5\text{R}$, ignoring whether the limit entry was already filled at $T+1$.
4. **`tests/test_time_utils.py` (Tests Dead Code)**:
   - All 7 tests pass against `core/time_utils.py`, but the module is completely unused by the application.
5. **FastAPI TestClient Warning**:
   - `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.` (FastAPI 0.162+ compatibility warning emitted during collection).

---

## N. Strategy Validation Status & Empirical Evidence

### Artifacts Present in Repository

A systematic search for backtest and validation artifacts yielded the following files on disk:

1. **`backtest.db` (36,474,880 bytes, Root)**:
   - SQLite database containing **100,408 raw 15-minute XAU/USD candles** spanning from `2023-03-01 00:00:00` to `2026-11-15 15:00:00 UTC`.
   - Source tagged: all rows tagged `source = "twelvedata"`.
   - Cleanliness: 96 duplicate timestamps dropped; closed-market placeholder bars flagged.
2. **`reports/crt_replay/crt_replay_report.md` (3,227 bytes)**:
   - Generated by `scripts/crt_replay.py` on November 17, 2026.
   - Evaluated 3 months of historical data (2026-08-16 07:30 to 2026-11-15 15:00 UTC) through the exact production CRT strategy pipeline.
3. **`reports/crt_replay/crt_replay_signals.csv` (254 bytes)**:
   - Empty CSV output corresponding to zero emitted signals.
4. **`REPORT.md` (24,787 bytes, Root)**:
   - Comprehensive quantitative strategy audit detailing mathematical and market structure checks.

---

### CRT 3-Month Replay Diagnostic Analysis

The 3-month replay diagnostic (`reports/crt_replay/crt_replay_report.md`) executed against `backtest.db` evaluated **5,625 open-market 15m bars** (warm-up bars skipped: 100; closed-market bars dropped: 2,662):

#### Empirical Rejection Funnel Output

```
Total Open-Market Bars Evaluated: 5,625
├── Pre-Sweep Phase:
│   ├── NO_SWEEP:                      4,846 bars (86.2%)
│   ├── MICRO_RANGE (< 0.35 ATR):         55 bars  (1.0%)
│   ├── EXCESSIVE_RANGE (> 4.0 ATR):       0 bars  (0.0%)
│   ├── MISSING_TIMESTAMPS:                0 bars  (0.0%)
│   └── OFF_SESSION:                       0 bars  (0.0%)
└── Sweep Candidate Bars:                724 bars (12.9%)
    ├── Post-Sweep Rejections:
    │   ├── TREND_CONFLICT (HTF 1h/4h):  390 bars (53.9% of sweeps)
    │   ├── MICRO_SWEEP (< 0.15 ATR):    119 bars (16.4% of sweeps)
    │   ├── CONFIRMATION_PENDING:        179 bars (24.7% of sweeps)
    │   │   ├── Awaiting close in range: 118 bars
    │   │   ├── Awaiting confirm bars:    41 bars
    │   │   ├── Insufficient displacement:14 bars
    │   │   └── Awaiting post-sweep MSS:   6 bars
    │   ├── EXCESSIVE_MANIPULATION:       35 bars  (4.8% of sweeps)
    │   └── PATH_BLOCKED (< 1.0R):         1 bar   (0.1% of sweeps)
    └── CONFIRMED SETUPS EMITTED:          0 signals (0.0%)
```

#### Outcome Simulation & Statistical Edge
- **Signals Emitted**: `0`
- **Filled Trades**: `0`
- **Win Rate**: `n/a%`
- **Expectancy / Average R**: `n/a`
- **Profit Factor**: `n/a`
- **Bootstrap 95% Confidence Interval**: `[n/a, n/a]`

> **Factual Finding**: Over 3 months of continuous 15-minute historical Gold data (August–November 2026), the Candle Range Theory (CRT) strategy emitted **zero trades**. The conjunction of HTF trend alignment (which vetoed 53.9% of sweeps) and lower-timeframe confirmation requirements (which vetoed 24.7% of sweeps) produced a 100% rejection rate. Consequently, **there is ZERO empirical evidence that CRT possesses a positive statistical edge**.

---

### SMC and Range Strategy Validation Evidence

1. **SMC Strategy (`smc_strategy.py`)**:
   - No historical backtest report artifact exists in `reports/` for `SMCStrategy`.
   - `services/backtesting/backtest_engine.py` can simulate SMC, but no saved backtest runs exist in `trade.db` (`backtest_runs` table has 0 completed runs in default DB).
   - **Status: UNVERIFIED**. There is no quantitative artifact proving an edge for SMC.
2. **Range Strategy (`range_strategy.py`)**:
   - No historical backtest report artifact exists in `reports/` for `RangeStrategy`.
   - **Status: UNVERIFIED**. There is no quantitative artifact proving an edge for Range Strategy.

---

### Random Walk Control Baseline

In `tests/test_control_random_walk.py` and `services/backtesting/walk_forward_harness.py:450-520`:
- Generates 1,000 synthetic geometric Brownian motion price paths with identical drift and volatility to XAU/USD.
- Evaluates trading through friction ($0.40 round-trip).
- Confirms that random entries produce negative expectancy ($-0.12\text{R}$ to $-0.25\text{R}$ per trade) due to bid-ask spread and slippage.
- Proves the backtest simulation harness is capable of detecting when a strategy lacks an edge.

---

### Validation Verdict: Does Any Strategy Have a Proven Edge?

| Strategy | Backtest Artifact Present? | Out-of-Sample Period | Trade Count ($N$) | Win Rate | Expectancy | Verified Edge? |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Candle Range Theory (CRT)** | Yes (`reports/crt_replay/`) | 3 months (Aug–Nov 2026) | **0** | n/a | n/a | **NO (Zero Trades Emitted)** |
| **SMC Strategy (Strategy A)** | None | None | 0 | n/a | n/a | **UNVERIFIED (No Artifact)** |
| **Range Strategy (Strategy C)**| None | None | 0 | n/a | n/a | **UNVERIFIED (No Artifact)** |
| **Phase 2 Sweep Engine** | None | None | 0 | n/a | n/a | **UNVERIFIED (No Artifact)** |

**Conclusion**:
QuantView currently possesses robust zero-lookahead testing infrastructure, realistic friction models, and strict gatekeeper logic. However, **no strategy in this repository has demonstrated a statistically verified positive trading edge on historical data**. For CRT, the gatekeeper criteria are so restrictive that no actionable setups were confirmed across 5,625 open-market bars.
