"""Telegram magic-link authentication schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginLinkRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram user id from the /login command")
    username: Optional[str] = None
    first_name: Optional[str] = None


class LoginLinkResponse(BaseModel):
    login_url: str
    expires_in: int


class VerifyTokenRequest(BaseModel):
    token: str = Field(..., min_length=10)


class UserResponse(BaseModel):
    id: UUID
    telegram_id: Optional[int] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    is_admin: bool = False
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SessionResponse(BaseModel):
    authenticated: bool
    user: Optional[UserResponse] = None
