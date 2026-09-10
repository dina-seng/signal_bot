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
  isSyncingCalendar?: boolean;
  onToggleBlackout: () => void;
  onSyncCalendar?: () => void;
}

export const NewsRiskMonitor: React.FC<NewsRiskMonitorProps> = ({
  news,
  riskStatus,
  isLoading = false,
  isSyncingCalendar = false,
  onToggleBlackout,
  onSyncCalendar,
}) => {
  return (
    <div className="space-y-4 font-mono">
      {/* Risk Status Banner */}
      <div
        className={`rounded-lg p-4 border transition-colors ${
          riskStatus.isBlackout
            ? 'bg-[#181116] border-[#ff3366]/40 text-slate-200'
            : 'bg-[#111614] border-[#00e676]/30 text-slate-200'
        }`}
      >
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div className="flex items-center gap-3">
            <div
              className={`p-2 rounded shrink-0 ${
                riskStatus.isBlackout
                  ? 'bg-[#ff3366]/15 text-[#ff3366]'
                  : 'bg-[#00e676]/10 text-[#00e676]'
              }`}
            >
              {riskStatus.isBlackout ? (
                <ShieldAlert className="w-5 h-5" />
              ) : (
                <ShieldCheck className="w-5 h-5" />
              )}
            </div>

            <div className="space-y-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className={`text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-wider border ${
                    riskStatus.isBlackout
                      ? 'bg-[#ff3366]/20 text-[#ff3366] border-[#ff3366]/40'
                      : 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                  }`}
                >
                  {riskStatus.isBlackout ? '● BLACKOUT ACTIVE' : '○ SAFE TO TRADE'}
                </span>
                <span className="text-[11px] text-slate-400">
                  Risk Per Order: <strong className="text-white">{riskStatus.allowedRiskPercent}%</strong>
                </span>
                <span className="text-slate-600 hidden sm:inline">|</span>
                <span className="text-[10px] text-slate-500 hidden sm:inline">
                  Buffer: -30m / +15m Red Folder
                </span>
              </div>

              <div className="text-xs font-semibold text-white pt-0.5">
                {riskStatus.isBlackout
                  ? 'Automated Order Flow Suspended (High-Impact Macro Event)'
                  : 'Institutional Flow Normal — All Systems Operating Safely'}
              </div>

              <p className="text-[11px] text-slate-400 italic">
                {riskStatus.activeEvent || 'No high-impact economic releases scheduled within the risk buffer window.'}
              </p>
            </div>
          </div>

          {/* Quick Simulation / Test Toggle */}
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={onToggleBlackout}
              className={`px-3 py-1.5 rounded text-xs font-semibold border transition-colors cursor-pointer ${
                riskStatus.isBlackout
                  ? 'bg-[#161922] text-slate-300 hover:text-white border-[#1d2230]'
                  : 'bg-[#ff3366]/15 text-[#ff3366] border-[#ff3366]/30 hover:bg-[#ff3366]/25'
              }`}
            >
              {riskStatus.isBlackout ? 'Deactivate Blackout' : 'Test Blackout'}
            </button>
          </div>
        </div>
      </div>

      {/* Economic Calendar Section */}
      <div className="rounded-lg p-4 bg-[#111319] border border-[#1d2230] space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 pb-2.5 border-b border-[#1d2230]">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-white uppercase tracking-wide">Macroeconomic Calendar</h3>
              <span className="px-1.5 py-0.5 rounded text-[9px] uppercase bg-[#161922] text-slate-400 border border-[#1d2230]">
                ForexFactory Feed
              </span>
            </div>
            <p className="text-[10px] text-slate-500 mt-0.5">
              Blackout rules: 30m prior and 15m after high-impact events automatically trigger trading halt
            </p>
          </div>

          <div className="flex items-center gap-3 text-xs text-slate-400 flex-wrap">
            <span className="flex items-center gap-1 text-[11px]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#ff3366]" /> HIGH
            </span>
            <span className="flex items-center gap-1 text-[11px]">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" /> MEDIUM
            </span>
            <span className="flex items-center gap-1 text-[11px]">
              <span className="w-1.5 h-1.5 rounded-full bg-slate-500" /> LOW
            </span>

            {onSyncCalendar && (
              <button
                onClick={onSyncCalendar}
                disabled={isSyncingCalendar}
                className={`px-2 py-0.5 rounded bg-[#161922] hover:bg-[#1d212d] text-slate-300 hover:text-white border border-[#1d2230] text-xs flex items-center gap-1 transition-colors cursor-pointer ${
                  isSyncingCalendar ? 'opacity-70 cursor-wait' : ''
                }`}
                title="Sync calendar from ForexFactory provider"
              >
                <RefreshCw className={`w-3 h-3 text-cyan-400 ${isSyncingCalendar ? 'animate-spin' : ''}`} />
                <span>{isSyncingCalendar ? 'Syncing...' : 'Sync'}</span>
              </button>
            )}
          </div>
        </div>

        {/* News Table */}
        <div className="overflow-x-auto rounded border border-[#1d2230]">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#0c0d12] text-slate-500 uppercase text-[10px] tracking-wider border-b border-[#1d2230]">
              <tr>
                <th scope="col" className="py-2 px-3">Time (UTC)</th>
                <th scope="col" className="py-2 px-3">CCY</th>
                <th scope="col" className="py-2 px-3">Event</th>
                <th scope="col" className="py-2 px-3 text-center">Impact</th>
                <th scope="col" className="py-2 px-3 text-right">Actual</th>
                <th scope="col" className="py-2 px-3 text-right">Forecast</th>
                <th scope="col" className="py-2 px-3 text-right">Previous</th>
                <th scope="col" className="py-2 px-3 text-right">Countdown</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1d2230]/60 text-[11px]">
              {news.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-6 text-center text-slate-500 italic text-xs">
                    No scheduled economic news events found in database.
                  </td>
                </tr>
              ) : (
                news.map((item) => {
                  const isHigh = item.impact === 'HIGH';
                  const isMed = item.impact === 'MEDIUM';
                  
                  const countdown = getTimeUntil(item.scheduledTimeRaw || item.time);
                  const isUrgent = countdown.isWithin30m;
                  const isBlackoutTrigger = (isHigh && isUrgent) || item.isBlackoutTrigger;

                  return (
                    <tr
                      key={item.id}
                      className={`hover:bg-[#161922]/50 transition-colors ${
                        isBlackoutTrigger ? 'bg-[#ff3366]/10' : ''
                      }`}
                    >
                      {/* Time */}
                      <td className="py-2 px-3 text-slate-400 whitespace-nowrap">
                        {formatTime(item.time || item.scheduledTimeRaw)}
                      </td>

                      {/* Currency */}
                      <td className="py-2 px-3">
                        <span className="px-1.5 py-0.5 rounded font-bold bg-[#161922] text-slate-300 border border-[#1d2230]">
                          {item.currency}
                        </span>
                      </td>

                      {/* Event Title */}
                      <td className="py-2 px-3 font-semibold text-white">
                        <div className="flex items-center gap-2">
                          <span>{item.event}</span>
                          {isBlackoutTrigger && (
                            <span className="px-1 py-0.2 rounded text-[8px] uppercase bg-[#ff3366]/20 text-[#ff3366] border border-[#ff3366]/40">
                              BLACKOUT
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Impact Badge */}
                      <td className="py-2 px-3 text-center">
                        <span
                          className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold border ${
                            isHigh
                              ? 'bg-[#ff3366]/10 text-[#ff3366] border-[#ff3366]/30'
                              : isMed
                              ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                              : 'bg-[#161922] text-slate-400 border-[#1d2230]'
                          }`}
                        >
                          {isHigh && <Flame className="w-2.5 h-2.5 text-[#ff3366]" />}
                          {item.impact}
                        </span>
                      </td>

                      {/* Actual */}
                      <td className="py-2 px-3 text-right font-bold text-slate-200">
                        {item.actual || <span className="text-slate-600">--</span>}
                      </td>

                      {/* Forecast */}
                      <td className="py-2 px-3 text-right text-slate-400">
                        {item.forecast || '--'}
                      </td>

                      {/* Previous */}
                      <td className="py-2 px-3 text-right text-slate-500">
                        {item.previous || '--'}
                      </td>

                      {/* Countdown */}
                      <td className="py-2 px-3 text-right whitespace-nowrap">
                        {countdown.isPast ? (
                          <span className="text-slate-500">Released</span>
                        ) : (
                          <span
                            className={
                              isUrgent
                                ? 'text-[#ff3366] font-bold'
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
