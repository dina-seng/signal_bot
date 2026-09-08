import React from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  Calendar,
  AlertTriangle,
  Clock,
  Flame,
  Info,
  ChevronRight,
  TrendingUp,
  RefreshCw,
} from 'lucide-react';
import { NewsEvent, RiskStatus } from '../types';
import { formatTime, getTimeUntil } from '../utils/formatters';

interface NewsRiskMonitorProps {
  news: NewsEvent[];
  riskStatus: RiskStatus;
  isLoading?: boolean;
  onToggleBlackout: () => void;
  onSyncCalendar?: () => void;
}

export const NewsRiskMonitor: React.FC<NewsRiskMonitorProps> = ({
  news,
  riskStatus,
  isLoading = false,
  onToggleBlackout,
  onSyncCalendar,
}) => {
  return (
    <div className="space-y-6">
      {/* Risk Status Banner */}
      <div
        className={`rounded-xl p-5 border transition-all duration-300 shadow-terminal ${
          riskStatus.isBlackout
            ? 'bg-gradient-to-r from-[#ff3366]/20 via-[#18121a] to-[#12121a] border-[#ff3366]/50 shadow-sell-glow'
            : 'bg-gradient-to-r from-[#00ff88]/15 via-[#121814] to-[#12121a] border-[#00ff88]/40 shadow-buy-glow'
        }`}
      >
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div className="flex items-start gap-4">
            <div
              className={`p-3 rounded-xl shrink-0 ${
                riskStatus.isBlackout
                  ? 'bg-[#ff3366]/20 text-[#ff3366] animate-bounce'
                  : 'bg-[#00ff88]/20 text-[#00ff88]'
              }`}
            >
              {riskStatus.isBlackout ? (
                <ShieldAlert className="w-7 h-7" />
              ) : (
                <ShieldCheck className="w-7 h-7" />
              )}
            </div>

            <div className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className={`text-xs font-mono font-bold px-2.5 py-0.5 rounded uppercase tracking-wider border ${
                    riskStatus.isBlackout
                      ? 'bg-[#ff3366]/20 text-[#ff3366] border-[#ff3366]/40 animate-pulse'
                      : 'bg-[#00ff88]/20 text-[#00ff88] border-[#00ff88]/40'
                  }`}
                >
                  {riskStatus.isBlackout ? '🔴 BLACKOUT ACTIVE' : '🟢 SAFE ENVIRONMENT'}
                </span>
                <span className="text-xs font-mono text-slate-400">
                  Risk Per Trade: {riskStatus.allowedRiskPercent}%
                </span>
              </div>

              <h3 className="text-base font-bold text-white">
                {riskStatus.isBlackout
                  ? 'Automated Trading Paused (Macroeconomic Blackout Window)'
                  : 'Institutional Flow Normal — All Systems Operating Safely'}
              </h3>

              <p className="text-xs text-slate-300 font-mono">
                {riskStatus.activeEvent || 'No high-impact red folder events within the -30m / +15m blackout buffer.'}
              </p>
            </div>
          </div>

          {/* Quick Simulation / Test Toggle */}
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={onToggleBlackout}
              className={`px-3 py-2 rounded-lg text-xs font-mono font-bold border transition-all cursor-pointer ${
                riskStatus.isBlackout
                  ? 'bg-[#181824] text-slate-300 hover:text-white border-[#1e1e2d]'
                  : 'bg-[#ff3366]/20 text-[#ff3366] border-[#ff3366]/40 hover:bg-[#ff3366]/30'
              }`}
            >
              {riskStatus.isBlackout ? 'Deactivate Blackout' : 'Simulate Blackout Test'}
            </button>
          </div>
        </div>
      </div>

      {/* Economic Calendar Section */}
      <div className="rounded-xl p-5 bg-[#12121a] border border-[#1e1e2d] shadow-terminal space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 pb-4 border-b border-[#1e1e2d]">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-white">Economic News Calendar</h3>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-cyan-500/15 text-cyan-400 border border-cyan-500/30">
                Live Backend Feed
              </span>
            </div>
            <p className="text-xs text-slate-400 font-mono mt-1">
              Blackout rules: Automated suspension 30 mins before & 15 mins after red-folder events
            </p>
          </div>

          <div className="flex items-center gap-3 text-xs font-mono text-slate-400 flex-wrap">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-[#ff3366]" /> HIGH
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-amber-400" /> MEDIUM
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-slate-500" /> LOW
            </span>

            {onSyncCalendar && (
              <button
                onClick={onSyncCalendar}
                className="ml-2 px-2.5 py-1 rounded bg-[#181824] hover:bg-[#202030] text-slate-300 hover:text-white border border-[#1e1e2d] text-xs font-mono flex items-center gap-1.5 transition-all cursor-pointer"
                title="Sync calendar from ForexFactory"
              >
                <RefreshCw className="w-3 h-3 text-cyan-400" />
                <span>Sync</span>
              </button>
            )}
          </div>
        </div>

        {/* News Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-[#0a0a0f] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1e1e2d]">
              <tr>
                <th scope="col" className="py-2.5 px-4">Time (UTC)</th>
                <th scope="col" className="py-2.5 px-4">Currency</th>
                <th scope="col" className="py-2.5 px-4">Event Name</th>
                <th scope="col" className="py-2.5 px-4 text-center">Impact</th>
                <th scope="col" className="py-2.5 px-4 text-right">Actual</th>
                <th scope="col" className="py-2.5 px-4 text-right">Forecast</th>
                <th scope="col" className="py-2.5 px-4 text-right">Previous</th>
                <th scope="col" className="py-2.5 px-4 text-right">Countdown</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1e1e2d]/60">
              {news.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-slate-500 italic">
                    No scheduled economic news events found in database.
                  </td>
                </tr>
              ) : (
                news.map((item) => {
                  const isHigh = item.impact === 'HIGH';
                  const isMed = item.impact === 'MEDIUM';
                  
                  // Compute dynamic countdown from scheduled time if available
                  const countdown = getTimeUntil(item.scheduledTimeRaw || item.time);
                  const isUrgent = countdown.isWithin30m;
                  const isBlackoutTrigger = (isHigh && isUrgent) || item.isBlackoutTrigger;

                  return (
                    <tr
                      key={item.id}
                      className={`hover:bg-[#181824]/50 transition-colors ${
                        isBlackoutTrigger ? 'bg-[#ff3366]/10 animate-pulse' : ''
                      }`}
                    >
                      {/* Time */}
                      <td className="py-3 px-4 text-slate-300 font-medium whitespace-nowrap">
                        {formatTime(item.time || item.scheduledTimeRaw)}
                      </td>

                      {/* Currency */}
                      <td className="py-3 px-4">
                        <span className="px-2 py-0.5 rounded font-bold bg-[#181824] text-slate-200 border border-[#1e1e2d]">
                          {item.currency}
                        </span>
                      </td>

                      {/* Event Title */}
                      <td className="py-3 px-4 font-semibold text-white">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span>{item.event}</span>
                          {isBlackoutTrigger && (
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-mono uppercase bg-[#ff3366]/20 text-[#ff3366] border border-[#ff3366]/40 shadow-[0_0_8px_rgba(255,51,102,0.3)] animate-pulse">
                              BLACKOUT TRIGGER
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Impact Badge */}
                      <td className="py-3 px-4 text-center">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold border ${
                            isHigh
                              ? 'bg-[#ff3366]/15 text-[#ff3366] border-[#ff3366]/40'
                              : isMed
                              ? 'bg-amber-500/15 text-amber-400 border-amber-500/40'
                              : 'bg-slate-700/30 text-slate-300 border-slate-600/40'
                          }`}
                        >
                          {isHigh && <Flame className="w-3 h-3 text-[#ff3366]" />}
                          {item.impact}
                        </span>
                      </td>

                      {/* Actual */}
                      <td className="py-3 px-4 text-right font-bold text-slate-100">
                        {item.actual || <span className="text-slate-600">--</span>}
                      </td>

                      {/* Forecast */}
                      <td className="py-3 px-4 text-right text-slate-400">
                        {item.forecast || '--'}
                      </td>

                      {/* Previous */}
                      <td className="py-3 px-4 text-right text-slate-500">
                        {item.previous || '--'}
                      </td>

                      {/* Countdown */}
                      <td className="py-3 px-4 text-right font-semibold whitespace-nowrap">
                        {countdown.isPast ? (
                          <span className="text-slate-500">Released</span>
                        ) : (
                          <span
                            className={
                              isUrgent
                                ? 'text-[#ff3366] font-bold animate-pulse'
                                : 'text-cyan-400'
                            }
                          >
                            {countdown.text}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
