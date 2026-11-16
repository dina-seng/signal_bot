# RAYU.md

This file provides guidance to RAYU when working with code in this repository.

## What this repo is

QuantTrade monorepo: a FastAPI + SQLAlchemy trading-signal backend (`server/`), a React/Vite/TypeScript dashboard (`client/`), and a root `package.json` that orchestrates both. Active work is on branch `feat/xauusd-liquidity-sweep`: a single-asset (XAU/USD), 15m/1h/4h liquidity-sweep SMC system. `REPORT.md` is the authoritative, phase-by-phase engineering record (Phases 0–3) — read the relevant phase before touching sweep, data-layer, or backtest code.

## Commands

Python 3.14 venv lives at `.venv/` (repo root). All backend/test commands run from `server/` with the venv active (on Windows: `source .venv/Scripts/activate` from repo root).

- Run everything (backend uvicorn :8000 + frontend vite): `npm run dev` (repo root)
- Backend only: `cd server && uvicorn app.main:app --reload --port 8000`
- Frontend only: `cd client && npm run dev` (build: `npm run build`)
- Tests (hermetic, in-memory SQLite): `cd server && python -m pytest tests/`
  - Single file / test: `python -m pytest tests/test_sweep_engine.py` / `... -k test_name`
  - Full baseline is ~240+ tests and takes ~3 min; slow controls (`test_random_walk_control_slow.py`) are separate.
- Backtest harness: `cd server && python -m app.scripts.run_sweep_backtest [--db-path backtest.db]` (loads 15m candles, runs grid, writes reports to `reports/`)
- History backfill (hits the live Twelve Data API, budgeted): `cd server && python -m app.scripts.backfill_twelvedata --start YYYY-MM-DD --end YYYY-MM-DD --db-path backtest.db`
- Migrations: `cd server && alembic upgrade head`; new revision: `alembic revision --autogenerate -m "..."`

## Databases

- Dev/app DB: `server/trade.db` (via `DATABASE_URL=sqlite:///./trade.db`, see `server/.env.example`; `.env` is gitignored, never commit credentials)
- Backtest DB: `backtest.db` at repo root (~100k clean 15m XAU/USD bars, source-tagged)
- Production is Neon Postgres (`DATABASE_URL` in env) — see safety rules below.
- The root `app/` directory contains thin wrapper shims that re-exec `server/app` scripts; `server/app/` is the real code.

## Architecture (big picture)

Data flow: Twelve Data (15m only) → SQLite `candles` → market-calendar filter → pure analysis engines → signals/backtests → FastAPI `/api/v1/*` → React dashboard.

- `server/app/services/market_data/` — Phase 1 data layer.
  - `twelvedata_provider.py` is the ONLY permitted provider (factory raises on `mock`/`yahoo`; `MockMarketDataProvider` exists for DI in tests). Token bucket 7 req/min + 780 calls/day hard budget persisted in the `api_usage` table; 429 → 60s backoff, 3 retries, then `TwelveDataRateLimitError` marks data STALE.
  - `resample.py` — only 15m is ever fetched; 30m/1h/4h are rebuilt by the pure `resample_ohlc()` from UTC-anchored buckets (incomplete buckets omitted); daily anchored 17:00 America/New_York DST-aware.
  - `calendar.py` — Twelve Data fills market closures with flat synthetic bars. `is_market_open(ts)` / `filter_open_market_candles()` drop them at load time (Fri 17:00 NY close → Sun 18:00 NY open, daily 17:00–18:00 NY break) without mutating DB rows. All analysis inputs must be filtered first.
  - `freshness.py` — closed-market periods are `MARKET_CLOSED`, never `STALE`.
- `server/app/services/sweep/` — Phase 2 pure liquidity-sweep engine (`atr.py`, `pivots.py` fractal N-left/N-right confirmed at k+N, `pools.py` EQH/EQL + PDH/PDL + session pools, `detector.py` sweep→MSS→FVG/OB zone→SL/TP with RR≥1.5 gate, `state_machine.py` POTENTIAL→WAITING→CONFIRMED/INVALIDATED/NO_SETUP, `config.py` `SweepConfig`). Top-level entry: `evaluate_sweep_market(candles_15m, candles_1h, candles_4h, as_of, config)`.
- `server/app/services/sweep/backtest/` — Phase 3 harness: walk-forward simulation reusing the production engine, trade-through limit fills, same-bar SL-first, $0.40 roundtrip friction, bootstrap 95% CI (no edge verdict unless n≥100 and CI lower >0; `n<30` → "n/a"), random-entry baseline, purged/embargoed 60/20/20 splits, pre-registered 18-combination tuning grid (`tuning.py`).
- `server/app/api/v1/` — REST routes mounted on `router.py`; `server/app/models/` — SQLAlchemy tables; `server/app/services/` also holds the legacy SMC stack (structure, indicators, signals, liquidity, news, paper trading, telegram scanner/scheduler).

## Hard rules (violating these breaks the project)

1. **Zero lookahead.** Every analysis function takes an explicit `as_of`; never call `datetime.now()` inside sweep/backtest computation; pivots only known at k+N. Prefix-invariance tests (`test_sweep_engine.py`, `test_window_invariance.py`, `test_sweep_backtest.py`) must keep passing — if you change engine code, verify bit-identical outputs for truncated vs. garbage-padded futures.
2. **Tests are hermetic.** `server/tests/conftest.py` hard-fails if `DATABASE_URL` points at Postgres/Neon and force-pins in-memory SQLite, scanner off, symbols to XAU/USD. Never weaken these guards, never let a test touch Neon or the live API.
3. **API budget.** Twelve Data calls are rate-limited (7/min, 780/day). Never write code or run scripts that page the API in loops without the budgeted provider/backfill path.
4. **Data hygiene.** 15m candles only are fetched; derive HTFs by resampling. Filter closed-market placeholder bars before any analysis; drop forming bars by timestamp rule (`ts + delta <= now`), never by index.
5. **Migrations.** Schema changes go through Alembic (`server/alembic/`); no ad-hoc `DROP TABLE` / manual DDL against DBs.
