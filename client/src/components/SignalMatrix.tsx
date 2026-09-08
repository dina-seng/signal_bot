import React from 'react';
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
} from 'lucide-react';
import { TradeSignal, PairSymbol } from '../types';
import { formatPrice } from '../utils/formatters';

interface SignalMatrixProps {
  signals: TradeSignal[];
  livePrices?: Record<string, number>;
  isLoading?: boolean;
  onToggleNotify: (id: string, symbol: PairSymbol, currentNotify: boolean) => void;
  onSelectSignalForChart?: (symbol: PairSymbol) => void;
  onTriggerScan?: () => void;
}

export const SignalMatrix: React.FC<SignalMatrixProps> = ({
  signals,
  livePrices = {},
  isLoading = false,
  onToggleNotify,
  onSelectSignalForChart,
  onTriggerScan,
}) => {
  return (
    <div className="space-y-4">
      {/* Header bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-white">Signal Matrix</h2>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-[#00ff88]/15 text-[#00ff88] border border-[#00ff88]/30 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-[#00ff88] animate-pulse" />
              Live Backend Scans
            </span>
          </div>
          <p className="text-xs text-slate-400 font-mono">
            Smart Money Concepts confluence engine scanning Market Structure (BOS/CHOCH), sweeps, and momentum
          </p>
        </div>

        <div className="flex items-center gap-2">
          {onTriggerScan && (
            <button
              onClick={onTriggerScan}
              className="px-2.5 py-1 rounded bg-[#181824] hover:bg-[#202030] text-slate-300 hover:text-white border border-[#1e1e2d] text-xs font-mono font-semibold flex items-center gap-1.5 transition-all cursor-pointer"
              title="Run on-demand market scan across pairs"
            >
              <Search className="w-3 h-3 text-cyan-400" />
              <span>Scan Markets</span>
            </button>
          )}

          <div className="text-xs font-mono text-slate-400 flex items-center gap-1.5">
            <span>Min Setup Threshold:</span>
            <span className="font-bold text-slate-200 bg-[#181824] px-2 py-0.5 rounded border border-[#1e1e2d]">
              75 / 100
            </span>
          </div>
        </div>
      </div>

      {/* 4 Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {signals.map((sig) => {
          const isBuy = sig.direction === 'BUY';
          const isSell = sig.direction === 'SELL';
          const hasSetup = sig.hasActiveSignal && (isBuy || isSell);
          const livePrice = livePrices[sig.symbol] || sig.currentPrice;

          return (
            <div
              key={sig.id || sig.symbol}
              className={`relative rounded-xl p-4 bg-[#12121a] border transition-all duration-300 hover:-translate-y-1 shadow-terminal flex flex-col justify-between ${
                hasSetup
                  ? isBuy
                    ? 'border-[#00ff88]/40 hover:border-[#00ff88]/70 hover:shadow-buy-glow'
                    : 'border-[#ff3366]/40 hover:border-[#ff3366]/70 hover:shadow-sell-glow'
                  : 'border-[#1e1e2d] hover:border-[#2a2a3e]'
              }`}
            >
              {/* Top Row: Symbol, Timeframe & Direction Badge */}
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-base font-mono font-black text-white tracking-wide">
                      {sig.symbol}
                    </span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-[#181824] text-slate-400 border border-[#1e1e2d]">
                      {sig.timeframe || '15m'}
                    </span>
                  </div>

                  {/* BUY / SELL or SCANNING Badge */}
                  {hasSetup ? (
                    <div
                      className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-mono font-bold tracking-wider uppercase border ${
                        isBuy
                          ? 'bg-[#00ff88]/15 text-[#00ff88] border-[#00ff88]/40 shadow-[0_0_10px_rgba(0,255,136,0.25)]'
                          : 'bg-[#ff3366]/15 text-[#ff3366] border-[#ff3366]/40 shadow-[0_0_10px_rgba(255,51,102,0.25)]'
                      }`}
                    >
                      {isBuy ? (
                        <TrendingUp className="w-3.5 h-3.5" />
                      ) : (
                        <TrendingDown className="w-3.5 h-3.5" />
                      )}
                      <span>{sig.direction}</span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-[#181824] text-slate-400 border border-[#1e1e2d]">
                      <RefreshCw className="w-3 h-3 animate-spin text-cyan-400" />
                      <span>SCANNING</span>
                    </div>
                  )}
                </div>

                {/* Confluence Score Bar or Live Ticker */}
                <div className="mt-3 p-2.5 rounded-lg bg-[#0a0a0f] border border-[#1e1e2d] space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-400 font-mono text-[11px] flex items-center gap-1">
                      <Sparkles className="w-3 h-3 text-cyan-400" />
                      Confluence Score
                    </span>
                    <span
                      className={`font-mono font-bold text-xs ${
                        sig.confluenceScore >= 85
                          ? 'text-[#00ff88]'
                          : sig.confluenceScore >= 75
                          ? 'text-cyan-400'
                          : 'text-slate-400'
                      }`}
                    >
                      {hasSetup ? `${sig.confluenceScore} / 100` : 'Evaluating...'}
                    </span>
                  </div>

                  <div className="w-full bg-[#181824] rounded-full h-1.5 overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        hasSetup
                          ? isBuy
                            ? 'bg-[#00ff88]'
                            : 'bg-[#ff3366]'
                          : 'bg-slate-700 animate-pulse'
                      }`}
                      style={{ width: `${Math.max(sig.confluenceScore || 20, 10)}%` }}
                    />
                  </div>
                </div>

                {/* Levels Display (Entry, SL, TP1, TP2) */}
                {hasSetup ? (
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs font-mono">
                    {/* Entry */}
                    <div className="p-2 rounded bg-[#181824]/80 border border-[#1e1e2d]">
                      <span className="text-[10px] text-slate-500 uppercase block">Entry Level</span>
                      <span className="font-bold text-slate-200">
                        {formatPrice(sig.symbol, sig.entryPrice)}
                      </span>
                    </div>

                    {/* Stop Loss */}
                    <div className="p-2 rounded bg-[#181824]/80 border border-[#1e1e2d]">
                      <span className="text-[10px] text-[#ff3366] uppercase block flex items-center gap-0.5">
                        <Shield className="w-2.5 h-2.5" /> SL {sig.pipsAtRisk ? `(${sig.pipsAtRisk}p)` : ''}
                      </span>
                      <span className="font-bold text-[#ff3366]">
                        {formatPrice(sig.symbol, sig.stopLoss)}
                      </span>
                    </div>

                    {/* Take Profit 1 */}
                    <div className="p-2 rounded bg-[#181824]/80 border border-[#1e1e2d]">
                      <span className="text-[10px] text-[#00ff88] uppercase block flex items-center gap-0.5">
                        <Target className="w-2.5 h-2.5" /> TP1 (50%)
                      </span>
                      <span className="font-bold text-[#00ff88]">
                        {formatPrice(sig.symbol, sig.takeProfit1)}
                      </span>
                    </div>

                    {/* Take Profit 2 */}
                    <div className="p-2 rounded bg-[#181824]/80 border border-[#1e1e2d]">
                      <span className="text-[10px] text-cyan-400 uppercase block flex items-center gap-0.5">
                        <Target className="w-2.5 h-2.5" /> TP2 (Runner)
                      </span>
                      <span className="font-bold text-cyan-400">
                        {formatPrice(sig.symbol, sig.takeProfit2)}
                      </span>
                    </div>
                  </div>
                ) : (
                  /* When no active setup is available */
                  <div className="mt-3 p-3 rounded bg-[#181824]/40 border border-[#1e1e2d] text-center space-y-1 font-mono">
                    <div className="text-[11px] text-slate-400">Current Market Price:</div>
                    <div className="text-base font-bold text-slate-200">
                      {livePrice ? formatPrice(sig.symbol, livePrice) : 'Fetching...'}
                    </div>
                    <div className="text-[10px] text-slate-500 italic">
                      No high-probability setup (&ge;75%) detected. Scanning order flow...
                    </div>
                  </div>
                )}

                {/* Risk / Reward & Setup Thesis */}
                <div className="mt-2.5 px-2.5 py-2 rounded bg-[#0d0d14] border border-[#1e1e2d] text-[11px] space-y-1">
                  <div className="flex items-center justify-between font-mono text-slate-400">
                    <span>Risk-to-Reward:</span>
                    <span className="font-bold text-slate-200 text-xs">
                      {sig.riskRewardRatio || '1:2.0'}
                    </span>
                  </div>
                  <p className="text-[10px] text-slate-400 line-clamp-2 italic leading-relaxed">
                    {sig.setupReason || 'Monitoring fractal swings, fair value gaps, and liquidity sweeps.'}
                  </p>
                </div>
              </div>

              {/* Bottom Actions: Notify Toggle & View Chart */}
              <div className="mt-4 pt-3 border-t border-[#1e1e2d] flex items-center justify-between gap-2">
                {/* Notify on Signal Toggle */}
                <button
                  onClick={() => onToggleNotify(sig.id, sig.symbol, sig.notifyEnabled)}
                  className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-mono font-medium transition-all cursor-pointer ${
                    sig.notifyEnabled
                      ? 'bg-[#00ff88]/15 text-[#00ff88] border border-[#00ff88]/40 shadow-[0_0_8px_rgba(0,255,136,0.2)]'
                      : 'bg-[#181824] text-slate-400 border border-[#1e1e2d] hover:text-slate-200'
                  }`}
                  title={sig.notifyEnabled ? 'Alerts active for this pair' : 'Click to enable alerts for this pair'}
                >
                  {sig.notifyEnabled ? (
                    <Bell className="w-3.5 h-3.5 text-[#00ff88] fill-[#00ff88]/20" />
                  ) : (
                    <BellOff className="w-3.5 h-3.5 text-slate-500" />
                  )}
                  <span>{sig.notifyEnabled ? 'Notify ON' : 'Notify OFF'}</span>
                </button>

                {/* Inspect on Chart Button */}
                {onSelectSignalForChart && (
                  <button
                    onClick={() => onSelectSignalForChart(sig.symbol)}
                    className="flex items-center gap-1 text-[11px] font-mono text-slate-400 hover:text-cyan-400 hover:underline transition-colors cursor-pointer"
                  >
                    <span>Inspect</span>
                    <ArrowRight className="w-3 h-3" />
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
