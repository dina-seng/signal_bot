# Live Paper-Trade Sizing Audit (READ ONLY)

**Date:** 2026-11-23
**Scope:** diagnosis only — no code, config, manifest, or strategy changes were made.
**Symptom audited:** dashboard "Risk Per Order: 0.5%" / BAL $214.20, open BUY 0.01 lot
XAU/USD with entry 3592.79 and SL 3515.43 (77.36 price-unit stop) risks ~$77 ≈ 36% of
account, not 0.5%.

---

## Verdict

**COMPUTED-AND-CLAMPED.**

A genuine risk-based sizing formula exists and is executed, but the computed lot is
floored to a hard minimum of **0.01 lots**. With a small account and a wide stop, the
formula returns a tiny fraction of a lot (≈0.0001), which is silently rounded/clamped to
0.01. The 0.5% figure is therefore honored as the *target budget inside the formula* but
is **not honored as a realized risk cap**. The trade is not rejected; it is forced to
the minimum lot.

---

## Q1 — Exact lot-sizing code path

```
run_scan_cycle
  server/app/services/telegram/scanner.py:471-483
      paper_service.trade_from_signal(
          AutoTradeSignalRequest(..., risk_percent=settings.MAX_RISK_PERCENT)  # :477
      )

PaperTradingService.trade_from_signal
  server/app/services/paper_trading/paper_service.py:84-87
      -> order_executor.open_trade_from_signal(db, request)

PaperOrderExecutor.open_trade_from_signal
  server/app/services/paper_trading/order_executor.py:332-426
      :351-354   load Signal by request.signal_id
      :372-387   idempotency guard (existing trade returned unchanged)
      :392       live_price = get_latest_market_price(...)
      :397-401   validate_signal_before_execution (staleness + live-price gates)
      :413-423   build PaperOrderCreate(risk_percent=request.risk_percent,
                                        stop_loss=signal.stop_loss, tp1/tp2=..., )
      :426       execute_order(..., current_market_price=live_price)

PaperOrderExecutor.execute_order
  server/app/services/paper_trading/order_executor.py:213-324
      :229-230   mkt_price; pip_size = risk_manager.get_pip_size(symbol)
      :234-240   MARKET entry = live price + 0.5 pip half-spread for BUY
      :253-255   sl / tp1 / tp2 carried from the signal
      :269-274   *** SIZING BRANCH USED (SL + TP present) ***
      :276-277   override + clamp
      :279-290   margin validation
      :296-320   PaperTrade(initial_position_size=lots, remaining_position_size=lots)
      :324       recalculate_account_financials
```

The fallback branch at `order_executor.py:257-268` (when SL/TP are absent) delegates to
`RiskManager.calculate_trade_risk` and takes `risk_res.suggested_lot_size`; the live
signal path never uses it, because signals always carry SL/TP.

---

## Q2 — Is there a risk-based sizing formula?

Yes. The live path uses the branch at `order_executor.py:269-274`:

```python
# order_executor.py:270-274
risk_pips = abs(exec_entry - sl) / pip_size
pip_val   = self.risk_manager.get_pip_value_per_lot(order.symbol)
risk_usd  = account.balance * ((order.risk_percent or 0.5) / 100.0)
calculated_lots = round(max(0.01, min(100.0, risk_usd / max(1e-6, risk_pips * pip_val))), 2)
```

This is exactly `lots = (equity × risk%) / (stop_distance_in_pips × pip_value)`, with
the clamp applied. A second, independent copy of the same formula exists in the
risk manager at `server/app/services/signals/risk_manager.py:121-125`:

```python
risk_amount_usd = round(balance * (risk_pct / 100.0), 2)
pip_val = self.get_pip_value_per_lot(symbol)
raw_lots = risk_amount_usd / max(1e-6, risk_pips * pip_val)
suggested_lots = round(max(0.01, min(100.0, raw_lots)), 2)
```

Note that `execute_order` uses `account.balance`, not `account.equity`
(`order_executor.py:273`). At `risk_manager.py:122` the same value is passed as
`account_balance`. The dashboard label "Risk Per Order" is therefore applied to cash
balance, not mark-to-market equity.

Final assignment (`order_executor.py:276-277`):

```python
lots = round(order.position_size if order.position_size else calculated_lots, 2)
lots = max(0.01, min(100.0, lots))
```

`order.position_size` is `None` from `open_trade_from_signal` (`order_executor.py:413-423`
does not set it), so `calculated_lots` is always used on the scanner path.

