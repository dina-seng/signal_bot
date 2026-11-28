import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Sidebar } from '../components/Sidebar';
import { MobileMenu } from '../components/MobileMenu';
import { Header } from '../components/Header';
import { PerformanceDashboard } from '../components/PerformanceDashboard';
import { SignalMatrix } from '../components/SignalMatrix';
import { ActivePositionsTable } from '../components/ActivePositionsTable';
import { NotificationSettings } from '../components/NotificationSettings';
import { NewsRiskMonitor } from '../components/NewsRiskMonitor';
import { TradingChart } from '../components/TradingChart';
import { SystemTelemetry } from '../components/SystemTelemetry';
import { GlassCard } from '../components/ui/GlassCard';
import { ToastContainer, ToastMessage } from '../components/Toast';
import {
  NavigationTab,
  PairSymbol,
  TradeSignal,
  Position,
  ClosedTrade,
  AlertConfiguration,
  NewsEvent,
  RiskStatus,
  AccountType,
} from '../types';
import {
  initialAccountSummary,
  initialPerformanceStats,
  initialSignals,
  initialPositions,
  initialAlertConfig,
  initialNewsEvents,
  initialRiskStatus,
} from '../data/mockData';
import {
  quantViewApi,
  BackendAccount,
  BackendPosition,
  BackendSignal,
  BackendNewsEvent,
  BackendPerformance,
  BackendPaperTrade,
  BackendTelegramStatus,
  BackendScannerStatus,
  BackendQuote,
  AppConfig,
  DashboardSnapshot,
  ApiError,
} from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { formatPrice, getTimeUntil } from '../utils/formatters';
import { AlertTriangle, RefreshCw } from 'lucide-react';

const SUPPORTED_PAIRS: PairSymbol[] = ['XAU/USD', 'BTC/USD'];

/** Workspace routing: BTC/USD trades on CENT, everything else on MAIN. */
const accountForSymbol = (symbol: PairSymbol): AccountType =>
  symbol === 'BTC/USD' ? 'CENT' : 'MAIN';

/** Chart/API timeframe is instrument-specific: BTC momentum runs on 1H, gold SMC on 15m. */
const chartTimeframeForSymbol = (symbol: PairSymbol): string =>
  symbol === 'BTC/USD' ? '1h' : '15m';

/** Coerce backend values (JSON numbers *or* numeric strings) to finite numbers. */
const toFiniteNumber = (value: unknown): number | undefined => {
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
};

/** Map backend signal metadata into the momentum fields used by the UI cards. */
const momentumFields = (sig: BackendSignal, symbol: PairSymbol) => {
  const meta: Record<string, any> = sig.metadata || {};
  // Accept both snake_case (backend) and camelCase (older payloads / direct
  // fields) so a valid 0 is never dropped and numeric strings still render.
  const pick = (...keys: string[]): number | undefined => {
    for (const key of keys) {
      const value = toFiniteNumber(meta[key] ?? (sig as any)[key]);
      if (value !== undefined) return value;
    }
    return undefined;
  };
  const ema50 = pick('ema_50', 'ema50');
  const ema200 = pick('ema_200', 'ema200');
  const rsi14 = pick('rsi_14', 'rsi14');
  const adx14 = pick('adx_14', 'adx14');
  return {
    targetAccount: (meta.target_account || accountForSymbol(symbol)) as AccountType,
    strategyName: sig.strategy_name || meta.strategy_name || undefined,
    emaTrend: meta.ema_trend || (ema50 !== undefined && ema200 !== undefined
      ? (ema50 > ema200 ? 'Bullish' : 'Bearish')
      : undefined),
    ema50,
    ema200,
    rsi14,
    adx14,
    heuristicProvenance: meta.heuristic_provenance,
    // Backend-computed, bounded (60-95%) confidence. Never fall back to the
    // old "confidence == score" heuristic, which produced a fake 100%.
    aiConfidence: toFiniteNumber(meta.ai_confidence),
  };
};

