"""Schema drift: a missing user_id column must not 500 the dashboard."""

from sqlalchemy.exc import ProgrammingError

from app.services.paper_trading.account_manager import VirtualAccountManager


def test_missing_column_recovery(client, test_db_session, monkeypatch, caplog):
    """Simulate UndefinedColumn on the account lookup; expect rollback + legacy read."""
    account = VirtualAccountManager().get_or_create_default_account(test_db_session)

    real_scalars = test_db_session.scalars
    real_rollback = test_db_session.rollback
    state = {"scalars": 0, "rollbacks": 0}

    def fake_scalars(statement, *args, **kwargs):
        state["scalars"] += 1
        if state["scalars"] == 1:
            raise ProgrammingError(
                "SELECT ... FROM virtual_accounts ... user_id ...",
                {},
                Exception("column virtual_accounts.user_id does not exist"),
            )
        return real_scalars(statement, *args, **kwargs)

    def spy_rollback():
        state["rollbacks"] += 1
        return real_rollback()

    monkeypatch.setattr(test_db_session, "scalars", fake_scalars)
    monkeypatch.setattr(test_db_session, "rollback", spy_rollback)

    with caplog.at_level("WARNING"):
        response = client.get("/api/v1/paper/summary")

    assert response.status_code == 200, response.text
    assert response.json()["account"]["id"] == account.id
    assert state["rollbacks"] >= 1
    assert "schema drift" in caplog.text
    assert "virtual_accounts.user_id" in caplog.text
