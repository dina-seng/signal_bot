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
  isScanning?: boolean;
  onToggleNotify: (id: string, symbol: PairSymbol, currentNotify: boolean) => void;
  onSelectSignalForChart?: (symbol: PairSymbol) => void;
  onTriggerScan?: () => void;
  onTradeFromSignal?: (signal: TradeSignal) => void;
}

export const SignalMatrix: React.FC<SignalMatrixProps> = ({
  signals,
  livePrices = {},
  isLoading = false,
  isScanning = false,
  onToggleNotify,
  onSelectSignalForChart,
  onTriggerScan,
  onTradeFromSignal,
}) => {
  return (
    <div className="space-y-3">
      {/* Header bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <h2 className="text-sm font-semibold text-white tracking-wide uppercase font-mono">
            Confluence Matrix
          </h2>
          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#161922] text-slate-400 border border-[#1d2230] flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-[#00e676]" />
            Multi-Timeframe 15m / 30m / 1H
          </span>
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
          const livePrice = livePrices[sig.symbol] || sig.currentPrice;

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

                  {/* BUY / SELL or SCANNING Badge */}
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

                {/* Levels Display (Entry, SL, TP1, TP2) */}
                {hasSetup ? (
                  <div className="mt-2.5 grid grid-cols-2 gap-1.5 text-[11px]">
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
                ) : (
                  /* When no active setup is available */
                  <div className="mt-2.5 p-2 rounded bg-[#0a0b10] border border-[#1d2230] text-center space-y-0.5">
                    <div className="text-[10px] text-slate-500">Live Price:</div>
                    <div className="text-sm font-bold text-slate-200">
                      {livePrice ? formatPrice(sig.symbol, livePrice) : 'Fetching...'}
                    </div>
                    <div className="text-[9px] text-slate-500">
                      Awaiting high-confluence setup (&ge;75%)
                    </div>
                  </div>
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
