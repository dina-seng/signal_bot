# QuantView — SMC Signal Bot

Self-hosted, single-asset (**XAU/USD**) market-analysis system. It ingests 15m candles, derives 1h/4h locally, scores Smart Money Concepts (SMC) setups, and publishes qualified signals to a React dashboard, a FastAPI API, an optional Telegram bot, and a virtual paper-trading account.

> **Research system, not financial advice.** No broker integration and no live order routing.

## Scope

- **One asset, one strategy.** XAU/USD only; SMC-only since PR #16 (CRT/Range removed).
- **Qualification floor 60/100.** PA and confluence floors are hard filters.
- **Strict risk (execution).** The Signal Engine finds the entry only; the Risk Engine places the 15m structural SL and a single 1:3 TP anchored to that entry, at a fixed 0.01 lot. No ATR or candle-extreme fallback stops; when no 15m swing exists a fixed 10-price-unit gap is used. Wide structural stops are **never** a rejection reason.
- **Fully automatic paper trading.** The scheduler creates paper trades directly in the database for qualified 15m signals (15m SL ≤ `AUTO_EXEC_MAX_SL_POINTS`), capped globally by `MAX_OPEN_POSITIONS` and idempotent per signal. The dashboard is read-only; Telegram sends an immediate `AUTO-EXECUTED` alert.
- **Frozen execution contract.** `optionB-v1` simulator rules (fills, gaps, voids, R denominator, costs) are unchanged by strategy work.
- **Truthful state.** Dashboard reads one atomic `/paper/summary` snapshot so equity, P&L and the position ledger always agree.

## Quick start

```bash
pip install -r server/requirements.txt          # Python 3.11+
cd client && npm install && cd ..               # Node 20.19+
npm run dev                                     # API :8000 · dashboard :3000
```

Backend settings live in `server/.env` (start from `server/.env.example`); a Twelve Data key is required for live data. API docs: `http://localhost:8000/docs`.

Verify:

```bash
cd server && python -m pytest -q                # 333 passed
cd ../client && npm run build                   # type-check + production build
```

## Layout

```
server/app/services/strategies/   SMC strategy (scoring, floors)
server/app/services/signals/       evaluators, signal orchestration
server/app/services/paper_trading/ orders, risk-budget rejection, accounts
server/app/services/telegram/      scanner, alerts, rejection notices
server/scripts/                    frozen replay / backtest harnesses
client/src/                        React dashboard
reports/smc_baseline_v2/           canonical baseline v2 + delta report
```

## Baseline

`reports/smc_baseline_v2/` is the reference run: 735 accepted opportunities, 258 filled trades, +65.71R, profit factor 1.52. Control tests still fail, so results are **descriptive only** — see `delta_report.md` and `manifest.yaml` there. Baseline v1 remains untouched.

## Go deeper

[Architecture](docs/ARCHITECTURE.md) · [Services](docs/SERVICES.md) · [Testing](docs/TESTING_AND_VALIDATION.md) · [Findings](docs/GAPS_AND_FINDINGS.md) · [Execution contract](execution_contract_final.md) · [Baseline write-up](establish.md) · [AI workflow rules](RAYU.md)

Research and educational use only. No outcome is guaranteed; independent validation and risk controls are required before any live decision.
