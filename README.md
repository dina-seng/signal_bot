# Forex Market Analysis & Telegram Signal Bot

A production-quality Forex market analysis and signal generation system based on rule-based technical analysis, market structure (HH/HL/LH/LL, BOS, CHOCH/MSS), liquidity concepts, price-action confirmation, risk management, and economic-news filtering.

> **Scope Note**: This system is for **analysis and signal generation only**. It does not execute real-money trades.

---

## 🏛️ Modular Architecture

```text
Market Data Provider (Yahoo Finance / Twelve Data / Mock)
        │
        ▼
Data Ingestion Service (Cleaning, Sorting, Deduplication, Gap Detection)
        │
        ▼
Database (SQLAlchemy + SQLite / PostgreSQL)
        │
        ▼
Technical Analysis Engine (Milestones 2–4)
        │
        ├── Market Structure (Swings, HH/HL, BOS, CHOCH)
        ├── Liquidity & S/R Zones
        └── Indicators & Price Action
        │
        ▼
News & Economic Calendar Engine (Milestone 5)
        │
        ▼
Signal Engine & Risk Management (Milestone 6)
        │
        ▼
Backtesting & Paper Trading (Milestones 7–8)
        │
        ▼
Telegram Notification Service (Milestone 9)
```

---

## 🚀 Milestone 1 Features

- **Database Layer**: SQLAlchemy ORM with `Candle` entity, composite indexes, and strict unique constraints on `(symbol, timeframe, timestamp)`.
- **Flexible Market Data Providers**:
  - `YahooFinanceProvider`: Zero-friction, free real-time and historical OHLCV data for `EUR/USD`, `GBP/USD`, `USD/JPY`, `XAU/USD` across `15m`, `1h`, `4h`.
  - `TwelveDataProvider`: REST API provider with configurable API keys.
  - `MockMarketDataProvider`: Deterministic synthetic candle generator for automated testing.
- **Robust Ingestion Pipeline**:
  - Validates OHLC pricing invariants ($High \ge Open, Close, Low$ and $Low \le Open, Close, High$).
  - Chronologically sorts out-of-order data streams.
  - Removes intra-batch and database duplicate records.
  - Detects missing candle intervals/gaps while accounting for weekend Forex market hours.
- **REST API**:
  - `GET /api/v1/health`: System health and candle counts per symbol/timeframe.
  - `GET /api/v1/market/symbols`: Supported currency pairs and metadata.
  - `GET /api/v1/market/{symbol}/candles`: Query historical OHLCV candles with limit and date filters.
  - `POST /api/v1/market/sync`: Trigger manual or scheduled ingestion.

---

## ⚡ Milestone 2 Features: Market Structure & Trend Classification

- **N-Bar Fractal Swing Detector (`SwingDetector`)**:
  - Pure deterministic algorithm with configurable lookback ($N_L$ left, $N_R$ right bars).
  - Confirms Swing Highs ($High_i \ge High_{i-k}, High_i > High_{i+k}$) and Swing Lows ($Low_i \le Low_{i-k}, Low_i < Low_{i+k}$).
- **Market Structure Classification (`StructureEngine`)**:
  - Classifies swing points into **Higher High (HH)**, **Higher Low (HL)**, **Lower High (LH)**, **Lower Low (LL)**, **Equal High (EH / Double Top)**, and **Equal Low (EL / Double Bottom)** with percentage tolerance threshold.
  - Dynamically extracts key structural resistance and key support levels.
- **Directional Trend & Strength Classification**:
  - Classifies trend into `BULLISH` (HH + HL progression), `BEARISH` (LH + LL progression), and `RANGING` (conflicting swings / double tops / consolidation).
  - Calculates normalized trend strength score from 0.0 to 1.0 based on structural consistency and streak momentum.
- **Multi-Timeframe (MTF) Alignment Engine (`MultiTimeframeStructureEngine`)**:
  - Evaluates confluence across higher timeframe (4h HTF), intermediate timeframe (1h ITF), and lower execution timeframe (15m LTF).
  - Classifies overall alignment: `BULLISH_ALIGNED`, `BEARISH_ALIGNED`, `HTF_BULLISH_PULLBACK`, `HTF_BEARISH_PULLBACK`, `MIXED`.
  - Computes composite MTF alignment score and generates human-readable executive summaries.
