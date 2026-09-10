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
    <header className="sticky top-0 z-30 w-full bg-[#111319]/95 backdrop-blur-md border-b border-[#1d2230] px-4 lg:px-5 py-2.5">
      <div className="flex items-center justify-between gap-3 flex-wrap xl:flex-nowrap">
        {/* Left: Terminal Branding & Environment Telemetry */}
        <div className="flex items-center gap-3">
          <button
            onClick={onToggleMobileSidebar}
            className="lg:hidden p-1.5 rounded bg-[#161922] text-slate-400 hover:text-white border border-[#1d2230] cursor-pointer"
            aria-label="Toggle navigation menu"
          >
            <Menu className="w-4 h-4" />
          </button>

          {/* Terminal Identifier & Mode Badge */}
          <div className="flex items-center gap-2.5">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-mono font-bold tracking-widest text-slate-100 uppercase">
                QUANT<span className="text-[#00e676]">VIEW</span>
              </span>
              <span className="text-[10px] font-mono text-slate-500 uppercase">TERMINAL</span>
            </div>

            {/* Live Data / Simulation Mode Badge */}
            <span
              className={`px-2 py-0.5 rounded text-[10px] font-mono font-semibold tracking-wider uppercase border flex items-center gap-1.5 ${
                isApiConnected
                  ? 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                  : 'bg-amber-500/10 text-amber-400 border-amber-500/30'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isApiConnected ? 'bg-[#00e676]' : 'bg-amber-400'
                }`}
              />
              {isApiConnected ? 'LIVE DATA' : 'SIMULATION'}
            </span>
          </div>

          {/* Telemetry separator */}
          <div className="hidden sm:flex items-center gap-2 text-[11px] font-mono text-slate-400 pl-2 border-l border-[#1d2230]">
            <span className="flex items-center gap-1 text-slate-300">
              <Radio className={`w-3 h-3 ${isApiConnected ? 'text-[#00e676]' : 'text-slate-500'}`} />
              <span>{isApiConnected ? 'BROKER' : 'OFFLINE'}</span>
            </span>
            <span className="text-slate-600">|</span>
            <span className="text-slate-300">{account.latencyMs}ms</span>
            <span className="text-slate-600">|</span>
            <span className="flex items-center gap-1 text-slate-300">
              <Clock className="w-3 h-3 text-slate-500" />
              <span>{utcTime || '00:00:00 UTC'}</span>
            </span>
            <span className="text-slate-600">|</span>
            <span className="text-slate-500 text-[10px]">
              T-{lastUpdatedSecondsAgo}s
            </span>
          </div>

          {/* Quick Risk Pill */}
          <button
            onClick={onToggleBlackout}
            title="Click to toggle macroeconomic blackout window simulation"
            className={`hidden md:flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-mono font-semibold border transition-all cursor-pointer ${
              riskStatus.isBlackout
                ? 'bg-[#ff3366]/15 text-[#ff3366] border-[#ff3366]/40 hover:bg-[#ff3366]/25'
                : 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30 hover:bg-[#00e676]/20'
            }`}
          >
            {riskStatus.isBlackout ? (
              <>
                <ShieldAlert className="w-3 h-3" />
                <span>BLACKOUT ACTIVE</span>
              </>
            ) : (
              <>
                <ShieldCheck className="w-3 h-3" />
                <span>RISK SAFE</span>
              </>
            )}
          </button>
        </div>

        {/* Right: Financial Metrics & Synchronization Controls */}
        <div className="flex items-center gap-3 sm:gap-4 flex-wrap justify-end">
          {/* Account Balance */}
          <div className="flex items-baseline gap-1.5 px-2.5 py-1 rounded bg-[#0a0b10] border border-[#1d2230] font-mono">
            <span className="text-[10px] uppercase text-slate-500 font-semibold">Bal:</span>
            <span className="text-xs sm:text-sm font-bold text-slate-100">
              {formatCurrency(account.balance)}
            </span>
          </div>

          {/* Equity */}
          <div className="flex items-baseline gap-1.5 px-2.5 py-1 rounded bg-[#0a0b10] border border-[#1d2230] font-mono">
            <span className="text-[10px] uppercase text-slate-500 font-semibold">Eq:</span>
            <span className="text-xs sm:text-sm font-bold text-slate-100">
              {formatCurrency(account.equity)}
            </span>
          </div>

          {/* Floating P&L */}
          <div
            className={`flex items-baseline gap-1.5 px-2.5 py-1 rounded border font-mono ${
              pnlMeta.isPositive
                ? 'bg-[#00e676]/10 border-[#00e676]/30 text-[#00e676]'
                : 'bg-[#ff3366]/10 border-[#ff3366]/30 text-[#ff3366]'
            }`}
          >
            <span className="text-[10px] uppercase opacity-75 font-semibold">P&L:</span>
            <span className="text-xs sm:text-sm font-bold">
              {pnlMeta.formatted}
            </span>
            <span className="text-[10px] opacity-80">
              ({pnlMeta.isPositive ? '+' : ''}{account.unrealizedPnlPercent.toFixed(2)}%)
            </span>
          </div>

          {/* Polling Countdown Indicator */}
          <div
            className="hidden lg:flex items-center gap-1.5 px-2 py-1 rounded bg-[#161922] border border-[#1d2230] text-[10px] font-mono text-slate-400"
            title="Automated sync countdown"
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                isRefreshing ? 'bg-cyan-400 animate-ping' : 'bg-slate-500'
              }`}
            />
            <span>SYNC {pollSecondsRemaining}s</span>
          </div>

          {/* Refresh Action Button */}
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            className={`px-2.5 py-1 rounded bg-[#161922] hover:bg-[#1d212d] text-slate-300 hover:text-white border border-[#1d2230] hover:border-[#282f42] text-xs font-mono font-medium flex items-center gap-1.5 transition-all cursor-pointer ${
              isRefreshing ? 'opacity-70 cursor-wait' : ''
            }`}
            title="Trigger full sync across all endpoints"
            aria-label="Refresh Data"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 text-cyan-400 ${
                isRefreshing ? 'animate-spin' : ''
              }`}
            />
            <span className="hidden sm:inline text-xs">Sync</span>
          </button>
        </div>
      </div>
    </header>
  );
};
