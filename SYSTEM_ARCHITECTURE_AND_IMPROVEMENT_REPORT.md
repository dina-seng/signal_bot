# 🏛️ Institutional Quantitative Architecture Document & Engineering Audit
**System:** Forex Market Analysis, Smart Money Concepts (SMC) Engine & Signal Bot  
**Repository Scope:** `D:\trade` (`server/`, `client/`, `app/`)  
**Target Environment:** Python 3.10+ / FastAPI / SQLAlchemy / PostgreSQL (Neon) & SQLite / React 18 (Vite) / APScheduler

---

## 1. System Architecture & Tech Stack Breakdown

### 1.1 High-Level Architecture Overview
The system is structured as an **event-driven quantitative trading signal generation and simulation platform**. It continuously ingests macroeconomic news feeds and multi-timeframe OHLCV candles, evaluates structural market dynamics (Smart Money Concepts / ICT principles), calculates mathematical technical indicators, applies confluence weighting and news blackout guards, sizes risk dynamically, and dispatches signals to Telegram and an automated paper trading simulation. A high-performance React dashboard ("QuantView") monitors portfolio telemetry and system state.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PRESENTATION LAYER                              │
│   QuantView React Dashboard (Vite / TS / Tailwind)  │  Telegram Bot   │
└───────────────────▲──────────────────────────────────────▲─────────────┘
                    │ REST API / Polling                   │ Webhook / Poll
┌───────────────────┴──────────────────────────────────────┴─────────────┐
│                          FASTAPI APPLICATION                           │
│  Routers: /market, /signals, /structure, /liquidity, /paper, /news    │
└───────────────▲───────────────────────▲───────────────────────▲────────┘
                │                       │                       │
┌───────────────┴────────┐  ┌───────────┴──────────┐  ┌─────────┴────────┐
│  BACKGROUND SCANNER    │  │ CONFLUENCE ENGINE    │  │ PAPER TRADING    │
│  APScheduler (:XX:10)  │  │ StrategyManager      │  │ Order Executor   │
│  Async Ingestion Loop  │  │ SMC + Price Action   │  │ Position Manager │
└───────────────▲────────┘  └───────────▲──────────┘  └─────────▲────────┘
                │                       │                       │
┌───────────────┴───────────────────────┴───────────────────────┴────────┐
│                          PERSISTENCE LAYER                             │
│   SQLAlchemy 2.0 ORM  │  PostgreSQL (Neon Cloud) / SQLite (Local)     │
│   Tables: candles, structure_events, signals, paper_trades, news       │
└───────────────▲───────────────────────────────────────────────▲────────┘
                │                                               │
