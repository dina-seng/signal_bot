import React from 'react';
import {
  LayoutDashboard,
  Zap,
  Briefcase,
  Newspaper,
  Bell,
  Sliders,
  Send,
  Cpu,
  ChevronRight,
  Shield,
} from 'lucide-react';
import { NavigationTab } from '../types';

interface SidebarProps {
  currentTab: NavigationTab;
  onTabChange: (tab: NavigationTab) => void;
  signalsCount: number;
  positionsCount: number;
  isBlackout: boolean;
  isOpenMobile: boolean;
  onCloseMobile: () => void;
  isApiConnected?: boolean;
  isScannerRunning?: boolean;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentTab,
  onTabChange,
  signalsCount,
  positionsCount,
  isBlackout,
  isOpenMobile,
  onCloseMobile,
  isApiConnected = false,
  isScannerRunning = false,
}) => {
  const navItems = [
    {
      id: 'dashboard' as NavigationTab,
      label: 'Dashboard',
      icon: LayoutDashboard,
      badge: null,
    },
    {
      id: 'signals' as NavigationTab,
      label: 'Signals',
      icon: Zap,
      badge: signalsCount > 0 ? `${signalsCount}` : null,
      badgeColor: 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30',
    },
    {
      id: 'positions' as NavigationTab,
      label: 'Positions',
      icon: Briefcase,
      badge: positionsCount > 0 ? `${positionsCount}` : null,
      badgeColor: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30',
    },
    {
      id: 'news' as NavigationTab,
      label: 'News & Risk',
      icon: Newspaper,
      badge: isBlackout ? 'BLACKOUT' : 'SAFE',
      badgeColor: isBlackout
        ? 'bg-[#ff3366]/15 text-[#ff3366] border-[#ff3366]/30'
        : 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30',
    },
    {
      id: 'settings' as NavigationTab,
      label: 'Settings',
      icon: Bell,
      badge: null,
      badgeColor: '',
    },
  ];

  return (
    <>
      {/* Mobile Backdrop */}
      {isOpenMobile && (
        <div
          onClick={onCloseMobile}
          className="fixed inset-0 z-40 bg-black/80 backdrop-blur-xs lg:hidden"
          aria-hidden="true"
        />
      )}

      <aside
        className={`fixed top-0 bottom-0 left-0 z-50 w-56 bg-[#111319] border-r border-[#1d2230] flex flex-col justify-between transition-transform duration-200 ease-in-out lg:translate-x-0 ${
          isOpenMobile ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Navigation Sections */}
        <div>
          {/* Top Branding */}
          <div className="px-4 py-3.5 border-b border-[#1d2230] flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded bg-[#161922] border border-[#1d2230] flex items-center justify-center">
                <Shield className="w-4 h-4 text-[#00e676]" />
              </div>
              <div>
                <span className="text-sm font-bold tracking-tight text-white block leading-tight">
                  Quant<span className="text-[#00e676]">View</span>
                </span>
                <span className="text-[9px] font-mono tracking-wider text-slate-500 uppercase">
                  Institutional Desk
                </span>
              </div>
            </div>
            <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-[#161922] text-slate-400 border border-[#1d2230]">
              v2.4
            </span>
          </div>

          {/* Nav Items */}
          <nav className="p-2 space-y-1">
            <div className="px-2.5 pt-2 pb-1 text-[9px] font-mono tracking-wider text-slate-500 uppercase font-semibold">
              Trading Desk
            </div>
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = currentTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => {
                    onTabChange(item.id);
                    onCloseMobile();
                  }}
                  className={`w-full flex items-center justify-between px-2.5 py-2 rounded text-xs font-medium transition-colors cursor-pointer ${
                    isActive
                      ? 'bg-[#161922] text-white border-l-2 border-[#00e676] border-r border-t border-b border-transparent shadow-xs'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-[#131620]'
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    <Icon
                      className={`w-4 h-4 ${
                        isActive ? 'text-[#00e676]' : 'text-slate-500'
                      }`}
                    />
                    <span>{item.label}</span>
                  </div>

                  {item.badge !== null && (
                    <span
                      className={`px-1.5 py-0.5 text-[9px] font-mono font-bold rounded border ${item.badgeColor}`}
                    >
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Bottom System Services & Diagnostics */}
        <div className="p-3 border-t border-[#1d2230] space-y-2 bg-[#0c0d12]">
          <div className="text-[9px] font-mono uppercase tracking-wider text-slate-500 font-semibold px-1">
            System Telemetry
          </div>

          {/* Telegram bot status */}
          <div className="px-2.5 py-2 rounded bg-[#111319] border border-[#1d2230] space-y-1 font-mono text-[10px]">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-slate-300 font-medium">
                <Send className="w-3 h-3 text-cyan-400" />
                Telegram Bot
              </span>
              <span
                className={`flex items-center gap-1 font-bold ${
                  isApiConnected ? 'text-[#00e676]' : 'text-amber-400'
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    isApiConnected ? 'bg-[#00e676]' : 'bg-amber-400'
                  }`}
                />
                {isApiConnected ? 'ONLINE' : 'STANDBY'}
              </span>
            </div>
            <p className="text-slate-500 truncate text-[9px]">
              @signalTheBEST_bot
            </p>
          </div>

          {/* SMC Scanner status */}
          <div className="px-2.5 py-1.5 rounded bg-[#111319] border border-[#1d2230] flex items-center justify-between text-[10px] font-mono text-slate-400">
            <span className="flex items-center gap-1.5">
              <Cpu className="w-3 h-3 text-slate-500" />
              SMC Scanner
            </span>
            <span className={`font-bold ${isScannerRunning ? 'text-[#00e676]' : isApiConnected ? 'text-slate-300' : 'text-slate-500'}`}>
              {isScannerRunning ? 'ACTIVE' : isApiConnected ? 'READY' : 'OFFLINE'}
            </span>
          </div>
        </div>
      </aside>
    </>
  );
};
