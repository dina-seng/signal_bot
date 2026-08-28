"""Pydantic schemas for Telegram Bot, Notifications, and Automated Scanner."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class TelegramMessageRequest(BaseModel):
    """Payload for sending a custom message to Telegram."""
    text: str = Field(..., description="Message text content formatted in Markdown or HTML")
    chat_id: Optional[str] = Field(default=None, description="Target Telegram Chat ID (defaults to config)")
    parse_mode: str = Field(default="Markdown", description="Formatting mode: Markdown or HTML")
    disable_web_page_preview: bool = Field(default=True)


class TelegramMessageResponse(BaseModel):
    """Response returned after attempting to send a Telegram message."""
    success: bool
    message_id: Optional[int] = None
    chat_id: Optional[str] = None
    text_sent: str
    sent_at: datetime
    error: Optional[str] = None


class TelegramCommandRequest(BaseModel):
    """Payload for executing an interactive Telegram bot command."""
    command: str = Field(..., description="Command string, e.g. /scan, /signal EUR/USD, /news, /account, /help")
    chat_id: Optional[str] = None
    user_id: Optional[int] = None
    user_name: Optional[str] = None


class TelegramCommandResponse(BaseModel):
    """Response after executing an interactive Telegram command."""
    command: str
    reply_text: str
    handled_successfully: bool
    chat_id: Optional[str] = None


class TelegramWebhookUpdate(BaseModel):
    """Incoming Telegram Webhook payload structure."""
    update_id: int
    message: Optional[Dict[str, Any]] = None
    channel_post: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="ignore")


class TelegramBotStatusResponse(BaseModel):
    """Status of Telegram Bot connection and configuration."""
    is_configured: bool
    bot_token_present: bool
    chat_id_present: bool
    mode: str = Field(..., description="'LIVE' if credentials are set, 'MOCK' otherwise")
    total_messages_sent: int = 0
    last_message_at: Optional[datetime] = None


class ScannerTriggerResponse(BaseModel):
    """Response returned after triggering a market scan."""
    timestamp: datetime
    symbols_scanned: List[str]
    timeframes_scanned: List[str]
    signals_found_count: int
    signals_broadcast_count: int
    paper_trades_opened_count: int
    positions_synced_count: int
    execution_time_seconds: float
    summary: str


class ScannerStatusResponse(BaseModel):
    """Status of the automated background market scanner."""
    is_enabled: bool
    interval_minutes: int
    scanned_symbols: List[str]
    scanned_timeframes: List[str]
    auto_paper_trade: bool
    is_running: bool = False
    last_scan_at: Optional[datetime] = None
    next_scan_at: Optional[datetime] = None
    last_scan_signals_count: int = 0
    total_scans_completed: int = 0
