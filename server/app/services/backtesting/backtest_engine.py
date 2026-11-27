"""Event-driven / Candle-by-candle Backtest Simulation Engine."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Union

from app.core.logging import logger
from app.schemas.backtesting import (
    BacktestConfig,
    BacktestResultResponse,
    BacktestTradeLog,
    EquityPoint,
    PerformanceMetrics,
)
from app.schemas.candle import CandleBase
from app.schemas.signal import SignalDirection
from app.services.backtesting.performance_metrics import PerformanceMetricsCalculator
from app.services.signals import RiskEngine, SignalGenerator


@dataclass
class _SimPosition:
    """Internal backtest position tracking."""
    position_id: int
    symbol: str
    direction: SignalDirection
    entry_time: datetime
    entry_price: float
    initial_sl: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    initial_size: float
    current_size: float
    initial_risk_usd: float
    score: float
    tp1_hit: bool = False
    realized_pnl_so_far: float = 0.0


class BacktestEngine:
    """Institutional candle-by-candle backtesting simulation engine."""

    def __init__(
        self,
        signal_generator: Optional[SignalGenerator] = None,
        risk_engine: Optional[RiskEngine] = None,
    ):
        self.signal_generator = signal_generator or SignalGenerator()
        self.risk_engine = risk_engine or RiskEngine()

    def run_simulation(
        self,
        candles: Sequence[Union[CandleBase, Any]],
        symbol: str = "XAU/USD",
        timeframe: str = "1h",
        config: Optional[BacktestConfig] = None,
        candles_4h: Optional[Sequence[Union[CandleBase, Any]]] = None,
        candles_15m: Optional[Sequence[Union[CandleBase, Any]]] = None,
        name: Optional[str] = None,
    ) -> BacktestResultResponse:
        """Run candle-by-candle backtest simulation on historical candles.

        Args:
            candles: Chronologically sorted OHLCV candle sequence.
            symbol: Forex / Commodity pair symbol (e.g. 'EUR/USD').
            timeframe: Candle timeframe (e.g. '1h').
            config: Simulation configuration options.
            candles_4h: Optional 4h candles for MTF alignment.
            candles_15m: Optional 15m candles for MTF alignment.
            name: Optional descriptive label for the backtest.

        Returns:
            BacktestResultResponse containing metrics, equity curve, and trade logs.
        """
        cfg = config or BacktestConfig()
        pip_size = RiskEngine.get_pip_size(symbol)
        pip_val = RiskEngine.get_pip_value_per_lot(symbol)
        half_spread_and_slippage = (cfg.spread_pips / 2.0 + cfg.slippage_pips) * pip_size

        current_balance = float(cfg.initial_balance)
        peak_equity = float(cfg.initial_balance)
        open_positions: List[_SimPosition] = []
        closed_trades: List[BacktestTradeLog] = []
        equity_curve: List[EquityPoint] = []
        trade_counter = 0

        total_candles = len(candles)
        warmup = min(cfg.warmup_bars, max(10, total_candles // 4))

        if total_candles < warmup + 5:
            # Not enough data to run simulation
            empty_metrics = PerformanceMetricsCalculator.calculate(
                trades=[],
                equity_curve=[],
                initial_balance=cfg.initial_balance,
            )
            return BacktestResultResponse(
                name=name or f"{symbol} {timeframe} Backtest",
                symbol=symbol,
                timeframe=timeframe,
                start_date=candles[0].timestamp if candles else None,
                end_date=candles[-1].timestamp if candles else None,
                config=cfg,
                metrics=empty_metrics,
                equity_curve=[],
                trades=[],
            )

        # Main Candle-by-Candle Simulation Loop
        for i in range(warmup, total_candles):
            current_bar = candles[i]
            bar_ts = current_bar.timestamp
            bar_open = float(current_bar.open)
            bar_high = float(current_bar.high)
            bar_low = float(current_bar.low)
            bar_close = float(current_bar.close)

            # -------------------------------------------------------------
            # Step 1: Evaluate Active Open Positions against current candle
            # -------------------------------------------------------------
            remaining_positions: List[_SimPosition] = []

            for pos in open_positions:
                pos_closed = False

                if pos.direction == SignalDirection.BUY:
                    # 1. Stop Loss check (conservative: check SL first)
                    if bar_low <= pos.stop_loss:
                        exit_price = round(pos.stop_loss - half_spread_and_slippage, 5)
                        exit_reason = "BREAK_EVEN" if pos.tp1_hit else "SL_HIT"
                        pips_diff = (exit_price - pos.entry_price) / pip_size
                        leg_pnl = round(
                            (pips_diff * pip_val * pos.current_size)
                            - (pos.current_size * cfg.commission_per_lot),
                            2,
                        )
                        total_trade_pnl = round(pos.realized_pnl_so_far + leg_pnl, 2)
                        pnl_pct = round((total_trade_pnl / current_balance) * 100.0, 2)
                        ret_r = (
                            round(total_trade_pnl / pos.initial_risk_usd, 2)
                            if pos.initial_risk_usd > 0
                            else 0.0
                        )

                        current_balance = round(current_balance + leg_pnl, 2)
                        closed_trades.append(
                            BacktestTradeLog(
                                id=pos.position_id,
                                symbol=pos.symbol,
                                direction=pos.direction,
                                entry_time=pos.entry_time,
                                exit_time=bar_ts,
                                entry_price=pos.entry_price,
                                exit_price=exit_price,
                                stop_loss=pos.stop_loss,
                                take_profit_1=pos.take_profit_1,
                                take_profit_2=pos.take_profit_2,
                                position_size=pos.initial_size,
                                pnl=total_trade_pnl,
                                pnl_percent=pnl_pct,
                                return_r=ret_r,
                                exit_reason=exit_reason,
                                score=pos.score,
                            )
                        )
                        pos_closed = True

                    # 2. TP2 Target check
                    elif bar_high >= pos.take_profit_2:
                        exit_price = pos.take_profit_2
                        exit_reason = "TP2_HIT"
                        pips_diff = (exit_price - pos.entry_price) / pip_size
                        leg_pnl = round(
                            (pips_diff * pip_val * pos.current_size)
                            - (pos.current_size * cfg.commission_per_lot),
                            2,
                        )
                        total_trade_pnl = round(pos.realized_pnl_so_far + leg_pnl, 2)
                        pnl_pct = round((total_trade_pnl / current_balance) * 100.0, 2)
                        ret_r = (
                            round(total_trade_pnl / pos.initial_risk_usd, 2)
                            if pos.initial_risk_usd > 0
                            else 0.0
                        )

                        current_balance = round(current_balance + leg_pnl, 2)
                        closed_trades.append(
                            BacktestTradeLog(
                                id=pos.position_id,
                                symbol=pos.symbol,
                                direction=pos.direction,
                                entry_time=pos.entry_time,
                                exit_time=bar_ts,
                                entry_price=pos.entry_price,
                                exit_price=exit_price,
                                stop_loss=pos.stop_loss,
                                take_profit_1=pos.take_profit_1,
                                take_profit_2=pos.take_profit_2,
                                position_size=pos.initial_size,
                                pnl=total_trade_pnl,
                                pnl_percent=pnl_pct,
                                return_r=ret_r,
                                exit_reason=exit_reason,
                                score=pos.score,
                            )
                        )
                        pos_closed = True

                    # 3. TP1 Target check (partial close)
                    elif bar_high >= pos.take_profit_1 and not pos.tp1_hit:
                        if cfg.partial_tp_ratio >= 1.0:
                            # Full exit at TP1
                            exit_price = pos.take_profit_1
                            exit_reason = "TP1_HIT"
                            pips_diff = (exit_price - pos.entry_price) / pip_size
                            leg_pnl = round(
                                (pips_diff * pip_val * pos.current_size)
                                - (pos.current_size * cfg.commission_per_lot),
                                2,
                            )
                            total_trade_pnl = leg_pnl
                            pnl_pct = round((total_trade_pnl / current_balance) * 100.0, 2)
                            ret_r = (
                                round(total_trade_pnl / pos.initial_risk_usd, 2)
                                if pos.initial_risk_usd > 0
                                else 0.0
                            )

                            current_balance = round(current_balance + leg_pnl, 2)
                            closed_trades.append(
                                BacktestTradeLog(
                                    id=pos.position_id,
                                    symbol=pos.symbol,
                                    direction=pos.direction,
                                    entry_time=pos.entry_time,
                                    exit_time=bar_ts,
                                    entry_price=pos.entry_price,
                                    exit_price=exit_price,
                                    stop_loss=pos.stop_loss,
                                    take_profit_1=pos.take_profit_1,
                                    take_profit_2=pos.take_profit_2,
                                    position_size=pos.initial_size,
                                    pnl=total_trade_pnl,
                                    pnl_percent=pnl_pct,
                                    return_r=ret_r,
                                    exit_reason=exit_reason,
                                    score=pos.score,
                                )
                            )
                            pos_closed = True
                        else:
                            # Partial exit at TP1
                            close_lots = round(pos.initial_size * cfg.partial_tp_ratio, 2)
                            close_lots = max(0.01, min(pos.current_size, close_lots))
                            rem_lots = round(pos.current_size - close_lots, 2)

                            pips_diff = (pos.take_profit_1 - pos.entry_price) / pip_size
                            partial_pnl = round(
                                (pips_diff * pip_val * close_lots)
                                - (close_lots * cfg.commission_per_lot),
                                2,
                            )

                            pos.realized_pnl_so_far = round(pos.realized_pnl_so_far + partial_pnl, 2)
                            current_balance = round(current_balance + partial_pnl, 2)
                            pos.current_size = rem_lots
                            pos.tp1_hit = True

                            if cfg.move_sl_to_be_on_tp1:
                                # Move SL to Break-Even (Entry price)
                                pos.stop_loss = pos.entry_price

                else:  # SELL Position
                    # 1. Stop Loss check
                    if bar_high >= pos.stop_loss:
                        exit_price = round(pos.stop_loss + half_spread_and_slippage, 5)
                        exit_reason = "BREAK_EVEN" if pos.tp1_hit else "SL_HIT"
                        pips_diff = (pos.entry_price - exit_price) / pip_size
                        leg_pnl = round(
                            (pips_diff * pip_val * pos.current_size)
                            - (pos.current_size * cfg.commission_per_lot),
                            2,
                        )
                        total_trade_pnl = round(pos.realized_pnl_so_far + leg_pnl, 2)
                        pnl_pct = round((total_trade_pnl / current_balance) * 100.0, 2)
                        ret_r = (
                            round(total_trade_pnl / pos.initial_risk_usd, 2)
                            if pos.initial_risk_usd > 0
                            else 0.0
                        )

                        current_balance = round(current_balance + leg_pnl, 2)
                        closed_trades.append(
                            BacktestTradeLog(
                                id=pos.position_id,
                                symbol=pos.symbol,
                                direction=pos.direction,
                                entry_time=pos.entry_time,
                                exit_time=bar_ts,
                                entry_price=pos.entry_price,
                                exit_price=exit_price,
                                stop_loss=pos.stop_loss,
                                take_profit_1=pos.take_profit_1,
                                take_profit_2=pos.take_profit_2,
                                position_size=pos.initial_size,
                                pnl=total_trade_pnl,
                                pnl_percent=pnl_pct,
                                return_r=ret_r,
                                exit_reason=exit_reason,
                                score=pos.score,
                            )
                        )
                        pos_closed = True

                    # 2. TP2 Target check
                    elif bar_low <= pos.take_profit_2:
                        exit_price = pos.take_profit_2
                        exit_reason = "TP2_HIT"
                        pips_diff = (pos.entry_price - exit_price) / pip_size
                        leg_pnl = round(
                            (pips_diff * pip_val * pos.current_size)
                            - (pos.current_size * cfg.commission_per_lot),
                            2,
                        )
                        total_trade_pnl = round(pos.realized_pnl_so_far + leg_pnl, 2)
                        pnl_pct = round((total_trade_pnl / current_balance) * 100.0, 2)
                        ret_r = (
                            round(total_trade_pnl / pos.initial_risk_usd, 2)
                            if pos.initial_risk_usd > 0
                            else 0.0
                        )

                        current_balance = round(current_balance + leg_pnl, 2)
                        closed_trades.append(
                            BacktestTradeLog(
                                id=pos.position_id,
                                symbol=pos.symbol,
                                direction=pos.direction,
                                entry_time=pos.entry_time,
                                exit_time=bar_ts,
                                entry_price=pos.entry_price,
                                exit_price=exit_price,
                                stop_loss=pos.stop_loss,
                                take_profit_1=pos.take_profit_1,
                                take_profit_2=pos.take_profit_2,
                                position_size=pos.initial_size,
                                pnl=total_trade_pnl,
                                pnl_percent=pnl_pct,
                                return_r=ret_r,
                                exit_reason=exit_reason,
                                score=pos.score,
                            )
                        )
                        pos_closed = True

                    # 3. TP1 Target check (partial close)
                    elif bar_low <= pos.take_profit_1 and not pos.tp1_hit:
                        if cfg.partial_tp_ratio >= 1.0:
                            exit_price = pos.take_profit_1
                            exit_reason = "TP1_HIT"
                            pips_diff = (pos.entry_price - exit_price) / pip_size
                            leg_pnl = round(
                                (pips_diff * pip_val * pos.current_size)
                                - (pos.current_size * cfg.commission_per_lot),
                                2,
                            )
                            total_trade_pnl = leg_pnl
                            pnl_pct = round((total_trade_pnl / current_balance) * 100.0, 2)
                            ret_r = (
                                round(total_trade_pnl / pos.initial_risk_usd, 2)
                                if pos.initial_risk_usd > 0
                                else 0.0
                            )

                            current_balance = round(current_balance + leg_pnl, 2)
                            closed_trades.append(
                                BacktestTradeLog(
                                    id=pos.position_id,
                                    symbol=pos.symbol,
                                    direction=pos.direction,
                                    entry_time=pos.entry_time,
                                    exit_time=bar_ts,
                                    entry_price=pos.entry_price,
                                    exit_price=exit_price,
                                    stop_loss=pos.stop_loss,
                                    take_profit_1=pos.take_profit_1,
                                    take_profit_2=pos.take_profit_2,
                                    position_size=pos.initial_size,
                                    pnl=total_trade_pnl,
                                    pnl_percent=pnl_pct,
                                    return_r=ret_r,
                                    exit_reason=exit_reason,
                                    score=pos.score,
                                )
                            )
                            pos_closed = True
                        else:
                            close_lots = round(pos.initial_size * cfg.partial_tp_ratio, 2)
                            close_lots = max(0.01, min(pos.current_size, close_lots))
                            rem_lots = round(pos.current_size - close_lots, 2)

                            pips_diff = (pos.entry_price - pos.take_profit_1) / pip_size
                            partial_pnl = round(
                                (pips_diff * pip_val * close_lots)
                                - (close_lots * cfg.commission_per_lot),
                                2,
                            )

                            pos.realized_pnl_so_far = round(pos.realized_pnl_so_far + partial_pnl, 2)
                            current_balance = round(current_balance + partial_pnl, 2)
                            pos.current_size = rem_lots
                            pos.tp1_hit = True

                            if cfg.move_sl_to_be_on_tp1:
                                pos.stop_loss = pos.entry_price

                if not pos_closed:
                    remaining_positions.append(pos)

            open_positions = remaining_positions

            # -------------------------------------------------------------
            # Step 2: Floating Equity and Drawdown Tracking for this Bar
            # -------------------------------------------------------------
            floating_open_pnl = 0.0
            for pos in open_positions:
                if pos.direction == SignalDirection.BUY:
                    pdiff = (bar_close - pos.entry_price) / pip_size
                else:
                    pdiff = (pos.entry_price - bar_close) / pip_size
                floating_open_pnl += pdiff * pip_val * pos.current_size

            current_equity = round(current_balance + floating_open_pnl, 2)
            if current_equity > peak_equity:
                peak_equity = current_equity

            dd_usd = round(max(0.0, peak_equity - current_equity), 2)
            dd_pct = round((dd_usd / peak_equity) * 100.0 if peak_equity > 0 else 0.0, 2)

            equity_curve.append(
                EquityPoint(
                    timestamp=bar_ts,
                    equity=current_equity,
                    balance=current_balance,
                    drawdown_pct=dd_pct,
                    drawdown_usd=dd_usd,
                    open_positions=len(open_positions),
                )
            )

            # -------------------------------------------------------------
            # Step 3: Signal Evaluation on Closed Bar
            # -------------------------------------------------------------
            if len(open_positions) < cfg.max_open_trades:
                # Lookback candle slice strictly up to bar i (no forward lookahead!)
                lookback_start = max(0, i - 150)
                eval_candles = candles[lookback_start : i + 1]

                # Align MTF if provided
                sub_4h = [c for c in candles_4h if c.timestamp <= bar_ts] if candles_4h else None
                sub_15m = [c for c in candles_15m if c.timestamp <= bar_ts] if candles_15m else None

                sig = self.signal_generator.evaluate_market_signal(
                    candles_primary=eval_candles,
                    symbol=symbol,
                    timeframe=timeframe,
                    candles_4h=sub_4h[-100:] if sub_4h else None,
                    candles_15m=sub_15m[-100:] if sub_15m else None,
                    account_balance=current_balance,
                    risk_percent=cfg.risk_percent,
                )

                if (
                    sig.direction in (SignalDirection.BUY, SignalDirection.SELL)
                    and sig.setup_score >= cfg.min_score_threshold
                ):
                    trade_counter += 1
                    risk_p = sig.risk_parameters

                    if sig.direction == SignalDirection.BUY:
                        exec_entry = round(bar_close + half_spread_and_slippage, 5)
                        sl = risk_p.stop_loss if risk_p else round(exec_entry - (pip_size * 20.0), 5)
                        if sl >= exec_entry:
                            sl = round(exec_entry - (pip_size * 20.0), 5)

                        risk_dist = exec_entry - sl
                        tp1 = round(exec_entry + (risk_dist * cfg.take_profit_1_rr), 5)
                        tp2 = round(exec_entry + (risk_dist * cfg.take_profit_2_rr), 5)

                    else:  # SELL
                        exec_entry = round(bar_close - half_spread_and_slippage, 5)
                        sl = risk_p.stop_loss if risk_p else round(exec_entry + (pip_size * 20.0), 5)
                        if sl <= exec_entry:
                            sl = round(exec_entry + (pip_size * 20.0), 5)

                        risk_dist = sl - exec_entry
                        tp1 = round(exec_entry - (risk_dist * cfg.take_profit_1_rr), 5)
                        tp2 = round(exec_entry - (risk_dist * cfg.take_profit_2_rr), 5)

                    risk_pips = risk_dist / pip_size
                    risk_usd = round(current_balance * (cfg.risk_percent / 100.0), 2)
                    lots = round(max(0.01, min(100.0, risk_usd / max(1e-6, risk_pips * pip_val))), 2)

                    new_pos = _SimPosition(
                        position_id=trade_counter,
                        symbol=symbol,
                        direction=sig.direction,
                        entry_time=bar_ts,
                        entry_price=exec_entry,
                        initial_sl=sl,
                        stop_loss=sl,
                        take_profit_1=tp1,
                        take_profit_2=tp2,
                        initial_size=lots,
                        current_size=lots,
                        initial_risk_usd=risk_usd,
                        score=sig.setup_score,
                    )
                    open_positions.append(new_pos)

        # -------------------------------------------------------------
        # Step 4: Finalize and close any remaining open positions at end of data
        # -------------------------------------------------------------
        final_bar = candles[-1]
        final_ts = final_bar.timestamp
        final_close = float(final_bar.close)

        for pos in open_positions:
            if pos.direction == SignalDirection.BUY:
                exit_price = round(final_close - half_spread_and_slippage, 5)
                pdiff = (exit_price - pos.entry_price) / pip_size
            else:
                exit_price = round(final_close + half_spread_and_slippage, 5)
                pdiff = (pos.entry_price - exit_price) / pip_size

            leg_pnl = round(
                (pdiff * pip_val * pos.current_size) - (pos.current_size * cfg.commission_per_lot),
                2,
            )
            total_trade_pnl = round(pos.realized_pnl_so_far + leg_pnl, 2)
            pnl_pct = round((total_trade_pnl / current_balance) * 100.0, 2)
            ret_r = (
                round(total_trade_pnl / pos.initial_risk_usd, 2)
                if pos.initial_risk_usd > 0
                else 0.0
            )

            current_balance = round(current_balance + leg_pnl, 2)
            closed_trades.append(
                BacktestTradeLog(
                    id=pos.position_id,
                    symbol=pos.symbol,
                    direction=pos.direction,
                    entry_time=pos.entry_time,
                    exit_time=final_ts,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    stop_loss=pos.stop_loss,
                    take_profit_1=pos.take_profit_1,
                    take_profit_2=pos.take_profit_2,
                    position_size=pos.initial_size,
                    pnl=total_trade_pnl,
                    pnl_percent=pnl_pct,
                    return_r=ret_r,
                    exit_reason="END_OF_DATA",
                    score=pos.score,
                )
            )

        if equity_curve:
            equity_curve[-1].balance = round(current_balance, 2)
            equity_curve[-1].equity = round(current_balance, 2)
            equity_curve[-1].open_positions = 0

        # Compute Performance Metrics
        metrics = PerformanceMetricsCalculator.calculate(
            trades=closed_trades,
            equity_curve=equity_curve,
            initial_balance=cfg.initial_balance,
        )

        return BacktestResultResponse(
            name=name or f"{symbol} {timeframe} Strategy Backtest",
            symbol=symbol,
            timeframe=timeframe,
            start_date=candles[warmup].timestamp if len(candles) > warmup else candles[0].timestamp,
            end_date=final_ts,
            config=cfg,
            metrics=metrics,
            equity_curve=equity_curve,
            trades=closed_trades,
            created_at=datetime.now(),
        )
