import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  RefreshCw,
  Activity,
  Layers,
  Sparkles,
  SlidersHorizontal,
} from 'lucide-react';
import { TradeSignal, PairSymbol } from '../types';
import { ConfluenceCard } from './ConfluenceCard';
import { AppConfig, BackendQuote } from '../services/api';

interface SignalMatrixProps {
  signals: TradeSignal[];
  livePrices?: Record<string, number>;
  isLoading?: boolean;
  isScanning?: boolean;
  onToggleNotify: (id: string, symbol: PairSymbol, currentNotify: boolean) => void;
  onSelectSignalForChart?: (symbol: PairSymbol) => void;
  onTriggerScan?: () => void;
  onTradeFromSignal?: (signal: TradeSignal) => void;
  appConfig?: AppConfig | null;
  quote?: BackendQuote | null;
}

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
  appConfig,
  quote,
}) => {
  // Honest provenance: provider labels are minute-rounded, so "updated" means the
  // last time we actually fetched, not the provider minute label.
  const quoteAgeSeconds = quote
    ? Math.max(0, Math.round((Date.now() - new Date(quote.fetched_at || quote.timestamp).getTime()) / 1000))
    : null;
  const providerLabel = quote?.provider === 'twelvedata'
    ? 'Twelve Data'
    : quote?.provider === 'mock'
      ? 'Mock'
      : (quote?.provider || 'provider');
  const staleAfterSeconds = appConfig?.quote_stale_after_seconds ?? 180;
  // Tick directions for green/red flash effect on real price changes
  const [tickDirections, setTickDirections] = useState<Record<string, TickDirection>>({});
  const prevPricesRef = useRef<Record<string, number>>({});
  const resetTimeoutsRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // Derive consolidated live prices from externalLivePrices or signal definitions without mock defaults
  const resolvedPrices = useMemo(() => {
    const prices: Record<string, number> = {};
    if (externalLivePrices) {
      Object.entries(externalLivePrices).forEach(([sym, p]) => {
        if (typeof p === 'number' && p > 0) {
          prices[sym] = p;
        }
      });
    }
    signals.forEach((s) => {
      if (s.currentPrice && s.currentPrice > 0 && !prices[s.symbol]) {
        prices[s.symbol] = s.currentPrice;
      } else if (s.entryPrice && s.entryPrice > 0 && !prices[s.symbol]) {
        prices[s.symbol] = s.entryPrice;
      }
    });
    return prices;
  }, [externalLivePrices, signals]);

  // Track real tick direction changes (no fake micro-tick simulation)
  useEffect(() => {
    const newTicks: Record<string, TickDirection> = {};

    Object.entries(resolvedPrices).forEach(([sym, price]) => {
      const oldPrice = prevPricesRef.current[sym];
      if (oldPrice !== undefined && price !== oldPrice) {
        if (price > oldPrice) {
          newTicks[sym] = 'up';
        } else if (price < oldPrice) {
          newTicks[sym] = 'down';
        }
      }
      prevPricesRef.current[sym] = price;

      if (newTicks[sym]) {
        if (resetTimeoutsRef.current[sym]) {
          clearTimeout(resetTimeoutsRef.current[sym]);
        }
        resetTimeoutsRef.current[sym] = setTimeout(() => {
          setTickDirections((prev) => ({ ...prev, [sym]: null }));
        }, 1200);
      }
    });

    if (Object.keys(newTicks).length > 0) {
      setTickDirections((prev) => ({ ...prev, ...newTicks }));
    }

    return () => {
      Object.values(resetTimeoutsRef.current).forEach((t) => clearTimeout(t));
    };
  }, [resolvedPrices]);

  // Filter signals strictly to supported symbols: XAU/USD (US100 quarantined)
  const activeSignals = signals.filter((s) => s.symbol === 'XAU/USD');

  return (
    <div className="space-y-4 w-full min-w-0 overflow-hidden">
      {/* Sleek Glassmorphic Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 p-4 rounded-xl bg-white/[0.03] border border-white/10 min-w-0">
        <div className="flex items-center gap-3 flex-wrap min-w-0">
          <div className="flex items-center gap-2 shrink-0">
            <Layers className="w-4 h-4 text-emerald-400" />
            <h2 className="text-sm font-semibold text-white tracking-wide uppercase font-sans truncate">
              Confluence Matrix
            </h2>
          </div>

          {/* Honest quote provenance / staleness badge */}
          {quote?.is_stale ? (
            <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono bg-rose-500/10 text-rose-400 border border-rose-500/20 flex items-center gap-1.5 shrink-0">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
              STALE &bull; no price change &gt;{staleAfterSeconds}s
            </span>
          ) : (
            <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5 shadow-[0_0_12px_rgba(16,185,129,0.15)] shrink-0">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              1-min aggregated &middot; {providerLabel} &middot; updated {quoteAgeSeconds != null ? `${quoteAgeSeconds}s` : '--'} ago
            </span>
          )}

          <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono bg-white/5 text-zinc-400 border border-white/10 hidden md:flex items-center gap-1.5 shrink-0">
            Single-Asset Focus &bull; XAU/USD
          </span>
        </div>

        <div className="flex items-center gap-3 shrink-0 self-start sm:self-auto">
          {onTriggerScan && (
            <button
              onClick={onTriggerScan}
              disabled={isScanning}
              className={`px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white font-sans text-xs font-semibold flex items-center gap-2 border border-violet-400/30 shadow-[0_0_20px_rgba(124,58,237,0.35)] hover:shadow-[0_0_25px_rgba(124,58,237,0.55)] transition-all duration-300 cursor-pointer ${
                isScanning ? 'opacity-70 cursor-wait' : ''
              }`}
              title="Run on-demand market scan across XAU/USD via GET /api/v1/signals/scan"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-white ${isScanning ? 'animate-spin' : ''}`} />
              <span>{isScanning ? 'Scanning...' : 'Scan Markets'}</span>
            </button>
          )}

          <div className="text-xs font-mono text-zinc-400 flex items-center gap-1.5">
            <span className="text-zinc-500">Threshold:</span>
            <span className="font-semibold text-zinc-200 bg-white/5 px-2.5 py-0.5 rounded-lg border border-white/10">
              &ge; {appConfig?.min_confluence_score ?? 60} / 100
            </span>
          </div>
        </div>
      </div>

      {/* Signal Cards Display - Responsive Grid with min-w-0 overflow safety */}
      {activeSignals.length === 0 ? (
        <div className="rounded-2xl bg-zinc-900/40 backdrop-blur-md border border-white/10 p-8 sm:p-10 text-center font-mono w-full min-w-0">
          <p className="text-sm text-zinc-300 font-semibold mb-1">No Active Signals For XAU/USD</p>
          <p className="text-xs text-zinc-500 max-w-md mx-auto">
            Awaiting confirmed liquidity sweep and order-flow imbalance before triggering trade setup.
          </p>
        </div>
      ) : (
        <div className={activeSignals.length === 1 ? "w-full min-w-0" : "grid grid-cols-1 xl:grid-cols-2 gap-6 w-full min-w-0"}>
          {activeSignals.map((sig) => (
            <ConfluenceCard
              key={sig.id}
              signal={sig}
              livePrice={resolvedPrices[sig.symbol]}
              tickDirection={tickDirections[sig.symbol]}
              onToggleNotify={onToggleNotify}
              onSelectSignalForChart={onSelectSignalForChart}
              onTradeFromSignal={onTradeFromSignal}
              minScore={appConfig?.min_confluence_score ?? 60}
            />
          ))}
        </div>
      )}
    </div>
  );
};
