# QuantView Backend Services Documentation (`server/app/services/` & `core/`)

This document provides technical documentation of the backend packages and modules in QuantView as they exist in the repository on November 17, 2026. Every factual statement is supported by citations to exact file paths, line numbers, or read-only execution output obtained during this audit.

---

## Table of Contents

1. [Status Summary](#status-summary)
2. [Core Architecture (`app/core/`)](#core-architecture-appcore)
   - [app/core/config.py](#appcoreconfigpy)
   - [app/core/database.py](#appcoredatabasepy)
   - [app/core/logging.py](#appcoreloggingpy)
   - [app/core/normalization.py](#appcorenormalizationpy)
   - [app/core/time_utils.py](#appcoretime_utilspy)
3. [Market Data Service (`app/services/market_data/`)](#market-data-service-appservicesmarket_data)
   - [market_data/base.py](#market_databasepy)
   - [market_data/calendar.py](#market_datacalendarpy)
   - [market_data/freshness.py](#market_datafreshnesspy)
   - [market_data/ingestion.py](#market_dataingestionpy)
   - [market_data/mock_provider.py](#market_datamock_providerpy)
   - [market_data/resample.py](#market_dataresamplepy)
   - [market_data/symbols.py](#market_datasymbolspy)
   - [market_data/twelvedata_provider.py](#market_datatwelvedata_providerpy)
4. [Indicators Service (`app/services/indicators/`)](#indicators-service-appservicesindicators)
   - [indicators/atr_calculator.py](#indicatorsatr_calculatorpy)
   - [indicators/ema_calculator.py](#indicatorsema_calculatorpy)
   - [indicators/indicator_service.py](#indicatorsindicator_servicepy)
   - [indicators/price_action.py](#indicatorsprice_actionpy)
   - [indicators/rsi_calculator.py](#indicatorsrsi_calculatorpy)
5. [Liquidity Service (`app/services/liquidity/`)](#liquidity-service-appservicesliquidity)
   - [liquidity/liquidity_service.py](#liquidityliquidity_servicepy)
   - [liquidity/sr_detector.py](#liquiditysr_detectorpy)
   - [liquidity/sweep_detector.py](#liquiditysweep_detectorpy)
6. [Structure Service (`app/services/structure/`)](#structure-service-appservicesstructure)
   - [structure/bos_choch_detector.py](#structurebos_choch_detectorpy)
   - [structure/crt_analyzer.py](#structurecrt_analyzerpy)
   - [structure/ltf_confirmation.py](#structureltf_confirmationpy)
   - [structure/multi_timeframe.py](#structuremulti_timeframepy)
   - [structure/structure_engine.py](#structurestructure_enginepy)
   - [structure/swing_detector.py](#structureswing_detectorpy)
7. [Sweep Engine & Sweep Backtest (`app/services/sweep/`)](#sweep-engine--sweep-backtest-appservicessweep)
   - [sweep/config.py](#sweepconfigpy)
   - [sweep/atr.py](#sweepatrpy)
   - [sweep/pivots.py](#sweeppivotspy)
   - [sweep/pools.py](#sweeppoolspy)
   - [sweep/detector.py](#sweepdetectorpy)
   - [sweep/state_machine.py](#sweepstate_machinepy)
   - [sweep/engine.py](#sweepenginepy)
   - [sweep/backtest/models.py](#sweepbacktestmodelspy)
   - [sweep/backtest/metrics.py](#sweepbacktestmetricspy)
   - [sweep/backtest/baseline.py](#sweepbacktestbaselinepy)
   - [sweep/backtest/engine.py](#sweepbacktestenginepy)
   - [sweep/backtest/tuning.py](#sweepbacktesttuningpy)
   - [sweep/backtest/formatter.py](#sweepbacktestformatterpy)
8. [Trading Strategies (`app/services/strategies/`)](#trading-strategies-appservicesstrategies)
   - [strategies/base.py](#strategiesbasepy)
   - [strategies/strategy_manager.py](#strategiesstrategy_managerpy)
   - [strategies/smc_strategy.py](#strategiessmc_strategypy)
   - [strategies/range_strategy.py](#strategiesrange_strategypy)
   - [strategies/crt_strategy.py](#strategiescrt_strategypy)
   - [strategies/crt/daily_bias.py](#strategiescrtdaily_biaspy)
   - [strategies/crt/confirmation.py](#strategiescrtconfirmationpy)
   - [strategies/crt/entry.py](#strategiescrtentrypy)
   - [strategies/crt/targets.py](#strategiescrttargetspy)
   - [strategies/crt/tiers.py](#strategiescrttierspy)
   - [strategies/crt/lifecycle.py](#strategiescrtlifecyclepy)
   - [strategies/crt/backtest_adapter.py](#strategiescrtbacktest_adapterpy)
9. [Signals Service (`app/services/signals/`)](#signals-service-appservicessignals)
   - [signals/confluence_engine.py](#signalsconfluence_enginepy)
   - [signals/evaluators.py](#signalsevaluatorspy)
   - [signals/path_validator.py](#signalspath_validatorpy)
   - [signals/risk_manager.py](#signalsrisk_managerpy)
   - [signals/scoring_engine.py](#signalsscoring_enginepy)
   - [signals/signal_generator.py](#signalssignal_generatorpy)
10. [News Service (`app/services/news/`)](#news-service-appservicesnews)
    - [news/base.py](#newsbasepy)
    - [news/forexfactory_provider.py](#newsforexfactory_providerpy)
    - [news/mock_provider.py](#newsmock_providerpy)
    - [news/ingestion.py](#newsingestionpy)
    - [news/filter_engine.py](#newsfilter_enginepy)
11. [Paper Trading Service (`app/services/paper_trading/`)](#paper-trading-service-appservicespaper_trading)
    - [paper_trading/account_manager.py](#paper_tradingaccount_managerpy)
    - [paper_trading/order_executor.py](#paper_tradingorder_executorpy)
    - [paper_trading/position_manager.py](#paper_tradingposition_managerpy)
    - [paper_trading/paper_service.py](#paper_tradingpaper_servicepy)
12. [Backtesting Service (`app/services/backtesting/`)](#backtesting-service-appservicesbacktesting)
    - [backtesting/performance_metrics.py](#backtestingperformance_metricspy)
    - [backtesting/backtest_engine.py](#backtestingbacktest_enginepy)
    - [backtesting/backtest_service.py](#backtestingbacktest_servicepy)
    - [backtesting/optimization.py](#backtestingoptimizationpy)
    - [backtesting/walk_forward_harness.py](#backtestingwalk_forward_harnesspy)
13. [Telegram Service (`app/services/telegram/`)](#telegram-service-appservicestelegram)
    - [telegram/client.py](#telegramclientpy)
    - [telegram/command_handler.py](#telegramcommand_handlerpy)
    - [telegram/message_formatter.py](#telegrammessage_formatterpy)
    - [telegram/scanner.py](#telegramscannerpy)
    - [telegram/scheduler.py](#telegramschedulerpy)
    - [telegram/telegram_service.py](#telegramtelegram_servicepy)

---

## Status Summary

The table below lists every service and core module under `server/app/core/` and `server/app/services/`, its status (ACTIVE, PARTIAL, DEAD, DEPRECATED), and import proof. Status definition:
- **ACTIVE**: Directly or transitively imported from runtime entry points (`app.main`, `scheduler`, `scanner`, API routers).
- **PARTIAL**: Reachable only from standalone CLI scripts (`scripts/run_sweep_backtest.py`, `scripts/backfill_twelvedata.py`, `scripts/backtest_report.py`) or imported only by inactive modules.
- **DEAD**: Zero references in production application code or scripts (only imported in unit tests, or completely unreferenced).
- **DEPRECATED**: Module docstring explicitly declares deprecation. (None found in codebase).

| Module | Lines | Status | Proof / Importers |
| :--- | :---: | :---: | :--- |
| `app/core/config.py` | 167 | **ACTIVE** | `app.main`, `api.deps`, `api.v1.*`, `services.telegram.*` (39 files) |
| `app/core/database.py` | 87 | **ACTIVE** | `app.main`, `api.deps`, `models.*`, `services.telegram.scheduler` (26 files) |
| `app/core/logging.py` | 32 | **ACTIVE** | `app.main`, `services.signals.*`, `services.strategies.*` (36 files) |
| `app/core/normalization.py` | 91 | **ACTIVE** | `services.news.forexfactory_provider`, `services.news.ingestion` (2 files) |
| `app/core/time_utils.py` | 74 | **DEAD** | Zero application callers. Only referenced in `tests/test_time_utils.py` |
| `app/services/market_data/base.py` | 60 | **ACTIVE** | `services.market_data.ingestion`, `services.market_data.mock_provider`, `api.v1.market` |
| `app/services/market_data/calendar.py` | 84 | **ACTIVE** | `services.market_data.freshness`, `services.market_data.resample`, `services.market_data.__init__` |
| `app/services/market_data/freshness.py` | 287 | **ACTIVE** | `services.market_data.ingestion`, `services.market_data.twelvedata_provider`, `api.v1.health` |
| `app/services/market_data/ingestion.py` | 371 | **ACTIVE** | `api.v1.market`, `services.market_data.__init__` |
| `app/services/market_data/mock_provider.py` | 123 | **ACTIVE** | `services.market_data.__init__`, `services.telegram.command_handler` |
| `app/services/market_data/resample.py` | 191 | **ACTIVE** | `services.market_data.ingestion`, `services.sweep.backtest.engine` |
| `app/services/market_data/symbols.py` | 169 | **ACTIVE** | `api.v1.market`, `services.market_data.twelvedata_provider`, `services.signals.risk_manager` |
| `app/services/market_data/twelvedata_provider.py` | 397 | **ACTIVE** | `services.market_data.__init__`, `api.v1.health` |
| `app/services/indicators/atr_calculator.py` | 108 | **ACTIVE** | `services.indicators.indicator_service`, `services.indicators.__init__` |
| `app/services/indicators/ema_calculator.py` | 110 | **ACTIVE** | `services.indicators.indicator_service`, `services.indicators.__init__` |
| `app/services/indicators/indicator_service.py` | 236 | **ACTIVE** | `api.deps`, `api.v1.indicators`, `services.signals.confluence_engine` |
| `app/services/indicators/price_action.py` | 222 | **ACTIVE** | `services.indicators.indicator_service`, `services.indicators.__init__` |
| `app/services/indicators/rsi_calculator.py` | 203 | **ACTIVE** | `services.indicators.indicator_service`, `services.indicators.__init__` |
| `app/services/liquidity/liquidity_service.py` | 288 | **ACTIVE** | `api.deps`, `api.v1.liquidity`, `services.signals.confluence_engine` |
| `app/services/liquidity/sr_detector.py` | 216 | **ACTIVE** | `services.liquidity.liquidity_service`, `services.liquidity.__init__` |
| `app/services/liquidity/sweep_detector.py` | 188 | **ACTIVE** | `services.liquidity.liquidity_service`, `services.liquidity.__init__` |
| `app/services/structure/bos_choch_detector.py` | 238 | **ACTIVE** | `services.liquidity.liquidity_service`, `services.structure.ltf_confirmation` |
| `app/services/structure/crt_analyzer.py` | 295 | **ACTIVE** | `services.strategies.crt_strategy`, `services.structure.__init__` |
| `app/services/structure/ltf_confirmation.py` | 160 | **ACTIVE** | `services.strategies.smc_strategy`, `services.signals.confluence_engine` |
| `app/services/structure/multi_timeframe.py` | 223 | **ACTIVE** | `services.structure.__init__`, `api.v1.structure` |
| `app/services/structure/structure_engine.py` | 363 | **ACTIVE** | `api.deps`, `api.v1.structure`, `services.liquidity.liquidity_service` |
| `app/services/structure/swing_detector.py` | 147 | **ACTIVE** | `services.indicators.indicator_service`, `services.structure.structure_engine` |
| `app/services/sweep/config.py` | 49 | **PARTIAL** | `scripts.run_sweep_backtest`, `services.sweep.*`, `services.strategies.crt.backtest_adapter` |
| `app/services/sweep/atr.py` | 42 | **PARTIAL** | `services.sweep.engine`, `services.sweep.__init__` |
| `app/services/sweep/pivots.py` | 86 | **PARTIAL** | `services.sweep.engine`, `services.sweep.detector`, `services.sweep.pools` |
| `app/services/sweep/pools.py` | 224 | **PARTIAL** | `services.sweep.engine`, `services.sweep.detector` |
| `app/services/sweep/detector.py` | 450 | **PARTIAL** | `services.sweep.engine`, `services.sweep.state_machine` |
| `app/services/sweep/state_machine.py` | 98 | **PARTIAL** | `services.sweep.engine`, `services.sweep.backtest.engine` |
| `app/services/sweep/engine.py` | 425 | **PARTIAL** | `services.sweep.backtest.engine`, `scripts.run_sweep_backtest` |
| `app/services/sweep/backtest/models.py` | 101 | **PARTIAL** | `services.sweep.backtest.*`, `services.strategies.crt.backtest_adapter` |
| `app/services/sweep/backtest/metrics.py` | 114 | **PARTIAL** | `services.sweep.backtest.baseline`, `services.sweep.backtest.tuning` |
| `app/services/sweep/backtest/baseline.py` | 145 | **PARTIAL** | `services.sweep.backtest.tuning`, `scripts.backtest_report` |
| `app/services/sweep/backtest/engine.py` | 392 | **PARTIAL** | `scripts.run_sweep_backtest`, `services.sweep.backtest.tuning` |
| `app/services/sweep/backtest/tuning.py` | 177 | **PARTIAL** | `scripts.run_sweep_backtest`, `services.sweep.backtest.__init__` |
| `app/services/sweep/backtest/formatter.py` | 102 | **PARTIAL** | `scripts.run_sweep_backtest`, `services.sweep.backtest.__init__` |
| `app/services/strategies/base.py` | 74 | **ACTIVE** | `services.strategies.strategy_manager`, `services.strategies.*` |
| `app/services/strategies/strategy_manager.py` | 118 | **ACTIVE** | `services.signals.confluence_engine`, `api.deps` |
| `app/services/strategies/smc_strategy.py` | 171 | **ACTIVE** | `services.strategies.strategy_manager` (lazy imported line 43) |
| `app/services/strategies/range_strategy.py` | 482 | **ACTIVE** | `services.strategies.strategy_manager` (lazy imported line 44) |
| `app/services/strategies/crt_strategy.py` | 1484 | **ACTIVE** | `services.strategies.strategy_manager` (lazy imported line 45) |
| `app/services/strategies/crt/daily_bias.py` | 209 | **ACTIVE** | `services.strategies.crt_strategy` (line 38) |
| `app/services/strategies/crt/confirmation.py` | 238 | **ACTIVE** | `services.strategies.crt_strategy` (line 41) |
| `app/services/strategies/crt/entry.py` | 210 | **ACTIVE** | `services.strategies.crt_strategy` (line 40) |
| `app/services/strategies/crt/targets.py` | 226 | **ACTIVE** | `services.strategies.crt_strategy` (line 39) |
| `app/services/strategies/crt/tiers.py` | 75 | **ACTIVE** | `services.strategies.crt_strategy` (line 42) |
| `app/services/strategies/crt/lifecycle.py` | 189 | **ACTIVE** | `services.strategies.crt_strategy` (line 43) |
| `app/services/strategies/crt/backtest_adapter.py` | 112 | **DEAD** | Exported in `strategies/crt/__init__.py`; zero active/script callers; 0 tests |
| `app/services/signals/confluence_engine.py` | 681 | **ACTIVE** | `services.signals.signal_generator`, `api.deps` |
| `app/services/signals/evaluators.py` | 587 | **ACTIVE** | `services.signals.confluence_engine`, `services.strategies.smc_strategy` |
| `app/services/signals/path_validator.py` | 211 | **ACTIVE** | `services.signals.confluence_engine`, `services.strategies.crt.targets` |
| `app/services/signals/risk_manager.py` | 141 | **ACTIVE** | `services.signals.confluence_engine`, `services.paper_trading.order_executor` |
| `app/services/signals/scoring_engine.py` | 119 | **ACTIVE** | `services.signals.signal_generator`, `api.deps` |
| `app/services/signals/signal_generator.py` | 636 | **ACTIVE** | `services.telegram.scheduler`, `services.telegram.scanner`, `api.deps` |
| `app/services/news/base.py` | 34 | **ACTIVE** | `services.news.forexfactory_provider`, `services.news.mock_provider` |
| `app/services/news/forexfactory_provider.py` | 123 | **ACTIVE** | `services.telegram.scheduler`, `services.news.__init__` |
| `app/services/news/mock_provider.py` | 79 | **ACTIVE** | `services.news.__init__`, `services.telegram.command_handler` |
| `app/services/news/ingestion.py` | 299 | **ACTIVE** | `api.v1.news`, `services.news.__init__` |
| `app/services/news/filter_engine.py` | 261 | **ACTIVE** | `services.signals.confluence_engine`, `api.v1.news` |
| `app/services/paper_trading/account_manager.py` | 226 | **ACTIVE** | `services.paper_trading.order_executor`, `services.paper_trading.paper_service` |
| `app/services/paper_trading/order_executor.py` | 426 | **ACTIVE** | `services.paper_trading.paper_service`, `services.telegram.scanner` |
| `app/services/paper_trading/position_manager.py` | 342 | **ACTIVE** | `services.paper_trading.paper_service`, `services.paper_trading.__init__` |
| `app/services/paper_trading/paper_service.py` | 225 | **ACTIVE** | `services.telegram.scheduler`, `api.deps`, `api.v1.paper` |
| `app/services/backtesting/performance_metrics.py` | 197 | **ACTIVE** | `services.backtesting.backtest_engine`, `services.backtesting.__init__` |
| `app/services/backtesting/backtest_engine.py` | 594 | **ACTIVE** | `services.backtesting.backtest_service`, `services.backtesting.optimization` |
| `app/services/backtesting/backtest_service.py` | 311 | **ACTIVE** | `api.deps`, `api.v1.backtest` |
| `app/services/backtesting/optimization.py` | 117 | **ACTIVE** | `services.backtesting.backtest_service`, `api.v1.backtest` |
| `app/services/backtesting/walk_forward_harness.py` | 700 | **PARTIAL** | Imported in `backtesting/__init__.py`; called in `scripts.backtest_report`; tested in `test_walk_forward_harness.py` |
| `app/services/telegram/client.py` | 224 | **ACTIVE** | `services.telegram.scheduler`, `services.telegram.command_handler`, `services.telegram.scanner` |
| `app/services/telegram/command_handler.py` | 403 | **ACTIVE** | `services.telegram.telegram_service`, `services.telegram.__init__` |
| `app/services/telegram/message_formatter.py` | 589 | **ACTIVE** | `services.telegram.scanner`, `services.telegram.command_handler` |
| `app/services/telegram/scanner.py` | 617 | **ACTIVE** | `services.telegram.scheduler`, `services.telegram.telegram_service` |
| `app/services/telegram/scheduler.py` | 181 | **ACTIVE** | `app.main` (lines 13-16, 38, 45), `api.v1.health` |
| `app/services/telegram/telegram_service.py` | 71 | **ACTIVE** | `app.services.telegram.__init__`, `api.deps` |

**Totals across core and services:**
- **ACTIVE**: 59 modules
- **PARTIAL**: 14 modules (`services/sweep/*` 13 modules + `services/backtesting/walk_forward_harness.py`)
- **DEAD**: 2 modules (`core/time_utils.py`, `services/strategies/crt/backtest_adapter.py`)
- **DEPRECATED**: 0 modules

---

## Core Architecture (`app/core/`)

### app/core/config.py
- **Purpose**: Defines application settings, environment variables, validation rules, and symbol/timeframe lists via Pydantic BaseSettings.
- **Status**: ACTIVE. Imported by 39 modules across `server/app` including `app.main` [L7], `api.deps` [L25], `services.telegram.scheduler` [L9].
- **Public interface**:
  - `class Settings(BaseSettings)` [L29-L163]
  - `settings = Settings()` instance [L166]
  - `ACTIVE_SYMBOLS = ("XAU/USD",)` tuple [L16]
- **Inputs/outputs**: Reads environment variables from system and `.env` file via `SettingsConfigDict(env_file=".env", extra="ignore")` [L161-L163]. Emits strongly typed `Settings` instance.
- **Key algorithms and parameters**:
  - `MODE`: `'paper'` default (`'live'` triggers provider guard in `main.py:25`) [L32]
  - `MARKET_DATA_PROVIDER`: `'twelvedata'` [L39]
  - `NEWS_PROVIDER`: `'forexfactory'` [L46]
  - `MAX_RISK_PERCENT`: `0.5%` (range 0.1 to 5.0) [L71]
  - `MIN_RR_TP1`: `2.0` (range 1.0 to 10.0) [L76]
  - `MIN_RR_TP2`: `3.0` [L81]
  - `MIN_SETUP_SCORE`: `75.0` (range 0.0 to 100.0) [L86]
  - `SIGNAL_COOLDOWN_HOURS`: `2` hours [L91]
  - `SCANNER_INTERVAL_MINUTES`: `15` [L107]
  - `SCANNER_TIMEFRAMES`: `["1h", "15m"]` [L108]
  - `SUPPORTED_SYMBOLS`: `["XAU/USD"]` (derived from `ACTIVE_SYMBOLS`) [L19, L110]
- **Dependencies**: `pydantic_settings.BaseSettings`, `pydantic.Field`, `pydantic.AliasChoices`.
- **Side effects**: Reads environment variables and `.env` file at import time.
- **Lookahead / determinism notes**: Deterministic configuration parsing; no time calls.
- **Tests**: Covered by `tests/conftest.py`, `tests/test_candle_fallback_and_webhook.py::test_us100_quarantine_config`, `tests/test_phase1_data_layer.py`.
- **Known issues and risks**: Defines 11 unused fields: `ALPHA_VANTAGE_API_KEY`, `ATR_PERIOD`, `CRT_ENTRY_EXPIRY_BARS`, `CRT_MAX_RANGE_ATR_MULT`, `CRT_MAX_RISK_ATR_MULT`, `CRT_MIN_RANGE_ATR_MULT`, `CRT_MIN_RR_TP1`, `CRT_MIN_SWEEP_ATR_MULT`, `EMA_FAST`, `EMA_MID`, `EMA_SLOW`, `RSI_PERIOD`, `YAHOO_GOLD_SYMBOL`. CRT modules hardcode these values rather than referencing `settings.CRT_*`.

### app/core/database.py
- **Purpose**: Establishes SQLAlchemy database engine, session factory (`SessionLocal`), base declarative model class, and `init_db()` table creation.
- **Status**: ACTIVE. Imported by `app.main` [L9], `api.deps` [L7], `services.telegram.scheduler` [L10], and 23 other modules.
- **Public interface**:
  - `Base = declarative_base()` [L17]
  - `engine = create_engine(...)` [L20-L32]
  - `SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)` [L34]
  - `def get_db() -> Generator[Session, None, None]` [L39-L44]
  - `def init_db()` [L47-L86]
- **Inputs/outputs**: Database connection URL from `settings.DATABASE_URL`. Yields SQLAlchemy `Session`.
- **Key algorithms and parameters**:
  - For SQLite: applies `connect_args={"check_same_thread": False}` [L26].
  - For PostgreSQL: applies connection pooling with `pool_size=10`, `max_overflow=20`, `pool_timeout=30`, `pool_recycle=1800`, `pool_pre_ping=True` [L28-L32].
  - `init_db()` calls `Base.metadata.create_all(bind=engine)` [L78].
- **Dependencies**: `sqlalchemy`, `app.core.config.settings`, `app.core.logging.logger`.
- **Side effects**: Establishes connection pools; executes DDL (`create_all`) on startup.
- **Lookahead / determinism notes**: Stateless DB connection manager.
- **Tests**: Covered by `tests/conftest.py` (pins in-memory SQLite), `tests/test_duplicate_integrity.py`, `tests/test_models.py`.
- **Known issues and risks**: `Base.metadata.create_all` creates all tables on startup, which bypasses Alembic migration tracking if a blank DB is started.

### app/core/logging.py
- **Purpose**: Configures structured centralized logging with ISO UTC timestamps and level formatting.
- **Status**: ACTIVE. Imported by 36 files across the server.
- **Public interface**:
  - `logger = logging.getLogger("quantview")` [L31]
  - `def setup_logging() -> logging.Logger` [L12-L29]
- **Inputs/outputs**: Reads `settings.LOG_LEVEL`. Outputs formatted log stream to stderr.
- **Key algorithms and parameters**: Formats lines as `%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s` [L18]. Uses `logging.Formatter.converter = lambda *args: datetime.now(timezone.utc).timetuple()` [L24].
- **Dependencies**: `logging`, `sys`, `datetime.timezone`, `app.core.config.settings`.
- **Side effects**: Modifies root logging handler on import/execution.
- **Lookahead / determinism notes**: Calls `datetime.now(timezone.utc)` only for log line emission timestamps.
- **Tests**: No dedicated test file, exercised transitively across all test executions.
- **Known issues and risks**: None.

### app/core/normalization.py
- **Purpose**: Provides string normalizers for symbols, timeframes, and UTC datetimes across news and generic inputs.
- **Status**: ACTIVE. Imported by `services.news.forexfactory_provider` [L10] and `services.news.ingestion` [L17].
- **Public interface**:
  - `def normalize_symbol(raw_symbol: str) -> str` [L50-L73]
  - `def normalize_timeframe(raw_timeframe: str) -> str` [L76-L82]
  - `def normalize_utc_datetime(dt: Optional[datetime]) -> Optional[datetime]` [L85-L91]
- **Inputs/outputs**: Raw string or datetime in; sanitized string or UTC datetime out.
- **Key algorithms and parameters**:
  - `SYMBOL_MAP`: Static dictionary mapping 12 forex pairs and aliases (e.g. `"XAUUSD": "XAU/USD"`, `"GOLD": "XAU/USD"`) [L13-L27].
  - Fallback logic: if string is 6 alpha characters, converts to `f"{cleaned[:3]}/{cleaned[3:]}"` [L70-L71]. Never raises error; returns raw string on unknown symbol.
- **Dependencies**: `datetime.timezone`, `typing.Optional`.
- **Side effects**: None (pure utility functions).
- **Lookahead / determinism notes**: Deterministic string transformation.
- **Tests**: Covered by `tests/test_duplicate_integrity.py`.
- **Known issues and risks**: Duplicated by `services/market_data/symbols.py:normalize_symbol`. The core normalization function is permissive and guesses, while `market_data/symbols.py` is strict and raises `UnknownSymbolError`.

### app/core/time_utils.py
- **Purpose**: Converts UTC datetimes to user local time for display purposes.
- **Status**: DEAD. Zero callers in `server/app` or `server/scripts`. Only imported in `tests/test_time_utils.py`.
- **Public interface**:
  - `def format_local_time(utc_dt: Optional[datetime], timezone_str: Optional[str] = None) -> str` [L26-L53]
  - `def get_local_now(timezone_str: Optional[str] = None) -> datetime` [L56-L74]
- **Inputs/outputs**: UTC `datetime` input; formatted string `"%Y-%m-%d %H:%M:%S %Z"` output.
- **Key algorithms and parameters**: Resolves timezone via `pytz.timezone(tz_name)`. Falls back to `pytz.utc` on `UnknownTimeZoneError`.
- **Dependencies**: `pytz`, `datetime`, `app.core.config.settings`, `app.core.logging.logger`.
- **Side effects**: None.
- **Lookahead / determinism notes**: `get_local_now()` calls `datetime.now(timezone.utc)`.
- **Tests**: Covered by `tests/test_time_utils.py` (7 tests: `test_naive_utc_datetime_converted_to_local`, `test_timezone_aware_utc_datetime_converted`, `test_default_utc_configuration`, `test_explicit_timezone_override`, `test_invalid_timezone_fallback_to_utc`, `test_none_datetime_handling`, `test_backend_utc_integrity`).
- **Known issues and risks**: Dead code. The application uses `zoneinfo.ZoneInfo` in `services/market_data/calendar.py` and `services/strategies/crt_strategy.py`, while this file uses `pytz`.

---

## Market Data Service (`app/services/market_data/`)

### market_data/base.py
- **Purpose**: Defines abstract base class `BaseMarketDataProvider` for market data feeds.
- **Status**: ACTIVE. Imported by `services.market_data.ingestion` [L11], `services.market_data.mock_provider` [L15], and `api.v1.market` [L17].
- **Public interface**:
  - `class BaseMarketDataProvider(ABC)` [L14-L59]
  - Methods: `get_candles()`, `get_latest_candle()`, `get_quote()`, `health_check()`
- **Inputs/outputs**: Returns `List[CandleCreate]`, `Optional[CandleCreate]`, `QuoteResponse`, `Dict[str, Any]`.
- **Key algorithms and parameters**: Abstract interface with pure `@abstractmethod` signatures.
- **Dependencies**: `abc.ABC`, `app.schemas.candle.CandleCreate`, `app.schemas.market.QuoteResponse`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Interface definition only.
- **Tests**: Transitive coverage via `tests/test_market_data_provider.py`.
- **Known issues and risks**: None.

### market_data/calendar.py
- **Purpose**: Implements Spot Gold (XAU/USD) trading calendar rules, DST-aware market hours, and closed-market bar filtering.
- **Status**: ACTIVE. Imported by `services.market_data.freshness` [L12], `services.market_data.resample` [L11], `services.market_data.__init__` [L19], and `scripts/run_sweep_backtest.py` [L13].
- **Public interface**:
  - `def is_market_open(ts: Optional[datetime]) -> bool` [L21-L58]
  - `def filter_open_market_candles(candles: Sequence[T]) -> List[T]` [L61-L63]
  - `def is_forex_weekend(ts: Optional[datetime] = None) -> bool` [L66-L84]
- **Inputs/outputs**: Accepts UTC `datetime` or sequence of candle objects. Returns boolean or filtered list.
- **Key algorithms and parameters**:
  - Timezone: `NY_TZ = ZoneInfo("America/New_York")` [L15].
  - Spot Gold trading week schedule:
    - Friday: Closes at 17:00 America/New_York [L41-L43].
    - Saturday: Closed all day [L45-L47].
    - Sunday: Opens at 18:00 America/New_York [L49-L51].
    - Monday–Thursday: Daily maintenance break from 17:00 to 18:00 America/New_York [L53-L56].
- **Dependencies**: `zoneinfo.ZoneInfo`, `datetime.timezone`.
- **Side effects**: None (pure filtering functions).
- **Lookahead / determinism notes**: Zero lookahead. Filters based purely on timestamp.
- **Tests**: Covered by `tests/test_market_calendar.py` (5 tests: `test_market_open_regular_trading_hours`, `test_market_closed_friday_evening_and_weekend`, `test_market_closed_daily_maintenance_break`, `test_filter_open_market_candles`, `test_dst_transition_preserves_ny_schedule`).
- **Known issues and risks**: `is_forex_weekend` is duplicated in `services/market_data/freshness.py:54`. The `freshness.py` version uses hardcoded UTC hours without DST awareness, creating a 1-hour discrepancy during DST shifts.

### market_data/freshness.py
- **Purpose**: Candle closed-state validation, data staleness detection, and candle timestamp logging.
- **Status**: ACTIVE. Imported by `services.market_data.ingestion` [L13], `services.market_data.twelvedata_provider` [L18], `api.v1.health` [L14].
- **Public interface**:
  - `def get_timeframe_delta(timeframe: str) -> timedelta` [L36-L42]
  - `def ensure_utc_datetime(dt: Optional[datetime]) -> Optional[datetime]` [L45-L51]
  - `def is_forex_weekend(timestamp: Optional[datetime] = None) -> bool` [L54-L73]
  - `def is_candle_closed(candle_timestamp: datetime, timeframe: str, as_of: Optional[datetime] = None) -> bool` [L76-L94]
  - `def filter_closed_candles(candles: Sequence[T], timeframe: str, as_of: Optional[datetime] = None) -> List[T]` [L97-L123]
  - `def get_latest_closed_candle(candles: Sequence[T], timeframe: str, as_of: Optional[datetime] = None) -> Optional[T]` [L126-L150]
  - `def check_data_staleness(...) -> Tuple[bool, str, Optional[int]]` [L153-L242]
  - `def format_candle_log_line(...) -> str` [L245-L269]
  - `def log_latest_candle(...)` [L272-L286]
- **Inputs/outputs**: Accepts candle sequences, timeframe strings, optional `as_of` timestamp. Returns filtered candle lists or `(is_stale, reason, age_seconds)`.
- **Key algorithms and parameters**:
  - Closed candle rule: `candle_timestamp + timeframe_delta <= as_of` [L94].
  - Multiplier thresholds for staleness: 15m allows 2.5x delta (37.5 min); 1h allows 2.0x (120 min); 4h allows 1.5x (360 min) [L185-L188].
  - If current time is Forex weekend or closed market, flags `is_stale=False` with `"MARKET_CLOSED"` [L173-L177].
- **Dependencies**: `datetime`, `app.core.logging.logger`, `app.services.market_data.calendar.is_market_open`.
- **Side effects**: Emits log lines via `logger.info`.
- **Lookahead / determinism notes**: Accepts explicit `as_of` parameter for replay determinism. Falls back to `datetime.now(timezone.utc)` when `as_of` is None.
- **Tests**: Covered by `tests/test_data_freshness.py` (11 tests).
- **Known issues and risks**: Duplicated `is_forex_weekend` function at line 54 uses hardcoded UTC (Friday 21:00 UTC to Sunday 21:00 UTC), conflicting with `calendar.py:is_forex_weekend`.

### market_data/ingestion.py
- **Purpose**: Persists raw and resampled candles to the database with duplicate elimination and gap detection.
- **Status**: ACTIVE. Imported by `api.v1.market` [L16], `services.market_data.__init__` [L32].
- **Public interface**:
  - `class MarketDataIngestionService` [L23-L370]
    - `ingest_candles(db, symbol, timeframe, candles, source)` [L31-L105]
    - `sync_symbol_data(db, symbol, timeframe, limit)` [L108-L150]
    - `resample_and_store(db, symbol, source_tf, target_tf)` [L153-L225]
    - `audit_candles(...)` [L228-L285]
    - `detect_gaps(db, symbol, timeframe)` [L288-L370]
- **Inputs/outputs**: Accepts SQLAlchemy `Session`, candle data models; writes to `candles` table.
- **Key algorithms and parameters**:
  - Bulk upsert via dialect-specific SQL (SQLite `ON CONFLICT DO UPDATE` or PostgreSQL `ON CONFLICT DO UPDATE`) [L65-L95].
  - Filters closed candles prior to storage if `filter_closed=True`.
- **Dependencies**: `SQLAlchemy`, `app.models.candle.Candle`, `app.services.market_data.resample.resample_ohlc`.
- **Side effects**: Writes, updates, and commits records in `candles` table.
- **Lookahead / determinism notes**: Database operations are deterministic based on candle timestamps.
- **Tests**: Covered by `tests/test_ingestion_pipeline.py` (6 tests), `tests/test_audit_candles.py`.
- **Known issues and risks**: None.

### market_data/mock_provider.py
- **Purpose**: Deterministic synthetic candle generator for unit testing and offline development.
- **Status**: ACTIVE. Used as fallback/test provider; imported in `services.market_data.__init__` [L26] and `services.telegram.command_handler` [L35].
- **Public interface**:
  - `class MockMarketDataProvider(BaseMarketDataProvider)` [L25-L122]
- **Inputs/outputs**: Returns synthetic `List[CandleCreate]` with realistic random-walk OHLC geometry.
- **Key algorithms and parameters**: Generates candles with base prices ($2,000 for XAU/USD, 1.0850 for EUR/USD) and sine-wave drift [L55-L85].
- **Dependencies**: `app.services.market_data.base.BaseMarketDataProvider`.
- **Side effects**: None (in-memory generation).
- **Lookahead / determinism notes**: Uses static seed or timestamp offset; no external lookahead.
- **Tests**: Covered by `tests/test_market_data_provider.py`, `tests/test_candle_fallback_and_webhook.py`.
- **Known issues and risks**: In `app.main:25`, starting the server with `MODE=live` and `MARKET_DATA_PROVIDER=mock` raises `RuntimeError("FATAL: Cannot run in LIVE mode with MOCK market data provider.")`.

### market_data/resample.py
- **Purpose**: Pure resampling of lower timeframe (15m) candles into higher timeframes (30m, 1h, 4h, 1d) with zero lookahead.
- **Status**: ACTIVE. Imported by `services.market_data.ingestion` [L16] and `services.sweep.backtest.engine` [L11].
- **Public interface**:
  - `def resample_ohlc(candles: Sequence[T], target_timeframe: str, closed_only: bool = True) -> List[T]` [L25-L190]
- **Inputs/outputs**: Sequence of 15m candle objects/dicts in; resampled higher-timeframe candle objects out.
- **Key algorithms and parameters**:
  - Bucket anchoring:
    - 30m, 1h, 4h: Anchored to UTC midnight [L70-L85].
    - 1d: Anchored to 17:00 America/New_York (Forex/Metals standard daily close) [L87-L105].
  - Aggregation logic: `open = first.open`, `high = max(highs)`, `low = min(lows)`, `close = last.close`, `volume = sum(volumes)`.
  - Incomplete buckets: If `closed_only=True`, the forming bucket is dropped based on count or timestamp check [L150-L165].
- **Dependencies**: `zoneinfo.ZoneInfo`, `datetime`, `app.services.market_data.calendar.is_market_open`.
- **Side effects**: None (pure transformation).
- **Lookahead / determinism notes**: Pure functional design. Does not call `datetime.now()`; respects closed bucket boundaries strictly.
- **Tests**: Covered by `tests/test_resample.py` (7 tests).
- **Known issues and risks**: None.

### market_data/symbols.py
- **Purpose**: Canonical symbol dictionary, pip sizes, contract specifications, price formatting, and pip distance calculations.
- **Status**: ACTIVE. Imported by `services.market_data.twelvedata_provider` [L14], `services.signals.risk_manager` [L7], `api.v1.market` [L18].
- **Public interface**:
  - `class InstrumentSpec(NamedTuple)` [L18-L27]
  - `INSTRUMENT_SPECS: Dict[str, InstrumentSpec]` [L30-L81]
  - `def normalize_symbol(symbol: str) -> str` [L84-L105]
  - `def get_instrument_spec(symbol: str) -> InstrumentSpec` [L107-L110]
  - `def get_provider_symbol(symbol: str, provider: str, ...) -> str` [L113-L146]
  - `def format_price(price: Optional[float], symbol: str) -> str` [L149-L157]
  - `def calculate_pips(entry: float, target: float, symbol: str) -> float` [L160-L169]
- **Inputs/outputs**: Symbol strings, prices; returns canonical symbols, `InstrumentSpec`, formatted strings, pip floats.
- **Key algorithms and parameters**:
  - Canonical specs:
    - `XAU/USD`: `pip_size=0.10`, `point_value_per_lot=10.0`, `contract_size=100.0`, `digits=2` [L32-L40].
    - `EUR/USD`: `pip_size=0.0001`, `point_value_per_lot=10.0`, `contract_size=100000.0`, `digits=5` [L42-L50].
    - `USD/JPY`: `pip_size=0.01`, `point_value_per_lot=10.0`, `contract_size=100000.0`, `digits=3` [L52-L60].
    - `GBP/USD`: `pip_size=0.0001`, `point_value_per_lot=10.0`, `contract_size=100000.0`, `digits=5` [L62-L70].
    - `US100`: `pip_size=0.25`, `point_value_per_lot=20.0`, `contract_size=20.0`, `digits=2` [L72-L80].
  - `normalize_symbol` raises `UnknownSymbolError` if the symbol cannot be matched to `INSTRUMENT_SPECS` [L104].
- **Dependencies**: `typing.NamedTuple`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Deterministic static table lookup.
- **Tests**: Covered by `tests/test_symbol_mapping.py` (4 tests).
- **Known issues and risks**: `calculate_pips` line 169 has fallback `return round(diff / 0.01, 1)` if `UnknownSymbolError` is caught, which treats 1 cent ($0.01) as 1 pip instead of $0.10.

### market_data/twelvedata_provider.py
- **Purpose**: Twelve Data API client with token-bucket rate limiter, daily budget tracking in database, and closed-bar validation.
- **Status**: ACTIVE. Primary market data feed. Imported in `services.market_data.__init__` [L22], `api.v1.health` [L15].
- **Public interface**:
  - `class TwelveDataProvider(BaseMarketDataProvider)` [L34-L396]
    - `get_candles(symbol, timeframe, limit)` [L88-L235]
    - `get_latest_candle(symbol, timeframe)` [L238-L255]
    - `get_quote(symbol)` [L258-L335]
    - `health_check()` [L338-L365]
- **Inputs/outputs**: Calls Twelve Data REST API (`/time_series`, `/quote`); returns `List[CandleCreate]` and `QuoteResponse`.
- **Key algorithms and parameters**:
  - Token bucket rate limiter: max 7 requests per minute [L45].
  - Daily budget tracking: max 780 calls per day tracked in `api_usage` table [L48, L101-L108].
  - 429 response handling: Backoff 60 seconds, retries up to 3 times, then raises `TwelveDataRateLimitError` [L155-L175].
  - Forming bar filter: Drops incomplete bar using timestamp rule `bar_ts + tf_delta > now(UTC)` [L195-L205].
  - OHLC integrity validation: Verifies `high >= max(open, close)` and `low <= min(open, close)` [L210-L225].
- **Dependencies**: `httpx.AsyncClient`, `SQLAlchemy`, `app.models.api_usage.ApiUsage`, `app.core.config.settings`.
- **Side effects**: Performs HTTP GET requests; updates `api_usage` table in DB.
- **Lookahead / determinism notes**: Strictly drops still-forming candles before returning data to consumers.
- **Tests**: Covered by `tests/test_twelvedata_provider.py` (6 tests), `tests/test_candle_fallback_and_webhook.py`.
- **Known issues and risks**: Hardcoded budget limit of 780 calls per day [L48] assumes the Twelve Data 800 credits/day free plan.



---

## Indicators Service (`app/services/indicators/`)

### indicators/atr_calculator.py
- **Purpose**: Computes Average True Range (ATR) series and current volatility snapshots using Wilder's smoothing.
- **Status**: ACTIVE. Imported by `services.indicators.indicator_service` [L11], `services.indicators.__init__` [L3].
- **Public interface**:
  - `class ATRCalculator` [L14-L107]
    - `calculate_tr(candle, prev_close) -> float` [L24-L38]
    - `calculate_atr_series(candles, period=14) -> List[float]` [L40-L66]
    - `calculate_atr_snapshot(candles, period=14) -> ATRSnapshot` [L68-L107]
- **Inputs/outputs**: Sequence of `Candle` or `CandleCreate` objects in; `ATRSnapshot` schema out.
- **Key algorithms and parameters**:
  - Period: default `14` [L40].
  - Warm-up: First 14 bars use simple moving average of True Range [L55-L58].
  - Smoothing: Wilder's RMA: `(prev_atr * 13 + current_tr) / 14` [L60-L63].
  - Volatility regime: Classified based on percentile of ATR over available window [L88-L100].
- **Dependencies**: `app.schemas.indicators.ATRSnapshot`, `app.schemas.candle.CandleCreate`.
- **Side effects**: None (in-memory math).
- **Lookahead / determinism notes**: Deterministic series calculation. No forward-looking data.
- **Tests**: Covered by `tests/test_indicators.py::test_atr_calculator_wilders_smoothing`.
- **Known issues and risks**: Duplicated by `services/sweep/atr.py:calculate_atr`.

### indicators/ema_calculator.py
- **Purpose**: Calculates Exponential Moving Averages (EMA 20, 50, 200) and moving average alignment bias.
- **Status**: ACTIVE. Imported by `services.indicators.indicator_service` [L12], `services.indicators.__init__` [L4].
- **Public interface**:
  - `class EMACalculator` [L14-L109]
    - `calculate_ema_series(candles, period) -> List[float]` [L23-L52]
    - `calculate_ema_snapshot(candles, fast=20, mid=50, slow=200) -> EMASnapshot` [L54-L109]
- **Inputs/outputs**: Candle sequence in; `EMASnapshot` schema with `ema_fast`, `ema_mid`, `ema_slow`, `alignment` out.
- **Key algorithms and parameters**:
  - Multiplier: $k = \frac{2}{\text{period} + 1}$ [L39].
  - Seed: First EMA value is SMA of first $N$ closes [L41-L44].
  - Alignment: `BULLISH` if `fast > mid > slow`; `BEARISH` if `fast < mid < slow`; otherwise `MIXED` [L85-L95].
- **Dependencies**: `app.schemas.indicators.EMASnapshot`, `app.schemas.candle.Candle`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Deterministic sequence; respects chronological order.
- **Tests**: Covered by `tests/test_indicators.py::test_ema_calculator_alignment`.
- **Known issues and risks**: Periods 20, 50, 200 are hardcoded defaults in function signature [L57-L59] despite `Settings` containing `EMA_FAST`, `EMA_MID`, `EMA_SLOW`.

### indicators/indicator_service.py
- **Purpose**: Orchestrates ATR, EMA, RSI, Fair Value Gap (FVG), and candlestick pattern evaluations into an aggregate indicator response.
- **Status**: ACTIVE. Imported by `api.deps` [L12], `api.v1.indicators` [L13], `services.signals.confluence_engine` [L28].
- **Public interface**:
  - `class IndicatorService` [L22-L235]
    - `calculate_indicators(candles, symbol, timeframe) -> IndicatorAnalysisResponse` [L35-L148]
    - `detect_divergences(candles) -> List[Divergence]` [L151-L195]
    - `get_fair_value_gaps(candles) -> List[FairValueGap]` [L198-L235]
- **Inputs/outputs**: Sequence of candles; returns `IndicatorAnalysisResponse` schema.
- **Key algorithms and parameters**:
  - Requires minimum 15 candles for base calculations [L42].
  - Aggregate technical score: Combines RSI zone, EMA alignment, and price action patterns into a confluence bias score (-100 to +100) [L105-L135].
- **Dependencies**: `app.services.indicators.atr_calculator.ATRCalculator`, `EMACalculator`, `RSICalculator`, `PriceActionDetector`.
- **Side effects**: None (pure analytical service).
- **Lookahead / determinism notes**: Fully deterministic on input candle list.
- **Tests**: Covered by `tests/test_indicators.py` (4 tests), `tests/test_indicators_api.py` (5 tests).
- **Known issues and risks**: None.

### indicators/price_action.py
- **Purpose**: Identifies Fair Value Gaps (FVGs), Pin Bars (Hammer/Shooting Star), Engulfing bars, and Inside Bars.
- **Status**: ACTIVE. Imported by `services.indicators.indicator_service` [L14], `services.indicators.__init__` [L6].
- **Public interface**:
  - `class PriceActionDetector` [L15-L221]
    - `detect_fair_value_gaps(candles, min_gap_pct=0.01) -> List[FairValueGap]` [L25-L95]
    - `detect_candlestick_patterns(candles) -> List[PriceActionPattern]` [L98-L175]
    - `detect_inside_bars(candles) -> List[PriceActionPattern]` [L178-L221]
- **Inputs/outputs**: Candle sequence in; lists of `FairValueGap` and `PriceActionPattern` schemas out.
- **Key algorithms and parameters**:
  - Bullish FVG: `candle[i-2].high < candle[i].low` (gap between bar 1 high and bar 3 low) [L45-L55].
  - Bearish FVG: `candle[i-2].low > candle[i].high` [L60-L70].
  - Pin Bar: Wick is $\ge 60\%$ of total candle range and body is $\le 25\%$ [L115-L135].
  - Engulfing: Candle body completely covers previous candle body and moves in direction of trend [L140-L165].
- **Dependencies**: `app.schemas.indicators.FairValueGap`, `PriceActionPattern`, `PatternType`.
- **Side effects**: None.
- **Lookahead / determinism notes**: FVG checks require index $i-2$ to $i$, evaluating strictly closed historical triples.
- **Tests**: Covered by `tests/test_price_action.py` (4 tests).
- **Known issues and risks**: FVG mitigation tracking checks only subsequent candles present in the slice; short candle slices may falsely report an old FVG as unmitigated.

### indicators/rsi_calculator.py
- **Purpose**: Computes Relative Strength Index (RSI 14) and regular bullish/bearish divergences against price swing pivots.
- **Status**: ACTIVE. Imported by `services.indicators.indicator_service` [L13], `services.indicators.__init__` [L5].
- **Public interface**:
  - `class RSICalculator` [L15-L202]
    - `calculate_rsi_series(candles, period=14) -> List[float]` [L25-L68]
    - `calculate_rsi_snapshot(candles, period=14) -> RSISnapshot` [L70-L115]
    - `detect_divergences(candles, rsi_series) -> List[Divergence]` [L118-L202]
- **Inputs/outputs**: Candle sequence in; `RSISnapshot` and `List[Divergence]` out.
- **Key algorithms and parameters**:
  - Wilder's smoothing for average gains and average losses [L45-L65].
  - Overbought: `RSI >= 70.0`; Oversold: `RSI <= 30.0` [L88-L98].
  - Regular Bullish Divergence: Lower price low with higher RSI low [L150-L165].
  - Regular Bearish Divergence: Higher price high with lower RSI high [L170-L185].
- **Dependencies**: `app.schemas.indicators.RSISnapshot`, `Divergence`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Strict chronological smoothing.
- **Tests**: Covered by `tests/test_indicators.py::test_rsi_calculator_and_divergences`.
- **Known issues and risks**: None.

---

## Liquidity Service (`app/services/liquidity/`)

### liquidity/liquidity_service.py
- **Purpose**: Orchestrates Support/Resistance zone detection, liquidity pool clustering, and liquidity sweep detection.
- **Status**: ACTIVE. Imported by `api.deps` [L13], `api.v1.liquidity` [L16], `services.signals.confluence_engine` [L29].
- **Public interface**:
  - `class LiquidityService` [L24-L287]
    - `analyze_liquidity(candles, symbol, timeframe) -> AdvancedStructureAnalysisResponse` [L40-L150]
    - `get_sr_zones(candles, symbol, timeframe) -> List[SupportResistanceZone]` [L153-L195]
    - `get_sweeps(candles, symbol, timeframe) -> List[LiquiditySweep]` [L198-L245]
    - `get_pools(candles, symbol, timeframe) -> List[LiquidityPool]` [L248-L287]
- **Inputs/outputs**: Candle sequence in; `AdvancedStructureAnalysisResponse` and liquidity event schemas out.
- **Key algorithms and parameters**:
  - Connects `SRDetector` and `SweepDetector`.
  - Persists detected sweeps and structure events to `liquidity_events` and `structure_events` tables if DB session provided [L110-L135].
- **Dependencies**: `app.services.liquidity.sr_detector.SRDetector`, `SweepDetector`, `app.models.liquidity.LiquidityEvent`.
- **Side effects**: Writes to database if a DB session is injected.
- **Lookahead / determinism notes**: Operates on input candle list.
- **Tests**: Covered by `tests/test_liquidity.py` (5 tests), `tests/test_liquidity_api.py` (5 tests).
- **Known issues and risks**: Overlaps with `services/sweep/engine.py` (Phase 2 sweep engine). This service represents the legacy multi-asset detector.

### liquidity/sr_detector.py
- **Purpose**: Detects Support and Resistance levels from pivot highs/lows and clusters them into zones by price tolerance.
- **Status**: ACTIVE. Imported by `services.liquidity.liquidity_service` [L14], `services.liquidity.__init__` [L3].
- **Public interface**:
  - `class SRDetector` [L18-L215]
    - `find_pivot_highs_and_lows(candles, lookback=2) -> Tuple[List, List]` [L30-L75]
    - `cluster_levels_into_zones(levels, tolerance_pct=0.1) -> List[SupportResistanceZone]` [L78-L150]
    - `detect_equal_highs_and_lows(candles, tolerance_pct=0.05) -> List[LiquidityPool]` [L153-L215]
- **Inputs/outputs**: Candles in; lists of `SupportResistanceZone` and `LiquidityPool` schemas out.
- **Key algorithms and parameters**:
  - Pivot condition: Candle high > previous `lookback` highs AND next `lookback` highs [L45-L60].
  - Clustering: Groups price levels within `tolerance_pct` (default `0.1%` from `settings.SR_TOLERANCE_PERCENT`) into a weighted zone [L95-L125].
  - Equal Highs/Lows: Finds 2 or more swing points within `0.05%` of each other [L170-L190].
- **Dependencies**: `app.schemas.liquidity.SupportResistanceZone`, `LiquidityPool`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Pivot detection requires `lookback` bars to the right, meaning a pivot at bar $k$ is only confirmed at bar $k + \text{lookback}$.
- **Tests**: Covered by `tests/test_liquidity.py::test_sr_zone_clustering`.
- **Known issues and risks**: Lookback of 2 means the most recent 2 candles in any slice cannot be recognized as pivots until subsequent bars close.

### liquidity/sweep_detector.py
- **Purpose**: Detects liquidity sweeps where candle wicks breach key S/R zones or swing points but close back within range.
- **Status**: ACTIVE. Imported by `services.liquidity.liquidity_service` [L15], `services.liquidity.__init__` [L4].
- **Public interface**:
  - `class SweepDetector` [L18-L187]
    - `detect_sweeps(candles, sr_zones, lookback=20) -> List[LiquiditySweep]` [L30-L187]
- **Inputs/outputs**: Candles and S/R zones in; `List[LiquiditySweep]` out.
- **Key algorithms and parameters**:
  - Bullish Sweep (Sell-Side Liquidity Sweep): Candle low penetrates support zone, but candle close is above the zone [L75-L105].
  - Bearish Sweep (Buy-Side Liquidity Sweep): Candle high penetrates resistance zone, but candle close is below the zone [L110-L140].
  - Sweep volume and wick ratio validation: Requires rejection wick to be at least $40\%$ of candle range [L125].
- **Dependencies**: `app.schemas.liquidity.LiquiditySweep`, `SupportResistanceZone`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Evaluates completed closed candles sequentially.
- **Tests**: Covered by `tests/test_liquidity.py::test_sweep_detector_logic`.
- **Known issues and risks**: Relies on `SRDetector` zone inputs which can drift as new candles enter the lookback window.

---

## Structure Service (`app/services/structure/`)

### structure/bos_choch_detector.py
- **Purpose**: Detects Break of Structure (BOS) and Change of Character (CHoCH / Market Structure Shift) events.
- **Status**: ACTIVE. Imported by `services.liquidity.liquidity_service` [L16], `services.structure.ltf_confirmation` [L14], `services.structure.__init__` [L3].
- **Public interface**:
  - `class BOSChoCHDetector` [L17-L237]
    - `detect_bos_choch(candles, swing_highs, swing_lows) -> List[StructureEvent]` [L28-L237]
- **Inputs/outputs**: Candles and swing lists in; list of `StructureEvent` schemas out.
- **Key algorithms and parameters**:
  - Bullish BOS: Candle close > prior swing high during an existing uptrend (continuation) [L85-L110].
  - Bullish CHoCH: Candle close > prior swing high during an existing downtrend (reversal) [L115-L140].
  - Bearish BOS: Candle close < prior swing low during an existing downtrend (continuation) [L145-L170].
  - Bearish CHoCH: Candle close < prior swing low during an existing uptrend (reversal) [L175-L200].
  - Strict Close Rule: Requires `candle.close` beyond swing extreme; wick-only breaks are ignored [L92, L152].
- **Dependencies**: `app.schemas.structure.StructureEvent`, `StructureEventType`, `TrendDirection`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Requires confirmation bar close beyond swing level. Zero lookahead.
- **Tests**: Covered by `tests/test_bos_choch.py` (5 tests: `test_bullish_bos_continuation`, `test_bearish_bos_continuation`, `test_bullish_choch_mss_reversal`, `test_bearish_choch_mss_reversal`, `test_no_lookahead_breakout_before_confirmation_bar`).
- **Known issues and risks**: None. Follows SMC textbook definitions accurately.

### structure/crt_analyzer.py
- **Purpose**: Candle Range Theory (CRT) AMD core: extracts accumulation benchmark range from HTF, detects manipulation sweep, and enforces range re-entry.
- **Status**: ACTIVE. Imported by `services.strategies.crt_strategy` [L37], `services.structure.__init__` [L7].
- **Public interface**:
  - `class CRTAnalyzer` [L20-L294]
    - `analyze(range_candles, confirm_candles, htf_timeframe, ltf_timeframe, min_manip_pct, max_manip_pct) -> CRTAnalysis` [L35-L294]
- **Inputs/outputs**: HTF range candles, LTF confirm candles in; `CRTAnalysis` schema out.
- **Key algorithms and parameters**:
  - Benchmark accumulation candle: `ref_candle = range_candles[-1]` [L85].
  - Lookahead guard: Verifies `confirm_candle.timestamp >= range_open_ts + htf_duration` [L153-L160].
  - Manipulation sweep direction:
    - Bullish accumulation (`close > open`): Low breaches `range_low` [L185-L205].
    - Bearish accumulation (`close < open`): High breaches `range_high` [L210-L230].
  - Manipulation depth gate: `min_manip_pct=5.0%`, `max_manip_pct=100.0%` of range height [L240-L260].
  - Re-entry gate: Confirms if LTF candle closes back inside the benchmark range [L265-L280].
- **Dependencies**: `app.schemas.structure.CRTAnalysis`, `app.services.market_data.freshness.get_timeframe_delta`.
- **Side effects**: None (pure analyzer).
- **Lookahead / determinism notes**: Zero lookahead. Rejects input if any candle has missing timestamps or falls inside the HTF formation window.
- **Tests**: Covered by `tests/test_crt_strategy.py::test_crt_analyzer_edge_cases`.
- **Known issues and risks**: Does not return `manipulation_candle_index` in `CRTAnalysis` schema, causing `crt_strategy.py:734` to default `manip_candle_index` to `0`.

### structure/ltf_confirmation.py
- **Purpose**: Validates lower-timeframe (15m) Market Structure Shift (MSS) alignment when primary signals originate on higher timeframes (1h/4h).
- **Status**: ACTIVE. Imported by `services.strategies.smc_strategy` [L25], `services.signals.confluence_engine` [L36].
- **Public interface**:
  - `class LTFConfirmationEngine` [L18-L159]
    - `check_ltf_confirmation(primary_timeframe, primary_direction, primary_candles, ltf_candles, max_bars_ago=5) -> Tuple[bool, str]` [L30-L159]
- **Inputs/outputs**: Timeframes, direction, candles in; `(is_confirmed, reason)` out.
- **Key algorithms and parameters**:
  - Detects recent swing points on 15m candles via `SwingDetector`.
  - Runs `BOSChoCHDetector` on 15m to identify if a Bullish CHoCH or Bullish BOS has occurred within the last `max_bars_ago` (default 5) bars [L85-L125].
  - If no recent aligned structural event found, returns `(False, reason)` which triggers a 70% score penalty in `smc_strategy.py:111`.
- **Dependencies**: `app.services.structure.bos_choch_detector.BOSChoCHDetector`, `SwingDetector`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Uses closed 15m bars only.
- **Tests**: Covered by `tests/test_ltf_confirmation.py` (9 tests).
- **Known issues and risks**: None.

### structure/multi_timeframe.py
- **Purpose**: Aggregates market structure (trend, key support/resistance, market state) across 15m, 1h, and 4h into a unified MTF response.
- **Status**: ACTIVE. Imported by `services.structure.__init__` [L4], `api.v1.structure` [L16].
- **Public interface**:
  - `class MultiTimeframeStructureEngine` [L17-L222]
    - `analyze_multi_timeframe(symbol, primary_tf, db, candles_by_tf) -> MultiTimeframeStructureResponse` [L30-L222]
- **Inputs/outputs**: Symbol, timeframes, DB session; returns `MultiTimeframeStructureResponse` schema.
- **Key algorithms and parameters**:
  - Queries `candles` table for each timeframe (or receives pre-loaded dictionary) [L55-L75].
  - Analyzes each timeframe with `StructureEngine`.
  - Determines primary trend alignment: `ALIGNED_BULLISH` if 1h and 4h agree, `ALIGNED_BEARISH` if both bearish, else `CONFLICTING` [L160-L190].
- **Dependencies**: `app.services.structure.structure_engine.StructureEngine`, `app.models.candle.Candle`.
- **Side effects**: Reads candles from database.
- **Lookahead / determinism notes**: Operates on closed candles.
- **Tests**: Covered by `tests/test_structure.py`, `tests/test_structure_api.py`.
- **Known issues and risks**: None.

### structure/structure_engine.py
- **Purpose**: Core market structure analyzer for a single timeframe: swing points, trend classification (BULLISH/BEARISH/RANGING), and market state.
- **Status**: ACTIVE. Imported by `api.deps` [L11], `api.v1.structure` [L14], `services.liquidity.liquidity_service` [L17].
- **Public interface**:
  - `class StructureEngine` [L22-L362]
    - `analyze(candles, symbol, timeframe) -> StructureAnalysisResponse` [L35-L362]
- **Inputs/outputs**: Candle sequence in; `StructureAnalysisResponse` schema out.
- **Key algorithms and parameters**:
  - Swing detection via `SwingDetector(lookback=2)` [L55].
  - Market state classification: `TRENDING` if series of higher highs / higher lows or lower highs / lower lows; `RANGING` if pivots oscillate within bounds [L145-L185].
  - Premium / Discount evaluation: Computes equilibrium at 50% between range high and range low [L215-L235].
- **Dependencies**: `app.services.structure.swing_detector.SwingDetector`, `BOSChoCHDetector`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Zero lookahead.
- **Tests**: Covered by `tests/test_structure.py` (7 tests).
- **Known issues and risks**: None.

### structure/swing_detector.py
- **Purpose**: Detects local swing highs and swing lows using symmetrical rolling window lookbacks.
- **Status**: ACTIVE. Imported by `services.indicators.indicator_service` [L15], `services.structure.structure_engine` [L15], `services.structure.ltf_confirmation` [L13].
- **Public interface**:
  - `class SwingDetector` [L13-L146]
    - `detect_swings(candles, lookback=2) -> Tuple[List[SwingPoint], List[SwingPoint]]` [L25-L146]
- **Inputs/outputs**: Candle sequence in; tuples of `(swing_highs, swing_lows)` out.
- **Key algorithms and parameters**:
  - Symmetrical condition: Bar $i$ must be strictly higher (or lower) than all bars in $[i-\text{lookback}, i-1]$ and all bars in $[i+1, i+\text{lookback}]$ [L60-L95].
  - Default `lookback = 2` (anchored to `settings.SWING_LOOKBACK`).
- **Dependencies**: `app.schemas.structure.SwingPoint`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Confirmation delay: A swing point at bar $k$ is only confirmed when bar $k + \text{lookback}$ has closed.
- **Tests**: Covered by `tests/test_structure.py::test_swing_detector`.
- **Known issues and risks**: None.

---

## Sweep Engine & Sweep Backtest (`app/services/sweep/`)

### sweep/config.py
- **Purpose**: Configuration dataclass for the Phase 2 liquidity-sweep engine.
- **Status**: PARTIAL. Reachable only from `scripts/run_sweep_backtest.py` [L17], `services/sweep/*`, and `services/strategies/crt/backtest_adapter.py` [L13].
- **Public interface**:
  - `@dataclass(frozen=True) class SweepConfig` [L6-L48]
- **Inputs/outputs**: Configuration parameters for sweep detection and trade planning.
- **Key algorithms and parameters**:
  - `pivot_n_left: int = 5`, `pivot_n_right: int = 3` [L9-L10]
  - `min_sweep_atr: float = 0.15`, `max_sweep_atr: float = 2.50` [L11-L12]
  - `rejection_wick_ratio: float = 0.35`, `max_rejection_bars: int = 4` [L13-L14]
  - `equal_level_threshold_atr: float = 0.10` [L16]
  - `mss_timeframe: str = "15m"`, `max_mss_bars: int = 12` [L18-L19]
  - `zone_expiry_bars: int = 8`, `min_rr_tp1: float = 1.5`, `high_rr_threshold: float = 2.0` [L24, L27, L29]
- **Dependencies**: `dataclasses.dataclass`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Immutable configuration object.
- **Tests**: Covered by `tests/test_sweep_engine.py`, `tests/test_sweep_backtest.py`.
- **Known issues and risks**: None.

### sweep/atr.py
- **Purpose**: Pure ATR calculation in USD for candle sequences.
- **Status**: PARTIAL. Used internally by `services.sweep.engine` [L15].
- **Public interface**:
  - `def calculate_atr(candles: Sequence[CandleCreate], period: int = 14) -> List[float]` [L7-L42]
- **Inputs/outputs**: Candle sequence in; list of float ATR values out.
- **Key algorithms and parameters**: Wilder's smoothing `(prev_atr * 13 + current_tr) / 14` [L37-L40].
- **Dependencies**: `app.schemas.candle.CandleCreate`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Pure functional, strictly closed candles.
- **Tests**: Covered by `tests/test_sweep_engine.py`.
- **Known issues and risks**: Duplicated by `services/indicators/atr_calculator.py`.

### sweep/pivots.py
- **Purpose**: Fractal pivot high and pivot low detection with exact confirmation lag ($k + N_\text{right}$).
- **Status**: PARTIAL. Used by `services.sweep.engine` and `services.sweep.pools`.
- **Public interface**:
  - `def detect_fractal_pivots(candles, n_left=5, n_right=3) -> Tuple[List[PivotPoint], List[PivotPoint]]` [L20-L85]
- **Inputs/outputs**: Candles in; lists of `PivotPoint` instances with `confirm_time` out.
- **Key algorithms and parameters**: A pivot at index $k$ requires $k \ge n_\text{left}$ and is only emitted with `confirm_time = candles[k + n_right].timestamp` [L60-L75].
- **Dependencies**: `dataclasses.dataclass`, `app.schemas.candle.CandleCreate`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Zero lookahead. A pivot cannot be seen by the engine before its `confirm_time`.
- **Tests**: Covered by `tests/test_sweep_engine.py::test_prefix_invariance_300_indices`.
- **Known issues and risks**: None.

### sweep/pools.py
- **Purpose**: Builds liquidity pools from equal levels (EQH/EQL), session extremes (Asia, London, NY), and Previous-Day High/Low (PDH/PDL).
- **Status**: PARTIAL. Used by `services.sweep.engine` [L17].
- **Public interface**:
  - `def build_liquidity_pools(candles_15m, candles_1d, atr_list, config) -> List[LiquidityPool]` [L65-L223]
  - `def is_in_kill_zone(dt_utc) -> bool` [L37-L62]
- **Inputs/outputs**: Multi-timeframe candles in; list of active `LiquidityPool` objects out.
- **Key algorithms and parameters**:
  - EQH/EQL: Pivots within `equal_level_threshold_atr * ATR` are grouped into pools [L118, L139].
  - Sessions (anchored in `America/New_York`):
    - Asia: 18:00 - 00:00 NY [L166]
    - London: 03:00 - 07:00 NY [L170]
    - Daily PDH/PDL: Closed at 17:00 NY [L174, L208]
- **Dependencies**: `zoneinfo.ZoneInfo`, `app.services.sweep.config.SweepConfig`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Pools are only created after the relevant session or daily bar closes (`confirm_time`).
- **Tests**: Covered by `tests/test_sweep_engine.py::test_equal_highs_sweep_fixture`.
- **Known issues and risks**: None.

### sweep/detector.py
- **Purpose**: Sweep penetration detection, Market Structure Shift (MSS) within 12 bars, FVG/Order Block entry zones, and SL/TP planning.
- **Status**: PARTIAL. Used by `services.sweep.engine` [L18].
- **Public interface**:
  - `def detect_sweep_event(...) -> Optional[SweepEvent]` [L45-L165]
  - `def detect_mss(...) -> Optional[MSSEvent]` [L170-L255]
  - `def construct_entry_zone(...) -> Optional[EntryZone]` [L258-L368]
  - `def plan_trade_setup(...) -> Optional[SetupPlan]` [L371-L449]
- **Inputs/outputs**: Candles, pools, ATR series in; `SetupPlan` out.
- **Key algorithms and parameters**:
  - Sweep requires wick penetration beyond pool price by $\ge 0.15\text{ ATR}$ and close back inside [L85-L115].
  - MSS required within `max_mss_bars = 12` 15m bars [L185].
  - Entry zone constructed from FVG or Order Block (last opposing candle before displacement) [L265, L331].
  - Risk/Reward Gate: Rejects setup if $RR < 1.5$ [L415].
- **Dependencies**: `app.services.sweep.config.SweepConfig`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Zero lookahead.
- **Tests**: Covered by `tests/test_sweep_engine.py` (10 tests: `test_clean_bearish_sweep_fixture`, `test_fake_out_breakout_fixture`, `test_late_rejection_after_4_bars_fails`, `test_no_mss_within_12_bars_yields_no_setup`, etc.).
- **Known issues and risks**: None.

### sweep/state_machine.py
- **Purpose**: Setup lifecycle state machine: POTENTIAL -> WAITING_FOR_CONFIRMATION -> CONFIRMED_SETUP / INVALIDATED / NO_SETUP.
- **Status**: PARTIAL. Used by `services.sweep.engine` [L20].
- **Public interface**:
  - `class SetupState(Enum)` [L14-L21]
  - `class SweepSetup` [L32-L65]
  - `def transition_setup_state(...) -> SetupState` [L70-L97]
- **Inputs/outputs**: Current state and event triggers; returns updated state.
- **Key algorithms and parameters**: Invalidation triggers if close penetrates beyond sweep extreme [L85].
- **Dependencies**: `enum.Enum`, `dataclasses.dataclass`.
- **Side effects**: None.
- **Lookahead / determinism notes**: State evolves strictly bar by bar.
- **Tests**: Covered by `tests/test_sweep_engine.py`.
- **Known issues and risks**: None.

### sweep/engine.py
- **Purpose**: Top-level coordinator of the pure liquidity sweep engine for point-in-time evaluation.
- **Status**: PARTIAL. Used by `services.sweep.backtest.engine` [L14] and `scripts/run_sweep_backtest.py`.
- **Public interface**:
  - `def evaluate_sweep_market(candles_15m, candles_1h, candles_4h, as_of, config) -> Optional[SweepSetup]` [L30-L424]
- **Inputs/outputs**: Multi-timeframe candles, `as_of` timestamp, `SweepConfig`; returns `Optional[SweepSetup]`.
- **Key algorithms and parameters**: Chains `build_liquidity_pools` -> `detect_sweep_event` -> `detect_mss` -> `construct_entry_zone` -> `plan_trade_setup`.
- **Dependencies**: `services.sweep.*`.
- **Side effects**: None (pure functional evaluation).
- **Lookahead / determinism notes**: Validated by prefix invariance tests: evaluating up to bar $T$ yields bit-identical outputs regardless of subsequent data.
- **Tests**: Covered by `tests/test_sweep_engine.py` (10 tests) and `tests/test_window_invariance.py`.
- **Known issues and risks**: Standalone engine not wired into live scanner or API signal generator.

### sweep/backtest/ (Subpackage)
- **Purpose**: Walk-forward simulation harness, trade-through fill model, friction/slippage modeling, bootstrap 95% confidence intervals, and parameter grid tuning.
- **Status**: PARTIAL. Only called by `scripts/run_sweep_backtest.py` and covered by tests.
- **Public interface**:
  - `sweep/backtest/engine.py: run_walk_forward_backtest(...)` [L50-L390]
  - `sweep/backtest/tuning.py: run_parameter_grid_search(...)` [L25-L175]
  - `sweep/backtest/baseline.py: run_random_walk_baseline(...)` [L30-L144]
  - `sweep/backtest/metrics.py: calculate_performance_metrics(...)` [L15-L113]
  - `sweep/backtest/formatter.py: format_backtest_report_markdown(...)` [L15-L101]
- **Inputs/outputs**: Historical 15m candle database; outputs `BacktestReport` dataclass and markdown report.
- **Key algorithms and parameters**:
  - Fill Model: Trade-through required (limit order fills only when price trades strictly beyond limit price) [L145].
  - Same-bar conflict: Assumes Stop Loss hit first if both SL and TP touched on same bar [L175].
  - Friction: Spread $0.30 + Slippage $0.10 = $0.40 round-trip USD on XAU/USD [L45].
  - Bootstrap CI: 10,000 resamples. Guardrail: if $N < 30$ trades, confidence interval returns "n/a" [L75-L85].
  - Purged/Embargoed splits: 60% Train, 20% Validation, 20% Test with 48-hour purge window [L80-L105].
- **Dependencies**: `services.sweep.engine`, `services.sweep.config`.
- **Side effects**: Reads `backtest.db`; writes markdown reports to `reports/`.
- **Lookahead / determinism notes**: Zero lookahead. Walk-forward loops bar by bar calling `evaluate_sweep_market`.
- **Tests**: Covered by `tests/test_sweep_backtest.py` (7 tests), `tests/test_random_walk_control_slow.py`.
- **Known issues and risks**: `services/sweep/backtest/engine.py:30` has `if h >= 18 or h < 0:` (condition `h < 0` is dead code as `datetime.hour >= 0`).


---

## Trading Strategies (`app/services/strategies/`)

### strategies/base.py
- **Purpose**: Defines abstract base strategy class `BaseStrategy` and immutable `StrategyResult` container.
- **Status**: ACTIVE. Inherited by all strategies; imported in `services.strategies.strategy_manager` [L14].
- **Public interface**:
  - `@dataclass class StrategyResult` [L16-L45]
  - `class BaseStrategy(ABC)` [L48-L73]
    - `@property def name(self) -> str`
    - `def analyze(...) -> StrategyResult`
- **Inputs/outputs**: Standardized multi-timeframe candles, indicators, structure in; `StrategyResult` out.
- **Key algorithms and parameters**: Common contract across SMC, Range, and CRT strategies.
- **Dependencies**: `app.schemas.signal.SignalDirection`, `ScoreBreakdown`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Interface definition.
- **Tests**: Covered transitively by all strategy tests.
- **Known issues and risks**: None.

### strategies/strategy_manager.py
- **Purpose**: Strategy orchestrator fanning out analysis across `SMCStrategy`, `RangeStrategy`, and `CRTStrategy`.
- **Status**: ACTIVE. Imported by `services.signals.confluence_engine` [L94], `api.deps` [L17].
- **Public interface**:
  - `class StrategyManager` [L17-L117]
    - `run_all_strategies(...) -> List[StrategyResult]` [L58-L117]
    - `register(strategy: BaseStrategy)` [L53-L56]
- **Inputs/outputs**: Market inputs in; `List[StrategyResult]` out.
- **Key algorithms and parameters**:
  - Lazy imports `SMCStrategy`, `RangeStrategy`, `CRTStrategy` in `__init__` [L43-L45] to prevent circular imports with `confluence_engine`.
  - Infers `htf_trend` context from MTF 1h/4h trends if not explicitly provided [L79-L90].
  - Exception isolation: Wraps each strategy call in `try...except` so one failing strategy cannot halt others [L93-L116].
- **Dependencies**: `app.services.strategies.*`.
- **Side effects**: Emits log entries.
- **Lookahead / determinism notes**: Deterministic fan-out.
- **Tests**: Covered by `tests/test_crt_strategy.py::test_strategy_manager_runs_crt_strategy`, `tests/test_range_strategy.py`.
- **Known issues and risks**: None.

### strategies/smc_strategy.py
- **Purpose**: Smart Money Concepts 3-pillar trend-following strategy (Structure 35, Liquidity 40, Price Action 25).
- **Status**: ACTIVE. Registered in `StrategyManager` [L47].
- **Public interface**:
  - `class SMCStrategy(BaseStrategy)` [L29-L171]
    - `name = "Strategy A (SMC Sniper)"` [L55]
    - `analyze(...) -> StrategyResult` [L57-L171]
- **Inputs/outputs**: Candles, indicators, structure; returns `StrategyResult`.
- **Key algorithms and parameters**:
  - Evaluates BUY and SELL via `StructureConsensusEvaluator`, `LiquiditySMCConsensusEvaluator`, `PriceActionConsensusEvaluator` [L74-L95].
  - Evaluates consensus via `ConsensusFilter`: requires PA floor $\ge 10/25$ and Structural confluence $\ge 20/75$.
  - LTF Confirmation Filter: If primary timeframe is 1h or 4h, checks 15m candles via `LTFConfirmationEngine`. If unconfirmed, slashes score by 70% (`score * 0.3`) [L101-L126].
  - Qualifying threshold: `total_score >= settings.MIN_SETUP_SCORE` (75.0) [L129, L134].
- **Dependencies**: `services.signals.evaluators.*`, `services.structure.ltf_confirmation.LTFConfirmationEngine`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Evaluates closed candles only.
- **Tests**: Covered by `tests/test_strategies.py`, `tests/test_production_parity.py`.
- **Known issues and risks**: Does not generate custom SL/TP levels; delegates execution levels to `RiskManager`.

### strategies/range_strategy.py
- **Purpose**: Mean-reversion range trading strategy for sideways market regimes (Structure 30, Liquidity 25, Indicators 25, Price Action 20).
- **Status**: ACTIVE. Registered in `StrategyManager` [L48].
- **Public interface**:
  - `class RangeStrategy(BaseStrategy)` [L44-L481]
    - `name = "Strategy C (Range Sniper)"` [L64]
    - `analyze(...) -> StrategyResult` [L66-L481]
- **Inputs/outputs**: Market inputs in; `StrategyResult` out.
- **Key algorithms and parameters**:
  - No-trend gatekeeper: If `structure.trend != TrendDirection.RANGING`, immediately returns `WAIT` with score `0.0` [L82-L100].
  - Minimum Range Width Gate: Rejects if range height $< 1.5\text{ ATR}$ [L430-L435].
  - S/R boundary proximity: Requires price within $0.3\text{ ATR}$ of support (for BUY) or resistance (for SELL) [L140-L165].
  - Indicator overbought/oversold: Scores RSI $< 35$ or $> 65$, EMA stretch $> 1.5\text{ ATR}$ [L220-L260].
  - Qualifying threshold: `total_score >= settings.MIN_SETUP_SCORE` (75.0) [L348].
- **Dependencies**: `app.schemas.indicators.*`, `app.schemas.liquidity.*`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Zero lookahead.
- **Tests**: Covered by `tests/test_range_strategy.py` (9 tests).
- **Known issues and risks**: None.

### strategies/crt_strategy.py
- **Purpose**: Candle Range Theory (CRT) trading strategy combining AMD sequence, HTF trend filtering, session killzones, retracement entry, obstacle path validation, 3-pillar scoring, quality tiers, and pip/lot sizing.
- **Status**: ACTIVE. Registered in `StrategyManager` [L49].
- **Public interface**:
  - `class CRTStrategy(BaseStrategy)` [L93-L1483]
    - `name = "Candle Range Theory (CRT)"` [L152]
    - `analyze(...) -> StrategyResult` [L154-L1483]
- **Inputs/outputs**: Candles, indicators, structure, MTF, account settings; returns `StrategyResult` with comprehensive metadata.
- **Key algorithms and parameters**:
  - 9-stage pipeline:
    1. Benchmark accumulation range selection (`CRTAnalyzer`) [L220-L245].
    2. Lookahead protection (`confirm_candle.timestamp >= range_open_ts + htf_duration`) [L260-L275].
    3. HTF Trend filter: Aligns with 1h/4h trend unless ranging [L295-L330].
    4. Session Gate: London 03:00–07:00 NY, NY 08:00–12:00 NY; off-session penalized -8 pts [L62-L87, L350-L365].
    5. Range Size Quality Gate: $0.35\text{ ATR} \le \text{height} \le 4.0\text{ ATR}$ [L400-L425].
    6. Manipulation Sweep Gate: $\ge \max(3 \times \text{spread}, 0.15\text{ ATR})$ and $5\% \le \text{depth} \le 100\%$ [L450-L500].
    7. LTF Confirmation: Re-entry, displacement, MSS [L720-L755].
    8. Risk Geometry: Stop loss at sweep extreme $\pm$ buffer; risk distance $\le 3.0\text{ ATR}$ [L850-L895].
    9. Targets & Path Validation: TP1 midpoint, TP2 opposing extreme; capped before obstacles; $RR \ge 1.0$ [L935-L980].
  - Position sizing: $100\text{ oz}$ contract, $1\text{ pip} = \$0.10$. Min lot $0.01$. If risk budget exceeded, flags `RISK EXCEEDS LIMIT` [L1275-L1310].
  - Deduplication: SHA-256 key with 2-hour cooldown in `crt_sweep_events` table [L1000-L1035].
- **Dependencies**: `services.structure.crt_analyzer`, `services.strategies.crt.*`, `models.crt_sweep_event.CRTSweepEvent`.
- **Side effects**: Queries and updates `crt_sweep_events` table in DB.
- **Lookahead / determinism notes**: Evaluates closed candles only; verified by 79 unit tests.
- **Tests**: Covered by `tests/test_crt_strategy.py` (79 tests).
- **Known issues and risks**:
  - `manip_candle_index` defaults to 0 due to schema omission [L734], pulling pre-sweep bars into post-sweep confirmation.
  - Limit order R:R distortion: passes `current_price` instead of `ideal_entry` to `calculate_crt_targets` [L942].
  - Replay evaluation on historical data emitted 0 signals across 5,625 bars due to restrictive gate confluence.

### strategies/crt/ (Subpackage)
- **`daily_bias.py`** (ACTIVE, 209 lines): Computes 17:00 NY daily bias, PDH/PDL, Asian (18:00–00:00 NY) and London (03:00–07:00 NY) session extremes. Classifies swept level points (+18 PDL/PDH, +14 Session, +12 EQH/EQL, +10 Major Swing, +4 Range extreme).
- **`confirmation.py`** (ACTIVE, 238 lines): Evaluates LTF displacement and MSS. *Known defect*: `has_displacement` is computed but omitted from return guard clause [L158-L179], allowing doji re-entries to confirm. Wick breaks qualify as MSS [L120, L154]. Structure event timestamp check missing [L105-L111].
- **`entry.py`** (ACTIVE, 210 lines): Calculates retracement limit entry zone (FVG, Order Block, or 50% equilibrium) and 8-bar expiry. Flags `is_missed = True` if price runs $> 0.5\text{R}$ without filling.
- **`targets.py`** (ACTIVE, 226 lines): Sets TP1 at range midpoint, TP2 at opposing extreme. Calls `PathValidator` to cap TP1 before obstacles. Enforces $RR \ge 1.0$.
- **`tiers.py`** (ACTIVE, 75 lines): Classifies setups into quality tiers: A+ ($\ge 85$), A ($\ge 75$), B ($\ge 65$, dashboard only), C ($< 65$).
- **`lifecycle.py`** (ACTIVE, 189 lines): Manages CRT setup lifecycle transitions (`POTENTIAL` $\to$ `CONFIRMED` $\to$ `ENTRY_FILLED` $\to$ `TP1_HIT` / `STOPPED` / `MISSED` / `EXPIRED`) and deduplicates Telegram alerts.
- **`backtest_adapter.py`** (DEAD, 112 lines): Converts CRT results to SweepSetup objects for Phase 3 sweep backtest engine. Unreferenced in application runtime; 0 tests.

---

## Signals Service (`app/services/signals/`)

### signals/confluence_engine.py
- **Purpose**: Top-level multi-strategy consensus engine: handles data validation, news blackout checks, MTF execution, strategy fan-out, and signal construction.
- **Status**: ACTIVE. Core signal coordinator. Imported by `services.signals.signal_generator` [L34], `api.deps` [L16].
- **Public interface**:
  - `class ConfluenceEngine` [L49-L680]
    - `evaluate_consensus(...) -> List[SignalResponse]` [L575-L680]
    - `generate_fingerprint(...) -> str` [L98-L117]
- **Inputs/outputs**: Candles, account balance, risk percent in; `List[SignalResponse]` out.
- **Key algorithms and parameters**:
  - News blackout gate: Checks `NewsFilterEngine.check_blackout()`. If active, forces `direction = SignalDirection.WAIT` [L200-L225].
  - HTF trend resolution: Evaluates 1h and 4h structure trends [L625-L628].
  - Strategy fan-out: Calls `StrategyManager.run_all_strategies(...)` [L630-L639].
  - Path Advisory: Calls `PathValidator`, attaches warning if obstacles detected [L415-L460].
  - Small Account Check: If lot size evaluates to `0.0`, rejects trade with `WAIT` [L401-L408].
- **Dependencies**: `services.strategies.strategy_manager.StrategyManager`, `services.signals.risk_manager.RiskManager`, `services.signals.path_validator.PathValidator`.
- **Side effects**: None directly; logs diagnostics.
- **Lookahead / determinism notes**: Respects closed candles and historical `as_of` timestamp.
- **Tests**: Covered by `tests/test_crt_strategy.py`, `tests/test_production_parity.py`, `tests/test_news_integrity.py`.
- **Known issues and risks**: In `_build_signal_response` lines 368-369, `entry_price` is overwritten with `current_price` (market price), discarding CRT's limit retracement entry.

### signals/evaluators.py
- **Purpose**: Sub-strategy modular evaluators (Structure, Liquidity/SMC, Indicators, Price Action) and `ConsensusFilter` synthesizer.
- **Status**: ACTIVE. Imported by `services.signals.confluence_engine` [L38], `services.strategies.smc_strategy` [L19].
- **Public interface**:
  - `class StructureConsensusEvaluator` [L55-L165]
  - `class LiquiditySMCConsensusEvaluator` [L168-L295]
  - `class PriceActionConsensusEvaluator` [L390-L485]
  - `class ConsensusFilter` [L488-L586]
    - `synthesize(evaluations, candidate_direction) -> Tuple[float, ScoreBreakdown, List[str], bool]` [L496-L586]
- **Inputs/outputs**: Analytical evaluations in; composite score, breakdown, catalysts, and fatal conflict boolean out.
- **Key algorithms and parameters**:
  - Pillar weights: Structure max 35, Liquidity max 40, Price Action max 25 (Indicators weight = 0) [L502-L505].
  - Price Action Floor: If `price_action_score < 10.0`, vetos direction [L526-L537].
  - Minimum Confluence: If `structure + liquidity < 20.0`, vetos direction [L543-L553].
  - Conflict penalties: 1 opposing signal = -15 pts; $\ge 2$ opposing signals = -30 pts and `fatal_conflict = True` [L559-L569].
- **Dependencies**: `app.schemas.signal.*`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Pure math.
- **Tests**: Covered by `tests/test_signals.py`, `tests/test_strategies.py`.
- **Known issues and risks**: None.

### signals/path_validator.py
- **Purpose**: Scans for structural barriers (S/R zones, unmitigated FVGs, liquidity pools) between entry and take-profit targets.
- **Status**: ACTIVE. Imported by `services.signals.confluence_engine` [L42], `services.strategies.crt.targets` [L19].
- **Public interface**:
  - `class PathValidator` [L40-L210]
    - `validate_trade_path(direction, entry_price, target_price, sr_zones, active_fvgs, liquidity_pools) -> PathValidationResult` [L49-L113]
- **Inputs/outputs**: Trade levels and structural objects in; `PathValidationResult` (`is_clear`, `nearest_obstacle_price`, `obstacle_type`) out.
- **Key algorithms and parameters**:
  - BUY trades check: Resistance zones, Bearish FVGs, Buy-Side Liquidity above entry and below target [L77-L79].
  - SELL trades check: Support zones, Bullish FVGs, Sell-Side Liquidity below entry and above target [L81-L83].
  - Nearest obstacle: Lowest barrier above entry for BUY, highest barrier below entry for SELL [L94-L98].
- **Dependencies**: `app.schemas.indicators.FairValueGap`, `app.schemas.liquidity.*`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Pure geometric comparison.
- **Tests**: Covered transitively by `tests/test_crt_strategy.py::test_tp_capped_before_opposing_ob_or_fvg`.
- **Known issues and risks**: None.

### signals/risk_manager.py
- **Purpose**: Calculates Stop Loss, Take Profit 1 & 2, Risk:Reward ratios, and position sizing in standard lots.
- **Status**: ACTIVE. Imported by `services.signals.confluence_engine` [L43], `services.paper_trading.order_executor` [L18].
- **Public interface**:
  - `class RiskManager` [L14-L141]
    - `get_pip_size(symbol) -> float` [L18-L27]
    - `get_pip_value_per_lot(symbol, current_price=1.0) -> float` [L29-L35]
    - `calculate_trade_risk(...) -> RiskParameters` [L36-L141]
- **Inputs/outputs**: Symbol, direction, entry price, balance, risk percent in; `RiskParameters` schema out.
- **Key algorithms and parameters**:
  - SL placement: Structural support/resistance $\pm 0.5\text{ ATR}$, capped at max structural distance (2,500 pips for XAU/USD, 100-120 pips for forex) [L65-L83]. Fallback: `entry \pm 1.5 ATR`.
  - Targets: `TP1 = entry + (risk * MIN_RR_TP1)`, `TP2 = entry + (risk * MIN_RR_TP2)` [L91-L92].
  - Lot sizing: `lots = risk_usd / (risk_pips * pip_value_per_lot)`, clamped between 0.01 and 100.0 lots [L124-L125].
- **Dependencies**: `app.services.market_data.symbols.*`, `app.core.config.settings`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Pure math.
- **Tests**: Covered by `tests/test_signals.py`, `tests/test_symbol_mapping.py`.
- **Known issues and risks**: Hardcodes maximum structural distance of 2,500 pips for XAU/USD ($250.00) [L66], which is very wide for intraday trading.

### signals/scoring_engine.py
- **Purpose**: Legacy scoring engine preserved for backward compatibility with older API endpoints.
- **Status**: ACTIVE. Imported by `services.signals.signal_generator` [L36], `api.deps` [L18].
- **Public interface**:
  - `class SignalScoringEngine` [L18-L118]
    - `evaluate_signals(...) -> Tuple[SignalDirection, float, ScoreBreakdown, List[str]]` [L40-L118]
- **Inputs/outputs**: Legacy evaluations in; composite direction and score out.
- **Key algorithms and parameters**: Wraps `ConsensusFilter` directly.
- **Dependencies**: `app.services.signals.evaluators.ConsensusFilter`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Pure math.
- **Tests**: Covered by `tests/test_signals.py`.
- **Known issues and risks**: Redundant with `ConfluenceEngine`.

### signals/signal_generator.py
- **Purpose**: High-level market scanning service coordinating data fetching, indicator generation, structure calculation, confluence scoring, and signal database persistence.
- **Status**: ACTIVE. Imported by `services.telegram.scheduler` [L15], `services.telegram.scanner` [L14], `api.deps` [L19].
- **Public interface**:
  - `class SignalGenerator` [L40-L635]
    - `generate_signal(db, symbol, timeframe, ...) -> SignalResponse` [L70-L320]
    - `scan_market(db, symbols, timeframes, ...) -> MarketScanResponse` [L325-L480]
    - `scan_all_pairs_unified(db, symbols, timeframes, ...) -> MarketScanResponse` [L485-L635]
- **Inputs/outputs**: DB session, symbols, timeframes; returns `SignalResponse` and `MarketScanResponse`.
- **Key algorithms and parameters**:
  - Fetches closed candles from DB or provider [L95-L125].
  - Checks staleness via `check_data_staleness` [L130-L150].
  - Executes `ConfluenceEngine.evaluate_consensus()` [L185-L210].
  - Deduplication: Computes SHA-256 fingerprint, suppresses duplicates within cooldown window [L230-L260].
  - Persists qualified signals to `signals` table [L275-L310].
- **Dependencies**: `ConfluenceEngine`, `TwelveDataProvider`, `app.models.signal.Signal`.
- **Side effects**: Writes signals to `signals` table in DB.
- **Lookahead / determinism notes**: Uses closed candles only.
- **Tests**: Covered by `tests/test_signals.py`, `tests/test_signals_api.py`, `tests/test_scanner_scheduler.py`.
- **Known issues and risks**: None.

---

## News Service (`app/services/news/`)

### news/base.py
- **Purpose**: Abstract base class `BaseNewsProvider` defining economic calendar interface.
- **Status**: ACTIVE. Inherited by ForexFactory and Mock news providers.
- **Public interface**:
  - `class BaseNewsProvider(ABC)` [L14-L33]
    - `@abstractmethod def get_economic_calendar(...) -> List[NewsEventCreate]`
- **Inputs/outputs**: Date range in; `List[NewsEventCreate]` out.
- **Key algorithms and parameters**: Abstract interface contract.
- **Dependencies**: `abc.ABC`, `app.schemas.news.NewsEventCreate`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Interface definition.
- **Tests**: Transitive coverage in news tests.
- **Known issues and risks**: None.

### news/forexfactory_provider.py
- **Purpose**: Economic calendar provider scraping or ingesting ForexFactory XML/JSON feeds.
- **Status**: ACTIVE. Primary news provider. Imported by `services.telegram.scheduler` [L13], `services.news.__init__` [L4].
- **Public interface**:
  - `class ForexFactoryProvider(BaseNewsProvider)` [L18-L122]
    - `get_economic_calendar(start_date, end_date) -> List[NewsEventCreate]` [L25-L95]
    - `health_check() -> Dict[str, Any]` [L98-L122]
- **Inputs/outputs**: HTTP GET to ForexFactory weekly schedule endpoint; returns `List[NewsEventCreate]`.
- **Key algorithms and parameters**: Normalizes event impact (`HIGH`, `MEDIUM`, `LOW`, `NON_ECONOMIC`), maps currencies, converts times to UTC [L45-L75].
- **Dependencies**: `httpx`, `app.core.normalization.normalize_utc_datetime`.
- **Side effects**: Outbound HTTP network requests to ForexFactory.
- **Lookahead / determinism notes**: Uses scheduled event release times; point-in-time checks use event timestamp.
- **Tests**: Covered by `tests/test_news.py`, `tests/test_news_integrity.py`.
- **Known issues and risks**: External web scraping endpoint can fail or be rate-limited by Cloudflare.

### news/mock_provider.py
- **Purpose**: Mock economic calendar generator for offline testing.
- **Status**: ACTIVE. Imported in `services.news.__init__` [L5], `services.telegram.command_handler` [L36].
- **Public interface**:
  - `class MockNewsProvider(BaseNewsProvider)` [L15-L78]
- **Inputs/outputs**: Returns synthetic high-impact news events (CPI, NFP, FOMC, Rate Decision).
- **Key algorithms and parameters**: Schedules events around current day/hour for testing blackout logic [L30-L65].
- **Dependencies**: `app.services.news.base.BaseNewsProvider`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Test utility.
- **Tests**: Covered by `tests/test_news.py`.
- **Known issues and risks**: None.

### news/ingestion.py
- **Purpose**: Persists economic calendar events to `news_events` table and detects scheduled releases.
- **Status**: ACTIVE. Imported by `api.v1.news` [L13], `services.news.__init__` [L6].
- **Public interface**:
  - `class NewsIngestionService` [L24-L298]
    - `sync_calendar(db, provider, start_date, end_date) -> NewsSyncReport` [L35-L120]
    - `get_upcoming_events(db, hours_ahead=24) -> List[NewsEvent]` [L125-L165]
- **Inputs/outputs**: DB session, news provider; writes to `news_events` table.
- **Key algorithms and parameters**: Upsert based on `uq_news_currency_name_time` unique constraint [L65-L85].
- **Dependencies**: `SQLAlchemy`, `app.models.news.NewsEvent`.
- **Side effects**: Inserts/updates `news_events` records in DB.
- **Lookahead / determinism notes**: Database storage is chronological.
- **Tests**: Covered by `tests/test_news.py`, `tests/test_news_integrity.py`.
- **Known issues and risks**: None.

### news/filter_engine.py
- **Purpose**: Economic news blackout filter preventing trade signal generation before and after high-impact events.
- **Status**: ACTIVE. Imported by `services.signals.confluence_engine` [L30], `api.v1.news` [L14].
- **Public interface**:
  - `class NewsFilterEngine` [L20-L260]
    - `check_blackout(db, symbol, check_time=None) -> NewsBlackoutCheckResponse` [L35-L175]
    - `is_trade_allowed(db, symbol, check_time=None) -> bool` [L180-L210]
- **Inputs/outputs**: Symbol, optional check timestamp; returns `NewsBlackoutCheckResponse` schema.
- **Key algorithms and parameters**:
  - Blackout windows (from `Settings`):
    - `NEWS_BLACKOUT_BEFORE_MINUTES`: default `30` minutes [L55].
    - `NEWS_BLACKOUT_AFTER_MINUTES`: default `15` minutes [L56].
  - Currency resolution: Maps symbol (e.g. `XAU/USD` -> `USD`; `EUR/USD` -> `EUR`, `USD`) [L65-L80].
  - Impact filter: Blocks trades on `HIGH` impact events; warns on `MEDIUM` impact events [L95-L125].
- **Dependencies**: `app.models.news.NewsEvent`, `app.core.config.settings`.
- **Side effects**: Queries database.
- **Lookahead / determinism notes**: Accepts explicit `check_time` for historical backtest replay. Falls back to `now(UTC)`.
- **Tests**: Covered by `tests/test_news.py` (7 tests), `tests/test_news_integrity.py` (8 tests).
- **Known issues and risks**: None.

---

## Paper Trading Service (`app/services/paper_trading/`)

### paper_trading/account_manager.py
- **Purpose**: Manages virtual accounts, balances, deposits, leverage, margin calculations, and equity recalculation.
- **Status**: ACTIVE. Imported by `services.paper_trading.order_executor` [L17], `services.paper_trading.paper_service` [L14].
- **Public interface**:
  - `class AccountManager` [L20-L225]
    - `get_or_create_default_account(db, balance=10000.0, leverage=100.0) -> VirtualAccount` [L30-L75]
    - `calculate_required_margin(symbol, lots, price, leverage) -> float` [L80-L115]
    - `recalculate_account_financials(db, account) -> VirtualAccount` [L120-L175]
    - `deposit_funds(db, account_id, amount) -> VirtualAccount` [L180-L225]
- **Inputs/outputs**: DB session, account params; returns `VirtualAccount` model.
- **Key algorithms and parameters**:
  - Margin formula: $\text{Required Margin} = \frac{\text{lots} \times \text{contract\_size} \times \text{price}}{\text{leverage}}$ [L95-L105].
  - For XAU/USD: contract size = 100 oz. At $2,600/oz with 100:1 leverage, 1 lot requires $\frac{1 \times 100 \times 2600}{100} = \$2,600$ margin.
- **Dependencies**: `app.models.paper.VirtualAccount`, `AccountTransaction`, `app.services.market_data.symbols.get_instrument_spec`.
- **Side effects**: Writes and commits account and transaction updates in DB.
- **Lookahead / determinism notes**: State-based balance updates.
- **Tests**: Covered by `tests/test_paper_trading.py` (6 tests).
- **Known issues and risks**: None.

### paper_trading/order_executor.py
- **Purpose**: Executes paper orders from manual commands or automated signals; applies spread/slippage; validates margin and staleness.
- **Status**: ACTIVE. Imported by `services.paper_trading.paper_service` [L16], `services.telegram.scanner` [L16].
- **Public interface**:
  - `class PaperOrderExecutor` [L28-L425]
    - `execute_order(db, order_request) -> PaperTrade` [L45-L215]
    - `execute_order_from_signal(db, signal_id, risk_percent, position_size) -> PaperTrade` [L220-L380]
- **Inputs/outputs**: Order request or signal ID; returns `PaperTrade` record.
- **Key algorithms and parameters**:
  - Gate 1: Signal Staleness Check: Uses `signal.created_at` compared to current time. Rejects if age exceeds 2 hours [L120-L135].
  - Gate 2: Margin Check: Verifies `account.free_margin >= required_margin` [L138-L142].
  - Gate 3: Minimum SL Distance Guard: Rejects if market price is within `0.0001` of SL [L152-L162].
  - Execution Friction: Applies half-spread ($0.5 \times \text{pip\_size}$) and slippage ($0.2 \times \text{pip\_size}$) [L235-L245].
- **Dependencies**: `app.models.paper.PaperTrade`, `app.models.signal.Signal`, `RiskManager`, `AccountManager`.
- **Side effects**: Inserts `PaperTrade` and `AccountTransaction` records in DB.
- **Lookahead / determinism notes**: Real-time order execution uses `datetime.now(timezone.utc)`.
- **Tests**: Covered by `tests/test_paper_trading.py`, `tests/test_duplicate_integrity.py`.
- **Known issues and risks**: Line 152 defines `MIN_SL_DISTANCE_PIPS = 0.0001` (EUR/USD convention) instead of reading `pip_size` (which is $0.10 for XAU/USD).

### paper_trading/position_manager.py
- **Purpose**: Tracks open positions, updates unrealized P&L against live prices, and handles SL, TP1, and TP2 exits.
- **Status**: ACTIVE. Imported by `services.paper_trading.paper_service` [L15], `services.paper_trading.__init__` [L4].
- **Public interface**:
  - `class PositionManager` [L20-L341]
    - `sync_all_positions(db, current_prices=None) -> PositionSyncReport` [L35-L78]
    - `close_position_leg(db, trade, close_ratio, exit_reason) -> PaperTrade` [L80-L140]
    - `modify_position(db, trade_id, stop_loss, take_profit) -> PaperTrade` [L250-L300]
- **Inputs/outputs**: DB session, price dictionary; updates `PaperTrade` records and returns report.
- **Key algorithms and parameters**:
  - TP1 Partial Close: Closes 50% of position size upon touching TP1, adjusts SL to break-even (`entry_price`), and lets remaining 50% run to TP2 [L160-L195].
  - Stop Loss Exit: Closes 100% of remaining position upon touching SL [L200-L225].
  - P&L Calculation: `pnl = pips_gain * pip_val * lots` [L94].
- **Dependencies**: `app.models.paper.PaperTrade`, `AccountTransaction`, `AccountManager`.
- **Side effects**: Updates DB records, creates transaction entries, updates account balances.
- **Lookahead / determinism notes**: Evaluates against current market prices.
- **Tests**: Covered by `tests/test_paper_trading.py`.
- **Known issues and risks**: None.

### paper_trading/paper_service.py
- **Purpose**: High-level facade uniting account, order, and position managers for API and scanner consumption.
- **Status**: ACTIVE. Imported by `services.telegram.scheduler` [L14], `api.deps` [L20], `api.v1.paper` [L15].
- **Public interface**:
  - `class PaperTradingService` [L18-L224]
    - Facade methods for account creation, order placement, position monitoring, and performance stats.
- **Inputs/outputs**: Delegated directly to underlying managers.
- **Key algorithms and parameters**: Thin facade router.
- **Dependencies**: `AccountManager`, `PaperOrderExecutor`, `PositionManager`.
- **Side effects**: DB transactions.
- **Lookahead / determinism notes**: Stateful paper execution.
- **Tests**: Covered by `tests/test_paper_trading.py`, `tests/test_paper_trading_api.py`.
- **Known issues and risks**: None.

---

## Backtesting Service (`app/services/backtesting/`)

### backtesting/performance_metrics.py
- **Purpose**: Computes quantitative performance statistics from a list of executed trades.
- **Status**: ACTIVE. Imported by `services.backtesting.backtest_engine` [L20], `services.backtesting.__init__` [L3].
- **Public interface**:
  - `def calculate_performance_metrics(trades, initial_balance) -> BacktestMetrics` [L25-L196]
- **Inputs/outputs**: List of trade dicts/models and balance in; `BacktestMetrics` schema out.
- **Key algorithms and parameters**:
  - Metrics calculated: Win rate, Profit Factor, Max Drawdown ($ and %), Sharpe Ratio (annualized $R_f = 0$), Sortino Ratio, Calmar Ratio, Expectancy ($ and R-multiple) [L55-L175].
  - Zero trades guard: Returns clean zeroed metrics without ZeroDivisionError [L35-L50].
- **Dependencies**: `math`, `app.schemas.backtesting.BacktestMetrics`.
- **Side effects**: None.
- **Lookahead / determinism notes**: Pure post-trade analytics.
- **Tests**: Covered by `tests/test_backtesting.py` (5 tests).
- **Known issues and risks**: None.

### backtesting/backtest_engine.py
- **Purpose**: Historical simulation engine running candle-by-candle re-evaluations with simulated order execution.
- **Status**: ACTIVE. Imported by `services.backtesting.backtest_service` [L16], `services.backtesting.optimization` [L12].
- **Public interface**:
  - `class BacktestEngine` [L25-L593]
    - `run_backtest(candles, symbol, timeframe, config) -> BacktestResult` [L40-L380]
- **Inputs/outputs**: Candle sequence, config in; `BacktestResult` schema out.
- **Key algorithms and parameters**:
  - Loops bar by bar from index 50 to end. Evaluates `SignalGenerator.generate_signal()` at each bar.
  - Manages simulated pending limit orders and active positions.
  - Same-bar conflict handling: assumes SL hit first if bar low $\le$ SL and bar high $\ge$ TP [L265].
- **Dependencies**: `SignalGenerator`, `calculate_performance_metrics`.
- **Side effects**: None (runs in-memory).
- **Lookahead / determinism notes**: Simulates sequential bar arrivals.
- **Tests**: Covered by `tests/test_backtesting.py::test_backtest_engine_simulation`.
- **Known issues and risks**: Slow when evaluating large candle lists due to re-running the entire indicator/structure pipeline on every bar.

### backtesting/backtest_service.py
- **Purpose**: Database CRUD and orchestration service for managing saved backtest runs and trade logs.
- **Status**: ACTIVE. Imported by `api.deps` [L21], `api.v1.backtest` [L15].
- **Public interface**:
  - `class BacktestService` [L18-L310]
    - `execute_and_persist_backtest(db, request) -> BacktestRun` [L35-L160]
    - `get_run(db, run_id) -> Optional[BacktestRun]` [L165-L210]
    - `list_runs(db, symbol, skip, limit) -> List[BacktestRun]` [L215-L255]
    - `delete_run(db, run_id) -> bool` [L260-L310]
- **Inputs/outputs**: Backtest request schemas, DB session; persists and returns `BacktestRun` records.
- **Key algorithms and parameters**: Queries candles from DB, runs `BacktestEngine`, and writes run summary and individual trade records to `backtest_runs` and `backtest_trades` tables.
- **Dependencies**: `BacktestEngine`, `app.models.backtest.BacktestRun`, `BacktestTrade`.
- **Side effects**: DB writes and commits.
- **Lookahead / determinism notes**: Depends on underlying engine.
- **Tests**: Covered by `tests/test_backtest_api.py`.
- **Known issues and risks**: None.

### backtesting/optimization.py
- **Purpose**: Parameter grid search optimizer evaluating combinations of risk percent, minimum score, and minimum R:R.
- **Status**: ACTIVE. Imported by `services.backtesting.backtest_service` [L17], `api.v1.backtest` [L16].
- **Public interface**:
  - `class ParameterOptimizer` [L16-L116]
    - `optimize(candles, symbol, timeframe, param_grid) -> ParameterSweepResponse` [L25-L116]
- **Inputs/outputs**: Candles, parameter ranges in; `ParameterSweepResponse` out.
- **Key algorithms and parameters**: Cartesian product of candidate parameters; runs `BacktestEngine` for each combination and ranks by profit factor and Sharpe ratio [L50-L95].
- **Dependencies**: `BacktestEngine`.
- **Side effects**: None.
- **Lookahead / determinism notes**: In-memory backtest loop.
- **Tests**: Covered by `tests/test_backtesting.py::test_parameter_optimizer`, `tests/test_backtest_api.py`.
- **Known issues and risks**: In-process synchronous grid search can block the server if large grids are submitted via API.

### backtesting/walk_forward_harness.py
- **Purpose**: Phase 3 walk-forward testing harness: purged/embargoed cross-validation splits, trade-through execution, and random-walk control comparisons.
- **Status**: PARTIAL. Reachable via `scripts/backtest_report.py` [L19] and covered by unit tests.
- **Public interface**:
  - `class WalkForwardHarness` [L38-L699]
    - `run_walk_forward(...) -> WalkForwardReport` [L65-L350]
    - `split_train_validation_test(...)` [L355-L420]
    - `detect_session(ts) -> str` [L28-L36]
- **Inputs/outputs**: 15m candle database in; `WalkForwardReport` with out-of-sample statistics out.
- **Key algorithms and parameters**:
  - Fills: Requires price to trade through limit price [L210].
  - Purging: 48-hour embargo window between splits to eliminate cross-boundary overlap [L380-L400].
  - Random Walk Control: Generates synthetic price paths via geometric Brownian motion; asserts strategy edge exceeds random-walk baseline [L450-L520].
- **Dependencies**: `numpy`, `pandas`, `app.models.signal_candidate.SignalCandidate`.
- **Side effects**: Reads candles; logs execution metrics.
- **Lookahead / determinism notes**: Strict chronological progression; zero lookahead.
- **Tests**: Covered by `tests/test_walk_forward_harness.py` (7 tests), `tests/test_control_random_walk.py`.
- **Known issues and risks**: Line 28 `detect_session` uses raw UTC hours (0–8 Asia, 8–13 London, 13–21 NY) ignoring Daylight Saving Time.

---

## Telegram Service (`app/services/telegram/`)

### telegram/client.py
- **Purpose**: Telegram Bot HTTP client providing asynchronous message transmission and error handling.
- **Status**: ACTIVE. Imported by `services.telegram.scheduler` [L16], `services.telegram.command_handler` [L20], `services.telegram.scanner` [L17].
- **Public interface**:
  - `class TelegramClient` [L20-L223]
    - `send_message(text, chat_id=None, parse_mode="HTML") -> bool` [L35-L125]
    - `health_check() -> Dict[str, Any]` [L130-L165]
- **Inputs/outputs**: HTML text in; performs HTTP POST to `https://api.telegram.org/bot<TOKEN>/sendMessage`.
- **Key algorithms and parameters**:
  - Token and Chat ID from `settings.TELEGRAM_BOT_TOKEN` and `settings.TELEGRAM_CHAT_ID` [L25-L30].
  - Fallback: If token or chat ID is missing, logs warning and returns `False` without raising exception [L40-L48].
- **Dependencies**: `httpx.AsyncClient`, `app.core.config.settings`, `app.core.logging.logger`.
- **Side effects**: Outbound HTTPS network calls to Telegram servers.
- **Lookahead / determinism notes**: Network delivery client.
- **Tests**: Covered by `tests/test_telegram.py::test_mock_telegram_client`.
- **Known issues and risks**: Message length limit of 4096 characters enforced by Telegram API; overly long messages can be rejected if not split.

### telegram/command_handler.py
- **Purpose**: Parses and dispatches interactive Telegram bot commands (`/scan`, `/signal`, `/news`, `/account`, `/positions`, `/performance`, `/help`).
- **Status**: ACTIVE. Imported by `services.telegram.telegram_service` [L14], `services.telegram.__init__` [L4].
- **Public interface**:
  - `class TelegramCommandHandler` [L25-L402]
    - `handle_command(db, request) -> TelegramCommandResponse` [L72-L402]
- **Inputs/outputs**: Incoming command text, user ID, chat ID in; formatted response text out.
- **Key algorithms and parameters**:
  - Parses root command using case-insensitive slash prefix [L85-L100].
  - Dispatches `/scan` -> `SignalGenerator.scan_all_pairs_unified` [L125-L170].
  - Dispatches `/signal <symbol>` -> `SignalGenerator.generate_signal` [L175-L220].
  - Dispatches `/news` -> `NewsFilterEngine.check_blackout` [L225-L260].
  - Dispatches `/account`, `/positions`, `/performance` -> `PaperTradingService` [L265-L350].
- **Dependencies**: `SignalGenerator`, `PaperTradingService`, `NewsFilterEngine`, `TelegramMessageFormatter`.
- **Side effects**: Triggers market scans and database queries.
- **Lookahead / determinism notes**: Command handler; operates on current DB state.
- **Tests**: Covered by `tests/test_telegram.py::test_telegram_command_handler`, `tests/test_candle_fallback_and_webhook.py`.
- **Known issues and risks**: None.

### telegram/message_formatter.py
- **Purpose**: HTML message formatting for Telegram notifications (signals, scan digests, risk warnings, paper trades).
- **Status**: ACTIVE. Imported by `services.telegram.scanner` [L18], `services.telegram.command_handler` [L21].
- **Public interface**:
  - `class TelegramMessageFormatter` [L20-L588]
    - `format_signal_message(signal, metadata=None) -> str` [L35-L250]
    - `format_scan_digest(scan_response) -> str` [L255-L380]
    - `format_paper_trade_alert(trade) -> str` [L385-L480]
    - `escape_html(text) -> str` [L485-L510]
- **Inputs/outputs**: `SignalResponse` or `PaperTrade` models in; HTML-formatted string out.
- **Key algorithms and parameters**:
  - HTML escaping: Sanitizes `&`, `<`, `>` to prevent Telegram parse errors [L490-L495].
  - RISK EXCEEDS LIMIT formatting: If `risk_warning` present, formats warning line `⚠️ RISK EXCEEDS LIMIT: <msg>` and suppresses normal lot size display [L220-L230].
  - Displays Bangkok time: `expires_utc7` converted from UTC to UTC+7 (`Asia/Bangkok`) [L120-L125].
- **Dependencies**: `html.escape`, `app.schemas.signal.SignalResponse`, `app.models.paper.PaperTrade`.
- **Side effects**: None (pure formatting).
- **Lookahead / determinism notes**: Formatting only.
- **Tests**: Covered by `tests/test_message_formatter_pure.py` (6 tests), `tests/test_crt_strategy.py`.
- **Known issues and risks**: None.

### telegram/scanner.py
- **Purpose**: Automated market scanning worker: executes multi-pair scans on candle close, enforces signal deduplication, and broadcasts alerts.
- **Status**: ACTIVE. Imported by `services.telegram.scheduler` [L17], `services.telegram.telegram_service` [L15].
- **Public interface**:
  - `class AutomatedMarketScanner` [L28-L616]
    - `run_scan_cycle(db, symbols, timeframes, broadcast_to_telegram=True, auto_paper_trade=True) -> List[SignalResponse]` [L100-L315]
    - `has_active_position(db, symbol) -> bool` [L88-L98]
- **Inputs/outputs**: DB session, symbols, timeframes; returns list of generated signals.
- **Key algorithms and parameters**:
  - Pre-scan position guard: Checks `has_active_position()`. If an open position exists for the symbol in `paper_trades`, skips new signal generation to avoid stacking positions [L125-L135].
  - Closed-candle fetch: Fetches latest 15m closed bars, resamples locally to 1h/4h [L317-L360].
  - Deduplication: Maintains in-memory set `_recent_fingerprints` and seeds from `signals` table on startup [L72-L85].
  - Signal Broadcast: Formats message via `TelegramMessageFormatter` and calls `TelegramClient.send_message()` [L235-L260].
  - Auto Paper Trade: If `auto_paper_trade=True` and signal is qualified, calls `PaperTradingService.execute_order_from_signal()` [L265-L290].
- **Dependencies**: `SignalGenerator`, `PaperTradingService`, `TelegramClient`, `TwelveDataProvider`, `ForexFactoryProvider`.
- **Side effects**: Writes to `signals` and `paper_trades` tables; sends Telegram messages.
- **Lookahead / determinism notes**: Operates on persisted closed candles.
- **Tests**: Covered by `tests/test_scanner_scheduler.py` (17 tests), `tests/test_signals.py`.
- **Known issues and risks**: None.

### telegram/scheduler.py
- **Purpose**: APScheduler background runner firing automated market scans at candle-close boundaries.
- **Status**: ACTIVE. Started in `app.main` lifespan [L38] and stopped at shutdown [L45].
- **Public interface**:
  - `def start_scanner_scheduler(scanner=None) -> Optional[AsyncIOScheduler]` [L76-L172]
  - `def stop_scanner_scheduler()` [L174-L181]
  - `def get_scheduler_info() -> Dict[str, Any]` [L50-L74]
  - `def is_scheduler_running() -> bool` [L44-L48]
- **Inputs/outputs**: Manages background `AsyncIOScheduler`.
- **Key algorithms and parameters**:
  - Cron trigger: Fires at `:00:10, :15:10, :30:10, :45:10 UTC` (10 seconds after each 15-minute candle close boundary) [L143-L167].
  - Offset rationale: The 10-second offset ensures Twelve Data has completed persisting the closed bar before the scanner queries it [L81-L85].
  - Settings: `max_instances=1`, `coalesce=True`, `misfire_grace_time=60` [L164-L166].
- **Dependencies**: `apscheduler.schedulers.asyncio.AsyncIOScheduler`, `apscheduler.triggers.cron.CronTrigger`, `app.core.config.settings`.
- **Side effects**: Spawns background asyncio tasks on scheduled intervals.
- **Lookahead / determinism notes**: Scheduled 10 seconds post-close to guarantee strictly completed bars.
- **Tests**: Covered by `tests/test_scanner_scheduler.py` (17 tests), `tests/conftest.py`.
- **Known issues and risks**: None.

### telegram/telegram_service.py
- **Purpose**: Service facade exposing bot status, webhook processing, manual broadcast, and scanner triggering to API routers.
- **Status**: ACTIVE. Injected as FastAPI dependency in `api.deps` [L22] and mounted in `api.v1.telegram` [L18].
- **Public interface**:
  - `class TelegramBotService` [L18-L70]
    - `get_status() -> Dict[str, Any]` [L25-L42]
    - `process_command(db, request) -> TelegramCommandResponse` [L44-L48]
    - `broadcast_signal(db, signal_id) -> bool` [L50-L58]
    - `trigger_manual_scan(db) -> List[SignalResponse]` [L60-L70]
- **Inputs/outputs**: Delegated to `TelegramCommandHandler`, `TelegramClient`, and `AutomatedMarketScanner`.
- **Key algorithms and parameters**: Thin facade coordinating Telegram operations.
- **Dependencies**: `TelegramClient`, `TelegramCommandHandler`, `AutomatedMarketScanner`.
- **Side effects**: Network calls, database queries.
- **Lookahead / determinism notes**: Real-time service layer.
- **Tests**: Covered by `tests/test_telegram_api.py` (4 tests).
- **Known issues and risks**: None.
