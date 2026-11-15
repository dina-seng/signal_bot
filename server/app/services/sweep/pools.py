"""Liquidity Pool representation and pool discovery logic with zero lookahead."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Set
import zoneinfo
import hashlib

from app.schemas.candle import CandleCreate
from app.services.sweep.config import SweepConfig
from app.services.sweep.pivots import Pivot, detect_pivots

NY_TZ = zoneinfo.ZoneInfo("America/New_York")
UTC_TZ = timezone.utc


@dataclass
class LiquidityPool:
    """Represents a resting liquidity pool."""
    id: str
    price: float
    pool_type: str         # 'SWING_HIGH', 'SWING_LOW', 'EQUAL_HIGHS', 'EQUAL_LOWS', 'PDH', 'PDL', 'ASIA_HIGH', etc.
    side: str              # 'BUYSIDE' (above market) or 'SELLSIDE' (below market)
    confirm_time: datetime # Exact timestamp when this pool became known/active
    swept: bool = False
    sweep_bar_index: Optional[int] = None
    timeframe: str = "15m"


def build_pool_id(pool_type: str, side: str, price: float, confirm_time: datetime) -> str:
    """Generate deterministic pool id."""
    key = f"{pool_type}_{side}_{price:.2f}_{confirm_time.isoformat()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def is_kill_zone(dt_utc: datetime, config: SweepConfig) -> bool:
    """Check if a UTC timestamp falls within defined kill-zone windows (America/New_York)."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=UTC_TZ)
    dt_ny = dt_utc.astimezone(NY_TZ)
    hour = dt_ny.hour
    minute = dt_ny.minute

    # London: 03:00 - 07:00 NY
    if config.london_start_hour_ny <= hour < config.london_end_hour_ny:
        return True

    # NY Prep: 09:00 - 09:30 NY
    if hour == config.ny_prep_start_hour_ny and config.ny_prep_start_min_ny <= minute < config.ny_prep_end_min_ny:
        return True

    # NY Window: 09:30 - 10:30 NY
    if (hour == 9 and minute >= 30) or (hour == 10 and minute <= 30):
        return True

    return False


