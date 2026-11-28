"""Graded technical-confluence scoring and realistic AI confidence.

The legacy BTC momentum implementation awarded fixed points for three boolean
checks (EMA alignment 40, RSI 35, price location 25). Any bar that passed all
three therefore produced *exactly* 100/100, regardless of how strong or weak the
underlying confluence actually was, and ADX never contributed to the score at
all. This module replaces the boolean points with graded 0-100 sub-scores and
combines them with the documented 40/30/30 weighting::

    score = ema_score * 0.40 + rsi_score * 0.30 + adx_score * 0.30

Every sub-score is bounded and graded, so a perfect 100 is structurally
unreachable (the highest possible weighted score is 97.0). AI confidence is
derived from the resulting score, the ADX regime, historical win rate and
realized volatility, and is hard-clamped to 60-95%.
"""

from dataclasses import dataclass
from typing import Optional

from app.services.indicators.ema_calculator import classify_ema_trend

# Documented pillar weights.
EMA_WEIGHT = 0.40
RSI_WEIGHT = 0.30
ADX_WEIGHT = 0.30

# Confidence is a *belief*, never a certainty: no model output may reach 100%.
CONFIDENCE_MIN = 60.0
CONFIDENCE_MAX = 95.0
MAX_CONFLUENCE_SCORE = 99.0


