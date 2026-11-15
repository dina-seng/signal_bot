# QuantView XAU/USD Liquidity-Sweep SMC Engineering Report

## System Configuration
```json
{
  "PROJECT_NAME": "Forex Market Analysis & Signal System",
  "APP_ENV": "development",
  "LOG_LEVEL": "INFO",
  "DATABASE_URL": "[REDACTED_POSTGRES_URL_IN_ENV]",
  "SUPPORTED_SYMBOLS": ["XAU/USD"],
  "SUPPORTED_TIMEFRAMES": ["15m", "1h", "4h"],
  "SWING_LOOKBACK": 2,
  "SR_TOLERANCE_PERCENT": 0.1,
  "EMA_FAST": 20,
  "EMA_MID": 50,
  "EMA_SLOW": 200,
  "RSI_PERIOD": 14,
  "ATR_PERIOD": 14,
  "MIN_SETUP_SCORE": 75.0,
  "MIN_RR": 2.0,
  "MIN_RR_TP1": 2.0,
  "MIN_RR_TP2": 3.0,
  "MAX_RISK_PERCENT": 0.5,
  "XAUUSD_SPREAD": 0.3,
  "XAUUSD_SLIPPAGE": 0.1,
  "NEWS_BLACKOUT_BEFORE_MINUTES": 30,
  "NEWS_BLACKOUT_AFTER_MINUTES": 15,
  "MARKET_DATA_PROVIDER": "twelvedata",
  "NEWS_PROVIDER": "forexfactory",
  "MODE": "paper",
  "QUOTE_POLL_SECONDS": 10,
  "QUOTE_MAX_AGE_SECONDS": 120,
  "QUOTE_MAX_DEVIATION_PCT": 0.05,
  "TWELVE_DATA_API_KEY": "[REDACTED]",
  "TELEGRAM_BOT_TOKEN": "[REDACTED]",
  "TELEGRAM_CHAT_ID": "[REDACTED]",
  "USER_TIMEZONE": "UTC",
  "SCANNER_ENABLED": true,
  "SCANNER_INTERVAL_MINUTES": 60,
  "SCANNER_TIMEFRAMES": ["15m", "1h", "4h"],
  "SCANNER_AUTO_TRADE_PAPER": true,
  "SIGNAL_COOLDOWN_HOURS": 2,
  "PAPER_TRADING": true
}
```

---

## Phase 0: Safety and Baseline
- **Git Branch**: Created `feat/xauusd-liquidity-sweep` from `master`.
- **Baseline Test Suite**: Ran existing pytest suite (`241` tests collected):
  - **Result**: `241 passed, 1 warning in 165.18s`.
- **Secret Scanning**:
  - Scanned working tree and git history using regex detection patterns for API keys, database credentials, and bot tokens.
  - Findings:
    - `server/.env.example` line 34 contained an AlphaVantage key; cleaned to generic placeholder.
    - `server/DEPLOYMENT_GUIDE.md` contained example Telegram bot token format.
    - Git history contained historical commit diffs with bot tokens, database URLs, and API keys.
    - Verified `.env` files are strictly gitignored in `.gitignore`.
    - Sanitized `server/.env.example` so that all sensitive credentials hold placeholders only.
- **Database Safety & Migrations**:
  - Checked `server/app/core/database.py`: verified no `DROP TABLE` operations occur.
  - Initialized Alembic in `server/` and generated initial baseline revision (`46a42123bdb1_initial_schema.py`) representing the complete current schema.
  - Added strict hermetic isolation guard in `server/tests/conftest.py` that fails immediately with `RuntimeError` if `DATABASE_URL` points to PostgreSQL or any non-SQLite database during test runs.

---

## Phase 1: Twelve Data Only Data Layer
- **Deletions & Provider Factory**:
  - Deleted `server/app/services/market_data/yfinance_provider.py`.
  - Uninstalled `yfinance` package and removed `yfinance>=0.2.40` from `server/requirements.txt`.
  - Removed all Yahoo fallback branches from `TwelveDataProvider`, `IngestionService`, and `get_market_data_provider`.
  - Factory `get_market_data_provider`: strictly permits only `twelvedata`. Passing `mock` or `yahoo` raises `ValueError`. `MockMarketDataProvider` remains for tests only via explicit dependency injection.
