"""Telegram Bot and Background Market Scanner API Endpoints."""

import asyncio
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.config import settings
from app.core.logging import logger
from app.api.deps import get_telegram_bot_service
from app.schemas.telegram import (
    ScannerStatusResponse,
    ScannerTriggerResponse,
    TelegramBotStatusResponse,
    TelegramCommandRequest,
    TelegramCommandResponse,
    TelegramMessageRequest,
    TelegramMessageResponse,
    TelegramWebhookUpdate,
)
from app.services.telegram import TelegramBotService

router = APIRouter(prefix="/telegram", tags=["Telegram Bot & Automated Scanner"])

# Heavy commands that fetch market data and run multi-timeframe analysis
_HEAVY_COMMANDS = {"/scan", "/signal", "/sync"}


async def _run_command_in_background(
    service: TelegramBotService,
    request: TelegramCommandRequest,
) -> None:
    """Execute a heavy command asynchronously in the background with an isolated DB session."""
    db: Session = SessionLocal()
    try:
        await service.command_handler.handle_command(db=db, request=request)
    except Exception as e:
        logger.error(
            f"❌ Background command '{request.command}' failed for chat {request.chat_id}: {e}",
            exc_info=True,
        )
        try:
            await service.client.send_message(
                text=f"❌ Error processing command: {str(e)}",
                chat_id=request.chat_id,
            )
        except Exception:
            pass
    finally:
        db.close()


@router.post("/broadcast", response_model=TelegramMessageResponse)
async def broadcast_telegram_message(
    request: TelegramMessageRequest,
    service: TelegramBotService = Depends(get_telegram_bot_service),
):
    """Broadcast a formatted message or signal alert to the configured Telegram chat/channel."""
    return await service.broadcast_message(request=request)


@router.post("/command", response_model=TelegramCommandResponse)
async def process_telegram_command(
    request: TelegramCommandRequest,
    db: Session = Depends(get_db),
    service: TelegramBotService = Depends(get_telegram_bot_service),
):
    """Process an interactive Telegram command (/scan, /signal, /news, /account, /positions, /help)."""
    return await service.process_command(db=db, request=request)



@router.post("/webhook")
async def telegram_webhook(
    update: TelegramWebhookUpdate,
    background_tasks: BackgroundTasks,
    service: TelegramBotService = Depends(get_telegram_bot_service),
):
    """Webhook endpoint for receiving real-time interactive updates from Telegram servers."""
    logger.info(f"🔔 TELEGRAM WEBHOOK RECEIVED")

    # Handle both Pydantic model and dict cases
    msg = update.message or update.channel_post
    if not msg:
        logger.warning("Webhook received but no message payload found")
        return {"status": "ignored", "reason": "No message payload"}

    # Safely extract data whether msg is a dict or Pydantic model
    if isinstance(msg, dict):
        text = msg.get("text", "")
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        user = msg.get("from", {})
    else:
        # Pydantic model - access attributes directly
        text = getattr(msg, "text", "") or ""
        chat = getattr(msg, "chat", None)
        chat_id = str(getattr(chat, "id", "")) if chat else ""
        user = getattr(msg, "from_user", None) or getattr(msg, "from_", None)

    logger.info(f"📩 Message from chat {chat_id}: {text}")

    if text.startswith("/"):
        cmd_root = text.split()[0].split("@")[0].lower()
        cmd_req = TelegramCommandRequest(
            command=text,
            chat_id=chat_id,
            user_id=getattr(user, "id", None) if user else None,
            user_name=getattr(user, "username", None) if user else None,
        )

        if cmd_root in _HEAVY_COMMANDS:
            # Task 4: Fast instant acknowledgement and non-blocking background dispatch
            if cmd_root == "/scan":
                ack_text = "⚡ Scanning XAU/USD... Please wait while fresh market data is analyzed."
            elif cmd_root == "/sync":
                ack_text = "🔄 Syncing fresh market data for XAU/USD... Please wait."
            else:
                ack_text = "🔄 Processing request... analyzing market data. Please wait."

            if chat_id:
                try:
                    await asyncio.wait_for(
                        service.client.send_message(
                            text=ack_text,
                            chat_id=chat_id,
                        ),
                        timeout=2.0,
                    )
                except Exception as ack_err:
                    logger.warning(f"Could not send acknowledgement message to {chat_id}: {ack_err}")

            # Offload heavy multi-timeframe analysis & DB sync to BackgroundTasks so webhook returns 200 OK instantly
            background_tasks.add_task(_run_command_in_background, service, cmd_req)
            return {"status": "success", "command": cmd_root, "reply": ack_text}

        # Lightweight commands processed inline
        try:
            db: Session = SessionLocal()
            try:
                cmd_res = await service.command_handler.handle_command(db=db, request=cmd_req)
            finally:
                db.close()
            logger.info(f"✅ Command processed: {cmd_res.command}")
            return {"status": "success", "command": cmd_res.command, "reply": cmd_res.reply_text}
        except Exception as e:
            logger.error(f"❌ Error processing command: {e}", exc_info=True)
            try:
                await service.client.send_message(
                    text=f"❌ Error processing command: {str(e)}",
                    chat_id=chat_id,
                )
            except Exception:
                pass
            return {"status": "error", "error": str(e)}

    logger.info(f"📝 Non-command message received from {chat_id}")
    return {"status": "received", "chat_id": chat_id}
@router.get("/status", response_model=TelegramBotStatusResponse)
def get_bot_status(
    service: TelegramBotService = Depends(get_telegram_bot_service),
):
    """Check Telegram bot connectivity status, mode (LIVE or MOCK), and message counts."""
    return service.get_bot_status()


@router.post("/scanner/trigger", response_model=ScannerTriggerResponse)
async def trigger_scanner_cycle(
    timeframe: str = Query("1h", description="Timeframe to scan (e.g. 1h, 15m)"),
    broadcast: bool = Query(True, description="Whether to broadcast newly qualified signals to Telegram"),
    auto_trade: bool = Query(True, description="Whether to auto-open paper positions for qualified signals"),
    db: Session = Depends(get_db),
    service: TelegramBotService = Depends(get_telegram_bot_service),
):
    """Manually trigger an automated market scanner cycle across all supported pairs."""
    return await service.trigger_market_scan(
        db=db,
        symbols=settings.SUPPORTED_SYMBOLS,
        timeframe=timeframe,
        broadcast_to_telegram=broadcast,
        auto_paper_trade=auto_trade,
    )


@router.get("/scanner/status", response_model=ScannerStatusResponse)
def get_scanner_status(
    service: TelegramBotService = Depends(get_telegram_bot_service),
):
    """Retrieve operational status, scan interval, and activity history of the background scanner."""
    return service.get_scanner_status()