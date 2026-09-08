import React, { useState, useEffect, useCallback } from 'react';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { PerformanceDashboard } from './components/PerformanceDashboard';
import { SignalMatrix } from './components/SignalMatrix';
import { ActivePositionsTable } from './components/ActivePositionsTable';
import { NotificationSettings } from './components/NotificationSettings';
import { NewsRiskMonitor } from './components/NewsRiskMonitor';
import { TradingChart } from './components/TradingChart';
import { ToastContainer, ToastMessage } from './components/Toast';
import {
  NavigationTab,
  PairSymbol,
  TradeSignal,
  Position,
  AlertConfiguration,
  RiskStatus,
} from './types';
import {
  initialAccountSummary,
  initialPerformanceStats,
  initialSignals,
  initialPositions,
  initialAlertConfig,
  initialNewsEvents,
  initialRiskStatus,
} from './data/mockData';

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<NavigationTab>('dashboard');
  const [account, setAccount] = useState(initialAccountSummary);
  const [stats, setStats] = useState(initialPerformanceStats);
  const [signals, setSignals] = useState<TradeSignal[]>(initialSignals);
  const [positions, setPositions] = useState<Position[]>(initialPositions);
  const [alertConfig, setAlertConfig] = useState<AlertConfiguration>(initialAlertConfig);
  const [news, setNews] = useState(initialNewsEvents);
  const [riskStatus, setRiskStatus] = useState<RiskStatus>(initialRiskStatus);
  const [selectedChartSymbol, setSelectedChartSymbol] = useState<PairSymbol>('EUR/USD');
  const [pollCountdown, setPollCountdown] = useState<number>(10);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState<boolean>(false);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [isSendingTestTelegram, setIsSendingTestTelegram] = useState<boolean>(false);
  const [testNotificationResult, setTestNotificationResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

  // Helper to trigger floating toasts
  const addToast = useCallback((type: 'success' | 'warning' | 'info', title: string, message: string) => {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((prev) => [...prev, { id, type, title, message }]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Real-time market tick simulation (every 10s cycle)
  const refreshMarketData = useCallback(() => {
    setPositions((prevPositions) => {
      let updatedFloatingPnl = 0;

      const updated = prevPositions.map((pos) => {
        const isGold = pos.symbol === 'XAU/USD';
        const tickStep = isGold ? 0.35 : pos.symbol === 'USD/JPY' ? 0.02 : 0.00008;
        const delta = (Math.random() - 0.48) * tickStep;
        const newPrice = Number((pos.currentPrice + delta).toFixed(isGold ? 2 : pos.symbol === 'USD/JPY' ? 3 : 5));

        // Recompute pnl
        let pips = 0;
        if (isGold) {
          pips = pos.side === 'BUY' ? (newPrice - pos.entryPrice) * 10 : (pos.entryPrice - newPrice) * 10;
        } else if (pos.symbol === 'USD/JPY') {
          pips = pos.side === 'BUY' ? (newPrice - pos.entryPrice) * 100 : (pos.entryPrice - newPrice) * 100;
        } else {
          pips = pos.side === 'BUY' ? (newPrice - pos.entryPrice) * 10000 : (pos.entryPrice - newPrice) * 10000;
        }

        const pipValue = pos.size * (isGold ? 10 : 10);
        const pnl = Number((pips * pipValue).toFixed(2));
        updatedFloatingPnl += pnl;

        return {
          ...pos,
          currentPrice: newPrice,
          pips: Number(pips.toFixed(1)),
          pnl,
        };
      });

      // Update Account floating equity
      setAccount((prevAcc) => {
        const equity = Number((prevAcc.balance + updatedFloatingPnl).toFixed(2));
        const unrealizedPnl = Number(updatedFloatingPnl.toFixed(2));
        const unrealizedPnlPercent = Number(((unrealizedPnl / prevAcc.balance) * 100).toFixed(2));
        return {
          ...prevAcc,
          equity,
          unrealizedPnl,
          unrealizedPnlPercent,
          latencyMs: Math.floor(Math.random() * 8 + 12),
        };
      });

      return updated;
    });

    setPollCountdown(10);
  }, []);

  // 10-Second Polling Timer
  useEffect(() => {
    const timer = setInterval(() => {
      setPollCountdown((prev) => {
        if (prev <= 1) {
          refreshMarketData();
          return 10;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [refreshMarketData]);

  // Per-pair notification toggle
  const handleToggleNotify = (id: string, symbol: PairSymbol, currentVal: boolean) => {
    const newVal = !currentVal;
    setSignals((prev) =>
      prev.map((s) => (s.id === id ? { ...s, notifyEnabled: newVal } : s))
    );

    if (newVal) {
      addToast(
        'success',
        'Pair Alert Enabled',
        `Instant Telegram notifications active for ${symbol} (@signalTheBEST_bot).`
      );
    } else {
      addToast(
        'info',
        'Pair Alert Disabled',
        `Muted Telegram alerts for ${symbol}.`
      );
    }
  };

  // Close position handler
  const handleClosePosition = (id: string, symbol: string) => {
    const target = positions.find((p) => p.id === id);
    if (!target) return;

    setPositions((prev) => prev.filter((p) => p.id !== id));
    setAccount((prev) => ({
      ...prev,
      balance: Number((prev.balance + target.pnl).toFixed(2)),
      activePositionsCount: prev.activePositionsCount - 1,
    }));

    addToast(
      target.pnl >= 0 ? 'success' : 'warning',
      'Position Liquidated',
      `Closed ${symbol} (${target.side} ${target.size}L) with P&L: ${target.pnl >= 0 ? '+' : ''}$${target.pnl.toFixed(2)}`
    );
  };

  // Test Notification Button Handler (Telegram simulation)
  const handleSendTestNotification = async () => {
    setIsSendingTestTelegram(true);
    setTestNotificationResult(null);

    // Simulate backend network API request to /api/v1/telegram/test-alert
    setTimeout(() => {
      setIsSendingTestTelegram(false);
      setTestNotificationResult({
        success: true,
        message: '✅ Telegram Test Dispatched: "QuantView Alert Engine — Test Signal EUR/USD BUY @ 1.08450 delivered to @signalTheBEST_bot"',
      });

      addToast(
        'success',
        'Telegram Test Sent',
        'Payload delivered to bot @signalTheBEST_bot successfully via FastAPI webhook.'
      );
    }, 1200);
  };

  // Toggle Risk / Blackout simulation
  const handleToggleBlackout = () => {
    setRiskStatus((prev) => {
      const nextBlackout = !prev.isBlackout;
      if (nextBlackout) {
        addToast(
          'warning',
          'Blackout Engaged',
          'High-impact event imminent. Automated trading & new signal entries suspended.'
        );
        return {
          isBlackout: true,
          statusText: 'BLACKOUT ACTIVE: High-Impact Macro Window. Automated entries paused.',
          allowedRiskPercent: 0.0,
          activeEvent: 'USD Core CPI in 14m (Blackout window: -30m / +15m)',
          minutesRemaining: 14,
        };
      } else {
        addToast(
          'success',
          'Blackout Cleared',
          'Safe risk environment restored. Automated confluence scanning resumed.'
        );
        return {
          isBlackout: false,
          statusText: 'SAFE TO TRADE — No immediate high-impact blackout in effect',
          allowedRiskPercent: 0.5,
          activeEvent: 'Normal volatility conditions (Risk cap: 0.5% per trade)',
          minutesRemaining: 0,
        };
      }
    });
  };

  const handleSelectSignalForChart = (symbol: PairSymbol) => {
    setSelectedChartSymbol(symbol);
    // Smooth scroll to chart if on dashboard, or switch
    const chartEl = document.getElementById('chart-section');
    if (chartEl) {
      chartEl.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-slate-200 flex flex-col font-sans">
      {/* Toast notifications */}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Sidebar Navigation */}
      <Sidebar
        currentTab={currentTab}
        onTabChange={(tab) => setCurrentTab(tab)}
        signalsCount={signals.length}
        positionsCount={positions.length}
        isBlackout={riskStatus.isBlackout}
        isOpenMobile={isMobileSidebarOpen}
        onCloseMobile={() => setIsMobileSidebarOpen(false)}
      />

      {/* Main Wrapper with Left Margin for Fixed Sidebar on Large Screens */}
      <div className="lg:pl-64 flex flex-col min-h-screen">
        {/* Top Header */}
        <Header
          account={account}
          riskStatus={riskStatus}
          pollSecondsRemaining={pollCountdown}
          onRefresh={refreshMarketData}
          onToggleMobileSidebar={() => setIsMobileSidebarOpen(!isMobileSidebarOpen)}
          onToggleBlackout={handleToggleBlackout}
        />

        {/* Tab Navigation Pill Bar (Quick filter for views) */}
        <div className="px-4 lg:px-6 pt-4 flex items-center justify-between border-b border-[#1e1e2d]/60 pb-3">
          <div className="flex items-center gap-1 bg-[#12121a] p-1 rounded-lg border border-[#1e1e2d] overflow-x-auto">
            <button
              onClick={() => setCurrentTab('dashboard')}
              className={`px-3 py-1.5 rounded-md text-xs font-mono font-bold transition-all ${
                currentTab === 'dashboard'
                  ? 'bg-[#181824] text-white border border-[#1e1e2d] shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Unified Dashboard
            </button>
            <button
              onClick={() => setCurrentTab('signals')}
              className={`px-3 py-1.5 rounded-md text-xs font-mono font-bold transition-all ${
                currentTab === 'signals'
                  ? 'bg-[#181824] text-[#00ff88] border border-[#00ff88]/30 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Signals ({signals.length})
            </button>
            <button
              onClick={() => setCurrentTab('positions')}
              className={`px-3 py-1.5 rounded-md text-xs font-mono font-bold transition-all ${
                currentTab === 'positions'
                  ? 'bg-[#181824] text-cyan-400 border border-cyan-500/30 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Positions ({positions.length})
            </button>
            <button
              onClick={() => setCurrentTab('news')}
              className={`px-3 py-1.5 rounded-md text-xs font-mono font-bold transition-all ${
                currentTab === 'news'
                  ? 'bg-[#181824] text-amber-400 border border-amber-500/30 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              News & Risk
            </button>
            <button
              onClick={() => setCurrentTab('settings')}
              className={`px-3 py-1.5 rounded-md text-xs font-mono font-bold transition-all ${
                currentTab === 'settings'
                  ? 'bg-[#181824] text-purple-300 border border-purple-500/30 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Alert Settings
            </button>
          </div>

          <div className="hidden sm:flex items-center gap-2 text-xs font-mono text-slate-400">
            <span>Terminal Mode:</span>
            <span className="text-emerald-400 font-bold bg-[#12121a] px-2 py-0.5 rounded border border-[#1e1e2d]">
              PAPER TRADING
            </span>
          </div>
        </div>

        {/* Main Content Body */}
        <main className="flex-1 p-4 lg:p-6 space-y-6 max-w-[1600px] w-full mx-auto">
          {/* 1. UNIFIED DASHBOARD TAB */}
          {currentTab === 'dashboard' && (
            <>
              {/* Performance Stats & Equity Curve */}
              <PerformanceDashboard stats={stats} />

              {/* Signal Matrix Grid (4 Cards) */}
              <SignalMatrix
                signals={signals}
                onToggleNotify={handleToggleNotify}
                onSelectSignalForChart={handleSelectSignalForChart}
              />

              {/* Candlestick Chart Area Placeholder */}
              <div id="chart-section">
                <TradingChart
                  selectedSymbol={selectedChartSymbol}
                  onSymbolChange={(sym) => setSelectedChartSymbol(sym)}
                />
              </div>

              {/* Active Positions Table */}
              <ActivePositionsTable
                positions={positions}
                onClosePosition={handleClosePosition}
              />

              {/* News & Risk Status */}
              <NewsRiskMonitor
                news={news}
                riskStatus={riskStatus}
                onToggleBlackout={handleToggleBlackout}
              />

              {/* Notification Settings Panel */}
              <NotificationSettings
                config={alertConfig}
                onUpdateConfig={setAlertConfig}
                onSendTestNotification={handleSendTestNotification}
                isSendingTest={isSendingTestTelegram}
                testNotificationResult={testNotificationResult}
              />
            </>
          )}

          {/* 2. DEDICATED SIGNALS TAB */}
          {currentTab === 'signals' && (
            <div className="space-y-6">
              <SignalMatrix
                signals={signals}
                onToggleNotify={handleToggleNotify}
                onSelectSignalForChart={handleSelectSignalForChart}
              />
              <div id="chart-section">
                <TradingChart
                  selectedSymbol={selectedChartSymbol}
                  onSymbolChange={(sym) => setSelectedChartSymbol(sym)}
                />
              </div>
            </div>
          )}

          {/* 3. DEDICATED POSITIONS TAB */}
          {currentTab === 'positions' && (
            <div className="space-y-6">
              <ActivePositionsTable
                positions={positions}
                onClosePosition={handleClosePosition}
              />
              <div id="chart-section">
                <TradingChart
                  selectedSymbol={selectedChartSymbol}
                  onSymbolChange={(sym) => setSelectedChartSymbol(sym)}
                />
              </div>
            </div>
          )}

          {/* 4. DEDICATED NEWS & RISK TAB */}
          {currentTab === 'news' && (
            <div className="space-y-6">
              <NewsRiskMonitor
                news={news}
                riskStatus={riskStatus}
                onToggleBlackout={handleToggleBlackout}
              />
            </div>
          )}

          {/* 5. DEDICATED NOTIFICATION SETTINGS TAB */}
          {currentTab === 'settings' && (
            <div className="space-y-6">
              <NotificationSettings
                config={alertConfig}
                onUpdateConfig={setAlertConfig}
                onSendTestNotification={handleSendTestNotification}
                isSendingTest={isSendingTestTelegram}
                testNotificationResult={testNotificationResult}
              />
            </div>
          )}
        </main>

        {/* Terminal Footer Bar */}
        <footer className="mt-auto border-t border-[#1e1e2d] bg-[#0d0d14] px-4 lg:px-6 py-2.5 text-[11px] font-mono text-slate-500 flex flex-col sm:flex-row items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            <span className="text-slate-400 font-semibold">QUANTVIEW v2.4.0</span>
            <span>•</span>
            <span>SMC Confluence Engine</span>
            <span>•</span>
            <span className="text-slate-400">Telegram Bot: @signalTheBEST_bot</span>
          </div>

          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1 text-[#00ff88]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#00ff88]" />
              WebSocket: 10s Poll Active
            </span>
            <span>•</span>
            <span>All times UTC</span>
          </div>
        </footer>
      </div>
    </div>
  );
};
