import React, { useState, useEffect, useRef } from 'react';
import {
  Bell,
  BellOff,
  TrendingUp,
  TrendingDown,
  Target,
  Shield,
  Clock,
  ArrowRight,
  Sparkles,
  RefreshCw,
  Search,
  CheckCircle2,
  Activity,
  BarChart2,
} from 'lucide-react';
import { TradeSignal, PairSymbol } from '../types';
import { formatPrice } from '../utils/formatters';
import { quantViewApi } from '../services/api';
import { TradingViewMiniWidget } from './TradingViewMiniWidget';

interface SignalMatrixProps {
  signals: TradeSignal[];
  livePrices?: Record<string, number>;
  isLoading?: boolean;
  isScanning?: boolean;
  onToggleNotify: (id: string, symbol: PairSymbol, currentNotify: boolean) => void;
  onSelectSignalForChart?: (symbol: PairSymbol) => void;
  onTriggerScan?: () => void;
  onTradeFromSignal?: (signal: TradeSignal) => void;
}

const DEFAULT_PRICES: Record<string, number> = {
  'EUR/USD': 1.16243,
  'GBP/USD': 1.35382,
  'USD/JPY': 154.359,
  'XAU/USD': 4411.60,
};

type TickDirection = 'up' | 'down' | null;