- **Structure Persistence**:
  - Persists detected structure events to `StructureEvent` table with idempotent deduplication.
- **REST API**:
  - `GET /api/v1/structure/{symbol}`: Full market structure, swings, labels, trend, and S/R levels.
  - `GET /api/v1/structure/{symbol}/multi-timeframe`: Multi-timeframe trend alignment and summary.
  - `POST /api/v1/structure/analyze`: Stateless on-demand structure analysis for any custom candle array.

---

## 🎯 Milestone 3 Features: SMC Breakouts, Liquidity Sweeps & S/R Zones

- **Break of Structure (BOS) Engine (`BOSCHOCHDetector`)**:
  - **Bullish BOS**: Candle body closes strictly above prior Higher High in an established uptrend (Trend Continuation).
  - **Bearish BOS**: Candle body closes strictly below prior Lower Low in an established downtrend (Trend Continuation).
  - Computes breakout candle displacement momentum score ($0.0 \to 1.0$).
- **Change of Character / Market Structure Shift (CHOCH / MSS)**:
  - **Bullish CHOCH**: Candle body closes strictly above the most recent Lower High (LH) in a downtrend/range (Reversal to Bullish).
  - **Bearish CHOCH**: Candle body closes strictly below the most recent Higher Low (HL) in an uptrend/range (Reversal to Bearish).
- **Institutional Liquidity Sweeps / Stop Hunts (`LiquiditySweepDetector`)**:
  - **Buy-Side Liquidity Sweep (BSL)**: Price wicks above resistance/high triggering stop losses, then rejects and closes back inside the range.
  - **Sell-Side Liquidity Sweep (SSL)**: Price wicks below support/low triggering stop losses, then rejects and closes back inside the range.
  - Calculates rejection wick ratio ($\ge 0.25$) and pip penetration distance.
- **Dynamic S/R Zones & Resting Liquidity Pools (`SupportResistanceDetector`)**:
  - Dynamic clustering of swing highs into **Resistance Zones** and **Equal Highs (`EQUAL_HIGHS`)** pools.
  - Dynamic clustering of swing lows into **Support Zones** and **Equal Lows (`EQUAL_LOWS`)** pools.
  - Zone strength scoring based on touch counts, reaction quality, and fresh vs breached status.
- **Institutional Market State Classification**:
  - Classifies market into `BULLISH_TREND_CONTINUATION`, `BEARISH_TREND_CONTINUATION`, `BULLISH_REVERSAL_CONFIRMED`, `BEARISH_REVERSAL_CONFIRMED`, `BUY_SIDE_LIQUIDITY_SWEPT`, `SELL_SIDE_LIQUIDITY_SWEPT`, `RANGING_CONSOLIDATION`.
- **Database Persistence**:
  - Persists breakout events (`BULLISH_BOS`, `BEARISH_BOS`, `BULLISH_CHOCH`, `BEARISH_CHOCH`) to `StructureEvent` table.
  - Persists liquidity events (`BUY_SIDE_SWEEP`, `SELL_SIDE_SWEEP`, `EQUAL_HIGHS`, `EQUAL_LOWS`) to `LiquidityEvent` table.
- **REST API**:
  - `GET /api/v1/liquidity/{symbol}/analysis`: Comprehensive SMC analysis (BOS, CHOCH, sweeps, S/R zones, pools, market state).
  - `GET /api/v1/liquidity/{symbol}/sweeps`: Query active/historical Buy-Side and Sell-Side sweeps.
  - `GET /api/v1/liquidity/{symbol}/zones`: Query dynamic S/R zones and liquidity pools.
  - `POST /api/v1/liquidity/analyze`: Stateless on-demand SMC analysis on arbitrary candle sequences.

---

## 📊 Milestone 4 Features: Technical Indicators & Price Action Patterns

- **Exponential Moving Averages (`EMACalculator`)**:
  - Fast recursive calculation for **EMA 20**, **EMA 50**, and **EMA 200**.
  - Identifies `BULLISH_STACK` ($Price > 20 > 50 > 200$), `BEARISH_STACK` ($Price < 20 < 50 < 200$), Golden Crosses, and Death Crosses.
