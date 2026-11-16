"""Daily Bias, Previous-Day Range, Session Extremes, and Swept Level Classification.

Anchored to 17:00 America/New_York daily close (Forex/Metals standard).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Sequence, Tuple
import zoneinfo

NY_TZ = zoneinfo.ZoneInfo("America/New_York")
UTC_TZ = timezone.utc


@dataclass(frozen=True)
class DailyBiasResult:
    """Result of daily bias and session range computation."""
    pdh: Optional[float]
    pdl: Optional[float]
    daily_open: Optional[float]
    bias: str  # "BULLISH", "BEARISH", "NEUTRAL"
    premium_discount: str  # "PREMIUM", "DISCOUNT", "EQUILIBRIUM"
    asian_high: Optional[float]
    asian_low: Optional[float]
    london_high: Optional[float]
    london_low: Optional[float]


def _get_candle_ts(c: Any) -> Optional[datetime]:
    if isinstance(c, dict):
        raw = c.get("timestamp")
    else:
        raw = getattr(c, "timestamp", None)
    if raw is None:
        return None
    if raw.tzinfo is None:
        return raw.replace(tzinfo=UTC_TZ)
    return raw.astimezone(UTC_TZ)


def _get_val(c: Any, field: str) -> float:
    if isinstance(c, dict):
        return float(c[field])
    return float(getattr(c, field))


def calculate_daily_bias(
    candles_1h: Sequence[Any],
    current_time: Optional[datetime] = None,
    current_price: Optional[float] = None,
) -> DailyBiasResult:
    """Calculate Previous Day High/Low, Daily Open, and Session Extremes."""
    if not candles_1h:
        return DailyBiasResult(
            pdh=None, pdl=None, daily_open=None,
            bias="NEUTRAL", premium_discount="EQUILIBRIUM",
            asian_high=None, asian_low=None,
            london_high=None, london_low=None,
        )

    ref_ts = current_time or _get_candle_ts(candles_1h[-1]) or datetime.now(UTC_TZ)
    ref_ny = ref_ts.astimezone(NY_TZ)

    # Determine current trading day start in NY: today at 17:00 NY if past 17:00, else yesterday 17:00 NY
    if ref_ny.hour >= 17:
        current_day_start_ny = ref_ny.replace(hour=17, minute=0, second=0, microsecond=0)
    else:
        current_day_start_ny = (ref_ny - timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)

    prev_day_start_ny = current_day_start_ny - timedelta(days=1)
    prev_day_end_ny = current_day_start_ny

    prev_day_start_utc = prev_day_start_ny.astimezone(UTC_TZ)
    prev_day_end_utc = prev_day_end_ny.astimezone(UTC_TZ)
    current_day_start_utc = current_day_start_ny.astimezone(UTC_TZ)

    # Collect previous day candles and current day candles
    prev_day_candles = []
    current_day_candles = []

    for c in candles_1h:
        c_ts = _get_candle_ts(c)
        if c_ts is None:
            continue
        if prev_day_start_utc <= c_ts < prev_day_end_utc:
            prev_day_candles.append(c)
        elif c_ts >= current_day_start_utc and c_ts <= ref_ts:
            current_day_candles.append(c)

    # Calculate PDH / PDL
    pdh = max((_get_val(c, "high") for c in prev_day_candles), default=None)
    pdl = min((_get_val(c, "low") for c in prev_day_candles), default=None)

    # Daily open is open of the first candle of the current session
    daily_open = _get_val(current_day_candles[0], "open") if current_day_candles else None

    # Asian session: 18:00 - 00:00 NY (of current day cycle)
    asian_start_ny = current_day_start_ny.replace(hour=18, minute=0, second=0, microsecond=0)
    asian_end_ny = (current_day_start_ny + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    asian_start_utc = asian_start_ny.astimezone(UTC_TZ)
    asian_end_utc = asian_end_ny.astimezone(UTC_TZ)

    asian_candles = [
        c for c in candles_1h
        if _get_candle_ts(c) is not None and asian_start_utc <= _get_candle_ts(c) < asian_end_utc
    ]
    asian_high = max((_get_val(c, "high") for c in asian_candles), default=None)
    asian_low = min((_get_val(c, "low") for c in asian_candles), default=None)

    # London session: 03:00 - 07:00 NY (of current day cycle)
    london_start_ny = (current_day_start_ny + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
    london_end_ny = (current_day_start_ny + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
    london_start_utc = london_start_ny.astimezone(UTC_TZ)
    london_end_utc = london_end_ny.astimezone(UTC_TZ)

    london_candles = [
        c for c in candles_1h
        if _get_candle_ts(c) is not None and london_start_utc <= _get_candle_ts(c) < london_end_utc
    ]
    london_high = max((_get_val(c, "high") for c in london_candles), default=None)
    london_low = min((_get_val(c, "low") for c in london_candles), default=None)

    # Premium / Discount classification
    price = current_price if current_price is not None else (_get_val(candles_1h[-1], "close") if candles_1h else 0.0)
    prem_disc = "EQUILIBRIUM"
    if pdh is not None and pdl is not None and pdh > pdl:
        eq = (pdh + pdl) / 2.0
        if price > eq:
            prem_disc = "PREMIUM"
        elif price < eq:
            prem_disc = "DISCOUNT"

    # Daily Bias
    bias = "NEUTRAL"
    if daily_open is not None:
        if price > daily_open:
            bias = "BULLISH"
        elif price < daily_open:
            bias = "BEARISH"

    return DailyBiasResult(
        pdh=pdh,
        pdl=pdl,
        daily_open=daily_open,
        bias=bias,
        premium_discount=prem_disc,
        asian_high=asian_high,
        asian_low=asian_low,
        london_high=london_high,
        london_low=london_low,
    )


def classify_swept_level(
    breach_point: float,
    positive_direction: bool,
    daily_bias: DailyBiasResult,
    structure: Any = None,
    atr: float = 10.0,
) -> Tuple[str, float]:
    """Classify the swept liquidity level type and determine its base score (max 18.0).

    Returns:
        (level_type_label, score_points)
    """
    tol = max(0.50, 0.15 * atr)

    # 1. Previous Day High / Low
    if positive_direction and daily_bias.pdl is not None and abs(breach_point - daily_bias.pdl) <= tol:
        return "Previous Day Low (PDL)", 18.0
    if not positive_direction and daily_bias.pdh is not None and abs(breach_point - daily_bias.pdh) <= tol:
        return "Previous Day High (PDH)", 18.0

    # 2. Session High / Low
    if positive_direction:
        if daily_bias.asian_low is not None and abs(breach_point - daily_bias.asian_low) <= tol:
            return "Asian Session Low", 16.0
        if daily_bias.london_low is not None and abs(breach_point - daily_bias.london_low) <= tol:
            return "London Session Low", 16.0
    else:
        if daily_bias.asian_high is not None and abs(breach_point - daily_bias.asian_high) <= tol:
            return "Asian Session High", 16.0
        if daily_bias.london_high is not None and abs(breach_point - daily_bias.london_high) <= tol:
            return "London Session High", 16.0

    # 3. Equal Highs / Lows Pool from structure
    if structure is not None and hasattr(structure, "liquidity_pools") and structure.liquidity_pools:
        for pool in structure.liquidity_pools:
            pool_type = getattr(pool, "pool_type", "")
            p_price = getattr(pool, "price_level", getattr(pool, "price", 0.0))
            if positive_direction and "LOW" in str(pool_type) and abs(breach_point - p_price) <= tol:
                return "Equal Lows Liquidity Pool", 15.0
            if not positive_direction and "HIGH" in str(pool_type) and abs(breach_point - p_price) <= tol:
                return "Equal Highs Liquidity Pool", 15.0

    # 4. Swing High / Low
    if structure is not None and hasattr(structure, "base_structure") and structure.base_structure:
        bs = structure.base_structure
        if hasattr(bs, "swing_points") and bs.swing_points:
            for sp in bs.swing_points:
                s_price = getattr(sp, "price", 0.0)
                if abs(breach_point - s_price) <= tol:
                    label = "Confirmed Swing Low" if positive_direction else "Confirmed Swing High"
                    return label, 12.0

    # 5. Benchmark Accumulation Range Extreme
    # A standard range extreme sweep scores solid baseline
    return "Benchmark Range Extreme", 10.0

