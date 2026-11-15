@echo off
set PYTHONPATH=D:\trade\server
D:\trade\.venv\Scripts\python.exe -m app.scripts.backfill_twelvedata --start 2023-03-01 --end 2026-05-20 --db-path D:\trade\backtest.db > D:\trade\backfill_history.log 2>&1
