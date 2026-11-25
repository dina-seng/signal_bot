"""Regression tests: /auth/me must never return HTML to the client.

Scenario: Netlify proxies /api/* to Render.  When Render is cold-starting or
returning an error page, the proxy can serve an HTML body — which breaks the
client with:

    SyntaxError: Unexpected token '<', "<!doctype..." is not valid JSON

These tests assert:

1. /auth/me always returns Content-Type: application/json (never HTML).
2. A missing / expired cookie returns a valid JSON {"authenticated": false},
   not an HTML 401 page.
3. The same-origin proxy config has the /api/* rule BEFORE the /* SPA rule
   in every netlify.toml (guards against rule-ordering regressions).
4. test_session_check_non_json — documents the expected *client-side* guard
   that must be in api.ts: Content-Type check before .json() call.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Backend endpoint contract ─────────────────────────────────────────────────

def test_auth_me_returns_json_when_unauthenticated(client):
    """GET /auth/me with no cookie must return JSON {authenticated: false}, not HTML."""
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200, resp.text
    content_type = resp.headers.get("content-type", "")
    assert "application/json" in content_type, (
        f"/auth/me returned Content-Type '{content_type}' — "
        "the client would throw SyntaxError parsing this as JSON.\n"
        "Body preview: " + resp.text[:200]
    )
    body = resp.json()
    assert body["authenticated"] is False
    assert body["user"] is None


def test_auth_me_returns_json_when_authenticated(client, test_db_session, monkeypatch):
    """GET /auth/me with a valid session cookie must return JSON {authenticated: true}."""
    import hashlib, hmac, time
    from app.core.config import settings

    BOT_TOKEN = "session-json-test-token"
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setattr(settings, "ADMIN_TELEGRAM_ID", None)
    monkeypatch.setattr(settings, "WIDGET_COOKIE_SECURE", False)
    monkeypatch.setattr(settings, "WIDGET_COOKIE_SAMESITE", "lax")

    values = {
        "id": 999,
        "first_name": "JsonTest",
        "username": "json_test_user",
        "auth_date": int(time.time()),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(values.items()))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()

    # Authenticate via widget to get a session cookie.
    login = client.get(
        "/api/v1/auth/telegram-widget-verify",
        params=values,
        follow_redirects=False,
    )
    assert login.status_code == 302, login.text

    # /auth/me must respond with JSON {authenticated: true}.
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200, me.text
    content_type = me.headers.get("content-type", "")
    assert "application/json" in content_type, (
        f"/auth/me returned Content-Type '{content_type}' after login — "
        "the client would throw SyntaxError.\nBody: " + me.text[:200]
    )
    body = me.json()
    assert body["authenticated"] is True
    assert body["user"] is not None


def test_auth_me_never_returns_html(client):
    """Belt-and-suspenders: confirm /auth/me body does NOT start with HTML doctype."""
    resp = client.get("/api/v1/auth/me")
    text = resp.text.lstrip()
    assert not text.lower().startswith("<!doctype"), (
        "/auth/me returned an HTML body — this causes the client SyntaxError.\n"
        "Body preview: " + text[:300]
    )
    assert not text.startswith("<html"), (
        "/auth/me returned an HTML body.\nBody preview: " + text[:300]
    )


# ── Netlify proxy rule ordering guard ─────────────────────────────────────────

def _check_netlify_toml_rule_order(path: Path) -> None:
    """Assert /api/* redirect appears before /* in the given netlify.toml."""
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    api_index = None
    spa_index = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == 'from = "/api/*"' and api_index is None:
            api_index = i
        if stripped == 'from = "/*"' and spa_index is None:
            spa_index = i

    assert api_index is not None, (
        f"{path}: missing [[redirects]] rule for '/api/*' — "
        "the Netlify proxy to the Render backend is not configured."
    )
    assert spa_index is not None, (
        f"{path}: missing SPA catch-all [[redirects]] rule for '/*'."
    )
    assert api_index < spa_index, (
        f"{path}: '/api/*' rule (line {api_index + 1}) must come BEFORE '/*' rule "
        f"(line {spa_index + 1}). When the SPA rewrite wins, every /api/* request "
        "gets /index.html (HTML) back, causing SyntaxError in the client."
    )

    # Confirm force = true on the /api rule so Netlify doesn't skip it.
    api_block_lines = "\n".join(lines[api_index - 2 : spa_index])
    assert "force = true" in api_block_lines, (
        f"{path}: '/api/*' redirect block must include 'force = true' "
        "otherwise Netlify may serve a cached /index.html for API paths."
    )


def test_netlify_toml_root_proxy_order():
    """Root netlify.toml: /api/* must precede /* and have force=true."""
    toml_path = REPO_ROOT / "netlify.toml"
    if not toml_path.exists():
        pytest.skip("Root netlify.toml not found")
    _check_netlify_toml_rule_order(toml_path)


def test_netlify_toml_client_proxy_order():
    """client/netlify.toml: /api/* must precede /* and have force=true."""
    toml_path = REPO_ROOT / "client" / "netlify.toml"
    if not toml_path.exists():
        pytest.skip("client/netlify.toml not found")
    _check_netlify_toml_rule_order(toml_path)


# ── Client-side guard documentation ───────────────────────────────────────────

def test_session_check_non_json_guard_in_api_ts():
    """api.ts fetchWithTiming must check Content-Type before calling .json().

    This is the client-side guard that prevents:
        SyntaxError: Unexpected token '<', "<!doctype..." is not valid JSON

    When Render is cold-starting or the proxy rule is missing, /api/v1/auth/me
    can return an HTML body (Netlify's index.html or Render's error page).
    Without a Content-Type guard the client calls res.json() on HTML and throws
    an uncaught SyntaxError that crashes React.

    The guard converts the bad response to an ApiError(502) which AuthContext
    catches, logs a warning, and treats as logged-out — redirecting to /login.
    """
    api_ts = (REPO_ROOT / "client" / "src" / "services" / "api.ts").read_text(
        encoding="utf-8"
    )
    # Confirm the content-type guard is present.
    assert "content-type" in api_ts.lower() or "contentType" in api_ts, (
        "api.ts is missing a Content-Type check in fetchWithTiming. "
        "Without it, an HTML response from /auth/me causes "
        "SyntaxError: Unexpected token '<'"
    )
    assert "application/json" in api_ts, (
        "api.ts must check for 'application/json' content-type before calling .json(). "
        "HTML responses must throw ApiError, not propagate as SyntaxError."
    )
    assert "502" in api_ts, (
        "api.ts must throw ApiError(502) when Content-Type is not JSON — "
        "AuthContext catches this and treats it as logged-out."
    )

    # Confirm AuthContext catches the proxy error gracefully.
    auth_ctx = (
        REPO_ROOT / "client" / "src" / "contexts" / "AuthContext.tsx"
    ).read_text(encoding="utf-8")
    assert "502" in auth_ctx or "proxy" in auth_ctx.lower(), (
        "AuthContext.tsx should log a warning for 502 proxy errors. "
        "Without this, the user sees a blank screen instead of being "
        "redirected to /login."
    )
