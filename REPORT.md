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
- **Empirical Market Calendar (Phase 1.7)**:
  - Analysis across 10,000 continuous 15m bars from Twelve Data shows that Twelve Data's XAU/USD feed provides unbroken 24/7 quotes with **0 gaps** across calendar weeks.
  - Freshness logic unifies:
    - During weekend / daily breaks, data is marked `MARKET_CLOSED` and is **not STALE** if the break-start closing bar exists.
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
