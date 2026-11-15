"""Pure, DST-aware market open/closed calendar for Spot Gold (XAU/USD).

Empirical findings from full Twelve Data history (100,408 bars):
- Spot gold markets close Friday at 17:00 America/New_York (21:00 UTC EDT / 22:00 UTC EST).
- Spot gold markets reopen Sunday at 18:00 America/New_York (22:00 UTC EDT / 23:00 UTC EST).
- Closed all of Saturday.
- Daily maintenance break: Monday through Thursday 17:00 to 18:00 America/New_York (21:00-22:00 UTC EDT / 22:00-23:00 UTC EST).
- Twelve Data inserts synthetic placeholder bars with collapsed range (~0.25 USD tick spread) during closed periods.
"""

from datetime import datetime, timezone
from typing import Optional, Sequence, TypeVar, List
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")
UTC_TZ = timezone.utc

T = TypeVar("T")


def is_market_open(ts: Optional[datetime]) -> bool:
    """Check if a bar timestamp falls within active Spot Gold (XAU/USD) market hours.

    Pure, DST-aware function anchored in America/New_York time.

    Trading week rules:
    - Friday: Closes at 17:00 America/New_York. (17:00 <= t < 24:00 is CLOSED)
    - Saturday: Closed all day.
    - Sunday: Opens at 18:00 America/New_York. (00:00 <= t < 18:00 is CLOSED, t >= 18:00 is OPEN)
    - Monday through Thursday: Daily maintenance break from 17:00 to 18:00 America/New_York.
    """
    if ts is None:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC_TZ)

    ny_dt = ts.astimezone(NY_TZ)
    wd = ny_dt.weekday()  # 0=Monday, ..., 6=Sunday
    m_since_midnight = ny_dt.hour * 60 + ny_dt.minute

    # Friday: Market closes at 17:00 NY
    if wd == 4:
        return m_since_midnight < 17 * 60

    # Saturday: Closed all day
    if wd == 5:
        return False

    # Sunday: Market opens at 18:00 NY
    if wd == 6:
        return m_since_midnight >= 18 * 60

    # Monday through Thursday (0, 1, 2, 3):
    # Daily maintenance break from 17:00 to 18:00 NY
    if 17 * 60 <= m_since_midnight < 18 * 60:
        return False

    return True


def filter_open_market_candles(candles: Sequence[T]) -> List[T]:
    """Filter out closed-market and placeholder bars at load time without mutating database."""
    return [c for c in candles if is_market_open(getattr(c, "timestamp", None))]


def is_forex_weekend(ts: Optional[datetime] = None) -> bool:
    """Check if a timestamp falls within the weekend market closure (Fri 17:00 NY to Sun 18:00 NY)."""
    if ts is None:
        ts = datetime.now(UTC_TZ)
    elif ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC_TZ)

    ny_dt = ts.astimezone(NY_TZ)
    wd = ny_dt.weekday()
    m_since_midnight = ny_dt.hour * 60 + ny_dt.minute

    if wd == 4 and m_since_midnight >= 17 * 60:
        return True
    if wd == 5:
        return True
    if wd == 6 and m_since_midnight < 18 * 60:
        return True

    return False
