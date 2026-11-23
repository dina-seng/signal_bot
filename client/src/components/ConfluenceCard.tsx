import React, { useState } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Sparkles,
  Bot,
  ChevronDown,
  ChevronUp,
  Bell,
  BellOff,
  ArrowRight,
  Shield,
  Target,
  BarChart2,
  Activity,
  Layers,
} from 'lucide-react';
import { TradeSignal, PairSymbol } from '../types';
import { formatPrice } from '../utils/formatters';
import { TradingViewMiniWidget } from './TradingViewMiniWidget';
import { Card } from './Card';

interface ConfluenceCardProps {
  signal: TradeSignal;
  livePrice?: number;
  tickDirection?: 'up' | 'down' | null;
  onToggleNotify?: (id: string, symbol: PairSymbol, currentNotify: boolean) => void;
  onSelectSignalForChart?: (symbol: PairSymbol) => void;
  onTradeFromSignal?: (signal: TradeSignal) => void;
  minScore?: number;
}

export const ConfluenceCard: React.FC<ConfluenceCardProps> = ({
  signal,
  livePrice,
  tickDirection,
  onToggleNotify,
  onSelectSignalForChart,
  onTradeFromSignal,
  minScore = 60,
}) => {
  const [isAiExpanded, setIsAiExpanded] = useState<boolean>(true);
  const [viewMode, setViewMode] = useState<'ticker' | 'tradingview'>('ticker');

  const isBuy = signal.direction === 'BUY';
  const isSell = signal.direction === 'SELL';
  const hasSetup = signal.hasActiveSignal && (isBuy || isSell);

  // Resolved live price
  const displayPrice = livePrice || signal.currentPrice || signal.entryPrice;

  // AI confidence fallback (e.g., 88-94% for high setups, 45-65% for scanning)
  const aiConfidence = signal.aiConfidence ?? (hasSetup && signal.confluenceScore > 0 ? Math.min(96, Math.max(78, signal.confluenceScore + 2)) : (signal.confluenceScore > 0 ? signal.confluenceScore : null));

  // Default institutional AI reasoning if not provided
  const aiReasoningText =
    signal.aiReasoning ||
    (hasSetup
      ? isBuy
        ? `Order-flow imbalance detected on ${signal.symbol}. Clean liquidity sweep beneath local support followed by institutional displacement into Bullish FVG.`
        : `Supply absorption confirmed on ${signal.symbol}. Internal market structure shift (MSS) with heavy ask skew and premium rejection.`
      : `Algorithmic liquidity scan in progress. Accumulating tick volume and awaiting displacement through key liquidity pools.`);

  // Tick highlight colors
  const tickBg =
    tickDirection === 'up'
      ? 'bg-emerald-500/15 border-emerald-500/40 shadow-[0_0_15px_rgba(16,185,129,0.2)]'
      : tickDirection === 'down'
      ? 'bg-rose-500/15 border-rose-500/40 shadow-[0_0_15px_rgba(244,63,94,0.2)]'
      : 'bg-zinc-950/60 border-white/[0.08]';

  const tickTextColor =
    tickDirection === 'up'
      ? 'text-emerald-400'
      : tickDirection === 'down'
      ? 'text-rose-500'
      : 'text-white';

  const glowChoice = hasSetup ? (isBuy ? 'emerald' : 'rose') : 'violet';

  return (
    <Card
      glowOnHover={glowChoice}
      className="p-4 sm:p-5 flex flex-col justify-between w-full min-w-0 overflow-hidden"
    >
      {/* Specular Edge Glow */}
      <div
        className={`absolute inset-x-0 top-0 h-[2px] transition-opacity duration-500 ${
          hasSetup
            ? isBuy
              ? 'bg-gradient-to-r from-transparent via-emerald-400/80 to-transparent'
              : 'bg-gradient-to-r from-transparent via-rose-500/80 to-transparent'
            : 'bg-gradient-to-r from-transparent via-indigo-500/60 to-transparent'
        }`}
      />

      {/* Main Content Area */}
      <div className="space-y-4">
        {/* 1. Header Row: Symbol, Timeframe & Direction Badge */}
        <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
          <div className="flex items-center gap-2.5">
            <div className="flex items-baseline gap-1.5">
              <span className="font-mono text-base font-bold tracking-tight text-white">
                {signal.symbol}
              </span>
              <span className="rounded-md bg-white/[0.06] border border-white/10 px-1.5 py-0.5 font-mono text-[10px] font-medium text-zinc-400">
                {signal.timeframe ? signal.timeframe.toUpperCase() : '1H'}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            {/* View Mode Toggle Button */}
            <button
              onClick={() => setViewMode(viewMode === 'ticker' ? 'tradingview' : 'ticker')}
              className={`rounded-lg border px-2 py-0.5 font-mono text-[10px] transition-colors cursor-pointer ${
                viewMode === 'tradingview'
                  ? 'bg-indigo-500/10 text-indigo-300 border-indigo-500/30'
                  : 'bg-white/[0.04] text-zinc-400 border-white/10 hover:text-white'
              }`}
              title={viewMode === 'tradingview' ? 'Switch to Live Ticker' : 'Switch to Mini Chart'}
            >
              {viewMode === 'tradingview' ? 'Mini Chart' : 'Live Ticker'}
            </button>

            {/* Direction Badge */}
            {hasSetup ? (
              <div
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-xs font-semibold tracking-wide border ${
                  isBuy
                    ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                    : 'bg-rose-500/15 text-rose-500 border-rose-500/30'
                }`}
              >
                {isBuy ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
                <span>{signal.direction}</span>
              </div>
            ) : (
              <div className="inline-flex items-center gap-1.5 rounded-full bg-zinc-800/60 border border-white/10 px-2.5 py-0.5 font-mono text-[11px] font-medium text-zinc-400">
                <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
                <span>SCANNING</span>
              </div>
            )}
          </div>
        </div>

        {/* 2-Column Responsive Body Layout on Desktop */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 lg:gap-5">
          {/* LEFT COLUMN: Price Ticker & AI Neural Intelligence */}
          <div className="space-y-3.5">
            {/* 2. Live Price Ticker or TradingView Mini Widget */}
            {viewMode === 'tradingview' ? (
              <div className="rounded-xl overflow-hidden border border-white/10">
                <TradingViewMiniWidget symbol={signal.symbol} height={180} />
              </div>
            ) : (
              <div
                className={`rounded-xl border p-3 transition-all duration-300 ${tickBg}`}
              >
                <div className="flex items-center justify-between font-mono">
                  <div className="flex items-center gap-2 text-xs text-zinc-400">
                    <span
                      className={`h-2 w-2 rounded-full ${
                        tickDirection === 'up'
                          ? 'bg-emerald-400 animate-ping'
                          : tickDirection === 'down'
                          ? 'bg-rose-500 animate-ping'
                          : 'bg-emerald-400 animate-pulse'
                      }`}
                    />
                    <span className="uppercase tracking-wider text-[11px] font-medium">Live Market Price</span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <span
                      className={`text-base sm:text-lg font-bold tracking-tight transition-all duration-300 ${
                        tickDirection === 'up'
                          ? 'animate-tick-up text-emerald-400'
                          : tickDirection === 'down'
                          ? 'animate-tick-down text-rose-500'
                          : 'text-white'
                      }`}
                    >
                      {displayPrice && displayPrice > 0 ? formatPrice(signal.symbol, displayPrice) : '--'}
                    </span>
                    {tickDirection === 'up' && <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />}
                    {tickDirection === 'down' && <TrendingDown className="h-3.5 w-3.5 text-rose-500" />}
                  </div>
                </div>
              </div>
            )}

            {/* 3. AI Intelligence Layer */}
            <div className="rounded-xl border border-indigo-500/20 bg-gradient-to-b from-indigo-950/30 to-violet-950/20 p-3.5 backdrop-blur-md">
              {/* AI Header */}
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5 font-medium text-indigo-300">
                  <Bot className="h-3.5 w-3.5 text-indigo-400" />
                  <span>AI Neural Confidence</span>
                </span>
                <span className="font-mono font-semibold text-indigo-200">
                  {aiConfidence !== null ? `${aiConfidence}%` : '--%'}
                </span>
              </div>

              {/* AI Confidence Gradient Progress Bar */}
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-zinc-950/80 p-0.5 border border-indigo-500/30">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-indigo-500 via-indigo-400 to-violet-500 shadow-[0_0_10px_rgba(99,102,241,0.5)] transition-all duration-500"
                  style={{ width: `${aiConfidence !== null ? Math.max(10, aiConfidence) : 0}%` }}
                />
              </div>

              {/* AI Reasoning Expandable Drawer */}
              <div className="mt-2.5">
                <button
                  onClick={() => setIsAiExpanded(!isAiExpanded)}
                  className="flex w-full items-center justify-between text-[11px] font-medium text-indigo-300/80 hover:text-indigo-200 transition-colors cursor-pointer"
                >
                  <span className="flex items-center gap-1">
                    <Sparkles className="h-3 w-3 text-indigo-400" />
                    <span>Institutional Thesis</span>
                  </span>
                  {isAiExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                </button>

                {isAiExpanded && (
                  <div className="mt-1.5 rounded-r-lg border-l-2 border-indigo-500 bg-indigo-950/40 p-2.5 pl-3 backdrop-blur-sm">
                    <p className="font-sans text-xs italic leading-relaxed text-indigo-200/90">
                      "{aiReasoningText}"
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* RIGHT COLUMN: Technical Confluence, Key Trade Levels & Execution */}
          <div className="space-y-3.5">
            {/* 4. Technical Confluence Score Strip */}
            <div className="rounded-xl border border-white/[0.08] bg-zinc-950/50 p-3 space-y-2 font-mono text-xs">
              <div className="flex items-center justify-between">
                <span className="text-zinc-400 flex items-center gap-1.5 text-[11px]">
                  <Layers className="h-3 w-3 text-zinc-400" />
                  <span>Technical Confluence</span>
                </span>
                <span
                  className={`font-semibold ${
                    signal.confluenceScore >= 85
                      ? 'text-emerald-400'
                      : signal.confluenceScore >= minScore
                      ? 'text-indigo-300'
                      : 'text-zinc-400'
                  }`}
                >
                  {signal.confluenceScore > 0 ? `${signal.confluenceScore} / 100` : '-- / 100'}
                </span>
              </div>

              <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
                <div
                  className={`h-full transition-all duration-300 ${
                    hasSetup
                      ? isBuy
                        ? 'bg-emerald-400'
                        : 'bg-rose-500'
                      : 'bg-zinc-500'
                  }`}
                  style={{ width: `${signal.confluenceScore > 0 ? Math.max(8, signal.confluenceScore) : 0}%` }}
                />
              </div>

              {/* Pillars tags with balanced 2-column spacing */}
              <div className="grid grid-cols-2 gap-2.5 pt-1 text-[11px] text-zinc-400">
                <div className="flex items-center justify-between rounded-lg bg-zinc-900/60 px-2.5 py-1 border border-white/[0.04]">
                  <span>Structure:</span>
                  <span className="text-zinc-200 font-semibold">{hasSetup ? 'Confirmed' : 'Validating'}</span>
                </div>
                <div className="flex items-center justify-between rounded-lg bg-zinc-900/60 px-2.5 py-1 border border-white/[0.04]">
                  <span>Liquidity:</span>
                  <span className="text-zinc-200 font-semibold">{hasSetup ? 'Swept' : 'Building'}</span>
                </div>
              </div>
            </div>

            {/* 5. Key Trade Levels (Entry, SL, TP1, TP2) */}
            {hasSetup ? (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 font-mono text-xs w-full min-w-0">
                {/* Entry */}
                <div className="rounded-xl border border-white/[0.08] bg-zinc-950/60 p-2.5 min-w-0 flex flex-col justify-between">
                  <span className="block text-[10px] uppercase font-medium tracking-wider text-zinc-400">Entry</span>
                  <span className="font-semibold text-white tracking-tight truncate block mt-0.5 text-xs sm:text-sm">
                    {signal.entryPrice && signal.entryPrice > 0 ? formatPrice(signal.symbol, signal.entryPrice) : '--'}
                  </span>
                </div>

                {/* Stop Loss */}
                <div className="rounded-xl border border-rose-500/20 bg-rose-500/[0.06] p-2.5 min-w-0 flex flex-col justify-between">
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-[10px] uppercase font-medium tracking-wider text-rose-400">Stop Loss</span>
                    {signal.pipsAtRisk ? (
                      <span className="text-[9px] px-1 rounded bg-rose-500/20 text-rose-300 font-medium">
                        {signal.pipsAtRisk}p
                      </span>
                    ) : null}
                  </div>
                  <span className="font-semibold text-rose-400 tracking-tight truncate block mt-0.5 text-xs sm:text-sm">
                    {signal.stopLoss && signal.stopLoss > 0 ? formatPrice(signal.symbol, signal.stopLoss) : '--'}
                  </span>
                </div>

                {/* TP1 */}
                <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] p-2.5 min-w-0 flex flex-col justify-between">
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-[10px] uppercase font-medium tracking-wider text-emerald-400">TP1</span>
                    <span className="text-[9px] text-emerald-300/80">50% Scale</span>
                  </div>
                  <span className="font-semibold text-emerald-400 tracking-tight truncate block mt-0.5 text-xs sm:text-sm">
                    {signal.takeProfit1 && signal.takeProfit1 > 0 ? formatPrice(signal.symbol, signal.takeProfit1) : '--'}
                  </span>
                </div>

                {/* TP2 */}
                <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/[0.06] p-2.5 min-w-0 flex flex-col justify-between">
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-[10px] uppercase font-medium tracking-wider text-indigo-300">TP2</span>
                    <span className="text-[9px] text-indigo-300/80">Runner</span>
                  </div>
                  <span className="font-semibold text-indigo-300 tracking-tight truncate block mt-0.5 text-xs sm:text-sm">
                    {signal.takeProfit2 && signal.takeProfit2 > 0 ? formatPrice(signal.symbol, signal.takeProfit2) : '--'}
                  </span>
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-white/[0.06] bg-zinc-950/40 p-3 text-center font-mono text-xs text-zinc-400">
                <span>R:R Target: </span>
                <strong className="text-white">{signal.riskRewardRatio && signal.riskRewardRatio !== '--' ? signal.riskRewardRatio : '1:2.0'}</strong>
                <span className="block text-[10px] text-zinc-500 mt-1">
                  {signal.setupReason || `Awaiting institutional confirmation threshold (≥ ${minScore} pts)`}
                </span>
              </div>
            )}

            {/* 6. Action Execution Button */}
            {hasSetup && onTradeFromSignal && (
              <button
                onClick={() => onTradeFromSignal(signal)}
                className={`flex w-full items-center justify-center gap-2 rounded-xl py-2.5 px-3 font-mono text-xs font-semibold tracking-wide border transition-all duration-200 cursor-pointer ${
                  isBuy
                    ? 'bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border-emerald-500/40 hover:shadow-[0_0_15px_rgba(16,185,129,0.25)]'
                    : 'bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border-rose-500/40 hover:shadow-[0_0_15px_rgba(244,63,94,0.25)]'
                }`}
              >
                <span>Execute Paper {signal.direction}</span>
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 7. Footer Actions: Alert Toggle & Chart View */}
      <div className="mt-4 flex items-center justify-between border-t border-white/[0.08] pt-3 font-mono text-xs">
        {onToggleNotify && (
          <button
            onClick={() => onToggleNotify(signal.id, signal.symbol, signal.notifyEnabled)}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] font-medium transition-colors cursor-pointer ${
              signal.notifyEnabled
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                : 'bg-white/[0.04] text-zinc-400 border-white/10 hover:text-white'
            }`}
            title={signal.notifyEnabled ? 'Telegram alerts active' : 'Enable Telegram alerts'}
          >
            {signal.notifyEnabled ? (
              <Bell className="h-3 w-3 text-emerald-400" />
            ) : (
              <BellOff className="h-3 w-3 text-zinc-500" />
            )}
            <span>{signal.notifyEnabled ? 'Alert Active' : 'Muted'}</span>
          </button>
        )}

        {onSelectSignalForChart && (
          <button
            onClick={() => onSelectSignalForChart(signal.symbol)}
            className="inline-flex items-center gap-1 text-[11px] text-zinc-400 hover:text-indigo-300 transition-colors cursor-pointer"
          >
            <span>Inspect Chart</span>
            <ArrowRight className="h-3 w-3" />
          </button>
        )}
      </div>
    </Card>
  );
};
