import React, { useState, useEffect, useRef } from 'react';
import {
  RefreshCw,
  Menu,
  Clock,
  Radio,
  ChevronDown,
  ShieldCheck,
  ShieldAlert,
  Zap,
  Activity,
  CheckCircle2,
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
  const [isStatusDropdownOpen, setIsStatusDropdownOpen] = useState<boolean>(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

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

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsStatusDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const pnlMeta = formatPnL(account.unrealizedPnl);

  // Status computation for unified pill
  const isAllGood = isApiConnected && !riskStatus.isBlackout;
  const statusLabel = riskStatus.isBlackout
    ? 'Blackout Active'
    : isApiConnected
    ? 'System Operational'
    : 'Simulation Active';

  return (
    <header className="sticky top-0 z-30 w-full bg-[#030014]/80 backdrop-blur-xl border-b border-white/10 px-4 sm:px-6 lg:px-8 py-2.5 transition-colors">
      <div className="flex items-center justify-between gap-3 flex-wrap lg:flex-nowrap min-w-0">
        {/* Left: Terminal Branding & Unified System Status Pill */}
        <div className="flex items-center gap-3 shrink-0">
          <button
            onClick={onToggleMobileSidebar}
            className="lg:hidden p-2 rounded-xl bg-white/5 text-zinc-400 hover:text-white border border-white/10 transition-colors cursor-pointer"
            aria-label="Toggle navigation menu"
          >
            <Menu className="w-4 h-4" />
          </button>

          {/* Terminal Identifier */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono font-bold tracking-widest text-white uppercase">
              QUANT<span className="text-emerald-400">VIEW</span>
            </span>
            <span className="text-[10px] font-mono text-zinc-500 uppercase">OS</span>
          </div>

          {/* Unified System Status Dropdown Pill (Consolidates LIVE DATA, BROKER, RISK SAFE) */}
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setIsStatusDropdownOpen((prev) => !prev)}
              className={`flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono font-medium border transition-all duration-300 cursor-pointer ${
                riskStatus.isBlackout
                  ? 'bg-rose-500/10 text-rose-400 border-rose-500/30 hover:bg-rose-500/20'
                  : isApiConnected
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25 hover:bg-emerald-500/15'
                  : 'bg-amber-500/10 text-amber-400 border-amber-500/30 hover:bg-amber-500/20'
              }`}
              title="Click to view detailed system telemetry & risk controls"
            >
              {/* Pulsing Status Dot */}
              <span className="relative flex h-2 w-2">
                <span
                  className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                    riskStatus.isBlackout
                      ? 'bg-rose-400'
                      : isApiConnected
                      ? 'bg-emerald-400'
                      : 'bg-amber-400'
                  }`}
                />
                <span
                  className={`relative inline-flex rounded-full h-2 w-2 ${
                    riskStatus.isBlackout
                      ? 'bg-rose-400'
                      : isApiConnected
                      ? 'bg-emerald-400'
                      : 'bg-amber-400'
                  }`}
                />
              </span>

              <span>{statusLabel}</span>

              <ChevronDown
                className={`w-3.5 h-3.5 transition-transform duration-200 ${
                  isStatusDropdownOpen ? 'rotate-180' : ''
                }`}
              />
            </button>

            {/* De-cluttered Interactive Telemetry Popover */}
            {isStatusDropdownOpen && (
              <div className="absolute left-0 mt-2 w-72 rounded-2xl bg-zinc-950/95 backdrop-blur-xl border border-white/15 p-3.5 shadow-2xl z-50 animate-in fade-in zoom-in-95 duration-150 font-mono text-xs">
                <div className="flex items-center justify-between pb-2.5 border-b border-white/10">
                  <span className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">
                    System Telemetry
                  </span>
                  <span className="text-[10px] text-zinc-500">{utcTime || 'UTC Clock'}</span>
                </div>

                <div className="space-y-2.5 py-2.5 text-xs">
                  {/* Market Data Feed */}
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-400 flex items-center gap-1.5">
                      <Radio className="w-3.5 h-3.5 text-zinc-500" />
                      Data Feed
                    </span>
                    <span
                      className={`font-semibold flex items-center gap-1 ${
                        isApiConnected ? 'text-emerald-400' : 'text-amber-400'
                      }`}
                    >
                      <CheckCircle2 className="w-3 h-3" />
                      {isApiConnected ? 'Live FastFeed' : 'Simulated'}
                    </span>
                  </div>

                  {/* Broker & Latency */}
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-400 flex items-center gap-1.5">
                      <Activity className="w-3.5 h-3.5 text-zinc-500" />
                      Broker Gateway
                    </span>
                    <span className="text-white font-medium">
                      MetaTrader / FIX ({account.latencyMs}ms)
                    </span>
                  </div>

                  {/* Sync Age */}
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-400 flex items-center gap-1.5">
                      <Clock className="w-3.5 h-3.5 text-zinc-500" />
                      Last Sync
                    </span>
                    <span className="text-zinc-300">T-{lastUpdatedSecondsAgo}s ago</span>
                  </div>

                  {/* Risk Gate Status */}
                  <div className="flex items-center justify-between pt-1 border-t border-white/10">
                    <span className="text-zinc-400 flex items-center gap-1.5">
                      <ShieldCheck className="w-3.5 h-3.5 text-zinc-500" />
                      Risk Firewall
                    </span>
                    <span
                      className={`font-semibold ${
                        riskStatus.isBlackout ? 'text-rose-400' : 'text-emerald-400'
                      }`}
                    >
                      {riskStatus.isBlackout ? 'Blackout Enforced' : 'Risk Cleared'}
                    </span>
                  </div>
                </div>

                {/* Macro Blackout Toggle */}
                <div className="pt-2 border-t border-white/10">
                  <button
                    onClick={() => {
                      onToggleBlackout();
                    }}
                    className={`w-full py-1.5 px-2.5 rounded-xl font-medium text-xs flex items-center justify-center gap-2 transition-all cursor-pointer ${
                      riskStatus.isBlackout
                        ? 'bg-rose-500/20 text-rose-300 hover:bg-rose-500/30 border border-rose-500/40'
                        : 'bg-white/5 text-zinc-300 hover:bg-white/10 border border-white/10'
                    }`}
                  >
                    {riskStatus.isBlackout ? (
                      <>
                        <ShieldAlert className="w-3.5 h-3.5 text-rose-400" />
                        <span>Disable Blackout Override</span>
                      </>
                    ) : (
                      <>
                        <ShieldAlert className="w-3.5 h-3.5 text-zinc-400" />
                        <span>Simulate High-Impact Blackout</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right: Glassmorphic Financial Metrics & Synchronization Controls (Fluid wrapping & no squish) */}
        <div className="flex items-center gap-2 sm:gap-2.5 flex-wrap sm:flex-nowrap overflow-x-auto max-w-full py-0.5 justify-end">
          {/* Account Balance */}
          <div className="flex items-baseline gap-1.5 px-2.5 sm:px-3 py-1.5 rounded-xl bg-white/5 backdrop-blur-md border border-white/10 font-mono transition-all hover:bg-white/[0.08] shrink-0">
            <span className="text-[10px] uppercase text-zinc-400 font-semibold tracking-wider">BAL:</span>
            <span className="text-xs sm:text-sm font-semibold text-white">
              {formatCurrency(account.balance)}
            </span>
          </div>

          {/* Equity */}
          <div className="flex items-baseline gap-1.5 px-2.5 sm:px-3 py-1.5 rounded-xl bg-white/5 backdrop-blur-md border border-white/10 font-mono transition-all hover:bg-white/[0.08] shrink-0">
            <span className="text-[10px] uppercase text-zinc-400 font-semibold tracking-wider">EQ:</span>
            <span className="text-xs sm:text-sm font-semibold text-white">
              {formatCurrency(account.equity)}
            </span>
          </div>

          {/* Floating P&L */}
          <div
            className={`flex items-baseline gap-1.5 px-2.5 sm:px-3 py-1.5 rounded-xl backdrop-blur-md border font-mono transition-all shrink-0 ${
              pnlMeta.isPositive
                ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400 hover:bg-emerald-500/15'
                : 'bg-rose-500/10 border-rose-500/20 text-rose-400 hover:bg-rose-500/15'
            }`}
          >
            <span className="text-[10px] uppercase opacity-75 font-semibold tracking-wider">P&amp;L:</span>
            <span className="text-xs sm:text-sm font-semibold">
              {pnlMeta.formatted}
            </span>
            <span className="text-[10px] opacity-80">
              ({pnlMeta.isPositive ? '+' : ''}{account.unrealizedPnlPercent.toFixed(2)}%)
            </span>
          </div>

          {/* Polling Countdown Indicator */}
          <div
            className="hidden md:flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl bg-white/5 border border-white/10 text-[10px] font-mono text-zinc-400 shrink-0"
            title="Automated backend sync countdown"
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                isRefreshing ? 'bg-cyan-400 animate-ping' : 'bg-zinc-500'
              }`}
            />
            <span>SYNC {pollSecondsRemaining}s</span>
          </div>

          {/* Refresh Action Button */}
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            className={`px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white font-sans text-xs font-semibold flex items-center gap-1.5 border border-violet-400/30 shadow-[0_0_20px_rgba(124,58,237,0.35)] hover:shadow-[0_0_25px_rgba(124,58,237,0.55)] transition-all duration-300 cursor-pointer shrink-0 ${
              isRefreshing ? 'opacity-70 cursor-wait' : ''
            }`}
            title="Trigger manual sync across all API endpoints"
            aria-label="Refresh Data"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 text-white ${
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
