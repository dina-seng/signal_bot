"""Tests for graded confluence scoring and bounded AI confidence."""

import pytest

from app.services.indicators.ema_calculator import classify_ema_trend
from app.services.signals.confluence_scoring import (
    calculate_ai_confidence,
    calculate_confluence,
    ema_confluence_score,
    rsi_confluence_score,
)


BULLISH = dict(
    price=61_000.0, ema_fast=60_500.0, ema_mid=60_000.0,
    ema_slow=59_000.0, rsi=58.0, adx=32.0,
)
BEARISH = dict(
    price=59_204.37, ema_fast=59_814.08, ema_mid=60_167.90,
    ema_slow=60_734.95, rsi=31.53, adx=49.94,
)
NEUTRAL = dict(
    price=60_000.0, ema_fast=60_050.0, ema_mid=60_000.0,
    ema_slow=60_000.0, rsi=50.0, adx=18.0,
)


def test_ema_trend_uses_fast_mid_and_price_not_ema200():
    """EMA20 > EMA50 + price > EMA20 is bullish even when below EMA200."""
    assert classify_ema_trend(60_100.0, 60_050.0, 60_000.0, 61_000.0) == "BULLISH_STACK"
    assert classify_ema_trend(59_900.0, 59_950.0, 60_000.0, 59_000.0) == "BEARISH_STACK"
    assert classify_ema_trend(60_020.0, 60_050.0, 60_000.0) == "BULLISH_BIAS"
    assert classify_ema_trend(**{k: v for k, v in BEARISH.items() if k != "rsi" and k != "adx"}) == "BEARISH_STACK"


def test_scores_are_dynamic_and_never_a_hardcoded_100():
    bull = calculate_confluence(**BULLISH, direction="BUY")
    bear = calculate_confluence(**BEARISH, direction="SELL")
    neutral = calculate_confluence(**NEUTRAL, direction="BUY")

    assert 0.0 <= bull.score <= 99.0
    assert 0.0 <= bear.score <= 99.0
    assert 0.0 <= neutral.score <= 99.0
    assert len({bull.score, bear.score, neutral.score}) == 3
    assert bull.score > neutral.score
    assert bear.score > neutral.score


def test_rsi_is_contextual_not_unconditionally_bullish():
    oversold = 28.0  # strictly below the 30 threshold
    # Oversold only helps a BUY when the EMA trend is bullish.
    assert rsi_confluence_score(oversold, "BUY", "BULLISH_STACK") == 95.0
    assert rsi_confluence_score(oversold, "BUY", "BEARISH_STACK") == 60.0
    # Neutral 30-70 zone stays modest -- including the reported RSI 31.5 case,
    # which must NOT be treated as a perfect-score catalyst.
    assert 45.0 <= rsi_confluence_score(50.0, "BUY", "BULLISH_STACK") <= 55.0
    assert rsi_confluence_score(31.5, "BUY", "BULLISH_STACK") < 50.0
    # Oversold is hostile to a fresh short.
    assert rsi_confluence_score(oversold, "SELL", "BEARISH_STACK") == 20.0


def test_ema_score_is_graded_not_binary():
    strong = ema_confluence_score(61_000.0, 60_500.0, 60_000.0, 59_000.0, "BUY")
    weak = ema_confluence_score(60_010.0, 60_050.0, 60_000.0, 60_000.0, "BUY")
    assert strong > weak


def test_ai_confidence_is_bounded_and_varies():
    bull = calculate_confluence(**BULLISH, direction="BUY")
    neutral = calculate_confluence(**NEUTRAL, direction="BUY")
    high = calculate_ai_confidence(bull.score, bull.adx_score, 0.70, 0.8)
    low = calculate_ai_confidence(neutral.score, neutral.adx_score, 0.40, 3.0)

    assert 60 <= high <= 95
    assert 60 <= low <= 95
    assert high > low
    assert high != 100 and low != 100

    # Even perfect inputs cannot produce certainty.
    assert calculate_ai_confidence(100.0, 60.0, 1.0, 0.0) <= 95