┌───────────────┴────────┐                             ┌────────┴────────┐
│ MARKET DATA PROVIDERS  │                             │  NEWS CALENDAR  │
│ Twelve Data / YFinance │                             │  ForexFactory   │
└────────────────────────┘                             └─────────────────┘
```

### 1.2 Tech Stack Inventory

| Component | Technology | Role & Purpose |
| :--- | :--- | :--- |
| **Backend Framework** | FastAPI (ASGI), Uvicorn | High-throughput asynchronous REST API presentation layer |
| **ORM & Data Layer** | SQLAlchemy 2.0 (Sync engine) | Object-relational mapping, pool pre-ping, connection recycling |
| **Databases** | PostgreSQL (Neon Cloud) / SQLite | Relational persistence for OHLCV bars, trades, signals, news |
| **Scheduler** | APScheduler (`AsyncIOScheduler`) | Candle-close-aligned background scanner (fires at `:00:10`, `:15:10`, `:30:10`, `:45:10` UTC) |
| **HTTP Clients** | `httpx` (AsyncClient) | Non-blocking external API ingestion (Twelve Data, ForexFactory, Telegram) |
| **Data Validation** | Pydantic v2 & `pydantic-settings` | Strict schema validation, environment variable type coercion |
| **Frontend Framework**| React 18, TypeScript, Vite | Bloomberg-terminal inspired real-time trading dashboard |
| **UI Styling** | Tailwind CSS, Lucide React | Modern dark-mode UI, responsive layouts, data visualization |
| **Testing Harness** | Pytest, AnyIO, Asyncio | Comprehensive 196-item unit and integration test suite |

---

## 2. Component Descriptions

### 2.1 Ingestion & Market Data Layer (`server/app/services/market_data/`)
- **`TwelveDataProvider`**: Primary Forex/commodity provider. Queries Twelve Data REST API (`/time_series`). Enforces a 7.5s interval to comply with free-tier rate limits (8 calls/min). Automatically drops unclosed bars (`drop_unclosed=True`).
- **`YahooFinanceProvider`**: Secondary fallback provider querying Yahoo Finance for historical backfill.
- **`MockMarketDataProvider`**: Deterministic synthetic candle generator for offline simulation and unit testing.
- **`IngestionService`**: 
  - Validates price invariants ($High \ge Low$, $High \ge Open$, $High \ge Close$).
  - Performs deduplication (intra-batch timestamp set deduplication and DB existence check).
  - Detects data gaps (accounting for Forex weekend closures: Friday 21:00 UTC – Sunday 21:00 UTC).
  - Implements a *Smart Freshness Cache Gate*: Skips remote API fetches if the latest closed candle in the DB is still within the active bar window.

### 2.2 News & Fundamental Protection Layer (`server/app/services/news/`)
- **`ForexFactoryProvider`**: Scrapes high/medium impact macroeconomic calendar data from `ff_calendar_thisweek.json` with exponential backoff retries. Generates SHA-256 fingerprints to ensure idempotent upserts.
- **`NewsFilterEngine`**: Enforces pre- and post-event trading freeze windows (default: 30 minutes before, 15 minutes after high-impact events like NFP, FOMC, CPI).
- **Fail-Safe Mechanism**: If the live economic feed is unreachable or stale, trading signals are blocked immediately with `is_news_unavailable=True`.

### 2.3 Quantitative Analysis & SMC Engine (`server/app/services/structure/`, `indicators/`, `liquidity/`)
- **`SwingDetector`**: Implements pure fractal extrema detection using configurable left/right lookback windows (default: $N=2$). Identifies Swing Highs and Swing Lows.
- **`StructureEngine`**: Classifies swings into Higher Highs (HH), Higher Lows (HL), Lower Highs (LH), and Lower Lows (LL); classifies macro trend as `BULLISH`, `BEARISH`, or `RANGING`.
- **`BOSCHOCHDetector`**: Detects Break of Structure (BOS, trend continuation) and Change of Character (CHOCH/MSS, trend reversal) requiring candle body closes beyond previous extrema with displacement filtering.
- **`LiquiditySweepDetector`**: Detects institutional Buy-Side (BSL) and Sell-Side (SSL) liquidity sweeps—wick penetration through key swing highs/lows followed by strong rejection closing back inside the range.
- **`SRDetector`**: Groups price clusters into dynamic Support/Resistance zones and Equal Highs/Lows (EQH/EQL) pools.
- **`IndicatorService`**: Computes 20/50/200 EMA stacks, Wilder's 14-period RSI with regular/hidden divergence detection, 14-period ATR volatility, and Price Action patterns (Fair Value Gaps [FVG], Pin Bars, Engulfing bars).

### 2.4 Strategy & Confluence Layer (`server/app/services/signals/`, `strategies/`)
- **`StrategyManager`**: Pluggable strategy orchestrator dispatching candles to:
  - `SMCStrategy`: Standard trend continuation & reversal setups.
  - `CRTStrategy`: Candle Range Theory session sweeps.
  - `RangeStrategy`: Mean reversion between defined S/R boundaries.
- **`ConfluenceEngine`**: Synthesizes multi-pillar scores (Structure: 35, Liquidity: 30, Indicators: 20, Price Action: 15). Enforces strict veto floors (e.g., price action score $\ge 10$, structure+liquidity $\ge 20$).
- **`PathValidator`**: Ray-tracing validator that inspects the trade path between entry and Take Profit 1. Flags obstacles (opposing FVGs, resting liquidity pools, unmitigated S/R levels) and attaches informational advisories.
- **`RiskManager`**: Sizes dynamic Stop Loss (structural swing anchor + $0.5 \times \text{ATR}$ buffer or pure $1.5 \times \text{ATR}$) and calculates Take Profit targets maintaining a minimum 1:2 Risk:Reward ratio. Calculates suggested lot size based on account balance and maximum risk percentage.

### 2.5 Execution & Notification Layer (`server/app/services/paper_trading/`, `telegram/`)
- **`AutomatedMarketScanner`**: Coordinates scanning loops across configured symbols and timeframes. Verifies active positions, checks cooldown timers (preventing duplicate hourly alerts), and dispatches qualified signals.
- **`PaperOrderExecutor`**: Simulates order placement with realistic spread (0.5 pip) and slippage (0.2 pip). Executes pre-flight staleness and price-invalidation gates.
- **`PaperPositionManager`**: Monitors open positions on incoming ticks/bars, detects Stop Loss and Take Profit breaches, supports partial exits at TP1, and manages break-even trailing stops.
- **`TelegramClient` & `TelegramMessageFormatter`**: Builds structured Markdown alert cards with entry, SL, TP1, TP2, R:R, confluence breakdown, and path warnings, broadcasting to configured chat IDs.

---

## 3. Data Flow Lifecycle

```
[ APScheduler Cron / API Trigger ]
              │
              ▼
    1. MARKET DATA INGESTION
       - Twelve Data REST call (/time_series)
       - Invariant checking & deduplication
       - DB Bulk Insert (Candle table)
              │
              ▼
    2. NEWS CALENDAR SYNCHRONIZATION
       - ForexFactory JSON feed fetch
       - Deduplication & Upsert into NewsEvent
              │
              ▼
    3. MULTI-TIMEFRAME DATA RETRIEVAL
       - Fetch 100-200 closed bars (15m, 1h, 4h)
       - Filter unclosed active bars
              │
              ▼
    4. MACRO NEWS BLACKOUT GATE
       - Check scheduled news within [-30m, +15m]
       - If high-impact news active ──► [ Block Signal / Return WAIT ]
              │ (Trading Allowed)
              ▼
    5. QUANTITATIVE & SMC ANALYSIS
       - Swing Detection (N-bar extrema)
       - BOS / CHOCH Breakout Detection
       - Liquidity Sweeps (BSL / SSL)
       - Indicators (EMA Stack, Wilder RSI, ATR, FVG)
              │
              ▼
    6. CONFLUENCE SCORING & STRATEGY EVALUATION
       - StrategyManager runs (SMC, CRT, Range)
       - Pillar Scoring (Structure, Liquidity, Ind, PA)
       - Veto Gate Enforcement (Min Score >= 75%)
              │
              ▼
    7. RISK MANAGEMENT & PATH VALIDATION
       - Structural / ATR Stop Loss & TP1 (Min 1:2 R:R)
       - Position sizing (Lot calculation)
       - Path Obstacle Inspection (S/R, FVG check)
              │
              ▼
    8. PERSISTENCE & EXECUTION
       - Signal persisted in DB (Fingerprint deduplication)
       - If Paper Trading enabled ──► Virtual position opened
       - If Telegram enabled ─────► Rich Markdown dispatched to chat
              │
              ▼
    9. DASHBOARD TELEMETRY
       - QuantView React UI polls updated account equity & signal matrix
