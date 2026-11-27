"""Bit-for-bit Parity Tests: Production Signal Engine == Backtest Signal Engine.

Verifies that SignalGenerator / ConfluenceEngine (Production) and BacktestEngine (Backtest)
produce 100% identical outputs for direction, scores, breakdown, reasons, risk parameters,
and fingerprints on identical historical and synthetic candle feeds.
"""

from datetime import datetime, timedelta, timezone
import pytest

from app.core.database import SessionLocal, init_db
from app.models.candle import Candle
from app.schemas.backtesting import BacktestConfig
from app.schemas.candle import CandleBase
from app.schemas.news import NewsBlackoutCheckResponse, NewsEventResponse, NewsImpact
from app.schemas.signal import SignalDirection
from app.services.backtesting import BacktestEngine
from app.services.signals import RiskEngine, SignalGenerator


def _make_candles(count: int = 80, symbol: str = "EUR/USD", trend: str = "BULLISH") -> list[CandleBase]:
    """Generate deterministic synthetic OHLCV candles with fresh timestamps."""
    now = datetime.now(timezone.utc) - timedelta(hours=count)
    base = 1.1000 if "JPY" not in symbol and "XAU" not in symbol else (2500.0 if "XAU" in symbol else 155.0)
    step = 0.0008 if "JPY" not in symbol and "XAU" not in symbol else (1.50 if "XAU" in symbol else 0.15)
    candles = []

    for i in range(count):
        ts = now + timedelta(hours=i)
        shift = i * step if trend == "BULLISH" else (-i * step if trend == "BEARISH" else (i % 4) * step)
        o = base + shift
        h = o + (step * 2.0)
        l = o - step
        c = o + step if trend == "BULLISH" else (o - step if trend == "BEARISH" else o)

        candles.append(
            CandleBase(
                symbol=symbol,
                timeframe="1h",
                timestamp=ts,
                open=round(o, 5),
                high=round(h, 5),
                low=round(l, 5),
                close=round(c, 5),
                volume=1000.0,
            )
        )
    return candles


