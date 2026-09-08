"""Market data freshness verification, latest closed candle selection, and timestamp utilities."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Union

from app.core.logging import logger
from app.schemas.candle import CandleBase


TIMEFRAME_DELTAS: Dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
}

# Standard max staleness thresholds during open market hours
DEFAULT_STALENESS_THRESHOLDS: Dict[str, timedelta] = {
    "1m": timedelta(minutes=15),
    "5m": timedelta(minutes=30),
    "15m": timedelta(hours=1),
    "30m": timedelta(hours=2),
    "1h": timedelta(hours=4),
    "4h": timedelta(hours=16),
    "1d": timedelta(hours=48),
    "1w": timedelta(days=14),
}


def get_timeframe_delta(timeframe: str) -> timedelta:
    """Retrieve timedelta interval for standard timeframe string."""
    tf = timeframe.lower().strip()
    delta = TIMEFRAME_DELTAS.get(tf)
    if not delta:
        raise ValueError(f"Unknown timeframe '{timeframe}'. Supported: {list(TIMEFRAME_DELTAS.keys())}")
    return delta


def ensure_utc_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure a datetime object is timezone-aware in UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_forex_weekend(timestamp: Optional[datetime] = None) -> bool:
    """Check if a timestamp falls during the standard Forex weekend closure.
    
    Forex market closes Friday ~21:00 UTC and reopens Sunday ~21:00 UTC.
    """
    ts = ensure_utc_datetime(timestamp) or datetime.now(timezone.utc)
    weekday = ts.weekday()  # Monday is 0, Sunday is 6
    hour = ts.hour

    # Friday after 21:00 UTC
    if weekday == 4 and hour >= 21:
        return True
    # Entire Saturday
    if weekday == 5:
        return True
    # Sunday before 21:00 UTC
    if weekday == 6 and hour < 21:
        return True

    return False


def is_candle_closed(
    candle: Union[CandleBase, Any],
    timeframe: str,
    as_of: Optional[datetime] = None,
) -> bool:
    """Check whether a candle bar has completed its duration and is closed.
    
    A candle with start timestamp T and duration D is closed if:
        T + D <= as_of
    """
    if candle is None:
        return False

    ref_time = ensure_utc_datetime(as_of) or datetime.now(timezone.utc)
    candle_ts = ensure_utc_datetime(candle.timestamp)
    delta = get_timeframe_delta(timeframe)
    candle_close_time = candle_ts + delta

    return candle_close_time <= ref_time


def filter_closed_candles(
    candles: Sequence[Union[CandleBase, Any]],
    timeframe: str,
    as_of: Optional[datetime] = None,
) -> List[Any]:
    """Filter a candle sequence to include only fully closed (verified) candles.
    
    Out-of-order candles are sorted chronologically ascending.
    If candles are strictly in the past relative to as_of (e.g. historical data/backtests),
    all elapsed candles are returned.
    """
    if not candles:
        return []

    ref_time = ensure_utc_datetime(as_of) or datetime.now(timezone.utc)
    delta = get_timeframe_delta(timeframe)

    closed_candles: List[Any] = []
    for c in candles:
        ts = ensure_utc_datetime(c.timestamp)
        close_time = ts + delta
        if close_time <= ref_time:
            closed_candles.append(c)

    # Sort ascending chronologically
    closed_candles.sort(key=lambda c: ensure_utc_datetime(c.timestamp))
    return closed_candles


def get_latest_closed_candle(
    candles: Sequence[Union[CandleBase, Any]],
    timeframe: str,
    as_of: Optional[datetime] = None,
) -> Optional[Any]:
    """Retrieve the single most recent closed candle from a sequence."""
    closed = filter_closed_candles(candles, timeframe=timeframe, as_of=as_of)
    if not closed:
        return None
    return closed[-1]


@dataclass
class StalenessCheckResult:
    """Detailed diagnostics for candle dataset freshness."""
    is_stale: bool
    symbol: str
    timeframe: str
    latest_candle_time: Optional[datetime]
    latest_close_time: Optional[datetime]
    age_seconds: float
    age_hours: float
    max_allowed_hours: float
    is_weekend: bool
    message: str


def check_data_staleness(
    candles: Sequence[Union[CandleBase, Any]],
    symbol: str = "UNKNOWN",
    timeframe: str = "1h",
    max_staleness_hours: Optional[float] = None,
    as_of: Optional[datetime] = None,
) -> StalenessCheckResult:
    """Check if the latest candle in the dataset is stale relative to current time or as_of time.
    
    Accounts for Forex weekend closures (Friday 21:00 UTC - Sunday 21:00 UTC).
    """
    ref_time = ensure_utc_datetime(as_of) or datetime.now(timezone.utc)
    delta = get_timeframe_delta(timeframe)
    tf_lower = timeframe.lower().strip()

    if max_staleness_hours is not None:
        threshold_delta = timedelta(hours=max_staleness_hours)
    else:
        threshold_delta = DEFAULT_STALENESS_THRESHOLDS.get(tf_lower, delta * 3)

    max_allowed_hours = threshold_delta.total_seconds() / 3600.0
    weekend = is_forex_weekend(ref_time)

    if not candles:
        return StalenessCheckResult(
            is_stale=True,
            symbol=symbol,
            timeframe=timeframe,
            latest_candle_time=None,
            latest_close_time=None,
            age_seconds=float("inf"),
            age_hours=float("inf"),
            max_allowed_hours=max_allowed_hours,
            is_weekend=weekend,
            message=f"No candle data available for {symbol} [{timeframe}]. Dataset is empty.",
        )

    # Sort to find latest
    latest_candle = max(candles, key=lambda c: ensure_utc_datetime(c.timestamp))
    latest_ts = ensure_utc_datetime(latest_candle.timestamp)
    latest_close = latest_ts + delta

    age_seconds = max(0.0, (ref_time - latest_close).total_seconds())
    age_hours = age_seconds / 3600.0

    # If it is currently a Forex weekend and the latest candle is from Friday close (after 18:00 UTC)
    if weekend:
        if latest_ts.weekday() == 4 and latest_ts.hour >= 18:
            return StalenessCheckResult(
                is_stale=False,
                symbol=symbol,
                timeframe=timeframe,
                latest_candle_time=latest_ts,
                latest_close_time=latest_close,
                age_seconds=age_seconds,
                age_hours=age_hours,
                max_allowed_hours=max_allowed_hours,
                is_weekend=True,
                message=(
                    f"Market is closed for weekend. Latest candle from Friday close "
                    f"({latest_ts.strftime('%Y-%m-%d %H:%M UTC')}) is valid."
                ),
            )

    is_stale = age_seconds > threshold_delta.total_seconds()

    if is_stale:
        msg = (
            f"STALE DATA DETECTED for {symbol} [{timeframe}]: Latest closed candle closed at "
            f"{latest_close.strftime('%Y-%m-%d %H:%M UTC')} ({age_hours:.1f}h ago). "
            f"Exceeds maximum freshness threshold of {max_allowed_hours:.1f}h."
        )
    else:
        msg = (
            f"Market data for {symbol} [{timeframe}] is FRESH: Latest closed candle at "
            f"{latest_close.strftime('%Y-%m-%d %H:%M UTC')} ({age_hours:.1f}h ago <= {max_allowed_hours:.1f}h threshold)."
        )

    return StalenessCheckResult(
        is_stale=is_stale,
        symbol=symbol,
        timeframe=timeframe,
        latest_candle_time=latest_ts,
        latest_close_time=latest_close,
        age_seconds=age_seconds,
        age_hours=age_hours,
        max_allowed_hours=max_allowed_hours,
        is_weekend=weekend,
        message=msg,
    )


def format_candle_log_line(
    candle: Union[CandleBase, Any],
    symbol: str,
    timeframe: str,
    context: str = "MARKET DATA",
    is_fresh: Optional[bool] = None,
) -> str:
    """Format structured log string for explicit latest candle logging."""
    if candle is None:
        return f"[{context}] Symbol: {symbol} | Timeframe: {timeframe} | No candle data available."

    ts = ensure_utc_datetime(candle.timestamp)
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S UTC") if ts else "N/A"
    
    vol = getattr(candle, "volume", 0.0) or 0.0
    freshness_str = ""
    if is_fresh is not None:
        freshness_str = f" | Freshness: {'FRESH' if is_fresh else 'STALE'}"

    return (
        f"[{context}] Symbol: {symbol} | Timeframe: {timeframe} | "
        f"Latest Closed Candle: {ts_str} | Open: {candle.open:.5f} | "
        f"High: {candle.high:.5f} | Low: {candle.low:.5f} | "
        f"Close: {candle.close:.5f} | Volume: {vol:.1f}{freshness_str}"
    )


def log_latest_candle(
    candle: Union[CandleBase, Any],
    symbol: str,
    timeframe: str,
    context: str = "MARKET DATA",
    is_fresh: Optional[bool] = None,
) -> None:
    """Explicitly log latest candle details at INFO level."""
    log_line = format_candle_log_line(
        candle=candle,
        symbol=symbol,
        timeframe=timeframe,
        context=context,
        is_fresh=is_fresh,
    )
    logger.info(log_line)
