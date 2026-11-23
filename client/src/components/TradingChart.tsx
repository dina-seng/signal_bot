import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  LineStyle,
  CrosshairMode,
  ColorType,
  IChartApi,
  ISeriesApi,
  IPriceLine,
  UTCTimestamp,
} from 'lightweight-charts';
import {
  Layers,
  Sparkles,
  RefreshCw,
  TrendingUp,
  Activity,
  Maximize2,
  Crosshair,
  ShieldAlert,
} from 'lucide-react';
import { PairSymbol, TradeSignal } from '../types';
import {
  quantViewApi,
  BackendFairValueGap,
  BackendIndicatorAnalysis,
  BackendLiquidityZones,
  BackendStructureAnalysis,
  BackendQuote,
} from '../services/api';
import { formatPrice } from '../utils/formatters';

export interface FormedCandle {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ema20?: number;
  ema50?: number;
}

interface TradingChartProps {
  selectedSymbol: PairSymbol;
  onSymbolChange: (symbol: PairSymbol) => void;
  latestQuote?: BackendQuote | null;
  signals?: TradeSignal[];
  activeSignal?: TradeSignal | null;
}

// Parse string/number timestamp into Unix seconds (UTCTimestamp)
function parseToUnixSeconds(ts: string | number | Date): UTCTimestamp {
  if (typeof ts === 'number') {
    return (ts > 1e11 ? Math.floor(ts / 1000) : Math.floor(ts)) as UTCTimestamp;
  }
  if (ts instanceof Date) {
    return Math.floor(ts.getTime() / 1000) as UTCTimestamp;
  }
  let str = String(ts).trim();
  if (!str.endsWith('Z') && !str.includes('+') && !str.includes('-')) {
    str = str.replace(' ', 'T') + 'Z';
  } else if (!str.includes('T')) {
    str = str.replace(' ', 'T');
  }
  const parsed = new Date(str).getTime();
  return (isNaN(parsed) ? Math.floor(Date.now() / 1000) : Math.floor(parsed / 1000)) as UTCTimestamp;
}

// Convert timeframe string to duration in seconds
function getTimeframeDurationSeconds(tf: string): number {
  switch (tf.toLowerCase()) {
    case '1m':
      return 60;
    case '5m':
      return 300;
    case '15m':
      return 900;
    case '30m':
      return 1800;
    case '1h':
      return 3600;
    case '4h':
      return 14400;
    case '1d':
    case '1day':
      return 86400;
    default:
      return 60; // Default to 1-minute window
  }
}

// Math helper for continuous Exponential Moving Average
function computeEMAArray(closes: number[], period: number, decimals: number): number[] {
  if (closes.length === 0) return [];
  const k = 2 / (period + 1);
  const result: number[] = [];
  let ema = closes[0];
  for (let i = 0; i < closes.length; i++) {
    ema = closes[i] * k + ema * (1 - k);
    result.push(Number(ema.toFixed(decimals)));
  }
  return result;
}

// Helper to remove duplicate candle timestamps and ensure strict ascending order
function deduplicateAndSortCandles(candles: FormedCandle[]): FormedCandle[] {
  const map = new Map<number, FormedCandle>();
  for (const c of candles) {
    map.set(c.time, c);
  }
  return Array.from(map.values()).sort((a, b) => a.time - b.time);
}

