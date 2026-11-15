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
  "SCANNER_TIMEFRAMES": ["1h", "30m", "15m", "4h"],
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
  - Scanned repository working tree and complete git history using regex detection patterns for API keys, database credentials, and bot tokens.
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