def _to_float(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


@dataclass(frozen=True)
class ConfluenceResult:
    """Graded, direction-aware confluence result."""

    score: float
    ema_score: float
    rsi_score: float
    adx_score: float
    ema_trend: str


def _direction_value(direction: Optional[str], ema_trend: str) -> int:
    """Return +1 for BUY, -1 for SELL, or infer from the EMA trend."""
    token = str(direction or "").strip().upper()
    if token == "BUY":
        return 1
    if token == "SELL":
        return -1
    if "BULLISH" in ema_trend:
        return 1
    if "BEARISH" in ema_trend:
        return -1
    return 0


def ema_confluence_score(
    price: Optional[float],
    ema_fast: Optional[float],
    ema_mid: Optional[float],
    ema_slow: Optional[float] = None,
    direction: Optional[str] = None,
) -> float:
    """Grade EMA alignment/price/slow-EMA confluence from 0 to 100.

    Four graded components replace the old boolean "40 points if EMA50>EMA200":
    alignment (max 30), price distance from EMA20 (max 30), EMA200 confirmation
    (max 30) and a full-stack bonus (10). Weak alignment now scores weakly.
    """
    price_f = _to_float(price)
    fast_f = _to_float(ema_fast)
    mid_f = _to_float(ema_mid)
    slow_f = _to_float(ema_slow)
    if price_f is None or fast_f is None or mid_f is None or fast_f == 0 or mid_f == 0:
        return 50.0  # unknown inputs -> neutral, never a perfect score

    trend = classify_ema_trend(price_f, fast_f, mid_f, slow_f)
    trend_dir = 1 if fast_f > mid_f else -1 if fast_f < mid_f else 0
    trade_dir = _direction_value(direction, trend) or trend_dir or 1
    aligned = trend_dir == trade_dir

    # 1. Fast/mid separation, relative to a 0.5% reference move.
    separation_pct = abs(fast_f - mid_f) / abs(mid_f)
    alignment_points = (
        30.0 * min(1.0, separation_pct / 0.005)
        if aligned
        else (8.0 if trend_dir == 0 else 0.0)
    )

    # 2. Price location vs EMA20 in the trade direction, 0.5% reference.
    favorable_distance = (price_f - fast_f) if trade_dir > 0 else (fast_f - price_f)
    price_points = 30.0 * min(1.0, max(0.0, favorable_distance) / abs(fast_f) / 0.005)

    # 3. EMA200 confirmation, 1.0% reference.
    slow_points = 0.0
    if slow_f not in (None, 0.0):
        slow_separation_pct = abs(fast_f - slow_f) / abs(slow_f)
        slow_confirms = (
            (trade_dir > 0 and fast_f > slow_f)
            or (trade_dir < 0 and fast_f < slow_f)
        )
        if slow_confirms:
            slow_points = 30.0 * min(1.0, slow_separation_pct / 0.01)

    # 4. Only a fully confirmed stack earns the bonus.
    stack_points = 10.0 if aligned and trend.endswith("_STACK") else 0.0

    return round(
        min(100.0, alignment_points + price_points + slow_points + stack_points), 1
    )


def rsi_confluence_score(
    rsi: Optional[float],
    direction: Optional[str] = None,
    ema_trend: Optional[str] = None,
) -> float:
    """Contextual RSI score: extremes only count when the EMA trend agrees.

    * RSI 30-70: neutral zone -> deliberately modest score (45-55).
    * RSI < 30: strong BUY evidence only in a bullish stack; otherwise a
      weaker mean-reversion score (60). Against a BUY it stays low.
    * RSI > 70: strong SELL evidence only in a bearish stack; symmetric rules.
    """
    rsi_f = _to_float(rsi)
    if rsi_f is None:
        return 50.0

    trend = ema_trend or "NEUTRAL"
    trade_dir = _direction_value(direction, trend)
    if trade_dir == 0:
        return 50.0

    trend_aligned = (
        (trade_dir > 0 and "BULLISH" in trend)
        or (trade_dir < 0 and "BEARISH" in trend)
    )

    if trade_dir > 0:  # BUY
        if rsi_f < 30.0:
            return 95.0 if trend_aligned else 60.0
        if rsi_f > 70.0:
            return 20.0  # overbought is hostile to a fresh long
        return round(45.0 + ((rsi_f - 30.0) / 40.0) * 10.0, 1)

    # SELL
    if rsi_f > 70.0:
        return 95.0 if trend_aligned else 60.0
    if rsi_f < 30.0:
        return 20.0  # oversold is hostile to a fresh short
    return round(55.0 - ((rsi_f - 30.0) / 40.0) * 10.0, 1)


def adx_confluence_score(adx: Optional[float]) -> float:
    """Grade trend strength without ever awarding a perfect 100."""
    adx_f = _to_float(adx)
    if adx_f is None:
        return 50.0
    if adx_f < 20.0:
        return 25.0
    if adx_f < 25.0:
        return round(45.0 + (adx_f - 20.0) * 4.0, 1)
    if adx_f < 50.0:
        return round(min(95.0, 65.0 + (adx_f - 25.0) * 1.2), 1)
    return 95.0


def calculate_confluence(
    price: Optional[float],
    ema_fast: Optional[float],
    ema_mid: Optional[float],
    rsi: Optional[float],
    adx: Optional[float],
    ema_slow: Optional[float] = None,
    direction: Optional[str] = None,
) -> ConfluenceResult:
    """Weighted 40/30/30 confluence score in the 0-100 range."""
    trend = classify_ema_trend(price, ema_fast, ema_mid, ema_slow)
    ema_score = ema_confluence_score(price, ema_fast, ema_mid, ema_slow, direction)
    rsi_score = rsi_confluence_score(rsi, direction, trend)
    adx_score = adx_confluence_score(adx)
    score = (
        EMA_WEIGHT * ema_score
        + RSI_WEIGHT * rsi_score
        + ADX_WEIGHT * adx_score
    )
    return ConfluenceResult(
        score=round(min(MAX_CONFLUENCE_SCORE, max(0.0, score)), 1),
        ema_score=ema_score,
        rsi_score=rsi_score,
        adx_score=adx_score,
        ema_trend=trend,
    )


def calculate_ai_confidence(
    confluence_score: Optional[float],
    adx: Optional[float] = None,
    historical_win_rate: Optional[float] = None,
    volatility_pct: Optional[float] = None,
) -> int:
    """Bounded, explainable confidence in the 60-95% range.

    Factors: signal strength (the graded confluence score), ADX regime
    confirmation, observed historical win rate (0.5 when unknown) and a
    realized-volatility penalty. The hard clamp guarantees it never prints
    100%.
    """
    score = _to_float(confluence_score)
    if score is None:
        return 60

    win_rate = _to_float(historical_win_rate)
    if win_rate is None:
        win_rate = 0.5
    win_rate = min(1.0, max(0.0, win_rate))

    base = CONFIDENCE_MIN + (min(100.0, max(0.0, score)) / 100.0) * 30.0
    regime_adjustment = 3.0 if (_to_float(adx) or 0.0) >= 25.0 else -3.0
    win_rate_adjustment = (win_rate - 0.5) * 12.0

    volatility_penalty = 0.0
    volatility = _to_float(volatility_pct)
    if volatility is not None and volatility > 1.0:
        volatility_penalty = min(8.0, (volatility - 1.0) * 4.0)

    confidence = (
        base + regime_adjustment + win_rate_adjustment - volatility_penalty
    )
    return int(round(min(CONFIDENCE_MAX, max(CONFIDENCE_MIN, confidence))))