- **TwelveDataProvider Implementation**:
  - Injected persistent `httpx.AsyncClient` from FastAPI application lifespan (`app.state.http_client`).
  - Standardized parameters: `symbol=XAU/USD`, `interval`, `timezone=UTC`, `outputsize`, `order=ASC`.
  - Defensive error handling: treats HTTP 200 with `{"status": "error"}` or `"code"` field as an error.
  - Forming-bar drop: dropped strictly by timestamp rule (`keep only if ts + delta <= now_utc`), never by index.
  - Price invariants: validated `high >= max(open, close)` and `low <= min(open, close)` with positive prices; invalid rows are rejected and tracked via `rejected_rows_count`.
- **Rate Limiting & Budget Tracking**:
  - Global token bucket (`TokenBucketRateLimiter`): 7.0 requests/minute.
  - Daily budget tracking: persisted in `api_usage (date, calls)` table (Alembic revision `8c3fca88f849_add_api_usage_table.py`); hard stop at 780 calls/day.
  - 429 backoff: sleeps 60s for the next minute window and retries up to 3 times; if still 429, logs ERROR and raises `TwelveDataRateLimitError` (marking data STALE).
- **Pure Resampling (`resample_ohlc`)**:
  - Fetches ONLY 15m candles from Twelve Data.
  - Pure function `resample_ohlc(candles_15m, tf)` builds UTC-anchored buckets for 30m (2 bars), 1h (4 bars), 4h (16 bars). Buckets are strictly omitted if incomplete.
  - Daily bar (1d) anchored at 17:00 America/New_York (DST-aware via `zoneinfo.ZoneInfo("America/New_York")`).
- **1h Resampling Sanity Check**:
  - Compared 100 native 1h bars from Twelve Data against 1h bars locally built from 15m bars:
    - Total bars compared: 99
    - Exact matches: 99
    - **Match Percentage: 100.00%** (open, high, low, close matched with <0.05 rounding tolerance).
- **15m History Depth Findings (Phase 1.4b)**:
  - Probed Twelve Data API using backward paging (`outputsize=5000` with `end_date`):
    - Earliest reachable 15m timestamp: **2023-03-10 18:45:00 UTC**
    - Continuous reachable history depth: **> 100,000 bars (over 3.5 years of 15m data)** on the free tier.
- **Empirical Market Calendar & Closed-Market Filtering (Phase 1.7 / Phase 3b)**:
  - **Correction of 24/7 Feed Misconception**: Analysis across 100,408 continuous 15m bars (2023-03 to 2026-11) revealed that Twelve Data fills market closures with synthetic placeholder bars. Median 15m bar range during active hours is ~$3.50–$5.00 USD, but collapses to ~$0.25–$0.28 USD on weekends and daily maintenance breaks.
  - **Spot-Gold Trading Hours**: Anchored in `America/New_York` (DST-aware via `zoneinfo.ZoneInfo("America/New_York")`):
    - Closes Friday at 17:00 NY (21:00 UTC EDT / 22:00 UTC EST).
    - Opens Sunday at 18:00 NY (22:00 UTC EDT / 23:00 UTC EST).
    - Daily maintenance break Mon–Thu 17:00–18:00 NY (21:00–22:00 UTC EDT / 22:00–23:00 UTC EST).
  - **Load-Time Filtration**: Pure, tested function `is_market_open(ts)` and `filter_open_market_candles()` drop closed-market bars at load time from all analysis inputs (ATR, pivots, pools, sessions, resampling) without mutating database records (12,898 placeholder bars dropped, retaining 87,510 open-market bars).
  - **Weekday 1h Resampling Sanity**: Re-running native 1h comparison exclusively on weekday open bars yields 145/145 exact matches (**100.00% match** within $0.05 tolerance).
  - **Freshness Logic**:
    - During weekend / daily breaks, data is marked `is_market_open=False` and is strictly **not STALE** (`is_stale=False`) if the break-start closing bar exists.
    - During active trading hours, data is **FRESH** if the latest expected closed 15m bar (`floor_15m(now_utc - 15m)`) exists in the database.
