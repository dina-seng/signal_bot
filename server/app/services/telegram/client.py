"""Telegram Bot Client supporting live Async API and Mock fallback."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
import httpx

from app.core.config import settings
from app.core.logging import logger
from app.schemas.telegram import TelegramBotStatusResponse, TelegramMessageResponse


class BaseTelegramClient:
    """Abstract interface for Telegram client operations."""

    async def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
        signal_id: Optional[Union[int, str]] = None,
    ) -> TelegramMessageResponse:
        raise NotImplementedError

    def get_status(self) -> TelegramBotStatusResponse:
        raise NotImplementedError


class MockTelegramClient(BaseTelegramClient):
    """Mock Telegram client for local testing and simulation without real bot tokens."""

    def __init__(self):
        self.sent_messages: List[Dict[str, Any]] = []
        self._message_counter = 1000

    async def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
        signal_id: Optional[Union[int, str]] = None,
    ) -> TelegramMessageResponse:
        now = datetime.now(timezone.utc)
        self._message_counter += 1
        target_chat = chat_id or settings.TELEGRAM_CHAT_ID or "MOCK_CHAT_ID"

        msg_record = {
            "message_id": self._message_counter,
            "signal_id": signal_id,
            "chat_id": target_chat,
            "text": text,
            "parse_mode": parse_mode,
            "sent_at": now,
        }
        self.sent_messages.append(msg_record)

        logger.info(
            f"[MOCK TELEGRAM] Sent to chat {target_chat} (ID: {self._message_counter}, signal_id={signal_id}):\n"
            f"{text[:120]}..."
        )

        return TelegramMessageResponse(
            success=True,
            message_id=self._message_counter,
            chat_id=target_chat,
            text_sent=text,
            sent_at=now,
        )

    def get_status(self) -> TelegramBotStatusResponse:
        last_at = self.sent_messages[-1]["sent_at"] if self.sent_messages else None
        return TelegramBotStatusResponse(
            is_configured=True,
            bot_token_present=bool(settings.TELEGRAM_BOT_TOKEN),
            chat_id_present=bool(settings.TELEGRAM_CHAT_ID),
            mode="MOCK",
            total_messages_sent=len(self.sent_messages),
            last_message_at=last_at,
        )


class TelegramClient(BaseTelegramClient):
    """Live Telegram Bot API client using httpx."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        default_chat_id: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.default_chat_id = default_chat_id or settings.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else None
        self.messages_sent_count = 0
        self.last_sent_at: Optional[datetime] = None
        self._http_client = http_client  # Injected shared client; falls back to per-request if None

    async def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
        signal_id: Optional[Union[int, str]] = None,
    ) -> TelegramMessageResponse:
        now = datetime.now(timezone.utc)
        target_chat = chat_id or self.default_chat_id

        if not self.bot_token or not target_chat:
            logger.warning("Telegram Bot Token or Chat ID not configured. Falling back to console broadcast.")
            return TelegramMessageResponse(
                success=True,
                message_id=0,
                chat_id=target_chat or "UNCONFIGURED",
                text_sent=text,
                sent_at=now,
                error="Bot token or chat ID not set (Simulated dispatch).",
            )

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }

        max_retries = 3
        backoff = 1.0

        for attempt in range(max_retries):
            try:
                if self._http_client:
                    resp = await self._http_client.post(url, json=payload)
                else:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.post(url, json=payload)

                if resp.status_code == 200:
                    data = resp.json()
                    msg_id = data.get("result", {}).get("message_id", 0)
                    self.messages_sent_count += 1
                    self.last_sent_at = now
                    logger.info(
                        f"Telegram message #{msg_id} (signal_id={signal_id}) sent successfully to chat {target_chat}."
                    )
                    return TelegramMessageResponse(
                        success=True,
                        message_id=msg_id,
                        chat_id=target_chat,
                        text_sent=text,
                        sent_at=now,
                    )
                elif resp.status_code == 429:
                    # Rate limited: read retry_after and backoff
                    retry_after = 1.0
                    try:
                        retry_after = float(resp.json().get("parameters", {}).get("retry_after", 1.0))
                    except Exception:
                        pass
                    retry_wait = min(10.0, max(1.0, retry_after))
                    logger.warning(
                        f"Telegram 429 Too Many Requests for chat {target_chat} (signal_id={signal_id}). "
                        f"Backing off for {retry_wait:.1f}s (attempt {attempt + 1}/{max_retries})..."
                    )
                    await asyncio.sleep(retry_wait)
                    continue
                else:
                    err_msg = f"Telegram API error {resp.status_code}: {resp.text}"
                    logger.error(f"{err_msg} (signal_id={signal_id})")
                    return TelegramMessageResponse(
                        success=False,
                        chat_id=target_chat,
                        text_sent=text,
                        sent_at=now,
                        error=err_msg,
                    )
            except (httpx.TimeoutException, httpx.NetworkError) as transient_err:
                logger.warning(
                    f"Transient network error sending Telegram message (signal_id={signal_id}): {transient_err}. "
                    f"Retrying in {backoff}s (attempt {attempt + 1}/{max_retries})..."
                )
                await asyncio.sleep(backoff)
                backoff *= 2
            except Exception as e:
                err_msg = f"Failed to send Telegram message: {str(e)}"
                logger.error(f"{err_msg} (signal_id={signal_id})")
                return TelegramMessageResponse(
                    success=False,
                    chat_id=target_chat,
                    text_sent=text,
                    sent_at=now,
                    error=err_msg,
                )

        final_err = f"Failed to deliver Telegram message after {max_retries} retries."
        logger.error(f"{final_err} (signal_id={signal_id})")
        return TelegramMessageResponse(
            success=False,
            chat_id=target_chat,
            text_sent=text,
            sent_at=now,
            error=final_err,
        )

    def get_status(self) -> TelegramBotStatusResponse:
        is_conf = bool(self.bot_token and self.default_chat_id)
        return TelegramBotStatusResponse(
            is_configured=is_conf,
            bot_token_present=bool(self.bot_token),
            chat_id_present=bool(self.default_chat_id),
            mode="LIVE" if is_conf else "UNCONFIGURED",
            total_messages_sent=self.messages_sent_count,
            last_message_at=self.last_sent_at,
        )


def get_telegram_client() -> BaseTelegramClient:
    """Factory helper returning TelegramClient if configured, else MockTelegramClient."""
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        return TelegramClient()
    return MockTelegramClient()
