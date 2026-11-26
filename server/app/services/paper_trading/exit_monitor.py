"""Fast app-side TP/SL monitor driven by live quote ticks.

There is no external broker integration in this project: fills are simulated
locally. This monitor is the fallback that makes exits happen on price ticks
instead of only on the 15-minute scanner cycle.
"""

import asyncio
import re
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import logger
from app.models.paper import PaperTrade
from app.services.market_data import get_market_data_provider
from app.services.market_data.cache import CachedMarketDataProvider
from app.services.paper_trading import PaperTradingService

_EXIT_EVENT_KEYS = ("TP1", "TP2", "SL_HIT", "BREAK_EVEN")


async def _notify_exit(db, event: str) -> None:
    """Send the Telegram close alert for one lifecycle event."""
    match = re.search(r"Position #(\d+)", event)
    if not match:
        return
    try:
        from app.services.telegram.scheduler import get_shared_scanner

        trade = db.get(PaperTrade, int(match.group(1)))
        if trade is not None:
            await get_shared_scanner()._send_trade_exit_alert(trade, event, db=db)
    except Exception as exc:
        logger.warning("[exit-monitor] Telegram close alert failed: %s", exc)


async def _monitor_loop(provider, service: PaperTradingService) -> None:
    symbol = settings.POSITION_MONITOR_SYMBOL
    interval = settings.POSITION_MONITOR_INTERVAL_SECONDS
    logger.info(
        "[exit-monitor] started: symbol=%s interval=%.2fs", symbol, interval
    )
    while True:
        tick_received = datetime.now(timezone.utc)
        db = SessionLocal()
        try:
            # _resolve_quote is cached: even at 0.5s this does not hammer the
            # upstream provider (quote cache TTL is presence-gated in seconds).
            from app.api.v1.market import _resolve_quote

            quote = await _resolve_quote(symbol, provider, db=db)
            if quote is not None and float(quote.price) > 0:
                report = service.sync_prices(
                    db=db,
                    symbol_prices={quote.symbol: float(quote.price)},
                )
                for event in report.events:
                    if any(key in event for key in _EXIT_EVENT_KEYS):
                        logger.info(
                            "EXIT_LATENCY tick_received=%s condition_met=%s event=%s",
                            tick_received.isoformat(),
                            datetime.now(timezone.utc).isoformat(),
                            event,
                        )
                        await _notify_exit(db, event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("[exit-monitor] tick failed: %s", exc)
        finally:
            db.close()
        await asyncio.sleep(interval)


async def start_exit_monitor(http_client=None) -> Optional[asyncio.Task]:
    """Launch the background exit monitor; returns None when disabled."""
    if not settings.POSITION_MONITOR_ENABLED:
        return None
    provider = CachedMarketDataProvider(
        get_market_data_provider(settings.MARKET_DATA_PROVIDER, http_client=http_client)
    )
    return asyncio.create_task(
        _monitor_loop(provider, PaperTradingService()),
        name="position-exit-monitor",
    )


async def stop_exit_monitor(task: Optional[asyncio.Task]) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