---

## Q3 — Min lot and below-min behaviour

| Item | Evidence |
|---|---|
| Minimum lot | `0.01` — hardcoded literal at `order_executor.py:274`, `:277` and `risk_manager.py:125`; schema floor `position_size ge=0.01` at `server/app/schemas/paper_trading.py:58`; `AutoTradeSignalRequest` has no lot field at all (`:115-121`) |
| Maximum lot | `100.0` — same three sites |
| Behaviour below min | **Forced to 0.01, trade proceeds.** Both `max(0.01, ...)` clamps (`:274`, `:277`) silently raise the lot; there is no "risk exceeds limit" exception on this path |
| Actual rejections on this path | (a) insufficient free margin `order_executor.py:287-290`; (b) pre-execution staleness / live-price invalidation `order_executor.py:397-401`; (c) idempotency returns an existing trade `:372-387` |

The only place that *warns* about this condition is the Telegram formatter at
`server/app/services/telegram/message_formatter.py:222-228`, which prints
"RISK EXCEEDS LIMIT … (Min lot 0.01 exceeds budget)" — but that warning is driven by a
`risk_warning` metadata field which no code in the repository populates (grep for
`risk_warning` yields only the formatter). It never reaches the paper-trade executor.

---

## Q4 — Pip / contract convention (BT-010 cross-check)

**The sizer uses the RiskManager / instrument-spec convention: pip_size = 0.10 and
point value = $10.00 per standard lot for XAU/USD.**

- `server/app/services/market_data/symbols.py:31-40` — `XAU/USD`: `pip_size=0.10`,
  `point_value_per_lot=10.0`, `contract_size=100.0` (100 oz/lot).
- `server/app/services/signals/risk_manager.py:18-21` `get_pip_size` → spec above;
  `:29-34` `get_pip_value_per_lot` → `point_value_per_lot` = 10.0.
- `order_executor.py:230` and `:271-272` call exactly those two methods.
- The P&L mark-to-market uses the same pair:
  `server/app/api/v1/paper.py:163-169` and
  `server/app/services/paper_trading/position_manager.py:215-216, 256-259`.

**BT-010 confirmed as a labelling inconsistency, not a sizing error:**
`server/app/services/indicators/atr_calculator.py:11-15` returns `0.01` for XAU/USD, as
do `server/app/services/indicators/price_action.py:36-40` and
`server/app/services/liquidity/sweep_detector.py:46-50`. Those modules report "pips"
that are 10× larger than RiskManager pips. They do not feed the sizer, so lot sizes are
computed consistently with $10/pip. Dollar risk is invariant to the convention as long
as `pip_size × pip_value` is consistent — `0.10 × $10 = 0.01 × $1 = $1 per $1 of price
move per lot`, i.e. 100 oz × Δprice. The practical damage is conflicting "pip" labels
between the chart/ATR panels and the risk panel, not a wrong lot size.

---

## Q5 — Does the header include floating P&L?

**Yes, by design — but the displayed value can be stale.**

Trace:

1. `server/app/services/paper_trading/position_manager.py:253-259` — on each
   `sync_prices` tick, `t.current_price` is refreshed and
   `t.unrealized_pnl = round(pips_gain * pip_val * remaining_lots, 2)` is written to the DB.
   `run_scan_cycle` invokes this at `server/app/services/telegram/scanner.py:496`.
2. `server/app/services/paper_trading/account_manager.py:161-180` — `recalculate_account_financials`
   sums the **stored** `t.unrealized_pnl` and sets
   `account.equity = round(account.balance + total_unrealized_pnl, 2)` (`:172-175`).
3. `paper_service.get_account_summary` (`paper_service.py:45-53`) →
   `get_account_response` (`account_manager.py:182-226`), which calls
   `recalculate_account_financials` again (`:184`) using the stored values.
4. `client/src/pages/Dashboard.tsx:118-140` computes
   `calculatedUnrealized = bAcc.equity - bAcc.balance` (`:122`) and feeds it to the header.
5. `client/src/components/Header.tsx:77` formats that value; `:272-287` renders the
   "P&L:" badge.