- **Relative Strength Index & Divergences (`RSICalculator`)**:
  - Wilder's Smoothed **RSI (14-period)** with Overbought ($\ge 70$) and Oversold ($\le 30$) zones.
  - **Regular Bullish Divergence** (Price Lower Low, RSI Higher Low $\to$ Reversal Long).
  - **Regular Bearish Divergence** (Price Higher High, RSI Lower High $\to$ Reversal Short).
  - **Hidden Bullish Divergence** (Price Higher Low, RSI Lower Low $\to$ Trend Continuation Long).
  - **Hidden Bearish Divergence** (Price Lower High, RSI Higher High $\to$ Trend Continuation Short).
- **Average True Range & Dynamic Risk Management (`ATRCalculator`)**:
  - Wilder's Smoothed **ATR (14-period)** with automatic currency pip conversion.
  - Volatility state analysis (`HIGH`, `NORMAL`, `LOW`).
  - Dynamic suggested Stop Loss distance ($1.5 \times ATR$) and Take Profit distance ($3.0 \times ATR$).
- **Price Action Patterns & Fair Value Gaps (`PriceActionDetector`)**:
  - **Pin Bars (Hammers & Shooting Stars)** with $>55\%$ rejection wick ratio.
  - **Bullish & Bearish Engulfing** bars.
  - **Inside Bars** (consolidation inside mother bar).
  - **Fair Value Gaps (FVG / Imbalances)** with subsequent mitigation/retest tracking.
- **Multi-Factor Confluence Scoring (`IndicatorService`)**:
  - Computes composite technical confluence score from $-100$ (Strong Bearish) to $+100$ (Strong Bullish).
- **REST API**:
  - `GET /api/v1/indicators/{symbol}`: Full technical indicator and confluence analysis report.
  - `GET /api/v1/indicators/{symbol}/fvg`: Active and historical Fair Value Gaps and mitigation status.
  - `GET /api/v1/indicators/{symbol}/divergences`: Detected RSI divergences.
  - `POST /api/v1/indicators/analyze`: Stateless on-demand indicator calculation for custom candle series.

## 📰 Milestone 5 Features: Economic News Calendar & Blackout Filter

- **Economic Calendar Providers (`BaseNewsProvider`, `ForexFactoryProvider`, `MockNewsProvider`)**:
  - Fetches and parses real-time macroeconomic events with automatic fallback.
  - Classifies event impact into `HIGH`, `MEDIUM`, and `LOW` across `USD`, `EUR`, `GBP`, `JPY`.
  - Captures historical, forecast, and actual release figures.
- **News Ingestion & Deduplication (`NewsIngestionService`)**:
  - Deduplicates events against the `NewsEvent` database table using currency, event name, and UTC scheduled timestamp.
- **News Blackout Window Filter (`NewsFilterEngine`)**:
  - Automatically blocks signal generation and trading during high-impact volatility windows.
  - Configurable safety buffers (default: 30 minutes before release, 15 minutes after release).
  - Cross-currency mapping: checks both base and quote currencies (e.g. `EUR` and `USD` for `EUR/USD`), and links Gold (`XAU/USD`) to `USD` macroeconomic events (NFP, FOMC, CPI, etc.).
  - Calculates time to next major event and time elapsed since previous event.
- **REST API**:
  - `GET /api/v1/news/calendar`: Query scheduled economic calendar events with currency, impact, and date filters.
  - `GET /api/v1/news/check/{symbol}`: Check live news blackout status and trading permission for a symbol.
  - `POST /api/v1/news/sync`: Trigger manual or background synchronization of the economic calendar.

## 🎯 Milestone 6 Features: Deterministic Signal Scoring & Risk Management

- **Multi-Pillar Deterministic Scoring Engine (`SignalScoringEngine`)**:
  - **Market Structure & MTF Alignment (Max 30 pts)**: Base trend direction (+10), multi-timeframe 4h/1h/15m alignment (+10), confirmed BOS/CHOCH breakout (+10).
  - **Institutional Liquidity & S/R Zones (Max 25 pts)**: Institutional BSL/SSL stop hunt sweep (+15), fresh S/R zone reaction (+10).
  - **Technical Indicators & Confluence (Max 25 pts)**: EMA 20/50/200 Stack (+10), RSI momentum zone or regular/hidden divergence (+10), active Fair Value Gap retest (+5).
  - **Price Action Confirmation (Max 20 pts)**: High-conviction rejection Pin Bar (Hammer/Shooting Star) or Engulfing candle trigger (+20).
  - **Minimum Score Threshold**: Configurable gate (default: $\ge 75.0$) required to issue actionable `BUY` or `SELL` signals; otherwise classified as `WAIT`.