export const TradingChart: React.FC<TradingChartProps> = ({
  selectedSymbol,
  onSymbolChange,
  latestQuote,
  signals,
  activeSignal,
}) => {
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>('15m');
  const [showEMA, setShowEMA] = useState<boolean>(true);
  const [showSR, setShowSR] = useState<boolean>(true);
  const [showFVG, setShowFVG] = useState<boolean>(true);
  const [candles, setCandles] = useState<FormedCandle[]>([]);
  const [isRealData, setIsRealData] = useState<boolean>(false);
  const [hoveredCandle, setHoveredCandle] = useState<{
    open: number;
    high: number;
    low: number;
    close: number;
    volume?: number;
    time?: string;
  } | null>(null);

  // Backend indicators & SMC structure
  const [indicatorData, setIndicatorData] = useState<BackendIndicatorAnalysis | null>(null);
  const [liquidityZones, setLiquidityZones] = useState<BackendLiquidityZones | null>(null);
  const [structureData, setStructureData] = useState<BackendStructureAnalysis | null>(null);

  const priceDecimals = 2;

  // Chart DOM container and series references
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const ema20SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const ema50SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const smcLinesRef = useRef<IPriceLine[]>([]);
  const srLinesRef = useRef<IPriceLine[]>([]);

  // 1. Initialize Lightweight Charts instance
  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Clean up if already exists
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const container = chartContainerRef.current;

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: '#090a0f' },
        textColor: '#94a3b8',
        fontFamily: 'JetBrains Mono, Menlo, monospace',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: 'rgba(0, 230, 118, 0.4)',
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: '#161922',
        },
        horzLine: {
          color: 'rgba(0, 230, 118, 0.4)',
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: '#161922',
        },
      },
      timeScale: {
        borderColor: 'rgba(255, 255, 255, 0.1)',
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.1)',
        scaleMargins: {
          top: 0.08,
          bottom: 0.22,
        },
      },
      handleScale: {
        mouseWheel: true,
        pinch: true,
        axisPressedMouseMove: {
          time: true,
          price: true,
        },
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      autoSize: true,
    });

    // 2. Add Candlestick Series with High-Tech Dark / Neon theme
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#00e676', // Neon Green
      downColor: '#ff3366', // Neon Red/Pink
      borderVisible: false,
      wickUpColor: '#00e676',
      wickDownColor: '#ff3366',
      priceFormat: {
        type: 'price',
        precision: priceDecimals,
        minMove: 0.01,
      },
    });

    // 3. Add Volume Histogram Series as overlay pane at bottom 20%
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '', // Overlay pane
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    // 4. Add EMA 20 (Neon Purple) & EMA 50 (Neon Cyan)
    const ema20Series = chart.addSeries(LineSeries, {
      color: '#a855f7',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      title: 'EMA 20',
    });

    const ema50Series = chart.addSeries(LineSeries, {
      color: '#00e5ff',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      title: 'EMA 50',
    });

    // 5. Crosshair Hover Subscription for Interactive Terminal Header
    chart.subscribeCrosshairMove((param) => {
      if (
        param.point === undefined ||
        !param.time ||
        param.point.x < 0 ||
        param.point.x > container.clientWidth ||
        param.point.y < 0 ||
        param.point.y > container.clientHeight
      ) {
        setHoveredCandle(null);
      } else {
        const cData = param.seriesData.get(candleSeries) as any;
        if (cData) {
          const vData = param.seriesData.get(volumeSeries) as any;
          setHoveredCandle({
            time: typeof param.time === 'number'
              ? new Date(param.time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
              : String(param.time),
            open: cData.open,
            high: cData.high,
            low: cData.low,
            close: cData.close,
            volume: vData?.value ?? 0,
          });
        }
      }
    });

    // Save refs
    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    ema20SeriesRef.current = ema20Series;
    ema50SeriesRef.current = ema50Series;

    // Handle container resize
    const resizeObserver = new ResizeObserver((entries) => {
      if (!entries || entries.length === 0) return;
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) {
        chart.applyOptions({ width, height });
      }
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      ema20SeriesRef.current = null;
      ema50SeriesRef.current = null;
    };
  }, []);

  // 2. Fetch Base Historical Candlesticks from FastAPI backend
  const loadChartData = useCallback(async () => {
    try {
      const [candlesRes, indRes, liqRes, structRes] = await Promise.allSettled([
        quantViewApi.getCandles(selectedSymbol, selectedTimeframe, 60),
        quantViewApi.getIndicators(selectedSymbol, selectedTimeframe),
        quantViewApi.getLiquidityZones(selectedSymbol, selectedTimeframe),
        quantViewApi.getStructure(selectedSymbol, selectedTimeframe),
      ]);

      if (candlesRes.status === 'fulfilled' && candlesRes.value.data?.length > 0) {
        const rawCandles = candlesRes.value.data;

        const mapped: FormedCandle[] = rawCandles.map((c) => ({
          time: parseToUnixSeconds(c.timestamp),
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
          volume: c.volume || 0,
        }));

        const cleanCandles = deduplicateAndSortCandles(mapped);

        // Compute EMAs
        const closes = cleanCandles.map((c) => c.close);
        const ema20Arr = computeEMAArray(closes, 20, priceDecimals);
        const ema50Arr = computeEMAArray(closes, 50, priceDecimals);
        cleanCandles.forEach((c, i) => {
          c.ema20 = ema20Arr[i];
          c.ema50 = ema50Arr[i];
        });

        // Set to state
        setCandles(cleanCandles);
        setIsRealData(true);

        // Feed TradingView Lightweight Charts
        if (candleSeriesRef.current && volumeSeriesRef.current) {
          candleSeriesRef.current.setData(
            cleanCandles.map((c) => ({
              time: c.time,
              open: c.open,
              high: c.high,
              low: c.low,
              close: c.close,
            }))
          );

          volumeSeriesRef.current.setData(
            cleanCandles.map((c) => ({
              time: c.time,
              value: c.volume,
              color: c.close >= c.open ? 'rgba(0, 230, 118, 0.35)' : 'rgba(255, 51, 102, 0.35)',
            }))
          );

          if (ema20SeriesRef.current && ema50SeriesRef.current) {
            ema20SeriesRef.current.setData(
              cleanCandles.map((c) => ({ time: c.time, value: c.ema20! }))
            );
            ema50SeriesRef.current.setData(
              cleanCandles.map((c) => ({ time: c.time, value: c.ema50! }))
            );
          }

          chartRef.current?.timeScale().fitContent();
        }
      } else {
        setCandles([]);
        setIsRealData(false);
      }

      if (indRes.status === 'fulfilled' && indRes.value.data) {
        setIndicatorData(indRes.value.data);
      }
      if (liqRes.status === 'fulfilled' && liqRes.value.data) {
        setLiquidityZones(liqRes.value.data);
      }
      if (structRes.status === 'fulfilled' && structRes.value.data) {
        setStructureData(structRes.value.data);
      }
    } catch (err) {
      console.warn('[TradingChart] Error loading candle data:', err);
    }
  }, [selectedSymbol, selectedTimeframe, priceDecimals]);

  // Periodic historical refresh every 60s
  useEffect(() => {
    loadChartData();
    const interval = setInterval(() => {
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return;
      loadChartData();
    }, 60000);

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') loadChartData();
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [loadChartData]);

  // 3. TASK 1: The "Forming Candle" Illusion with 15s Live Quotes
  // Logic:
  // - If the quote timestamp is within the current 1-minute window (or selected timeframe window),
  //   update the `close`, `high`, and `low` of the last candle in the chart array.
  // - Do not push a new candle until the minute actually rolls over.
  // - This makes the chart "tick" in real-time without backend changes.
  useEffect(() => {
    if (!latestQuote || typeof latestQuote.price !== 'number' || latestQuote.price <= 0) return;
    if (latestQuote.symbol && latestQuote.symbol !== selectedSymbol) return;

    setCandles((prevCandles) => {
      if (prevCandles.length === 0) return prevCandles;

      const quotePrice = latestQuote.price;
      const quoteTimeSec = parseToUnixSeconds(
        latestQuote.timestamp || latestQuote.fetched_at || Date.now()
      );

      const windowSec = getTimeframeDurationSeconds(selectedTimeframe);
      const lastIndex = prevCandles.length - 1;
      const lastCandle = prevCandles[lastIndex];

      // Check whether the quote timestamp is within the current window
      // For 1m: Math.floor(quoteTimeSec / 60) <= Math.floor(lastCandle.time / 60)
      const isWithinWindow =
        windowSec === 60
          ? Math.floor(quoteTimeSec / 60) <= Math.floor(lastCandle.time / 60)
          : quoteTimeSec < lastCandle.time + windowSec;

      if (isWithinWindow) {
        // Update forming candle
        const updatedHigh = Math.max(lastCandle.high, quotePrice);
        const updatedLow = Math.min(lastCandle.low, quotePrice);
        const updatedClose = quotePrice;

        const updatedCandle: FormedCandle = {
          ...lastCandle,
          high: updatedHigh,
          low: updatedLow,
          close: updatedClose,
        };

        // Real-time tick into TradingView Candlestick series
        candleSeriesRef.current?.update({
          time: updatedCandle.time,
          open: updatedCandle.open,
          high: updatedHigh,
          low: updatedLow,
          close: updatedClose,
        });

        // Fast update EMA on forming candle
        if (showEMA && lastCandle.ema20 && lastCandle.ema50) {
          const k20 = 2 / 21;
          const k50 = 2 / 51;
          const newEma20 = Number((updatedClose * k20 + lastCandle.ema20 * (1 - k20)).toFixed(2));
          const newEma50 = Number((updatedClose * k50 + lastCandle.ema50 * (1 - k50)).toFixed(2));
          updatedCandle.ema20 = newEma20;
          updatedCandle.ema50 = newEma50;
          ema20SeriesRef.current?.update({ time: updatedCandle.time, value: newEma20 });
          ema50SeriesRef.current?.update({ time: updatedCandle.time, value: newEma50 });
        }

        const next = [...prevCandles];
        next[lastIndex] = updatedCandle;
        return next;
      } else {
        // Minute / Window has rolled over!
        const newCandleTime = (Math.floor(quoteTimeSec / windowSec) * windowSec) as UTCTimestamp;

        // Ensure strictly ascending timestamp
        if (newCandleTime <= lastCandle.time) {
          return prevCandles;
        }

        const newCandle: FormedCandle = {
          time: newCandleTime,
          open: quotePrice,
          high: quotePrice,
          low: quotePrice,
          close: quotePrice,
          volume: 0,
          ema20: lastCandle.ema20 ?? quotePrice,
          ema50: lastCandle.ema50 ?? quotePrice,
        };

        // Push new candle bar to TradingView chart
        candleSeriesRef.current?.update({
          time: newCandle.time,
          open: newCandle.open,
          high: newCandle.high,
          low: newCandle.low,
          close: newCandle.close,
        });

        volumeSeriesRef.current?.update({
          time: newCandle.time,
          value: 0,
          color: 'rgba(0, 230, 118, 0.35)',
        });

        if (showEMA && newCandle.ema20 && newCandle.ema50) {
          ema20SeriesRef.current?.update({ time: newCandle.time, value: newCandle.ema20 });
          ema50SeriesRef.current?.update({ time: newCandle.time, value: newCandle.ema50 });
        }

        return [...prevCandles, newCandle];
      }
    });
  }, [latestQuote, selectedSymbol, selectedTimeframe, showEMA]);

  // 4. TASK 4: SMC Setup Overlays (Visual Only)
  // Horizontal dashed lines on TradingView chart for entry_price, stop_loss, take_profit_1
  useEffect(() => {
    if (!candleSeriesRef.current) return;
    const series = candleSeriesRef.current;

    // Clear previous SMC overlay lines
    smcLinesRef.current.forEach((line) => {
      try {
        series.removePriceLine(line);
      } catch {}
    });
    smcLinesRef.current = [];

    // Identify active signal for current symbol
    const signal =
      activeSignal ||
      signals?.find(
        (s) =>
          s.symbol === selectedSymbol &&
          s.hasActiveSignal &&
          (s.status === 'ACTIVE' || s.direction === 'BUY' || s.direction === 'SELL')
      );

    if (signal && signal.hasActiveSignal) {
      const entry = signal.entryPrice ?? (signal as any).entry_price;
      const sl = signal.stopLoss ?? (signal as any).stop_loss;
      const tp1 = signal.takeProfit1 ?? (signal as any).take_profit_1;
      const tp2 = signal.takeProfit2 ?? (signal as any).take_profit_2;

      // 1. Entry Price Line (Cyan dashed)
      if (typeof entry === 'number' && entry > 0) {
        const entryLine = series.createPriceLine({
          price: entry,
          color: '#00e5ff',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `ENTRY: ${formatPrice(selectedSymbol, entry)}`,
        });
        smcLinesRef.current.push(entryLine);
      }

      // 2. Stop Loss Line (Neon Red dashed)
      if (typeof sl === 'number' && sl > 0) {
        const slLine = series.createPriceLine({
          price: sl,
          color: '#ff3366',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `SL: ${formatPrice(selectedSymbol, sl)}`,
        });
        smcLinesRef.current.push(slLine);
      }

      // 3. Take Profit 1 Line (Neon Green dashed)
      if (typeof tp1 === 'number' && tp1 > 0) {
        const tp1Line = series.createPriceLine({
          price: tp1,
          color: '#00e676',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `TP1: ${formatPrice(selectedSymbol, tp1)}`,
        });
        smcLinesRef.current.push(tp1Line);
      }

      // Optional: Take Profit 2 Line (Emerald Dotted)
      if (typeof tp2 === 'number' && tp2 > 0) {
        const tp2Line = series.createPriceLine({
          price: tp2,
          color: '#00b0ff',
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: `TP2: ${formatPrice(selectedSymbol, tp2)}`,
        });
        smcLinesRef.current.push(tp2Line);
      }
    }
  }, [signals, activeSignal, selectedSymbol, candles]);

  // 5. Support / Resistance Levels on Chart
  useEffect(() => {
    if (!candleSeriesRef.current) return;
    const series = candleSeriesRef.current;

    srLinesRef.current.forEach((line) => {
      try {
        series.removePriceLine(line);
      } catch {}
    });
    srLinesRef.current = [];

    if (showSR && liquidityZones?.sr_zones) {
      liquidityZones.sr_zones.slice(0, 4).forEach((zone) => {
        const isSupport = zone.zone_type === 'SUPPORT';
        const avgPrice = (zone.price_low + zone.price_high) / 2;
        const srLine = series.createPriceLine({
          price: avgPrice,
          color: isSupport ? '#00d2ff' : '#e040fb',
          lineWidth: 1,
          lineStyle: LineStyle.SparseDotted,
          axisLabelVisible: true,
          title: `${isSupport ? 'SUPP' : 'RES'} (${zone.strength?.toFixed(0) || 'SMC'}%)`,
        });
        srLinesRef.current.push(srLine);
      });
    }
  }, [showSR, liquidityZones, candles]);

  // 6. Toggle EMA Visibility
  useEffect(() => {
    ema20SeriesRef.current?.applyOptions({ visible: showEMA });
    ema50SeriesRef.current?.applyOptions({ visible: showEMA });
  }, [showEMA]);

  // Current active display candle (either hovered or last forming candle)
  const lastCandle = candles.length > 0 ? candles[candles.length - 1] : null;
  const displayCandle = hoveredCandle || lastCandle;
  const isDisplayGreen = displayCandle ? displayCandle.close >= displayCandle.open : true;

  // Active signal for badge
  const currentSignal =
    activeSignal ||
    signals?.find(
      (s) =>
        s.symbol === selectedSymbol &&
        s.hasActiveSignal &&
        (s.status === 'ACTIVE' || s.direction === 'BUY' || s.direction === 'SELL')
    );

  return (
    <div className="relative min-w-0 w-full overflow-hidden p-3.5 sm:p-5 space-y-3 font-sans">
      {/* Chart Top Header & Toolbar: Fluid Wrapping & Horizontally Scrollable Controls on Mobile */}
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3 pb-2.5 border-b border-[#1d2230]">
        <div className="flex items-center gap-2 sm:gap-2.5 flex-wrap min-w-0">
          {/* Symbol Select Buttons */}
          <div className="flex items-center p-0.5 rounded-lg bg-[#0a0b10] border border-[#1d2230] shrink-0">
            {(['XAU/USD'] as PairSymbol[]).map((sym) => (
              <button
                key={sym}
                onClick={() => onSymbolChange(sym)}
                className={`min-h-[44px] sm:min-h-[32px] md:min-h-0 px-2.5 py-1 text-xs font-bold rounded flex items-center justify-center transition-colors cursor-pointer touch-manipulation ${
                  selectedSymbol === sym
                    ? 'bg-[#161922] text-[#00e676] border border-[#1d2230]'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {sym}
              </button>
            ))}
          </div>

          {/* Timeframe Select (Supports 1m, 5m, 15m, 1h, 4h, 1D) - Horizontally Scrollable on Mobile */}
          <div className="flex items-center p-0.5 rounded-lg bg-[#0a0b10] border border-[#1d2230] overflow-x-auto max-w-full snap-x scrollbar-none touch-pan-x">
            {['1m', '5m', '15m', '1h', '4h', '1D'].map((tf) => (
              <button
                key={tf}
                onClick={() => setSelectedTimeframe(tf)}
                className={`min-h-[44px] sm:min-h-[32px] md:min-h-0 min-w-[38px] sm:min-w-0 snap-start px-2.5 py-1 text-xs font-semibold rounded flex items-center justify-center transition-colors cursor-pointer touch-manipulation shrink-0 ${
                  selectedTimeframe === tf
                    ? 'bg-[#161922] text-cyan-400 border border-[#1d2230]'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>

          {/* Active SMC Signal Banner Pill if present */}
          {currentSignal && (
            <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-zinc-950 border border-cyan-500/30 text-[10px] shrink-0">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping" />
              <span className="text-cyan-300 font-bold">
                {currentSignal.direction} OVERLAY ACTIVE
              </span>
              <span className="text-zinc-500 hidden sm:inline">
                (TP1: {currentSignal.takeProfit1 ? formatPrice(selectedSymbol, currentSignal.takeProfit1) : '--'})
              </span>
            </div>
          )}
        </div>

        {/* Indicators Overlay Toggle & Data Source Badge: Stack / Wrap Gracefully */}
        <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap w-full lg:w-auto justify-start lg:justify-end">
          <span
            className={`px-2 py-1 rounded text-[10px] font-bold border flex items-center gap-1 shrink-0 ${
              isRealData
                ? 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                : 'bg-zinc-800 text-zinc-400 border-zinc-700'
            }`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-[#00e676] animate-pulse" />
            <span className="hidden xs:inline">{isRealData ? 'LIGHTWEIGHT CHARTS (TV)' : 'AWAITING DATA'}</span>
            <span className="xs:hidden">{isRealData ? 'TV CHART' : 'WAITING'}</span>
          </span>

          <button
            onClick={() => setShowEMA(!showEMA)}
            className={`min-h-[44px] md:min-h-0 px-2.5 sm:px-3 py-1.5 sm:py-1 rounded-lg text-xs font-medium border transition-colors flex items-center gap-1.5 cursor-pointer touch-manipulation ${
              showEMA
                ? 'bg-purple-500/10 text-purple-300 border-purple-500/30'
                : 'bg-[#0a0b10] text-slate-500 border-[#1d2230]'
            }`}
          >
            <Layers className="w-3.5 h-3.5 text-purple-400" />
            <span>EMA 20/50</span>
          </button>

          <button
            onClick={() => setShowSR(!showSR)}
            className={`min-h-[44px] md:min-h-0 px-2.5 sm:px-3 py-1.5 sm:py-1 rounded-lg text-xs font-medium border transition-colors flex items-center gap-1.5 cursor-pointer touch-manipulation ${
              showSR
                ? 'bg-cyan-500/10 text-cyan-300 border-cyan-500/30'
                : 'bg-[#0a0b10] text-slate-500 border-[#1d2230]'
            }`}
          >
            <Layers className="w-3.5 h-3.5 text-cyan-400" />
            <span>S/R {liquidityZones?.sr_zones?.length ? `(${liquidityZones.sr_zones.length})` : ''}</span>
          </button>

          <button
            onClick={loadChartData}
            title="Reload Chart Data"
            className="min-h-[44px] min-w-[44px] md:min-h-0 md:min-w-0 flex items-center justify-center p-2 md:p-1 rounded-lg bg-[#0a0b10] hover:bg-zinc-800 text-slate-400 hover:text-white border border-[#1d2230] transition-colors cursor-pointer touch-manipulation shrink-0"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Technical Indicators & Macro Bias Bar */}
      {indicatorData && (
        <div className="flex items-center justify-between gap-x-4 gap-y-2 text-[11px] px-2.5 py-1 rounded bg-[#0a0b10] border border-[#1d2230] flex-wrap">
          <div className="flex items-center gap-x-4 gap-y-2 flex-wrap">
            {/* RSI */}
            <div className="flex items-center gap-1">
              <span className="text-slate-500">RSI (14):</span>
              <span
                className={`font-bold ${
                  (indicatorData.rsi?.rsi_value || 50) > 70
                    ? 'text-[#ff3366]'
                    : (indicatorData.rsi?.rsi_value || 50) < 30
                    ? 'text-[#00e676]'
                    : 'text-cyan-400'
                }`}
              >
                {indicatorData.rsi?.rsi_value?.toFixed(1) || '--'}
              </span>
              <span className="text-slate-500 text-[10px]">
                ({indicatorData.rsi?.condition || 'NEUTRAL'})
              </span>
            </div>

            {/* ATR */}
            <div className="flex items-center gap-1">
              <span className="text-slate-500">ATR:</span>
              <span className="text-slate-200 font-bold">
                {indicatorData.atr?.atr_pips ? `${indicatorData.atr.atr_pips.toFixed(1)}p` : '--'}
              </span>
              <span className="text-slate-500 text-[10px]">
                ({indicatorData.atr?.volatility_state || 'NORMAL'})
              </span>
            </div>

            {/* EMA Trend */}
            <div className="flex items-center gap-1">
              <span className="text-slate-500">EMA Trend:</span>
              <span
                className={`font-bold ${
                  indicatorData.ema?.ema_trend?.includes('BULLISH')
                    ? 'text-[#00e676]'
                    : indicatorData.ema?.ema_trend?.includes('BEARISH')
                    ? 'text-[#ff3366]'
                    : 'text-slate-300'
                }`}
              >
                {indicatorData.ema?.ema_trend || 'NEUTRAL'}
              </span>
            </div>

            {/* Key Support & Resistance */}
            {structureData && (
              <div className="hidden lg:flex items-center gap-3 text-slate-400">
                {structureData.key_support && (
                  <span>
                    Supp: <strong className="text-[#00e676]">{formatPrice(selectedSymbol, structureData.key_support)}</strong>
                  </span>
                )}
                {structureData.key_resistance && (
                  <span>
                    Res: <strong className="text-[#ff3366]">{formatPrice(selectedSymbol, structureData.key_resistance)}</strong>
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Confluence Bias */}
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">Bias:</span>
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                indicatorData.confluence_bias?.includes('BULLISH')
                  ? 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                  : indicatorData.confluence_bias?.includes('BEARISH')
                  ? 'bg-[#ff3366]/10 text-[#ff3366] border-[#ff3366]/30'
                  : 'bg-slate-800 text-slate-300 border-slate-700'
              }`}
            >
              {indicatorData.confluence_bias} ({indicatorData.confluence_score > 0 ? '+' : ''}
              {indicatorData.confluence_score.toFixed(0)})
            </span>
          </div>
        </div>
      )}

      {/* OHLCV Bar: Real-time Forming Candle Feed (labels hidden on mobile) */}
      <div className="flex items-center justify-between gap-3 text-xs md:text-[11px] px-2.5 py-1.5 rounded-xl bg-white/[0.03] border border-white/10 overflow-x-auto font-mono">
        <div className="flex items-center gap-3.5 text-slate-400 whitespace-nowrap">
          <span>
            <span className="hidden md:inline">O: </span>
            <strong className="text-slate-200">{displayCandle ? formatPrice(selectedSymbol, displayCandle.open) : '--'}</strong>
          </span>
          <span>
            <span className="hidden md:inline">H: </span>
            <strong className="text-[#00e676]">{displayCandle ? formatPrice(selectedSymbol, displayCandle.high) : '--'}</strong>
          </span>
          <span>
            <span className="hidden md:inline">L: </span>
            <strong className="text-[#ff3366]">{displayCandle ? formatPrice(selectedSymbol, displayCandle.low) : '--'}</strong>
          </span>
          <span>
            <span className="hidden md:inline">C: </span>
            <strong className={isDisplayGreen ? 'text-[#00e676]' : 'text-[#ff3366]'}>
              {displayCandle ? formatPrice(selectedSymbol, displayCandle.close) : '--'}
            </strong>
          </span>
          {displayCandle?.volume != null && displayCandle.volume > 0 && (
            <span>
              <span className="hidden md:inline">Vol: </span>
              <strong className="text-slate-200">{displayCandle.volume.toLocaleString()}</strong>
            </span>
          )}
        </div>

        <div className="hidden sm:flex items-center gap-2 text-[10px] text-slate-500 shrink-0">
          <span className="flex items-center gap-1 text-[#00e676]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#00e676] animate-pulse" />
            <span>Forming Candle (15s Tick)</span>
          </span>
        </div>
      </div>

      {/* TradingView Lightweight Charts Viewport */}
      <div className="relative w-full h-[400px] md:h-[500px] lg:h-[600px] min-w-0 bg-[#090a0f] rounded-xl border border-white/10 overflow-hidden shadow-inner touch-manipulation">
        {candles.length === 0 && (
          <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-zinc-950/80 text-zinc-500 font-mono text-xs">
            <Activity className="w-6 h-6 animate-pulse text-cyan-400 mb-2" />
            <span>Streaming Candle History...</span>
          </div>
        )}
        <div ref={chartContainerRef} className="w-full h-full" />
      </div>

      {/* Institutional Legend & SMC Setup Overlay Key */}
      <div className="flex items-center justify-between text-[10px] font-mono text-slate-400 pt-0.5 flex-wrap gap-2">
        <div className="flex items-center gap-3.5 flex-wrap">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-xs bg-[#00e676] inline-block" />
            Bullish
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-xs bg-[#ff3366] inline-block" />
            Bearish
          </span>
          {showEMA && (
            <>
              <span className="flex items-center gap-1 text-purple-400">
                <span className="w-2.5 h-0.5 bg-purple-500 inline-block" /> EMA 20
              </span>
              <span className="flex items-center gap-1 text-cyan-400">
                <span className="w-2.5 h-0.5 bg-cyan-400 inline-block" /> EMA 50
              </span>
            </>
          )}
          {currentSignal && (
            <>
              <span className="flex items-center gap-1 text-cyan-300">
                <span className="w-2.5 h-0.5 border-t-2 border-dashed border-cyan-400 inline-block" /> Entry
              </span>
              <span className="flex items-center gap-1 text-[#ff3366]">
                <span className="w-2.5 h-0.5 border-t-2 border-dashed border-[#ff3366] inline-block" /> Stop Loss
              </span>
              <span className="flex items-center gap-1 text-[#00e676]">
                <span className="w-2.5 h-0.5 border-t-2 border-dashed border-[#00e676] inline-block" /> Take Profit
              </span>
            </>
          )}
          {showSR && (
            <span className="flex items-center gap-1 text-pink-400">
              <span className="w-2 h-0.5 border-t border-dotted border-pink-400 inline-block" /> S/R Levels
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 text-zinc-500 text-[10px]">
          <span>TradingView Lightweight v5</span>
          <span>•</span>
          <span>FastAPI SMC Engine</span>
        </div>
      </div>
    </div>
  );
};