```

---

## 4. End-to-End System Architecture Flowchart

```mermaid
flowchart TD
    %% Styling
    classDef external fill:#1e293b,stroke:#38bdf8,stroke-width:2px,color:#f8fafc;
    classDef core fill:#0f172a,stroke:#818cf8,stroke-width:2px,color:#f8fafc;
    classDef storage fill:#1e1b4b,stroke:#a855f7,stroke-width:2px,color:#f8fafc;
    classDef decision fill:#311042,stroke:#ec4899,stroke-width:2px,color:#f8fafc;
    classDef execution fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#f8fafc;
    classDef ui fill:#1c1917,stroke:#f59e0b,stroke-width:2px,color:#f8fafc;

    subgraph EXT["External Providers & Services"]
        P_TD["Twelve Data API\n(Forex & Gold Candles)"]:::external
        P_YF["Yahoo Finance\n(Historical Backfill)"]:::external
        P_FF["ForexFactory JSON\n(Economic Calendar)"]:::external
        P_TG["Telegram Bot API\n(Alert Dispatch)"]:::external
    end

    subgraph SCHED["Automation & Orchestration"]
        CRON["APScheduler\n(:00:10, :15:10, :30:10, :45:10 UTC)"]:::core
    end

    subgraph INGEST_LAYER["Ingestion Pipeline (app/services/market_data & news)"]
        ING_MKT["Market Ingestion Service\n- Invariant Validation\n- Gap Detection\n- Cache Freshness Gate"]:::core
        ING_NEWS["News Ingestion Service\n- SHA-256 Fingerprinting\n- Deduplication & Upsert"]:::core
    end

    subgraph DB_LAYER["Persistence Engine (PostgreSQL / SQLite)"]
        T_CANDLE[("Candles Table\n(symbol, tf, timestamp)")]:::storage
        T_NEWS[("News Events Table")]:::storage
        T_SIGNAL[("Trade Signals Table")]:::storage
        T_PAPER[("Paper Trades & Accounts")]:::storage
        T_STRUCT[("Structure Events Table")]:::storage
    end

    subgraph ANALYTICS["Technical & SMC Analysis Engine"]
        SMC_SWING["Swing Detector\n(N=2 Fractal Extrema)"]:::core
        SMC_BOS["BOS / CHOCH Detector\n(Trend & Reversal Shifts)"]:::core
        SMC_LIQ["Liquidity Sweep Detector\n(BSL/SSL Stop Hunts)"]:::core
        IND_TECH["Indicators & Patterns\n- EMA 20/50/200 Stack\n- Wilder's RSI (14) Divergence\n- ATR (14) & FVGs"]:::core
    end

    subgraph DECISION_LAYER["Decision & Risk Architecture"]
        STRAT_MGR["Strategy Manager\n(SMC, CRT, Range Strategies)"]:::decision
        NEWS_GATE{"News Blackout\nFilter Active?"}:::decision
        CONF_SCORE{"Confluence Score\n>= 75.0 & Veto Check"}:::decision
        PATH_VAL["Path Validator\n(S/R & FVG Obstacle Ray-Cast)"]:::decision
        RISK_MGR["Risk Manager\n- Dynamic ATR SL/TP\n- Min 1:2 R:R\n- Position Sizing"]:::decision
    end

    subgraph EXEC_LAYER["Execution & Dispatch Engine"]
        PAPER_ENG["Paper Trading Engine\n- Spread & Slippage Model\n- SL/TP Trailing Monitor"]:::execution
        TG_CLIENT["Telegram Service\n- Cooldown Checker (2h)\n- Markdown Formatter"]:::execution
    end

    subgraph UI_LAYER["Presentation Layer"]
        API_ROUTER["FastAPI Router (/api/v1/*)"]:::ui
        REACT_DASH["QuantView React Dashboard\n(Active Positions, Charting, Metrics)"]:::ui
    end

    %% Flow Connections
    CRON -->|Triggers Scan| ING_MKT
    CRON -->|Triggers Calendar Sync| ING_NEWS

    P_TD -->|Candle HTTP Stream| ING_MKT
    P_YF -.->|Historical Fallback| ING_MKT
    P_FF -->|Weekly Calendar JSON| ING_NEWS

    ING_MKT -->|Bulk Insert| T_CANDLE
    ING_NEWS -->|Upsert Events| T_NEWS

    T_CANDLE -->|Fetch Verified Closed Bars| ANALYTICS
    T_NEWS -->|Query Active Events| NEWS_GATE

    ANALYTICS --> SMC_SWING
    ANALYTICS --> SMC_BOS
    ANALYTICS --> SMC_LIQ
    ANALYTICS --> IND_TECH

    SMC_SWING & SMC_BOS & SMC_LIQ & IND_TECH --> STRAT_MGR
    STRAT_MGR --> NEWS_GATE

    NEWS_GATE -- Yes (Blackout) --> VETO_EXIT["Halt: Return WAIT Signal"]:::decision
    NEWS_GATE -- No (Clear) --> CONF_SCORE

    CONF_SCORE -- Fail (<75%) --> VETO_EXIT
    CONF_SCORE -- Pass (>=75%) --> RISK_MGR

    RISK_MGR --> PATH_VAL
    PATH_VAL -->|Qualified Signal| T_SIGNAL

    T_SIGNAL --> PAPER_ENG
    T_SIGNAL --> TG_CLIENT

    PAPER_ENG -->|Record Trade & Position| T_PAPER
    TG_CLIENT -->|HTTP POST| P_TG

    DB_LAYER -.->|Query State| API_ROUTER
    API_ROUTER <-->|REST Polling (3s/10s)| REACT_DASH
