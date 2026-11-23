"""Tests for the guarded virtual-funding helper (Option C capital side)."""

import json

import pytest

from app.scripts import paper_fund
from app.services.paper_trading.account_manager import VirtualAccountManager


def test_paper_fund_updates_balance_equity_and_writes_audit(
    test_db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(paper_fund.settings, "MODE", "paper")
    audit = tmp_path / "audit.jsonl"

    manager = VirtualAccountManager()
    account = manager.get_or_create_default_account(test_db_session)
    before = account.balance

    record = paper_fund.fund_account(
        test_db_session, 500.0, "Option C capital test", audit_path=audit
    )

    test_db_session.refresh(account)
    assert account.balance == round(before + 500.0, 2)
    assert account.equity == account.balance  # no open positions
    assert record["resulting_balance"] == account.balance

    rows = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["amount"] == 500.0
    assert rows[0]["reason"] == "Option C capital test"
    assert rows[0]["resulting_balance"] == account.balance
    assert "timestamp" in rows[0]

    # Append-only: a second top-up adds a row without rewriting the first.
    paper_fund.fund_account(test_db_session, 100.0, "second top-up", audit_path=audit)
    assert len(audit.read_text(encoding="utf-8").splitlines()) == 2


def test_paper_fund_rejects_negative_amount(test_db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(paper_fund.settings, "MODE", "paper")
    audit = tmp_path / "audit.jsonl"
    with pytest.raises(SystemExit, match="must be positive"):
        paper_fund.fund_account(test_db_session, -5.0, "bad", audit_path=audit)
    assert not audit.exists()


def test_paper_fund_refuses_non_paper_mode(test_db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(paper_fund.settings, "MODE", "live")
    audit = tmp_path / "audit.jsonl"
    with pytest.raises(SystemExit, match="paper mode"):
        paper_fund.fund_account(test_db_session, 100.0, "bad", audit_path=audit)
    assert not audit.exists()
