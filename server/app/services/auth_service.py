"""Telegram magic-link authentication service."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.core.security import generate_login_token, hash_login_token
from app.models.user import LoginToken, User


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    """Creates short-lived login links and exchanges them for dashboard users."""

    def create_login_link(
        self,
        db: Session,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
    ) -> Tuple[str, int]:
        token = generate_login_token()
        ttl = settings.LOGIN_LINK_TTL_SECONDS
        db.add(
            LoginToken(
                token_hash=hash_login_token(token),
                telegram_id=int(telegram_id),
                username=username,
                first_name=first_name,
                expires_at=_now_utc() + timedelta(seconds=ttl),
            )
        )
        db.commit()
        base = settings.MAGIC_LINK_BASE_URL.rstrip("/")
        return f"{base}/auth/callback?token={token}", ttl

    def verify_login_token(self, db: Session, token: str) -> User:
        record = db.scalars(
            select(LoginToken).where(
                LoginToken.token_hash == hash_login_token(token),
                LoginToken.used_at.is_(None),
            )
        ).first()
        if record is None:
            raise ValueError("Invalid or already-used login link.")

        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= _now_utc():
            raise ValueError("Login link has expired. Send /login again.")

        record.used_at = _now_utc()
        user = db.scalars(
            select(User).where(User.telegram_id == record.telegram_id)
        ).first()
        if user is None:
            user = User(
                id=uuid.uuid4(),
                telegram_id=record.telegram_id,
                username=record.username,
                first_name=record.first_name,
                is_admin=settings.ADMIN_TELEGRAM_ID == record.telegram_id,
            )
            db.add(user)
            logger.info("Created dashboard user for Telegram id %s", record.telegram_id)
        else:
            if record.username:
                user.username = record.username
            if record.first_name:
                user.first_name = record.first_name
        db.commit()
        db.refresh(user)
        return user

    def get_or_create_widget_user(
        self,
        db: Session,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
    ) -> User:
        """Find or create a user verified by the official Telegram widget."""
        user = db.scalars(
            select(User).where(User.telegram_id == telegram_id)
        ).first()
        is_admin = settings.ADMIN_TELEGRAM_ID == telegram_id
        if user is None:
            user = User(
                id=uuid.uuid4(),
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                is_admin=is_admin,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info("Created widget-authenticated user for Telegram id %s", telegram_id)
            return user

        changed = False
        if username and user.username != username:
            user.username = username
            changed = True
        if first_name and user.first_name != first_name:
            user.first_name = first_name
            changed = True
        if is_admin and not user.is_admin:
            user.is_admin = True
            changed = True
        if changed:
            db.commit()
            db.refresh(user)
        return user

    @staticmethod
    def get_user(db: Session, user_id: str) -> Optional[User]:
        try:
            return db.scalars(select(User).where(User.id == uuid.UUID(str(user_id)))).first()
        except (ValueError, TypeError):
            return None