**Why the header can read -$0.05 while the ledger shows -$2.51:** `GET /paper/positions`
re-prices open trades on the fly at `server/app/api/v1/paper.py:162-169` (using the live
quote) and updates `unrealized_pnl` in the response object, whereas
`GET /paper/account` only aggregates the previously persisted value. In
`fetchAccountAndPositions`, the account is fetched **first** (`Dashboard.tsx:118`) and
positions **second** (`Dashboard.tsx:143`), so the header is one price-tick stale
relative to the table. The 30-second refresh cadence (`Dashboard.tsx:112`) and the
scanner-driven `sync_prices` are the only things that refresh the persisted figure.
This is a freshness/ordering defect, **not** a missing mark-to-market: equity does
include floating P&L.

---

## Worked example — $214.20 / 0.5% / 77.36-point stop

Inputs: `balance = 214.20`, `risk_percent = 0.5`, `stop_distance = 3592.79 - 3515.43 = 77.36`,
`pip_size = 0.10` (symbols.py:35), `pip_val = 10.0` (symbols.py:36).

| Step | Expression | Value |
|---|---|---:|
| Risk budget | `214.20 × 0.5 / 100` | **$1.071** |
| Stop in pips | `77.36 / 0.10` | **773.6 pips** |
| Risk per 1.00 lot | `773.6 × $10.00` | **$7,736.00** |
| Raw lots | `1.071 / 7736` | **0.0001384 lots** |
| After `round(..., 2)` | — | **0.00 lots** |
| After `max(0.01, …)` | — | **0.01 lots** |
| Realized stop risk | `773.6 × $10.00 × 0.01` | **$77.36** |
| Realized risk % | `77.36 / 214.20` | **36.12%** |

Cross-check via contract size: `0.01 lot × 100 oz × $77.36 = $77.36` — same answer,
confirming $10/pip is internally consistent with 100 oz/lot.

Why it is not rejected: required margin at 100:1 leverage is
`0.01 × 100 oz × 3592.79 / 100 ≈ $3.59`, far below free margin, so the check at
`order_executor.py:287-290` passes. The half-spread adjustment at `:236-240` changes the
BUY entry from 3592.79 to ≈3592.84, making the stop ≈77.41 and the realized risk
≈$77.41 (36.14%) — immaterial to the conclusion.

**To honour 0.5% at this stop distance would require ≈0.0001 lots, which the 0.01 lot
floor makes impossible on this venue. The minimum-lot trade is ~72× the intended risk.**

---

## Is the "0.5%" label honored anywhere?

| Location | Status |
|---|---|
| Backend target budget | **Honored** — `settings.MAX_RISK_PERCENT` default `0.5` (`server/app/core/config.py:55-60`) flows through `scanner.py:477` → `order_executor.py:418` → `:273` |
| Risk-manager suggested sizing | **Honored**, then clamped — `risk_manager.py:121-125` |
| Realized risk | **Not honored** — min-lot clamp dominates (`order_executor.py:274,277`) |
| Dashboard "Risk Per Order: 0.5%" | **Cosmetic / hardcoded** — `client/src/components/NewsRiskMonitor.tsx:72` renders `riskStatus.allowedRiskPercent`, which is assigned literal `0.5` in `client/src/pages/Dashboard.tsx:432`, `:786`, and `0.0` at `:773`. It is not read from `appConfig.risk_per_order_pct` (`client/src/services/api.ts:35`), even though the backend `GET /api/v1/config` exposes `risk_per_order_pct=settings.MAX_RISK_PERCENT` |
| Telegram "RISK EXCEEDS LIMIT" warning | **Dead code** — formatter branch exists (`message_formatter.py:222-228`) but no producer sets `risk_warning` |

---

## Summary answers

- **Q1:** `scanner.py:471-483` → `paper_service.py:84-87` → `order_executor.py:332-426` →
  `execute_order` `order_executor.py:213-324`, sizing at `:269-277`.
- **Q2:** Yes — `order_executor.py:270-274` (and `risk_manager.py:121-125`).
- **Q3:** Min lot `0.01`; below-min is **forced to 0.01**, not rejected. Only margin or
  pre-trade validation gates reject.
- **Q4:** Sizer uses RiskManager's `pip_size=0.10`, `$10.00/lot` (BT-010: ATR/PA/sweep
  modules use `0.01`, a labelling inconsistency only).
- **Q5:** Equity = balance + floating P&L (`account_manager.py:172-175`), so it does mark
  to market, but the account endpoint reads the persisted value while the positions
  endpoint re-prices live (`paper.py:162-169`); fetching account before positions
  (`Dashboard.tsx:118,143`) makes the header one tick stale.
