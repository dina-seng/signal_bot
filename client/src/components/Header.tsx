import React, { useState, useEffect } from 'react';
import {
  Activity,
  RefreshCw,
  Wallet,
  TrendingUp,
  TrendingDown,
  ShieldAlert,
  ShieldCheck,
  Menu,
  Clock,
  Radio,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';
import { AccountSummary, RiskStatus } from '../types';
import { formatCurrency, formatPnL } from '../utils/formatters';

interface HeaderProps {
  account: AccountSummary;
  riskStatus: RiskStatus;
  pollSecondsRemaining: number;
  isApiConnected?: boolean;
  isRefreshing?: boolean;
  lastUpdatedSecondsAgo?: number;
  apiEndpoint?: string;
  onRefresh: () => void;
  onToggleMobileSidebar: () => void;
  onToggleBlackout: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  account,
  riskStatus,
  pollSecondsRemaining,
  isApiConnected = false,
  isRefreshing = false,
  lastUpdatedSecondsAgo = 0,
  apiEndpoint = 'http://localhost:8000',
  onRefresh,
  onToggleMobileSidebar,
  onToggleBlackout,
}) => {
  const [utcTime, setUtcTime] = useState<string>('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setUtcTime(
        now.toLocaleTimeString('en-GB', {
          timeZone: 'UTC',
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        }) + ' UTC'
      );
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  const pnlMeta = formatPnL(account.unrealizedPnl);

  return (
    <header className="sticky top-0 z-30 w-full bg-[#12121a]/95 backdrop-blur-md border-b border-[#1e1e2d] px-4 lg:px-6 py-3">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
        {/* Left: Mobile hamburger + Terminal Title & Connection Status */}
        <div className="flex items-center justify-between lg:justify-start gap-4">
          <div className="flex items-center gap-3">
            <button
              onClick={onToggleMobileSidebar}
              className="lg:hidden p-2 rounded-md bg-[#181824] text-slate-300 hover:text-white border border-[#1e1e2d] cursor-pointer"
              aria-label="Toggle menu"
            >
              <Menu className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-2.5">
              <div
                className={`w-2.5 h-2.5 rounded-full ${
                  isApiConnected
                    ? 'bg-[#00ff88] shadow-[0_0_8px_#00ff88] animate-pulse'
                    : 'bg-amber-400 shadow-[0_0_8px_#fbbf24]'
                }`}
              />
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono font-bold tracking-wider text-slate-300 uppercase">
                    QUANTVIEW TERMINAL
                  </span>

                  {/* Mode Badge: LIVE DATA vs SIMULATION MODE */}
                  <span
                    className={`px-2 py-0.2 rounded text-[10px] font-mono font-bold uppercase tracking-wider border ${
                      isApiConnected
                        ? 'bg-[#00ff88]/15 text-[#00ff88] border-[#00ff88]/30 shadow-[0_0_8px_rgba(0,255,136,0.2)]'
                        : 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                    }`}
                  >
                    {isApiConnected ? '● LIVE DATA' : '○ SIMULATION MODE'}
                  </span>
                </div>

                <div className="flex items-center gap-2 text-[11px] font-mono text-slate-400 flex-wrap">
                  <span className="flex items-center gap-1 text-emerald-400">
                    <Radio className="w-3 h-3 animate-pulse" />
                    BROKER
                  </span>
                  <span className="text-slate-600">|</span>
                  <span>{account.latencyMs}ms</span>
                  <span className="text-slate-600">|</span>
                  <span className="flex items-center gap-1 text-slate-400">
                    <Clock className="w-3 h-3 text-slate-500" />
                    {utcTime || '00:00:00 UTC'}
                  </span>
                  <span className="text-slate-600">|</span>
                  <span className="text-slate-500 text-[10px]">
                    Updated {lastUpdatedSecondsAgo}s ago
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Quick Risk Pill (clickable to simulate blackout) */}
          <button
            onClick={onToggleBlackout}
            title="Click to toggle blackout simulation"
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono font-semibold border transition-all cursor-pointer ${
              riskStatus.isBlackout
                ? 'bg-[#ff3366]/15 text-[#ff3366] border-[#ff3366]/30 hover:bg-[#ff3366]/25 animate-pulse'
                : 'bg-[#00ff88]/15 text-[#00ff88] border-[#00ff88]/30 hover:bg-[#00ff88]/25'
            }`}
          >
            {riskStatus.isBlackout ? (
              <>
                <ShieldAlert className="w-3.5 h-3.5" />
                <span>BLACKOUT ACTIVE</span>
              </>
            ) : (
              <>
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>SAFE ENVIRONMENT</span>
              </>
            )}
          </button>
        </div>

        {/* Right: Key Financial Metrics Header */}
        <div className="flex items-center justify-between lg:justify-end gap-3 lg:gap-5 flex-wrap">
          {/* Account Balance */}
          <div className="bg-[#0a0a0f] px-3.5 py-1.5 rounded-lg border border-[#1e1e2d]">
            <span className="text-[10px] uppercase tracking-wider font-mono text-slate-400 flex items-center gap-1">
              <Wallet className="w-3 h-3 text-slate-500" />
              Balance
            </span>
            <div className="text-sm lg:text-base font-mono font-bold text-slate-100">
              {formatCurrency(account.balance)}
            </div>
          </div>

          {/* Equity */}
          <div className="bg-[#0a0a0f] px-3.5 py-1.5 rounded-lg border border-[#1e1e2d]">
            <span className="text-[10px] uppercase tracking-wider font-mono text-slate-400 flex items-center gap-1">
              <Activity className="w-3 h-3 text-slate-500" />
              Equity
            </span>
            <div className="text-sm lg:text-base font-mono font-bold text-slate-100">
              {formatCurrency(account.equity)}
            </div>
          </div>

          {/* Unrealized P&L */}
          <div
            className={`px-3.5 py-1.5 rounded-lg border transition-colors ${
              pnlMeta.isPositive
                ? 'bg-[#00ff88]/10 border-[#00ff88]/30 text-[#00ff88]'
                : 'bg-[#ff3366]/10 border-[#ff3366]/30 text-[#ff3366]'
            }`}
          >
            <span className="text-[10px] uppercase tracking-wider font-mono opacity-80 flex items-center gap-1">
              {pnlMeta.isPositive ? (
                <TrendingUp className="w-3 h-3" />
              ) : (
                <TrendingDown className="w-3 h-3" />
              )}
              Unrealized P&L
            </span>
            <div className="text-sm lg:text-base font-mono font-bold flex items-center gap-1.5">
              <span>{pnlMeta.formatted}</span>
              <span className="text-xs opacity-90">
                ({pnlMeta.isPositive ? '+' : ''}
                {account.unrealizedPnlPercent.toFixed(2)}%)
              </span>
            </div>
          </div>

          {/* Polling Indicator & Refresh Button */}
          <div className="flex items-center gap-2">
            <div
              className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#181824] border border-[#1e1e2d] text-[11px] font-mono text-slate-400"
              title="Next automated synchronization"
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isRefreshing ? 'bg-cyan-400 animate-ping' : 'bg-slate-500'
                }`}
              />
              <span>SYNC {pollSecondsRemaining}s</span>
            </div>

            {/* Refresh Data Button */}
            <button
              onClick={onRefresh}
              className={`px-3 py-1.5 rounded-lg bg-[#181824] hover:bg-[#202030] text-slate-300 hover:text-white border border-[#1e1e2d] hover:border-[#2a2a3e] text-xs font-mono font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
                isRefreshing ? 'opacity-70 cursor-wait' : ''
              }`}
              title="Manually trigger API fetch across all endpoints"
              aria-label="Refresh Data"
              disabled={isRefreshing}
            >
              <RefreshCw
                className={`w-3.5 h-3.5 text-cyan-400 ${
                  isRefreshing ? 'animate-spin' : 'hover:rotate-180 transition-transform duration-500'
                }`}
              />
              <span className="hidden sm:inline">Refresh Data</span>
            </button>
          </div>
        </div>
      </div>
    </header>
  );
};