- **Advanced Risk Management & Position Sizing (`RiskManager`)**:
  - **Protective Stop Loss (SL)**: Anchored beyond structural swing points / liquidity sweeps plus an ATR volatility buffer.
  - **Take Profit Targets**: Primary target **TP1** ($\ge 2.0 \times R:R$) and runner target **TP2** ($3.0 \times R:R$).
  - **Dynamic Position Sizing**: Exact calculation of standard lots based on account balance, $0.5\%$ risk per trade, pip distance, and symbol pip value.
- **Signal Deduplication & Fingerprinting (`SignalGenerator`)**:
  - Computes deterministic SHA-256 fingerprint hash based on symbol, timeframe, direction, entry, stop loss, and timestamp.
  - Persists qualified trade signals into the `Signal` table.
- **Multi-Symbol Market Scanner**:
  - Simultaneously analyzes `EUR/USD`, `GBP/USD`, `USD/JPY`, `XAU/USD` across multiple timeframes and filters against the live News Blackout engine.
- **REST API**:
  - `GET /api/v1/signals`: Query historical and active signals with direction, symbol, and status filters.
  - `GET /api/v1/signals/scan`: Trigger full multi-market scanner with configurable account balance and risk percentage.
  - `POST /api/v1/signals/evaluate`: Stateless on-demand signal scoring and risk calculation for custom candle series.

---

## 📈 Milestone 7 Features: Backtesting Engine & Performance Metrics

- **Candle-by-Candle Event-Driven Simulation (`BacktestEngine`)**:
  - Sequential walk-forward historical simulation with warmup buffer (no lookahead bias).
  - Realistic order execution with spread & slippage friction on entry and exit.
  - Intra-bar high/low execution checks for Stop Loss and Take Profits.
  - Partial Take Profit at **TP1** (e.g. 50% lot size closed) and automatic move of Stop Loss to **Break-Even**.
  - Secondary runner exit at **TP2** or trailing / end-of-data liquidation.
  - Account equity and balance time-series curve tracking per candle.
- **Institutional Financial & Risk Performance Metrics (`PerformanceMetricsCalculator`)**:
  - **Trade Statistics**: Total Trades, Winning/Losing/Break-Even Trades, Win Rate %, Loss Rate %.
  - **Profitability Metrics**: Initial/Final Balance, Gross Profit/Loss, Net Total PnL ($ and %), Profit Factor ($\frac{\text{Gross Profit}}{\text{Gross Loss}}$), Average Win/Loss, Payoff Ratio.
  - **Expectancy**: Expected USD Return per trade ($) and Expected R-Multiple ($R$).
  - **Risk & Drawdown**: Peak Equity, Max Drawdown ($ and %), Max Drawdown Duration (bars), Sharpe Ratio, Sortino Ratio, Calmar Ratio.
  - **Directional Performance**: Long (BUY) vs Short (SELL) win rates, trade counts, and PnL.
- **Parameter Grid Search & Strategy Optimization (`ParameterOptimizer`)**:
  - Multi-parameter grid search across Setup Score Thresholds ($60, 70, 75, 80$), Risk Percentages ($0.5\%, 1.0\%$), and Risk:Reward Multipliers ($1.5, 2.0, 2.5, 3.0$).
  - Automatically identifies optimal parameters ranked by Sharpe Ratio, Net PnL, and Profit Factor.
- **Database Persistence & Runs History (`BacktestService`)**:
  - Saves full backtest runs and individual simulated trades into `BacktestRun` and `BacktestTrade` tables.
- **REST API**:
  - `POST /api/v1/backtest/run`: Run historical backtest from database candles and persist run results.
  - `POST /api/v1/backtest/execute`: Stateless in-memory backtest on custom candle arrays.
  - `POST /api/v1/backtest/optimize`: Parameter grid sweep over candidate parameter configurations.
  - `GET /api/v1/backtest/runs`: Query historical backtest runs with symbol and timeframe filters.
  - `GET /api/v1/backtest/runs/{run_id}`: Retrieve detailed metrics report, equity curve, and trade logs for a run.
  - `DELETE /api/v1/backtest/runs/{run_id}`: Delete a backtest run and its trade logs.

---

