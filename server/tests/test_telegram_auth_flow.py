"""Milestone 2: Telegram magic-link auth, session guard and multi-user broadcast."""

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.models.user import User
from app.schemas.telegram import TelegramCommandRequest, TelegramMessageResponse
from app.services.telegram.broadcast import broadcast_to_subscribers
from app.services.telegram.client import MockTelegramClient
from app.services.telegram.command_handler import TelegramCommandHandler


def _message_response(chat_id: str, *, success: bool = True, error=None):
    return TelegramMessageResponse(
        success=success,
        message_id=1,
        chat_id=chat_id,
        text_sent="test",
        sent_at=datetime.now(timezone.utc),
        error=error,
    )


def test_telegram_auth_flow(client, test_db_session, monkeypatch):
    """Mock /login -> magic link -> verify -> user + signed session cookie."""
    monkeypatch.setattr(settings, "ADMIN_TELEGRAM_ID", 777)
    tg = MockTelegramClient()
    handler = TelegramCommandHandler(telegram_client=tg)

    reply = asyncio.run(handler.handle_command(
        db=test_db_session,
        request=TelegramCommandRequest(
            command="/login", chat_id="777", user_id=777, user_name="tester"
        ),
    ))

    assert reply.handled_successfully is True
    record = tg.sent_messages[-1]
    keyboard = record["reply_markup"]["inline_keyboard"]
    login_url = keyboard[0][0]["url"]
    assert "Click here to log in to QuantView" in keyboard[0][0]["text"]
    assert "/auth/callback?token=" in login_url
    token = login_url.split("token=")[1]

    verified = client.post("/api/v1/auth/verify", json={"token": token})
    assert verified.status_code == 200, verified.text
    payload = verified.json()
    assert payload["authenticated"] is True
    assert payload["user"]["telegram_id"] == 777
    assert payload["user"]["is_admin"] is True
    assert settings.SESSION_COOKIE_NAME in verified.cookies

    users = test_db_session.query(User).all()
    assert len(users) == 1
    assert users[0].is_admin is True

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["telegram_id"] == 777

    # A second use of the same token must fail.
    replay = client.post("/api/v1/auth/verify", json={"token": token})
    assert replay.status_code == 400


def test_start_login_deep_link_uses_same_flow(test_db_session):
    """The web deep link sends '/start login' and must yield the same magic link."""
    tg = MockTelegramClient()
    handler = TelegramCommandHandler(telegram_client=tg)

    reply = asyncio.run(handler.handle_command(
        db=test_db_session,
        request=TelegramCommandRequest(
            command="/start login", chat_id="888", user_id=888,
            user_name="deeplink", start_parameter="login",
        ),
    ))

    assert reply.handled_successfully is True
    assert "QuantView Login" in reply.reply_text
    record = tg.sent_messages[-1]
    login_url = record["reply_markup"]["inline_keyboard"][0][0]["url"]
    assert "/auth/callback?token=" in login_url

    from app.models.user import LoginToken
    token_row = test_db_session.query(LoginToken).filter(LoginToken.telegram_id == 888).one_or_none()
    assert token_row is not None

    # Plain /start still shows the help menu.
    help_reply = asyncio.run(handler.handle_command(
        db=test_db_session,
        request=TelegramCommandRequest(command="/start", chat_id="888", user_id=888),
    ))
    assert "/scan" in help_reply.reply_text


def test_unauthorized_redirect(client, monkeypatch):
    """Protected APIs answer 401 while public/health/preflight stay reachable."""
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    assert client.get("/api/v1/dashboard/snapshot").status_code == 401
    assert client.get("/api/v1/paper/summary").status_code == 401
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200

    preflight = client.options(
        "/api/v1/dashboard/snapshot",
        headers={
            "Origin": settings.FRONTEND_ORIGIN[0],
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.status_code == 200


@pytest.mark.asyncio
async def test_broadcast(test_db_session, monkeypatch):
    """Three subscribers -> three sends with a 0.5s gap between them."""
    for telegram_id in (111, 222, 333):
        test_db_session.add(User(id=uuid.uuid4(), telegram_id=telegram_id))
    test_db_session.commit()

    tg = MockTelegramClient()
    monkeypatch.setattr(settings, "TELEGRAM_BROADCAST_DELAY_SECONDS", 0.5)
    delays = []

    async def _no_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr("app.services.telegram.broadcast.asyncio.sleep", _no_sleep)

    results = await broadcast_to_subscribers(
        test_db_session, tg, text="broadcast test"
    )

    assert len(results) == 3
    assert len(tg.sent_messages) == 3
    assert {msg["chat_id"] for msg in tg.sent_messages} == {"111", "222", "333"}
    assert delays == [0.5, 0.5]


@pytest.mark.asyncio
async def test_blocked_user_is_unsubscribed(test_db_session, monkeypatch):
    """HTTP 403 from Telegram clears that user's telegram_id."""
    user = User(id=uuid.uuid4(), telegram_id=999)
    test_db_session.add(user)
    test_db_session.commit()

    client = AsyncMock()
    client.send_message = AsyncMock(
        return_value=_message_response("999", success=False, error="Telegram API error 403: Forbidden")
    )
    monkeypatch.setattr("app.services.telegram.broadcast.asyncio.sleep", AsyncMock())

    await broadcast_to_subscribers(test_db_session, client, text="blocked test")

    test_db_session.refresh(user)
    assert user.telegram_id is None
