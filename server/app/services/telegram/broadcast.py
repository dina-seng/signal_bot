"""Multi-user Telegram fan-out with rate limiting and blocked-user cleanup."""

import asyncio
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models.user import User
from app.schemas.telegram import TelegramMessageResponse


def _is_blocked(error: Optional[str]) -> bool:
    message = (error or "").lower()
    return (
        "403" in message
        or "blocked" in message
        or "chat not found" in message
        or "user is deactivated" in message
    )


async def broadcast_to_subscribers(
    db: Session,
    client,
    *,
    text: str,
    parse_mode: str = "HTML",
    signal_id: Optional[Any] = None,
    reply_markup: Optional[Dict[str, Any]] = None,
) -> List[TelegramMessageResponse]:
    """Send one logical message to every registered Telegram user.

    With no registered subscribers we fall back to the legacy single configured
    chat so existing deployments and tests keep working unchanged.
    """
    telegram_ids = [
        row[0]
        for row in db.execute(
            select(User.telegram_id).where(User.telegram_id.isnot(None))
        ).all()
    ]
    targets = [str(chat_id) for chat_id in telegram_ids]
    if not targets:
        targets = [settings.TELEGRAM_CHAT_ID] if settings.TELEGRAM_CHAT_ID else [None]

    results: List[TelegramMessageResponse] = []
    for index, chat_id in enumerate(targets):
        if index:
            await asyncio.sleep(settings.TELEGRAM_BROADCAST_DELAY_SECONDS)
        try:
            result = await client.send_message(
                text=text,
                chat_id=chat_id,
                parse_mode=parse_mode,
                signal_id=signal_id,
                reply_markup=reply_markup,
            )
        except Exception as exc:
            logger.warning("Telegram broadcast to %s failed: %s", chat_id, exc)
            continue
        results.append(result)

        if not result.success and _is_blocked(result.error):
            logger.warning(
                "Telegram user %s blocked the bot or is unreachable; unsubscribing.", chat_id
            )
            blocked = db.scalars(
                select(User).where(User.telegram_id == chat_id)
            ).first()
            if blocked is not None:
                blocked.telegram_id = None
                db.commit()
    return results
