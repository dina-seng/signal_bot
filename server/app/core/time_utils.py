"""Timezone conversion and formatting utilities for presentation layers.

All backend calculations, market data ingestion, candle storage, news filters,
and strategy evaluations strictly use UTC. This module provides presentation-level
formatting to display timestamps in the user's configured local timezone.
"""

from datetime import datetime, timezone
from typing import Optional, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings
from app.core.logging import logger


def get_user_timezone() -> ZoneInfo:
    """Retrieve the configured user timezone as a ZoneInfo instance.
    
    Defaults to UTC if the configured string is missing or invalid.
    """
    tz_str = getattr(settings, "USER_TIMEZONE", "UTC") or "UTC"
    try:
        return ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, Exception) as err:
        logger.warning(
            f"Invalid USER_TIMEZONE '{tz_str}': {err}. Falling back to UTC."
        )
        return ZoneInfo("UTC")


def format_local_time(
    utc_dt: Optional[datetime],
    tz: Optional[Union[str, ZoneInfo]] = None,
    fmt: str = "%Y-%m-%d %H:%M:%S %Z",
) -> str:
    """Converts a UTC datetime to the user's local timezone formatted string.

    Args:
        utc_dt: The input datetime. If timezone-naive, assumed to be in UTC.
        tz: Optional override timezone (IANA string or ZoneInfo instance).
            Defaults to settings.USER_TIMEZONE.
        fmt: strftime format string. Defaults to "%Y-%m-%d %H:%M:%S %Z".

    Returns:
        Formatted local time string (e.g. "2026-09-24 15:30:00 +07" or "2026-09-24 08:30:00 UTC").
    """
    if utc_dt is None:
        return "N/A"

    # If the datetime is naive (no timezone info), assume it is UTC
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)

    # Determine target timezone
    if tz is None:
        target_tz = get_user_timezone()
    elif isinstance(tz, str):
        try:
            target_tz = ZoneInfo(tz)
        except (ZoneInfoNotFoundError, Exception) as err:
            logger.warning(f"Invalid timezone override '{tz}': {err}. Falling back to UTC.")
            target_tz = ZoneInfo("UTC")
    elif isinstance(tz, ZoneInfo):
        target_tz = tz
    else:
        target_tz = ZoneInfo("UTC")

    # Convert to target local timezone
    local_dt = utc_dt.astimezone(target_tz)

    return local_dt.strftime(fmt)


__all__ = ["format_local_time", "get_user_timezone"]