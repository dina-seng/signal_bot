"""Same-origin Telegram login regression tests (mobile cookie loop).

The widget callback, the API base and the session cookie must all live on the
frontend origin. Cross-site cookies are dropped by mobile ITP/STP, producing a
/login redirect loop on phones while desktop keeps working.
"""

import hashlib
import hmac
import re
import time
from pathlib import Path

import pytest

from app.core.config import settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def _signed_widget_payload(telegram_id: int = 777) -> dict:
    values = {
        "id": telegram_id,
        "first_name": "Mobile",
        "username": "mobile_user",
        "auth_date": int(time.time()),
    }
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret = hashlib.sha256(settings.TELEGRAM_BOT_TOKEN.encode("utf-8")).digest()
    values["hash"] = hmac.new(
        secret, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return values


@pytest.fixture
def widget_token(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "same-origin-widget-token")
    monkeypatch.setattr(settings, "ADMIN_TELEGRAM_ID", None)
    return _signed_widget_payload()


def test_widget_authurl_is_first_party():
    """The rendered widget callback must be absolute and on the frontend host."""
    login_source = (REPO_ROOT / "client" / "src" / "pages" / "Login.tsx").read_text(
        encoding="utf-8"
    )
    same_origin = (
        REPO_ROOT / "client" / "src" / "config" / "sameOrigin.ts"
    ).read_text(encoding="utf-8")

    site_origin = re.search(r"SITE_ORIGIN = '([^']+)'", same_origin).group(1)
    api_base_path = re.search(r"API_BASE_PATH = '([^']+)'", same_origin).group(1)
    # Reconstruct the URL the widget actually receives at render time.
    rendered_auth_url = (
        f"{site_origin}{api_base_path}/auth/telegram-widget-verify"
    )
    assert rendered_auth_url == (
        "https://quanview.dinacreator.space"
        "/api/v1/auth/telegram-widget-verify"
    )
    assert f"`${{SITE_ORIGIN}}${{API_BASE_PATH}}/auth/telegram-widget-verify`" in same_origin

    # Login.tsx renders exactly that constant into the widget attribute.
    assert "TELEGRAM_WIDGET_AUTH_URL" in login_source
    assert "data-auth-url" in login_source
    auth_url_line = next(
        line for line in login_source.splitlines() if "data-auth-url" in line
    )
    assert "widgetAuthUrl" in auth_url_line
    assert "onrender.com" not in login_source

    # No browser-facing config may point at the backend host.
    for relative in (
        "client/.env",
        "client/src/services/api.ts",
        "client/src/pages/Login.tsx",
        "server/.env.example",
    ):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "onrender.com" not in text, relative

    env = (REPO_ROOT / "client" / ".env").read_text(encoding="utf-8")
    assert "VITE_API_URL=/api/v1" in env


def test_cookie_host_only(client, widget_token, monkeypatch):
    """Set-Cookie is host-only, HttpOnly, Secure and SameSite=Lax."""
    monkeypatch.setattr(settings, "WIDGET_COOKIE_SECURE", True)
    monkeypatch.setattr(settings, "WIDGET_COOKIE_SAMESITE", "lax")

    resp = client.get(
        "/api/v1/auth/telegram-widget-verify",
        params=widget_token,
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text

    cookie_header = resp.headers.get("set-cookie", "")
    assert settings.SESSION_COOKIE_NAME in cookie_header
    assert "Domain=" not in cookie_header  # host-only: no explicit Domain
    assert "Path=/" in cookie_header
    assert "samesite=lax" in cookie_header.lower()
    assert "Secure" in cookie_header
    assert "httponly" in cookie_header.lower()


def test_mobile_login_flow(client, widget_token, monkeypatch):
    """widget -> verify -> 302 /dashboard -> authenticated GET /dashboard."""
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "WIDGET_COOKIE_SECURE", False)
    monkeypatch.setattr(settings, "WIDGET_COOKIE_SAMESITE", "lax")

    verify = client.get(
        "/api/v1/auth/telegram-widget-verify",
        params=widget_token,
        follow_redirects=False,
    )
    assert verify.status_code == 302, verify.text
    location = verify.headers["location"]
    assert location.endswith("/dashboard")
    assert location.startswith("https://quanview.dinacreator.space")

    # The cookie from the same-origin 302 is sent back on the SPA route.
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    assert "/login" not in str(dashboard.json())

    session = client.get("/api/v1/auth/me")
    assert session.status_code == 200, session.text
    assert session.json()["authenticated"] is True

    # Guard still works without the cookie (no silent auth bypass).
    client.cookies.clear()
    assert client.get("/dashboard").status_code == 401
