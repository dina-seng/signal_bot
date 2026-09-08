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
} from 'lucide-react';
import { AccountSummary, RiskStatus } from '../types';

interface HeaderProps {
  account: AccountSummary;
  riskStatus: RiskStatus;
  pollSecondsRemaining: number;
  onRefresh: () => void;
  onToggleMobileSidebar: () => void;
  onToggleBlackout: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  account,
  riskStatus,
  pollSecondsRemaining,
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

  const isPnlPositive = account.unrealizedPnl >= 0;

  return (
    <header className="sticky top-0 z-30 w-full bg-[#12121a]/95 backdrop-blur-md border-b border-[#1e1e2d] px-4 lg:px-6 py-3">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
        {/* Left: Mobile hamburger + Terminal Title & Connection Status */}
        <div className="flex items-center justify-between lg:justify-start gap-4">
          <div className="flex items-center gap-3">
            <button
              onClick={onToggleMobileSidebar}
              className="lg:hidden p-2 rounded-md bg-[#181824] text-slate-300 hover:text-white border border-[#1e1e2d]"
              aria-label="Toggle menu"
            >
              <Menu className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-2.5">
              <div className="w-2.5 h-2.5 rounded-full bg-[#00ff88] shadow-[0_0_8px_#00ff88] animate-pulse" />
              <div>
                <span className="text-xs font-mono font-bold tracking-wider text-slate-400 uppercase">
                  QUANTVIEW TERMINAL
                </span>
                <div className="flex items-center gap-2 text-[11px] font-mono text-slate-400">
                  <span className="flex items-center gap-1 text-emerald-400">
                    <Radio className="w-3 h-3 animate-pulse" />
                    LIVE BROKER
                  </span>
                  <span className="text-slate-600">|</span>
                  <span>{account.latencyMs}ms</span>
                  <span className="text-slate-600">|</span>
                  <span className="flex items-center gap-1 text-slate-400">
                    <Clock className="w-3 h-3 text-slate-500" />
                    {utcTime || '00:00:00 UTC'}
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
        <div className="flex items-center justify-between lg:justify-end gap-3 lg:gap-6 flex-wrap">
          {/* Account Balance */}
          <div className="bg-[#0a0a0f] px-3.5 py-1.5 rounded-lg border border-[#1e1e2d]">
            <span className="text-[10px] uppercase tracking-wider font-mono text-slate-400 flex items-center gap-1">
              <Wallet className="w-3 h-3 text-slate-500" />
              Balance
            </span>
            <div className="text-sm lg:text-base font-mono font-bold text-slate-100">
              ${account.balance.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
          </div>

          {/* Equity */}
          <div className="bg-[#0a0a0f] px-3.5 py-1.5 rounded-lg border border-[#1e1e2d]">
            <span className="text-[10px] uppercase tracking-wider font-mono text-slate-400 flex items-center gap-1">
              <Activity className="w-3 h-3 text-slate-500" />
              Equity
            </span>
            <div className="text-sm lg:text-base font-mono font-bold text-slate-100">
              ${account.equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
          </div>

          {/* Unrealized P&L */}
          <div
            className={`px-3.5 py-1.5 rounded-lg border transition-colors ${
              isPnlPositive
                ? 'bg-[#00ff88]/10 border-[#00ff88]/30 text-[#00ff88]'
                : 'bg-[#ff3366]/10 border-[#ff3366]/30 text-[#ff3366]'
            }`}
          >
            <span className="text-[10px] uppercase tracking-wider font-mono opacity-80 flex items-center gap-1">
              {isPnlPositive ? (
                <TrendingUp className="w-3 h-3" />
              ) : (
                <TrendingDown className="w-3 h-3" />
              )}
              Unrealized P&L
            </span>
            <div className="text-sm lg:text-base font-mono font-bold flex items-center gap-1.5">
              <span>
                {isPnlPositive ? '+' : ''}$
                {account.unrealizedPnl.toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </span>
              <span className="text-xs opacity-90">
                ({isPnlPositive ? '+' : ''}
                {account.unrealizedPnlPercent.toFixed(2)}%)
              </span>
            </div>
          </div>

          {/* Polling Indicator & Refresh Button */}
          <div className="flex items-center gap-2">
            <div
              className="hidden sm:flex items-center gap-1.5 px-2 py-1 rounded bg-[#181824] border border-[#1e1e2d] text-[11px] font-mono text-slate-400"
              title="Auto-refresh interval"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping" />
              <span>SYNC {pollSecondsRemaining}s</span>
            </div>

            <button
              onClick={onRefresh}
              className="p-2 rounded-lg bg-[#181824] text-slate-300 hover:text-white hover:bg-[#1f1f30] border border-[#1e1e2d] transition-all"
              title="Manual Data Refresh"
              aria-label="Refresh Data"
            >
              <RefreshCw className="w-4 h-4 text-cyan-400 hover:rotate-180 transition-transform duration-500" />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
};
