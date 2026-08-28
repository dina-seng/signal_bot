"""Institutional Performance and Risk Metrics Calculator."""

import math
from typing import List, Sequence
import numpy as np

from app.schemas.backtesting import BacktestTradeLog, EquityPoint, PerformanceMetrics
from app.schemas.signal import SignalDirection


class PerformanceMetricsCalculator:
    """Calculates win rate, profit factor, max drawdown, Sharpe, Sortino, Calmar, and expectancy."""

    @classmethod
    def calculate(
        cls,
        trades: Sequence[BacktestTradeLog],
        equity_curve: Sequence[EquityPoint],
        initial_balance: float = 10000.0,
    ) -> PerformanceMetrics:
        """Compute complete institutional performance metrics from executed trade logs and equity curve."""
        total_trades = len(trades)
        total_pnl = round(sum(t.pnl for t in trades), 2)
        final_balance = round(initial_balance + total_pnl, 2)
        total_pnl_percent = round((total_pnl / initial_balance) * 100.0, 2)

        if total_trades == 0:
            return PerformanceMetrics(
                initial_balance=initial_balance,
                final_balance=final_balance,
                total_pnl=0.0,
                total_pnl_percent=0.0,
                peak_equity=initial_balance,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                break_even_trades=0,
                win_rate=0.0,
                loss_rate=0.0,
                profit_factor=0.0,
                gross_profit=0.0,
                gross_loss=0.0,
                average_win=0.0,
                average_loss=0.0,
                win_loss_payoff_ratio=0.0,
                expectancy_usd=0.0,
                expectancy_r=0.0,
                max_drawdown_pct=0.0,
                max_drawdown_usd=0.0,
                max_drawdown_duration_bars=0,
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                calmar_ratio=0.0,
                buy_trades_count=0,
                buy_winning_trades=0,
                buy_win_rate=0.0,
                buy_pnl=0.0,
                sell_trades_count=0,
                sell_winning_trades=0,
                sell_win_rate=0.0,
                sell_pnl=0.0,
            )

        winning_trades_list = [t for t in trades if t.pnl > 0.0001]
        losing_trades_list = [t for t in trades if t.pnl < -0.0001]
        be_trades_list = [t for t in trades if abs(t.pnl) <= 0.0001]

        winning_count = len(winning_trades_list)
        losing_count = len(losing_trades_list)
        be_count = len(be_trades_list)

        win_rate = round((winning_count / total_trades) * 100.0, 2)
        loss_rate = round((losing_count / total_trades) * 100.0, 2)

        gross_profit = round(sum(t.pnl for t in winning_trades_list), 2)
        gross_loss = round(abs(sum(t.pnl for t in losing_trades_list)), 2)

        if gross_loss > 0.0:
            profit_factor = round(gross_profit / gross_loss, 2)
        elif gross_profit > 0.0:
            profit_factor = 99.99
        else:
            profit_factor = 0.0

        avg_win = round(gross_profit / winning_count, 2) if winning_count > 0 else 0.0
        avg_loss = round(gross_loss / losing_count, 2) if losing_count > 0 else 0.0

        payoff_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else (99.99 if avg_win > 0 else 0.0)

        # Expectancy: (Win Rate * Avg Win) - (Loss Rate * Avg Loss)
        expectancy_usd = round(
            ((winning_count / total_trades) * avg_win) - ((losing_count / total_trades) * avg_loss),
            2,
        )
        r_multiples = [t.return_r for t in trades]
        expectancy_r = round(float(np.mean(r_multiples)), 2) if r_multiples else 0.0

        # Drawdown calculation from equity curve
        peak_equity = initial_balance
        max_dd_usd = 0.0
        max_dd_pct = 0.0
        max_dd_duration = 0
        current_dd_duration = 0

        for eq in equity_curve:
            if eq.equity > peak_equity:
                peak_equity = eq.equity
                current_dd_duration = 0
            else:
                dd_usd = peak_equity - eq.equity
                dd_pct = (dd_usd / peak_equity) * 100.0 if peak_equity > 0 else 0.0
                if dd_usd > max_dd_usd:
                    max_dd_usd = dd_usd
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct
                current_dd_duration += 1
                if current_dd_duration > max_dd_duration:
                    max_dd_duration = current_dd_duration

        max_dd_usd = round(max_dd_usd, 2)
        max_dd_pct = round(max_dd_pct, 2)

        # Sharpe, Sortino, Calmar Ratios
        trade_returns = [t.pnl_percent / 100.0 for t in trades]
        sharpe_ratio = 0.0
        sortino_ratio = 0.0
        calmar_ratio = 0.0

        if len(trade_returns) >= 2:
            mean_ret = float(np.mean(trade_returns))
            std_ret = float(np.std(trade_returns, ddof=1))
            
            # Annualization factor for trades (approx. sqrt of trade frequency)
            ann_factor = math.sqrt(max(1, len(trade_returns)))

            if std_ret > 1e-7:
                sharpe_ratio = round((mean_ret / std_ret) * ann_factor, 2)

            downside_diffs = [min(0.0, r) for r in trade_returns]
            downside_std = math.sqrt(sum(d ** 2 for d in downside_diffs) / max(1, len(trade_returns)))
            if downside_std > 1e-7:
                sortino_ratio = round((mean_ret / downside_std) * ann_factor, 2)

        if max_dd_pct > 0.0:
            calmar_ratio = round(total_pnl_percent / max_dd_pct, 2)
        elif total_pnl_percent > 0:
            calmar_ratio = 99.99

        # Directional Breakdown (Longs vs Shorts)
        buy_trades = [t for t in trades if t.direction == SignalDirection.BUY]
        sell_trades = [t for t in trades if t.direction == SignalDirection.SELL]

        buy_count = len(buy_trades)
        buy_wins = len([t for t in buy_trades if t.pnl > 0.0001])
        buy_win_rate = round((buy_wins / buy_count) * 100.0, 2) if buy_count > 0 else 0.0
        buy_pnl = round(sum(t.pnl for t in buy_trades), 2)

        sell_count = len(sell_trades)
        sell_wins = len([t for t in sell_trades if t.pnl > 0.0001])
        sell_win_rate = round((sell_wins / sell_count) * 100.0, 2) if sell_count > 0 else 0.0
        sell_pnl = round(sum(t.pnl for t in sell_trades), 2)

        return PerformanceMetrics(
            initial_balance=round(initial_balance, 2),
            final_balance=round(final_balance, 2),
            total_pnl=total_pnl,
            total_pnl_percent=total_pnl_percent,
            peak_equity=round(peak_equity, 2),
            total_trades=total_trades,
            winning_trades=winning_count,
            losing_trades=losing_count,
            break_even_trades=be_count,
            win_rate=win_rate,
            loss_rate=loss_rate,
            profit_factor=profit_factor,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            average_win=avg_win,
            average_loss=avg_loss,
            win_loss_payoff_ratio=payoff_ratio,
            expectancy_usd=expectancy_usd,
            expectancy_r=expectancy_r,
            max_drawdown_pct=max_dd_pct,
            max_drawdown_usd=max_dd_usd,
            max_drawdown_duration_bars=max_dd_duration,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            calmar_ratio=calmar_ratio,
            buy_trades_count=buy_count,
            buy_winning_trades=buy_wins,
            buy_win_rate=buy_win_rate,
            buy_pnl=buy_pnl,
            sell_trades_count=sell_count,
            sell_winning_trades=sell_wins,
            sell_win_rate=sell_win_rate,
            sell_pnl=sell_pnl,
        )
