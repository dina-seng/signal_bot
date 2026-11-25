"""Same-origin Telegram login regression tests (JWT transport).

The widget callback and API base stay on the frontend origin, and the session
travels as a JWT in localStorage + Authorization header instead of a cookie
that mobile ITP/STP drops on cross-site redirects.
"""

import hashlib
import hmac
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.core.config import settings
from app.core.security import decode_session_token

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


def _jwt_from_redirect(resp) -> str:
    location = urlparse(resp.headers["location"])
    assert location.path == "/auth/callback"
    assert location.scheme == "https"
    assert location.netloc == "quanview.dinacreator.space"
    return parse_qs(location.query)["token"][0]


def test_frontend_uses_localstorage_bearer_token():
    """The SPA stores the JWT in localStorage and sends it as a Bearer header."""
    def source(relative: str) -> str:
        return (REPO_ROOT / relative).read_text(encoding="utf-8")

    token_module = source("client/src/services/authToken.ts")
    assert "'quantview_auth_token'" in token_module
    assert "localStorage" in token_module

    api = source("client/src/services/api.ts")
    assert "credentials: 'include'" not in api
    assert "Authorization: `Bearer ${token}`" in api
    assert "getAuthToken()" in api

    callback = source("client/src/pages/AuthCallback.tsx")
    assert "setAuthToken(jwt)" in callback
    assert "window.history.replaceState" in callback
    assert "navigate('/dashboard'" in callback

    auth_context = source("client/src/contexts/AuthContext.tsx")
    assert "getAuthToken()" in auth_context
    assert "clearAuthToken()" in auth_context

    app = source("client/src/App.tsx")
    assert "<Navigate to=\"/login\" replace />" in app


def test_widget_verify_uses_jwt_not_cookie(client, widget_token):
    """Verify 302s to the SPA callback with a JWT and sets no cookie at all."""
    resp = client.get(
        "/api/v1/auth/telegram-widget-verify",
        params=widget_token,
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    assert "set-cookie" not in resp.headers

    jwt = _jwt_from_redirect(resp)
    claims = decode_session_token(jwt)
    assert claims is not None
    assert claims["sub"]


def test_mobile_login_flow(client, widget_token, monkeypatch):
    """widget -> 302 /auth/callback?token -> Bearer JWT -> dashboard 200."""
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)

    verify = client.get(
        "/api/v1/auth/telegram-widget-verify",
        params=widget_token,
        follow_redirects=False,
    )
    assert verify.status_code == 302, verify.text
    jwt = _jwt_from_redirect(verify)

    # The SPA stores the JWT in localStorage and sends it on every API call.
    auth_headers = {"Authorization": f"Bearer {jwt}"}
    session = client.get("/api/v1/auth/me", headers=auth_headers)
    assert session.status_code == 200, session.text
    assert session.json()["authenticated"] is True

    dashboard = client.get("/dashboard", headers=auth_headers)
    assert dashboard.status_code == 200, dashboard.text
    assert "/login" not in str(dashboard.json())

    # Guard still rejects a plain browser navigation without a Bearer header.
    assert client.get("/dashboard").status_code == 401
