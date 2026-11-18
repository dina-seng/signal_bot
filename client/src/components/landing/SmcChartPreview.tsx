import React from 'react';

/**
 * Stylized XAU/USD 15m chart used on the landing page.
 * Illustrative price action only — it depicts an SMC short setup:
 * liquidity sweep -> break of structure -> order-block retest -> entry with 1:2.4 R:R.
 * Fully deterministic, no runtime data fetching.
 */

interface Candle {
  o: number;
  c: number;
  h: number;
  l: number;
  v: number;
}

const CANDLES: Candle[] = [
  { o: 2416.2, c: 2417.6, h: 2418.0, l: 2415.6, v: 0.34 },
  { o: 2417.6, c: 2419.4, h: 2419.9, l: 2417.1, v: 0.42 },
  { o: 2419.4, c: 2418.8, h: 2420.6, l: 2418.2, v: 0.30 },
  { o: 2418.8, c: 2421.6, h: 2422.0, l: 2418.4, v: 0.48 },
  { o: 2421.6, c: 2424.2, h: 2424.8, l: 2421.2, v: 0.56 },
  { o: 2424.2, c: 2423.4, h: 2425.2, l: 2422.9, v: 0.38 },
  { o: 2423.4, c: 2426.8, h: 2427.4, l: 2423.0, v: 0.52 },
  { o: 2426.8, c: 2427.9, h: 2434.8, l: 2426.4, v: 0.88 },
  { o: 2427.9, c: 2424.6, h: 2428.3, l: 2423.9, v: 0.72 },
  { o: 2424.6, c: 2421.4, h: 2425.0, l: 2420.8, v: 0.94 },
  { o: 2421.4, c: 2420.2, h: 2422.0, l: 2418.9, v: 0.81 },
  { o: 2420.2, c: 2423.2, h: 2423.6, l: 2419.6, v: 0.55 },
  { o: 2423.2, c: 2426.1, h: 2426.5, l: 2422.8, v: 0.44 },
  { o: 2426.1, c: 2427.5, h: 2428.0, l: 2425.7, v: 0.50 },
  { o: 2427.5, c: 2426.9, h: 2428.2, l: 2426.3, v: 0.46 },
  { o: 2426.9, c: 2424.0, h: 2427.2, l: 2423.5, v: 0.68 },
  { o: 2424.0, c: 2422.2, h: 2424.4, l: 2421.6, v: 0.62 },
  { o: 2422.2, c: 2421.0, h: 2422.6, l: 2420.2, v: 0.58 },
  { o: 2421.0, c: 2419.5, h: 2421.4, l: 2418.8, v: 0.64 },
  { o: 2419.5, c: 2417.8, h: 2419.9, l: 2416.9, v: 0.70 },
  { o: 2417.8, c: 2415.6, h: 2418.2, l: 2414.8, v: 0.74 },
  { o: 2415.6, c: 2414.2, h: 2416.0, l: 2413.6, v: 0.52 },
];

// Chart geometry
const MIN_PRICE = 2412;
const MAX_PRICE = 2437;
const VIEW_W = 700;
const VIEW_H = 300;
const PAD_TOP = 20;
const PAD_BOTTOM = 34;
const X0 = 54;
const STEP = 25.5;
const BODY_W = 12;

const priceY = (p: number) =>
  PAD_TOP + ((MAX_PRICE - p) / (MAX_PRICE - MIN_PRICE)) * (VIEW_H - PAD_TOP - PAD_BOTTOM);

const candleX = (i: number) => X0 + i * STEP;

// Annotations (illustrative)
const OB = { top: 2428.6, bottom: 2426.4, from: 7, to: 15 };
const FVG = { top: 2423.4, bottom: 2421.6, from: 9, to: 13 };
const SWEEP_PRICE = 2434.7;
const BOS_PRICE = 2419.2;
const ENTRY = 2427.0;
const STOP = 2428.8;
const TARGET = 2422.7;

const GREEN = '#26a69a';
const RED = '#ef5350';

const zoneX = (from: number, to: number) => candleX(from) - 2;
const zoneW = (from: number, to: number) => candleX(to) + BODY_W + 2 - zoneX(from, to);
const zoneY = (top: number) => priceY(top);
const zoneH = (top: number, bottom: number) => priceY(bottom) - priceY(top);

