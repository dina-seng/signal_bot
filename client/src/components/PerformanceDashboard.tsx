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
} from 'lucide-react';
import { PerformanceStats, EquityDataPoint, AccountSummary, ClosedTrade } from '../types';
import { equityHistoryData } from '../data/mockData';
import { KPICard } from './KPICard';
import { AppConfig } from '../services/api';

interface PerformanceDashboardProps {
  stats: PerformanceStats;
  account?: AccountSummary;
  closedTrades?: ClosedTrade[];
  appConfig?: AppConfig | null;
}

type TimeframeKey = '1W' | '1M' | '3M' | 'ALL';

export const PerformanceDashboard: React.FC<PerformanceDashboardProps> = ({
  stats,
  account,
  closedTrades = [],
  appConfig,
}) => {
  const [activeTimeframe, setActiveTimeframe] = useState<TimeframeKey>('1M');

  const hasInitialBalance = typeof stats.initialBalance === 'number' && stats.initialBalance > 0;
  const realInitialBalance = hasInitialBalance ? (stats.initialBalance as number) : null;

  // Dynamically compute equity curve data from real account and closed trades
  const chartData = React.useMemo<EquityDataPoint[]>(() => {
    if (!account) {
      return equityHistoryData[activeTimeframe];
    }

    const currentBal = account.balance;
    const currentEq = account.equity;

    if (closedTrades.length === 0) {
      if (hasInitialBalance && realInitialBalance !== null) {
        const peak = Math.max(realInitialBalance, currentBal, currentEq);
        const currentDd = peak > 0 ? Math.max(0, Number((((peak - currentEq) / peak) * 100).toFixed(1))) : 0;
        return [
          { timestamp: 'Deposit', balance: realInitialBalance, equity: realInitialBalance, drawdown: 0 },
          { timestamp: 'Current', balance: currentBal, equity: currentEq, drawdown: currentDd },
        ];
      }
      // Missing initial_balance: label axis Cumulative P&L starting at 0 instead of faking a deposit
      const floatingPnl = Number((currentEq - currentBal).toFixed(2));
      return [
        { timestamp: 'Start', balance: 0, equity: 0, drawdown: 0 },
        { timestamp: 'Current', balance: 0, equity: floatingPnl, drawdown: 0 },
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

    const tradesBeforeCutoff = cutoffMs > 0
      ? sortedTrades.filter((t) => t.closedAt && new Date(t.closedAt).getTime() < cutoffMs)
      : [];
    const filteredTrades = cutoffMs > 0
      ? sortedTrades.filter((t) => !t.closedAt || new Date(t.closedAt).getTime() >= cutoffMs)
      : sortedTrades;

    const points: EquityDataPoint[] = [];

    if (hasInitialBalance && realInitialBalance !== null) {
      const priorPnl = tradesBeforeCutoff.reduce((acc, t) => acc + (t.realizedPnl || 0), 0);
      let runningBalance = Number((realInitialBalance + priorPnl).toFixed(2));

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

      if (currentEq > peakEquity) peakEquity = currentEq;
      const currentDd = Math.max(0, Number((((peakEquity - currentEq) / (peakEquity || 1)) * 100).toFixed(1)));
      points.push({
        timestamp: 'Current',
        balance: currentBal,
        equity: currentEq,
        drawdown: currentDd,
      });
    } else {
      // Missing initial_balance: Cumulative P&L starting at 0
      let runningPnl = 0.0;

      points.push({
        timestamp: activeTimeframe === '1W' ? 'Start of Wk' : activeTimeframe === '1M' ? 'Start of Mo' : 'Start',
        balance: 0,
        equity: 0,
        drawdown: 0,
      });

      let peakEquity = 0.0;

      for (let i = 0; i < filteredTrades.length; i++) {
        const trade = filteredTrades[i];
        runningPnl = Number((runningPnl + (trade.realizedPnl || 0)).toFixed(2));
        const eq = runningPnl;
        if (eq > peakEquity) peakEquity = eq;
        const dd = peakEquity > 0 ? Number((((peakEquity - eq) / peakEquity) * 100).toFixed(1)) : 0;

        const timeLabel = trade.closedAt
          ? new Date(trade.closedAt).toLocaleDateString([], { month: 'numeric', day: 'numeric' }) +
            ' ' +
            new Date(trade.closedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          : `T-${i + 1}`;

        points.push({
          timestamp: timeLabel,
          balance: runningPnl,
          equity: eq,
          drawdown: dd,
        });
      }

      const floatingPnl = Number((currentEq - currentBal).toFixed(2));
      const currentEquityPnl = Number((runningPnl + floatingPnl).toFixed(2));
      if (currentEquityPnl > peakEquity) peakEquity = currentEquityPnl;
      const currentDd = peakEquity > 0 ? Math.max(0, Number((((peakEquity - currentEquityPnl) / peakEquity) * 100).toFixed(1))) : 0;
      points.push({
        timestamp: 'Current',
        balance: runningPnl,
        equity: currentEquityPnl,
        drawdown: currentDd,
      });
    }

    return points;
  }, [account, closedTrades, activeTimeframe, hasInitialBalance, realInitialBalance]);

  const hasTradeHistory = closedTrades.length > 0;
  const sampleSize = hasTradeHistory ? closedTrades.length : stats.totalTrades;
  const computedWinRate = hasTradeHistory
    ? Number(((closedTrades.filter((t) => t.realizedPnl > 0).length / closedTrades.length) * 100).toFixed(1))
    : stats.totalTrades > 0 ? stats.winRate : null;

  // Real peak-to-trough max drawdown computed from chartData equity series
  const realMaxDrawdown = React.useMemo<number | null>(() => {
    if (!chartData || chartData.length === 0) {
      return stats.maxDrawdown != null ? stats.maxDrawdown : null;
    }
    const drawdowns = chartData.map((d) => (typeof d.drawdown === 'number' && !isNaN(d.drawdown) ? d.drawdown : 0));
    const maxDd = Math.max(...drawdowns, 0);
    if (hasTradeHistory) {
      return Number(maxDd.toFixed(1));
    }
    return stats.maxDrawdown != null ? stats.maxDrawdown : (maxDd > 0 ? Number(maxDd.toFixed(1)) : null);
  }, [chartData, hasTradeHistory, stats.maxDrawdown]);

  // Compute profit factor from closed trades if available
  const computedProfitFactor = React.useMemo<number | null>(() => {
    if (!hasTradeHistory) return null;
    const grossWin = closedTrades.filter((t) => t.realizedPnl > 0).reduce((acc, t) => acc + t.realizedPnl, 0);
    const grossLoss = Math.abs(closedTrades.filter((t) => t.realizedPnl < 0).reduce((acc, t) => acc + t.realizedPnl, 0));
    if (grossLoss > 0) return Number((grossWin / grossLoss).toFixed(2));
    if (grossWin > 0) return Number(grossWin.toFixed(2));
    return 0;
  }, [closedTrades, hasTradeHistory]);

  const effectivePF = (stats.profitFactor != null && stats.profitFactor > 0)
    ? stats.profitFactor
    : computedProfitFactor;

  // BUG 3: Expectancy calculation - if PF > 1 but expectancy shows +0 / missing, recompute expectancy = mean(realizedPnl)
  const expectancyDisplay = React.useMemo<string>(() => {
    if (sampleSize === 0) return '—';

    const meanPnl = hasTradeHistory
      ? closedTrades.reduce((acc, t) => acc + (t.realizedPnl || 0), 0) / closedTrades.length
      : null;

    const isPfPositive = effectivePF !== null && effectivePF > 1;
    const isExpectancyZeroOrMissing = stats.expectancyPips === null || stats.expectancyPips === 0;

    if (isPfPositive && isExpectancyZeroOrMissing && meanPnl !== null) {
      return meanPnl >= 0 ? `+$${meanPnl.toFixed(2)}` : `-$${Math.abs(meanPnl).toFixed(2)}`;
    }

    if (stats.expectancyPips !== null && stats.expectancyPips !== 0) {
      return stats.expectancyPips > 0 ? `+${stats.expectancyPips} pips` : `${stats.expectancyPips} pips`;
    }

    if (meanPnl !== null) {
      return meanPnl >= 0 ? `+$${meanPnl.toFixed(2)}` : `-$${Math.abs(meanPnl).toFixed(2)}`;
    }

    return '—';
  }, [sampleSize, hasTradeHistory, closedTrades, effectivePF, stats.expectancyPips]);

  // BUG 1: Guard against duplicate tick labels on Y-axis (e.g. sub-$1000 accounts)
  const seenTicksRef = React.useRef<Set<string>>(new Set());
  seenTicksRef.current.clear();

  const formatYAxisTick = (value: number, index?: number) => {
    if (index === 0) {
      seenTicksRef.current.clear();
    }
    const formatted =
      value >= 1000 ? `$${(value / 1000).toFixed(1)}k` : `$${Math.round(value)}`;
    if (seenTicksRef.current.has(formatted)) {
      return '';
    }
    seenTicksRef.current.add(formatted);
    return formatted;
  };

  // BUG 4: Active symbols from appConfig
  const activeSymbolsLabel =
    appConfig?.active_symbols && appConfig.active_symbols.length > 0
      ? appConfig.active_symbols.join(' & ')
      : 'XAU/USD';

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
          value={sampleSize > 0 && effectivePF !== null && effectivePF > 0 ? effectivePF.toFixed(2) : '—'}
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
          subValue={expectancyDisplay}
          tooltip="Total closed market executions and mathematical pip expectancy"
        />

        {/* Max Drawdown & Sharpe */}
        <KPICard
          label="Max Drawdown"
          value={realMaxDrawdown !== null ? `${realMaxDrawdown}%` : '—'}
          delta={realMaxDrawdown !== null && stats.maxDrawdownDelta !== 0 ? `${stats.maxDrawdownDelta}%` : undefined}
          deltaType={realMaxDrawdown === null ? 'neutral' : (realMaxDrawdown > 5 ? 'negative' : 'positive')}
          icon={TrendingDown}
          iconColor={realMaxDrawdown === null ? 'text-zinc-400' : (realMaxDrawdown > 5 ? 'text-rose-400' : 'text-emerald-400')}
          iconBg={realMaxDrawdown === null ? 'bg-white/5 border-white/10' : (realMaxDrawdown > 5 ? 'bg-rose-500/10 border-rose-500/20' : 'bg-emerald-500/10 border-emerald-500/20')}
          subLabel="Sharpe Ratio"
          subValue={sampleSize > 0 && stats.sharpeRatio != null ? (typeof stats.sharpeRatio === 'number' ? stats.sharpeRatio.toFixed(2) : stats.sharpeRatio) : '—'}
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
                {hasInitialBalance ? 'Portfolio Equity Trajectory' : 'Cumulative P&L Trajectory'}
              </h2>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-mono uppercase bg-white/5 text-zinc-400 border border-white/10 shrink-0">
                {hasInitialBalance ? 'Mark-to-Market' : 'Cumulative P&L ($)'}
              </span>
            </div>
            <p className="text-xs text-zinc-400 mt-1 font-sans line-clamp-1 sm:line-clamp-none">
              {hasInitialBalance
                ? 'Walk-forward institutional equity curve with continuous floating drawdown estimation'
                : 'Walk-forward cumulative profit and loss trajectory ($) starting from zero'}
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
            <AreaChart data={chartData} margin={{ top: 8, right: 12, left: !hasInitialBalance ? 10 : 0, bottom: 0 }}>
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
                tickFormatter={formatYAxisTick}
                label={
                  !hasInitialBalance
                    ? {
                        value: 'Cumulative P&L ($)',
                        angle: -90,
                        position: 'insideLeft',
                        fill: '#71717a',
                        fontSize: 10,
                        fontFamily: 'JetBrains Mono',
                        style: { textAnchor: 'middle' },
                      }
                    : undefined
                }
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
                            <span>{hasInitialBalance ? 'Equity:' : 'Cumulative Equity:'}</span>
                            <span className="font-semibold text-white">
                              ${data.equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-4 text-sky-400">
                            <span>{hasInitialBalance ? 'Balance:' : 'Realized P&L:'}</span>
                            <span className="font-semibold text-white">
                              ${data.balance.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-4 text-zinc-400 border-t border-white/10 pt-1">
                            <span>Drawdown:</span>
                            <span className="text-rose-400 font-semibold">
                              {data.drawdown > 0 ? `-${data.drawdown}%` : '0.0%'}
                            </span>
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
              <span className="text-zinc-300">{hasInitialBalance ? 'Live Equity' : 'Cumulative Equity'}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-0.5 bg-sky-400 border-dashed rounded-full inline-block" />
              <span className="text-zinc-300">{hasInitialBalance ? 'Closed Balance' : 'Realized P&L'}</span>
            </div>
          </div>
          <span className="text-[11px] text-zinc-500">
            Source: FastAPI Paper Database &bull; {activeSymbolsLabel}
          </span>
        </div>
      </div>
    </div>
  );
};
