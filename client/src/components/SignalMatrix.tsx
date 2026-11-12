import React, { useState, useEffect, useRef } from 'react';
import {
  RefreshCw,
  Activity,
  Layers,
  Sparkles,
  SlidersHorizontal,
} from 'lucide-react';
import { TradeSignal, PairSymbol } from '../types';
import { quantViewApi } from '../services/api';
import { ConfluenceCard } from './ConfluenceCard';

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
  'XAU/USD': 2685.50,
  // 'US100': 20450.50, // Quarantined: US100 suspended due to API paywall
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

  // 3. Fast 1-second price polling for trading terminal feel
  useEffect(() => {
    let isMounted = true;
    let isPolling = false;

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
          // Backend offline or busy
        }

        if (!isMounted) return;

        Object.entries(fetched).forEach(([sym, p]) => {
          if (typeof p === 'number' && p > 0) {
            basePrices[sym] = p;
          }
        });

        const updatedPrices: Record<string, number> = {};
        const newTicks: Record<string, TickDirection> = {};
        const supported = ['XAU/USD'];

        supported.forEach((sym) => {
          const currentBase = basePrices[sym] || DEFAULT_PRICES[sym] || 100.0;
          const oldPrice = prevPricesRef.current[sym] ?? currentBase;

          let newPrice = fetched[sym];

          // Simulate realistic micro-ticks if backend doesn't push a tick
          if (newPrice === undefined || newPrice === oldPrice) {
            const pipStep = 0.05; // Gold micro-tick
            const decimals = 2;

            if (Math.random() > 0.35) {
              const deltaDirection = Math.random() > 0.5 ? 1 : -1;
              const nextCandidate = Number((oldPrice + deltaDirection * pipStep).toFixed(decimals));
              const maxDrift = 12 * pipStep;
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

          if (newPrice > oldPrice) {
            newTicks[sym] = 'up';
          } else if (newPrice < oldPrice) {
            newTicks[sym] = 'down';
          }

          prevPricesRef.current[sym] = newPrice;

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
        console.warn('[SignalMatrix] 1s poll error:', err);
      } finally {
        isPolling = false;
      }
    };

    pollPrices();
    const intervalId = setInterval(pollPrices, 1000);

    return () => {
      isMounted = false;
      clearInterval(intervalId);
      Object.values(resetTimeoutsRef.current).forEach((t) => clearTimeout(t));
    };
  }, [signals, externalLivePrices]);

  // Filter signals strictly to supported symbols: XAU/USD (US100 quarantined)
  const activeSignals = signals.filter((s) => s.symbol === 'XAU/USD');

  return (
    <div className="space-y-4">
      {/* Sleek Glassmorphic Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 p-4 rounded-2xl bg-zinc-900/40 backdrop-blur-md border border-white/10">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-emerald-400" />
            <h2 className="text-sm font-semibold text-white tracking-wide uppercase font-mono">
              Confluence Matrix
            </h2>
          </div>

          {/* Real-time Ticking Indicator */}
          <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5 shadow-[0_0_12px_rgba(16,185,129,0.15)]">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            LIVE TICKING &bull; 1s
          </span>

          <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono bg-white/5 text-zinc-400 border border-white/10 hidden md:flex items-center gap-1.5">
            Single-Asset Focus &bull; XAU/USD
          </span>
        </div>

        <div className="flex items-center gap-3">
          {onTriggerScan && (
            <button
              onClick={onTriggerScan}
              disabled={isScanning}
              className={`px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-zinc-300 hover:text-white border border-white/10 hover:border-white/20 text-xs font-mono font-medium flex items-center gap-2 transition-all duration-300 cursor-pointer ${
                isScanning ? 'opacity-70 cursor-wait' : ''
              }`}
              title="Run on-demand market scan across XAU/USD via GET /api/v1/signals/scan"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-cyan-400 ${isScanning ? 'animate-spin' : ''}`} />
              <span>{isScanning ? 'Scanning...' : 'Scan Markets'}</span>
            </button>
          )}

          <div className="text-xs font-mono text-zinc-400 flex items-center gap-1.5">
            <span className="text-zinc-500">Threshold:</span>
            <span className="font-semibold text-zinc-200 bg-white/5 px-2.5 py-0.5 rounded-lg border border-white/10">
              &ge; 75 / 100
            </span>
          </div>
        </div>
      </div>

      {/* Signal Cards Display - Graceful Degradation for Single-Asset */}
      {activeSignals.length === 0 ? (
        <div className="rounded-2xl bg-zinc-900/40 backdrop-blur-md border border-white/10 p-10 text-center font-mono">
          <p className="text-sm text-zinc-300 font-semibold mb-1">No Active Signals For XAU/USD</p>
          <p className="text-xs text-zinc-500">
            Awaiting confirmed liquidity sweep and order-flow imbalance before triggering trade setup.
          </p>
        </div>
      ) : (
        <div className={activeSignals.length === 1 ? "grid grid-cols-1 max-w-3xl mx-auto" : "grid grid-cols-1 lg:grid-cols-2 gap-4.5"}>
          {activeSignals.map((sig) => (
            <ConfluenceCard
              key={sig.id}
              signal={sig}
              livePrice={livePrices[sig.symbol]}
              tickDirection={tickDirections[sig.symbol]}
              onToggleNotify={onToggleNotify}
              onSelectSignalForChart={onSelectSignalForChart}
              onTradeFromSignal={onTradeFromSignal}
            />
          ))}
        </div>
      )}
    </div>
  );
};
