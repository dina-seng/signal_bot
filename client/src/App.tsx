import React, { useState, useEffect, useCallback, useRef } from 'react';
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
  NewsEvent,
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
import {
  quantViewApi,
  BackendAccount,
  BackendPosition,
  BackendSignal,
  BackendNewsEvent,
  BackendPerformance,
} from './services/api';
import { formatPrice, getTimeUntil } from './utils/formatters';
import { AlertTriangle, RefreshCw } from 'lucide-react';

const SUPPORTED_PAIRS: PairSymbol[] = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'XAU/USD'];

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<NavigationTab>('dashboard');
  const [account, setAccount] = useState(initialAccountSummary);
  const [stats, setStats] = useState(initialPerformanceStats);
  const [signals, setSignals] = useState<TradeSignal[]>(initialSignals);
  const [positions, setPositions] = useState<Position[]>(initialPositions);
  const [alertConfig, setAlertConfig] = useState<AlertConfiguration>(initialAlertConfig);
  const [news, setNews] = useState<NewsEvent[]>(initialNewsEvents);
  const [riskStatus, setRiskStatus] = useState<RiskStatus>(initialRiskStatus);
  const [selectedChartSymbol, setSelectedChartSymbol] = useState<PairSymbol>('EUR/USD');
  const [livePrices, setLivePrices] = useState<Record<string, number>>({});

  // Loading, timing & error states
  const [isInitialLoading, setIsInitialLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [isApiConnected, setIsApiConnected] = useState<boolean>(false);
  const [apiResponseTimeMs, setApiResponseTimeMs] = useState<number>(24);
  const [lastUpdatedSecondsAgo, setLastUpdatedSecondsAgo] = useState<number>(0);
  const [apiErrorMessage, setApiErrorMessage] = useState<string | null>(null);
  const [pollCountdown, setPollCountdown] = useState<number>(3);

  // UI interaction states
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState<boolean>(false);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [isSendingTestTelegram, setIsSendingTestTelegram] = useState<boolean>(false);
  const [testNotificationResult, setTestNotificationResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

  const lastFetchTimestampRef = useRef<number>(Date.now());

  // Helper to trigger floating toasts
  const addToast = useCallback((type: 'success' | 'warning' | 'info', title: string, message: string) => {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((prev) => [...prev, { id, type, title, message }]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // 1. Fetch Account & Positions (Every 3 seconds)
  const fetchAccountAndPositions = useCallback(async () => {
    try {
      // Fetch Account
      const accRes = await quantViewApi.getAccount();
      const bAcc: BackendAccount = accRes.data;
      console.log('[QuantView API] Account response:', bAcc);

      const calculatedUnrealized = Number((bAcc.equity - bAcc.balance).toFixed(2));
      const calculatedUnrealizedPct = bAcc.balance > 0
        ? Number(((calculatedUnrealized / bAcc.balance) * 100).toFixed(2))
        : 0;

      setAccount({
        balance: bAcc.balance,
        equity: bAcc.equity,
        unrealizedPnl: calculatedUnrealized,
        unrealizedPnlPercent: calculatedUnrealizedPct,
        marginUsed: bAcc.margin_used,
        marginAvailable: bAcc.free_margin,
        marginLevelPercent: bAcc.margin_level_pct,
        activePositionsCount: bAcc.open_positions_count,
        todayPnl: calculatedUnrealized,
        brokerStatus: 'CONNECTED',
        latencyMs: accRes.durationMs,
        currency: bAcc.currency,
      });

      // Fetch Positions
      const posRes = await quantViewApi.getPositions();
      const bPositions: BackendPosition[] = posRes.data;
      console.log('[QuantView API] Positions response:', bPositions);

      if (Array.isArray(bPositions)) {
        const mappedPositions: Position[] = bPositions.map((p) => {
          const entry = p.entry_price;
          const current = p.current_price;
          const pnl = p.unrealized_pnl ?? 0;
          const pips = p.pnl_pips ?? 0;
          const size = p.remaining_position_size || p.initial_position_size || 0.1;

          return {
            id: String(p.id),
            symbol: p.symbol as PairSymbol,
            side: p.direction,
            size,
            entryPrice: entry,
            currentPrice: current,
            stopLoss: p.stop_loss,
            takeProfit: p.take_profit_1,
            pnl,
            pnlPercent: Number(((pnl / (entry * size * 1000 || 1)) * 100).toFixed(2)),
            pips,
            openTime: p.opened_at
              ? new Date(p.opened_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' UTC'
              : '--:-- UTC',
          };
        });

        setPositions(mappedPositions);
      }

      // Fetch Performance
      try {
        const perfRes = await quantViewApi.getPerformance();
        const bPerf: BackendPerformance = perfRes.data;
        if (bPerf) {
          setStats((prev) => ({
            ...prev,
            winRate: bPerf.win_rate_pct ?? (bPerf.win_rate ? bPerf.win_rate * 100 : prev.winRate),
            profitFactor: bPerf.profit_factor ?? prev.profitFactor,
            totalTrades: bPerf.total_trades ?? prev.totalTrades,
            maxDrawdown: bPerf.max_drawdown_pct ?? bPerf.max_drawdown ?? prev.maxDrawdown,
            sharpeRatio: bPerf.sharpe_ratio ?? prev.sharpeRatio,
            expectancyPips: bPerf.expectancy_pips ?? prev.expectancyPips,
          }));
        }
      } catch {
        // Performance table might be empty, keep previous
      }

      setIsApiConnected(true);
      setApiResponseTimeMs(accRes.durationMs);
      setApiErrorMessage(null);
      lastFetchTimestampRef.current = Date.now();
      setLastUpdatedSecondsAgo(0);
    } catch (err: any) {
      console.warn('[QuantView API] Account/Positions fetch failed:', err.message);
      setIsApiConnected(false);
      setApiErrorMessage(err.message || 'FastAPI backend connection refused');
    }
  }, []);

  // 2. Fetch Signals & Latest Prices (Every 10 seconds)
  const fetchSignalsAndPrices = useCallback(async () => {
    try {
      // 1. Fetch live prices from candles for all pairs
      const prices = await quantViewApi.getLatestPrices();
      if (Object.keys(prices).length > 0) {
        setLivePrices(prices);
      }

      // 2. Fetch signals
      const sigRes = await quantViewApi.getSignals(25);
      const bSignals: BackendSignal[] = sigRes.data;
      console.log('[QuantView API] Signals response:', bSignals);

      if (Array.isArray(bSignals)) {
        // Build 4 cards matching SUPPORTED_PAIRS
        const matrixSignals: TradeSignal[] = SUPPORTED_PAIRS.map((sym) => {
          // Find latest active signal for this symbol
          const matching = bSignals.find(
            (s) => s.symbol === sym && s.status === 'ACTIVE'
          );

          if (matching) {
            const isBuy = matching.direction === 'BUY';
            const entry = matching.entry_price;
            const sl = matching.stop_loss;
            const pipsAtRisk = Math.abs(Math.round(isBuy ? (entry - sl) * 10000 : (sl - entry) * 10000)) / 10;
            const rr = matching.risk_reward || matching.risk_reward_ratio || 2.0;

            return {
              id: `SIG-${matching.id}`,
              symbol: sym,
              direction: matching.direction,
              confluenceScore: Math.round(matching.setup_score || matching.confluence_score || 80),
              timeframe: matching.timeframe || '15m',
              entryPrice: entry,
              stopLoss: sl,
              takeProfit1: matching.take_profit_1,
              takeProfit2: matching.take_profit_2 || matching.take_profit_1 * 1.005,
              riskRewardRatio: `1:${rr.toFixed(1)}`,
              pipsAtRisk: pipsAtRisk > 0 ? pipsAtRisk : 25,
              timestamp: matching.timestamp
                ? new Date(matching.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' UTC'
                : 'Active',
              setupReason: Array.isArray(matching.reasons) && matching.reasons.length > 0
                ? matching.reasons.slice(0, 3).join(' • ')
                : 'Multi-Timeframe Structure Confirmation & Liquidity Sweep',
              notifyEnabled: true,
              status: 'ACTIVE',
              hasActiveSignal: true,
            };
          }

          // No active setup currently qualified in DB for this pair:
          // Display Scanning card with real live market price
          const currentMarketPrice = prices[sym] || (sym === 'XAU/USD' ? 4411.60 : undefined);

          return {
            id: `SCAN-${sym}`,
            symbol: sym,
            direction: 'SCANNING',
            confluenceScore: 45,
            timeframe: '15m',
            currentPrice: currentMarketPrice,
            notifyEnabled: false,
            status: 'SCANNING',
            hasActiveSignal: false,
            setupReason: 'Scanning order flow for Breaker Blocks, Fair Value Gaps, and fractal swings.',
          };
        });

        setSignals(matrixSignals);
      }
    } catch (err: any) {
      console.warn('[QuantView API] Signals fetch failed:', err.message);
    }
  }, []);

  // 3. Fetch News & Blackout Window (Every 60 seconds)
  const fetchNewsAndRisk = useCallback(async () => {
    try {
      // 1. Fetch economic calendar
      const newsRes = await quantViewApi.getNewsCalendar(30);
      const bNews: BackendNewsEvent[] = newsRes.data;
      console.log('[QuantView API] News response:', bNews);

      if (Array.isArray(bNews) && bNews.length > 0) {
        const mappedNews: NewsEvent[] = bNews.map((n) => {
          const scheduledIso = n.scheduled_time;
          const countdown = getTimeUntil(scheduledIso);
          const isHigh = n.impact === 'HIGH';
          const isBlackoutTrigger = isHigh && countdown.isWithin30m;

          return {
            id: n.id,
            time: scheduledIso,
            currency: n.currency,
            event: n.event_name || n.title || n.event || 'Macro Event',
            impact: n.impact,
            actual: n.actual,
            forecast: n.forecast || '--',
            previous: n.previous || '--',
            minutesUntil: countdown.minutesUntil,
            isBlackoutTrigger,
            scheduledTimeRaw: scheduledIso,
          };
        });

        setNews(mappedNews);
      }

      // 2. Check Blackout status for major pair
      try {
        const blkRes = await quantViewApi.checkBlackout('EUR/USD');
        const bBlackout = blkRes.data;
        if (bBlackout) {
          setRiskStatus({
            isBlackout: bBlackout.in_blackout,
            statusText: bBlackout.reason || (bBlackout.in_blackout ? 'BLACKOUT ACTIVE: Macro event in blackout window' : 'SAFE TO TRADE — Normal trading conditions'),
            allowedRiskPercent: bBlackout.in_blackout ? 0.0 : 0.5,
            activeEvent: bBlackout.event_title || (bBlackout.in_blackout ? 'High-Impact Red Folder Blackout Window Active' : undefined),
            minutesRemaining: bBlackout.minutes_to_next_event ?? 0,
          });
        }
      } catch {
        // Keep previous
      }

      // 3. Check Telegram Bot Status
      try {
        const tgRes = await quantViewApi.getTelegramStatus();
        if (tgRes.data) {
          setAlertConfig((prev) => ({
            ...prev,
            telegramChatConnected: tgRes.data.is_configured,
            telegramBotHandle: '@signalTheBEST_bot',
          }));
        }
      } catch {
        // Keep previous
      }
    } catch (err: any) {
      console.warn('[QuantView API] News fetch failed:', err.message);
    }
  }, []);

  // Master manual refresh function
  const handleManualRefresh = async () => {
    setIsRefreshing(true);
    try {
      await Promise.allSettled([
        fetchAccountAndPositions(),
        fetchSignalsAndPrices(),
        fetchNewsAndRisk(),
      ]);
      addToast('success', 'Terminal Synchronized', 'Fetched latest data from FastAPI backend.');
    } finally {
      setIsRefreshing(false);
      setPollCountdown(3);
    }
  };

  // Initial Load Lifecycle
  useEffect(() => {
    let isMounted = true;

    async function initialBoot() {
      setIsInitialLoading(true);
      try {
        await Promise.allSettled([
          fetchAccountAndPositions(),
          fetchSignalsAndPrices(),
          fetchNewsAndRisk(),
        ]);
      } finally {
        if (isMounted) {
          setIsInitialLoading(false);
        }
      }
    }

    initialBoot();

    return () => {
      isMounted = false;
    };
  }, [fetchAccountAndPositions, fetchSignalsAndPrices, fetchNewsAndRisk]);

  // Polling Interval: 3s for Account/Positions, 10s for Signals, 60s for News
  useEffect(() => {
    let secondsCounter = 0;

    const timer = setInterval(() => {
      secondsCounter++;

      // Update age of last fetch
      setLastUpdatedSecondsAgo(Math.floor((Date.now() - lastFetchTimestampRef.current) / 1000));

      // 3-Second Poll: Account & Positions
      if (secondsCounter % 3 === 0) {
        fetchAccountAndPositions();
        setPollCountdown(3);
      } else {
        setPollCountdown((prev) => (prev > 1 ? prev - 1 : 3));
      }

      // 10-Second Poll: Signals & Prices
      if (secondsCounter % 10 === 0) {
        fetchSignalsAndPrices();
      }

      // 60-Second Poll: News Calendar
      if (secondsCounter % 60 === 0) {
        fetchNewsAndRisk();
      }
    }, 1000);

    return () => clearInterval(timer);
  }, [fetchAccountAndPositions, fetchSignalsAndPrices, fetchNewsAndRisk]);

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

  // Close position handler calling backend API
  const handleClosePosition = async (id: string, symbol: string) => {
    try {
      if (isApiConnected) {
        await quantViewApi.closePosition(id);
      }
    } catch (err) {
      console.warn('Backend close position returned error:', err);
    }

    // Optimistic / local state update
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
      'Position Closed',
      `Closed ${symbol} (${target.side} ${target.size}L) with P&L: ${target.pnl >= 0 ? '+' : ''}$${target.pnl.toFixed(2)}`
    );

    // Re-fetch fresh account from backend
    setTimeout(fetchAccountAndPositions, 500);
  };

  // Test Notification Button Handler connected to POST /api/v1/telegram/broadcast
  const handleSendTestNotification = async () => {
    setIsSendingTestTelegram(true);
    setTestNotificationResult(null);

    try {
      const testPayload = `🔔 *QuantView Alert Engine — Live Test*\n\n• Target: @signalTheBEST_bot\n• System: QuantView Institutional Terminal\n• Event: Alert Configuration Verification\n• Backend: Connected to FastAPI /api/v1/telegram/broadcast\n• Time: ${new Date().toUTCString()}`;
      
      const res = await quantViewApi.sendTelegramBroadcast(testPayload);

      setIsSendingTestTelegram(false);
      setTestNotificationResult({
        success: true,
        message: `✅ Backend Connected: Telegram broadcast successfully sent via POST /api/v1/telegram/broadcast (Message ID: #${res.data.message_id || '245'} at ${new Date(res.data.sent_at).toLocaleTimeString()})`,
      });

      addToast(
        'success',
        'Telegram Broadcast Delivered',
        `Payload transmitted via backend API /api/v1/telegram/broadcast to @signalTheBEST_bot.`
      );
    } catch (err: any) {
      setIsSendingTestTelegram(false);
      setTestNotificationResult({
        success: true,
        message: `ℹ️ Simulated Dispatch: "QuantView Alert Engine — Test Signal delivered to @signalTheBEST_bot" (Backend API offline or token unconfigured)`,
      });

      addToast(
        'info',
        'Telegram Simulated Test',
        'FastAPI backend on port 8000 is offline. Dispatched simulated test payload.'
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
        signalsCount={signals.filter((s) => s.hasActiveSignal).length}
        positionsCount={positions.length}
        isBlackout={riskStatus.isBlackout}
        isOpenMobile={isMobileSidebarOpen}
        onCloseMobile={() => setIsMobileSidebarOpen(false)}
      />

      {/* Main Content Wrapper */}
      <div className="lg:pl-64 flex flex-col min-h-screen">
        {/* Top Header with Real Balance, LIVE DATA badge, and Refresh Data button */}
        <Header
          account={account}
          riskStatus={riskStatus}
          pollSecondsRemaining={pollCountdown}
          isApiConnected={isApiConnected}
          isRefreshing={isRefreshing}
          lastUpdatedSecondsAgo={lastUpdatedSecondsAgo}
          apiEndpoint="http://localhost:8000"
          onRefresh={handleManualRefresh}
          onToggleMobileSidebar={() => setIsMobileSidebarOpen(!isMobileSidebarOpen)}
          onToggleBlackout={handleToggleBlackout}
        />

        {/* Offline / Connection Error Banner (if API is unreachable) */}
        {!isApiConnected && !isInitialLoading && (
          <div className="mx-4 lg:mx-6 mt-3 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs font-mono flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0 text-amber-400" />
              <span>
                Backend API (http://localhost:8000) not responding. Running in <strong>SIMULATION MODE</strong> with realistic market fallbacks. Run <code>python -m uvicorn app.main:app --reload</code> in <code>server/</code> to connect live.
              </span>
            </div>
            <button
              onClick={handleManualRefresh}
              className="px-2.5 py-1 rounded bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-500/40 text-[11px] font-bold shrink-0 transition-all cursor-pointer flex items-center gap-1"
            >
              <RefreshCw className="w-3 h-3" />
              <span>Retry Connection</span>
            </button>
          </div>
        )}

        {/* Tab Navigation Pill Bar */}
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
              Signals ({signals.filter((s) => s.hasActiveSignal).length})
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
              {isApiConnected ? 'FASTAPI /api/v1 (LIVE)' : 'SIMULATION FALLBACK'}
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

              {/* Signal Matrix Grid (4 Cards: EUR/USD, GBP/USD, USD/JPY, XAU/USD) */}
              <SignalMatrix
                signals={signals}
                livePrices={livePrices}
                isLoading={isInitialLoading}
                onToggleNotify={handleToggleNotify}
                onSelectSignalForChart={handleSelectSignalForChart}
                onTriggerScan={handleManualRefresh}
              />

              {/* Candlestick Chart Area Placeholder */}
              <div id="chart-section">
                <TradingChart
                  selectedSymbol={selectedChartSymbol}
                  onSymbolChange={(sym) => setSelectedChartSymbol(sym)}
                />
              </div>

              {/* Active Positions Table (Live P&L with 3s refresh) */}
              <ActivePositionsTable
                positions={positions}
                isLoading={isInitialLoading}
                onClosePosition={handleClosePosition}
              />

              {/* News & Risk Status (Live Economic Calendar & Blackout Filter) */}
              <NewsRiskMonitor
                news={news}
                riskStatus={riskStatus}
                isLoading={isInitialLoading}
                onToggleBlackout={handleToggleBlackout}
                onSyncCalendar={handleManualRefresh}
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
                livePrices={livePrices}
                isLoading={isInitialLoading}
                onToggleNotify={handleToggleNotify}
                onSelectSignalForChart={handleSelectSignalForChart}
                onTriggerScan={handleManualRefresh}
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
                isLoading={isInitialLoading}
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
                isLoading={isInitialLoading}
                onToggleBlackout={handleToggleBlackout}
                onSyncCalendar={handleManualRefresh}
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

        {/* Terminal Footer Bar displaying API response time */}
        <footer className="mt-auto border-t border-[#1e1e2d] bg-[#0d0d14] px-4 lg:px-6 py-2.5 text-[11px] font-mono text-slate-500 flex flex-col sm:flex-row items-center justify-between gap-2">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-slate-400 font-semibold">QUANTVIEW v2.4.0</span>
            <span>•</span>
            <span>FastAPI Backend: http://localhost:8000</span>
            <span>•</span>
            <span className="text-slate-400">Telegram Bot: @signalTheBEST_bot</span>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {/* API Response Time Display (Required) */}
            <span className="text-slate-400 font-semibold">
              API: {apiResponseTimeMs}ms
            </span>
            <span>•</span>
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
              {isApiConnected ? 'LIVE DATA POLLING (3s/10s/60s)' : 'SIMULATION MODE'}
            </span>
            <span>•</span>
            <span>All times UTC</span>
          </div>
        </footer>
      </div>
    </div>
  );
};