```

---

## 5. Comprehensive Vulnerability & Bottleneck Audit

Our code inspection and test harness execution revealed critical structural flaws, security concerns, concurrency bugs, and mathematical inaccuracies.

### 5.1 High-Severity Concurrency Bug in Background Scanner (`scanner.py`)
- **Location:** `server/app/services/telegram/scanner.py`, lines 314–337
- **Mechanism:** In `run_scan_cycle`, a single synchronous SQLAlchemy session (`db: Session`) is passed into `asyncio.gather(*ingestion_tasks)`.
- **Flaw:** SQLAlchemy `Session` is **not coroutine-safe or thread-safe**. When coroutines run concurrently with `api_semaphore = asyncio.Semaphore(3)`, they execute `select(Candle)`, `db.add_all()`, `db.commit()`, and `db.rollback()` on the **exact same session simultaneously**.
- **Impact:** Leads to session corruption, `InvalidRequestError: This Session's transaction has been rolled back`, and cross-coroutine rollback of committed data.

### 5.2 Critical Provider Latency & Rate-Limit Bottleneck (`twelvedata_provider.py`)
- **Location:** `server/app/services/market_data/twelvedata_provider.py`, lines 44–52
- **Mechanism:** Enforces a rigid 7.5-second sleep (`_rate_limit(min_interval=7.5)`) per request to avoid Twelve Data's 8 credits/min limit.
- **Flaw:** Evaluating 2 symbols across 4 timeframes requires 8 requests. Executed sequentially, **a single market scan takes a minimum of 60 seconds of idle blocking sleep**.
- **Impact:** If the scheduler triggers every 15 minutes, a network timeout or credit exhaustion results in dropped signals. Scanner cycles can overlap or fail to complete before the next candle event.

