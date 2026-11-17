# QuantView Gaps vs Project Vision & Prioritized Findings

This document evaluates QuantView against its architectural vision as an institutional SMC/CRT scanner and provides an auditable, evidence-backed list of prioritized findings as of November 17, 2026.

---

## Table of Contents

1. [M. Gaps vs Project Vision (SMC / ICT Concepts Matrix)](#m-gaps-vs-project-vision-smc--ict-concepts-matrix)
2. [Step 3: Prioritized Findings Table](#step-3-prioritized-findings-table)
   - [Critical Findings](#critical-findings)
   - [High Severity Findings](#high-severity-findings)
   - [Medium Severity Findings](#medium-severity-findings)
   - [Low Severity Findings](#low-severity-findings)

---

## M. Gaps vs Project Vision (SMC / ICT Concepts Matrix)

The original vision for ApexAnalyzer / QuantView is an institutional-grade scanner for XAU/USD (Gold) implementing core Smart Money Concepts (SMC), Inner Circle Trader (ICT) principles, and Candle Range Theory (CRT). The matrix below compares this vision against what is implemented in the codebase today.

| SMC / ICT Concept | Implemented Where | Implementation Quality Notes | Missing / Deficiencies |
| :--- | :--- | :--- | :--- |
| **Break of Structure (BOS)** | `services/structure/bos_choch_detector.py:85-110` | **High**. Requires candle body close beyond prior swing high/low in direction of existing trend (`bos_choch_detector.py:92`). Zero lookahead. | None. Fully conforms to SMC specifications. |
| **Change of Character (CHoCH / MSS)** | `services/structure/bos_choch_detector.py:115-140`, `services/strategies/crt/confirmation.py:114` | **Mixed**. `bos_choch_detector.py` is high quality (body close required). However, `confirmation.py:120, 154` allows **wick-only breaks** to qualify as MSS, and fails to check event timestamps relative to sweep breach. | Strict body-close enforcement and timestamp filtering missing in `crt/confirmation.py`. |
| **Liquidity Sweeps** | `services/liquidity/sweep_detector.py:30`, `services/sweep/detector.py:45`, `services/structure/crt_analyzer.py:185` | **High (Duplicated)**. Three parallel implementations exist. `crt_analyzer.py` accurately evaluates manipulation depth ($\ge 0.15\text{ ATR}$ and $5\%\text{--}100\%$ range height). `sweep/detector.py` implements pure fractal sweep with 12-bar MSS limit. | Consolidation: `services/sweep/detector.py` is not wired into production scanner. |
| **Equal Highs / Lows (EQH/EQL)** | `services/liquidity/sr_detector.py:153`, `services/sweep/pools.py:115` | **High**. Detects multiple swing points within tight ATR tolerance ($0.10\text{ ATR}$ in `pools.py`; $0.05\%$ in `sr_detector.py`). Classified as high-value liquidity pools ($+12$ pts). | None. Correctly modeled as liquidity magnets. |
| **Fair Value Gaps (FVG)** | `services/indicators/price_action.py:25-95`, `services/sweep/detector.py:270` | **High**. Three-bar pattern ($[i-2]$ to $[i]$). Correctly measures imbalance gap and tracks mitigation. | Mitigation tracking in `price_action.py` is bounded by candle slice size; old FVGs in small slices may show as unmitigated. |
| **Order Blocks (OB)** | `services/sweep/detector.py:331-365`, `services/strategies/crt/entry.py:90` | **Partial**. `sweep/detector.py` defines OB as the last opposing candle before displacement. In `crt/entry.py`, OB is an entry mode fallback. | Standalone dedicated Order Block detector service (with mitigation state and volume profile) is missing. |
| **Premium / Discount** | `services/structure/structure_engine.py:215`, `services/signals/evaluators.py:95`, `services/strategies/crt/entry.py:75` | **High**. Calculates 50% equilibrium between range high and range low. Scores BUY in discount ($< 50\%$) and SELL in premium ($> 50\%$). | None. Accurately implemented across structure and CRT entry. |
| **Previous-Day High/Low (PDH/PDL)**| `services/strategies/crt/daily_bias.py:15-100`, `services/sweep/pools.py:208` | **High**. Correctly anchored to 17:00 America/New_York daily close (metals market standard). Sweeps of PDH/PDL receive highest liquidity score ($+18$ pts). | None. Fully DST-aware. |
| **Session Highs / Lows** | `services/strategies/crt/daily_bias.py:105-150`, `services/sweep/pools.py:160-205` | **High**. Correctly separates Asian session (18:00–00:00 NY) and London session (03:00–07:00 NY). Sweeps receive $+14$ pts. | In `walk_forward_harness.py:28-36`, session tagging uses static UTC hours, ignoring DST. |
| **Multi-Timeframe (MTF) Context**| `services/structure/multi_timeframe.py:30`, `services/signals/confluence_engine.py:625` | **High**. Ingests 15m raw, resamples to 1h and 4h. Requires 1h/4h trend alignment before confirming CRT trade. | None. Robust resampling and trend filtering. |
| **Setup States & Lifecycle** | `services/strategies/crt/lifecycle.py:27-188`, `services/sweep/state_machine.py:14-97` | **High**. 10 lifecycle states (`POTENTIAL` $\to$ `CONFIRMED` $\to$ `ENTRY_FILLED` $\to$ `TP1_HIT` $\to$ `TP2_HIT` / `STOPPED` / `MISSED` / `EXPIRED`). Deduplicated in DB. | Bug in `entry.py:180` prematurely flags `MISSED` after fill has already occurred. |
| **Explainability & Auditing** | `services/strategies/crt_strategy.py:1085-1260`, `services/telegram/message_formatter.py:35` | **High**. Complete point-by-point audit trail emitted in metadata (`score_audit` list with rule, points, max points, reason). Formatted into clean HTML for Telegram. | None. Fully transparent scoring. |

---

## Step 3: Prioritized Findings Table

The findings below represent defects, discrepancies between documentation/comments and code, dead code, and operational gaps identified during this audit.

### Master Findings Table

| ID | Severity | Area | Evidence (File:Line) | Why It Matters | Suggested Fix |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **F-01** | **Critical** | CRT Confirmation | `services/strategies/crt/confirmation.py:158-179` | `has_displacement` is computed but omitted from return guard clause; doji or zero-displacement candles qualify as confirmed setups. | Add `if not has_displacement: return LTFConfirmationResult(is_confirmed=False, state="WAITING_FOR_CONFIRMATION", ...)` before MSS check. |
| **F-02** | **Critical** | CRT Analyzer / Strategy | `services/strategies/crt_strategy.py:734` & `schemas/structure.py:68` | `manipulation_candle_index` is omitted from `CRTAnalysis` schema and defaults to `0`, causing pre-sweep bars to be processed as post-sweep candles. | Add `manipulation_candle_index: int` to `CRTAnalysis` and populate the actual bar index in `CRTAnalyzer.analyze()`. |
| **F-03** | **High** | CRT Confirmation | `services/strategies/crt/confirmation.py:114-123` | `structure.recent_events` checks only `event_type` without filtering `event.timestamp > breach_ts`, allowing a pre-sweep CHoCH to qualify an unconfirmed sweep. | Add check `if ev_ts is not None and breach_ts is not None and ev_ts <= breach_ts: continue` inside event loop. |
| **F-04** | **High** | CRT Confirmation | `services/strategies/crt/confirmation.py:120, 154` | Condition `_get_val(c, "high") > recent_swing_high` accepts high wicks as MSS, violating SMC rules requiring candle body close beyond structure. | Require candle body close: `if _get_val(c, "close") > recent_swing_high:`. |
| **F-05** | **High** | CRT Risk & Execution | `services/strategies/crt_strategy.py:942` & `signals/confluence_engine.py:369` | `calculate_crt_targets` receives `current_price` instead of `ideal_entry`, artificially degrading reported limit order R:R and causing valid trades to be rejected with `PATH_BLOCKED`. | Pass `entry_res.ideal_entry` if `entry_mode == "limit_zone"` else `current_price` to `calculate_crt_targets`. |
| **F-06** | **High** | CRT Entry & Lifecycle | `services/strategies/crt/entry.py:175-190` | Evaluates static candle list and flags `is_missed = True` when price advances $>0.5\text{R}$ even if an earlier candle already filled the limit order. | Check if setup state is already `ENTRY_FILLED` before flagging `is_missed = True`. |
| **F-07** | **High** | Strategy Viability | `reports/crt_replay/crt_replay_report.md:28-51` | Replay across 5,625 bars yielded 0 confirmed trades due to hyper-restrictive gate confluence (HTF trend conflict vetoed 53.9% of sweeps; confirmation pending vetoed 24.7%). | Relax HTF trend filter to permit trades during neutral/ranging HTF regimes and calibrate confirmation gates. |
| **F-08** | **Medium** | Paper Trading | `services/paper_trading/order_executor.py:152` | Hardcodes `MIN_SL_DISTANCE_PIPS = 0.0001` (forex pip) instead of reading `pip_size` ($0.10 on Gold), making clearance guard 1000x too loose on Gold ($0.0001 = 0.001 pips). | Replace with `min_sl_distance = self.risk_manager.get_pip_size(order.symbol) * 1.0`. |
| **F-09** | **Medium** | Market Calendar | `services/market_data/freshness.py:54` vs `calendar.py:66` | Duplicated `is_forex_weekend` functions; `freshness.py` hardcodes UTC hours (Fri 21:00 - Sun 21:00 UTC) ignoring New York DST, causing 1-hour divergence from `calendar.py`. | Deprecate `freshness.py:is_forex_weekend` and route all weekend checks through `services/market_data/calendar.py`. |
| **F-10** | **Medium** | Symbol Normalization | `core/normalization.py:50` vs `market_data/symbols.py:84` | Duplicated `normalize_symbol` functions; `core` version silently guesses 6-char strings without error, while `market_data` version strictly enforces `INSTRUMENT_SPECS`. | Deprecate `core/normalization.py:normalize_symbol` and adopt `market_data/symbols.py:normalize_symbol` as canonical. |
| **F-11** | **Medium** | Backtest Timezones | `services/backtesting/walk_forward_harness.py:28-36` | `detect_session(ts)` uses raw UTC hours (0-8 Asia, 8-13 London, 13-21 NY) ignoring US DST, misclassifying trade sessions by 1 hour during Daylight Saving Time. | Convert timestamp to `ZoneInfo("America/New_York")` identical to `services/sweep/pools.py` and `crt_strategy.py`. |
| **F-12** | **Medium** | Configuration | `core/config.py:88-98` | 6 CRT settings (`CRT_MIN_SWEEP_ATR_MULT`, `CRT_MIN_RANGE_ATR_MULT`, etc.) and 5 indicator settings are defined in `Settings` but never read by strategy engines. | Inject `settings.CRT_*` and indicator parameters into calculators instead of hardcoded function defaults. |
| **F-13** | **Low** | Dead Code | `core/time_utils.py:1-74` | Zero application callers across `server/app` or scripts; only imported by its own test file `tests/test_time_utils.py`. | Remove `core/time_utils.py` and `tests/test_time_utils.py` or migrate remaining callers to standard `zoneinfo`. |
| **F-14** | **Low** | Dead Code | `services/strategies/crt/backtest_adapter.py:1-112` | Unreferenced in production runtime or scripts; 0 test coverage. | Remove dead adapter or wire into `scripts/run_sweep_backtest.py`. |
| **F-15** | **Low** | Code Quality | `services/sweep/backtest/engine.py:30` | Condition `if h >= 18 or h < 0:` contains impossible branch `h < 0` for `datetime.hour`. | Simplify to `if h >= 18:`. |
| **F-16** | **Low** | DevOps / CI | Repository Root | No GitHub Actions workflow or CI configuration exists in the repository (`.github` directory missing). | Add `.github/workflows/ci.yml` running `compileall` and `pytest tests/`. |
