# 🚀 QuantTrade Monorepo

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18+-cyan.svg)](https://reactjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-blue.svg)](https://www.typescriptlang.org/)
[![Tailwind](https://img.shields.io/badge/Tailwind-CSS-38bdf8.svg)](https://tailwindcss.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Institutional-grade algorithmic trading system.** A production-ready, full-stack platform combining Smart Money Concepts (SMC) market analysis, multi-timeframe confluence scoring, paper trading simulation, and a real-time "Bloomberg Terminal" style React dashboard.

---

## ✨ Why This is Cool

- 🧠 **Smart Money Concepts (SMC) Engine:** Automatically detects Fractal Swings, Break of Structure (BOS), Change of Character (CHOCH), and Buy/Sell-side Liquidity (BSL/SSL) sweeps.
- 📊 **QuantView Dashboard:** A high-performance, dark-mode React UI with 10-second real-time polling, interactive charts, active position tracking, and an economic calendar risk monitor.
- 🤖 **Automated Telegram Bot:** Background scanner that evaluates the market and pushes rich, Markdown-formatted trade signals directly to your phone.
- 🛡️ **News Blackout Protection:** Automatically halts signal generation during high-impact macroeconomic events (NFP, CPI, FOMC).
- 📈 **Built-in Paper Trading:** Virtual portfolio management with simulated slippage, dynamic ATR-based Stop Loss/Take Profit, and detailed performance metrics (Sharpe, Max Drawdown, Win Rate).

---

## 🏛️ System Architecture & Data Flow

```mermaid
flowchart TD
    subgraph Ingestion["1. Ingestion Pipeline"]
        P1["Market Data Providers\n(Yahoo Finance / Twelve Data)"] --> INGEST["Market Data Ingestion"]
        N1["ForexFactory Calendar"] --> NEWS_INGEST["News Ingestion & Scraping"]
        INGEST --> DB[("Database Engine\nSQLAlchemy + SQLite/Postgres")]
        NEWS_INGEST --> DB
    end

    subgraph Analysis["2. Technical & SMC Analysis"]
        DB --> STRUCT["Market Structure Engine\n- Fractal Swings\n- BOS & CHOCH\n- MTF Alignment"]
        DB --> LIQ["Liquidity Engine\n- BSL / SSL Sweeps\n- S/R Zones"]
        DB --> IND["Indicators & Patterns\n- EMA Stack (20, 50, 200)\n- RSI Divergences\n- Fair Value Gaps (FVG)"]
    end

    subgraph Decision["3. Confluence & Signal Generation"]
        STRUCT --> CONF["Confluence Scoring Engine"]
        LIQ --> CONF
        IND --> CONF
        DB --> BLACKOUT["News Blackout Filter"]
        BLACKOUT --> CONF
        CONF --> RISK["Risk Manager\n- Dynamic ATR SL/TP\n- Min 1:2 R:R\n- Confidence Threshold"]
        RISK --> SIGNAL["Actionable Trade Signal"]
    end

    subgraph Execution["4. Execution & Notifications"]
        SIGNAL --> PAPER["Paper Trading Service\n- Virtual Portfolio\n- Slippage & Fills"]
        SIGNAL --> TELEGRAM["Telegram Service\n- Scanner Scheduler\n- Signal Broadcasts"]
    end

    subgraph API["5. Presentation Layer"]
        FASTAPI["FastAPI REST API (app/api/v1)"]
        DB -.-> FASTAPI
        Execution -.-> FASTAPI
        FASTAPI -.-> REACT["QuantView React Dashboard"]
    end