### 5.3 Client Connection Churn (`twelvedata_provider.py`, `client.py`)
- **Location:** `twelvedata_provider.py` (line 86) and `telegram/client.py` (line 125)
- **Flaw:** Instantiates a new `httpx.AsyncClient()` on **every single outbound HTTP request** via `async with httpx.AsyncClient(...) as client:`.
- **Impact:** Destroys TCP connection reuse and keep-alive pools. Each call incurs full DNS resolution, TCP three-way handshake, and TLS negotiation overhead, adding 150–400ms of unnecessary latency per request.

### 5.4 Security Flaw: Wildcard CORS with Credentials (`main.py`)
- **Location:** `server/app/main.py`, lines 44–50
- **Flaw:** Configured with `allow_origins=["*"]` and `allow_credentials=True`.
- **Security Risk:** This violates modern browser CORS specifications and standard web security posture. Modern browsers reject requests matching wildcard origins with credentials. If a reverse proxy or browser allows it, it exposes authenticated session data and internal endpoints to Cross-Site Scripting (XSS) / CSRF exploitation from arbitrary origins.

### 5.5 Production Startup Data Loss Risk (`database.py`)
- **Location:** `server/app/core/database.py`, lines 58–64
- **Flaw:** Inside `init_db()`, the engine runs:
  ```python
  if "account_id" not in columns:
      conn.execute(text("DROP TABLE IF EXISTS paper_trades"))
      conn.commit()
  ```
