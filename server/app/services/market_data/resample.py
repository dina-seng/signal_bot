"""Pure functions for resampling 15m OHLCV candles to higher timeframes.

Rules:
1. Fetch ONLY 15m candles from Twelve Data.
2. Build 30m, 1h, 4h locally (UTC-anchored buckets).
   - Only emit a bucket if ALL expected 15m bars in that bucket exist; otherwise omit (incomplete).
   - 30m requires 2 bars (:00, :15 or :30, :45).
   - 1h requires 4 bars (:00, :15, :30, :45).
   - 4h requires 16 bars (anchored at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC).
3. Build daily (1d) bar anchored at 17:00 America/New_York (DST-aware via zoneinfo).
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Union
import zoneinfo

from app.schemas.candle import CandleCreate

NY_TZ = zoneinfo.ZoneInfo("America/New_York")
UTC_TZ = timezone.utc

EXPECTED_BARS_COUNT: Dict[str, int] = {
    "30m": 2,
    "1h": 4,
    "4h": 16,
}


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware in UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_bucket_start_utc(dt: datetime, tf: str) -> datetime:
    """Return the UTC-anchored bucket start timestamp for standard intraday timeframes."""
    dt = _ensure_utc(dt)
    if tf == "30m":
        minute = (dt.minute // 30) * 30
        return dt.replace(minute=minute, second=0, microsecond=0)
    elif tf == "1h":
        return dt.replace(minute=0, second=0, microsecond=0)
    elif tf == "4h":
        hour = (dt.hour // 4) * 4
        return dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"Unsupported intraday timeframe for UTC bucket: {tf}")


def get_ny_session_start(dt: datetime) -> datetime:
    """Return the 17:00 America/New_York session start in UTC for a given timestamp."""
    dt_utc = _ensure_utc(dt)
    dt_ny = dt_utc.astimezone(NY_TZ)

    if dt_ny.hour >= 17:
        session_start_ny = dt_ny.replace(hour=17, minute=0, second=0, microsecond=0)
    else:
        session_start_ny = (dt_ny - timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)

    return session_start_ny.astimezone(UTC_TZ)


def resample_ohlc(
    candles_15m: List[CandleCreate],
    tf: str,
    strict_completeness: bool = True,
    expected_daily_bars: int = 92,
) -> List[CandleCreate]:
    """Pure function to resample sorted 15m candles into higher timeframe candles.

    Args:
        candles_15m: Chronologically sorted list of 15m CandleCreate objects.
        tf: Target timeframe ("30m", "1h", "4h", "1d" or "1D").
        strict_completeness: If True, only emit buckets where all expected 15m bars exist.
        expected_daily_bars: Expected 15m bars in a 17:00 NY daily session (default 92 for 23h trading).

    Returns:
        List of resampled CandleCreate objects.
    """
    tf_normalized = tf.lower()
    if not candles_15m:
        return []

    if tf_normalized == "15m":
        return list(candles_15m)

    # Group candles by bucket start
    buckets: Dict[datetime, List[CandleCreate]] = defaultdict(list)
    symbol = candles_15m[0].symbol

    if tf_normalized in ("30m", "1h", "4h"):
        expected_count = EXPECTED_BARS_COUNT[tf_normalized]
        step_delta = timedelta(minutes=15)

        for c in candles_15m:
            ts = _ensure_utc(c.timestamp)
            bucket_key = get_bucket_start_utc(ts, tf_normalized)
            buckets[bucket_key].append(c)

        resampled: List[CandleCreate] = []
        for bucket_ts in sorted(buckets.keys()):
            bars = buckets[bucket_ts]
            bars.sort(key=lambda b: _ensure_utc(b.timestamp))

            if strict_completeness:
                if len(bars) != expected_count:
                    continue
                # Verify exact 15m spacing inside bucket
                timestamps = [_ensure_utc(b.timestamp) for b in bars]
                expected_timestamps = [bucket_ts + i * step_delta for i in range(expected_count)]
                if timestamps != expected_timestamps:
                    continue

            open_val = bars[0].open
            high_val = max(b.high for b in bars)
            low_val = min(b.low for b in bars)
            close_val = bars[-1].close
            vol_val = sum(b.volume for b in bars)

            resampled.append(
                CandleCreate(
                    symbol=symbol,
                    timeframe=tf_normalized,
                    timestamp=bucket_ts,
                    open=open_val,
                    high=high_val,
                    low=low_val,
                    close=close_val,
                    volume=vol_val,
                )
            )

        return resampled

    elif tf_normalized in ("1d", "1day"):
        for c in candles_15m:
            ts = _ensure_utc(c.timestamp)
            bucket_key = get_ny_session_start(ts)
            buckets[bucket_key].append(c)

        resampled: List[CandleCreate] = []
        for bucket_ts in sorted(buckets.keys()):
            bars = buckets[bucket_ts]
            bars.sort(key=lambda b: _ensure_utc(b.timestamp))

            # Only emit complete daily bars if strict_completeness is set
            if strict_completeness and len(bars) < expected_daily_bars:
                continue

            open_val = bars[0].open
            high_val = max(b.high for b in bars)
            low_val = min(b.low for b in bars)
            close_val = bars[-1].close
            vol_val = sum(b.volume for b in bars)

            resampled.append(
                CandleCreate(
                    symbol=symbol,
                    timeframe="1d",
                    timestamp=bucket_ts,
                    open=open_val,
                    high=high_val,
                    low=low_val,
                    close=close_val,
                    volume=vol_val,
                )
            )

        return resampled

    else:
        raise ValueError(f"Unsupported timeframe for resampling: {tf}")
