import React, { useState, useEffect, useRef } from 'react';
import {
  Activity,
  Radio,
  Clock,
  ShieldCheck,
  TrendingUp,
  TrendingDown,
  Cpu,
  Zap,
  Server,
  Wifi,
  Sparkles,
} from 'lucide-react';
import { AccountSummary, RiskStatus } from '../types';
import { BackendQuote, BackendScannerStatus } from '../services/api';
import { formatCurrency, formatPnL } from '../utils/formatters';

interface SystemTelemetryProps {
  account: AccountSummary;
  quote: BackendQuote | null;
  scannerStatus: BackendScannerStatus | null;
  riskStatus?: RiskStatus;
  isApiConnected?: boolean;
}

export const SystemTelemetry: React.FC<SystemTelemetryProps> = ({
  account,
  quote,
  scannerStatus,
  riskStatus,
  isApiConnected = true,
}) => {
  // Real-time ticking clock for exact Quote Age precision
  const [now, setNow] = useState<number>(Date.now());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Flashing P&L State: green on increase, red on decrease for 500ms
  const [flashState, setFlashState] = useState<'up' | 'down' | null>(null);
  const prevPnlRef = useRef<number>(account.unrealizedPnl);
  const prevPriceRef = useRef<number | null>(quote?.price ?? null);
  const flashTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const currentPnl = account.unrealizedPnl;
    const currentPrice = quote?.price;
    const prevPnl = prevPnlRef.current;
    const prevPrice = prevPriceRef.current;

    let direction: 'up' | 'down' | null = null;

    if (currentPnl !== prevPnl) {
      direction = currentPnl > prevPnl ? 'up' : 'down';
    } else if (currentPrice != null && prevPrice != null && currentPrice !== prevPrice) {
      // Live price ticked and shifted valuation
      direction = currentPrice > prevPrice ? 'up' : 'down';
    }

    if (direction) {
      if (flashTimeoutRef.current) clearTimeout(flashTimeoutRef.current);
      setFlashState(direction);
      flashTimeoutRef.current = setTimeout(() => {
        setFlashState(null);
      }, 500);
    }

    prevPnlRef.current = currentPnl;
    if (currentPrice != null) prevPriceRef.current = currentPrice;

    return () => {
      if (flashTimeoutRef.current) clearTimeout(flashTimeoutRef.current);
    };
  }, [account.unrealizedPnl, quote?.price]);

  // Quote Age calculation: Date.now() - quote.fetched_at (or quote.timestamp fallback)
  const quoteFetchedAt = quote?.fetched_at
    ? new Date(quote.fetched_at).getTime()
    : quote?.timestamp
    ? new Date(quote.timestamp).getTime()
    : null;

  const quoteAgeMs = quoteFetchedAt ? Math.max(0, now - quoteFetchedAt) : null;
  const quoteAgeSeconds = quoteAgeMs !== null ? (quoteAgeMs / 1000).toFixed(1) : null;

  // Latency styling
  const latency = account.latencyMs || 0;
  const latencyStatus =
    latency < 60
      ? { label: 'ULTRA-LOW', color: 'text-[#00e676]', badge: 'bg-[#00e676]/10 border-[#00e676]/30' }
      : latency < 180
      ? { label: 'OPTIMAL', color: 'text-cyan-400', badge: 'bg-cyan-500/10 border-cyan-500/30' }
      : latency < 350
      ? { label: 'MODERATE', color: 'text-amber-400', badge: 'bg-amber-500/10 border-amber-500/30' }
      : { label: 'DEGRADED', color: 'text-[#ff3366]', badge: 'bg-[#ff3366]/10 border-[#ff3366]/30' };

  // Scanner status
  const isScannerRunning = scannerStatus?.is_running ?? false;
  const isScannerEnabled = scannerStatus?.is_enabled ?? true;
  const intervalMin = scannerStatus?.interval_minutes || 15;
  const totalScans = scannerStatus?.total_scans_completed || 0;

  // P&L styling with 500ms flash effect
  const isPnlPositive = account.unrealizedPnl >= 0;
  const pnlMeta = formatPnL(account.unrealizedPnl);

  const pnlFlashClasses =
    flashState === 'up'
      ? 'text-[#00e676] bg-[#00e676]/25 shadow-[0_0_20px_rgba(0,230,118,0.7)] ring-1 ring-[#00e676] scale-[1.02]'
      : flashState === 'down'
      ? 'text-[#ff3366] bg-[#ff3366]/25 shadow-[0_0_20px_rgba(255,51,102,0.7)] ring-1 ring-[#ff3366] scale-[1.02]'
      : isPnlPositive
      ? 'text-[#00e676] bg-transparent'
      : 'text-[#ff3366] bg-transparent';

  return (
    <div className="relative w-full p-3.5 sm:p-4 space-y-3 overflow-hidden">
      {/* Background Micro Accent Lines */}
      <div className="absolute top-0 right-0 w-96 h-full bg-gradient-to-l from-emerald-500/5 via-cyan-500/5 to-transparent pointer-events-none" />

      {/* Top Telemetry Engine Banner */}
      <div className="flex items-center justify-between gap-3 pb-2 border-b border-[#1d2230] text-xs">
        <div className="flex items-center gap-2.5">
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-zinc-950 border border-white/10 text-[10px] uppercase font-bold tracking-wider text-zinc-300">
            <Cpu className="w-3 h-3 text-cyan-400" />
            <span>INSTITUTIONAL TELEMETRY</span>
          </div>
          <span className="text-[10px] text-zinc-500 hidden sm:inline">
            FIX PROTOCOL / FASTFEED REALTIME
          </span>
        </div>

        <div className="flex items-center gap-2 text-[10px]">
          <span className="flex items-center gap-1 text-zinc-400">
            <span
              className={`w-2 h-2 rounded-full ${
                isApiConnected ? 'bg-[#00e676] animate-pulse' : 'bg-amber-400'
              }`}
            />
            {isApiConnected ? 'TELEMETRY SYNCED' : 'OFFLINE SIM'}
          </span>
        </div>
      </div>

      {/* 4 Core Telemetry Metrics Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {/* Metric 1: Unrealized P&L (with 500ms Flashing effect) */}
        <div className="p-3 rounded-xl bg-zinc-950/80 border border-white/10 flex flex-col justify-between relative overflow-hidden transition-all duration-200">
          <div className="flex items-center justify-between text-[10px] text-zinc-400 pb-1">
            <span className="uppercase tracking-wider flex items-center gap-1">
              <Zap className="w-3 h-3 text-amber-400" />
              Unrealized P&L
            </span>
            <span
              className={`text-[9px] font-bold px-1.5 py-0.2 rounded border transition-colors ${
                flashState === 'up'
                  ? 'border-[#00e676] text-[#00e676]'
                  : flashState === 'down'
                  ? 'border-[#ff3366] text-[#ff3366]'
                  : 'border-white/10 text-zinc-500'
              }`}
            >
              {flashState === 'up' ? '▲ TICK UP' : flashState === 'down' ? '▼ TICK DOWN' : 'LIVE TICK'}
            </span>
          </div>

          <div className="my-1 flex items-baseline gap-2">
            <span
              className={`text-lg sm:text-xl font-bold tracking-tight rounded-md px-1.5 py-0.5 transition-all duration-300 ${pnlFlashClasses}`}
            >
              {pnlMeta.formatted}
            </span>
          </div>

          <div className="flex items-center justify-between text-[10px] text-zinc-400 pt-1 border-t border-white/5">
            <span>
              Return:{' '}
              <strong className={isPnlPositive ? 'text-[#00e676]' : 'text-[#ff3366]'}>
                {account.unrealizedPnlPercent > 0 ? '+' : ''}
                {account.unrealizedPnlPercent.toFixed(2)}%
              </strong>
            </span>
            <span className="text-zinc-500">
              {quote?.price ? `$${quote.price.toFixed(2)}` : '--'}
            </span>
          </div>
        </div>

        {/* Metric 2: API Latency */}
        <div className="p-3 rounded-xl bg-zinc-950/80 border border-white/10 flex flex-col justify-between">
          <div className="flex items-center justify-between text-[10px] text-zinc-400 pb-1">
            <span className="uppercase tracking-wider flex items-center gap-1">
              <Activity className="w-3 h-3 text-cyan-400" />
              API Latency
            </span>
            <span className={`text-[9px] font-bold px-1.5 py-0.2 rounded border ${latencyStatus.badge} ${latencyStatus.color}`}>
              {latencyStatus.label}
            </span>
          </div>

          <div className="my-1 flex items-baseline gap-1.5">
            <span className={`text-lg sm:text-xl font-bold tracking-tight ${latencyStatus.color}`}>
              {latency}
            </span>
            <span className="text-xs text-zinc-400">ms</span>
          </div>

          <div className="flex items-center justify-between text-[10px] text-zinc-400 pt-1 border-t border-white/5">
            <span className="text-zinc-400 flex items-center gap-1">
              <Server className="w-2.5 h-2.5 text-zinc-500" />
              MT5 / REST Gateway
            </span>
            <span className="text-zinc-500 font-mono">
              {latency < 100 ? '99.98% SLA' : 'NORMAL'}
            </span>
          </div>
        </div>

        {/* Metric 3: Quote Age */}
        <div className="p-3 rounded-xl bg-zinc-950/80 border border-white/10 flex flex-col justify-between">
          <div className="flex items-center justify-between text-[10px] text-zinc-400 pb-1">
            <span className="uppercase tracking-wider flex items-center gap-1">
              <Clock className="w-3 h-3 text-purple-400" />
              Quote Age
            </span>
            <span
              className={`text-[9px] font-bold px-1.5 py-0.2 rounded border ${
                quoteAgeSeconds != null && Number(quoteAgeSeconds) < 20
                  ? 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                  : 'bg-amber-500/10 text-amber-400 border-amber-500/30'
              }`}
            >
              {quoteAgeSeconds != null && Number(quoteAgeSeconds) < 20 ? 'REAL-TIME' : 'POLLING'}
            </span>
          </div>

          <div className="my-1 flex items-baseline gap-1.5">
            <span
              className={`text-lg sm:text-xl font-bold tracking-tight ${
                quoteAgeSeconds != null && Number(quoteAgeSeconds) < 25
                  ? 'text-zinc-100'
                  : 'text-amber-300'
              }`}
            >
              {quoteAgeSeconds != null ? `${quoteAgeSeconds}s` : '--'}
            </span>
            <span className="text-[10px] text-zinc-500">elapsed</span>
          </div>

          <div className="flex items-center justify-between text-[10px] text-zinc-400 pt-1 border-t border-white/5">
            <span className="text-zinc-400 flex items-center gap-1">
              <Radio className="w-2.5 h-2.5 text-zinc-500" />
              {quote?.provider || 'FastFeed'}
            </span>
            <span className="text-zinc-500 font-mono">
              {quote?.cached ? 'CACHE HIT' : '15s TICK'}
            </span>
          </div>
        </div>

        {/* Metric 4: Scanner Status */}
        <div className="p-3 rounded-xl bg-zinc-950/80 border border-white/10 flex flex-col justify-between">
          <div className="flex items-center justify-between text-[10px] text-zinc-400 pb-1">
            <span className="uppercase tracking-wider flex items-center gap-1">
              <ShieldCheck className="w-3 h-3 text-emerald-400" />
              SMC Scanner
            </span>
            <span
              className={`text-[9px] font-bold px-1.5 py-0.2 rounded border ${
                isScannerRunning
                  ? 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30 animate-pulse'
                  : isScannerEnabled
                  ? 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                  : 'bg-zinc-800 text-zinc-400 border-zinc-700'
              }`}
            >
              {isScannerRunning ? 'SCANNING' : isScannerEnabled ? 'ARMED' : 'IDLE'}
            </span>
          </div>

          <div className="my-1 flex items-baseline gap-1.5">
            <span
              className={`text-lg sm:text-xl font-bold tracking-tight ${
                isScannerRunning ? 'text-cyan-400' : 'text-[#00e676]'
              }`}
            >
              {isScannerRunning ? 'IN PROGRESS' : `${intervalMin}m CADENCE`}
            </span>
          </div>

          <div className="flex items-center justify-between text-[10px] text-zinc-400 pt-1 border-t border-white/5">
            <span className="text-zinc-400">
              Completed: <strong className="text-zinc-200">{totalScans}</strong>
            </span>
            <span className="text-zinc-500 font-mono">
              {scannerStatus?.last_scan_at
                ? new Date(scannerStatus.last_scan_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' UTC'
                : 'Standby'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
