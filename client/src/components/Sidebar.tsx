import React, { useState } from 'react';
import {
  LayoutDashboard,
  Zap,
  Briefcase,
  Newspaper,
  Bell,
  Send,
  Cpu,
  Shield,
  X,
  ChevronDown,
  ChevronUp,
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
  const [isTelemetryOpen, setIsTelemetryOpen] = useState<boolean>(true);

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
      badgeColor: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25',
    },
    {
      id: 'positions' as NavigationTab,
      label: 'Positions',
      icon: Briefcase,
      badge: positionsCount > 0 ? `${positionsCount}` : null,
      badgeColor: 'bg-sky-500/10 text-sky-400 border-sky-500/25',
    },
    {
      id: 'news' as NavigationTab,
      label: 'News & Risk',
      icon: Newspaper,
      badge: isBlackout ? 'BLACKOUT' : 'SAFE',
      badgeColor: isBlackout
        ? 'bg-rose-500/15 text-rose-400 border-rose-500/30'
        : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25',
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
      {/* Mobile / Tablet Backdrop (active on screens < 1024px) */}
      {isOpenMobile && (
        <div
          onClick={onCloseMobile}
          className="fixed inset-0 z-40 bg-black/80 backdrop-blur-sm lg:hidden transition-opacity duration-300"
          aria-hidden="true"
        />
      )}

      {/* Sidebar: Fixed 240px on Desktop (>1024px); Collapsible / Slide-in on Tablet & Mobile (<1024px) */}
      <aside
        className={`fixed top-0 bottom-0 left-0 z-50 w-[240px] bg-[#030014]/95 backdrop-blur-xl border-r border-white/10 flex flex-col justify-between transition-transform duration-300 ease-in-out lg:translate-x-0 ${
          isOpenMobile ? 'translate-x-0 shadow-2xl' : '-translate-x-full'
        }`}
      >
        {/* Navigation Sections */}
        <div>
          {/* Top Branding & Mobile Close Button */}
          <div className="px-4 py-3.5 border-b border-white/10 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center">
                <Shield className="w-4 h-4 text-emerald-400" />
              </div>
              <div>
                <span className="text-sm font-bold tracking-tight text-white block leading-tight">
                  Quant<span className="text-emerald-400">View</span>
                </span>
                <span className="text-[9px] font-mono tracking-wider text-zinc-500 uppercase">
                  Institutional Desk
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 rounded-full text-[9px] font-mono bg-white/5 text-zinc-400 border border-white/10 hidden sm:inline">
                v2.4
              </span>

              {/* Close Button on Mobile / Tablet */}
              <button
                onClick={onCloseMobile}
                className="lg:hidden flex min-h-[44px] min-w-[44px] items-center justify-center p-2 rounded-xl bg-white/5 text-zinc-400 hover:text-white border border-white/10 transition-colors cursor-pointer"
                aria-label="Close navigation sidebar"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Nav Items with generous 44px minimum touch targets */}
          <nav className="p-3 space-y-1.5">
            <div className="px-2.5 pt-2 pb-1 text-[9px] font-mono tracking-wider text-zinc-500 uppercase font-semibold">
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
                  className={`w-full flex min-h-[44px] items-center justify-between px-3 py-2.5 rounded-xl text-xs font-medium transition-all duration-200 cursor-pointer ${
                    isActive
                      ? 'bg-white/10 text-white border border-white/15 shadow-sm'
                      : 'text-zinc-400 hover:text-white hover:bg-white/5'
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    <Icon
                      className={`w-4 h-4 ${
                        isActive ? 'text-emerald-400' : 'text-zinc-500'
                      }`}
                    />
                    <span>{item.label}</span>
                  </div>

                  {item.badge !== null && (
                    <span
                      className={`px-2 py-0.5 text-[9px] font-mono font-semibold rounded-full border ${item.badgeColor}`}
                    >
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Bottom System Telemetry (Collapsible on Mobile/Tablet to save vertical space) */}
        <div className="p-3 border-t border-white/10 bg-zinc-950/80">
          <div className="flex items-center justify-between pb-1.5">
            <span className="text-[9px] font-mono uppercase tracking-wider text-zinc-500 font-semibold px-1">
              System Telemetry
            </span>
            <button
              onClick={() => setIsTelemetryOpen((prev) => !prev)}
              className="lg:hidden flex min-h-[32px] min-w-[32px] items-center justify-center p-1 rounded text-zinc-400 hover:text-white cursor-pointer"
              aria-label="Toggle telemetry details"
            >
              {isTelemetryOpen ? (
                <ChevronUp className="w-3.5 h-3.5" />
              ) : (
                <ChevronDown className="w-3.5 h-3.5" />
              )}
            </button>
          </div>

          {/* Telemetry body (collapsible on mobile/tablet, always open on desktop) */}
          <div className={`space-y-2 transition-all duration-200 ${isTelemetryOpen ? 'block' : 'hidden lg:block'}`}>
            {/* Telegram bot status */}
            <div className="px-3 py-2 rounded-xl bg-white/5 border border-white/10 space-y-1 font-mono text-[10px]">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-zinc-300 font-medium">
                  <Send className="w-3 h-3 text-cyan-400" />
                  Telegram Bot
                </span>
                <span
                  className={`flex items-center gap-1 font-bold ${
                    isApiConnected ? 'text-emerald-400' : 'text-amber-400'
                  }`}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      isApiConnected ? 'bg-emerald-400' : 'bg-amber-400'
                    }`}
                  />
                  {isApiConnected ? 'ONLINE' : 'STANDBY'}
                </span>
              </div>
              <p className="text-zinc-500 truncate text-[9px]">
                @signalTheBEST_bot
              </p>
            </div>

            {/* SMC Scanner status */}
            <div className="px-3 py-1.5 rounded-xl bg-white/5 border border-white/10 flex items-center justify-between text-[10px] font-mono text-zinc-400">
              <span className="flex items-center gap-1.5">
                <Cpu className="w-3 h-3 text-zinc-500" />
                SMC Scanner
              </span>
              <span className={`font-semibold ${isScannerRunning ? 'text-emerald-400' : isApiConnected ? 'text-zinc-300' : 'text-zinc-500'}`}>
                {isScannerRunning ? 'ACTIVE' : isApiConnected ? 'READY' : 'OFFLINE'}
              </span>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
};
