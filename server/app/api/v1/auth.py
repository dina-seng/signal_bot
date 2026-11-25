"""Telegram magic-link authentication endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.core.security import create_session_token, decode_session_token
from app.schemas.auth import (
    LoginLinkRequest,
    LoginLinkResponse,
    SessionResponse,
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