## 💼 Milestone 8 Features: Paper Trading Virtual Account Mode

- **Virtual Account & Margin Engine (`VirtualAccountManager`)**:
  - Virtual account state simulating real balance, floating equity, margin used, free margin, and margin level %.
  - Multi-account support with initial deposits, balance resets, custom leverage ($1:100$), and currency denomination ($USD$).
  - Precise Forex and Gold margin calculations accounting for base currency conventions.
- **Order & Position Management (`PaperOrderExecutor`, `PaperPositionManager`)**:
  - **Order Types**: `MARKET` (instant fill with spread & slippage), `LIMIT` (buy limit below / sell limit above), `STOP` (breakout stop orders).
  - **Signal-to-Trade Auto Execution**: Instantly converts qualified strategy signals into active virtual positions with dynamic position sizing and SL/TP.
  - **Intra-Day Position Management**:
    - Partial Take Profit at **TP1** (50% lots closed, locking in profit) and automatic Stop Loss adjustment to **Break-Even**.
    - Full runner exit at **TP2**.
    - Manual position modifications, SL/TP adjustments, and immediate market closures.
- **Live Price Synchronization & Auto SL/TP Monitoring (`sync_prices`)**:
  - Ticks all active and pending orders against live market prices.
  - Automatically executes SL hits, TP1 partial closes, TP2 full exits, and pending Limit/Stop order fills.
  - Margin Call & Stop Out emergency protection if margin level falls below $50\%$.
- **Database Persistence & Transaction Ledger**:
  - Persists accounts, paper positions, and transaction audit trails into `VirtualAccount`, `PaperTrade`, and `AccountTransaction` tables.
- **REST API**:
  - `GET /api/v1/paper/account`: Retrieve virtual account state, balance, equity, and margin levels.
  - `POST /api/v1/paper/account/create`: Create a new named virtual trading account.
  - `POST /api/v1/paper/account/deposit`: Deposit or adjust virtual funds.
  - `POST /api/v1/paper/account/reset`: Reset virtual balance and close all open positions.
  - `POST /api/v1/paper/orders`: Place a manual / algorithmic paper order.
  - `POST /api/v1/paper/orders/from-signal`: Auto-execute a trade directly from a strategy signal.
  - `GET /api/v1/paper/positions`: Query open and pending positions.
  - `GET /api/v1/paper/trades`: Query historical closed paper trades.
  - `GET /api/v1/paper/trades/{trade_id}`: Retrieve specific paper trade details.
  - `PUT /api/v1/paper/positions/{trade_id}/modify`: Modify SL and TP targets.
  - `POST /api/v1/paper/positions/{trade_id}/close`: Close position (full or partial).
  - `POST /api/v1/paper/monitor/sync`: Trigger price synchronization and SL/TP auto-monitoring.
  - `GET /api/v1/paper/performance`: Virtual portfolio performance statistics and win rate.

---

## 🤖 Milestone 9 Features: Telegram Bot Service & Automated Scanner

- **Telegram Message Formatter (`TelegramMessageFormatter`)**:
  - **Trade Signal Alerts**: Rich Markdown & emoji alerts featuring Direction, Quality Score ($/100$), Entry Price, SL, TP1, TP2, R:R ratio, Suggested Lot Sizing (0.5% risk rule), Multi-pillar confluence reasons, and News Blackout status badge.
  - **Trade Management Notifications**:
    - `🎯 TP1 Reached`: 50% partial exit notice with locked-in profit and Break-Even Stop Loss adjustment confirmation.
    - `🏆 TP2 Runner Hit`: Final target exit notice with total realized PnL and R-multiple.
    - `🛑 Stop Loss Hit` / `⚡ Break-Even Closed`.
  - **Market Scanner Digests**: Summary status across all monitored currency pairs (`EUR/USD`, `GBP/USD`, `USD/JPY`, `XAU/USD`).
  - **Economic News Flash Alerts & Portfolio Daily Reports**.
- **Interactive Bot Commands (`TelegramCommandHandler`)**:
  - `/start` or `/help`: Display interactive command directory and bot guides.
  - `/scan`: On-demand multi-market scan across all currency pairs.
  - `/signal <pair>`: In-depth setup evaluation and multi-pillar breakdown (e.g. `/signal EUR/USD` or `/signal XAU/USD`).
  - `/news`: Today's scheduled economic events and news blackout clearance.
  - `/account` or `/paper`: Virtual trading balance, floating equity, and margin levels.
  - `/positions`: List active and pending paper positions.
  - `/performance`: Virtual portfolio return %, win rate %, and profit factor.
  - `/backtest <pair>`: Run historical strategy backtest on demand.