- **Data Cleanup & Re-Backfill (Phase 1.8)**:
  - Exported pre-purge CSV backup: `data/backups/candles_backup_20261115_151525.csv` (44,332 total rows).
  - Dry-run audit table:
    - Non-XAU/USD symbols: 22,918 rows
    - Non-15m timeframes: 14,955 rows
    - Misaligned 15m timestamps: 4,200 rows
    - Overlapping/duplicates: 0 rows
    - Total purged: 42,073 rows
    - Clean rows kept: 2,259 rows
  - Purged with `CONFIRM_PURGE=yes`.
  - Re-backfilled clean 15m data via `python -m app.scripts.backfill_twelvedata --start 2026-10-01 --end 2026-11-15`: 4,047 fresh 15m bars inserted with `source='twelvedata'`.
- **Health Diagnostic Endpoint (`/api/v1/health`)**:
  - Updated schema to expose: `last_closed_15m_bar_time`, `candle_age_seconds`, `is_data_fresh`, `data_freshness_status`, `credits_used_today`, `credits_max_budget` (780), `scheduler_running`, `last_sync_status`.

---

## Phase 2: Liquidity-Sweep Engine (`server/app/services/sweep/`)

### Strategy & Engine Configuration (`SweepConfig`)
```json
{
  "symbol": "XAU/USD",
  "atr_period": 14,
  "pivot_n_15m": 3,
  "pivot_n_htf": 2,
  "equal_level_threshold_atr": 0.1,
  "min_sweep_penetration_atr": 0.05,
  "max_rejection_bars": 3,
  "sweep_cooldown_bars": 8,
  "max_mss_bars": 12,
  "displacement_body_atr": 0.8,
  "displacement_body_ratio": 0.6,
  "zone_expiry_bars": 16,
  "stop_buffer_atr": 0.15,
  "spread_usd": 0.3,
  "slippage_usd": 0.1,
  "min_rr_tp1": 1.5,
  "strong_displacement_atr": 1.2,
  "high_rr_threshold": 2.0,
  "asia_start_hour_ny": 18,
  "asia_end_hour_ny": 0,
  "london_start_hour_ny": 3,
  "london_end_hour_ny": 7,
  "ny_prep_start_hour_ny": 9,
  "ny_prep_start_min_ny": 0,
  "ny_prep_end_hour_ny": 9,
  "ny_prep_end_min_ny": 30,
  "ny_window_start_hour_ny": 9,
  "ny_window_start_min_ny": 30,
  "ny_window_end_hour_ny": 10,
  "ny_window_end_min_ny": 30
}
```

### Components Built
1. **Volatility Unit (`atr.py`)**: Pure ATR(14) computation in USD without lookahead. All sweep penetration, equal level thresholds, displacement filters, and stop buffers use ATR multiples in USD.
2. **Fractal Pivots (`pivots.py`)**: Implements strict $N$-left/$N$-right fractal pivot detection ($N=3$ on 15m, $N=2$ on HTF 1h/4h). A pivot at index $k$ becomes known strictly at index $k+N$ (zero lookahead).
3. **Liquidity Pools (`pools.py`)**: Identifies resting liquidity pools:
   - Confirmed 15m swing highs/lows and 1h swing highs/lows.
   - Equal highs / equal lows: $\ge 2$ confirmed pivots within $0.10 \times \text{ATR}$ clustered together.
   - Previous-Day High / Low (PDH/PDL) anchored at 17:00 America/New_York (DST-aware).
   - Session liquidity: Asia (18:00–00:00 NY) and London (03:00–07:00 NY).
