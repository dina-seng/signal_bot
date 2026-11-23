"""Guarded virtual-funds top-up for the paper trading account.

Usage:
    python -m app.scripts.paper_fund --amount 500 --reason "Option C capital test"

Hard-refuses anything outside paper mode, rejects non-positive amounts, appends an
audit record, and recalculates account financials after the deposit.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

# Ensure server root is in sys.path (matches other app.scripts CLIs).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import logger
from app.services.paper_trading.account_manager import VirtualAccountManager

AUDIT_PATH = Path(__file__).resolve().parents[2] / "reports" / "paper_funding_audit.jsonl"


def fund_account(db, amount: float, reason: str, audit_path: Path = AUDIT_PATH) -> Dict[str, float]:
    """Apply a virtual deposit and append an immutable audit record."""
    if settings.MODE.strip().lower() != "paper":
        raise SystemExit(
            f"REFUSED: MODE={settings.MODE!r} — virtual funding is only allowed in paper mode."
        )
    if amount <= 0:
        raise SystemExit(
            "REFUSED: --amount must be positive. Negative amounts (withdrawals) are not permitted."
        )
    if not reason or not reason.strip():
        raise SystemExit("REFUSED: --reason is required for the audit trail.")

    manager = VirtualAccountManager()
    account = manager.get_or_create_default_account(db)
    before_balance = account.balance

    account = manager.deposit_funds(
        db, account.id, amount, description=f"paper_fund: {reason.strip()}"
    )
    account = manager.recalculate_account_financials(db, account)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "amount": round(amount, 2),
        "reason": reason.strip(),
        "account_id": account.id,
        "balance_before": round(before_balance, 2),
        "resulting_balance": round(account.balance, 2),
        "resulting_equity": round(account.equity, 2),
        "mode": settings.MODE,
    }
    audit_path = Path(audit_path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")

    logger.info(f"[paper_fund] {record}")
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fund the paper trading account (virtual funds only).")
    parser.add_argument("--amount", type=float, required=True, help="Positive USD amount to add")
    parser.add_argument("--reason", type=str, required=True, help="Audit reason (required)")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        record = fund_account(db, args.amount, args.reason)
    finally:
        db.close()

    print(
        f"[+] Virtual account #{record['account_id']}: "
        f"${record['balance_before']:,.2f} -> ${record['resulting_balance']:,.2f} "
        f"(equity ${record['resulting_equity']:,.2f})"
    )
    print(f"[+] Audit appended: {AUDIT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
