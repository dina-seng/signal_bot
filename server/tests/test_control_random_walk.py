"""Control Test: Synthetic Random-Walk XAU/USD Series.

STEP E:
Verifies that running the full backtest harness on a synthetic random-walk series with
realistic volatility produces expectancy approximately minus transaction costs (spread + slippage),
and strictly does NOT show meaningful positive expectancy (which would indicate a lookahead leak).
"""

from datetime import datetime, timedelta, timezone
import math
import random
import pytest

from app.models.candle import Candle
from app.scripts.import_history import resample_bars
from app.services.backtesting.walk_forward_harness import WalkForwardHarness


def generate_synthetic_random_walk(
    bar_count: int = 800,
    base_price: float = 2500.0,
    volatility: float = 2.0,
    start_time: datetime = None,
    seed: int = 12345,
) -> tuple[list[Candle], list[Candle], list[Candle]]:
    """Generate a geometric random walk series for 15m, 1h, and 4h bars."""
    if start_time is None:
        start_time = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    delta_15m = timedelta(minutes=15)

    rng = random.Random(seed)
    current_price = base_price

    bars_15m_dict = []
    for i in range(bar_count):
        bar_t = start_time + (i * delta_15m)
        open_p = current_price

        # Gaussian innovation
        shock = rng.gauss(0.0, volatility)
        close_p = open_p + shock

        # Realistic high and low excursions
        wick_high = abs(rng.gauss(0.0, volatility * 0.6))
        wick_low = abs(rng.gauss(0.0, volatility * 0.6))
        high_p = max(open_p, close_p) + wick_high
        low_p = min(open_p, close_p) - wick_low

        bars_15m_dict.append({
            "timestamp": bar_t,
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "volume": 500.0,
        })
        current_price = close_p

    # Resample 1h and 4h
    bars_1h_dict = resample_bars(bars_15m_dict, "1h")
    bars_4h_dict = resample_bars(bars_15m_dict, "4h")

    candles_15m = [Candle(symbol="XAU/USD", timeframe="15m", source="random_walk", **b) for b in bars_15m_dict]
    candles_1h = [Candle(symbol="XAU/USD", timeframe="1h", source="random_walk", **b) for b in bars_1h_dict]
    candles_4h = [Candle(symbol="XAU/USD", timeframe="4h", source="random_walk", **b) for b in bars_4h_dict]

    return candles_15m, candles_1h, candles_4h


def test_random_walk_control_shows_no_positive_edge():
    """Verify that on a random walk with spread and slippage, the strategy shows no meaningful positive expectancy."""
    # 600 bars produced only 2 trades -- a statistically meaningless sample
    # (BT-028). 12,000 bars yields ~53 trades with this seed, enough for the
    # expectancy/false-edge control to be interpretable.
    c15, c1h, c4h = generate_synthetic_random_walk(bar_count=12000, volatility=2.2, seed=55)
    harness = WalkForwardHarness()

    res = harness.run_walk_forward(
        candles_15m=c15,
        candles_1h=c1h,
        candles_4h=c4h,
        symbol="XAU/USD",
        source="random_walk",
        spread_usd=0.30,
        slippage_usd=0.10,
        warmup_bars=50,
    )

    # Collect all executed trades
    executed = [c for c in res.candidates if c["qualified"] and c["skipped_reason"] is None]

    if executed:
        r_multiples = [c["r_multiple"] for c in executed if c["r_multiple"] is not None]
        overall_metrics = harness.calculate_metrics(r_multiples)

        # Transaction friction rule: On random noise with spread and slippage,
        # expectancy must NOT be meaningfully positive (<= 0.05R) and should reflect
        # transaction friction (win rate ~ 33.3% on 2:1 RR).
        assert overall_metrics.expectancy_r <= 0.05, (
            f"LEAK DETECTED: Random walk generated positive expectancy {overall_metrics.expectancy_r:.2f}R! "
            f"On random data, expectancy should be negative or near zero due to spread & slippage."
        )

        # Expectancy stays non-positive after transaction friction
        assert overall_metrics.expectancy_r <= 0.0
        assert overall_metrics.profit_factor <= 1.05