const CandleLayer: React.FC = () => (
  <>
    {CANDLES.map((k, i) => {
      const up = k.c >= k.o;
      const color = up ? GREEN : RED;
      const cx = candleX(i) + BODY_W / 2;
      const bodyTop = priceY(Math.max(k.o, k.c));
      const bodyHeight = Math.max(2, Math.abs(priceY(k.o) - priceY(k.c)));
      return (
        <g key={i}>
          <line
            x1={cx}
            x2={cx}
            y1={priceY(k.h)}
            y2={priceY(k.l)}
            stroke={color}
            strokeWidth={1.2}
            opacity={0.9}
          />
          <rect
            x={candleX(i)}
            y={bodyTop}
            width={BODY_W}
            height={bodyHeight}
            rx={1}
            fill={color}
            opacity={up ? 0.85 : 0.95}
          />
          <rect
            x={candleX(i)}
            y={VIEW_H - 10 - k.v * 20}
            width={BODY_W}
            height={k.v * 20}
            rx={1}
            fill={color}
            opacity={0.16}
          />
        </g>
      );
    })}
  </>
);

export const SmcChartPreview: React.FC = () => {
  return (
    <div className="relative">
      {/* Soft accent glow behind the panel */}
      <div
        aria-hidden="true"
        className="absolute -inset-6 rounded-[2rem] bg-[radial-gradient(ellipse_at_60%_20%,rgba(124,58,237,0.16),transparent_65%)] blur-2xl"
      />

      <div className="relative rounded-xl border border-white/5 bg-[#131722] shadow-[0_30px_80px_-24px_rgba(0,0,0,0.9)] overflow-hidden">
        {/* Panel header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
          <div className="flex items-center gap-2.5">
            <span className="text-sm font-semibold text-white tracking-tight">XAU/USD</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono text-slate-400 border border-white/10 bg-white/[0.03]">
              15m
            </span>
            <span className="hidden sm:inline-flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-widest text-slate-500">
              <span className="w-1.5 h-1.5 rounded-full bg-[#26a69a]" />
              Live structure
            </span>
          </div>
          <div className="flex items-center gap-2.5">
            <span className="font-mono text-sm text-slate-200 tabular-nums">2,418.60</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono text-[#26a69a] bg-[#26a69a]/10 border border-[#26a69a]/20">
              +0.42%
            </span>
          </div>
        </div>

        {/* Chart */}
        <div className="px-1.5 pt-1.5">
          <svg
            viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
            className="w-full h-auto block"
            role="img"
            aria-label="Illustrative XAU/USD 15m chart showing a liquidity sweep, break of structure, order block retest and short entry"
          >
            <defs>
              <filter id="ob-glow" x="-30%" y="-60%" width="160%" height="220%">
                <feGaussianBlur stdDeviation="4" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              <filter id="sweep-glow" x="-200%" y="-200%" width="500%" height="500%">
                <feGaussianBlur stdDeviation="4" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              <linearGradient id="ob-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#7c3aed" stopOpacity="0.30" />
                <stop offset="100%" stopColor="#7c3aed" stopOpacity="0.06" />
              </linearGradient>
              <linearGradient id="sweep-fade" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.15" />
                <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.7" />
              </linearGradient>
            </defs>

            {/* Grid */}
            {[2415, 2420, 2425, 2430, 2435].map((p) => (
              <g key={p}>
                <line
                  x1={X0 - 10}
                  x2={VIEW_W - 8}
                  y1={priceY(p)}
                  y2={priceY(p)}
                  stroke="rgba(255,255,255,0.045)"
                  strokeWidth={1}
                />
                <text
                  x={6}
                  y={priceY(p) + 3}
                  fill="rgba(148,163,184,0.55)"
                  fontSize={8.5}
                  fontFamily="'JetBrains Mono', monospace"
                >
                  {p}
                </text>
              </g>
            ))}
            {CANDLES.map((_, i) =>
              i % 5 === 4 ? (
                <line
                  key={i}
                  x1={candleX(i) + BODY_W / 2}
                  x2={candleX(i) + BODY_W / 2}
                  y1={PAD_TOP}
                  y2={VIEW_H - PAD_BOTTOM}
                  stroke="rgba(255,255,255,0.03)"
                  strokeWidth={1}
                />
              ) : null
            )}

            {/* Symbol watermark */}
            <text
              x={VIEW_W / 2 + 20}
              y={150}
              textAnchor="middle"
              fill="rgba(255,255,255,0.025)"
              fontSize={46}
              fontWeight={700}
              letterSpacing={4}
              fontFamily="'Inter', sans-serif"
            >
              XAU/USD
            </text>

            {/* Fair value gap */}
            <rect
              x={zoneX(FVG.from, FVG.to)}
              y={zoneY(FVG.top)}
              width={zoneW(FVG.from, FVG.to)}
              height={zoneH(FVG.top, FVG.bottom)}
              fill="rgba(245,158,11,0.07)"
              stroke="rgba(245,158,11,0.32)"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
            <text
              x={zoneX(FVG.from, FVG.to) + 6}
              y={zoneY(FVG.top) - 5}
              fill="rgba(245,158,11,0.85)"
              fontSize={8.5}
              letterSpacing={1.4}
              fontFamily="'JetBrains Mono', monospace"
            >
              FVG
            </text>

            {/* Order block */}
            <rect
              x={zoneX(OB.from, OB.to)}
              y={zoneY(OB.top)}
              width={zoneW(OB.from, OB.to)}
              height={zoneH(OB.top, OB.bottom)}
              rx={2}
              fill="url(#ob-fill)"
              stroke="rgba(167,139,250,0.75)"
              strokeWidth={1}
              filter="url(#ob-glow)"
            />
            <text
              x={zoneX(OB.from, OB.to) + 6}
              y={zoneY(OB.top) - 6}
              fill="#a78bfa"
              fontSize={8.5}
              letterSpacing={1.4}
              fontFamily="'JetBrains Mono', monospace"
            >
              ORDER BLOCK
            </text>

            {/* BOS */}
            <line
              x1={candleX(2)}
              x2={VIEW_W - 8}
              y1={priceY(BOS_PRICE)}
              y2={priceY(BOS_PRICE)}
              stroke="rgba(245,158,11,0.45)"
              strokeWidth={1}
              strokeDasharray="4 4"
            />
            <text
              x={candleX(2) + 4}
              y={priceY(BOS_PRICE) - 5}
              fill="rgba(245,158,11,0.8)"
              fontSize={8.5}
              letterSpacing={1.4}
              fontFamily="'JetBrains Mono', monospace"
            >
              BOS
            </text>

            {/* Liquidity sweep */}
            <line
              x1={X0 - 10}
              x2={candleX(7) + BODY_W / 2}
              y1={priceY(SWEEP_PRICE)}
              y2={priceY(SWEEP_PRICE)}
              stroke="url(#sweep-fade)"
              strokeWidth={1}
              strokeDasharray="4 4"
            />
            <circle
              cx={candleX(7) + BODY_W / 2}
              cy={priceY(2434.8)}
              r={6}
              fill="none"
              stroke="rgba(6,182,212,0.35)"
              strokeWidth={1}
            />
            <circle
              cx={candleX(7) + BODY_W / 2}
              cy={priceY(2434.8)}
              r={2.6}
              fill="#06b6d4"
              filter="url(#sweep-glow)"
            />
            <text
              x={X0 - 6}
              y={priceY(SWEEP_PRICE) - 6}
              fill="#22d3ee"
              fontSize={8.5}
              letterSpacing={1.4}
              fontFamily="'JetBrains Mono', monospace"
            >
              LIQUIDITY SWEEP
            </text>

            {/* Candles above the zones so bodies stay legible */}
            <CandleLayer />

            {/* Trade levels */}
            {[
              { p: ENTRY, color: '#e2e8f0', label: 'ENTRY 2427.00' },
              { p: STOP, color: '#f43f5e', label: 'SL 2428.80' },
              { p: TARGET, color: '#10b981', label: 'TP 2422.70' },
            ].map((lvl) => (
              <g key={lvl.label}>
                <line
                  x1={X0 - 10}
                  x2={VIEW_W - 84}
                  y1={priceY(lvl.p)}
                  y2={priceY(lvl.p)}
                  stroke={lvl.color}
                  strokeOpacity={0.4}
                  strokeWidth={1}
                  strokeDasharray="2 4"
                />
                <text
                  x={VIEW_W - 80}
                  y={priceY(lvl.p) + 3}
                  fill={lvl.color}
                  fillOpacity={0.9}
                  fontSize={8.5}
                  letterSpacing={0.6}
                  fontFamily="'JetBrains Mono', monospace"
                >
                  {lvl.label}
                </text>
              </g>
            ))}
          </svg>
        </div>

        {/* Signal footer */}
        <div className="grid grid-cols-3 divide-x divide-white/5 border-t border-white/5 bg-white/[0.015]">
          <div className="px-4 py-2.5">
            <div className="text-[9px] font-mono uppercase tracking-widest text-slate-500">Entry</div>
            <div className="font-mono text-xs text-slate-100 mt-0.5">2,427.00</div>
          </div>
          <div className="px-4 py-2.5">
            <div className="text-[9px] font-mono uppercase tracking-widest text-slate-500">Stop</div>
            <div className="font-mono text-xs text-rose-400 mt-0.5">2,428.80</div>
          </div>
          <div className="px-4 py-2.5 flex items-center justify-between gap-2">
            <div>
              <div className="text-[9px] font-mono uppercase tracking-widest text-slate-500">Target</div>
              <div className="font-mono text-xs text-emerald-400 mt-0.5">2,422.70</div>
            </div>
            <span className="px-2 py-1 rounded-md text-[10px] font-mono font-semibold text-purple-300 bg-purple-500/10 border border-purple-500/25">
              1 : 2.4R
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SmcChartPreview;