export const Dashboard: React.FC = () => {
  const { isAdmin, user: authUser, signOut } = useAuth();
  const [currentTab, setCurrentTab] = useState<NavigationTab>('dashboard');
  const [workspaceSymbol, setWorkspaceSymbol] = useState<PairSymbol>('XAU/USD');
  const accountType: AccountType = accountForSymbol(workspaceSymbol);
  const [account, setAccount] = useState(initialAccountSummary);
  const [stats, setStats] = useState(initialPerformanceStats);
  const [signals, setSignals] = useState<TradeSignal[]>(initialSignals);
  const [positions, setPositions] = useState<Position[]>(initialPositions);
  const [closedTrades, setClosedTrades] = useState<ClosedTrade[]>([]);
  const [alertConfig, setAlertConfig] = useState<AlertConfiguration>(initialAlertConfig);
  const [news, setNews] = useState<NewsEvent[]>(initialNewsEvents);
  const [riskStatus, setRiskStatus] = useState<RiskStatus>(initialRiskStatus);
  const [selectedChartSymbol, setSelectedChartSymbol] = useState<PairSymbol>('XAU/USD');
  const [livePrices, setLivePrices] = useState<Record<string, number>>({});
  const [latestQuote, setLatestQuote] = useState<BackendQuote | null>(null);
  const [appConfig, setAppConfig] = useState<AppConfig | null>(null);
  const [showQuoteDebug, setShowQuoteDebug] = useState<boolean>(false);

  // Telegram & Scanner live status
  const [telegramStatus, setTelegramStatus] = useState<BackendTelegramStatus | null>(null);
  const [scannerStatus, setScannerStatus] = useState<BackendScannerStatus | null>(null);

  // Loading, timing & error states
  const [isInitialLoading, setIsInitialLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [isScanningMarkets, setIsScanningMarkets] = useState<boolean>(false);
  const [isSyncingCalendar, setIsSyncingCalendar] = useState<boolean>(false);
  const [isTriggeringScanner, setIsTriggeringScanner] = useState<boolean>(false);
  const [isApiConnected, setIsApiConnected] = useState<boolean>(false);
  // True only after a real paper-account snapshot has been applied. Keeps the
  // header from presenting the mock zeros as if they were live balances.
  const [hasAccountData, setHasAccountData] = useState<boolean>(false);
  const [apiResponseTimeMs, setApiResponseTimeMs] = useState<number>(24);
  const [lastUpdatedSecondsAgo, setLastUpdatedSecondsAgo] = useState<number>(0);
  const [apiErrorMessage, setApiErrorMessage] = useState<string | null>(null);
  const [pollCountdown, setPollCountdown] = useState<number>(30);

  // In-flight request guards to avoid stacking overlapping requests
  const isFetchingAccountRef = useRef<boolean>(false);
  const isFetchingSignalsRef = useRef<boolean>(false);
  const isFetchingNewsRef = useRef<boolean>(false);
  const isFetchingPricesRef = useRef<boolean>(false);
  const isFetchingSnapshotRef = useRef<boolean>(false);
  // True when the last quote poll returned a live (non-STALE) quote. Candle-close
  // refreshes must never overwrite a newer quote while this is true.
  const quoteFreshRef = useRef<boolean>(false);

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
    const id = `${Date.now()}-${Date.now().toString(36)}`;
    setToasts((prev) => [...prev, { id, type, title, message }]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // 1. Fetch Account & Positions (Every 30 seconds)
  const fetchAccountAndPositions = useCallback(async () => {
    if (isFetchingAccountRef.current) return;
    isFetchingAccountRef.current = true;
    try {
      // Atomic snapshot — account + positions from ONE shared live price tick,
      // so the header and the Position Ledger can never disagree by a tick.
      const sumRes = await quantViewApi.getSummary(accountType);
      const bAcc: BackendAccount = sumRes.data.account;
      const bPositions: BackendPosition[] = sumRes.data.positions;
      console.log('[QuantView API] Summary snapshot:', sumRes.data);

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
        latencyMs: sumRes.durationMs,
        currency: bAcc.currency,
      });
      setHasAccountData(true);

      const mapBackendPositions = (rows: BackendPosition[]): Position[] =>
        rows.map((p) => {
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
            account: p.account_name || accountForSymbol(p.symbol as PairSymbol),
          };
        });

      let positionsToRender: Position[] = Array.isArray(bPositions)
        ? mapBackendPositions(bPositions)
        : [];

      // Fallback for "ghost trades": if the atomic snapshot shows none, ask the
      // authoritative open-positions endpoint directly so a freshly executed
      // (or partially closed) paper trade is never hidden from the Positions tab.
      if (positionsToRender.length === 0) {
        try {
          const openRes = await quantViewApi.getPositions(accountType);
          if (Array.isArray(openRes.data) && openRes.data.length > 0) {
            positionsToRender = mapBackendPositions(openRes.data);
          }
        } catch (posErr: any) {
          console.warn('[QuantView API] Open positions fallback failed:', posErr?.message);
        }
      }

      setPositions(positionsToRender);

      // Fetch Closed Trade History
      try {
        const tradesRes = await quantViewApi.getTradeHistory(50, accountType);
        const bTrades: BackendPaperTrade[] = tradesRes.data;
        if (Array.isArray(bTrades)) {
          const mappedClosed: ClosedTrade[] = bTrades.map((t) => ({
            id: String(t.id),
            symbol: t.symbol,
            side: t.direction,
            size: t.remaining_position_size || t.initial_position_size || 0.1,
            entryPrice: t.entry_price,
            exitPrice: t.exit_price || t.current_price,
            stopLoss: t.stop_loss,
            takeProfit: t.take_profit_1,
            realizedPnl: t.realized_pnl,
            pnlPips: t.pnl_pips,
            returnR: t.return_r,
            exitReason: t.exit_reason || 'CLOSED',
            openedAt: t.opened_at,
            closedAt: t.closed_at || t.opened_at,
            account: t.account_name || accountForSymbol(t.symbol as PairSymbol),
          }));
          setClosedTrades(mappedClosed);
        }
      } catch {
        // Keep previous closed trades
      }

      // Fetch Performance
      try {
        const perfRes = await quantViewApi.getPerformance();
        const bPerf: BackendPerformance = perfRes.data;
        if (bPerf) {
          setStats((prev) => ({
            ...prev,
            winRate: bPerf.win_rate_pct ?? (bPerf.win_rate ? Number((bPerf.win_rate * 100).toFixed(1)) : prev.winRate),
            profitFactor: bPerf.profit_factor ?? prev.profitFactor,
            totalTrades: bPerf.total_trades ?? prev.totalTrades,
            maxDrawdown: bPerf.max_drawdown_pct ?? bPerf.max_drawdown ?? null,
            sharpeRatio: bPerf.sharpe_ratio ?? null,
            expectancyPips: bPerf.expectancy_pips ?? null,
            initialBalance: bPerf.initial_balance ?? null,
          }));
        }
      } catch {
        // Performance table might be empty, keep previous
      }

      setIsApiConnected(true);
      setApiResponseTimeMs(sumRes.durationMs);
      setApiErrorMessage(null);
      lastFetchTimestampRef.current = Date.now();
      setLastUpdatedSecondsAgo(0);
    } catch (err: any) {
      console.warn('[QuantView API] Account/Positions fetch failed:', err.message);
      setIsApiConnected(false);
      setApiErrorMessage(err.message || 'FastAPI backend connection refused');
    } finally {
      isFetchingAccountRef.current = false;
    }
  }, [accountType]);

  // Real-Time Price Quote Poll (Every 15s; provider is ~1-min granular and the
  // backend caches for 60s, so this costs zero freshness and ~6x fewer credits).
  const fetchLiveQuotes = useCallback(async () => {
    if (isFetchingPricesRef.current) return;
    isFetchingPricesRef.current = true;
    try {
      const quoteRes = await quantViewApi.getQuote(workspaceSymbol);
      if (quoteRes.data && (!quoteRes.data.symbol || quoteRes.data.symbol === workspaceSymbol)) {
        const quote = {
          ...quoteRes.data,
          fetched_at: quoteRes.data.fetched_at || new Date().toISOString(),
        };
        setLatestQuote(quote);
        const quoteIsFresh = quote.is_stale !== true;
        quoteFreshRef.current = quoteIsFresh;
        if (typeof quote.price === 'number' && quote.price > 0) {
          setLivePrices((prev) => {
            // Never replace a fresh quote mark with an older cached/candle value.
            if (!quoteIsFresh && prev[workspaceSymbol] !== undefined) return prev;
            return { ...prev, [workspaceSymbol]: quote.price };
          });
        }
      }
    } catch {
      // Fallback to latest prices if quote provider is offline
      try {
        const prices = await quantViewApi.getLatestPrices();
        if (prices && Object.keys(prices).length > 0) {
          setLivePrices(prices);
          if (prices[workspaceSymbol]) {
            setLatestQuote((prev) => ({
              ...(prev || {
                symbol: workspaceSymbol,
                source: 'candle',
                timestamp: new Date().toISOString(),
              }),
              symbol: workspaceSymbol,
              price: prices[workspaceSymbol],
              fetched_at: new Date().toISOString(),
            }));
          }
        }
      } catch {
        // Ignore transient error
      }
    } finally {
      isFetchingPricesRef.current = false;
    }
  }, [workspaceSymbol]);

  // 2. Fetch Signals & Latest Prices (Every 60 seconds)
  const fetchSignalsAndPrices = useCallback(async () => {
    if (isFetchingSignalsRef.current) return;
    isFetchingSignalsRef.current = true;
    try {
      // 1. Fetch live prices from candles for all pairs. A candle close must never
      //    clobber a newer live quote; when the quote is STALE we leave the badge
      //    to say so rather than silently showing a stale candle as real-time.
      const prices = await quantViewApi.getLatestPrices();
      if (prices && Object.keys(prices).length > 0) {
        setLivePrices((prev) => {
          if (quoteFreshRef.current && prev['XAU/USD'] !== undefined) {
            return { ...prices, 'XAU/USD': prev['XAU/USD'] };
          }
          return { ...prev, ...prices };
        });
      }

      // 2. Fetch signals
      const sigRes = await quantViewApi.getSignals(25, true, workspaceSymbol, accountType);
      const bSignals: BackendSignal[] = sigRes.data;
      console.log('[QuantView API] Signals response:', bSignals);

      if (Array.isArray(bSignals)) {
        // Build cards matching SUPPORTED_PAIRS
        const matrixSignals: TradeSignal[] = [workspaceSymbol].map((sym) => {
          // Find matching unified signal for this symbol
          const matching = bSignals.find((s) => s.symbol === sym);
          const hasActiveActionable = matching && matching.status === 'ACTIVE' && (matching.direction === 'BUY' || matching.direction === 'SELL');

          if (hasActiveActionable && matching) {
            const isBuy = matching.direction === 'BUY';
            const entry = matching.entry_price || prices[sym] || 0;
            const sl = matching.stop_loss || 0;
            const pipsAtRisk = (entry > 0 && sl > 0)
              ? Math.abs(Math.round(isBuy ? (entry - sl) * 10000 : (sl - entry) * 10000)) / 10
              : undefined;
            const rr = matching.risk_reward || matching.risk_reward_ratio;
            const rawScore = matching.setup_score ?? matching.confluence_score;
            const score = typeof rawScore === 'number' ? Math.round(rawScore) : 0;

            return {
              id: `SIG-${matching.id || sym}`,
              ...momentumFields(matching, sym),
              symbol: sym,
              direction: matching.direction,
              confluenceScore: score,
              timeframe: matching.timeframe || '15m',
              entryPrice: entry,
              stopLoss: sl,
              takeProfit1: matching.take_profit_1 || 0,
              takeProfit2: matching.take_profit_2 || 0,
              riskRewardRatio: rr ? `1:${rr.toFixed(1)}` : '--',
              pipsAtRisk,
              timestamp: matching.timestamp
                ? new Date(matching.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' UTC'
                : 'Active',
              setupReason: Array.isArray(matching.reasons) && matching.reasons.length > 0
                ? matching.reasons.slice(0, 3).join(' • ')
                : 'Multi-Timeframe Structure Confirmation & Liquidity Sweep',
              trendAlignment: matching.trend_alignment || undefined,
              htfTrend: matching.htf_trend || undefined,
              notifyEnabled: true,
              status: 'ACTIVE',
              hasActiveSignal: true,
            };
          }

          // No active actionable setup currently for this pair:
          // Display Unified Scanning card with real 15m context & score
          const currentMarketPrice = prices[sym] || undefined;
          const waitTf = matching?.timeframe || '15m';
          const rawScore = matching ? (matching.setup_score ?? matching.confluence_score ?? 0) : 0;
          const waitScore = Math.round(rawScore);
          const waitReason = (matching?.reasons && matching.reasons.length > 0)
            ? matching.reasons[0]
            : (matching?.htf_trend ? `1H Trend: ${matching.htf_trend} • Awaiting high-confluence setup` : 'Awaiting Data: Scanning order flow for Breaker Blocks and Fair Value Gaps.');

          return {
            id: `SCAN-${sym}`,
            ...(matching ? momentumFields(matching, sym) : {}),
            symbol: sym,
            direction: 'SCANNING',
            confluenceScore: waitScore,
            timeframe: waitTf,
            currentPrice: currentMarketPrice,
            trendAlignment: matching?.trend_alignment || undefined,
            htfTrend: matching?.htf_trend || undefined,
            notifyEnabled: false,
            status: 'SCANNING',
            hasActiveSignal: false,
            setupReason: waitReason,
          };
        });

        setSignals(matrixSignals);
      }
    } catch (err: any) {
      console.warn('[QuantView API] Signals fetch failed:', err.message);
    } finally {
      isFetchingSignalsRef.current = false;
    }
  }, [workspaceSymbol, accountType]);

  // 3. Fetch News & Blackout Window (Every 60 seconds)
  const fetchNewsAndRisk = useCallback(async () => {
    if (isFetchingNewsRef.current) return;
    isFetchingNewsRef.current = true;
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
        const blkRes = await quantViewApi.checkBlackout('XAU/USD');
        const bBlackout = blkRes.data;
        if (bBlackout) {
          setRiskStatus({
            isBlackout: bBlackout.in_blackout,
            statusText: bBlackout.reason || (bBlackout.in_blackout ? 'BLACKOUT ACTIVE: Macro event in blackout window' : 'SAFE TO TRADE — Normal trading conditions'),
            activeEvent: bBlackout.event_title || (bBlackout.in_blackout ? 'High-Impact Red Folder Blackout Window Active' : undefined),
            minutesRemaining: bBlackout.minutes_to_next_event ?? 0,
          });
        }
      } catch {
        // Keep previous
      }

      // 3. Check Telegram Bot Status & Background Scanner Status
      try {
        const [tgRes, scanRes] = await Promise.allSettled([
          quantViewApi.getTelegramStatus(),
          quantViewApi.getScannerStatus(),
        ]);

        if (tgRes.status === 'fulfilled' && tgRes.value.data) {
          setTelegramStatus(tgRes.value.data);
          setAlertConfig((prev) => ({
            ...prev,
            telegramChatConnected: tgRes.value.data.is_configured,
            telegramBotHandle: '@signalTheBEST_bot',
          }));
        }

        if (scanRes.status === 'fulfilled' && scanRes.value.data) {
          setScannerStatus(scanRes.value.data);
        }
      } catch {
        // Keep previous
      }
    } catch (err: any) {
      console.warn('[QuantView API] News fetch failed:', err.message);
    } finally {
      isFetchingNewsRef.current = false;
    }
  }, []);

  // Single-endpoint poll: the backend assembles every section in parallel and
  // returns one response, so the UI no longer pays for ~10 serialised GETs.
  const fetchSnapshot = useCallback(async (force: boolean = false) => {
    // A manual Sync must always re-run even when a background poll is in
    // flight; otherwise the button appears to work but never refreshes.
    if (isFetchingSnapshotRef.current && !force) return;
    isFetchingSnapshotRef.current = true;
    try {
      const res = await quantViewApi.getDashboardSnapshot(
        workspaceSymbol,
        chartTimeframeForSymbol(workspaceSymbol),
        accountType
      );
      const snap: DashboardSnapshot = res.data;

      if (snap.config) setAppConfig(snap.config);

      // Quote — left panel and chart share the SAME fast quote field.
      const fastQuote = snap.live_quote || snap.quote;
      if (fastQuote) {
        const quote = {
          ...fastQuote,
          fetched_at: fastQuote.fetched_at || new Date().toISOString(),
        };
        setLatestQuote(quote);
        const quoteIsFresh = quote.is_stale !== true;
        quoteFreshRef.current = quoteIsFresh;
      }

      const prices: Record<string, number> = {};
      if (typeof fastQuote?.price === 'number' && fastQuote.price > 0 && !fastQuote.is_stale) {
        prices[workspaceSymbol] = fastQuote.price;
      } else if (Array.isArray(snap.candles) && snap.candles.length > 0) {
        const last = snap.candles[snap.candles.length - 1];
        if (typeof last?.close === 'number') prices[workspaceSymbol] = last.close;
      }
      setLivePrices((prev) => ({ ...prev, ...prices }));

      // Atomic paper snapshot: account + positions share one live price tick.
      if (snap.paper_summary) {
        const bAcc: BackendAccount = snap.paper_summary.account;
        const unrealized = Number((bAcc.equity - bAcc.balance).toFixed(2));
        setAccount({
          balance: bAcc.balance,
          equity: bAcc.equity,
          unrealizedPnl: unrealized,
          unrealizedPnlPercent: bAcc.balance > 0
            ? Number(((unrealized / bAcc.balance) * 100).toFixed(2))
            : 0,
          marginUsed: bAcc.margin_used,
          marginAvailable: bAcc.free_margin,
          marginLevelPercent: bAcc.margin_level_pct,
          activePositionsCount: bAcc.open_positions_count,
          todayPnl: unrealized,
          brokerStatus: 'CONNECTED',
          latencyMs: res.durationMs,
          currency: bAcc.currency,
        });
        setHasAccountData(true);
      }
      if (Array.isArray(snap.positions)) {
        setPositions(snap.positions.map((p: BackendPosition) => {
          const entry = p.entry_price;
          const pnl = p.unrealized_pnl ?? 0;
          const size = p.remaining_position_size || p.initial_position_size || 0.1;
          return {
            id: String(p.id),
            symbol: p.symbol as PairSymbol,
            side: p.direction,
            size,
            entryPrice: entry,
            currentPrice: p.current_price,
            stopLoss: p.stop_loss,
            takeProfit: p.take_profit_1,
            pnl,
            pnlPercent: Number(((pnl / (entry * size * 1000 || 1)) * 100).toFixed(2)),
            pips: p.pnl_pips ?? 0,
            openTime: p.opened_at
              ? new Date(p.opened_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' UTC'
              : '--:-- UTC',
            account: p.account_name || accountForSymbol(p.symbol as PairSymbol),
          };
        }));
      }

      if (Array.isArray(snap.trades)) {
        setClosedTrades(snap.trades.map((t: BackendPaperTrade) => ({
          id: String(t.id),
          symbol: t.symbol,
          side: t.direction,
          size: t.remaining_position_size || t.initial_position_size || 0.1,
          entryPrice: t.entry_price,
          exitPrice: t.exit_price || t.current_price,
          stopLoss: t.stop_loss,
          takeProfit: t.take_profit_1,
          realizedPnl: t.realized_pnl,
          pnlPips: t.pnl_pips,
          returnR: t.return_r,
          exitReason: t.exit_reason || 'CLOSED',
          openedAt: t.opened_at,
          closedAt: t.closed_at || t.opened_at,
          account: t.account_name || accountForSymbol(t.symbol as PairSymbol),
        })));
      }

      if (snap.performance) {
        const bPerf: BackendPerformance = snap.performance;
        setStats((prev) => ({
          ...prev,
          winRate: bPerf.win_rate_pct ?? (bPerf.win_rate ? Number((bPerf.win_rate * 100).toFixed(1)) : prev.winRate),
          profitFactor: bPerf.profit_factor ?? prev.profitFactor,
          totalTrades: bPerf.total_trades ?? prev.totalTrades,
          maxDrawdown: bPerf.max_drawdown_pct ?? bPerf.max_drawdown ?? null,
          sharpeRatio: bPerf.sharpe_ratio ?? null,
          expectancyPips: bPerf.expectancy_pips ?? null,
          initialBalance: bPerf.initial_balance ?? null,
        }));
      }

      if (Array.isArray(snap.signals)) {
        const bSignals: BackendSignal[] = snap.signals;
        setSignals([workspaceSymbol].map((sym) => {
          const matching = bSignals.find((s) => s.symbol === sym);
          const actionable = matching && matching.status === 'ACTIVE' &&
            (matching.direction === 'BUY' || matching.direction === 'SELL');
          if (actionable && matching) {
            const isBuy = matching.direction === 'BUY';
            const entry = matching.entry_price || prices[sym] || 0;
            const sl = matching.stop_loss || 0;
            const pipsAtRisk = entry > 0 && sl > 0
              ? Math.abs(Math.round(isBuy ? (entry - sl) * 10000 : (sl - entry) * 10000)) / 10
              : undefined;
            const rr = matching.risk_reward || matching.risk_reward_ratio;
            const rawScore = matching.setup_score ?? matching.confluence_score;
            return {
              id: `SIG-${matching.id || sym}`,
              ...momentumFields(matching, sym),
              symbol: sym,
              direction: matching.direction,
              confluenceScore: typeof rawScore === 'number' ? Math.round(rawScore) : 0,
              timeframe: matching.timeframe || '15m',
              entryPrice: entry,
              stopLoss: sl,
              takeProfit1: matching.take_profit_1 || 0,
              takeProfit2: matching.take_profit_2 || 0,
              riskRewardRatio: rr ? `1:${rr.toFixed(1)}` : '--',
              pipsAtRisk,
              timestamp: matching.timestamp
                ? new Date(matching.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' UTC'
                : 'Active',
              setupReason: Array.isArray(matching.reasons) && matching.reasons.length > 0
                ? matching.reasons.slice(0, 3).join(' • ')
                : 'Multi-Timeframe Structure Confirmation & Liquidity Sweep',
              trendAlignment: matching.trend_alignment || undefined,
              htfTrend: matching.htf_trend || undefined,
              notifyEnabled: true,
              status: 'ACTIVE' as const,
              hasActiveSignal: true,
            };
          }
          const rawScore = matching ? (matching.setup_score ?? matching.confluence_score ?? 0) : 0;
          return {
            id: `SCAN-${sym}`,
            ...(matching ? momentumFields(matching, sym) : {}),
            symbol: sym,
            direction: 'SCANNING' as const,
            confluenceScore: Math.round(rawScore),
            timeframe: matching?.timeframe || '15m',
            currentPrice: prices[sym] || undefined,
            trendAlignment: matching?.trend_alignment || undefined,
            htfTrend: matching?.htf_trend || undefined,
            notifyEnabled: false,
            status: 'SCANNING' as const,
            hasActiveSignal: false,
            setupReason: matching?.reasons?.[0]
              || (matching?.htf_trend ? `1H Trend: ${matching.htf_trend} • Awaiting high-confluence setup` : 'Awaiting Data: Scanning order flow for Breaker Blocks and Fair Value Gaps.'),
          };
        }));
      }

      if (Array.isArray(snap.news) && snap.news.length > 0) {
        setNews(snap.news.map((n: BackendNewsEvent) => {
          const scheduledIso = n.scheduled_time;
          const countdown = getTimeUntil(scheduledIso);
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
            isBlackoutTrigger: n.impact === 'HIGH' && countdown.isWithin30m,
            scheduledTimeRaw: scheduledIso,
          };
        }));
      }

      if (snap.blackout) {
        const b = snap.blackout;
        setRiskStatus({
          isBlackout: b.in_blackout,
          statusText: b.reason || (b.in_blackout ? 'BLACKOUT ACTIVE: Macro event in blackout window' : 'SAFE TO TRADE — Normal trading conditions'),
          activeEvent: b.event_title || (b.in_blackout ? 'High-Impact Red Folder Blackout Window Active' : undefined),
          minutesRemaining: b.minutes_to_next_event ?? 0,
        });
      }

      if (snap.telegram_status) {
        setTelegramStatus(snap.telegram_status);
        setAlertConfig((prev) => ({
          ...prev,
          telegramChatConnected: snap.telegram_status!.is_configured,
          telegramBotHandle: '@signalTheBEST_bot',
        }));
      }
      if (snap.scanner_status) setScannerStatus(snap.scanner_status);

      setApiResponseTimeMs(res.durationMs);
      setIsApiConnected(true);
      setApiErrorMessage(null);
      lastFetchTimestampRef.current = Date.now();
      setLastUpdatedSecondsAgo(0);
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 401) {
        // Session expired: clear it so the route guard redirects to /login.
        await signOut();
        return;
      }
      console.warn('[QuantView API] Snapshot fetch failed, falling back:', err.message);
      setIsApiConnected(false);
      setApiErrorMessage(err.message || 'Dashboard snapshot unavailable');
      await Promise.allSettled([
        fetchLiveQuotes(),
        fetchAccountAndPositions(),
        fetchSignalsAndPrices(),
        fetchNewsAndRisk(),
      ]);
    } finally {
      isFetchingSnapshotRef.current = false;
    }
  }, [fetchLiveQuotes, fetchAccountAndPositions, fetchSignalsAndPrices, fetchNewsAndRisk, signOut, workspaceSymbol, accountType]);

  // Master manual refresh function
  const handleManualRefresh = async () => {
    setIsRefreshing(true);
    try {
      await fetchSnapshot(true);
      addToast('success', 'Terminal Synchronized', 'Fetched latest data from FastAPI backend.');
    } finally {
      setIsRefreshing(false);
      setPollCountdown(pollSeconds);
    }
  };

  // Initial Load Lifecycle
  useEffect(() => {
    let isMounted = true;

    async function initialBoot() {
      setIsInitialLoading(true);
      try {
        // Config arrives inside the same snapshot response.
        await fetchSnapshot();
      } finally {
        if (isMounted) {
          setIsInitialLoading(false);
          setPollCountdown(appConfig?.dashboard_poll_seconds ?? 15);
        }
      }
    }

    initialBoot();

    return () => {
      isMounted = false;
    };
  }, [fetchSnapshot]);

  // One poll loop for the whole dashboard, cadence driven by backend config.
  // A single GET replaces the former 15s/30s/60s GET waterfall.
  const pollSeconds = appConfig?.dashboard_poll_seconds ?? 15;

  useEffect(() => {
    // Register presence immediately so the backend keeps the active quote TTL.
    quantViewApi.sendPresenceHeartbeat();

    const poll = () => {
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
        return;
      }
      quantViewApi.sendPresenceHeartbeat();
      fetchSnapshot();
      setPollCountdown(pollSeconds);
    };

    const timer = setInterval(poll, pollSeconds * 1000);
    const countdownTimer = setInterval(() => {
      setLastUpdatedSecondsAgo(Math.floor((Date.now() - lastFetchTimestampRef.current) / 1000));
      setPollCountdown((prev) => (prev > 1 ? prev - 1 : pollSeconds));
    }, 1000);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        const elapsedSec = Math.floor((Date.now() - lastFetchTimestampRef.current) / 1000);
        if (elapsedSec >= pollSeconds) {
          quantViewApi.sendPresenceHeartbeat();
          fetchSnapshot();
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      clearInterval(timer);
      clearInterval(countdownTimer);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [fetchSnapshot, pollSeconds]);

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
    setTimeout(fetchSnapshot, 500);
  };

  // On-demand market scan across all symbols
  const handleScanMarkets = async () => {
    setIsScanningMarkets(true);
    try {
      const res = await quantViewApi.scanMarkets('1h');
      const count = res.data.qualified_signals_count || 0;
      addToast(
        'info',
        'Scan Completed',
        `Confluence engine evaluated ${res.data.symbols_scanned} symbols: ${count} actionable trade setup(s) identified.`
      );
      await fetchSnapshot();
    } catch (err: any) {
      addToast('warning', 'Scan Failed', err.message || 'Market scanner returned error');
    } finally {
      setIsScanningMarkets(false);
    }
  };

  // Manual synchronization of economic calendar from live provider
  const handleSyncNews = async () => {
    setIsSyncingCalendar(true);
    try {
      await quantViewApi.syncNewsCalendar();
      addToast(
        'success',
        'Calendar Synchronized',
        `Synced economic news events from ForexFactory provider via /api/v1/news/sync.`
      );
      await fetchSnapshot();
    } catch (err: any) {
      addToast('warning', 'Sync Failed', err.message || 'Could not synchronize calendar');
    } finally {
      setIsSyncingCalendar(false);
    }
  };

  // Manually trigger background scanner cycle
  const handleTriggerScannerCycle = async () => {
    setIsTriggeringScanner(true);
    try {
      await quantViewApi.triggerScannerCycle('1h', true, true);
      addToast(
        'success',
        'Scanner Triggered',
        `Background scanner cycle executed via /api/v1/telegram/scanner/trigger.`
      );
      await fetchSnapshot();
    } catch (err: any) {
      addToast('warning', 'Scanner Error', err.message || 'Could not trigger background scanner');
    } finally {
      setIsTriggeringScanner(false);
    }
  };

  // Test Notification Button Handler connected to POST /api/v1/telegram/broadcast
  const handleSendTestNotification = async () => {
    setIsSendingTestTelegram(true);
    setTestNotificationResult(null);

    try {
      const testPayload = `🔔 <b>[TEST PING - NOT A SIGNAL]</b>\n\n<b>QuantView Terminal — Connectivity Verification</b>\n• System: QuantView Institutional Terminal\n• Target: @signalTheBEST_bot\n• Backend: Connected to FastAPI /api/v1/telegram/broadcast\n• Time: ${new Date().toUTCString()}\n\n<i>This is an automated test ping to verify bot connectivity. No action required.</i>`;
      
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
          activeEvent: appConfig
            ? `Normal volatility conditions (Risk cap: ${appConfig.risk_per_order_pct}% per trade)`
            : 'Loading risk configuration…',
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

  // Non-admin users never see (or keep) the admin-only settings tab.
  useEffect(() => {
    if (!isAdmin && currentTab === 'settings') setCurrentTab('dashboard');
  }, [isAdmin, currentTab]);

  // Shared navigation props for the persistent sidebar and the mobile drawer
  const sidebarProps = {
    currentTab,
    onTabChange: setCurrentTab,
    signalsCount: signals.filter((s) => s.hasActiveSignal).length,
    positionsCount: positions.length,
    isBlackout: riskStatus.isBlackout,
    isApiConnected,
    isScannerRunning: scannerStatus?.is_running,
    isAdmin,
  };

  return (
    <div className="relative min-h-screen bg-[#030014] text-slate-100 flex flex-col font-sans selection:bg-violet-500/30 selection:text-white overflow-x-hidden">
      {/* ZaqriraAI Global Atmosphere Background: 3 Large, Fixed, Heavily Blurred Floating Orbs */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-0" aria-hidden="true">
        {/* Deep Void Base Layer */}
        <div className="absolute inset-0 bg-[#030014]" />

        {/* Orb 1: Neon Purple Float (Top-Left) */}
        <div className="absolute -top-[12%] -left-[8%] w-[55vw] h-[55vw] max-w-[800px] max-h-[800px] rounded-full bg-purple-600/20 blur-[140px] animate-orb-purple transform-gpu" />

        {/* Orb 2: Electric Cyan Float (Center-Right) */}
        <div className="absolute top-[28%] -right-[8%] w-[50vw] h-[50vw] max-w-[750px] max-h-[750px] rounded-full bg-cyan-500/15 blur-[140px] animate-orb-cyan transform-gpu" />

        {/* Orb 3: Deep Violet Float (Bottom-Left / Center) */}
        <div className="absolute -bottom-[15%] left-[20%] w-[58vw] h-[58vw] max-w-[850px] max-h-[850px] rounded-full bg-violet-700/20 blur-[150px] animate-orb-violet transform-gpu" />

        {/* Subtle Modern Grid Overlay with Radial Spotlight Mask */}
        <div
          className="absolute inset-0 bg-fintech-grid bg-[size:40px_40px] opacity-40"
          style={{
            maskImage: 'radial-gradient(ellipse 75% 60% at 50% 35%, black 20%, transparent 85%)',
            WebkitMaskImage: 'radial-gradient(ellipse 75% 60% at 50% 35%, black 20%, transparent 85%)',
          }}
        />
      </div>

      {/* Toast notifications */}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Sidebar Navigation — persistent rail on tablet/desktop */}
      <Sidebar {...sidebarProps} />

      {/* Mobile slide-in navigation drawer (< md) */}
      <MobileMenu
        {...sidebarProps}
        isOpen={isMobileSidebarOpen}
        onClose={() => setIsMobileSidebarOpen(false)}
      />

      {/* Main Content Wrapper (Elevated above background mesh) */}
      <div className="relative z-10 md:pl-16 lg:pl-[240px] flex flex-col min-h-screen">
        {/* Top Header with Real Balance, LIVE DATA badge, and Refresh Data button */}
        <Header
          account={account}
          riskStatus={riskStatus}
          pollSecondsRemaining={pollCountdown}
          isApiConnected={isApiConnected}
          isAccountReady={isApiConnected && hasAccountData}
          isRefreshing={isRefreshing}
          lastUpdatedSecondsAgo={lastUpdatedSecondsAgo}
          apiEndpoint="http://localhost:8000"
          isScannerRunning={scannerStatus?.is_running}
          onRefresh={handleManualRefresh}
          onToggleMobileSidebar={() => setIsMobileSidebarOpen(!isMobileSidebarOpen)}
          onToggleBlackout={handleToggleBlackout}
        />

        {/* Offline / Connection Error Banner (if API is unreachable) */}
        {!isApiConnected && !isInitialLoading && (
          <div className="mx-4 lg:mx-5 mt-2.5 px-3 py-2 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs font-mono flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0 text-amber-400" />
              <span>
                FastAPI backend on port 8000 unreachable. Running in <strong>SIMULATION MODE</strong>. Start server with <code>python -m uvicorn app.main:app --reload</code> in <code>server/</code>.
              </span>
            </div>
            <button
              onClick={handleManualRefresh}
              className="px-2.5 py-1 rounded bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-500/40 text-[11px] font-bold shrink-0 transition-all cursor-pointer flex items-center gap-1"
            >
              <RefreshCw className="w-3 h-3" />
              <span>Retry</span>
            </button>
          </div>
        )}

        {/* Workspace Context Bar — stacks into two rows on mobile */}
        <div className="px-4 sm:px-6 lg:px-8 py-2.5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 sm:gap-3 border-b border-white/10 text-xs font-sans bg-[#030014]/60 backdrop-blur-xl min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-zinc-500 uppercase text-[10px] tracking-wider shrink-0">Workspace:</span>
            <span className="font-semibold text-zinc-200 uppercase text-xs truncate min-w-0">
              {currentTab === 'dashboard' && 'Unified Trading Desk'}
              {currentTab === 'signals' && 'Multi-Timeframe Confluence Matrix'}
              {currentTab === 'positions' && 'Position & Order Management'}
              {currentTab === 'news' && 'Macroeconomic Risk Monitor'}
              {currentTab === 'settings' && 'Alert Engine & Daemon Settings'}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2 sm:gap-3 text-[11px] w-full sm:w-auto min-w-0">
            <button
              onClick={() => setShowQuoteDebug((prev) => !prev)}
              className={`min-h-[44px] md:min-h-0 px-2 py-0.5 rounded text-[10px] font-mono border transition-all cursor-pointer touch-manipulation ${
                showQuoteDebug
                  ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                  : 'bg-zinc-800/60 hover:bg-zinc-700/60 text-zinc-400 border-white/10'
              }`}
              title="Toggle Dev-only Quote Diagnostics"
            >
              Dev: Quote Diagnostics
            </button>
            {/* Workspace switcher — XAU/USD on MAIN, BTC/USD on CENT. */}
            <div
              role="group"
              aria-label="Workspace instrument"
              className="inline-flex items-center rounded-lg border border-white/10 bg-white/[0.03] p-0.5"
            >
              {(['XAU/USD', 'BTC/USD'] as PairSymbol[]).map((sym) => (
                <button
                  key={sym}
                  onClick={() => {
                    setWorkspaceSymbol(sym);
                    setSelectedChartSymbol(sym);
                  }}
                  className={`min-h-[36px] md:min-h-0 px-2.5 py-1 rounded-md text-[10px] font-sans font-semibold tracking-wide transition-all cursor-pointer touch-manipulation ${
                    workspaceSymbol === sym
                      ? sym === 'BTC/USD'
                        ? 'bg-amber-500/15 text-amber-300 border border-amber-500/30'
                        : 'bg-violet-500/15 text-violet-300 border border-violet-500/30'
                      : 'text-zinc-500 hover:text-zinc-200 border border-transparent'
                  }`}
                  title={`Switch workspace to ${sym} (${accountForSymbol(sym)} account)`}
                >
                  {sym === 'XAU/USD' ? 'XAU/USD (Main)' : 'BTC/USD (Cent)'}
                </button>
              ))}
            </div>
            <span className="hidden xl:inline text-zinc-400">
              Active Instrument: <strong className="text-zinc-200">
                {workspaceSymbol === 'BTC/USD' ? 'BTC/USD (Momentum / Cent)' : 'XAU/USD (Gold Focus / Main)'}
              </strong>
            </span>
            <span className="text-zinc-700 hidden xl:inline">|</span>
            <span
              className={`px-2.5 py-0.5 rounded-full text-[10px] font-semibold border ${
                isApiConnected
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25'
                  : 'bg-amber-500/10 text-amber-400 border-amber-500/30'
              }`}
            >
              {isApiConnected ? 'FASTAPI /api/v1 (LIVE)' : 'SIMULATION MODE'}
            </span>
          </div>
        </div>

        {/* Dev-Only Quote Provenance Debug Panel */}
        {showQuoteDebug && (
          <div className="mx-4 sm:mx-6 lg:mx-8 mt-3 p-3 rounded-xl bg-zinc-950/80 border border-amber-500/30 font-mono text-xs text-zinc-300 backdrop-blur-md">
            <div className="flex items-center justify-between border-b border-white/10 pb-2 mb-2">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                <span className="font-semibold text-amber-400 tracking-wide uppercase text-[11px]">
                  Quote Provenance & Symbol Correctness (Dev Diagnostics)
                </span>
              </div>
              <span className="text-[10px] text-zinc-500">GET /api/v1/market/{latestQuote?.symbol || 'XAU/USD'}/quote</span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-5 gap-3 text-[11px]">
              <div>
                <span className="text-zinc-500 block text-[10px] uppercase">Canonical Symbol</span>
                <span className="font-semibold text-zinc-200">{latestQuote?.symbol || 'XAU/USD'}</span>
              </div>
              <div>
                <span className="text-zinc-500 block text-[10px] uppercase">Provider</span>
                <span className={`font-semibold ${latestQuote?.provider === 'mock' ? 'text-amber-400' : 'text-emerald-400'}`}>
                  {latestQuote?.provider || 'pending'}
                </span>
              </div>
              <div>
                <span className="text-zinc-500 block text-[10px] uppercase">Provider Symbol</span>
                <span className="font-semibold text-cyan-300">{latestQuote?.provider_symbol || '--'}</span>
              </div>
              <div>
                <span className="text-zinc-500 block text-[10px] uppercase">Price</span>
                <span className="font-semibold text-white">{latestQuote?.price ? latestQuote.price.toFixed(2) : '--'}</span>
              </div>
              <div>
                <span className="text-zinc-500 block text-[10px] uppercase">Timestamp (UTC)</span>
                <span className="text-zinc-300 truncate block">{latestQuote?.timestamp ? new Date(latestQuote.timestamp).toISOString() : '--'}</span>
              </div>
              <div>
                <span className="text-zinc-500 block text-[10px] uppercase">Age</span>
                <span className="text-zinc-300">{latestQuote?.age_seconds != null ? `${latestQuote.age_seconds.toFixed(1)}s` : '--'}</span>
              </div>
              <div>
                <span className="text-zinc-500 block text-[10px] uppercase">Staleness</span>
                <span className={`font-semibold ${latestQuote?.is_stale ? 'text-rose-400' : 'text-emerald-400'}`}>
                  {latestQuote?.is_stale
                    ? (appConfig?.quote_stale_after_seconds != null
                        ? `STALE (>${appConfig.quote_stale_after_seconds}s no change)`
                        : <span className="animate-pulse" aria-busy="true">—</span>)
                    : 'FRESH'}
                </span>
              </div>
              <div>
                <span className="text-zinc-500 block text-[10px] uppercase">Cache Status</span>
                <span className="text-zinc-300">
                  {latestQuote?.cached ? `HIT (${latestQuote.cache_age_ms?.toFixed(0) || 0}ms)` : 'MISS (Fresh Tick)'}
                </span>
              </div>
              <div>
                <span className="text-zinc-500 block text-[10px] uppercase">Degraded</span>
                <span className={`font-semibold ${latestQuote?.degraded ? 'text-amber-400' : 'text-zinc-400'}`}>
                  {latestQuote?.degraded ? 'TRUE' : 'FALSE'}
                </span>
              </div>
              <div className="col-span-2 sm:col-span-1">
                <span className="text-zinc-500 block text-[10px] uppercase">Fallback Reason</span>
                <span className="text-amber-300/80 truncate block">{latestQuote?.fallback_reason || 'None (Primary)'}</span>
              </div>
            </div>
          </div>
        )}

        {/* Main Content Body - Responsive Padding & Overflow Boundary */}
        <main className="flex-1 px-3 sm:px-6 lg:px-8 py-4 sm:py-6 max-w-[1600px] w-full mx-auto min-w-0 overflow-x-hidden relative z-10">
          {/* 1. UNIFIED DASHBOARD TAB - BENTO GRID LAYOUT */}
          {currentTab === 'dashboard' && (
            <div className="grid grid-cols-12 gap-4 w-full">
              {/* Telemetry HUD Widget */}
              <GlassCard className="col-span-12" glowColor="purple">
                <SystemTelemetry
                  account={account}
                  quote={latestQuote}
                  scannerStatus={scannerStatus}
                  riskStatus={riskStatus}
                  isApiConnected={isApiConnected}
                />
              </GlassCard>

              {/* Performance Stats & Equity Curve derived from real trades */}
              <GlassCard className="col-span-12">
                <PerformanceDashboard
                  stats={stats}
                  account={account}
                  closedTrades={closedTrades}
                  appConfig={appConfig}
                />
              </GlassCard>

              {/* 2-Column Core Trading Desk Grid: Desktop 1fr/1.5fr (~40/60), Tablet/Mobile single column (Confluence on top, Chart below) */}
              <div className="col-span-12 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)] gap-4 lg:gap-6 w-full min-w-0">
                {/* Left Column (Desktop ~40%): Confluence Matrix Card */}
                <GlassCard className="order-1 w-full min-w-0" glowColor="green">
                  <SignalMatrix
                    signals={signals}
                    activeSymbol={workspaceSymbol}
                    livePrices={livePrices}
                    isLoading={isInitialLoading}
                    isScanning={isScanningMarkets}
                    appConfig={appConfig}
                    quote={latestQuote}
                    onToggleNotify={handleToggleNotify}
                    onSelectSignalForChart={handleSelectSignalForChart}
                    onTriggerScan={handleScanMarkets}
                    executedSymbols={positions.map((p) => p.symbol)}
                  />
                </GlassCard>

                {/* Right Column (Desktop ~60%): XAU/USD Chart with Lightweight Charts */}
                <GlassCard id="chart-section" className="order-2 w-full min-w-0" glowColor="cyan">
                  <TradingChart
                    selectedSymbol={selectedChartSymbol}
                    timeframe={chartTimeframeForSymbol(selectedChartSymbol)}
                    onSymbolChange={(sym) => setSelectedChartSymbol(sym)}
                    latestQuote={latestQuote}
                    signals={signals}
                    activeSignal={signals.find((s) => s.symbol === selectedChartSymbol && s.hasActiveSignal)}
                  />
                </GlassCard>
              </div>

              {/* Active Positions & Closed Trades Table (Live P&L with 3s refresh) (8-col) */}
              <GlassCard className="col-span-12 lg:col-span-8">
                <ActivePositionsTable
                  positions={positions}
                  closedTrades={closedTrades}
                  isLoading={isInitialLoading}
                  onClosePosition={handleClosePosition}
                />
              </GlassCard>

              {/* News & Risk Status (Live Economic Calendar & Blackout Filter) (4-col) */}
              <GlassCard className="col-span-12 lg:col-span-4">
                <NewsRiskMonitor
                  news={news}
                  riskStatus={riskStatus}
                  appConfig={appConfig}
                  isLoading={isInitialLoading}
                  isSyncingCalendar={isSyncingCalendar}
                  onToggleBlackout={handleToggleBlackout}
                  onSyncCalendar={handleSyncNews}
                />
              </GlassCard>

              {/* Notification & Background Scanner Settings Panel (ADMIN ONLY) */}
              {isAdmin && (
              <GlassCard className="col-span-12">
                <NotificationSettings
                  config={alertConfig}
                  appConfig={appConfig}
                  onUpdateConfig={setAlertConfig}
                  onSendTestNotification={handleSendTestNotification}
                  isSendingTest={isSendingTestTelegram}
                  testNotificationResult={testNotificationResult}
                  telegramStatus={telegramStatus}
                  scannerStatus={scannerStatus}
                  onTriggerScanner={handleTriggerScannerCycle}
                  isTriggeringScanner={isTriggeringScanner}
                />
              </GlassCard>
              )}
            </div>
          )}

          {/* 2. DEDICATED SIGNALS TAB */}
          {currentTab === 'signals' && (
            <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)] gap-4 lg:gap-6 w-full min-w-0">
              <GlassCard className="order-1 w-full min-w-0" glowColor="green">
                <SignalMatrix
                  signals={signals}
                  activeSymbol={workspaceSymbol}
                  livePrices={livePrices}
                  isLoading={isInitialLoading}
                  isScanning={isScanningMarkets}
                  appConfig={appConfig}
                  quote={latestQuote}
                  onToggleNotify={handleToggleNotify}
                  onSelectSignalForChart={handleSelectSignalForChart}
                  onTriggerScan={handleScanMarkets}
                  executedSymbols={positions.map((p) => p.symbol)}
                />
              </GlassCard>
              <GlassCard id="chart-section" className="order-2 w-full min-w-0" glowColor="cyan">
                <TradingChart
                  selectedSymbol={selectedChartSymbol}
                  timeframe={chartTimeframeForSymbol(selectedChartSymbol)}
                  onSymbolChange={(sym) => setSelectedChartSymbol(sym)}
                  latestQuote={latestQuote}
                  signals={signals}
                  activeSignal={signals.find((s) => s.symbol === selectedChartSymbol && s.hasActiveSignal)}
                />
              </GlassCard>
            </div>
          )}

          {/* 3. DEDICATED POSITIONS TAB */}
          {currentTab === 'positions' && (
            <div className="grid grid-cols-12 gap-4 w-full">
              <GlassCard className="col-span-12 lg:col-span-7">
                <ActivePositionsTable
                  positions={positions}
                  closedTrades={closedTrades}
                  isLoading={isInitialLoading}
                  onClosePosition={handleClosePosition}
                />
              </GlassCard>
              <GlassCard id="chart-section" className="col-span-12 lg:col-span-5" glowColor="cyan">
                <TradingChart
                  selectedSymbol={selectedChartSymbol}
                  timeframe={chartTimeframeForSymbol(selectedChartSymbol)}
                  onSymbolChange={(sym) => setSelectedChartSymbol(sym)}
                  latestQuote={latestQuote}
                  signals={signals}
                  activeSignal={signals.find((s) => s.symbol === selectedChartSymbol && s.hasActiveSignal)}
                />
              </GlassCard>
            </div>
          )}

          {/* 4. DEDICATED NEWS & RISK TAB */}
          {currentTab === 'news' && (
            <div className="grid grid-cols-12 gap-4 w-full">
              <GlassCard className="col-span-12">
                <NewsRiskMonitor
                  news={news}
                  riskStatus={riskStatus}
                  appConfig={appConfig}
                  isLoading={isInitialLoading}
                  isSyncingCalendar={isSyncingCalendar}
                  onToggleBlackout={handleToggleBlackout}
                  onSyncCalendar={handleSyncNews}
                />
              </GlassCard>
            </div>
          )}

          {/* 5. DEDICATED NOTIFICATION SETTINGS TAB (ADMIN ONLY) */}
          {isAdmin && currentTab === 'settings' && (
            <div className="grid grid-cols-12 gap-4 w-full">
              <GlassCard className="col-span-12">
                <NotificationSettings
                  config={alertConfig}
                  appConfig={appConfig}
                  onUpdateConfig={setAlertConfig}
                  onSendTestNotification={handleSendTestNotification}
                  isSendingTest={isSendingTestTelegram}
                  testNotificationResult={testNotificationResult}
                  telegramStatus={telegramStatus}
                  scannerStatus={scannerStatus}
                  onTriggerScanner={handleTriggerScannerCycle}
                  isTriggeringScanner={isTriggeringScanner}
                />
              </GlassCard>
            </div>
          )}
        </main>

        {/* Terminal Footer Bar displaying API response time */}
        <footer className="mt-auto border-t border-white/10 bg-[#030014]/80 backdrop-blur-xl px-4 lg:px-6 py-2.5 text-[11px] font-sans text-slate-400 flex flex-col sm:flex-row items-center justify-between gap-2">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-slate-300 font-semibold tracking-wide">QUANTVIEW v2.4.0</span>
            <span>•</span>
            <span className="font-mono text-[10px] text-slate-500">FastAPI: http://localhost:8000</span>
            <span>•</span>
            <span className="text-slate-400">Telegram Bot: @signalTheBEST_bot</span>
            <span className="hidden xl:inline text-slate-500">
              Algorithmic analysis provided for informational purposes. Trading involves risk.
            </span>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {/* API Response Time Display (Required) */}
            <span className="text-slate-300 font-semibold font-mono">
              API: {apiResponseTimeMs}ms
            </span>
            <span>•</span>
            <span
              className={`flex items-center gap-1 font-mono text-[10px] ${
                isApiConnected ? 'text-[#00e676]' : 'text-amber-400'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isApiConnected ? 'bg-[#00e676] animate-pulse' : 'bg-amber-400'
                }`}
              />
              {isApiConnected ? 'LIVE DATA POLLING (15s/30s/60s)' : 'SIMULATION MODE'}
            </span>
            <span>•</span>
            <span className="font-mono text-[10px]">UTC</span>
          </div>
        </footer>

      </div>
    </div>
  );
};

export default Dashboard;