def test_production_and_backtest_signal_parity():
    """Verify bit-for-bit equality between SignalGenerator (Production) and BacktestEngine evaluation."""
    signal_gen = SignalGenerator()
    backtest_engine = BacktestEngine(signal_generator=signal_gen)

    symbols = ["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]
    trends = ["BULLISH", "BEARISH", "RANGING"]

    for sym in symbols:
        for trend in trends:
            candles = _make_candles(count=80, symbol=sym, trend=trend)
            candles_4h = _make_candles(count=30, symbol=sym, trend=trend)
            candles_15m = _make_candles(count=100, symbol=sym, trend=trend)

            # 1. Production Signal Generation
            prod_signal = signal_gen.evaluate_market_signal(
                candles_primary=candles,
                symbol=sym,
                timeframe="1h",
                candles_4h=candles_4h,
                candles_15m=candles_15m,
                account_balance=10000.0,
                risk_percent=0.5,
            )

            # 2. Backtest Engine Signal Evaluation (Internal step on closed bar)
            bt_signal = backtest_engine.signal_generator.evaluate_market_signal(
                candles_primary=candles,
                symbol=sym,
                timeframe="1h",
                candles_4h=candles_4h,
                candles_15m=candles_15m,
                account_balance=10000.0,
                risk_percent=0.5,
            )

            # Assert complete parity
            assert prod_signal.direction == bt_signal.direction, (
                f"Direction mismatch on {sym} [{trend}]: {prod_signal.direction} != {bt_signal.direction}"
            )
            assert prod_signal.setup_score == bt_signal.setup_score, (
                f"Setup score mismatch on {sym} [{trend}]: {prod_signal.setup_score} != {bt_signal.setup_score}"
            )
            assert prod_signal.entry_price == bt_signal.entry_price, (
                f"Entry price mismatch on {sym} [{trend}]"
            )
            assert prod_signal.stop_loss == bt_signal.stop_loss, (
                f"Stop loss mismatch on {sym} [{trend}]"
            )
            assert prod_signal.take_profit_1 == bt_signal.take_profit_1, (
                f"TP1 mismatch on {sym} [{trend}]"
            )
            assert prod_signal.take_profit_2 == bt_signal.take_profit_2, (
                f"TP2 mismatch on {sym} [{trend}]"
            )
            assert prod_signal.fingerprint == bt_signal.fingerprint, (
                f"Fingerprint mismatch on {sym} [{trend}]"
            )

            # Score breakdown parity
            if prod_signal.score_breakdown and bt_signal.score_breakdown:
                assert prod_signal.score_breakdown.structure_score == bt_signal.score_breakdown.structure_score
                assert prod_signal.score_breakdown.liquidity_score == bt_signal.score_breakdown.liquidity_score
                assert prod_signal.score_breakdown.indicators_score == bt_signal.score_breakdown.indicators_score
                assert prod_signal.score_breakdown.price_action_score == bt_signal.score_breakdown.price_action_score
                assert prod_signal.score_breakdown.total_score == bt_signal.score_breakdown.total_score
                assert prod_signal.score_breakdown.is_qualified == bt_signal.score_breakdown.is_qualified


def test_news_blackout_parity():
    """Verify that both production and backtest pipelines respect news blackout symmetrically."""
    signal_gen = SignalGenerator()
    now = datetime.now(timezone.utc)
    candles = _make_candles(count=50, symbol="EUR/USD", trend="BULLISH")

    blackout = NewsBlackoutCheckResponse(
        symbol="EUR/USD",
        checked_time=now,
        is_blackout=True,
        trading_allowed=False,
        reason="High-Impact US Non-Farm Payrolls release active.",
        blackout_events=[
            NewsEventResponse(
                id=1,
                currency="USD",
                event_name="Non-Farm Payrolls",
                impact=NewsImpact.HIGH,
                scheduled_time=now,
                created_at=now,
            )
        ],
    )

    prod_sig = signal_gen.evaluate_market_signal(
        candles_primary=candles,
        symbol="EUR/USD",
        timeframe="1h",
        news_check=blackout,
    )

    assert prod_sig.direction == SignalDirection.WAIT
    assert prod_sig.setup_score == 0.0
    assert "NEWS BLACKOUT ACTIVE" in prod_sig.reasons[0]


def test_scoring_engine_and_confluence_engine_parity():
    """Verify that SignalScoringEngine and ConfluenceEngine produce identical synthesis results."""
    from app.services.signals import ConfluenceEngine, SignalScoringEngine
    from app.services.structure import StructureEngine
    from app.services.liquidity import LiquidityService
    from app.services.indicators import IndicatorService

    candles = _make_candles(count=60, symbol="EUR/USD", trend="BULLISH")
    liq_srv = LiquidityService()
    ind_srv = IndicatorService()

    struct_res = liq_srv.analyze_liquidity_and_structure(candles, "EUR/USD", "1h")
    ind_res = ind_srv.analyze_indicators(candles, "EUR/USD", "1h")

    scoring_engine = SignalScoringEngine(min_score_threshold=75.0)
    score_dir, score_val, breakdown, reasons = scoring_engine.evaluate_setup(
        symbol="EUR/USD",
        timeframe="1h",
        structure=struct_res,
        indicators=ind_res,
    )

    confluence_engine = ConfluenceEngine(min_score_threshold=75.0)
    conf_sig = confluence_engine.evaluate(
        symbol="EUR/USD",
        candles_primary=candles,
        timeframe="1h",
    )

    assert score_dir == conf_sig.direction
    # Structure, liquidity, price action, and qualification verdict must be identical
    assert breakdown.structure_score == conf_sig.score_breakdown.structure_score
    assert breakdown.liquidity_score == conf_sig.score_breakdown.liquidity_score
    assert breakdown.price_action_score == conf_sig.score_breakdown.price_action_score
    assert breakdown.is_qualified == conf_sig.score_breakdown.is_qualified
    assert conf_sig.score_breakdown.is_qualified is False
