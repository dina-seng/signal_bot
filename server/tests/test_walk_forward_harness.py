"""Unit tests for Walk-Forward Historical Backtest Harness and Signal Candidate Logging."""

from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select

from app.models.candle import Candle
from app.models.signal_candidate import SignalCandidate
from app.schemas.signal import SignalDirection
from app.services.backtesting.walk_forward_harness import (
    WalkForwardHarness,
    get_utc_session,
    get_timeframe_delta,
)


def _generate_synthetic_candles(
    count: int = 80,
    timeframe: str = "15m",
    symbol: str = "XAU/USD",
    source: str = "twelvedata",
    start_time: datetime = None,
    base_price: float = 2500.0,
) -> list[Candle]:
    """Helper to generate sequential candles with deterministic price variation."""
    if start_time is None:
        start_time = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    delta = get_timeframe_delta(timeframe)

    candles = []
    p = base_price
    for i in range(count):
        # gentle oscillation
        change = 0.5 if i % 2 == 0 else -0.4
        open_p = p
        high_p = p + 2.0
        low_p = p - 2.0
        close_p = p + change
        p = close_p

        c = Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=start_time + (i * delta),
            open=round(open_p, 2),
            high=round(high_p, 2),
            low=round(low_p, 2),
            close=round(close_p, 2),
            volume=500.0,
            source=source,
        )
        candles.append(c)
    return candles


def test_walk_forward_refuses_mixed_data_sources():
    """Verify backtest harness strictly refuses to mix different data sources."""
    harness = WalkForwardHarness()

    candles_twelve = _generate_synthetic_candles(count=20, source="twelvedata")
    candles_yahoo = _generate_synthetic_candles(count=20, source="yfinance")

    mixed = candles_twelve + candles_yahoo

    with pytest.raises(ValueError, match="Mixed data sources detected"):
        harness.validate_data_sources(candles_15m=mixed)


def test_walk_forward_source_consistency_enforced():
    """Verify backtest accepts single consistent data source."""
    harness = WalkForwardHarness()
    candles_twelve = _generate_synthetic_candles(count=30, source="twelvedata")

    src = harness.validate_data_sources(candles_15m=candles_twelve, requested_source="twelvedata")
    assert src == "twelvedata"

    # Mismatched requested source raises ValueError
    with pytest.raises(ValueError, match="Requested data source 'yfinance' does not match"):
        harness.validate_data_sources(candles_15m=candles_twelve, requested_source="yfinance")


def test_sl_and_tp_in_same_bar_assumes_sl_first():
    """Verify that if a single bar touches both SL and TP, the harness assumes SL first."""
    harness = WalkForwardHarness()
    base_t = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)

    # Entry at bar 0: BUY at 2500.00, SL=2495.00, TP1=2510.00
    # Bar 1: Low dips to 2490.00 (below SL) AND High spikes to 2515.00 (above TP1)
    bar0 = Candle(
        symbol="XAU/USD", timeframe="15m", timestamp=base_t,
        open=2499.0, high=2501.0, low=2498.0, close=2500.0, source="twelvedata",
    )
    bar1 = Candle(
        symbol="XAU/USD", timeframe="15m", timestamp=base_t + timedelta(minutes=15),
        open=2500.0, high=2515.0, low=2490.0, close=2505.0, source="twelvedata",
    )

    candles = [bar0, bar1]

    outcome = harness.simulate_outcome(
        entry_bar_idx=0,
        direction=SignalDirection.BUY,
        entry_price=2500.0,
        stop_loss=2495.0,
        take_profit_1=2510.0,
        candles_15m=candles,
        spread_usd=0.30,
        slippage_usd=0.10,
    )

    # Conservative execution rule: must register SL_HIT, NOT TP1_HIT
    assert outcome.hit_sl is True
    assert outcome.exit_reason == "SL_HIT"
    assert outcome.r_multiple == -1.0
    assert outcome.exit_price == 2494.90  # 2495.0 - 0.10 slippage


def test_session_detection_utc():
    """Verify UTC-based session identification (Asia, London, NY)."""
    # 03:00 UTC -> Asia
    dt_asia = datetime(2026, 8, 1, 3, 0, tzinfo=timezone.utc)
    assert get_utc_session(dt_asia) == "Asia"

    # 09:30 UTC -> London
    dt_london = datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc)
    assert get_utc_session(dt_london) == "London"

    # 15:00 UTC -> NY
    dt_ny = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)
    assert get_utc_session(dt_ny) == "NY"


