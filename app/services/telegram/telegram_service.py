"""Unified Telegram and Automated Scanner Orchestration Service."""

from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from app.schemas.telegram import (
    ScannerStatusResponse,
    ScannerTriggerResponse,
    TelegramBotStatusResponse,
    TelegramCommandRequest,
    TelegramCommandResponse,
    TelegramMessageRequest,
    TelegramMessageResponse,
)
from app.services.telegram.client import BaseTelegramClient, get_telegram_client
from app.services.telegram.command_handler import TelegramCommandHandler
from app.services.telegram.message_formatter import TelegramMessageFormatter
from app.services.telegram.scanner import AutomatedMarketScanner


class TelegramBotService:
    """Consolidated facade service for Telegram messaging, interactive command handling, and background scanning."""

    def __init__(
        self,
        client: Optional[BaseTelegramClient] = None,
        command_handler: Optional[TelegramCommandHandler] = None,
        scanner: Optional[AutomatedMarketScanner] = None,
    ):
        self.client = client or get_telegram_client()
        self.formatter = TelegramMessageFormatter()
        self.command_handler = command_handler or TelegramCommandHandler(telegram_client=self.client)
        self.scanner = scanner or AutomatedMarketScanner(telegram_client=self.client)

    async def broadcast_message(self, request: TelegramMessageRequest) -> TelegramMessageResponse:
        """Send a message to Telegram channel/chat."""
        return await self.client.send_message(
            text=request.text,
            chat_id=request.chat_id,
            parse_mode=request.parse_mode,
            disable_web_page_preview=request.disable_web_page_preview,
        )

    async def process_command(self, db: Session, request: TelegramCommandRequest) -> TelegramCommandResponse:
        """Process interactive Telegram bot command."""
        return await self.command_handler.handle_command(db=db, request=request)

    async def trigger_market_scan(
        self,
        db: Session,
        symbols: Optional[List[str]] = None,
        timeframe: str = "1h",
        broadcast_to_telegram: bool = True,
        auto_paper_trade: bool = True,
    ) -> ScannerTriggerResponse:
        """Manually trigger background market scanner cycle."""
        return await self.scanner.run_scan_cycle(
            db=db,
            symbols=symbols,
            timeframe=timeframe,
            broadcast_to_telegram=broadcast_to_telegram,
            auto_paper_trade=auto_paper_trade,
        )

    def get_bot_status(self) -> TelegramBotStatusResponse:
        """Get Telegram bot configuration and connectivity status."""
        return self.client.get_status()

    def get_scanner_status(self) -> ScannerStatusResponse:
        """Get background scanner operational status."""
        return self.scanner.get_status()
