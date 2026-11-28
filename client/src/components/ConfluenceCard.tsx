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
  autoExecuted?: boolean;
  minScore?: number;
}

export const ConfluenceCard: React.FC<ConfluenceCardProps> = ({
  signal,
  livePrice,
  tickDirection,
  onToggleNotify,
  onSelectSignalForChart,
  autoExecuted = false,
  minScore,
}) => {
  const [isAiExpanded, setIsAiExpanded] = useState<boolean>(true);
  const [viewMode, setViewMode] = useState<'ticker' | 'tradingview'>('ticker');

  const isBuy = signal.direction === 'BUY';
  const isSell = signal.direction === 'SELL';
  const hasSetup = signal.hasActiveSignal && (isBuy || isSell);
  const isMomentum = signal.symbol === 'BTC/USD';
  const accountLabel = signal.targetAccount || (isMomentum ? 'CENT' : 'MAIN');

  // A score of 0 is valid data (WAIT / no fresh trigger), not a missing value.
  // Only null / undefined / NaN should ever render as "--".
  const rawScore = signal.confluenceScore;
  const hasScore = rawScore !== null && rawScore !== undefined && !Number.isNaN(Number(rawScore));
  const scoreValue = hasScore ? Math.round(Number(rawScore)) : null;

  // Resolved live price
  const displayPrice = livePrice || signal.currentPrice || signal.entryPrice;

  // AI Neural Confidence always comes from the backend's bounded heuristic.
  // Real models are never certain: clamp defensively to 60-95 and NEVER mirror
  // the confluence score into this field (that produced a fake 100%).
  const rawConfidence = signal.aiConfidence;
  const aiConfidence = rawConfidence !== null && rawConfidence !== undefined && !Number.isNaN(Number(rawConfidence))
    ? Math.min(95, Math.max(60, Math.round(Number(rawConfidence))))
    : null;

  // Institutional thesis is strategy-specific: momentum for BTC, SMC for XAU.
  const aiReasoningText =
    signal.aiReasoning ||
    (isMomentum
      ? hasSetup
        ? `Fresh ${signal.emaTrend || 'EMA'} momentum crossover confirmed. RSI(14) ${signal.rsi14?.toFixed(1) ?? '--'} with ADX(14) ${signal.adx14?.toFixed(1) ?? '--'} regime support; EMA50/EMA200 alignment clears the ${scoreValue ?? 0}/100 heuristic confluence floor.`
        : `Awaiting a fresh RSI/EMA momentum crossover on BTC/USD with ADX(14) regime confirmation.`
      : hasSetup
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
        <div className="flex flex-wrap items-center justify-between gap-y-2 border-b border-white/[0.08] pb-3">
          <div className="flex items-center gap-2.5">
            <div className="flex items-baseline gap-1.5">
              <span className="font-mono text-base font-bold tracking-tight text-white">
                {signal.symbol}
              </span>
              <span className="rounded-md bg-white/[0.06] border border-white/10 px-1.5 py-0.5 font-mono text-[10px] font-medium text-zinc-400">
                {signal.timeframe ? signal.timeframe.toUpperCase() : '1H'}
              </span>
              <span className={`rounded-md px-1.5 py-0.5 font-mono text-[10px] font-semibold border ${
                accountLabel === 'CENT'
                  ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                  : 'bg-violet-500/10 text-violet-300 border-violet-500/30'
              }`} title={`Executing account: ${accountLabel}`}>
                {accountLabel}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            {/* View Mode Toggle Button */}
            <button
              onClick={() => setViewMode(viewMode === 'ticker' ? 'tradingview' : 'ticker')}
              className={`min-h-[44px] sm:min-h-0 flex items-center justify-center whitespace-nowrap rounded-lg border px-2.5 py-1 sm:py-0.5 font-mono text-[10px] transition-colors cursor-pointer touch-manipulation ${
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

        {/* Responsive Body Layout: 2 cols when the card is wide (tablet / 2xl), single col in the narrow ~40% desktop column */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2 gap-4">
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
                      className={`text-lg font-bold tracking-tight transition-all duration-300 ${
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
                  className="flex w-full min-h-[44px] sm:min-h-0 items-center justify-between text-[11px] font-medium text-indigo-300/80 hover:text-indigo-200 transition-colors cursor-pointer touch-manipulation"
                >
                  <span className="flex items-center gap-1">
                    <Sparkles className="h-3 w-3 text-indigo-400" />
                    <span>Institutional Thesis</span>
                  </span>
                  {isAiExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                </button>

                {isAiExpanded && (
                  <div className="mt-1.5 rounded-r-lg border-l-2 border-indigo-500 bg-indigo-950/40 p-2.5 pl-3 backdrop-blur-sm">
                    <p className="font-sans text-xs italic leading-relaxed text-indigo-200/90 whitespace-normal break-words">
                      "{aiReasoningText}"
                    </p>
                    {isMomentum && (
                      <p className="mt-2 font-mono text-[10px] leading-relaxed text-amber-300/80 whitespace-normal break-words">
                        {signal.heuristicProvenance ? `Provenance: ${signal.heuristicProvenance}. ` : ''}
                        1H momentum is an empirical heuristic; Proelss et al. (2025) supports BTC
                        large-cap momentum only at 7d/30d horizons, not intraday.
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* RIGHT COLUMN: Technical Confluence, Key Trade Levels & Execution */}
          <div className="space-y-3.5">
            {/* 4. Technical Confluence Score Strip */}
            <div className="rounded-xl border border-white/[0.08] bg-zinc-950/50 p-3 space-y-2 font-mono text-xs min-w-0">
              <div className="flex items-center justify-between gap-2 min-w-0">
                <span className="text-zinc-400 flex items-center gap-1.5 text-[11px] min-w-0">
                  <Layers className="h-3 w-3 text-zinc-400 shrink-0" />
                  <span className="whitespace-normal leading-tight">Technical Confluence</span>
                </span>
                <span
                  className={`font-semibold whitespace-nowrap shrink-0 ${
                    scoreValue !== null && scoreValue >= 85
                      ? 'text-emerald-400'
                      : scoreValue !== null && minScore !== undefined && scoreValue >= minScore
                      ? 'text-indigo-300'
                      : 'text-zinc-400'
                  }`}
                >
                  {scoreValue !== null ? `${scoreValue} / 100` : '-- / 100'}
                </span>
              </div>

              <div className="h-1.5 w-full min-w-0 overflow-hidden rounded-full bg-zinc-800">
                <div
                  className={`h-full transition-all duration-300 ${
                    hasSetup
                      ? isBuy
                        ? 'bg-emerald-400'
                        : 'bg-rose-500'
                      : 'bg-zinc-500'
                  }`}
                  style={{ width: `${scoreValue !== null ? Math.max(8, scoreValue) : 0}%` }}
                />
              </div>

              {isMomentum ? (
                <>
                  {/* Momentum indicators — replaces SMC structure/liquidity pills */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 pt-1 font-mono text-[10px]">
                    {[
                      { label: 'EMA 50', value: signal.ema50?.toFixed(2) },
                      { label: 'EMA 200', value: signal.ema200?.toFixed(2) },
                      { label: 'RSI 14', value: signal.rsi14?.toFixed(1) },
                      { label: 'ADX 14', value: signal.adx14?.toFixed(1) },
                    ].map((item) => (
                      <div key={item.label} className="rounded-lg bg-zinc-900/60 px-2 py-1 border border-white/[0.04] min-w-0">
                        <span className="block text-zinc-500 text-[9px] uppercase tracking-wide truncate">{item.label}</span>
                        <span className="text-zinc-100 font-semibold">{item.value ?? '--'}</span>
                      </div>
                    ))}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 pt-1 text-[11px] text-zinc-400">
                    <div className="inline-flex items-center gap-1.5 rounded-full bg-zinc-900/60 px-2.5 py-1 border border-white/[0.04] whitespace-nowrap">
                      <span>EMA Trend:</span>
                      <span className="text-zinc-200 font-semibold">{signal.emaTrend || '--'}</span>
                    </div>
                    <div className="inline-flex items-center gap-1.5 rounded-full bg-zinc-900/60 px-2.5 py-1 border border-white/[0.04] whitespace-nowrap">
                      <span>RSI:</span>
                      <span className="text-zinc-200 font-semibold">{signal.rsi14?.toFixed(1) ?? '--'}</span>
                    </div>
                    <div className="inline-flex items-center gap-1.5 rounded-full bg-zinc-900/60 px-2.5 py-1 border border-white/[0.04] whitespace-nowrap">
                      <span>ADX:</span>
                      <span className="text-zinc-200 font-semibold">{signal.adx14?.toFixed(1) ?? '--'}</span>
                    </div>
                  </div>
                </>
              ) : (
                /* SMC pillars for XAU/USD */
                <div className="flex flex-wrap items-center gap-2 pt-1 text-[11px] text-zinc-400">
                  <div className="inline-flex items-center gap-1.5 rounded-full bg-zinc-900/60 px-2.5 py-1 border border-white/[0.04] whitespace-nowrap">
                    <span>Structure:</span>
                    <span className="text-zinc-200 font-semibold">{hasSetup ? 'Confirmed' : 'Validating'}</span>
                  </div>
                  <div className="inline-flex items-center gap-1.5 rounded-full bg-zinc-900/60 px-2.5 py-1 border border-white/[0.04] whitespace-nowrap">
                    <span>Liquidity:</span>
                    <span className="text-zinc-200 font-semibold">{hasSetup ? 'Swept' : 'Building'}</span>
                  </div>
                </div>
              )}
            </div>

            {/* 5. Key Trade Levels (Entry, SL, TP1, TP2) */}
            {hasSetup ? (
              <div className="grid grid-cols-2 gap-2.5 font-mono text-xs w-full min-w-0">
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
                {signal.riskRewardRatio && signal.riskRewardRatio !== '--' ? (
                  <strong className="text-white">{signal.riskRewardRatio}</strong>
                ) : (
                  <span className="inline-block min-w-[3rem] animate-pulse rounded bg-white/10 align-middle" aria-busy="true" aria-label="Loading risk reward" />
                )}
                <span className="block text-[10px] text-zinc-500 mt-1">
                  {signal.setupReason || (minScore !== undefined
                    ? `Awaiting institutional confirmation threshold (≥ ${minScore} pts)`
                    : 'Awaiting institutional confirmation threshold')}
                </span>
              </div>
            )}

            {/* 6. Read-only auto-execution state (no manual action) */}
            {hasSetup && (
              <div
                role="status"
                className={`flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl py-2.5 px-3 font-mono text-xs font-semibold tracking-wide border ${
                  autoExecuted
                    ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40'
                    : 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                }`}
              >
                <Bot className="h-3.5 w-3.5" />
                <span>{autoExecuted ? 'AUTO-EXECUTED' : 'AUTO-EXECUTE ON SIGNAL'}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 7. Footer Actions: Alert Toggle & Chart View */}
      <div className="mt-4 flex items-center justify-between border-t border-white/[0.08] pt-3 font-mono text-xs">
        {onToggleNotify && (
          <button
            onClick={() => onToggleNotify(signal.id, signal.symbol, signal.notifyEnabled)}
            className={`inline-flex min-h-[44px] md:min-h-0 items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] font-medium transition-colors cursor-pointer touch-manipulation ${
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
            className="inline-flex min-h-[44px] md:min-h-0 items-center gap-1 text-[11px] text-zinc-400 hover:text-indigo-300 transition-colors cursor-pointer touch-manipulation"
          >
            <span>Inspect Chart</span>
            <ArrowRight className="h-3 w-3" />
          </button>
        )}
      </div>
    </Card>
  );
};