def identify_liquidity_pools(
    candles_15m: Sequence[CandleCreate],
    candles_1h: Sequence[CandleCreate],
    atr_values: Sequence[float],
    config: SweepConfig,
) -> List[LiquidityPool]:
    """Identify all resting liquidity pools visible across the dataset.

    Pools included:
    1. Confirmed swing highs / lows on 15m (N=pivot_n_15m) and 1h (N=pivot_n_htf).
    2. Equal highs / equal lows: >=2 confirmed pivots within 0.10 * ATR of each other.
    3. Previous-Day High / Low (PDH/PDL) anchored at 17:00 America/New_York.
    4. Asia High / Low (18:00 - 00:00 America/New_York).
    5. London High / Low (03:00 - 07:00 America/New_York).
    """
    pools: List[LiquidityPool] = []
    if not candles_15m:
        return []

    # 1. 15m Swing Pivots
    pivots_15m = detect_pivots(candles_15m, n=config.pivot_n_15m)
    for p in pivots_15m:
        side = "BUYSIDE" if p.pivot_type == "HIGH" else "SELLSIDE"
        p_id = build_pool_id(f"SWING_{p.pivot_type}", side, p.price, p.confirm_timestamp)
        pools.append(
            LiquidityPool(
                id=p_id,
                price=p.price,
                pool_type=f"SWING_{p.pivot_type}",
                side=side,
                confirm_time=p.confirm_timestamp,
                timeframe="15m",
            )
        )

    # 2. 1h Swing Pivots
    if candles_1h:
        pivots_1h = detect_pivots(candles_1h, n=config.pivot_n_htf)
        for p in pivots_1h:
            side = "BUYSIDE" if p.pivot_type == "HIGH" else "SELLSIDE"
            p_id = build_pool_id(f"SWING_1H_{p.pivot_type}", side, p.price, p.confirm_timestamp)
            pools.append(
                LiquidityPool(
                    id=p_id,
                    price=p.price,
                    pool_type=f"SWING_1H_{p.pivot_type}",
                    side=side,
                    confirm_time=p.confirm_timestamp,
                    timeframe="1h",
                )
            )

    # 3. Equal Highs / Equal Lows (clustering within 0.10 * ATR)
    high_pivots = [p for p in pivots_15m if p.pivot_type == "HIGH"]
    for i in range(len(high_pivots)):
        for j in range(i + 1, min(i + 5, len(high_pivots))):
            p1 = high_pivots[i]
            p2 = high_pivots[j]
            atr_at_p2 = atr_values[p2.confirm_index] if p2.confirm_index < len(atr_values) else 10.0
            threshold = config.equal_level_threshold_atr * atr_at_p2
            if abs(p1.price - p2.price) <= threshold:
                avg_price = (p1.price + p2.price) / 2.0
                p_id = build_pool_id("EQUAL_HIGHS", "BUYSIDE", avg_price, p2.confirm_timestamp)
                pools.append(
                    LiquidityPool(
                        id=p_id,
                        price=avg_price,
                        pool_type="EQUAL_HIGHS",
                        side="BUYSIDE",
                        confirm_time=p2.confirm_timestamp,
                        timeframe="15m",
                    )
                )

    low_pivots = [p for p in pivots_15m if p.pivot_type == "LOW"]
    for i in range(len(low_pivots)):
        for j in range(i + 1, min(i + 5, len(low_pivots))):
            p1 = low_pivots[i]
            p2 = low_pivots[j]
            atr_at_p2 = atr_values[p2.confirm_index] if p2.confirm_index < len(atr_values) else 10.0
            threshold = config.equal_level_threshold_atr * atr_at_p2
            if abs(p1.price - p2.price) <= threshold:
                avg_price = (p1.price + p2.price) / 2.0
                p_id = build_pool_id("EQUAL_LOWS", "SELLSIDE", avg_price, p2.confirm_timestamp)
                pools.append(
                    LiquidityPool(
                        id=p_id,
                        price=avg_price,
                        pool_type="EQUAL_LOWS",
                        side="SELLSIDE",
                        confirm_time=p2.confirm_timestamp,
                        timeframe="15m",
                    )
                )

    # 4. Session Highs / Lows & Previous-Day High / Low (DST-aware America/New_York)
    # Group candles by session
    # A session becomes known immediately after the last bar of that session closes!
    session_asia_bars: Dict[Any, List[CandleCreate]] = {}
    session_london_bars: Dict[Any, List[CandleCreate]] = {}
    daily_bars: Dict[Any, List[CandleCreate]] = {}

    for c in candles_15m:
        ts = c.timestamp if c.timestamp.tzinfo else c.timestamp.replace(tzinfo=UTC_TZ)
        ny_dt = ts.astimezone(NY_TZ)
        d_val = (ny_dt.year, ny_dt.month, ny_dt.day)

        # Asia session: 18:00 - 00:00 NY
        if ny_dt.hour >= 18:
            session_asia_bars.setdefault(d_val, []).append(c)

        # London session: 03:00 - 07:00 NY
        if 3 <= ny_dt.hour < 7:
            session_london_bars.setdefault(d_val, []).append(c)

        # Daily 17:00 NY session key
        day_key = d_val if ny_dt.hour < 17 else ((ny_dt + timedelta(days=1)).year, (ny_dt + timedelta(days=1)).month, (ny_dt + timedelta(days=1)).day)
        daily_bars.setdefault(day_key, []).append(c)

    # Convert Asia sessions to pools once closed (closes at 00:00 NY = next day 00:00 NY)
    for d_str, bars in session_asia_bars.items():
        if len(bars) >= 16:  # full 6 hours
            high_val = max(b.high for b in bars)
            low_val = min(b.low for b in bars)
            close_time = bars[-1].timestamp + timedelta(minutes=15)
            pools.append(LiquidityPool(
                id=build_pool_id("ASIA_HIGH", "BUYSIDE", high_val, close_time),
                price=high_val, pool_type="ASIA_HIGH", side="BUYSIDE", confirm_time=close_time, timeframe="session"
            ))
            pools.append(LiquidityPool(
                id=build_pool_id("ASIA_LOW", "SELLSIDE", low_val, close_time),
                price=low_val, pool_type="ASIA_LOW", side="SELLSIDE", confirm_time=close_time, timeframe="session"
            ))

    # Convert London sessions to pools once closed (closes at 07:00 NY)
    for d_str, bars in session_london_bars.items():
        if len(bars) >= 12:  # 4 hours (03:00-07:00)
            high_val = max(b.high for b in bars)
            low_val = min(b.low for b in bars)
            close_time = bars[-1].timestamp + timedelta(minutes=15)
            pools.append(LiquidityPool(
                id=build_pool_id("LONDON_HIGH", "BUYSIDE", high_val, close_time),
                price=high_val, pool_type="LONDON_HIGH", side="BUYSIDE", confirm_time=close_time, timeframe="session"
            ))
            pools.append(LiquidityPool(
                id=build_pool_id("LONDON_LOW", "SELLSIDE", low_val, close_time),
                price=low_val, pool_type="LONDON_LOW", side="SELLSIDE", confirm_time=close_time, timeframe="session"
            ))

    # Convert Daily sessions to PDH / PDL once closed (at 17:00 NY)
    for d_key, bars in daily_bars.items():
        if len(bars) >= 80:  # complete daily trading session
            high_val = max(b.high for b in bars)
            low_val = min(b.low for b in bars)
            close_time = bars[-1].timestamp + timedelta(minutes=15)
            pools.append(LiquidityPool(
                id=build_pool_id("PDH", "BUYSIDE", high_val, close_time),
                price=high_val, pool_type="PDH", side="BUYSIDE", confirm_time=close_time, timeframe="1d"
            ))
            pools.append(LiquidityPool(
                id=build_pool_id("PDL", "SELLSIDE", low_val, close_time),
                price=low_val, pool_type="PDL", side="SELLSIDE", confirm_time=close_time, timeframe="1d"
            ))

    pools.sort(key=lambda p: p.confirm_time)
    return pools