- **Impact:** Automatically drops the live paper trades database table on service restart if schema checks trip, instead of utilizing proper non-destructive version-controlled database migrations (Alembic).

### 5.6 Lookahead Bias in Swing and Breakout Confirmation
- **Location:** `server/app/services/structure/bos_choch_detector.py` (line 86) & `liquidity/sweep_detector.py` (line 90)
- **Quantitative Flaw:** `SwingDetector` requires $N_{right} = 2$ subsequent bars to confirm that candle $i$ was indeed a swing point. However, in `bos_choch_detector.py` and `sweep_detector.py`:
  ```python
  for i in range(total_bars):
      if i in swings_by_idx:
          active_highs.append(swings_by_idx[i])
  ```
  At candle $i$, the swing at $i$ is activated immediately. If candle $i+1$ penetrates candle $i$'s price, the detector registers a breakout or sweep of an extreme that **could not have been known to exist until bar $i+2$ closed**.
- **Impact:** Backtests overestimate trade accuracy and signal frequency due to subtle forward lookahead leakage.

### 5.7 Math Error in Forex Pip Value & Position Sizing (`risk_manager.py`)
- **Location:** `server/app/services/signals/risk_manager.py`, lines 21–27
- **Quantitative Flaw:**
  ```python
  @staticmethod
  def get_pip_value_per_lot(symbol: str) -> float:
      if "XAU" in s or "GOLD" in s:
          return 1.0
      return 10.0  # Assumes standard FX pair = $10/lot
  ```
- **Financial Error:** A pip value of $10.00/standard lot is **only valid when USD is the QUOTE currency** (e.g. EUR/USD, GBP/USD). For `USD/JPY`, where USD is the BASE currency, 1 pip = 1,000 JPY. In USD terms:
  $$\text{Pip Value} = \frac{1000}{\text{USD/JPY Price}}$$
  At a current rate of 155.00 JPY/USD, 1 pip is worth $\approx \$6.45$, not $\$10.00$.
- **Impact:** Risk calculations and lot sizes for USD/JPY are distorted by **over 35%**, leading to undersized positions or inaccurate risk-to-reward ratios.

### 5.8 Database Ambiguity in Position Manager (`position_manager.py`)
- **Location:** `server/app/services/paper_trading/position_manager.py`, line 78
- **Flaw:** When closing a position without an explicit price:
  ```python
  stmt = select(Candle).where(Candle.symbol == trade.symbol).order_by(desc(Candle.timestamp)).limit(1)
  ```
- **Impact:** Queries the `candles` table without filtering by `timeframe`. Because candles for `15m`, `30m`, `1h`, and `4h` are stored with matching timestamps, the database returns an arbitrary timeframe candle's closing price.

### 5.9 Dashboard Polling Storm & Lack of Push Architecture
- **Location:** `client/src/App.tsx`, lines 96–250
- **Flaw:** The React dashboard executes aggressive periodic polling:
  - Account, positions, trades, and performance every 3 seconds (4 HTTP requests).
  - Price matrix, candlestick slices, and signals every 10 seconds (3+ HTTP requests).
- **Impact:** A single active dashboard client sends 100+ requests per minute directly to FastAPI and the SQL database. Multiple open tabs saturate FastAPI worker threads and exhaust the database connection pool.

### 5.10 Test Suite Pollution from Environment Variables
- **Empirical Evidence:** In test execution, 8 of 196 tests failed:
  1. `test_duplicate_integrity.py::test_paper_trade_idempotency_from_signal`: Hardcoded fallback price in `order_executor.py` (`1.1000`) collided with the test signal's Stop Loss (`1.1000`), tripping a degenerate setup gate.
  2. `test_signals_api.py::test_scan_markets_endpoint`: Test asserts 4 returned symbols, but `.env` configures `SUPPORTED_SYMBOLS=["XAU/USD", "USD/JPY"]` (length 2).
  3. `test_unified_scanner.py` (3 tests): Test looks for `EUR/USD`, which is omitted by `.env`.
  4. `test_production_parity.py` (3 tests): Non-deterministic fingerprints caused by using `datetime.now(timezone.utc)` instead of the candle timestamp during signal evaluation.