- **Telegram Client & Webhooks (`TelegramClient`, `MockTelegramClient`)**:
  - Asynchronous dispatch via `httpx` with graceful Mock mode fallback for local execution.
  - Interactive Webhook listener (`POST /api/v1/telegram/webhook`) for processing real-time user inputs.
- **Automated Background Market Scanner (`AutomatedMarketScanner`)**:
  - Periodic scanning loop syncing market candles and economic calendar.
  - Evaluates multi-pillar signals with fingerprint-based deduplication (preventing duplicate alerts).
  - Automatically converts qualified signals into paper trading positions and monitors active trades for TP1/TP2/SL triggers.
- **REST API**:
  - `POST /api/v1/telegram/broadcast`: Send custom formatted message to Telegram channel.
  - `POST /api/v1/telegram/command`: Process an interactive bot command.
  - `POST /api/v1/telegram/webhook`: Webhook endpoint for Telegram server events.
  - `GET /api/v1/telegram/status`: Connectivity and operational mode (LIVE or MOCK).
  - `POST /api/v1/telegram/scanner/trigger`: Manually trigger market scanner cycle.
  - `GET /api/v1/telegram/scanner/status`: Operational status and scanning interval.

---

## 🛠️ Getting Started

### 1. Installation

```bash
pip install -r requirements.txt
```

### 2. Configuration

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

### 3. Run Automated Tests

```bash
python -m pytest tests/ -v
```

### 4. Verify Market Data Pipeline (Milestone 1)

```bash
python scripts/verify_pipeline.py
```

### 5. Verify Market Structure & Trend Engine (Milestone 2)

```bash
python scripts/verify_structure.py
```

### 6. Verify SMC Breakouts & Liquidity Engine (Milestone 3)

```bash
python scripts/verify_liquidity.py
```

### 7. Verify Indicators & Price Action Engine (Milestone 4)

```bash
python scripts/verify_indicators.py
```

### 8. Verify Economic News Calendar & Blackout Filter (Milestone 5)

```bash
python scripts/verify_news.py
```

### 9. Verify Deterministic Signal Scoring & Risk Engine (Milestone 6)

```bash
python scripts/verify_signals.py
```

### 10. Verify Backtesting Engine & Performance Metrics (Milestone 7)

```bash
python scripts/verify_backtest.py
```

### 11. Verify Paper Trading Virtual Account Mode (Milestone 8)

```bash
python scripts/verify_paper_trading.py
```

### 12. Verify Telegram Bot Service & Automated Scanner (Milestone 9)

```bash
python scripts/verify_telegram.py
```

### 13. Start the REST API

```bash
python app/main.py
```
Open [http://localhost:8000/docs](http://localhost:8000/docs) in your browser for Swagger documentation.

### 14. Telegram Bot & Production Deployment Guide

For step-by-step instructions on setting up your Telegram Bot, obtaining tokens and Chat IDs, registering commands, setting up webhooks, and hosting on a VPS or Docker:
👉 **[Read the Complete Deployment Guide (DEPLOYMENT_GUIDE.md)](DEPLOYMENT_GUIDE.md)**

---

## 📅 Development Roadmap

- [x] **Milestone 1**: Market Data Pipeline, Database Models, Ingestion Engine & Verification
- [x] **Milestone 2**: Swing Detection, HH/HL/LH/LL & Trend Classification Engine
- [x] **Milestone 3**: BOS, CHOCH/MSS, Liquidity Sweeps & Support/Resistance Detection
- [x] **Milestone 4**: Indicators (EMA 20/50/200, RSI 14, ATR 14) & Price Action Patterns
- [x] **Milestone 5**: Economic News Calendar & Blackout Filter
- [x] **Milestone 6**: Deterministic Signal Scoring Engine (0-100) & Risk Management
- [x] **Milestone 7**: Backtesting Engine & Performance Metrics
- [x] **Milestone 8**: Paper Trading Virtual Account Mode
- [x] **Milestone 9**: Telegram Bot Service, Interactive Commands & Automated Scanner





