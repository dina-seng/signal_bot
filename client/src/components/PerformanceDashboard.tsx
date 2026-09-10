import React, { useState } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import {
  Trophy,
  Scale,
  Hash,
  TrendingDown,
  ArrowUpRight,
  ArrowDownRight,
  Calendar,
  Sparkles,
  Info,
} from 'lucide-react';
import { PerformanceStats, EquityDataPoint, AccountSummary, ClosedTrade } from '../types';
import { equityHistoryData } from '../data/mockData';

interface PerformanceDashboardProps {
  stats: PerformanceStats;
  account?: AccountSummary;
  closedTrades?: ClosedTrade[];
}

type TimeframeKey = '1W' | '1M' | '3M' | 'ALL';

export const PerformanceDashboard: React.FC<PerformanceDashboardProps> = ({
  stats,
  account,
  closedTrades = [],
}) => {
  const [activeTimeframe, setActiveTimeframe] = useState<TimeframeKey>('1M');

  // Dynamically compute equity curve data from real account and closed trades
  const chartData = React.useMemo<EquityDataPoint[]>(() => {
    if (!account) {
      return equityHistoryData[activeTimeframe];
    }

    const currentBal = account.balance;
    const currentEq = account.equity;

    if (closedTrades.length === 0) {
      // If no closed trades yet, show baseline trajectory to current balance/equity
      const startBal = 10000;
      return [
        { timestamp: 'Deposit', balance: startBal, equity: startBal, drawdown: 0 },
        { timestamp: 'Current', balance: currentBal, equity: currentEq, drawdown: stats.maxDrawdown || 0 },
      ];
    }

    // Sort closed trades ascending by closedAt
    const sortedTrades = [...closedTrades].sort((a, b) => {
      const ta = a.closedAt ? new Date(a.closedAt).getTime() : 0;
      const tb = b.closedAt ? new Date(b.closedAt).getTime() : 0;
      return ta - tb;
    });

    // Determine cutoff based on activeTimeframe
    const now = Date.now();
    let cutoffMs = 0;
    if (activeTimeframe === '1W') cutoffMs = now - 7 * 24 * 3600 * 1000;
    else if (activeTimeframe === '1M') cutoffMs = now - 30 * 24 * 3600 * 1000;
    else if (activeTimeframe === '3M') cutoffMs = now - 90 * 24 * 3600 * 1000;

    const filteredTrades = cutoffMs > 0
      ? sortedTrades.filter((t) => !t.closedAt || new Date(t.closedAt).getTime() >= cutoffMs)
      : sortedTrades;

    // Calculate starting balance for the timeframe
    let runningBalance = 10000.0;
    const totalPnlAll = sortedTrades.reduce((acc, t) => acc + (t.realizedPnl || 0), 0);
    const initialDeposit = Number((currentBal - totalPnlAll).toFixed(2));
    runningBalance = initialDeposit > 0 ? initialDeposit : 10000.0;

    const points: EquityDataPoint[] = [];

    // Initial start point
    points.push({
      timestamp: activeTimeframe === '1W' ? 'Start of Wk' : activeTimeframe === '1M' ? 'Start of Mo' : 'Deposit',
      balance: runningBalance,
      equity: runningBalance,
      drawdown: 0,
    });

    let peakEquity = runningBalance;

    for (let i = 0; i < filteredTrades.length; i++) {
      const trade = filteredTrades[i];
      runningBalance = Number((runningBalance + (trade.realizedPnl || 0)).toFixed(2));
      const eq = runningBalance;
      if (eq > peakEquity) peakEquity = eq;
      const dd = peakEquity > 0 ? Number((((peakEquity - eq) / peakEquity) * 100).toFixed(1)) : 0;

      const timeLabel = trade.closedAt
        ? new Date(trade.closedAt).toLocaleDateString([], { month: 'numeric', day: 'numeric' }) +
          ' ' +
          new Date(trade.closedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : `T-${i + 1}`;

      points.push({
        timestamp: timeLabel,
        balance: runningBalance,
        equity: eq,
        drawdown: dd,
      });
    }

    // Current point with floating equity
    const currentDd = Math.max(0, Number((((peakEquity - currentEq) / (peakEquity || 1)) * 100).toFixed(1)));
    points.push({
      timestamp: 'Current',
      balance: currentBal,
      equity: currentEq,
      drawdown: currentDd,
    });

    return points;
  }, [account, closedTrades, activeTimeframe, stats.maxDrawdown]);

  const hasTradeHistory = closedTrades.length > 0;
  const sampleSize = hasTradeHistory ? closedTrades.length : stats.totalTrades;
  const computedWinRate = hasTradeHistory
    ? Number(((closedTrades.filter((t) => t.realizedPnl > 0).length / closedTrades.length) * 100).toFixed(1))
    : stats.totalTrades > 0 ? stats.winRate : null;

  return (
    <div className="space-y-4">
      {/* 4 Stats Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {/* Win Rate */}
        <div className="p-3.5 rounded-lg bg-[#111319] border border-[#1d2230] hover:border-[#282f42] transition-colors font-mono">
          <div className="flex items-center justify-between">
            <span className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">
              Win Rate
            </span>
            <div className="p-1.5 rounded bg-[#00e676]/10 text-[#00e676]">
              <Trophy className="w-3.5 h-3.5" />
            </div>
          </div>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="text-xl font-extrabold text-white">
              {computedWinRate !== null ? `${computedWinRate}%` : '—'}
            </span>
            {computedWinRate !== null && stats.winRateDelta !== 0 && (
              <span className="flex items-center text-[11px] text-[#00e676]">
                <ArrowUpRight className="w-3 h-3" />
                +{stats.winRateDelta}%
              </span>
            )}
          </div>
          <div className="mt-2 flex items-center justify-between text-[10px] text-slate-500 border-t border-[#1d2230]/70 pt-1.5">
            <span>Sample size:</span>
            <span className="text-slate-300 font-medium">n = {sampleSize} trades</span>
          </div>
        </div>

        {/* Profit Factor */}
        <div className="p-3.5 rounded-lg bg-[#111319] border border-[#1d2230] hover:border-[#282f42] transition-colors font-mono">
          <div className="flex items-center justify-between">
            <span className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">
              Profit Factor
            </span>
            <div className="p-1.5 rounded bg-cyan-500/10 text-cyan-400">
              <Scale className="w-3.5 h-3.5" />
            </div>
          </div>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="text-xl font-extrabold text-white">
              {sampleSize > 0 && stats.profitFactor > 0 ? stats.profitFactor.toFixed(2) : '—'}
            </span>
            {sampleSize > 0 && stats.profitFactorDelta !== 0 && (
              <span className="flex items-center text-[11px] text-[#00e676]">
                <ArrowUpRight className="w-3 h-3" />
                +{stats.profitFactorDelta}
              </span>
            )}
          </div>
          <div className="mt-2 flex items-center justify-between text-[10px] text-slate-500 border-t border-[#1d2230]/70 pt-1.5">
            <span>Metric:</span>
            <span className="text-slate-300 font-medium">Gross Win / Gross Loss</span>
          </div>
        </div>

        {/* Total Trades & Expectancy */}
        <div className="p-3.5 rounded-lg bg-[#111319] border border-[#1d2230] hover:border-[#282f42] transition-colors font-mono">
          <div className="flex items-center justify-between">
            <span className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">
              Total Trades
            </span>
            <div className="p-1.5 rounded bg-purple-500/10 text-purple-400">
              <Hash className="w-3.5 h-3.5" />
            </div>
          </div>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="text-xl font-extrabold text-white">
              {sampleSize}
            </span>
            {sampleSize > 0 && stats.totalTradesDelta > 0 && (
              <span className="flex items-center text-[11px] text-purple-400">
                +{stats.totalTradesDelta} this cycle
              </span>
            )}
          </div>
          <div className="mt-2 flex items-center justify-between text-[10px] text-slate-500 border-t border-[#1d2230]/70 pt-1.5">
            <span>Expectancy:</span>
            <span className="text-slate-300 font-medium">
              {sampleSize > 0 ? `+${stats.expectancyPips} pips` : '—'}
            </span>
          </div>
        </div>

        {/* Max Drawdown & Sharpe */}
        <div className="p-3.5 rounded-lg bg-[#111319] border border-[#1d2230] hover:border-[#282f42] transition-colors font-mono">
          <div className="flex items-center justify-between">
            <span className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">
              Max Drawdown
            </span>
            <div className="p-1.5 rounded bg-[#ff3366]/10 text-[#ff3366]">
              <TrendingDown className="w-3.5 h-3.5" />
            </div>
          </div>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="text-xl font-extrabold text-[#00e676]">
              {stats.maxDrawdown}%
            </span>
            {stats.maxDrawdownDelta !== 0 && (
              <span className="flex items-center text-[11px] text-[#00e676]">
                <ArrowDownRight className="w-3 h-3" />
                {stats.maxDrawdownDelta}%
              </span>
            )}
          </div>
          <div className="mt-2 flex items-center justify-between text-[10px] text-slate-500 border-t border-[#1d2230]/70 pt-1.5">
            <span>Sharpe Ratio:</span>
            <span className="text-slate-300 font-medium">
              {sampleSize > 0 ? stats.sharpeRatio : '—'}
            </span>
          </div>
        </div>
      </div>

      {/* Equity Curve Area Chart */}
      <div className="p-4 rounded-lg bg-[#111319] border border-[#1d2230]">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3 border-b border-[#1d2230]">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-white tracking-wide">Portfolio Equity Trajectory</h2>
              <span className="px-1.5 py-0.5 rounded text-[9px] font-mono uppercase bg-[#161922] text-slate-400 border border-[#1d2230]">
                Mark-to-Market
              </span>
            </div>
            <p className="text-[11px] text-slate-400 mt-0.5 font-mono">
              Walk-forward equity curve with floating drawdown calculation
            </p>
          </div>

          {/* Timeframe selector */}
          <div className="flex items-center p-0.5 rounded bg-[#0a0b10] border border-[#1d2230]">
            {(['1W', '1M', '3M', 'ALL'] as TimeframeKey[]).map((tf) => (
              <button
                key={tf}
                onClick={() => setActiveTimeframe(tf)}
                className={`px-2.5 py-1 text-xs font-mono font-semibold rounded transition-colors cursor-pointer ${
                  activeTimeframe === tf
                    ? 'bg-[#161922] text-[#00e676] border border-[#1d2230]'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>

        {/* Chart Canvas */}
        <div className="h-64 w-full pt-3">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00e676" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#00e676" stopOpacity={0.0} />
                </linearGradient>
                <linearGradient id="balanceGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00d2ff" stopOpacity={0.12} />
                  <stop offset="95%" stopColor="#00d2ff" stopOpacity={0.0} />
                </linearGradient>
              </defs>

              <CartesianGrid strokeDasharray="3 3" stroke="#151824" vertical={false} />

              <XAxis
                dataKey="timestamp"
                stroke="#475569"
                fontSize={10}
                tickLine={false}
                fontFamily="JetBrains Mono"
              />
              <YAxis
                stroke="#475569"
                fontSize={10}
                tickLine={false}
                axisLine={false}
                domain={['auto', 'auto']}
                fontFamily="JetBrains Mono"
                tickFormatter={(value) => `$${(value / 1000).toFixed(1)}k`}
              />

              <Tooltip
                content={({ active, payload, label }) => {
                  if (active && payload && payload.length) {
                    const data = payload[0].payload as EquityDataPoint;
                    return (
                      <div className="p-2.5 bg-[#111319] border border-[#1d2230] rounded shadow-lg font-mono text-xs backdrop-blur-md">
                        <p className="text-slate-400 font-semibold mb-1 border-b border-[#1d2230] pb-1">{label}</p>
                        <div className="space-y-1 text-[11px]">
                          <div className="flex items-center justify-between gap-4 text-[#00e676]">
                            <span>Equity:</span>
                            <span className="font-bold">
                              ${data.equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-4 text-cyan-400">
                            <span>Balance:</span>
                            <span className="font-bold">
                              ${data.balance.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-4 text-slate-400 border-t border-[#1d2230] pt-1">
                            <span>Drawdown:</span>
                            <span className="text-[#ff3366]">-{data.drawdown}%</span>
                          </div>
                        </div>
                      </div>
                    );
                  }
                  return null;
                }}
              />

              <Area
                type="monotone"
                dataKey="equity"
                stroke="#00e676"
                strokeWidth={2}
                fillOpacity={1}
                fill="url(#equityGradient)"
              />
              <Area
                type="monotone"
                dataKey="balance"
                stroke="#00d2ff"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                fillOpacity={1}
                fill="url(#balanceGradient)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Legend */}
        <div className="flex items-center justify-between pt-2.5 border-t border-[#1d2230] text-[11px] font-mono text-slate-400">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-0.5 bg-[#00e676] rounded-full inline-block" />
              <span className="text-slate-300">Live Equity</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-0.5 bg-cyan-400 border-dashed rounded-full inline-block" />
              <span className="text-slate-300">Closed Balance</span>
            </div>
          </div>
          <span className="text-[10px] text-slate-500">
            Source: FastAPI Paper Database
          </span>
        </div>
      </div>
    </div>
  );
};