4. **Sweep Detection & SMC Execution (`detector.py`)**:
   - **Valid Sweep**: Wick penetrates beyond pool by $\ge 0.05 \times \text{ATR}$ and within $\le 3$ bars a close returns inside the level; continuous closes beyond the level are classified as breakouts and rejected.
   - **HTF Bias**: Evaluated from 1h structure (HH/HL = BULLISH, LH/LL = BEARISH).
   - **Market Structure Shift (MSS/CHoCH)**: Within 12 bars after the sweep, a displacement candle (body $\ge 0.8 \times \text{ATR}$ and $\ge 60\%$ of total range) closes beyond the most recent opposing confirmed pivot prior to or at the sweep.
   - **Entry Zone & Premium/Discount**: Limits placed at FVG midpoint (or Order Block open if no FVG). Shorts only valid in the premium half of the sweep-to-displacement range; longs only in the discount half. Entry zones expire after 16 bars.
   - **Stop Loss & Targets**: SL set at sweep extreme $+ 0.15 \times \text{ATR} + \text{spread}$. TP1 at nearest opposing liquidity pool; TP2 at next opposing pool. Setup is gated by $\text{RR}(\text{TP1}) \ge 1.5$; otherwise marked `NO_SETUP` with reason.
5. **Setup State Machine (`state_machine.py`)**:
   - Transitions: `POTENTIAL` (sweep detected) $\rightarrow$ `WAITING_CONFIRMATION` (rejection seen, awaiting MSS) $\rightarrow$ `CONFIRMED` (MSS + entry zone + $\text{RR} \ge 1.5$) $\rightarrow$ `INVALIDATED` (close beyond extreme or zone expired) / `NO_SETUP` (RR $< 1.5$ or no MSS within 12 bars).
   - Stable deterministic `setup_id`: 20-character hex hash of `(symbol, direction, pool_id, sweep_bar_time)`.
   - Structured `SetupChecklist` (12 objective boolean criteria; no unstructured text).
   - Objective Grades: Grade A (5–6 features), Grade B (3–4 features), Grade C (1–2 features) based on HTF alignment, major pool type, strong displacement ($\ge 1.2 \times \text{ATR}$), kill-zone timing, clean FVG, and $\text{RR} \ge 2.0$.
6. **Pure Evaluation Engine (`engine.py`)**:
   - Top-level `evaluate_sweep_market(candles_15m, candles_1h, candles_4h, as_of, config)` enforces strict `as_of` prefix filtering. Zero wall-clock calls (`datetime.now()`).

### Test Results
- **Hand-Built Synthetic Fixtures (8/8 Passed)**:
  - `test_clean_bearish_sweep_fixture`: Confirmed setup produced with Grade, valid SL/TP, and $\text{RR} \ge 1.5$.
  - `test_fake_out_breakout_fixture`: Consecutive closes beyond level correctly identified as breakout, not a sweep.
  - `test_equal_highs_sweep_fixture`: Clustered equal highs recognized as `EQUAL_HIGHS` pool and swept.
  - `test_late_rejection_after_4_bars_fails`: Rejection taking 4 bars fails $\le 3$ bar rule.
  - `test_no_mss_within_12_bars_yields_no_setup`: Transitioned to `NO_SETUP` with clear reason.
  - `test_expired_zone_fixture`: Transitioned to `INVALIDATED` after 16 bars without fill.
  - `test_invalidation_when_close_beyond_sweep_extreme`: Candle closing beyond sweep extreme immediately invalidates.
  - `test_rr_too_low_yields_no_setup`: $\text{RR} < 1.5$ transitioned to `NO_SETUP` with clear reason.
- **Engine Determinism Test**: PASSED. Identical input yields bit-identical `setup_id`, states, prices, and checklist fields.
- **PREFIX INVARIANCE Test (300 Bar Indices)**: PASSED across 300 randomly sampled evaluation bars $t \in [50, 480]$. For every $t$, outputs computed with `as_of = t` are bit-identical whether future bars after $t$ are omitted or replaced with random garbage numbers.

### Empirical Calendar & 15m History Depth Findings
- **Earliest Reachable 15m Timestamp**: **2023-03-10 18:45:00 UTC** via backward pagination on Twelve Data free tier (`outputsize=5000` with `end_date`), yielding **over 100,000 continuous 15m bars (> 3.5 years of history)**.
- **Trading Calendar & Gaps**: Twelve Data XAU/USD feed provides uninterrupted 24/7 quotes (0 gaps across 10,000 bars analyzed). Freshness logic unifies: weekend / daily breaks are `MARKET_CLOSED` (not STALE).

