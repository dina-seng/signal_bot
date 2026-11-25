"""Telegram magic-link and official Login Widget authentication endpoints."""

import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.core.logging import logger
from app.core.security import (
    create_session_token,
    decode_session_token,
    telegram_widget_computed_hash,
    telegram_widget_data_check_string,
    verify_telegram_widget_signature,
)
from app.schemas.auth import (
    LoginLinkRequest,
    LoginLinkResponse,
    SessionResponse,
    TelegramWidgetPayload,
    UserResponse,
    VerifyTokenRequest,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _set_session_cookie(
    response: Response,
    token: str,
    max_age: int,
    *,
    secure: bool,
    samesite: str,
) -> None:
    """Issue a HOST-ONLY session cookie for the same-origin /api proxy.

    Deliberately no `domain=` argument: the browser attaches the cookie to
    whatever host it sees (quanview.dinacreator.space), never to onrender.com.
    """
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )


@router.post("/generate-login-link", response_model=LoginLinkResponse)
def generate_login_link(
    payload: LoginLinkRequest,
    db: Session = Depends(get_db),
):
    """Called by the Telegram /login command; returns a short-lived magic link."""
    url, ttl = AuthService().create_login_link(
        db,
        payload.telegram_id,
        username=payload.username,
        first_name=payload.first_name,
    )
    return LoginLinkResponse(login_url=url, expires_in=ttl)


@router.post("/verify", response_model=SessionResponse)
def verify_login_token(
    payload: VerifyTokenRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Exchange a magic-link token for an HTTP-only signed session cookie."""
    try:
        user = AuthService().verify_login_token(db, payload.token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _set_session_cookie(
        response,
        create_session_token(str(user.id), bool(user.is_admin)),
        settings.SESSION_TTL_SECONDS,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )
    return SessionResponse(authenticated=True, user=UserResponse.model_validate(user))


def _widget_redirect(data: Dict[str, Any], received_hash: str, db: Session, request: Request | None = None) -> RedirectResponse:
    """Validate Telegram's signed payload and issue a 30-day session cookie."""
    # ── Temporary proxy-debug log (remove once login is confirmed working) ────
    if request is not None:
        fwd_proto = request.headers.get("x-forwarded-proto", "<not set>")
        fwd_host  = request.headers.get("x-forwarded-host", "<not set>")
        host      = request.headers.get("host", "<not set>")
        scheme    = request.url.scheme          # reflects ProxyHeadersMiddleware
        logger.info(
            "[AUTH_PROXY_DEBUG] scheme=%s host=%s X-Forwarded-Proto=%s X-Forwarded-Host=%s",
            scheme, host, fwd_proto, fwd_host,
        )
        logger.info(
            "[AUTH_PROXY_DEBUG] will set cookie: name=%s secure=%s samesite=%s → redirect=%s",
            settings.SESSION_COOKIE_NAME,
            settings.WIDGET_COOKIE_SECURE,
            settings.WIDGET_COOKIE_SAMESITE,
            settings.DASHBOARD_REDIRECT_URL,
        )

    if not verify_telegram_widget_signature(data, received_hash):
        if settings.AUTH_DEBUG:
            logger.debug(
                "[AUTH_DEBUG] widget data_check_string=%r computed_hash=%s",
                telegram_widget_data_check_string(data),
                telegram_widget_computed_hash(data),
            )
        logger.warning(
            "Rejected Telegram widget login: invalid hash for id %s", data.get("id")
        )
        raise HTTPException(status_code=401, detail="Invalid Telegram widget signature")

    try:
        telegram_id = int(data["id"])
        auth_date = int(data["auth_date"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid Telegram widget payload")

    # One-directional: only stale payloads are rejected; future clock skew is OK.
    age_seconds = int(time.time()) - auth_date
    if age_seconds > settings.WIDGET_AUTH_MAX_AGE_SECONDS:
        logger.warning("Rejected Telegram widget login: auth_date is %ss old", age_seconds)
        raise HTTPException(status_code=401, detail="Telegram widget payload expired")

    user = AuthService().get_or_create_widget_user(
        db,
        telegram_id,
        username=data.get("username"),
        first_name=data.get("first_name"),
    )
    # Same-origin /dashboard: the widget posts to quanview.dinacreator.space
    # (Netlify proxies /api), so the host-only cookie survives the redirect.
    # DASHBOARD_REDIRECT_URL must be an absolute URL to the frontend domain —
    # never a relative path, which would redirect to the Render backend domain.
    redirect_url = settings.DASHBOARD_REDIRECT_URL
    logger.info("[AUTH] Redirecting authenticated user to %s", redirect_url)
    redirect = RedirectResponse(url=redirect_url, status_code=302)
    _set_session_cookie(
        redirect,
        create_session_token(str(user.id), bool(user.is_admin)),
        settings.WIDGET_SESSION_TTL_SECONDS,
        secure=settings.WIDGET_COOKIE_SECURE,
        samesite=settings.WIDGET_COOKIE_SAMESITE,
    )
    return redirect


@router.post("/telegram-widget-verify")
def telegram_widget_verify_post(
    payload: TelegramWidgetPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    """JSON fallback for the Telegram Login Widget callback."""
    return _widget_redirect(payload.signing_data(), payload.hash, db, request)


@router.get("/telegram-widget-verify")
def telegram_widget_verify_get(request: Request, db: Session = Depends(get_db)):
    """Primary callback: widget navigates here with decoded query parameters.

    We read raw query params so extra signed fields (e.g. last_name) are also
    included verbatim in the data-check-string.
    """
    data = {
        key: value
        for key, value in request.query_params.items()
        if key != "hash"
    }
    return _widget_redirect(data, request.query_params.get("hash", ""), db, request)


@router.get("/me", response_model=SessionResponse)
def current_session(request: Request, db: Session = Depends(get_db)):
    """Return the current user (or authenticated=False) for the SPA bootstrap."""
    claims = decode_session_token(request.cookies.get(settings.SESSION_COOKIE_NAME))
    if claims is None:
        return SessionResponse(authenticated=False, user=None)
    user = AuthService.get_user(db, claims["sub"])
    if user is None:
        return SessionResponse(authenticated=False, user=None)
    return SessionResponse(authenticated=True, user=UserResponse.model_validate(user))


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    return {"success": True}
