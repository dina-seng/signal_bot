"""Unified 'QuantView Desk' final-validation summary.

Prints one ASCII table comparing the two frozen strategies side by side, then
a SURVIVAL CHECK that converts each strategy's R-based drawdown into real USD
risk for the two specified accounts at the 0.01 minimum lot.

Data inputs (no trading logic is reimplemented here):
  * BTC/USD 1H momentum: the hardcoded winning config in
    ``backtest_btc_momentum.py``, replayed on the cached Binance bars.
  * XAU/USD 15m SMC: accepted trades from the ``smc_replay.py`` checkpoints
    produced with the live SMC strategy (min score 60) on Twelve Data 15m bars.
    R-multiples already include the 0.40 price-unit round-trip friction.

Usage (from repository root)::

    python server/scripts/final_validation_desk.py
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = REPO_ROOT / "server"
SCRIPTS_ROOT = Path(__file__).resolve().parent
for p in (str(SERVER_ROOT), str(SCRIPTS_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from backtest_btc_momentum import (  # noqa: E402
    EXNESS_FEE_BPS,
    EXNESS_SLIPPAGE_BPS,
    EXNESS_SPREAD_USD,
    FINAL_ADX_THRESHOLD,
    FINAL_ATR_MULTIPLIER,
    FINAL_COST_LABEL,
    FINAL_MIN_SCORE,
    CostModel,
    load_real_data,
    precompute_indicators,
    run_backtest,
)
from replay_metrics import compute_core_metrics  # noqa: E402

DEFAULT_SMC_CKPT_DIR = REPO_ROOT / "reports" / "final_validation_2026-11-28" / "checkpoints"

# Account facts supplied for the survival check.
# Both desks are funded to a professional $10,000.00 testing size.
XAU_BALANCE_USD = 10000.0
XAU_LOT_SIZE = 0.01          # 0.01 lots XAU/USD = 1.00 oz (100 oz per standard lot)
XAU_OZ_PER_LOT = 100.0
# Cent accounts report balances in cents: 1,000,000 cents == $10,000.00 USD.
# This is the USD balance the survival check compares risk against.
BTC_BALANCE_CENTS = 1000000
BTC_BALANCE_USD = BTC_BALANCE_CENTS / 100.0
BTC_LOT_SIZE = 0.01          # 0.01 lots BTC/USD = 0.01 BTC (1 BTC per standard lot)
BTC_UNITS_PER_LOT = 1.0


@dataclass
class StrategyMetrics:
    name: str
    trades: int
    win_rate: Optional[float]
    profit_factor: Optional[float]
    total_r: Optional[float]
    max_dd_r: Optional[float]
    avg_stop: Optional[float]


def _fmt(value: Optional[float], digits: int = 2, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    if math.isnan(value):
        return "n/a"
    return f"{value:{'+' if signed else ''}.{digits}f}"


def btc_metrics() -> StrategyMetrics:
    """Replay the hardcoded winning BTC config on the cached Binance bars."""
    args = argparse.Namespace(db=None, refresh_cache=False, cache_only=True)
    with redirect_stdout(open(os.devnull, "w", encoding="utf-8")):
        candles, _, _ = load_real_data(args)
    series = precompute_indicators(candles)
    _, trades = run_backtest(
        candles, series,
        atr_multiplier=FINAL_ATR_MULTIPLIER,
        adx_threshold=FINAL_ADX_THRESHOLD,
        min_score=FINAL_MIN_SCORE,
    )
    cost = CostModel(
        label=FINAL_COST_LABEL, fee_bps=EXNESS_FEE_BPS,
        spread_usd=EXNESS_SPREAD_USD, slippage_bps=EXNESS_SLIPPAGE_BPS,
    )
    order = [t.exit_time.isoformat() for t in trades]
    net = compute_core_metrics([cost.net_r(t) for t in trades], order=order)
    avg_stop = sum(t.risk for t in trades) / len(trades) if trades else None
    return StrategyMetrics(
        name="Momentum 1H (BTC/USD)",
        trades=len(trades),
        win_rate=net["win_rate"],
        profit_factor=net["profit_factor"],
        total_r=net["total_r"],
        max_dd_r=net["max_drawdown_r"],
        avg_stop=avg_stop,
    )


def smc_metrics(ckpt_dir: Path) -> StrategyMetrics:
    """Aggregate accepted, filled SMC trades from the replay checkpoints."""
    paths = sorted(glob.glob(str(ckpt_dir / "*.json")))
    if not paths:
        raise SystemExit(f"SMC ABORT: no checkpoint JSON files in {ckpt_dir}")
    trades: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        for rec in payload.get("records", []):
            trade = rec.get("accepted_trade")
            if not rec.get("accepted") or not trade:
                continue
            if not trade.get("filled") or trade.get("r_multiple") is None:
                continue
            if trade.get("void_reason"):
                continue
            trades.append(trade)

    # One entry per 1h opportunity (same convention as smc_replay._dedupe).
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for t in trades:
        key = str(t.get("sweep_key") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(t)
    if not deduped:
        raise SystemExit("SMC ABORT: no accepted filled trades in checkpoints")

    order = [str(t.get("exit_time") or t.get("signal_time") or "") for t in deduped]
    core = compute_core_metrics([float(t["r_multiple"]) for t in deduped], order=order)
    avg_stop = (
        sum(float(t["risk_price"]) for t in deduped) / len(deduped)
        if deduped else None
    )
    return StrategyMetrics(
        name="SMC 15m (XAU/USD)",
        trades=len(deduped),
        win_rate=core["win_rate"],
        profit_factor=core["profit_factor"],
        total_r=core["total_r"],
        max_dd_r=core["max_drawdown_r"],
        avg_stop=avg_stop,
    )


def print_desk(smc: StrategyMetrics, btc: StrategyMetrics) -> None:
    line = "=" * 92
    print(line)
    print(" " * 24 + "QUANTVIEW DESK - FINAL VALIDATION")
    print(" " * 26 + "Institutional Desk Summary")
    print(line)
    print(
        " BTC : 2025-01-01 -> 2026-11-28 (1H bars) | Exness: $25 spread, 5 bps slippage, fee label 0"
        f" | ATR {FINAL_ATR_MULTIPLIER:g}x, ADX >= {FINAL_ADX_THRESHOLD:g}, score >= {FINAL_MIN_SCORE:g}"
    )
    print(
        " XAU : cached Twelve Data 15m decisions (1H primary) | min score 60 | "
        "$0.40/unit round trip already in R"
    )
    print("-" * 92)
    print(
        f" {'Strategy':<24}{'Trades':>8}{'Win %':>9}{'Net PF':>9}"
        f"{'Net Total R':>14}{'Max DD (R)':>13}"
    )
    print("-" * 92)
    for m in (smc, btc):
        print(
            f" {m.name:<24}{m.trades:>8}{(_fmt(m.win_rate, 2) + '%'):>9}"
            f"{_fmt(m.profit_factor, 2):>9}{(_fmt(m.total_r, 2, True) + ' R'):>14}"
            f"{(_fmt(m.max_dd_r, 2) + ' R'):>13}"
        )
    print("-" * 92)
    print(" Net PF / total R / DD are after costs. R = planned stop distance.")

    print()
    print("SURVIVAL CHECK (0.01 min lot; USD risk = avg stop distance x position size)")
    print("-" * 92)
    rows = [
        ("XAU/USD - Main Account", XAU_BALANCE_USD, smc,
         XAU_LOT_SIZE * XAU_OZ_PER_LOT, "oz", "100 oz/lot"),
        ("BTC/USD - Cent Account", BTC_BALANCE_USD, btc,
         BTC_LOT_SIZE * BTC_UNITS_PER_LOT, "BTC", "1 BTC/lot"),
    ]
    for label, balance, m, units, unit_name, contract in rows:
        risk = (m.avg_stop or 0.0) * units
        dd = (m.max_dd_r or 0.0) * risk
        survives = dd < balance
        lot_size = XAU_LOT_SIZE if "XAU" in label else BTC_LOT_SIZE
        pct_of_balance = (risk / balance * 100.0) if balance else 0.0
        print(f" {label}")
        print(f"   Account balance            : ${balance:,.2f}" +
              (f" ({int(round(balance * 100)):,} cents)" if "Cent" in label else ""))
        print(f"   Avg stop distance          : ${_fmt(m.avg_stop, 2)} / {unit_name} ({contract})")
        print(f"   USD risk / trade (1R)      : ${risk:,.2f} at {lot_size:.2f} lot")
        print(f"   Calculated Risk: ${risk:,.2f} ({pct_of_balance:.2f}% of Balance) using {lot_size:.2f} lots")
        print(f"   Max drawdown               : {_fmt(m.max_dd_r, 2)} R = ${dd:,.2f}")
        verdict = "✅ SURVIVES" if survives else "⚠️ BLOWOUT RISK"
        comp = "<" if survives else ">="
        print(f"   Result                     : {verdict} (max DD ${dd:,.2f} {comp} ${balance:,.2f})")
        print("-" * 92)

    print()
    print("FINAL EQUITY (net P&L = net total R x USD risk per R)")
    print("-" * 92)
    for label, balance, m, units, _, _ in rows:
        risk = (m.avg_stop or 0.0) * units
        net_pnl = round((m.total_r or 0.0) * risk, 2)
        final_equity = round(balance + net_pnl, 2)
        print(f" {label}")
        print(f"Starting Balance: ${balance:,.2f}")
        print(f"Net Profit/Loss: ${net_pnl:,.2f}")
        print(f"Final Equity: ${final_equity:,.2f}")
        print("-" * 92)
    print(line)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--smc-checkpoints", type=Path, default=DEFAULT_SMC_CKPT_DIR)
    args = p.parse_args(argv)
    smc = smc_metrics(args.smc_checkpoints)
    btc = btc_metrics()
    print_desk(smc, btc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
