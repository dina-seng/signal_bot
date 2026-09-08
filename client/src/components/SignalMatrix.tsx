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
  Layers,
} from 'lucide-react';
import { TradeSignal, PairSymbol } from '../types';

interface SignalMatrixProps {
  signals: TradeSignal[];
  onToggleNotify: (id: string, symbol: PairSymbol, currentNotify: boolean) => void;
  onSelectSignalForChart?: (symbol: PairSymbol) => void;
}

export const SignalMatrix: React.FC<SignalMatrixProps> = ({
  signals,
  onToggleNotify,
  onSelectSignalForChart,
}) => {
  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-white">Signal Matrix</h2>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-[#00ff88]/15 text-[#00ff88] border border-[#00ff88]/30">
              Live MTF Scans
            </span>
          </div>
          <p className="text-xs text-slate-400 font-mono">
            Algorithmic confluence setups based on Market Structure (BOS/CHOCH), SMC Liquidity, and Indicators
          </p>
        </div>
        <div className="text-xs font-mono text-slate-400 flex items-center gap-2">
          <span>Min Confluence Threshold:</span>
          <span className="font-bold text-slate-200 bg-[#181824] px-2 py-0.5 rounded border border-[#1e1e2d]">
            75 / 100
          </span>
        </div>
      </div>

      {/* 4 Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {signals.map((sig) => {
          const isBuy = sig.direction === 'BUY';
          const isGold = sig.symbol === 'XAU/USD';

          return (
            <div
              key={sig.id}
              className={`relative rounded-xl p-4 bg-[#12121a] border transition-all duration-300 hover:-translate-y-1 shadow-terminal flex flex-col justify-between ${
                isBuy
                  ? 'border-[#00ff88]/30 hover:border-[#00ff88]/60 hover:shadow-buy-glow'
                  : 'border-[#ff3366]/30 hover:border-[#ff3366]/60 hover:shadow-sell-glow'
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
                      {sig.timeframe}
                    </span>
                  </div>

                  {/* BUY / SELL Badge */}
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
                </div>

                {/* Confluence Score Bar */}
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
                          : 'text-amber-400'
                      }`}
                    >
                      {sig.confluenceScore} / 100
                    </span>
                  </div>
                  <div className="w-full bg-[#181824] rounded-full h-1.5 overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        isBuy ? 'bg-[#00ff88]' : 'bg-[#ff3366]'
                      }`}
                      style={{ width: `${sig.confluenceScore}%` }}
                    />
                  </div>
                </div>

                {/* Levels Display (Entry, SL, TP1, TP2) */}
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs font-mono">
                  {/* Entry */}
                  <div className="p-2 rounded bg-[#181824]/80 border border-[#1e1e2d]">
                    <span className="text-[10px] text-slate-500 uppercase block">Entry Level</span>
                    <span className="font-bold text-slate-200">
                      {isGold ? sig.entryPrice.toFixed(2) : sig.entryPrice.toFixed(5)}
                    </span>
                  </div>

                  {/* Stop Loss */}
                  <div className="p-2 rounded bg-[#181824]/80 border border-[#1e1e2d]">
                    <span className="text-[10px] text-[#ff3366] uppercase block flex items-center gap-0.5">
                      <Shield className="w-2.5 h-2.5" /> SL ({sig.pipsAtRisk}p)
                    </span>
                    <span className="font-bold text-[#ff3366]">
                      {isGold ? sig.stopLoss.toFixed(2) : sig.stopLoss.toFixed(5)}
                    </span>
                  </div>

                  {/* Take Profit 1 */}
                  <div className="p-2 rounded bg-[#181824]/80 border border-[#1e1e2d]">
                    <span className="text-[10px] text-[#00ff88] uppercase block flex items-center gap-0.5">
                      <Target className="w-2.5 h-2.5" /> TP1 (50%)
                    </span>
                    <span className="font-bold text-[#00ff88]">
                      {isGold ? sig.takeProfit1.toFixed(2) : sig.takeProfit1.toFixed(5)}
                    </span>
                  </div>

                  {/* Take Profit 2 */}
                  <div className="p-2 rounded bg-[#181824]/80 border border-[#1e1e2d]">
                    <span className="text-[10px] text-cyan-400 uppercase block flex items-center gap-0.5">
                      <Target className="w-2.5 h-2.5" /> TP2 (Runner)
                    </span>
                    <span className="font-bold text-cyan-400">
                      {isGold ? sig.takeProfit2.toFixed(2) : sig.takeProfit2.toFixed(5)}
                    </span>
                  </div>
                </div>

                {/* Risk / Reward & Rationale */}
                <div className="mt-2.5 px-2.5 py-2 rounded bg-[#0d0d14] border border-[#1e1e2d] text-[11px] space-y-1">
                  <div className="flex items-center justify-between font-mono text-slate-400">
                    <span>Risk-to-Reward:</span>
                    <span className="font-bold text-slate-200 text-xs">{sig.riskRewardRatio}</span>
                  </div>
                  <p className="text-[10px] text-slate-400 line-clamp-2 italic leading-relaxed">
                    "{sig.setupReason}"
                  </p>
                </div>
              </div>

              {/* Bottom Actions: Notify Toggle & View Chart */}
              <div className="mt-4 pt-3 border-t border-[#1e1e2d] flex items-center justify-between gap-2">
                {/* Notify on Signal Toggle */}
                <button
                  onClick={() => onToggleNotify(sig.id, sig.symbol, sig.notifyEnabled)}
                  className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-mono font-medium transition-all ${
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

                {/* View on Chart Button */}
                {onSelectSignalForChart && (
                  <button
                    onClick={() => onSelectSignalForChart(sig.symbol)}
                    className="flex items-center gap-1 text-[11px] font-mono text-slate-400 hover:text-cyan-400 hover:underline transition-colors"
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
