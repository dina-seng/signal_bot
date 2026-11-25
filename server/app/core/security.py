"""Minimal, dependency-free HS256 JWT + login-token helpers.

The project has no PyJWT dependency; this implements the standard compact JWT
encoding with the stdlib only. Signing uses HMAC-SHA256 and all comparisons are
constant-time.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, Optional

from app.core.config import settings


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def create_session_token(user_id: str, is_admin: bool) -> str:
    now = int(time.time())
    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "admin": bool(is_admin),
        "iat": now,
        "exp": now + settings.SESSION_TTL_SECONDS,
    }
    header = _b64url_encode(b'{"alg":"HS256","typ":"JWT"}')
    body = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{header}.{body}".encode("ascii")
    signature = _b64url_encode(
        hmac.new(settings.JWT_SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    )
    return f"{header}.{body}.{signature}"


def decode_session_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return verified claims, or None for any malformed/expired token."""
    if not token:
        return None
    try:
        header, body, signature = token.split(".")
        expected = _b64url_encode(
            hmac.new(
                settings.JWT_SECRET_KEY.encode("utf-8"),
                f"{header}.{body}".encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(signature, expected):
            return None
        claims = json.loads(_b64url_decode(body))
        if int(claims.get("exp", 0)) <= int(time.time()):
            return None
        if not claims.get("sub"):
            return None
        return claims
    except Exception:
        return None


def telegram_widget_data_check_string(payload: Dict[str, Any]) -> str:
    """Alphabetically sorted ``key=value`` lines, excluding hash (Login Widget)."""
    return "\n".join(
        f"{key}={value}"
        for key, value in sorted(payload.items())
        if key != "hash" and value is not None
    )


def telegram_widget_computed_hash(payload: Dict[str, Any]) -> str:
    """Official Login Widget HMAC: SHA256(bot_token).digest() is the key."""
    token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
    secret_key = hashlib.sha256(token.encode("utf-8")).digest()
    data_check_string = telegram_widget_data_check_string(payload)
    return hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_telegram_widget_signature(payload: Dict[str, Any], provided_hash: str) -> bool:
    """Constant-time verification against Telegram's Login Widget signature."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return False
    computed = telegram_widget_computed_hash(payload)
    return hmac.compare_digest(computed, provided_hash or "")


def generate_login_token() -> str:
    """High-entropy, URL-safe opaque token for the Telegram magic link."""
    return secrets.token_urlsafe(32)


def hash_login_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
