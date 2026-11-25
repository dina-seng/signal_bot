"""Official Telegram Login Widget: signature verification and sessions."""

import hashlib
import hmac
import time

from app.core.config import settings
from app.models.user import User


BOT_TOKEN = "test-widget-bot-token"


def _widget_payload(telegram_id=555, *, auth_date=None, stale=False):
    values = {
        "id": telegram_id,
        "first_name": "Widget",
        "username": "widget_user",
        "photo_url": "https://example.com/photo.png",
        "auth_date": auth_date if auth_date is not None else int(time.time()),
    }
    if stale:
        values["auth_date"] = int(time.time()) - settings.WIDGET_AUTH_MAX_AGE_SECONDS - 60
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hashlib.sha256(BOT_TOKEN.encode("utf-8")).digest()
    values["hash"] = hmac.new(
        secret, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return values


def test_telegram_widget_hash_verification(client, test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setattr(settings, "ADMIN_TELEGRAM_ID", 555)

    payload = _widget_payload()
    response = client.post("/api/v1/auth/telegram-widget-verify", json=payload, follow_redirects=False)

    assert response.status_code == 302, response.text
    assert response.headers["location"] == settings.DASHBOARD_REDIRECT_URL
    assert settings.SESSION_COOKIE_NAME in response.cookies

    user = test_db_session.query(User).filter(User.telegram_id == 555).one_or_none()
    assert user is not None
    assert user.username == "widget_user"
    assert user.is_admin is True

    me = client.get("/api/v1/auth/me")
    assert me.json()["user"]["id"] == str(user.id)


def test_telegram_widget_get_redirect(client, test_db_session, monkeypatch):
    """The real widget navigates to data-auth-url with query params."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    payload = _widget_payload(telegram_id=556)
    response = client.get("/api/v1/auth/telegram-widget-verify", params=payload, follow_redirects=False)
    assert response.status_code == 302
    assert test_db_session.query(User).filter(User.telegram_id == 556).one() is not None


def test_telegram_widget_invalid_hash(client, test_db_session, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    payload = _widget_payload()
    payload["username"] = "tampered_attacker"
    response = client.post("/api/v1/auth/telegram-widget-verify", json=payload, follow_redirects=False)
    assert response.status_code == 401
    assert test_db_session.query(User).count() == 0


def test_telegram_widget_expired_payload(client, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    payload = _widget_payload(stale=True)
    response = client.post("/api/v1/auth/telegram-widget-verify", json=payload, follow_redirects=False)
    assert response.status_code == 401


def test_widget_valid_signature(client, test_db_session, monkeypatch):
    """GET query params signed with SHA256(bot_token).digest() authenticate."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setattr(settings, "ADMIN_TELEGRAM_ID", 557)
    payload = _widget_payload(telegram_id=557)
    payload["last_name"] = "Signed"

    # Re-sign including the extra field.
    data = {k: v for k, v in payload.items() if k != "hash"}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    import hashlib
    import hmac
    payload["hash"] = hmac.new(
        hashlib.sha256(BOT_TOKEN.encode()).digest(),
        check.encode(),
        hashlib.sha256,
    ).hexdigest()

    response = client.get(
        "/api/v1/auth/telegram-widget-verify", params=payload, follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"].endswith("/dashboard")
    assert settings.SESSION_COOKIE_NAME in response.cookies
    assert test_db_session.query(User).filter(User.telegram_id == 557).one().is_admin is True


def test_widget_invalid_signature(client, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    payload = _widget_payload()
    payload["hash"] = "0" * 64
    response = client.get(
        "/api/v1/auth/telegram-widget-verify", params=payload, follow_redirects=False
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid Telegram widget signature"


def test_widget_future_auth_date_accepted(client, monkeypatch):
    """Future timestamps are not rejected (staleness is one-directional)."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    payload = _widget_payload(auth_date=int(time.time()) + 600)
    response = client.post(
        "/api/v1/auth/telegram-widget-verify", json=payload, follow_redirects=False
    )
    assert response.status_code == 302