---

## 6. Actionable Improvement Roadmap

### Milestone 1: Concurrency, Database & Network Architecture
1. **Per-Coroutine Database Sessions in Scanner:**
   - In `scanner.py`, create an isolated session factory context per ingestion task:
     ```python
     async def _sync_symbol_tf(sym: str, tf: str) -> None:
         async with api_semaphore:
             with SessionLocal() as task_db:
                 service = IngestionService(provider=self.market_provider, db=task_db)
                 await service.sync_symbol_timeframe(symbol=sym, timeframe=tf, limit=100)
     ```
2. **Persistent HTTP Client Session Pooling:**
   - Manage persistent singleton `httpx.AsyncClient` instances in `main.py` lifespan state:
     ```python
     @asynccontextmanager
     async def lifespan(app: FastAPI):
         app.state.http_client = httpx.AsyncClient(timeout=15.0)
         yield
         await app.state.http_client.aclose()
     ```
3. **CORS Hardening:**
   - Replace wildcard origins with specific whitelisted client hosts:
     ```python
     app.add_middleware(
         CORSMiddleware,
         allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
         allow_credentials=True,
         allow_methods=["GET", "POST", "PUT", "DELETE"],
         allow_headers=["*"],
     )
     ```
4. **WebSocket / Server-Sent Events (SSE) for Dashboard:**
   - Introduce an `/api/v1/stream/telemetry` WebSocket endpoint pushing account balance, open position PnL, and new signals on state mutations, replacing 3-second client polling.

### Milestone 2: Quantitative Engine & TA Accuracy
1. **Lookahead Bias Remediation in Swing Breakouts:**
   - Enforce that a swing point discovered at index $k$ with $N_{right}$ confirmation bars can only be activated into `active_highs` or `active_lows` once the loop counter reaches $i \ge k + N_{right}$:
     ```python
     # Confirmed swing at k becomes visible to the market at k + lookback_right
     if (i - lookback_right) in swings_by_idx:
         confirmed_swing = swings_by_idx[i - lookback_right]
         if confirmed_swing.swing_type == SwingType.SWING_HIGH:
             active_highs.append(confirmed_swing)
     ```
2. **Dynamic Cross-Currency Pip Value Calculator:**
   - Refactor `RiskManager.get_pip_value_per_lot` to dynamically resolve quote currency:
     ```python
     @staticmethod
     def get_pip_value_per_lot(symbol: str, current_price: float = 1.0) -> float:
         clean = symbol.upper().replace("%2F", "/").strip()
         if "XAU" in clean or "GOLD" in clean:
             return 1.0  # 100 oz contract: 0.01 = $1.00
         base, quote = clean.split("/") if "/" in clean else (clean[:3], clean[3:])
         if quote == "USD":
             return 10.0  # 100,000 * 0.0001
         elif base == "USD":
             return 1000.0 / current_price if current_price > 0 else 10.0
         return 10.0
     ```
3. **Deterministic Fingerprints for Backtest Reproducibility:**
   - In `ConfluenceEngine`, replace `now_utc = datetime.now(timezone.utc)` with the latest closed candle's timestamp when generating fallback or WAIT fingerprints, ensuring identical hashes across repeated runs.

### Milestone 3: Data Resilience & Multi-Provider Redundancy
1. **Multi-Provider Ingestion Fallback Pipeline:**
   - Build a provider chain: If Twelve Data hits rate limits (429 or status error), seamlessly fall back to Yahoo Finance or CCXT/Binance (for crypto/commodities).
2. **In-Memory Calendar Caching:**
   - Cache ForexFactory JSON responses in memory with a 15-minute TTL to prevent redundant downloads across rapid scan cycles.

### Milestone 4: Test Suite Hermeticity
1. **Isolated Test Configuration Fixture:**
   - In `conftest.py`, override `settings.SUPPORTED_SYMBOLS` to `["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]` during test execution so local developer `.env` files do not break assertion counts.
2. **Dynamic Fallback Pricing in Order Executor:**
   - Replace static fallback prices (`1.1000`) with prices derived from the target signal's entry price or recent candle history.
