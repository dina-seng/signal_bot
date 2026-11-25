"""Telegram magic-link and official Login Widget authentication endpoints."""

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.core.logging import logger
from app.core.security import (
    create_session_token,
    decode_session_token,
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

    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=create_session_token(str(user.id), bool(user.is_admin)),
        max_age=settings.SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        path="/",
    )
    return SessionResponse(authenticated=True, user=UserResponse.model_validate(user))


def _widget_redirect(payload: TelegramWidgetPayload, db: Session) -> RedirectResponse:
    """Validate Telegram's signed payload and issue a 30-day session cookie."""
    if not verify_telegram_widget_signature(payload.signing_data(), payload.hash):
        logger.warning("Rejected Telegram widget login: invalid hash for id %s", payload.id)
        raise HTTPException(status_code=401, detail="Invalid Telegram widget signature")

    age_seconds = int(time.time()) - payload.auth_date
    if age_seconds > settings.WIDGET_AUTH_MAX_AGE_SECONDS:
        logger.warning("Rejected Telegram widget login: auth_date is %ss old", age_seconds)
        raise HTTPException(status_code=401, detail="Telegram widget payload expired")

    user = AuthService().get_or_create_widget_user(
        db, payload.id, username=payload.username, first_name=payload.first_name
    )
    redirect = RedirectResponse(url=settings.DASHBOARD_REDIRECT_URL, status_code=302)
    redirect.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=create_session_token(str(user.id), bool(user.is_admin)),
        max_age=settings.WIDGET_SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.WIDGET_COOKIE_SECURE,
        samesite=settings.WIDGET_COOKIE_SAMESITE,
        path="/",
    )
    return redirect


@router.post("/telegram-widget-verify")
def telegram_widget_verify_post(
    payload: TelegramWidgetPayload,
    db: Session = Depends(get_db),
):
    """JSON fallback for the Telegram Login Widget callback."""
    return _widget_redirect(payload, db)


@router.get("/telegram-widget-verify")
def telegram_widget_verify_get(
    id: int,
    auth_date: int,
    hash: str,
    first_name: str = "",
    username: Optional[str] = None,
    photo_url: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Primary callback: the widget navigates here with query parameters."""
    payload = TelegramWidgetPayload(
        id=id,
        first_name=first_name,
        username=username,
        photo_url=photo_url,
        auth_date=auth_date,
        hash=hash,
    )
    return _widget_redirect(payload, db)


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
