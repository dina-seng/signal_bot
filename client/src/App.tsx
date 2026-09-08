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
import { quantViewApi } from './services/api';

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
  const [isApiConnected, setIsApiConnected] = useState<boolean>(false);
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

  // Simulated tick fallback when backend API is offline
  const refreshSimulatedData = useCallback(() => {
    setPositions((prevPositions) => {
      let updatedFloatingPnl = 0;

      const updated = prevPositions.map((pos) => {
        const isGold = pos.symbol === 'XAU/USD';
        const tickStep = isGold ? 0.35 : pos.symbol === 'USD/JPY' ? 0.02 : 0.00008;
        const delta = (Math.random() - 0.48) * tickStep;
        const newPrice = Number((pos.currentPrice + delta).toFixed(isGold ? 2 : pos.symbol === 'USD/JPY' ? 3 : 5));

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
  }, []);

  // Primary live endpoint polling function
  const fetchEndpointData = useCallback(async () => {
    try {
      // 1. Health check to test connectivity
      const health = await quantViewApi.getHealth();
      setIsApiConnected(true);

      // 2. Fetch real virtual account from /api/v1/paper/account
      try {
        const backendAcc = await quantViewApi.getAccount();
        if (backendAcc) {
          setAccount((prev) => ({
            ...prev,
            balance: backendAcc.balance,
            equity: backendAcc.equity,
            unrealizedPnl: backendAcc.floating_pnl,
            unrealizedPnlPercent: Number(
              ((backendAcc.floating_pnl / (backendAcc.balance || 1)) * 100).toFixed(2)
            ),
            marginUsed: backendAcc.margin_used,
            marginAvailable: backendAcc.free_margin,
            marginLevelPercent: backendAcc.margin_level_pct,
            activePositionsCount: backendAcc.open_positions_count,
            brokerStatus: 'CONNECTED',
            latencyMs: 14,
          }));
        }
      } catch (e) {
        // Continue
      }

      // 3. Fetch real open positions from /api/v1/paper/positions
      try {
        const backendPos = await quantViewApi.getPositions();
        if (backendPos && backendPos.length > 0) {
          setPositions(
            backendPos.map((bp) => ({
              id: String(bp.id),
              symbol: bp.symbol as PairSymbol,
              side: bp.direction,
              size: bp.remaining_position_size,
              entryPrice: bp.entry_price,
              currentPrice: bp.current_price,
              stopLoss: bp.stop_loss,
              takeProfit: bp.take_profit_1,
              pnl: bp.unrealized_pnl,
              pnlPercent: Number(
                (
                  (bp.unrealized_pnl / ((bp.entry_price * bp.remaining_position_size * 1000) || 1)) *
                  100
                ).toFixed(2)
              ),
              pips: bp.pnl_pips,
              openTime:
                new Date(bp.opened_at).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                }) + ' UTC',
            }))
          );
        }
      } catch (e) {
        // Continue
      }

      // 4. Fetch real performance from /api/v1/paper/performance
      try {
        const perf = await quantViewApi.getPerformance();
        if (perf) {
          setStats((prev) => ({
            ...prev,
            winRate: perf.win_rate_pct || prev.winRate,
            profitFactor: perf.profit_factor || prev.profitFactor,
            totalTrades: perf.total_trades || prev.totalTrades,
            maxDrawdown: perf.max_drawdown_pct || prev.maxDrawdown,
            sharpeRatio: perf.sharpe_ratio || prev.sharpeRatio,
            expectancyPips: perf.expectancy_pips || prev.expectancyPips,
          }));
        }
      } catch (e) {
        // Continue
      }

      // 5. Fetch real Telegram Bot Status from /api/v1/telegram/status
      try {
        const tgStatus = await quantViewApi.getTelegramStatus();
        if (tgStatus) {
          setAlertConfig((prev) => ({
            ...prev,
            telegramChatConnected: tgStatus.is_configured,
            telegramBotHandle: '@signalTheBEST_bot',
          }));
        }
      } catch (e) {
        // Continue
      }

      // 6. Check real news blackout from /api/v1/news/check/EUR/USD
      try {
        const blackout = await quantViewApi.checkBlackout('EUR/USD');
        if (blackout) {
          setRiskStatus((prev) => ({
            ...prev,
            isBlackout: blackout.in_blackout,
            statusText: blackout.reason || (blackout.in_blackout ? 'BLACKOUT ACTIVE: Macro event in window' : 'SAFE ENVIRONMENT: Normal trading conditions'),
            allowedRiskPercent: blackout.in_blackout ? 0.0 : 0.5,
          }));
        }
      } catch (e) {
        // Continue
      }

    } catch (err) {
      // Backend not running / offline - fallback to simulation
      setIsApiConnected(false);
      refreshSimulatedData();
    } finally {
      setPollCountdown(10);
    }
  }, [refreshSimulatedData]);

  // Initial load and 10-Second Polling Timer
  useEffect(() => {
    fetchEndpointData();

    const timer = setInterval(() => {
      setPollCountdown((prev) => {
        if (prev <= 1) {
          fetchEndpointData();
          return 10;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [fetchEndpointData]);

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

  // Close position handler connected to /api/v1/paper/positions/{id}/close
  const handleClosePosition = async (id: string, symbol: string) => {
    if (isApiConnected) {
      try {
        await quantViewApi.closePosition(id);
      } catch (err) {
        console.warn('Backend close position returned error:', err);
      }
    }

    const target = positions.find((p) => p.id === id);
    if (!target) return;

    setPositions((prev) => prev.filter((p) => p.id !== id));
    setAccount((prev) => ({
      ...prev,
      balance: Number((prev.balance + target.pnl).toFixed(2)),
      activePositionsCount: Math.max(0, prev.activePositionsCount - 1),
    }));

    addToast(
      target.pnl >= 0 ? 'success' : 'warning',
      'Position Liquidated',
      `Closed ${symbol} (${target.side} ${target.size}L) with P&L: ${target.pnl >= 0 ? '+' : ''}$${target.pnl.toFixed(2)}`
    );
  };

  // Test Notification Button Handler connected to /api/v1/telegram/broadcast
  const handleSendTestNotification = async () => {
    setIsSendingTestTelegram(true);
    setTestNotificationResult(null);

    try {
      // Direct call to FastAPI backend endpoint: POST /api/v1/telegram/broadcast
      const testPayload = `🔔 *QuantView Alert Engine — Test Ping*\n\n• Target: @signalTheBEST_bot\n• System: QuantView Institutional Terminal\n• Event: Alert Configuration Verification\n• Status: ONLINE & DISPATCHED\n• Time: ${new Date().toUTCString()}`;
      
      const res = await quantViewApi.sendTelegramBroadcast(testPayload);

      setIsSendingTestTelegram(false);
      setTestNotificationResult({
        success: true,
        message: `✅ Backend Connected: Telegram broadcast successfully sent via POST /api/v1/telegram/broadcast (Message ID: #${res.message_id || '245'} at ${new Date(res.sent_at).toLocaleTimeString()})`,
      });

      addToast(
        'success',
        'Telegram Endpoint Broadcast Delivered',
        `Payload transmitted via backend API /api/v1/telegram/broadcast to @signalTheBEST_bot.`
      );
    } catch (err: any) {
      // Backend not running or token not verified -> provide clear informative status & simulated fallback
      setIsSendingTestTelegram(false);
      setTestNotificationResult({
        success: true,
        message: `ℹ️ Simulated Dispatch: "QuantView Alert Engine — Test Signal EUR/USD BUY delivered to @signalTheBEST_bot" (Start backend server on port 8000 for live broadcast)`,
      });

      addToast(
        'info',
        'Telegram Simulated Test',
        'FastAPI backend on port 8000 is offline. Ran local simulated dispatch to @signalTheBEST_bot.'
      );
    }
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
          isApiConnected={isApiConnected}
          apiEndpoint="http://localhost:8000"
          onRefresh={fetchEndpointData}
          onToggleMobileSidebar={() => setIsMobileSidebarOpen(!isMobileSidebarOpen)}
          onToggleBlackout={handleToggleBlackout}
        />

        {/* Tab Navigation Pill Bar (Quick filter for views) */}
        <div className="px-4 lg:px-6 pt-4 flex items-center justify-between border-b border-[#1e1e2d]/60 pb-3 flex-wrap gap-3">
          <div className="flex items-center gap-1 bg-[#12121a] p-1 rounded-lg border border-[#1e1e2d] overflow-x-auto">
            <button
              onClick={() => setCurrentTab('dashboard')}
              className={`px-3 py-1.5 rounded-md text-xs font-mono font-bold transition-all cursor-pointer ${
                currentTab === 'dashboard'
                  ? 'bg-[#181824] text-white border border-[#1e1e2d] shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Unified Dashboard
            </button>
            <button
              onClick={() => setCurrentTab('signals')}
              className={`px-3 py-1.5 rounded-md text-xs font-mono font-bold transition-all cursor-pointer ${
                currentTab === 'signals'
                  ? 'bg-[#181824] text-[#00ff88] border border-[#00ff88]/30 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Signals ({signals.length})
            </button>
            <button
              onClick={() => setCurrentTab('positions')}
              className={`px-3 py-1.5 rounded-md text-xs font-mono font-bold transition-all cursor-pointer ${
                currentTab === 'positions'
                  ? 'bg-[#181824] text-cyan-400 border border-cyan-500/30 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Positions ({positions.length})
            </button>
            <button
              onClick={() => setCurrentTab('news')}
              className={`px-3 py-1.5 rounded-md text-xs font-mono font-bold transition-all cursor-pointer ${
                currentTab === 'news'
                  ? 'bg-[#181824] text-amber-400 border border-amber-500/30 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              News & Risk
            </button>
            <button
              onClick={() => setCurrentTab('settings')}
              className={`px-3 py-1.5 rounded-md text-xs font-mono font-bold transition-all cursor-pointer ${
                currentTab === 'settings'
                  ? 'bg-[#181824] text-purple-300 border border-purple-500/30 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Alert Settings
            </button>
          </div>

          <div className="flex items-center gap-3 text-xs font-mono">
            <span className="text-slate-400">Endpoint:</span>
            <span
              className={`px-2 py-0.5 rounded font-bold border ${
                isApiConnected
                  ? 'bg-[#00ff88]/15 text-[#00ff88] border-[#00ff88]/30'
                  : 'bg-amber-500/15 text-amber-400 border-amber-500/30'
              }`}
            >
              {isApiConnected ? 'FASTAPI /api/v1 (LIVE)' : 'FALLBACK SIMULATION'}
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
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-slate-400 font-semibold">QUANTVIEW v2.4.0</span>
            <span>•</span>
            <span>FastAPI Backend: http://localhost:8000</span>
            <span>•</span>
            <span className="text-slate-400">Telegram Bot: @signalTheBEST_bot</span>
          </div>

          <div className="flex items-center gap-3">
            <span
              className={`flex items-center gap-1 ${
                isApiConnected ? 'text-[#00ff88]' : 'text-amber-400'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isApiConnected ? 'bg-[#00ff88] animate-pulse' : 'bg-amber-400'
                }`}
              />
              {isApiConnected ? 'API Connected (10s Polling)' : 'API Standby (Simulation Active)'}
            </span>
            <span>•</span>
            <span>All times UTC</span>
          </div>
        </footer>
      </div>
    </div>
  );
};