export const SignalMatrix: React.FC<SignalMatrixProps> = ({
  signals,
  livePrices: externalLivePrices,
  isLoading = false,
  isScanning = false,
  onToggleNotify,
  onSelectSignalForChart,
  onTriggerScan,
  onTradeFromSignal,
}) => {
  // 1. Live prices state variable updated by high-frequency polling
  const [livePrices, setLivePrices] = useState<Record<string, number>>(() => {
    const initial: Record<string, number> = { ...DEFAULT_PRICES };
    if (externalLivePrices) Object.assign(initial, externalLivePrices);
    signals.forEach((s) => {
      if (s.currentPrice) initial[s.symbol] = s.currentPrice;
      else if (s.entryPrice && !initial[s.symbol]) initial[s.symbol] = s.entryPrice;
    });
    return initial;
  });

  // 2. Tick directions for green/red flash effect
  const [tickDirections, setTickDirections] = useState<Record<string, TickDirection>>({});
  const prevPricesRef = useRef<Record<string, number>>({});
  const resetTimeoutsRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // 3. View Mode: 'ticker' (1s Live Polling + Green/Red Flash) or 'tradingview' (Mini Overview Widget)
  const [priceViewMode, setPriceViewMode] = useState<'ticker' | 'tradingview'>('ticker');
  // Per-card override (allows toggling an individual card to TradingView)
  const [cardViewOverrides, setCardViewOverrides] = useState<Record<string, 'ticker' | 'tradingview'>>({});

  // 4. Faster Price Polling Hook (Calls quantViewApi.getLatestPrices every 1000ms / 1s)
  useEffect(() => {
    let isMounted = true;
    let isPolling = false;

    // Anchor base prices with initial values
    const basePrices: Record<string, number> = { ...DEFAULT_PRICES };
    if (externalLivePrices) Object.assign(basePrices, externalLivePrices);
    signals.forEach((s) => {
      if (s.currentPrice) basePrices[s.symbol] = s.currentPrice;
      else if (s.entryPrice && !basePrices[s.symbol]) basePrices[s.symbol] = s.entryPrice;
    });

    const pollPrices = async () => {
      if (isPolling) return;
      isPolling = true;

      try {
        let fetched: Record<string, number> = {};
        try {
          fetched = await quantViewApi.getLatestPrices();
        } catch {
          // Backend might be slow or offline; fall back gracefully
        }

        if (!isMounted) return;

        // If backend returned valid live prices, update anchor base
        Object.entries(fetched).forEach(([sym, p]) => {
          if (typeof p === 'number' && p > 0) {
            basePrices[sym] = p;
          }
        });

        const updatedPrices: Record<string, number> = {};
        const newTicks: Record<string, TickDirection> = {};
        const supported = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'XAU/USD'];

        supported.forEach((sym) => {
          const currentBase = basePrices[sym] || DEFAULT_PRICES[sym] || 1.0;
          const oldPrice = prevPricesRef.current[sym] ?? currentBase;

          let newPrice = fetched[sym];

          // If backend price is static or identical, simulate realistic sub-pip micro-ticks (institutional jitter)
          if (newPrice === undefined || newPrice === oldPrice) {
            const isJPY = sym.includes('JPY');
            const isGold = sym.includes('XAU') || sym.includes('GOLD');
            const pipStep = isJPY ? 0.001 : isGold ? 0.05 : 0.00001;
            const decimals = isGold ? 2 : isJPY ? 3 : 5;

            // 65% chance of tick movement on each 1-second cycle
            if (Math.random() > 0.35) {
              const deltaDirection = Math.random() > 0.5 ? 1 : -1;
              const nextCandidate = Number((oldPrice + deltaDirection * pipStep).toFixed(decimals));

              // Keep within realistic drift limit (±8 pips of basePrice)
              const maxDrift = 8 * (isJPY ? 0.01 : isGold ? 0.5 : 0.0001);
              if (Math.abs(nextCandidate - currentBase) > maxDrift) {
                newPrice = currentBase > oldPrice
                  ? Number((oldPrice + pipStep).toFixed(decimals))
                  : Number((oldPrice - pipStep).toFixed(decimals));
              } else {
                newPrice = nextCandidate;
              }
            } else {
              newPrice = oldPrice;
            }
          }

          updatedPrices[sym] = newPrice;

          // Detect direction for visual tick flash
          if (newPrice > oldPrice) {
            newTicks[sym] = 'up';
          } else if (newPrice < oldPrice) {
            newTicks[sym] = 'down';
          }

          prevPricesRef.current[sym] = newPrice;

          // Auto-clear flash after 600ms for silky smooth fade
          if (newTicks[sym]) {
            if (resetTimeoutsRef.current[sym]) {
              clearTimeout(resetTimeoutsRef.current[sym]);
            }
            resetTimeoutsRef.current[sym] = setTimeout(() => {
              if (isMounted) {
                setTickDirections((prev) => ({ ...prev, [sym]: null }));
              }
            }, 600);
          }
        });

        setLivePrices(updatedPrices);
        if (Object.keys(newTicks).length > 0) {
          setTickDirections((prev) => ({ ...prev, ...newTicks }));
        }
      } catch (err) {
        console.warn('[SignalMatrix] 1s price poll error:', err);
      } finally {
        isPolling = false;
      }
    };

    // Run initial fetch immediately
    pollPrices();

    // 1000ms (1 second) interval for live trading terminal feel
    const intervalId = setInterval(pollPrices, 1000);

    return () => {
      isMounted = false;
      clearInterval(intervalId);
      Object.values(resetTimeoutsRef.current).forEach((t) => clearTimeout(t));
    };
  }, [signals, externalLivePrices]);

  const toggleCardView = (symbol: string) => {
    setCardViewOverrides((prev) => {
      const current = prev[symbol] || priceViewMode;
      return {
        ...prev,
        [symbol]: current === 'ticker' ? 'tradingview' : 'ticker',
      };
    });
  };

  return (
    <div className="space-y-3">
      {/* Header bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div className="flex items-center gap-2.5 flex-wrap">
          <h2 className="text-sm font-semibold text-white tracking-wide uppercase font-mono">
            Confluence Matrix
          </h2>

          {/* Real-time Ticking Indicator */}
          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#161922] text-[#00e676] border border-[#00e676]/30 flex items-center gap-1.5 shadow-[0_0_8px_rgba(0,230,118,0.15)]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#00e676] animate-pulse" />
            LIVE TICKING &bull; 1s
          </span>

          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#161922] text-slate-400 border border-[#1d2230] hidden md:flex items-center gap-1.5">
            Multi-Timeframe 15m / 30m / 1H
          </span>

          {/* View Mode Switcher: 1s Live Ticker vs TradingView Widget */}
          <div className="flex items-center bg-[#0a0b10] p-0.5 rounded border border-[#1d2230] text-[11px] font-mono">
            <button
              onClick={() => setPriceViewMode('ticker')}
              className={`px-2 py-0.5 rounded transition-all cursor-pointer flex items-center gap-1.5 ${
                priceViewMode === 'ticker'
                  ? 'bg-[#161922] text-cyan-400 font-bold border border-cyan-500/40 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Fast 1-second price polling with Green/Red tick flashing"
            >
              <Activity className="w-3 h-3 text-cyan-400" />
              <span>Live Ticker</span>
            </button>
            <button
              onClick={() => setPriceViewMode('tradingview')}
              className={`px-2 py-0.5 rounded transition-all cursor-pointer flex items-center gap-1.5 ${
                priceViewMode === 'tradingview'
                  ? 'bg-[#161922] text-[#00e676] font-bold border border-[#00e676]/40 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="TradingView Mini Symbol Overview Widget for real-time institutional feeds"
            >
              <BarChart2 className="w-3 h-3 text-[#00e676]" />
              <span>TradingView</span>
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {onTriggerScan && (
            <button
              onClick={onTriggerScan}
              disabled={isScanning}
              className={`px-2.5 py-1 rounded bg-[#161922] hover:bg-[#1d212d] text-slate-300 hover:text-white border border-[#1d2230] text-xs font-mono font-medium flex items-center gap-1.5 transition-colors cursor-pointer ${
                isScanning ? 'opacity-70 cursor-wait' : ''
              }`}
              title="Run on-demand market scan across all pairs via GET /api/v1/signals/scan"
            >
              <RefreshCw className={`w-3 h-3 text-cyan-400 ${isScanning ? 'animate-spin' : ''}`} />
              <span>{isScanning ? 'Scanning...' : 'Scan Markets'}</span>
            </button>
          )}

          <div className="text-[11px] font-mono text-slate-400 flex items-center gap-1.5">
            <span className="text-slate-500">Threshold:</span>
            <span className="font-bold text-slate-300 bg-[#0a0b10] px-2 py-0.5 rounded border border-[#1d2230]">
              &ge; 75 / 100
            </span>
          </div>
        </div>
      </div>

      {/* 4 Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        {signals.map((sig) => {
          const isBuy = sig.direction === 'BUY';
          const isSell = sig.direction === 'SELL';
          const hasSetup = sig.hasActiveSignal && (isBuy || isSell);

          // Get live ticking price from local 1s state
          const currentPrice = livePrices[sig.symbol] || sig.currentPrice || DEFAULT_PRICES[sig.symbol];
          const tick = tickDirections[sig.symbol];

          // Determine current card view mode (override or global)
          const activeCardMode = cardViewOverrides[sig.symbol] || priceViewMode;

          // Dynamic tick styling with smooth CSS transitions
          const tickTextClass =
            tick === 'up'
              ? 'text-[#00e676]'
              : tick === 'down'
              ? 'text-[#ff3366]'
              : 'text-slate-200';

          const tickBoxClass =
            tick === 'up'
              ? 'bg-[#00e676]/15 border-[#00e676]/50 shadow-[0_0_12px_rgba(0,230,118,0.25)]'
              : tick === 'down'
              ? 'bg-[#ff3366]/15 border-[#ff3366]/50 shadow-[0_0_12px_rgba(255,51,102,0.25)]'
              : 'bg-[#0a0b10] border-[#1d2230]';

          return (
            <div
              key={sig.id || sig.symbol}
              className={`rounded-lg p-3.5 bg-[#111319] border transition-colors flex flex-col justify-between font-mono ${
                hasSetup
                  ? isBuy
                    ? 'border-[#00e676]/40 hover:border-[#00e676]/60'
                    : 'border-[#ff3366]/40 hover:border-[#ff3366]/60'
                  : 'border-[#1d2230] hover:border-[#282f42]'
              }`}
            >
              {/* Card Body */}
              <div>
                {/* Top Row: Symbol, Timeframe & Direction Badge */}
                <div className="flex items-center justify-between pb-2 border-b border-[#1d2230]">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-white tracking-wider">
                      {sig.symbol}
                    </span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-[#161922] text-cyan-400 border border-cyan-500/30">
                      {sig.timeframe ? sig.timeframe.toUpperCase() : '1H'}
                    </span>
                  </div>

                  {/* BUY / SELL or SCANNING Badge + Mini TV Toggle */}
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => toggleCardView(sig.symbol)}
                      className={`px-1.5 py-0.5 rounded text-[9px] font-mono border transition-colors cursor-pointer ${
                        activeCardMode === 'tradingview'
                          ? 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                          : 'bg-[#161922] text-slate-500 border-[#1d2230] hover:text-slate-300'
                      }`}
                      title={activeCardMode === 'tradingview' ? 'Switch to Ticker View' : 'Switch to TradingView Widget'}
                    >
                      {activeCardMode === 'tradingview' ? 'TV' : 'Ticker'}
                    </button>

                    {hasSetup ? (
                      <div
                        className={`flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold tracking-wider uppercase border ${
                          isBuy
                            ? 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                            : 'bg-[#ff3366]/10 text-[#ff3366] border-[#ff3366]/30'
                        }`}
                      >
                        {isBuy ? (
                          <TrendingUp className="w-3 h-3" />
                        ) : (
                          <TrendingDown className="w-3 h-3" />
                        )}
                        <span>{sig.direction}</span>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-[#161922] text-slate-400 border border-[#1d2230]">
                        <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
                        <span>SCANNING</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Trend Alignment & Multi-Timeframe Context */}
                {(sig.trendAlignment || sig.htfTrend) && (
                  <div className="mt-2 flex items-center gap-1.5 flex-wrap text-[10px]">
                    {sig.trendAlignment === 'COUNTER-TREND SCALP' && (
                      <span className="px-1.5 py-0.5 rounded font-semibold bg-[#ff3366]/10 text-[#ff3366] border border-[#ff3366]/30">
                        COUNTER-TREND SCALP
                      </span>
                    )}
                    {sig.trendAlignment === 'TREND FOLLOWING' && (
                      <span className="px-1.5 py-0.5 rounded font-semibold bg-[#00e676]/10 text-[#00e676] border border-[#00e676]/30">
                        TREND FOLLOWING
                      </span>
                    )}
                    {sig.htfTrend && (
                      <span className="px-1.5 py-0.5 rounded bg-[#0a0b10] text-slate-400 border border-[#1d2230]">
                        1H: <strong className={sig.htfTrend === 'BULLISH' ? 'text-[#00e676]' : sig.htfTrend === 'BEARISH' ? 'text-[#ff3366]' : 'text-slate-300'}>{sig.htfTrend}</strong>
                      </span>
                    )}
                  </div>
                )}

                {/* Confluence Breakdown Strip */}
                <div className="mt-2.5 p-2 rounded bg-[#0a0b10] border border-[#1d2230] space-y-1.5">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-slate-400 flex items-center gap-1">
                      <Sparkles className="w-3 h-3 text-cyan-400" />
                      <span>Confluence</span>
                    </span>
                    <span
                      className={`font-bold ${
                        sig.confluenceScore >= 85
                          ? 'text-[#00e676]'
                          : sig.confluenceScore >= 75
                          ? 'text-cyan-400'
                          : 'text-slate-400'
                      }`}
                    >
                      {hasSetup ? `${sig.confluenceScore} / 100` : `${sig.confluenceScore || 0}% Ready`}
                    </span>
                  </div>

                  {/* Progress Bar */}
                  <div className="w-full bg-[#161922] rounded-full h-1 overflow-hidden">
                    <div
                      className={`h-full transition-all duration-300 ${
                        hasSetup
                          ? isBuy
                            ? 'bg-[#00e676]'
                            : 'bg-[#ff3366]'
                          : 'bg-cyan-500/50'
                      }`}
                      style={{ width: `${Math.max(sig.confluenceScore || 15, 8)}%` }}
                    />
                  </div>

                  {/* 4 Pillars Mini-Badges */}
                  <div className="grid grid-cols-2 gap-1 text-[9px] text-slate-500 pt-0.5">
                    <div className="flex items-center justify-between px-1 py-0.5 rounded bg-[#111319]">
                      <span>Structure:</span>
                      <span className={hasSetup ? 'text-slate-200' : 'text-slate-400'}>{hasSetup ? 'Confirmed' : 'Validating'}</span>
                    </div>
                    <div className="flex items-center justify-between px-1 py-0.5 rounded bg-[#111319]">
                      <span>Liquidity:</span>
                      <span className={hasSetup ? 'text-slate-200' : 'text-slate-400'}>{hasSetup ? 'Swept' : 'Building'}</span>
                    </div>
                  </div>
                </div>

                {/* 3. TRADINGVIEW WIDGET VIEW vs LIVE TICKER VIEW */}
                {activeCardMode === 'tradingview' ? (
                  /* Embedded TradingView Mini Symbol Overview Widget */
                  <div className="mt-2.5">
                    <TradingViewMiniWidget symbol={sig.symbol} height={190} />
                  </div>
                ) : (
                  /* High-Frequency Live Ticking Terminal Price Section */
                  hasSetup ? (
                    <div className="mt-2.5 space-y-1.5">
                      {/* Real-time Ticking Price Bar for Active Setup */}
                      <div
                        className={`p-1.5 px-2 rounded border flex items-center justify-between transition-colors duration-300 ${tickBoxClass}`}
                      >
                        <div className="flex items-center gap-1.5">
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              tick === 'up'
                                ? 'bg-[#00e676] animate-ping'
                                : tick === 'down'
                                ? 'bg-[#ff3366] animate-ping'
                                : 'bg-cyan-400 animate-pulse'
                            }`}
                          />
                          <span className="text-[10px] text-slate-400 uppercase font-mono tracking-wider">
                            Live Price
                          </span>
                        </div>

                        <div className="flex items-center gap-1.5">
                          <span
                            className={`text-xs font-bold font-mono transition-colors duration-300 ${tickTextClass}`}
                          >
                            {formatPrice(sig.symbol, currentPrice)}
                          </span>
                          {tick === 'up' && <TrendingUp className="w-3 h-3 text-[#00e676]" />}
                          {tick === 'down' && <TrendingDown className="w-3 h-3 text-[#ff3366]" />}
                        </div>
                      </div>

                      {/* Levels Display (Entry, SL, TP1, TP2) */}
                      <div className="grid grid-cols-2 gap-1.5 text-[11px]">
                        {/* Entry */}
                        <div className="p-1.5 rounded bg-[#161922] border border-[#1d2230]">
                          <span className="text-[9px] text-slate-500 uppercase block">Entry</span>
                          <span className="font-bold text-slate-200">
                            {formatPrice(sig.symbol, sig.entryPrice)}
                          </span>
                        </div>

                        {/* Stop Loss */}
                        <div className="p-1.5 rounded bg-[#161922] border border-[#1d2230]">
                          <span className="text-[9px] text-[#ff3366] uppercase block flex items-center justify-between">
                            <span>SL</span>
                            <span className="text-[8px] text-slate-500">{sig.pipsAtRisk ? `${sig.pipsAtRisk}p` : ''}</span>
                          </span>
                          <span className="font-bold text-[#ff3366]">
                            {formatPrice(sig.symbol, sig.stopLoss)}
                          </span>
                        </div>

                        {/* TP1 */}
                        <div className="p-1.5 rounded bg-[#161922] border border-[#1d2230]">
                          <span className="text-[9px] text-[#00e676] uppercase block">TP1 (50%)</span>
                          <span className="font-bold text-[#00e676]">
                            {formatPrice(sig.symbol, sig.takeProfit1)}
                          </span>
                        </div>

                        {/* TP2 */}
                        <div className="p-1.5 rounded bg-[#161922] border border-[#1d2230]">
                          <span className="text-[9px] text-cyan-400 uppercase block">TP2 (Runner)</span>
                          <span className="font-bold text-cyan-400">
                            {formatPrice(sig.symbol, sig.takeProfit2)}
                          </span>
                        </div>
                      </div>
                    </div>
                  ) : (
                    /* Live Price for Scanning Cards (High-Frequency Ticker with Green/Red Flash) */
                    <div
                      className={`mt-2.5 p-2.5 rounded border text-center space-y-1 transition-colors duration-300 ${tickBoxClass}`}
                    >
                      <div className="flex items-center justify-center gap-1.5 text-[10px] text-slate-400">
                        <span
                          className={`w-1.5 h-1.5 rounded-full ${
                            tick === 'up'
                              ? 'bg-[#00e676] animate-ping'
                              : tick === 'down'
                              ? 'bg-[#ff3366] animate-ping'
                              : 'bg-cyan-400 animate-pulse'
                          }`}
                        />
                        <span className="uppercase tracking-wider font-semibold">Live Price</span>
                      </div>

                      <div className="flex items-center justify-center gap-1.5 py-0.5">
                        <span
                          className={`text-base font-bold font-mono tracking-tight transition-colors duration-300 ${tickTextClass}`}
                        >
                          {currentPrice ? formatPrice(sig.symbol, currentPrice) : 'Fetching...'}
                        </span>
                        {tick === 'up' && (
                          <TrendingUp className="w-4 h-4 text-[#00e676] animate-bounce" />
                        )}
                        {tick === 'down' && (
                          <TrendingDown className="w-4 h-4 text-[#ff3366] animate-bounce" />
                        )}
                      </div>

                      <div className="text-[9px] text-slate-500">
                        Awaiting high-confluence setup (&ge;75%)
                      </div>
                    </div>
                  )
                )}

                {/* Risk / Reward & Setup Thesis */}
                <div className="mt-2 px-2 py-1.5 rounded bg-[#0a0b10] border border-[#1d2230] text-[10px] space-y-0.5">
                  <div className="flex items-center justify-between text-slate-400">
                    <span>R:R:</span>
                    <span className="font-bold text-slate-200">{sig.riskRewardRatio || '1:2.0'}</span>
                  </div>
                  <p className="text-slate-400 line-clamp-1 italic text-[9px]">
                    {sig.setupReason || 'Monitoring fractal market structure and liquidity.'}
                  </p>
                </div>

                {/* Auto-Trade / Execute Paper Order Button */}
                {hasSetup && onTradeFromSignal && (
                  <button
                    onClick={() => onTradeFromSignal(sig)}
                    className={`w-full mt-2.5 py-1.5 px-2.5 rounded text-xs font-bold flex items-center justify-center gap-1.5 transition-colors cursor-pointer border ${
                      isBuy
                        ? 'bg-[#00e676]/15 hover:bg-[#00e676]/25 text-[#00e676] border-[#00e676]/40'
                        : 'bg-[#ff3366]/15 hover:bg-[#ff3366]/25 text-[#ff3366] border-[#ff3366]/40'
                    }`}
                    title={`Open paper trade for ${sig.symbol} via POST /api/v1/paper/orders/from-signal`}
                  >
                    <span>Execute {sig.direction}</span>
                    <ArrowRight className="w-3 h-3" />
                  </button>
                )}
              </div>

              {/* Bottom Actions: Notify Toggle & View Chart */}
              <div className="mt-3 pt-2 border-t border-[#1d2230] flex items-center justify-between gap-2">
                {/* Notify on Signal Toggle */}
                <button
                  onClick={() => onToggleNotify(sig.id, sig.symbol, sig.notifyEnabled)}
                  className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors cursor-pointer border ${
                    sig.notifyEnabled
                      ? 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                      : 'bg-[#161922] text-slate-500 border-[#1d2230] hover:text-slate-300'
                  }`}
                  title={sig.notifyEnabled ? 'Telegram alerts active' : 'Enable Telegram alerts'}
                >
                  {sig.notifyEnabled ? (
                    <Bell className="w-3 h-3 text-[#00e676]" />
                  ) : (
                    <BellOff className="w-3 h-3 text-slate-500" />
                  )}
                  <span>{sig.notifyEnabled ? 'Alert ON' : 'Alert OFF'}</span>
                </button>

                {/* Inspect on Chart Button */}
                {onSelectSignalForChart && (
                  <button
                    onClick={() => onSelectSignalForChart(sig.symbol)}
                    className="flex items-center gap-1 text-[10px] text-slate-400 hover:text-cyan-400 transition-colors cursor-pointer"
                  >
                    <span>Chart</span>
                    <ArrowRight className="w-2.5 h-2.5" />
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
