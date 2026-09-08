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
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentTab,
  onTabChange,
  signalsCount,
  positionsCount,
  isBlackout,
  isOpenMobile,
  onCloseMobile,
}) => {
  const navItems = [
    {
      id: 'dashboard' as NavigationTab,
      label: 'Dashboard',
      icon: LayoutDashboard,
      badge: null,
      description: 'Overview & Performance',
    },
    {
      id: 'signals' as NavigationTab,
      label: 'Signals',
      icon: Zap,
      badge: signalsCount,
      badgeColor: 'bg-[#00ff88]/20 text-[#00ff88] border-[#00ff88]/40',
      description: 'Confluence Matrix',
    },
    {
      id: 'positions' as NavigationTab,
      label: 'Positions',
      icon: Briefcase,
      badge: positionsCount,
      badgeColor: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/40',
      description: 'Active Orders & P&L',
    },
    {
      id: 'news' as NavigationTab,
      label: 'News & Risk',
      icon: Newspaper,
      badge: isBlackout ? 'BLACKOUT' : 'SAFE',
      badgeColor: isBlackout
        ? 'bg-[#ff3366]/20 text-[#ff3366] border-[#ff3366]/40'
        : 'bg-[#00ff88]/20 text-[#00ff88] border-[#00ff88]/40',
      description: 'Economic Calendar',
    },
    {
      id: 'settings' as NavigationTab,
      label: 'Settings',
      icon: Bell,
      badge: 'Telegram',
      badgeColor: 'bg-purple-500/20 text-purple-300 border-purple-500/40',
      description: 'Alert Configuration',
    },
  ];

  return (
    <>
      {/* Mobile Backdrop */}
      {isOpenMobile && (
        <div
          onClick={onCloseMobile}
          className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm lg:hidden"
          aria-hidden="true"
        />
      )}

      <aside
        className={`fixed top-0 bottom-0 left-0 z-50 w-64 bg-[#12121a] border-r border-[#1e1e2d] flex flex-col justify-between transition-transform duration-300 ease-in-out lg:translate-x-0 ${
          isOpenMobile ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Top Branding */}
        <div>
          <div className="p-5 border-b border-[#1e1e2d] flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-[#00ff88]/20 to-cyan-500/20 border border-[#00ff88]/40 flex items-center justify-center shadow-[0_0_15px_rgba(0,255,136,0.15)]">
                <Shield className="w-5 h-5 text-[#00ff88]" />
              </div>
              <div>
                <h1 className="text-base font-extrabold tracking-tight text-white flex items-center gap-1.5">
                  Quant<span className="text-[#00ff88]">View</span>
                </h1>
                <p className="text-[10px] font-mono tracking-widest text-slate-400 uppercase">
                  Institutional Desk
                </p>
              </div>
            </div>
            <div className="hidden lg:block px-1.5 py-0.5 rounded text-[9px] font-mono uppercase bg-[#181824] text-slate-400 border border-[#1e1e2d]">
              v2.4
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="p-3 space-y-1.5">
            <div className="px-3 py-1.5 text-[10px] font-mono tracking-wider text-slate-500 uppercase">
              Main Terminal
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
                  className={`w-full group flex items-center justify-between px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
                    isActive
                      ? 'bg-[#181824] text-white border-l-2 border-l-[#00ff88] border border-[#1e1e2d] shadow-sm'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-[#151520]'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <Icon
                      className={`w-4 h-4 transition-colors ${
                        isActive ? 'text-[#00ff88]' : 'text-slate-400 group-hover:text-slate-200'
                      }`}
                    />
                    <div className="text-left">
                      <span className="block leading-tight">{item.label}</span>
                      <span className="text-[10px] text-slate-500 font-mono hidden sm:block">
                        {item.description}
                      </span>
                    </div>
                  </div>

                  {item.badge !== null && (
                    <span
                      className={`px-1.5 py-0.5 text-[10px] font-mono font-semibold rounded border ${item.badgeColor}`}
                    >
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Bottom Status Panel */}
        <div className="p-4 border-t border-[#1e1e2d] space-y-3 bg-[#0d0d14]/60">
          {/* Telegram status indicator */}
          <div className="p-2.5 rounded-lg bg-[#181824] border border-[#1e1e2d] space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="flex items-center gap-1.5 text-slate-300 font-medium">
                <Send className="w-3.5 h-3.5 text-cyan-400" />
                Telegram Bot
              </span>
              <span className="flex items-center gap-1 text-[10px] font-mono text-[#00ff88]">
                <span className="w-1.5 h-1.5 rounded-full bg-[#00ff88] animate-ping" />
                ONLINE
              </span>
            </div>
            <p className="text-[11px] font-mono text-slate-400 truncate">
              @signalTheBEST_bot
            </p>
          </div>

          {/* System status */}
          <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
            <span className="flex items-center gap-1">
              <Cpu className="w-3 h-3 text-slate-500" />
              Confluence Engine
            </span>
            <span className="text-[#00ff88]">READY</span>
          </div>
        </div>
      </aside>
    </>
  );
};
