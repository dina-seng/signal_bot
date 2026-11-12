import React, { useState, useEffect, useMemo } from 'react';
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceArea,
} from 'recharts';
import {
  Layers,
  Sparkles,
  RefreshCw,
  TrendingUp,
} from 'lucide-react';
import { PairSymbol } from '../types';
import { generateCandles, CandleData } from '../data/mockData';
import {
  quantViewApi,
  BackendFairValueGap,
  BackendIndicatorAnalysis,
  BackendLiquidityZones,
  BackendStructureAnalysis,
} from '../services/api';
import { formatPrice } from '../utils/formatters';

interface TradingChartProps {
  selectedSymbol: PairSymbol;
  onSymbolChange: (symbol: PairSymbol) => void;
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

export const TradingChart: React.FC<TradingChartProps> = ({
  selectedSymbol,
  onSymbolChange,
}) => {
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>('15m');
  const [showEMA, setShowEMA] = useState<boolean>(true);
  const [showFVG, setShowFVG] = useState<boolean>(true);
  const [showSR, setShowSR] = useState<boolean>(true);
  const [candles, setCandles] = useState<CandleData[]>(() => generateCandles(selectedSymbol));
  const [isRealData, setIsRealData] = useState<boolean>(false);

  // Backend live indicator states
  const [indicatorData, setIndicatorData] = useState<BackendIndicatorAnalysis | null>(null);
  const [liquidityZones, setLiquidityZones] = useState<BackendLiquidityZones | null>(null);
  const [structureData, setStructureData] = useState<BackendStructureAnalysis | null>(null);

  const isGold = selectedSymbol === 'XAU/USD';
  const priceDecimals = 2;

  // Fetch real candles, indicators, SMC liquidity zones, and structure from backend
  useEffect(() => {
    let isCancelled = false;

    async function loadChartData() {
      try {
        const [candlesRes, indRes, liqRes, structRes] = await Promise.allSettled([
          quantViewApi.getCandles(selectedSymbol, selectedTimeframe, 35),
          quantViewApi.getIndicators(selectedSymbol, selectedTimeframe),
          quantViewApi.getLiquidityZones(selectedSymbol, selectedTimeframe),
          quantViewApi.getStructure(selectedSymbol, selectedTimeframe),
        ]);

        if (isCancelled) return;

        // 1. Process Candle Series
        if (candlesRes.status === 'fulfilled' && candlesRes.value.data?.length > 0) {
          const rawCandles = candlesRes.value.data;
          const closePrices = rawCandles.map((c) => c.close);
          const ema20Series = computeEMAArray(closePrices, 20, priceDecimals);
          const ema50Series = computeEMAArray(closePrices, 50, priceDecimals);
          const ema200Series = computeEMAArray(closePrices, 200, priceDecimals);

          const mapped: CandleData[] = rawCandles.map((c, i) => {
            const isGreen = c.close >= c.open;
            return {
              time: new Date(c.timestamp).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
                hour12: false,
              }),
              open: c.open,
              high: c.high,
              low: c.low,
              close: c.close,
              volume: c.volume || Math.floor(Math.random() * 6000 + 1500),
              ema20: ema20Series[i] || c.close,
              ema50: ema50Series[i] || c.close,
              ema200: ema200Series[i] || c.close,
              isGreen,
            };
          });

          setCandles(mapped);
          setIsRealData(true);
        } else {
          setCandles(generateCandles(selectedSymbol));
          setIsRealData(false);
        }

        // 2. Process Technical Indicators (RSI, ATR, FVGs)
        if (indRes.status === 'fulfilled' && indRes.value.data) {
          setIndicatorData(indRes.value.data);
        }

        // 3. Process SMC Liquidity & S/R Zones
        if (liqRes.status === 'fulfilled' && liqRes.value.data) {
          setLiquidityZones(liqRes.value.data);
        }

        // 4. Process Market Structure & Trend
        if (structRes.status === 'fulfilled' && structRes.value.data) {
          setStructureData(structRes.value.data);
        }
      } catch {
        if (!isCancelled) {
          setCandles(generateCandles(selectedSymbol));
          setIsRealData(false);
        }
      }
    }

    loadChartData();
    return () => {
      isCancelled = true;
    };
  }, [selectedSymbol, selectedTimeframe, priceDecimals]);

  const lastCandle = candles[candles.length - 1] || {
    open: 0,
    high: 0,
    low: 0,
    close: 0,
    volume: 0,
    isGreen: true,
  };

  return (
    <div className="rounded-lg p-4 bg-[#111319] border border-[#1d2230] space-y-3 font-mono">
      {/* Chart Top Header & Toolbar */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 pb-2.5 border-b border-[#1d2230]">
        <div className="flex items-center gap-2.5 flex-wrap">
          {/* Symbol Select Buttons */}
          <div className="flex items-center p-0.5 rounded bg-[#0a0b10] border border-[#1d2230]">
            {(['XAU/USD'] as PairSymbol[]).map((sym) => (
              <button
                key={sym}
                onClick={() => onSymbolChange(sym)}
                className={`px-2 py-0.5 text-xs font-bold rounded transition-colors cursor-pointer ${
                  selectedSymbol === sym
                    ? 'bg-[#161922] text-[#00e676] border border-[#1d2230]'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {sym}
              </button>
            ))}
          </div>

          {/* Timeframe Select */}
          <div className="flex items-center p-0.5 rounded bg-[#0a0b10] border border-[#1d2230]">
            {['15m', '1h', '4h', '1D'].map((tf) => (
              <button
                key={tf}
                onClick={() => setSelectedTimeframe(tf)}
                className={`px-2 py-0.5 text-xs font-semibold rounded transition-colors cursor-pointer ${
                  selectedTimeframe === tf
                    ? 'bg-[#161922] text-cyan-400 border border-[#1d2230]'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>

        {/* Indicators Overlay Toggle & Data Source Badge */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span
            className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
              isRealData
                ? 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                : 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30'
            }`}
          >
            {isRealData ? 'LIVE DB CANDLES' : 'SYNTHETIC OHLC'}
          </span>

          <button
            onClick={() => setShowEMA(!showEMA)}
            className={`px-2 py-0.5 rounded text-xs font-medium border transition-colors flex items-center gap-1 cursor-pointer ${
              showEMA
                ? 'bg-purple-500/10 text-purple-300 border-purple-500/30'
                : 'bg-[#0a0b10] text-slate-500 border-[#1d2230]'
            }`}
          >
            <Layers className="w-3 h-3" />
            <span>EMA 20/50</span>
          </button>

          <button
            onClick={() => setShowFVG(!showFVG)}
            className={`px-2 py-0.5 rounded text-xs font-medium border transition-colors flex items-center gap-1 cursor-pointer ${
              showFVG
                ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                : 'bg-[#0a0b10] text-slate-500 border-[#1d2230]'
            }`}
          >
            <Sparkles className="w-3 h-3" />
            <span>FVG {indicatorData?.active_fvgs?.length ? `(${indicatorData.active_fvgs.length})` : ''}</span>
          </button>

          <button
            onClick={() => setShowSR(!showSR)}
            className={`px-2 py-0.5 rounded text-xs font-medium border transition-colors flex items-center gap-1 cursor-pointer ${
              showSR
                ? 'bg-cyan-500/10 text-cyan-300 border-cyan-500/30'
                : 'bg-[#0a0b10] text-slate-500 border-[#1d2230]'
            }`}
          >
            <Layers className="w-3 h-3" />
            <span>S/R {liquidityZones?.sr_zones?.length ? `(${liquidityZones.sr_zones.length})` : ''}</span>
          </button>
        </div>
      </div>

      {/* Technical Indicators & Macro Bias Bar */}
      {indicatorData && (
        <div className="flex items-center justify-between gap-3 text-[11px] px-2.5 py-1 rounded bg-[#0a0b10] border border-[#1d2230] flex-wrap">
          <div className="flex items-center gap-3.5 flex-wrap">
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

            {/* Key Support & Resistance from Structure/Liquidity */}
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
              {indicatorData.confluence_bias} ({indicatorData.confluence_score > 0 ? '+' : ''}{indicatorData.confluence_score.toFixed(0)})
            </span>
          </div>
        </div>
      )}

      {/* OHLCV Bar */}
      <div className="flex items-center justify-between gap-3 text-[11px] px-2.5 py-1.5 rounded bg-[#0a0b10] border border-[#1d2230] overflow-x-auto">
        <div className="flex items-center gap-3.5 text-slate-400">
          <span>
            O: <strong className="text-slate-200">{formatPrice(selectedSymbol, lastCandle.open)}</strong>
          </span>
          <span>
            H: <strong className="text-[#00e676]">{formatPrice(selectedSymbol, lastCandle.high)}</strong>
          </span>
          <span>
            L: <strong className="text-[#ff3366]">{formatPrice(selectedSymbol, lastCandle.low)}</strong>
          </span>
          <span>
            C:{' '}
            <strong className={lastCandle.isGreen ? 'text-[#00e676]' : 'text-[#ff3366]'}>
              {formatPrice(selectedSymbol, lastCandle.close)}
            </strong>
          </span>
          <span>
            Vol: <strong className="text-slate-200">{lastCandle.volume.toLocaleString()}</strong>
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-[10px] text-slate-500 shrink-0">
          <span className="w-1.5 h-1.5 rounded-full bg-[#00e676]" />
          <span>SQLite Candle Feed</span>
        </div>
      </div>

      {/* SVG Candlestick Canvas & Custom High-Resolution Visualizer */}
      <div className="relative w-full h-80 bg-[#0a0b10] rounded border border-[#1d2230] overflow-hidden p-2">
        <ResponsiveContainer width="100%" height="80%">
          <ComposedChart data={candles} margin={{ top: 12, right: 15, left: 5, bottom: 0 }}>
            <CartesianGrid strokeDasharray="2 2" stroke="#151824" vertical={false} />
            <XAxis
              dataKey="time"
              stroke="#475569"
              fontSize={10}
              tickLine={false}
              fontFamily="JetBrains Mono"
            />
            <YAxis
              domain={['auto', 'auto']}
              stroke="#475569"
              fontSize={10}
              tickLine={false}
              axisLine={false}
              orientation="right"
              fontFamily="JetBrains Mono"
              tickFormatter={(v) => formatPrice(selectedSymbol, v)}
            />

            <Tooltip
              content={({ active, payload }) => {
                if (active && payload && payload.length) {
                  const data = payload[0].payload as CandleData;
                  return (
                    <div className="p-2.5 bg-[#111319]/95 border border-[#1d2230] rounded shadow-terminal font-mono text-xs space-y-1 backdrop-blur-md">
                      <p className="text-slate-400 font-bold border-b border-[#1d2230] pb-1">
                        {data.time} ({selectedTimeframe})
                      </p>
                      <div className="grid grid-cols-2 gap-x-3 text-[11px]">
                        <span className="text-slate-400">Open:</span>
                        <span className="text-slate-200">{formatPrice(selectedSymbol, data.open)}</span>
                        <span className="text-slate-400">High:</span>
                        <span className="text-[#00e676]">{formatPrice(selectedSymbol, data.high)}</span>
                        <span className="text-slate-400">Low:</span>
                        <span className="text-[#ff3366]">{formatPrice(selectedSymbol, data.low)}</span>
                        <span className="text-slate-400">Close:</span>
                        <span className={data.isGreen ? 'text-[#00e676]' : 'text-[#ff3366]'}>
                          {formatPrice(selectedSymbol, data.close)}
                        </span>
                      </div>
                      {showEMA && (
                        <div className="border-t border-[#1e1e2d] pt-1 text-[10px] space-y-0.5 text-purple-300">
                          <div>EMA 20: {formatPrice(selectedSymbol, data.ema20)}</div>
                          <div>EMA 50: {formatPrice(selectedSymbol, data.ema50)}</div>
                        </div>
                      )}
                    </div>
                  );
                }
                return null;
              }}
            />

            {/* Candlestick bodies via Custom Bar */}
            <Bar
              dataKey="close"
              fill="#00e676"
              shape={(props: any) => {
                const { x, y, width, height, payload } = props;
                const candle = payload as CandleData;
                const isGreen = candle.isGreen;
                const fillColor = isGreen ? '#00e676' : '#ff3366';
                const strokeColor = isGreen ? '#00e676' : '#ff3366';

                const bodyY = isGreen ? y : y;
                const bodyH = Math.max(Math.abs(height * 0.15), 4);

                return (
                  <g>
                    {/* Wick */}
                    <line
                      x1={x + width / 2}
                      y1={Math.max(bodyY - 12, 5)}
                      x2={x + width / 2}
                      y2={bodyY + bodyH + 12}
                      stroke={strokeColor}
                      strokeWidth={1.5}
                    />
                    {/* Body */}
                    <rect
                      x={x + 2}
                      y={bodyY}
                      width={Math.max(width - 4, 3)}
                      height={bodyH}
                      fill={fillColor}
                      stroke={strokeColor}
                      rx={1}
                    />
                  </g>
                );
              }}
            />

            {/* EMA Lines Overlay */}
            {showEMA && (
              <>
                <Line
                  type="monotone"
                  dataKey="ema20"
                  stroke="#a855f7"
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="ema50"
                  stroke="#38bdf8"
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
              </>
            )}

            {/* Real Fair Value Gap (FVG) Reference Areas from Backend */}
            {showFVG && indicatorData?.active_fvgs && indicatorData.active_fvgs.length > 0
              ? indicatorData.active_fvgs.slice(0, 4).map((fvg, idx) => {
                  const isBullish = fvg.fvg_type === 'BULLISH_FVG';
                  return (
                    <ReferenceArea
                      key={`fvg-${idx}`}
                      y1={fvg.bottom_price}
                      y2={fvg.top_price}
                      fill={isBullish ? '#00e676' : '#ffb800'}
                      fillOpacity={0.14}
                      stroke={isBullish ? '#00e676' : '#ffb800'}
                      strokeDasharray="3 3"
                    />
                  );
                })
              : showFVG && (
                  <ReferenceArea
                    y1={lastCandle.open * 0.9997}
                    y2={lastCandle.open * 1.0003}
                    fill="#ffb800"
                    fillOpacity={0.12}
                    stroke="#ffb800"
                    strokeDasharray="3 3"
                  />
                )}

            {/* Dynamic S/R Zones from SMC Backend */}
            {showSR && liquidityZones?.sr_zones && liquidityZones.sr_zones.slice(0, 3).map((zone, idx) => {
              const isSupport = zone.zone_type === 'SUPPORT';
              return (
                <ReferenceArea
                  key={`sr-${idx}`}
                  y1={zone.price_low}
                  y2={zone.price_high}
                  fill={isSupport ? '#00d2ff' : '#a855f7'}
                  fillOpacity={0.08}
                  stroke={isSupport ? '#00d2ff' : '#a855f7'}
                  strokeDasharray="2 2"
                />
              );
            })}
          </ComposedChart>
        </ResponsiveContainer>

        {/* Volume Sub-chart */}
        <div className="h-[20%] w-full border-t border-[#151824] pt-1">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={candles} margin={{ top: 0, right: 15, left: 5, bottom: 0 }}>
              <Bar
                dataKey="volume"
                fill="#334155"
                shape={(props: any) => {
                  const { x, y, width, height, payload } = props;
                  const candle = payload as CandleData;
                  const color = candle.isGreen ? 'rgba(0, 230, 118, 0.35)' : 'rgba(255, 51, 102, 0.35)';
                  return <rect x={x + 2} y={y} width={Math.max(width - 4, 2)} height={height} fill={color} rx={1} />;
                }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Chart Footer Indicator Legend */}
      <div className="flex items-center justify-between text-[10px] font-mono text-slate-400 pt-0.5">
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
              <span className="flex items-center gap-1 text-sky-400">
                <span className="w-2.5 h-0.5 bg-sky-400 inline-block" /> EMA 50
              </span>
            </>
          )}
          {showFVG && (
            <span className="flex items-center gap-1 text-amber-400">
              <span className="w-2 h-2 bg-amber-400/30 border border-amber-400 inline-block rounded-xs" />
              SMC FVG
            </span>
          )}
        </div>
        <span className="text-slate-500 hidden sm:inline">
          FastAPI SMC Feed
        </span>
      </div>
    </div>
  );
};
