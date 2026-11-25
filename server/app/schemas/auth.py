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


class TelegramWidgetPayload(BaseModel):
    """Data sent by the official Telegram Login Widget (auth_url redirect)."""

    id: int
    first_name: str = ""
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int
    hash: str

    model_config = ConfigDict(populate_by_name=True)

    def signing_data(self) -> dict:
        return self.model_dump(exclude={"hash"}, exclude_none=True, by_alias=True)


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
    # Session JWT issued by /auth/verify; the SPA stores it in localStorage.
    token: Optional[str] = None
