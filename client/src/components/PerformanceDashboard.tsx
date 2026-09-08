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
import { PerformanceStats, EquityDataPoint } from '../types';
import { equityHistoryData } from '../data/mockData';

interface PerformanceDashboardProps {
  stats: PerformanceStats;
}

type TimeframeKey = '1W' | '1M' | '3M' | 'ALL';

export const PerformanceDashboard: React.FC<PerformanceDashboardProps> = ({ stats }) => {
  const [activeTimeframe, setActiveTimeframe] = useState<TimeframeKey>('1M');
  const chartData = equityHistoryData[activeTimeframe];

  return (
    <div className="space-y-6">
      {/* 4 Stats Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Win Rate */}
        <div className="p-4 rounded-xl bg-[#12121a] border border-[#1e1e2d] hover:border-[#2a2a3e] transition-all shadow-terminal group">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider font-mono text-slate-400">
              Win Rate
            </span>
            <div className="p-2 rounded-lg bg-[#00ff88]/10 text-[#00ff88] group-hover:scale-110 transition-transform">
              <Trophy className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-mono font-extrabold text-white">
              {stats.winRate}%
            </span>
            <span className="flex items-center text-xs font-mono text-[#00ff88]">
              <ArrowUpRight className="w-3.5 h-3.5" />
              +{stats.winRateDelta}%
            </span>
          </div>
          <div className="mt-3 flex items-center justify-between text-[11px] font-mono text-slate-400">
            <span>Historical baseline: 65%</span>
            <span className="text-emerald-400 font-semibold">High Edge</span>
          </div>
        </div>

        {/* Profit Factor */}
        <div className="p-4 rounded-xl bg-[#12121a] border border-[#1e1e2d] hover:border-[#2a2a3e] transition-all shadow-terminal group">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider font-mono text-slate-400">
              Profit Factor
            </span>
            <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-400 group-hover:scale-110 transition-transform">
              <Scale className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-mono font-extrabold text-white">
              {stats.profitFactor}
            </span>
            <span className="flex items-center text-xs font-mono text-[#00ff88]">
              <ArrowUpRight className="w-3.5 h-3.5" />
              +{stats.profitFactorDelta}
            </span>
          </div>
          <div className="mt-3 flex items-center justify-between text-[11px] font-mono text-slate-400">
            <span>Gross Gain / Gross Loss</span>
            <span className="text-cyan-400 font-semibold">Robust</span>
          </div>
        </div>

        {/* Total Trades */}
        <div className="p-4 rounded-xl bg-[#12121a] border border-[#1e1e2d] hover:border-[#2a2a3e] transition-all shadow-terminal group">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider font-mono text-slate-400">
              Total Trades
            </span>
            <div className="p-2 rounded-lg bg-purple-500/10 text-purple-400 group-hover:scale-110 transition-transform">
              <Hash className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-mono font-extrabold text-white">
              {stats.totalTrades}
            </span>
            <span className="flex items-center text-xs font-mono text-purple-400">
              <ArrowUpRight className="w-3.5 h-3.5" />
              +{stats.totalTradesDelta} this wk
            </span>
          </div>
          <div className="mt-3 flex items-center justify-between text-[11px] font-mono text-slate-400">
            <span>Expectancy</span>
            <span className="text-slate-300 font-mono">+{stats.expectancyPips} pips/trade</span>
          </div>
        </div>

        {/* Max Drawdown */}
        <div className="p-4 rounded-xl bg-[#12121a] border border-[#1e1e2d] hover:border-[#2a2a3e] transition-all shadow-terminal group">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider font-mono text-slate-400">
              Max Drawdown
            </span>
            <div className="p-2 rounded-lg bg-[#ff3366]/10 text-[#ff3366] group-hover:scale-110 transition-transform">
              <TrendingDown className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-mono font-extrabold text-[#00ff88]">
              {stats.maxDrawdown}%
            </span>
            <span className="flex items-center text-xs font-mono text-[#00ff88]">
              <ArrowDownRight className="w-3.5 h-3.5" />
              {stats.maxDrawdownDelta}%
            </span>
          </div>
          <div className="mt-3 flex items-center justify-between text-[11px] font-mono text-slate-400">
            <span>Sharpe Ratio</span>
            <span className="text-slate-300 font-mono">{stats.sharpeRatio}</span>
          </div>
        </div>
      </div>

      {/* Equity Curve Area Chart */}
      <div className="p-5 rounded-xl bg-[#12121a] border border-[#1e1e2d] shadow-terminal">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-[#1e1e2d]">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-white">Equity Growth Curve</h2>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-[#00ff88]/15 text-[#00ff88] border border-[#00ff88]/30">
                Compounding
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1 font-mono">
              Net portfolio trajectory showing closed balance and floating equity
            </p>
          </div>

          {/* Timeframe selector */}
          <div className="flex items-center p-1 rounded-lg bg-[#0a0a0f] border border-[#1e1e2d]">
            {(['1W', '1M', '3M', 'ALL'] as TimeframeKey[]).map((tf) => (
              <button
                key={tf}
                onClick={() => setActiveTimeframe(tf)}
                className={`px-3 py-1 text-xs font-mono font-semibold rounded-md transition-all ${
                  activeTimeframe === tf
                    ? 'bg-[#1e1e2d] text-[#00ff88] shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>

        {/* Chart Canvas */}
        <div className="h-72 w-full pt-4">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00ff88" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#00ff88" stopOpacity={0.0} />
                </linearGradient>
                <linearGradient id="balanceGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00d2ff" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#00d2ff" stopOpacity={0.0} />
                </linearGradient>
              </defs>

              <CartesianGrid strokeDasharray="3 3" stroke="#1a1a26" vertical={false} />

              <XAxis
                dataKey="timestamp"
                stroke="#475569"
                fontSize={11}
                tickLine={false}
                fontFamily="JetBrains Mono"
              />
              <YAxis
                stroke="#475569"
                fontSize={11}
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
                      <div className="p-3 bg-[#12121a]/95 border border-[#1e1e2d] rounded-lg shadow-2xl font-mono text-xs backdrop-blur-md">
                        <p className="text-slate-400 font-semibold mb-1.5">{label}</p>
                        <div className="space-y-1">
                          <div className="flex items-center justify-between gap-4 text-[#00ff88]">
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
                          <div className="flex items-center justify-between gap-4 text-slate-400 border-t border-[#1e1e2d] pt-1 mt-1">
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
                stroke="#00ff88"
                strokeWidth={2.5}
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
        <div className="flex items-center justify-between pt-3 border-t border-[#1e1e2d] text-xs font-mono text-slate-400">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-0.5 bg-[#00ff88] rounded-full inline-block" />
              <span className="text-slate-300">Live Equity</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-0.5 bg-cyan-400 border-dashed rounded-full inline-block" />
              <span className="text-slate-300">Closed Balance</span>
            </div>
          </div>
          <span className="text-[11px] text-slate-500">
            Engine: Anti-lookahead walk-forward simulation
          </span>
        </div>
      </div>
    </div>
  );
};
