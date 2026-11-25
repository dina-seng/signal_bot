"""Telegram Bot and Automated Scanner package."""

from app.services.telegram.message_formatter import TelegramMessageFormatter
from app.services.telegram.client import BaseTelegramClient, TelegramClient, MockTelegramClient, get_telegram_client
from app.services.telegram.command_handler import TelegramCommandHandler
from app.services.telegram.scanner import AutomatedMarketScanner
from app.services.telegram.telegram_service import TelegramBotService
from app.services.telegram.broadcast import broadcast_to_subscribers

from app.services.telegram.scheduler import (
    get_scheduler_info,
    get_shared_scanner,
    is_scheduler_running,
    set_shared_scanner,
    start_scanner_scheduler,
    stop_scanner_scheduler,
)

__all__ = [
    "TelegramMessageFormatter",
    "BaseTelegramClient",
    "TelegramClient",
    "MockTelegramClient",
    "get_telegram_client",
    "TelegramCommandHandler",
    "AutomatedMarketScanner",
    "TelegramBotService",
    "broadcast_to_subscribers",
    "start_scanner_scheduler",
    "stop_scanner_scheduler",
    "is_scheduler_running",
    "get_scheduler_info",
    "get_shared_scanner",
    "set_shared_scanner",
]
