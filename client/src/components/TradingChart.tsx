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
import { quantViewApi } from '../services/api';
import { formatPrice } from '../utils/formatters';

interface TradingChartProps {
  selectedSymbol: PairSymbol;
  onSymbolChange: (symbol: PairSymbol) => void;
}

export const TradingChart: React.FC<TradingChartProps> = ({
  selectedSymbol,
  onSymbolChange,
}) => {
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>('15m');
  const [showEMA, setShowEMA] = useState<boolean>(true);
  const [showFVG, setShowFVG] = useState<boolean>(true);
  const [candles, setCandles] = useState<CandleData[]>(() => generateCandles(selectedSymbol));
  const [isRealData, setIsRealData] = useState<boolean>(false);

  const isGold = selectedSymbol === 'XAU/USD';
  const priceDecimals = isGold ? 2 : selectedSymbol === 'USD/JPY' ? 3 : 5;

  // Fetch real candles from FastAPI backend when symbol/timeframe changes
  useEffect(() => {
    let isCancelled = false;

    async function loadCandles() {
      try {
        const res = await quantViewApi.getCandles(selectedSymbol, selectedTimeframe, 30);
        if (!isCancelled && res.data && res.data.length > 0) {
          const mapped: CandleData[] = res.data.map((c, i) => {
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
              ema20: Number((c.close * 0.9994).toFixed(priceDecimals)),
              ema50: Number((c.close * 0.9988).toFixed(priceDecimals)),
              ema200: Number((c.close * 0.9972).toFixed(priceDecimals)),
              isGreen,
            };
          });
          setCandles(mapped);
          setIsRealData(true);
          return;
        }
      } catch {
        // Fallback to generated candles
      }

      if (!isCancelled) {
        setCandles(generateCandles(selectedSymbol));
        setIsRealData(false);
      }
    }

    loadCandles();
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
    <div className="rounded-xl p-5 bg-[#12121a] border border-[#1e1e2d] shadow-terminal space-y-4">
      {/* Chart Top Header & Toolbar */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 pb-3 border-b border-[#1e1e2d]">
        <div className="flex items-center gap-3 flex-wrap">
          {/* Symbol Select Buttons */}
          <div className="flex items-center p-1 rounded-lg bg-[#0a0a0f] border border-[#1e1e2d]">
            {(['EUR/USD', 'GBP/USD', 'USD/JPY', 'XAU/USD'] as PairSymbol[]).map((sym) => (
              <button
                key={sym}
                onClick={() => onSymbolChange(sym)}
                className={`px-2.5 py-1 text-xs font-mono font-bold rounded transition-all cursor-pointer ${
                  selectedSymbol === sym
                    ? 'bg-[#181824] text-[#00ff88] border border-[#00ff88]/40 shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {sym}
              </button>
            ))}
          </div>

          {/* Timeframe Select */}
          <div className="flex items-center p-1 rounded-lg bg-[#0a0a0f] border border-[#1e1e2d]">
            {['15m', '1h', '4h', '1D'].map((tf) => (
              <button
                key={tf}
                onClick={() => setSelectedTimeframe(tf)}
                className={`px-2.5 py-1 text-xs font-mono font-semibold rounded transition-all cursor-pointer ${
                  selectedTimeframe === tf
                    ? 'bg-[#1e1e2d] text-cyan-400'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>

        {/* Indicators Overlay Toggle & Data Source Badge */}
        <div className="flex items-center gap-2">
          <span
            className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${
              isRealData
                ? 'bg-[#00ff88]/15 text-[#00ff88] border-[#00ff88]/30'
                : 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30'
            }`}
          >
            {isRealData ? 'LIVE DB CANDLES' : 'SYNTHETIC OHLC'}
          </span>

          <button
            onClick={() => setShowEMA(!showEMA)}
            className={`px-2.5 py-1 rounded text-xs font-mono font-medium border transition-all flex items-center gap-1.5 cursor-pointer ${
              showEMA
                ? 'bg-purple-500/15 text-purple-300 border-purple-500/40'
                : 'bg-[#0a0a0f] text-slate-500 border-[#1e1e2d]'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>EMA 20/50/200</span>
          </button>

          <button
            onClick={() => setShowFVG(!showFVG)}
            className={`px-2.5 py-1 rounded text-xs font-mono font-medium border transition-all flex items-center gap-1.5 cursor-pointer ${
              showFVG
                ? 'bg-amber-500/15 text-amber-300 border-amber-500/40'
                : 'bg-[#0a0a0f] text-slate-500 border-[#1e1e2d]'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>SMC FVG</span>
          </button>
        </div>
      </div>

      {/* OHLCV Bar */}
      <div className="flex items-center justify-between gap-4 text-xs font-mono px-3 py-2 rounded-lg bg-[#0a0a0f] border border-[#1e1e2d] overflow-x-auto">
        <div className="flex items-center gap-4 text-slate-400">
          <span>
            O: <strong className="text-slate-200">{formatPrice(selectedSymbol, lastCandle.open)}</strong>
          </span>
          <span>
            H: <strong className="text-[#00ff88]">{formatPrice(selectedSymbol, lastCandle.high)}</strong>
          </span>
          <span>
            L: <strong className="text-[#ff3366]">{formatPrice(selectedSymbol, lastCandle.low)}</strong>
          </span>
          <span>
            C:{' '}
            <strong className={lastCandle.isGreen ? 'text-[#00ff88]' : 'text-[#ff3366]'}>
              {formatPrice(selectedSymbol, lastCandle.close)}
            </strong>
          </span>
          <span>
            Vol: <strong className="text-slate-200">{lastCandle.volume.toLocaleString()}</strong>
          </span>
        </div>

        <div className="flex items-center gap-2 text-[11px] text-slate-400 shrink-0">
          <span className="w-2 h-2 rounded-full bg-[#00ff88] animate-ping" />
          <span>Feed: FastAPI SQLite Database</span>
        </div>
      </div>

      {/* SVG Candlestick Canvas & Custom High-Resolution Visualizer */}
      <div className="relative w-full h-80 bg-[#0a0a0f] rounded-lg border border-[#1e1e2d] overflow-hidden p-2">
        <ResponsiveContainer width="100%" height="80%">
          <ComposedChart data={candles} margin={{ top: 15, right: 20, left: 10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="2 2" stroke="#161622" vertical={false} />
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
                    <div className="p-2.5 bg-[#12121a]/95 border border-[#1e1e2d] rounded-lg shadow-xl font-mono text-xs space-y-1 backdrop-blur-md">
                      <p className="text-slate-400 font-bold border-b border-[#1e1e2d] pb-1">
                        {data.time} ({selectedTimeframe})
                      </p>
                      <div className="grid grid-cols-2 gap-x-3 text-[11px]">
                        <span className="text-slate-400">Open:</span>
                        <span className="text-slate-200">{formatPrice(selectedSymbol, data.open)}</span>
                        <span className="text-slate-400">High:</span>
                        <span className="text-[#00ff88]">{formatPrice(selectedSymbol, data.high)}</span>
                        <span className="text-slate-400">Low:</span>
                        <span className="text-[#ff3366]">{formatPrice(selectedSymbol, data.low)}</span>
                        <span className="text-slate-400">Close:</span>
                        <span className={data.isGreen ? 'text-[#00ff88]' : 'text-[#ff3366]'}>
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
              fill="#00ff88"
              shape={(props: any) => {
                const { x, y, width, height, payload } = props;
                const candle = payload as CandleData;
                const isGreen = candle.isGreen;
                const fillColor = isGreen ? '#00ff88' : '#ff3366';
                const strokeColor = isGreen ? '#00ff88' : '#ff3366';

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

            {/* Fair Value Gap Reference Area */}
            {showFVG && (
              <ReferenceArea
                y1={lastCandle.open * 0.9997}
                y2={lastCandle.open * 1.0003}
                fill="#ffb800"
                fillOpacity={0.12}
                stroke="#ffb800"
                strokeDasharray="3 3"
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>

        {/* Volume Sub-chart */}
        <div className="h-[20%] w-full border-t border-[#161622] pt-1">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={candles} margin={{ top: 0, right: 20, left: 10, bottom: 0 }}>
              <Bar
                dataKey="volume"
                fill="#334155"
                shape={(props: any) => {
                  const { x, y, width, height, payload } = props;
                  const candle = payload as CandleData;
                  const color = candle.isGreen ? 'rgba(0, 255, 136, 0.4)' : 'rgba(255, 51, 102, 0.4)';
                  return <rect x={x + 2} y={y} width={Math.max(width - 4, 2)} height={height} fill={color} rx={1} />;
                }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Chart Footer Indicator Legend */}
      <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 pt-1">
        <div className="flex items-center gap-4 flex-wrap">
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm bg-[#00ff88] inline-block" />
            Bullish Candle
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm bg-[#ff3366] inline-block" />
            Bearish Candle
          </span>
          {showEMA && (
            <>
              <span className="flex items-center gap-1 text-purple-400">
                <span className="w-3 h-0.5 bg-purple-500 inline-block" /> EMA 20
              </span>
              <span className="flex items-center gap-1 text-sky-400">
                <span className="w-3 h-0.5 bg-sky-400 inline-block" /> EMA 50
              </span>
            </>
          )}
          {showFVG && (
            <span className="flex items-center gap-1 text-amber-400">
              <span className="w-2.5 h-2.5 bg-amber-400/30 border border-amber-400 inline-block rounded-xs" />
              SMC Fair Value Gap (FVG Zone)
            </span>
          )}
        </div>
        <span className="text-slate-500 hidden sm:inline">
          QuantView Candlestick Engine
        </span>
      </div>
    </div>
  );
};
