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
  Sparkles,
} from 'lucide-react';
import { PerformanceStats, EquityDataPoint, AccountSummary, ClosedTrade } from '../types';
import { equityHistoryData } from '../data/mockData';
import { KPICard } from './KPICard';

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

    const now = Date.now();
    let cutoffMs = 0;
    if (activeTimeframe === '1W') cutoffMs = now - 7 * 24 * 3600 * 1000;
    else if (activeTimeframe === '1M') cutoffMs = now - 30 * 24 * 3600 * 1000;
    else if (activeTimeframe === '3M') cutoffMs = now - 90 * 24 * 3600 * 1000;

    const filteredTrades = cutoffMs > 0
      ? sortedTrades.filter((t) => !t.closedAt || new Date(t.closedAt).getTime() >= cutoffMs)
      : sortedTrades;

    let runningBalance = 10000.0;
    const totalPnlAll = sortedTrades.reduce((acc, t) => acc + (t.realizedPnl || 0), 0);
    const initialDeposit = Number((currentBal - totalPnlAll).toFixed(2));
    runningBalance = initialDeposit > 0 ? initialDeposit : 10000.0;

    const points: EquityDataPoint[] = [];

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
    <div className="space-y-4 w-full min-w-0">
      {/* 4 Stats Cards Grid - Responsive CSS Grid & Auto-stretch */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-5 w-full min-w-0">
        {/* Win Rate */}
        <KPICard
          label="Win Rate"
          value={computedWinRate !== null ? `${computedWinRate}%` : '—'}
          delta={computedWinRate !== null && stats.winRateDelta !== 0 ? `+${stats.winRateDelta}%` : undefined}
          deltaType="positive"
          icon={Trophy}
          iconColor="text-emerald-400"
          iconBg="bg-emerald-500/10 border-emerald-500/20"
          subLabel="Sample size"
          subValue={`n = ${sampleSize} trades`}
          tooltip="Percentage of closed positions resulting in net positive profit"
        />

        {/* Profit Factor */}
        <KPICard
          label="Profit Factor"
          value={sampleSize > 0 && stats.profitFactor > 0 ? stats.profitFactor.toFixed(2) : '—'}
          delta={sampleSize > 0 && stats.profitFactorDelta !== 0 ? `+${stats.profitFactorDelta}` : undefined}
          deltaType="positive"
          icon={Scale}
          iconColor="text-cyan-400"
          iconBg="bg-cyan-500/10 border-cyan-500/20"
          subLabel="Metric"
          subValue="Gross Win / Gross Loss"
          tooltip="Gross institutional profits divided by gross losses"
        />

        {/* Total Trades & Expectancy */}
        <KPICard
          label="Total Trades"
          value={sampleSize}
          delta={sampleSize > 0 && stats.totalTradesDelta > 0 ? `+${stats.totalTradesDelta}` : undefined}
          deltaLabel="this cycle"
          deltaType="neutral"
          icon={Hash}
          iconColor="text-indigo-400"
          iconBg="bg-indigo-500/10 border-indigo-500/20"
          subLabel="Expectancy"
          subValue={sampleSize > 0 ? `+${stats.expectancyPips} pips` : '—'}
          tooltip="Total closed market executions and mathematical pip expectancy"
        />

        {/* Max Drawdown & Sharpe */}
        <KPICard
          label="Max Drawdown"
          value={`${stats.maxDrawdown}%`}
          delta={stats.maxDrawdownDelta !== 0 ? `${stats.maxDrawdownDelta}%` : undefined}
          deltaType={stats.maxDrawdown > 5 ? 'negative' : 'positive'}
          icon={TrendingDown}
          iconColor={stats.maxDrawdown > 5 ? 'text-rose-400' : 'text-emerald-400'}
          iconBg={stats.maxDrawdown > 5 ? 'bg-rose-500/10 border-rose-500/20' : 'bg-emerald-500/10 border-emerald-500/20'}
          subLabel="Sharpe Ratio"
          subValue={sampleSize > 0 ? stats.sharpeRatio : '—'}
          tooltip="Peak-to-trough equity decline with risk-adjusted Sharpe ratio"
        />
      </div>

      {/* Equity Curve Area Chart - Responsive Fluid Container */}
      <div className="relative min-w-0 w-full overflow-hidden rounded-2xl bg-zinc-900/40 backdrop-blur-md border border-white/10 p-4 sm:p-5 lg:p-6 shadow-2xl transition-all duration-300">
        {/* Subtle top edge highlight */}
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/20 to-transparent" />

        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-4 border-b border-white/10 min-w-0">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-sm font-semibold text-white tracking-wide truncate">
                Portfolio Equity Trajectory
              </h2>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-mono uppercase bg-white/5 text-zinc-400 border border-white/10 shrink-0">
                Mark-to-Market
              </span>
            </div>
            <p className="text-xs text-zinc-400 mt-1 font-sans line-clamp-1 sm:line-clamp-none">
              Walk-forward institutional equity curve with continuous floating drawdown estimation
            </p>
          </div>

          {/* Timeframe selector pill */}
          <div className="flex items-center p-1 rounded-xl bg-zinc-950/60 border border-white/10 shrink-0 self-start sm:self-auto">
            {(['1W', '1M', '3M', 'ALL'] as TimeframeKey[]).map((tf) => (
              <button
                key={tf}
                onClick={() => setActiveTimeframe(tf)}
                className={`px-3 py-1 text-xs font-mono font-medium rounded-lg transition-all cursor-pointer ${
                  activeTimeframe === tf
                    ? 'bg-white/15 text-white shadow-sm border border-white/10'
                    : 'text-zinc-400 hover:text-white hover:bg-white/5'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>

        {/* Chart Canvas */}
        <div className="h-64 sm:h-72 w-full pt-4 min-w-0 overflow-hidden">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0.0} />
                </linearGradient>
                <linearGradient id="balanceGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.12} />
                  <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.0} />
                </linearGradient>
              </defs>

              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />

              <XAxis
                dataKey="timestamp"
                stroke="#71717a"
                fontSize={10}
                tickLine={false}
                fontFamily="JetBrains Mono"
              />
              <YAxis
                stroke="#71717a"
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
                      <div className="p-3 bg-zinc-950/90 border border-white/15 rounded-xl shadow-2xl font-mono text-xs backdrop-blur-md">
                        <p className="text-zinc-400 font-medium mb-1.5 border-b border-white/10 pb-1">{label}</p>
                        <div className="space-y-1.5 text-[11px]">
                          <div className="flex items-center justify-between gap-4 text-emerald-400">
                            <span>Equity:</span>
                            <span className="font-semibold text-white">
                              ${data.equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-4 text-sky-400">
                            <span>Balance:</span>
                            <span className="font-semibold text-white">
                              ${data.balance.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-4 text-zinc-400 border-t border-white/10 pt-1">
                            <span>Drawdown:</span>
                            <span className="text-rose-400 font-semibold">-{data.drawdown}%</span>
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
                stroke="#10b981"
                strokeWidth={2}
                fillOpacity={1}
                fill="url(#equityGradient)"
              />
              <Area
                type="monotone"
                dataKey="balance"
                stroke="#38bdf8"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                fillOpacity={1}
                fill="url(#balanceGradient)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Legend */}
        <div className="flex items-center justify-between pt-3 border-t border-white/10 text-xs font-mono text-zinc-400">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-0.5 bg-emerald-400 rounded-full inline-block" />
              <span className="text-zinc-300">Live Equity</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-0.5 bg-sky-400 border-dashed rounded-full inline-block" />
              <span className="text-zinc-300">Closed Balance</span>
            </div>
          </div>
          <span className="text-[11px] text-zinc-500">
            Source: FastAPI Paper Database &bull; XAU/USD &amp; US100
          </span>
        </div>
      </div>
    </div>
  );
};
