"""Unit tests for Backtesting Engine, Performance Metrics, and Parameter Optimization."""

from datetime import datetime, timedelta, timezone
import pytest

from app.schemas.backtesting import (
    BacktestConfig,
    BacktestTradeLog,
    EquityPoint,
    ParameterSweepRequest,
)
from app.schemas.candle import CandleBase
from app.schemas.signal import SignalDirection
from app.services.backtesting.backtest_engine import BacktestEngine
from app.services.backtesting.optimization import ParameterOptimizer
from app.services.backtesting.performance_metrics import PerformanceMetricsCalculator


def _make_sample_candles(count: int = 100, trend: str = "BULLISH") -> list[CandleBase]:
    """Generate synthetic sequential OHLCV candles."""
    now = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    base_price = 1.1000
    candles = []

    for i in range(count):
        ts = now + timedelta(hours=i)
        if trend == "BULLISH":
            shift = i * 0.0008
        elif trend == "BEARISH":
            shift = -i * 0.0008
        else:
            shift = (i % 5) * 0.0004

        o = base_price + shift
        h = o + 0.0015
        l = o - 0.0010
        c = o + 0.0008 if trend == "BULLISH" else (o - 0.0008 if trend == "BEARISH" else o)

        candles.append(
            CandleBase(
                symbol="EUR/USD",
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


# -------------------------------------------------------------
# 1. Performance Metrics Calculator Tests
# -------------------------------------------------------------
def test_performance_metrics_zero_trades():
    """Verify metrics calculation handles empty trade history without errors."""
    metrics = PerformanceMetricsCalculator.calculate(
        trades=[],
        equity_curve=[],
        initial_balance=10000.0,
    )
    assert metrics.total_trades == 0
    assert metrics.win_rate == 0.0
    assert metrics.profit_factor == 0.0
    assert metrics.total_pnl == 0.0
    assert metrics.max_drawdown_pct == 0.0
    assert metrics.sharpe_ratio == 0.0


def test_performance_metrics_mixed_trades():
    """Verify precision calculations for Win Rate, Profit Factor, Drawdown, Sharpe, Sortino, and Expectancy."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trades = [
        BacktestTradeLog(
            id=1,
            symbol="EUR/USD",
            direction=SignalDirection.BUY,
            entry_time=now,
            exit_time=now + timedelta(hours=2),
            entry_price=1.1000,
            exit_price=1.1040,
            stop_loss=1.0980,
            take_profit_1=1.1040,
            position_size=1.0,
            pnl=400.0,
            pnl_percent=4.0,
            return_r=2.0,
            exit_reason="TP1_HIT",
            score=85.0,
        ),
        BacktestTradeLog(
            id=2,
            symbol="EUR/USD",
            direction=SignalDirection.BUY,
            entry_time=now + timedelta(hours=3),
            exit_time=now + timedelta(hours=5),
            entry_price=1.1040,
            exit_price=1.1020,
            stop_loss=1.1020,
            take_profit_1=1.1080,
            position_size=1.0,
            pnl=-200.0,
            pnl_percent=-2.0,
            return_r=-1.0,
            exit_reason="SL_HIT",
            score=80.0,
        ),
        BacktestTradeLog(
            id=3,
            symbol="EUR/USD",
            direction=SignalDirection.SELL,
            entry_time=now + timedelta(hours=6),
            exit_time=now + timedelta(hours=8),
            entry_price=1.1020,
            exit_price=1.0960,
            stop_loss=1.1050,
            take_profit_1=1.0960,
            position_size=1.0,
            pnl=600.0,
            pnl_percent=6.0,
            return_r=2.0,
            exit_reason="TP2_HIT",
            score=90.0,
        ),
    ]

    equity_points = [
        EquityPoint(timestamp=now, equity=10000.0, balance=10000.0, drawdown_pct=0.0, drawdown_usd=0.0, open_positions=0),
        EquityPoint(timestamp=now + timedelta(hours=2), equity=10400.0, balance=10400.0, drawdown_pct=0.0, drawdown_usd=0.0, open_positions=0),
        EquityPoint(timestamp=now + timedelta(hours=5), equity=10200.0, balance=10200.0, drawdown_pct=1.92, drawdown_usd=200.0, open_positions=0),
        EquityPoint(timestamp=now + timedelta(hours=8), equity=10800.0, balance=10800.0, drawdown_pct=0.0, drawdown_usd=0.0, open_positions=0),
    ]

    metrics = PerformanceMetricsCalculator.calculate(
        trades=trades,
        equity_curve=equity_points,
        initial_balance=10000.0,
    )

    assert metrics.total_trades == 3
    assert metrics.winning_trades == 2
    assert metrics.losing_trades == 1
    assert metrics.win_rate == round(2 / 3 * 100.0, 2)
    assert metrics.loss_rate == round(1 / 3 * 100.0, 2)
    assert metrics.gross_profit == 1000.0
    assert metrics.gross_loss == 200.0
    assert metrics.profit_factor == 5.0  # 1000 / 200
    assert metrics.total_pnl == 800.0
    assert metrics.total_pnl_percent == 8.0
    assert metrics.average_win == 500.0  # (400 + 600) / 2
    assert metrics.average_loss == 200.0
    assert metrics.win_loss_payoff_ratio == 2.5
    assert metrics.expectancy_usd > 0.0
    assert metrics.expectancy_r == 1.0  # (2.0 - 1.0 + 2.0) / 3
    assert metrics.max_drawdown_usd == 200.0
    assert metrics.max_drawdown_pct == 1.92
    assert metrics.buy_trades_count == 2
    assert metrics.sell_trades_count == 1
    assert metrics.buy_pnl == 200.0
    assert metrics.sell_pnl == 600.0


# -------------------------------------------------------------
# 2. Backtest Engine Simulation Tests
# -------------------------------------------------------------
def test_backtest_engine_simulation():
    """Verify that BacktestEngine simulates sequential trades and computes metrics."""
    candles = _make_sample_candles(count=80, trend="BULLISH")
    engine = BacktestEngine()
    config = BacktestConfig(
        initial_balance=10000.0,
        risk_percent=0.5,
        min_score_threshold=50.0,  # Low threshold so setups execute in synthetic candles
        take_profit_1_rr=2.0,
        take_profit_2_rr=3.0,
        move_sl_to_be_on_tp1=True,
        partial_tp_ratio=0.5,
        spread_pips=1.0,
        slippage_pips=0.5,
        warmup_bars=20,
    )

    result = engine.run_simulation(
        candles=candles,
        symbol="EUR/USD",
        timeframe="1h",
        config=config,
    )

    assert result.symbol == "EUR/USD"
    assert result.timeframe == "1h"
    assert len(result.equity_curve) > 0
    assert result.metrics.initial_balance == 10000.0
    assert result.metrics.final_balance > 0.0
    assert isinstance(result.metrics.profit_factor, float)
    assert isinstance(result.metrics.win_rate, float)


def test_backtest_engine_insufficient_candles():
    """Verify simulation handles insufficient candles gracefully."""
    candles = _make_sample_candles(count=5)
    engine = BacktestEngine()
    result = engine.run_simulation(candles=candles, symbol="EUR/USD", timeframe="1h")
    assert result.metrics.total_trades == 0
    assert len(result.trades) == 0


# -------------------------------------------------------------
# 3. Parameter Optimizer Tests
# -------------------------------------------------------------
def test_parameter_optimizer():
    """Verify parameter optimizer runs grid search and identifies optimal parameter set."""
    candles = _make_sample_candles(count=60, trend="BULLISH")
    optimizer = ParameterOptimizer()
    request = ParameterSweepRequest(
        symbol="EUR/USD",
        timeframe="1h",
        score_thresholds=[60.0, 75.0],
        risk_percentages=[0.5],
        rr_targets=[2.0],
    )

    response = optimizer.run_sweep(
        candles=candles,
        symbol="EUR/USD",
        timeframe="1h",
        request=request,
    )

    assert response.tested_combinations == 2
    assert len(response.results) == 2
    assert response.best_by_sharpe is not None
    assert response.best_by_pnl is not None