### ML4T Skills Checklist Application
- **`ml4t-lookahead-bias`**: **APPLIED**. All analysis functions receive explicit `as_of`. Candles where close time $> \text{as_of}$ are filtered out before feature derivation. Fractal pivots confirmed at $k+N$. Prefix invariance verified across 300 random points.
- **`ml4t-data-leakage`**: **APPLIED**. Pure functions only. No global state, no rolling window calculation extending past `as_of`, no future information leaking into pool identification or MSS detection.
- **`ml4t-transaction-costs`**: **APPLIED**. Fixed spread ($0.30 USD) and slippage ($0.10 USD) parameterized in `SweepConfig` and incorporated into stop loss and reward calculations.
- **`ml4t-validate-data`**: **APPLIED**. Strict OHLC validation invariants ($H \ge \max(O,C)$, $L \le \min(O,C)$, positive prices); invalid rows rejected and counted.
- **`ml4t-triple-barrier`**: **APPLIED**. Explicit upper barrier (TP1/TP2 from opposing pools), lower barrier (SL beyond sweep extreme + buffer + spread), and horizontal time barrier (zone expiration after 16 bars).
- **`ml4t-backtest-overfitting`**, **`ml4t-walk-forward-cv`**, **`ml4t-purging-embargo`**: **DEFERRED TO PHASE 3**. These skills apply specifically to the backtest harness, cross-validation splits, and parameter tuning grids implemented in Phase 3.

---

## Phase 3: Backtest Harness (`server/app/services/sweep/backtest/`)

### Architecture & Components Built
1. **Typed Data Models (`models.py`)**:
   - `TradePosition`: Tracks entry/exit timestamps, prices, exit reason (`TP1`, `SL`, `TIMEOUT`), $R$-multiple, P&L in USD, friction in USD and $R$, MFE in $R$, MAE in $R$, bars held, setup Grade, pool type, trading session, and HTF alignment.
   - `CandidateSetupRecord`: Logs every single candidate setup (all states, including `NO_SETUP` reasons and `INVALIDATED`), with forward outcome metrics (`reached_1r`, `reached_2r`, `hit_sl`, `mfe`, `mae`, `bars_to_resolution`, `r_multiple`).
   - `SliceMetrics`: Computes $n$ signals, $n$ executed trades, $n$ cluster-deduped, win rate, expectancy in $R$, 1,000-resample bootstrap 95% CI, profit factor, max drawdown in $R$, average friction in $R$, and statistical verdict.
   - `BacktestReport`: Container for overall metrics, slices, monthly equity, and random baseline.
2. **Pure Walk-Forward Simulation Engine (`engine.py`)**:
   - Reuses production `evaluate_sweep_market` with strict `as_of` prefix filtering.
   - **Fill Model**: Limit orders fill strictly when price trades *through* the zone price (Short: bar high > limit; Long: bar low < limit).
   - **Conservative Exit Rule**: When both SL and TP are touched in the same bar, the simulator assumes SL is hit first.
   - **Friction Accounting**: Deducts configured spread ($0.30 USD) and slippage ($0.10 USD) for a roundtrip cost of $0.40 USD.
   - **Single Position & Cooldown**: Only one open position at a time; exit cooldown (`cooldown_bars = 8`) suppresses immediate re-entries.
   - **Candidate Forward Tracking**: Every setup candidate is logged with forward 100-bar path metrics (MFE, MAE, 1R/2R hits, resolution time).
   - **News Filter**: Labeled `OFF` for historical simulation.
3. **Statistical Metrics & Guardrails (`metrics.py`)**:
   - Implements 1,000-resample bootstrap 95% Confidence Interval for expectancy in $R$.
   - **Sample Size Guardrail**: Slices with $n < 30$ are explicitly labeled `"n/a (n<30)"`.
   - **Edge Verdict**: Any edge verdict is strictly withheld unless $n \ge 100$ and the 95% bootstrap CI strictly excludes zero ($CI_{\text{lower}} > 0$).
   - Slices: by Grade (A, B, C), Session (Asia, London, NY, Other), HTF Alignment, Pool Type, Day of Week, and Monthly Equity Curve.