def test_walk_forward_logs_every_candidate_and_splits_train_test(test_db_session):
    """Verify walk-forward backtest logs all candidates to signal_candidates and computes 70/30 train/test metrics."""
    harness = WalkForwardHarness()
    c15 = _generate_synthetic_candles(count=90, timeframe="15m", base_price=2500.0)
    c1h = _generate_synthetic_candles(count=30, timeframe="1h", base_price=2500.0)
    c4h = _generate_synthetic_candles(count=20, timeframe="4h", base_price=2500.0)

    res = harness.run_walk_forward(
        candles_15m=c15,
        candles_1h=c1h,
        candles_4h=c4h,
        symbol="XAU/USD",
        source="twelvedata",
        spread_usd=0.30,
        slippage_usd=0.10,
        warmup_bars=30,
        db=test_db_session,
    )

    # Total evaluated candidates must be logged (>= 1 per evaluated bar)
    assert res.total_candidates_logged > 0
    assert len(res.candidates) == res.total_candidates_logged

    # Verify rows persisted into database table signal_candidates
    logged_in_db = list(test_db_session.scalars(select(SignalCandidate)).all())
    assert len(logged_in_db) == res.total_candidates_logged

    # Verify required feature columns populated on candidate row
    first_cand = logged_in_db[0]
    assert first_cand.symbol == "XAU/USD"
    assert first_cand.timeframe == "15m"
    assert first_cand.direction in ("BUY", "SELL", "WAIT")
    assert first_cand.session in ("Asia", "London", "NY")
    assert first_cand.structure_score >= 0.0
    assert first_cand.liquidity_score >= 0.0
    assert first_cand.indicators_score >= 0.0
    assert first_cand.price_action_score >= 0.0
    assert first_cand.final_score >= 0.0
    assert isinstance(first_cand.qualified, bool)

    # Verify Train/Test metrics exist
    assert hasattr(res.train_metrics, "trade_count")
    assert hasattr(res.test_metrics, "trade_count")
    assert hasattr(res.train_baseline_metrics, "win_rate")
    assert hasattr(res.test_baseline_metrics, "expectancy_r")

    # Verify session breakdown exists
    assert "Asia" in res.session_breakdown
    assert "London" in res.session_breakdown
    assert "NY" in res.session_breakdown


def test_historical_candles_from_6_months_ago_with_as_of_not_stale():
    """STEP B verification: candles from 6 months ago evaluated with as_of at that time must NOT be vetoed as stale."""
    # 6 months ago in UTC
    six_months_ago = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)
    delta_15m = timedelta(minutes=15)
    candles = []
    p = 2500.0
    for i in range(50):
        c = Candle(
            symbol="XAU/USD",
            timeframe="15m",
            timestamp=six_months_ago + (i * delta_15m),
            open=p,
            high=p + 1.5,
            low=p - 1.5,
            close=p + 0.5,
            volume=100.0,
            source="dukascopy",
        )
        candles.append(c)
        p += 0.5

    simulated_close = candles[-1].timestamp + delta_15m

    # 1. Direct staleness check with as_of
    from app.services.market_data.freshness import check_data_staleness
    staleness = check_data_staleness(candles, symbol="XAU/USD", timeframe="15m", as_of=simulated_close)
    assert staleness.is_stale is False
    assert staleness.age_hours < 0.1

    # 2. End-to-end signal generator evaluation with as_of and backtest_mode
    from app.services.signals import SignalGenerator
    sig_gen = SignalGenerator()
    resp = sig_gen.evaluate_market_signal(
        candles_primary=candles,
        symbol="XAU/USD",
        timeframe="15m",
        as_of=simulated_close,
        backtest_mode=True,
    )
    # Must NOT contain 'DATA TOO STALE' veto
    assert not any("DATA TOO STALE" in r for r in resp.reasons)
    assert not any("NEWS BLACKOUT ACTIVE" in r for r in resp.reasons)


def test_realistic_trade_simulation_position_active_and_cooldown():
    """STEP C verification: one position open at a time + cooldown between trades + skipped_reason logged."""
    harness = WalkForwardHarness()
    base_t = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    c15 = _generate_synthetic_candles(count=120, timeframe="15m", start_time=base_t, base_price=2500.0)

    res = harness.run_walk_forward(
        candles_15m=c15,
        symbol="XAU/USD",
        source="twelvedata",
        warmup_bars=30,
        min_score_threshold=0.0,  # force every actionable candidate to qualify to test collision/cooldown logic
    )

    # Every logged candidate must have a skipped_reason key
    for cand in res.candidates:
        assert "skipped_reason" in cand
        if cand["qualified"]:
            assert cand["skipped_reason"] in (None, "POSITION_ACTIVE", "COOLDOWN_ACTIVE")

    # Executed trades must only contain candidates where skipped_reason is None
    assert res.executed_trades_count <= res.qualified_candidates_count
    # All executed trades must have skipped_reason == None
    executed = [c for c in res.candidates if c["qualified"] and c["skipped_reason"] is None]
    assert len(executed) == res.executed_trades_count
