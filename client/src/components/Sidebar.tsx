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
  ChevronDown,
  ChevronUp,
  X,
} from 'lucide-react';
import { NavigationTab } from '../types';

export interface SidebarProps {
  currentTab: NavigationTab;
  onTabChange: (tab: NavigationTab) => void;
  signalsCount: number;
  positionsCount: number;
  isBlackout: boolean;
  isApiConnected?: boolean;
  isScannerRunning?: boolean;
  /** Drawer variant (mobile overlay): labels always visible, nav taps close the drawer. */
  isDrawer?: boolean;
  onCloseMobile?: () => void;
}

const navItemsFor = (
  signalsCount: number,
  positionsCount: number,
  isBlackout: boolean
) => [
  {
    id: 'dashboard' as NavigationTab,
    label: 'Dashboard',
    icon: LayoutDashboard,
    badge: null as string | null,
    badgeColor: '',
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
    badge: null as string | null,
    badgeColor: '',
  },
];

/**
 * Shared sidebar body. Rendered inside the persistent rail (tablet/desktop)
 * and inside the mobile drawer (see MobileMenu.tsx).
 */
export const SidebarContent: React.FC<SidebarProps> = ({
  currentTab,
  onTabChange,
  signalsCount,
  positionsCount,
  isBlackout,
  isApiConnected = false,
  isScannerRunning = false,
  isDrawer = false,
  onCloseMobile,
}) => {
  const [isTelemetryOpen, setIsTelemetryOpen] = useState<boolean>(true);

  // At the 64px tablet rail, text is only revealed while the rail is hovered/focused.
  const showLabel = isDrawer ? '' : 'hidden lg:inline md:group-hover:inline md:group-focus-within:inline';
  const showBlock = isDrawer ? '' : 'hidden lg:block md:group-hover:block md:group-focus-within:block';

  const navItems = navItemsFor(signalsCount, positionsCount, isBlackout);

  const handleNav = (tab: NavigationTab) => {
    onTabChange(tab);
    if (isDrawer) onCloseMobile?.();
  };

  return (
    <div className="flex h-full w-full min-w-0 flex-col justify-between">
      <div className="min-w-0">
        {/* Top Branding */}
        <div
          className={`flex items-center justify-between border-b border-white/10 py-3.5 ${
            isDrawer ? 'px-4' : 'px-4 md:px-3 md:justify-center lg:justify-between lg:px-4 md:group-hover:justify-between md:group-focus-within:justify-between'
          }`}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-8 h-8 shrink-0 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center">
              <Shield className="w-4 h-4 text-emerald-400" />
            </div>
            <div className={`min-w-0 ${showBlock}`}>
              <span className="text-sm font-bold tracking-tight text-white block leading-tight whitespace-nowrap">
                Quant<span className="text-emerald-400">View</span>
              </span>
              <span className="text-[9px] font-mono tracking-wider text-zinc-500 uppercase whitespace-nowrap">
                Institutional Desk
              </span>
            </div>
          </div>

          {isDrawer && (
            <button
              onClick={onCloseMobile}
              className="flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-xl bg-white/5 text-zinc-400 hover:text-white border border-white/10 transition-colors cursor-pointer touch-manipulation"
              aria-label="Close navigation sidebar"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Nav Items with 44px minimum touch targets */}
        <nav className="p-3 space-y-1.5">
          <div className={`px-2.5 pt-2 pb-1 text-[9px] font-mono tracking-wider text-zinc-500 uppercase font-semibold whitespace-nowrap ${showBlock}`}>
            Trading Desk
          </div>
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => handleNav(item.id)}
                title={item.label}
                aria-current={isActive ? 'page' : undefined}
                className={`w-full flex min-h-[44px] items-center justify-between px-3 py-2.5 rounded-xl text-xs font-medium transition-all duration-200 cursor-pointer touch-manipulation ${
                  isDrawer ? '' : 'md:justify-center lg:justify-between md:group-hover:justify-between md:group-focus-within:justify-between'
                } ${
                  isActive
                    ? 'bg-white/10 text-white border border-white/15 shadow-sm'
                    : 'text-zinc-400 hover:text-white hover:bg-white/5'
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <Icon
                    className={`w-4 h-4 shrink-0 ${
                      isActive ? 'text-emerald-400' : 'text-zinc-500'
                    }`}
                  />
                  <span className={`whitespace-nowrap ${showLabel}`}>{item.label}</span>
                </div>

                {item.badge !== null && (
                  <span
                    className={`px-2 py-0.5 text-[9px] font-mono font-semibold rounded-full border shrink-0 ${showLabel} ${item.badgeColor}`}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Bottom System Telemetry (hidden when the tablet rail is collapsed) */}
      <div
        className={`p-3 border-t border-white/10 bg-zinc-950/80 ${
          isDrawer ? '' : 'hidden lg:block md:group-hover:block md:group-focus-within:block'
        }`}
      >
        <div className="flex items-center justify-between pb-1.5">
          <span className="text-[9px] font-mono uppercase tracking-wider text-zinc-500 font-semibold px-1 whitespace-nowrap">
            System Telemetry
          </span>
          <button
            onClick={() => setIsTelemetryOpen((prev) => !prev)}
            className="flex min-h-[32px] min-w-[32px] items-center justify-center p-1 rounded text-zinc-400 hover:text-white cursor-pointer lg:hidden"
            aria-label="Toggle telemetry details"
          >
            {isTelemetryOpen ? (
              <ChevronUp className="w-3.5 h-3.5" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5" />
            )}
          </button>
        </div>

        <div className={`space-y-2 transition-all duration-200 ${isTelemetryOpen ? 'block' : 'hidden lg:block'}`}>
          <div className="px-3 py-2 rounded-xl bg-white/5 border border-white/10 space-y-1 font-mono text-[10px]">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-zinc-300 font-medium whitespace-nowrap">
                <Send className="w-3 h-3 text-cyan-400 shrink-0" />
                Telegram Bot
              </span>
              <span
                className={`flex items-center gap-1 font-bold shrink-0 ${
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
            <p className="text-zinc-500 truncate text-[9px]">@signalTheBEST_bot</p>
          </div>

          <div className="px-3 py-1.5 rounded-xl bg-white/5 border border-white/10 flex items-center justify-between gap-2 text-[10px] font-mono text-zinc-400">
            <span className="flex items-center gap-1.5 whitespace-nowrap">
              <Cpu className="w-3 h-3 text-zinc-500 shrink-0" />
              SMC Scanner
            </span>
            <span
              className={`font-semibold shrink-0 ${
                isScannerRunning ? 'text-emerald-400' : isApiConnected ? 'text-zinc-300' : 'text-zinc-500'
              }`}
            >
              {isScannerRunning ? 'ACTIVE' : isApiConnected ? 'READY' : 'OFFLINE'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

/**
 * Persistent sidebar:
 *  - Desktop (>= lg): fixed 240px, always visible.
 *  - Tablet (md..lg): 64px icon-only rail that expands to 240px on hover/focus.
 *  - Mobile (< md): hidden; rendered on demand by MobileMenu.
 */
export const Sidebar: React.FC<SidebarProps> = (props) => {
  return (
    <aside
      className="group fixed top-0 bottom-0 left-0 z-50 hidden md:flex w-16 lg:w-[240px] md:hover:w-[240px] md:focus-within:w-[240px] flex-col overflow-hidden bg-[#030014]/95 backdrop-blur-xl border-r border-white/10 transition-[width] duration-300 ease-in-out"
      aria-label="Main navigation"
    >
      <SidebarContent {...props} isDrawer={false} />
    </aside>
  );
};