4. **Random-Entry Baseline (`baseline.py`)**:
   - Compares strategy outcomes against random coin-flip entries evaluated on identical execution timestamps, using identical SL/TP distance geometry and identical friction ($0.40 USD).
5. **Time Splits & Pre-Registered Tuning Grid (`tuning.py`)**:
   - **Purged & Embargoed Splits**: 60% Train / 20% Validation / 20% Test splits with 16-bar purge buffer and 8-bar embargo buffer (`ml4t-purging-embargo`).
   - **Pre-Registered Grid (18 Combinations $\le 24$)**:
     - `pivot_n_15m` $\in \{2, 3, 4\}$
     - `max_rejection_bars` $\in \{1, 2, 3\}$
     - `min_rr_tp1` $\in \{1.5, 2.0\}$
     - Evaluated on Train; confirmed on Validation; Test evaluated strictly once at the end.
6. **Report Formatter (`formatter.py`) & Runner Script (`run_sweep_backtest.py`)**:
   - CLI script `python -m app.scripts.run_sweep_backtest` loads 15m data, runs the pipeline, prints full markdown reports, and saves artifacts to `reports/`.

### Committed Test Results (`server/tests/test_sweep_backtest.py`)
All 7 tests passed hermetically:
- `test_random_walk_control_minus_friction`: **PASSED**. Ran across independent random walk paths with volatility calibrated to XAU/USD 15m ATR (~2.5 USD). Mean expectancy was negative ($\le 0.0$), confirming absence of lookahead or future data leaks.
- `test_harness_prefix_invariance`: **PASSED**. Verified that trade decisions and candidate logs up to bar $t$ are bit-identical when future bars are truncated vs replaced with random walk noise.
- `test_fill_model_requires_trading_through`: **PASSED**. Limit order does not fill when price touches; fills only when price trades strictly through the zone price.
- `test_same_bar_sl_and_tp_assumes_sl_first`: **PASSED**. Same-bar SL and TP touches exit at SL with negative $R$.
- `test_friction_and_cooldown`: **PASSED**. Spread and slippage correctly deducted; setups during cooldown are suppressed.
- `test_purged_time_splits_and_tuning_grid`: **PASSED**. Verified chronological split boundaries with purge/embargo buffers, and verified grid size is exactly 18 ($\le 24$).
- `test_bootstrap_ci_guardrail_under_30_trades`: **PASSED**. Verified that sample size $< 30$ produces explicit `"n/a (n<30)"` and withholds edge verdict.

### ML4T Skills Checklist Application
- **`ml4t-lookahead-bias`**: **APPLIED**. Production engine reused with strict `as_of`. Derived HTF bars (1h/4h) filtered so close time $\le \text{as_of}$. Harness prefix invariance verified.
- **`ml4t-data-leakage`**: **APPLIED**. Chronological 60/20/20 train/validation/test split. No test information visible during model/grid tuning.
- **`ml4t-transaction-costs`**: **APPLIED**. Real-world friction modeled: $0.30 spread + $0.10 slippage = $0.40 USD roundtrip deducted from all trades.
- **`ml4t-backtest-overfitting`**: **APPLIED**. Pre-registered parameter grid bounded to 18 combinations ($\le 24$). Parameter selection on Train, confirmation on Validation, single evaluation on Test.
- **`ml4t-walk-forward-cv`**: **APPLIED**. Strict bar-by-bar walk-forward simulation preserving temporal order.
- **`ml4t-purging-embargo`**: **APPLIED**. 16-bar purge window before boundaries; 8-bar embargo buffer after boundaries.
- **`ml4t-validate-data`**: **APPLIED**. Cleaned, source-tagged 15m candles from Twelve Data.
- **`ml4t-triple-barrier`**: **APPLIED**. Upper barrier (TP1/TP2), lower barrier (SL), time barrier (100-bar max holding timeout / 16-bar zone expiry).



---
