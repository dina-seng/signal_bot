"""Single shared technical-confluence calculation used by the REST API and Telegram.

Returns a JSON-safe dictionary instead of raw pydantic snapshots or ``None``::

    {
        "score": 75.0, "ema_20": 2030.5, "ema_50": 2024.1,
        "rsi": 55.2, "adx": 22.1, "trend": "BULLISH_STACK", ...
    }

The calculator is deliberately defensive: with too little history (or NaN /
None indicator values) it returns a valid, fully-structured result with a
neutral score instead of throwing or emitting nulls into Telegram messages.
"""

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from app.services.indicators.adx_calculator import ADXCalculator
from app.services.indicators.indicator_service import IndicatorService
from app.services.signals.confluence_scoring import (
    calculate_ai_confidence,
    calculate_confluence,
)

# EMA200 needs 200 closed bars; ADX(14) needs 28. Request above both so the
# slow EMA is never None on a well-fed symbol.
MIN_HISTORY_BARS = 210
ADX_MIN_BARS = 28


def _safe_float(value: Any) -> Optional[float]:
    """Coerce to a finite float, mapping NaN/None/garbage to None."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def enough_history(candle_count: int) -> bool:
    """True when there are enough bars for EMA200 and ADX14."""
    return int(candle_count or 0) >= MIN_HISTORY_BARS


def calculate_technical_confluence(
    candles: Sequence[Any],
    symbol: str = "XAU/USD",
    timeframe: str = "1h",
    historical_win_rate: Optional[float] = None,
) -> dict[str, Any]:
    """Compute a structured, NaN-free technical analysis from OHLC candles."""
    bars = list(candles or [])
    result: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": datetime.now(timezone.utc),
        "bars": len(bars),
        "history_sufficient": enough_history(len(bars)),
        "price": None,
        "score": 0.0,
        "ema_20": None,
        "ema_50": None,
        "ema_200": None,
        "rsi": None,
        "adx": None,
        "trend": "NEUTRAL",
        "sub_scores": {"ema": 0.0, "rsi": 0.0, "adx": 0.0},
        "confidence": 60,
        "note": None,
    }

    if len(bars) < ADX_MIN_BARS:
        result["note"] = (
            f"Only {len(bars)} candles available; need at least {ADX_MIN_BARS} "
            "for ADX(14) and 200 for EMA200."
        )
        return result

    try:
        analysis = IndicatorService().analyze_indicators(
            candles=bars, symbol=symbol, timeframe=timeframe
        )
    except Exception as exc:  # never leak a formatter-breaking exception
        result["note"] = f"Indicator calculation unavailable: {exc}"
        return result

    price = _safe_float(getattr(analysis, "current_price", None))
    ema_snapshot = getattr(analysis, "ema", None)
    rsi_snapshot = getattr(analysis, "rsi", None)
    ema_20 = _safe_float(getattr(ema_snapshot, "ema_fast", None))
    ema_50 = _safe_float(getattr(ema_snapshot, "ema_mid", None))
    ema_200 = _safe_float(getattr(ema_snapshot, "ema_slow", None))
    rsi = _safe_float(getattr(rsi_snapshot, "rsi_value", None))
    adx = _safe_float(
        ADXCalculator().calculate_adx_from_candles(bars, period=14)
    )

    confluence = calculate_confluence(
        price=price,
        ema_fast=ema_20,
        ema_mid=ema_50,
        rsi=rsi,
        adx=adx,
        ema_slow=ema_200,
        direction=None,  # report the dominant trend's confluence
    )
    volatility_pct = None
    atr_value = _safe_float(getattr(getattr(analysis, "atr", None), "atr_value", None))
    if atr_value is not None and price not in (None, 0.0):
        volatility_pct = abs(atr_value) / abs(price) * 100.0

    result.update(
        price=price,
        score=confluence.score,
        ema_20=ema_20,
        ema_50=ema_50,
        ema_200=ema_200,
        rsi=rsi,
        adx=adx,
        trend=confluence.ema_trend,
        sub_scores={
            "ema": confluence.ema_score,
            "rsi": confluence.rsi_score,
            "adx": confluence.adx_score,
        },
        confidence=calculate_ai_confidence(
            confluence.score, adx, historical_win_rate, volatility_pct
        ),
        note=(
            "Fewer than 200 candles: EMA200 unavailable, score uses EMA20/50 + RSI + ADX."
            if ema_200 is None
            else None
        ),
    )
    return result
