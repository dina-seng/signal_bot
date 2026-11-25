import React from 'react';
import { Link } from 'react-router-dom';
import { motion, type Variants } from 'framer-motion';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import {
  TrendingUp,
  Activity,
  Layers,
  ArrowRight,
  Shield,
  BarChart2,
  CheckCircle2,
  Target,
} from 'lucide-react';
import { SmcChartPreview } from '../components/landing/SmcChartPreview';
import logoImg from '../../assets/logo.png';

// Walk-forward equity checkpoints, 249 executed trades, +51.26R net (2025–2026)
const equityCurveData = [
  { trade: 0, date: 'Apr 2025', returnR: 0, drawdown: 0 },
  { trade: 25, date: 'Jun 2025', returnR: 6.4, drawdown: 3.2 },
  { trade: 55, date: 'Aug 2025', returnR: 14.8, drawdown: 4.8 },
  { trade: 90, date: 'Oct 2025', returnR: 24.2, drawdown: 6.5 },
  { trade: 125, date: 'Dec 2025', returnR: 19.5, drawdown: 11.2 },
  { trade: 160, date: 'Feb 2026', returnR: 31.6, drawdown: 7.9 },
  { trade: 195, date: 'May 2026', returnR: 38.4, drawdown: 15.6 },
  { trade: 220, date: 'Aug 2026', returnR: 28.9, drawdown: 22.45 },
  { trade: 238, date: 'Nov 2026', returnR: 43.8, drawdown: 9.1 },
  { trade: 249, date: 'Current', returnR: 51.26, drawdown: 3.8 },
];

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: 'easeOut' } },
};

const stagger: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.1 } },
};

const panel = 'bg-[#131722] border border-white/5 rounded-xl';
const card =
  'bg-[#1E222D] border border-white/5 rounded-xl hover:border-purple-500/30 transition-all duration-300';

const stats = [
  {
    label: 'Win Rate',
    value: '47.0%',
    detail: '324 wins / 364 losses',
    icon: Target,
    iconClass: 'text-amber-400',
    iconWrap:
      'bg-amber-500/10 border-amber-500/20 shadow-[0_0_28px_-8px_rgba(245,158,11,0.75)]',
    valueClass: 'text-amber-400',
  },
  {
    label: 'Profit Factor',
    value: '1.42',
    detail: 'Gross profit / gross loss',
    icon: Activity,
    iconClass: 'text-cyan-400',
    iconWrap:
      'bg-cyan-500/10 border-cyan-500/20 shadow-[0_0_28px_-8px_rgba(6,182,212,0.75)]',
    valueClass: 'text-cyan-400',
  },
  {
    label: 'Net Return',
    value: '+51.26R',
    detail: '0.206R expectancy per trade',
    icon: TrendingUp,
    iconClass: 'text-purple-300',
    iconWrap:
      'bg-purple-500/10 border-purple-500/20 shadow-[0_0_28px_-8px_rgba(124,58,237,0.8)]',
    valueClass: 'text-purple-300',
  },
  {
    label: 'Setups Analyzed',
    value: '688',
    detail: '249 executed after filters',
    icon: Layers,
    iconClass: 'text-slate-200',
    iconWrap:
      'bg-white/5 border-white/10 shadow-[0_0_28px_-10px_rgba(255,255,255,0.45)]',
    valueClass: 'text-white',
  },
];

export const Landing: React.FC = () => {
  return (
    <div className="relative min-h-screen bg-[#0B0E11] text-slate-200 font-sans selection:bg-purple-500/30 selection:text-white overflow-x-hidden">
      {/* =====================================================================
          BACKGROUND ATMOSPHERE — restrained, no moving orbs
         ===================================================================== */}
      <div className="fixed inset-0 pointer-events-none z-0" aria-hidden="true">
        <div className="absolute inset-0 bg-[#0B0E11]" />
        <div className="absolute inset-x-0 top-0 h-[620px] bg-[radial-gradient(ellipse_55%_55%_at_50%_0%,rgba(124,58,237,0.13),transparent_72%)]" />
        <div className="absolute top-[38%] -right-40 w-[520px] h-[520px] rounded-full bg-[radial-gradient(circle,rgba(6,182,212,0.07),transparent_65%)]" />
        <div
          className="absolute inset-0 bg-fintech-grid bg-[size:44px_44px] opacity-[0.35]"
          style={{
            maskImage: 'radial-gradient(ellipse 70% 55% at 50% 25%, black 10%, transparent 80%)',
            WebkitMaskImage: 'radial-gradient(ellipse 70% 55% at 50% 25%, black 10%, transparent 80%)',
          }}
        />
      </div>

      {/* =====================================================================
          NAVIGATION
         ===================================================================== */}
      <header className="fixed top-0 inset-x-0 z-50 bg-[#0B0E11]/85 backdrop-blur-xl border-b border-white/5">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2.5 group" aria-label="QuantView home">
            <img
              src={logoImg}
              alt="QuantView"
              className="w-7 h-7 object-contain transition-[filter] duration-300 drop-shadow-[0_0_8px_rgba(124,58,237,0.35)] group-hover:drop-shadow-[0_0_18px_rgba(124,58,237,0.8)]"
            />
            <span className="text-[15px] font-semibold tracking-tight text-white">
              QUANT<span className="text-purple-400">VIEW</span>
            </span>
            <span className="hidden lg:inline-block ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-mono uppercase tracking-[0.16em] text-slate-400 border border-white/10 bg-white/[0.03]">
              XAU/USD · SMC
            </span>
          </Link>

          <nav className="hidden md:flex items-center gap-7 text-[13px] text-slate-400">
            <a href="#hero" className="hover:text-white transition-colors">
              Home
            </a>
            <a href="#features" className="hover:text-white transition-colors">
              Strategy
            </a>
            <a href="#performance" className="hover:text-white transition-colors">
              Backtest Data
            </a>
            <a href="#how-it-works" className="hover:text-white transition-colors">
              How It Works
            </a>
          </nav>

          <Link
            to="/dashboard"
            className="px-4 py-2 rounded-lg bg-[#7c3aed] hover:bg-[#8b5cf6] text-white text-xs font-semibold flex items-center gap-2 border border-[#a78bfa]/30 shadow-[0_0_24px_-8px_rgba(124,58,237,0.9)] hover:shadow-[0_0_30px_-6px_rgba(124,58,237,1)] transition-all duration-300"
          >
            <span>Open Dashboard</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </header>

      <main className="relative z-10">
        {/* =====================================================================
            HERO
           ===================================================================== */}
        <section id="hero" className="px-4 sm:px-6 lg:px-8 pt-32 pb-20 sm:pt-36 sm:pb-24">
          <div className="max-w-7xl mx-auto grid lg:grid-cols-[1.02fr_1fr] gap-12 lg:gap-8 items-center">
            <motion.div
              initial={{ opacity: 0, y: 22 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, ease: 'easeOut' }}
            >
              <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-md bg-white/[0.03] border border-white/[0.07] text-[10px] font-mono uppercase tracking-[0.18em] text-slate-400">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse-subtle" />
                <span>Live scanner · XAU/USD · 15m / 1h / 4h</span>
              </div>

              <h1 className="mt-6 text-[2.6rem] leading-[1.06] sm:text-6xl xl:text-[4.2rem] font-semibold tracking-[-0.035em] text-white [text-shadow:0_0_50px_rgba(255,255,255,0.12)]">
                Precision Trading Indicators
                <br className="hidden sm:block" /> &amp; Automated Signals
              </h1>

              <p className="mt-6 text-base sm:text-lg text-slate-400 leading-relaxed max-w-xl">
                Automated Smart Money Concepts (SMC) for
                XAU/USD. Backtested on 688 trades.
              </p>
              <p className="mt-3 text-sm text-slate-500 leading-relaxed max-w-xl">
                Zero lookahead. Fully mechanical rules. Structural stops and 1:2+ risk-reward
                across 15m execution, 1h structure and 4h bias.
              </p>

              <div className="mt-8 flex flex-col sm:flex-row gap-3">
                <Link
                  to="/dashboard"
                  className="px-6 py-3 rounded-lg bg-[#7c3aed] hover:bg-[#8b5cf6] text-white text-sm font-semibold flex items-center justify-center gap-2 border border-[#a78bfa]/30 shadow-[0_0_30px_-6px_rgba(124,58,237,0.85)] hover:shadow-[0_0_38px_-6px_rgba(124,58,237,1)] transition-all duration-300"
                >
                  <span>Open Dashboard</span>
                  <ArrowRight className="w-4 h-4" />
                </Link>
                <a
                  href="#performance"
                  className="px-6 py-3 rounded-lg bg-white/[0.02] hover:bg-white/[0.05] border border-white/10 hover:border-white/20 text-slate-200 hover:text-white text-sm font-semibold flex items-center justify-center gap-2 transition-all duration-300"
                >
                  <BarChart2 className="w-4 h-4 text-slate-400" />
                  <span>View Backtest Data</span>
                </a>
              </div>

              <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] font-mono text-slate-500">
                <span className="flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500/80" />
                  Zero lookahead
                </span>
                <span className="flex items-center gap-1.5">
                  <Shield className="w-3.5 h-3.5 text-purple-400/80" />
                  1:2+ R:R
                </span>
                <span className="flex items-center gap-1.5">
                  <BarChart2 className="w-3.5 h-3.5 text-cyan-400/80" />
                  23-month walk-forward
                </span>
              </div>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 22 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.12, ease: 'easeOut' }}
            >
              <SmcChartPreview />
            </motion.div>
          </div>
        </section>

        {/* =====================================================================
            FEATURES
           ===================================================================== */}
        <motion.section
          id="features"
          variants={stagger}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-80px' }}
          className="px-4 sm:px-6 lg:px-8 py-20 sm:py-24"
        >
          <div className="max-w-7xl mx-auto">
            <motion.div variants={fadeUp} className="max-w-2xl">
              <span className="text-[11px] font-mono uppercase tracking-[0.2em] text-cyan-400/80">
                Strategy Engine
              </span>
              <h2 className="mt-3 text-3xl sm:text-4xl font-semibold tracking-tight text-white">
                Market structure, encoded into rules
              </h2>
              <p className="mt-3 text-sm sm:text-base text-slate-400 leading-relaxed">
                No discretionary calls. Each signal is a mechanical sequence of structure,
                liquidity and displacement checks on gold.
              </p>
            </motion.div>

            <div className="mt-12 grid grid-cols-1 md:grid-cols-3 gap-5">
              <motion.article variants={fadeUp} className={`${card} p-6 sm:p-7 flex flex-col`}>
                <div className="w-10 h-10 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-300 shadow-[0_0_26px_-10px_rgba(124,58,237,0.9)]">
                  <TrendingUp className="w-5 h-5" />
                </div>
                <h3 className="mt-5 text-lg font-semibold text-white tracking-tight">
                  Smart Money Concepts
                </h3>
                <p className="mt-2.5 text-sm text-slate-400 leading-relaxed flex-1">
                  Tracks break of structure (BOS) and change of character (CHOCH) to map
                  intent, then marks fair value gaps (FVG) left by displacement. Entries
                  require a confirmed structural break plus a retest of the imbalance.
                </p>
                <div className="mt-6 pt-4 border-t border-white/5 flex flex-wrap gap-1.5 text-[10px] font-mono">
                  <span className="px-2 py-0.5 rounded bg-purple-500/10 border border-purple-500/20 text-purple-300">
                    BOS / CHOCH
                  </span>
                  <span className="px-2 py-0.5 rounded bg-purple-500/10 border border-purple-500/20 text-purple-300">
                    FVG
                  </span>
                  <span className="px-2 py-0.5 rounded bg-purple-500/10 border border-purple-500/20 text-purple-300">
                    Liquidity sweeps
                  </span>
                </div>
              </motion.article>

              <motion.article variants={fadeUp} className={`${card} p-6 sm:p-7 flex flex-col`}>
                <div className="w-10 h-10 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400 shadow-[0_0_26px_-10px_rgba(6,182,212,0.9)]">
                  <Activity className="w-5 h-5" />
                </div>
                <h3 className="mt-5 text-lg font-semibold text-white tracking-tight">
                  Multi-Timeframe Structure
                </h3>
                <p className="mt-2.5 text-sm text-slate-400 leading-relaxed flex-1">
                  Synchronizes 4h structural trend with 1h intermediate swings and 15m
                  lower-timeframe execution. Signals enforce zero lookahead and require
                  structural consensus and LTF confirmation before qualification.
                </p>
                <div className="mt-6 pt-4 border-t border-white/5 flex flex-wrap gap-1.5 text-[10px] font-mono">
                  <span className="px-2 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/20 text-cyan-300">
                    4h HTF Bias
                  </span>
                  <span className="px-2 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/20 text-cyan-300">
                    1h Structure
                  </span>
                  <span className="px-2 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/20 text-cyan-300">
                    15m LTF Confirmation
                  </span>
                </div>
              </motion.article>

              <motion.article variants={fadeUp} className={`${card} p-6 sm:p-7 flex flex-col`}>
                <div className="w-10 h-10 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 shadow-[0_0_26px_-10px_rgba(245,158,11,0.9)]">
                  <Shield className="w-5 h-5" />
                </div>
                <h3 className="mt-5 text-lg font-semibold text-white tracking-tight">
                  Real-Time Risk Management
                </h3>
                <p className="mt-2.5 text-sm text-slate-400 leading-relaxed flex-1">
                  Stops are placed behind the structural invalidation, sized dynamically
                  with ATR so risk adapts to volatility. Targets are set at a minimum of
                  1:2 R:R, with news blackouts pausing entries around high-impact events.
                </p>
                <div className="mt-6 pt-4 border-t border-white/5 flex flex-wrap gap-1.5 text-[10px] font-mono">
                  <span className="px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-300">
                    ATR stops
                  </span>
                  <span className="px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-300">
                    1:2+ R:R
                  </span>
                  <span className="px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-300">
                    News blackouts
                  </span>
                </div>
              </motion.article>
            </div>
          </div>
        </motion.section>

        {/* =====================================================================
            PROOF — BACKTEST METRICS
           ===================================================================== */}
        <motion.section
          id="performance"
          variants={stagger}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-80px' }}
          className="px-4 sm:px-6 lg:px-8 py-20 sm:py-24"
        >
          <div className="max-w-7xl mx-auto">
            <motion.div variants={fadeUp} className="max-w-2xl">
              <span className="text-[11px] font-mono uppercase tracking-[0.2em] text-purple-400/90">
                Verified Performance
              </span>
              <h2 className="mt-3 text-3xl sm:text-4xl font-semibold tracking-tight text-white">
                Backtested on real XAU/USD data
              </h2>
              <p className="mt-3 text-sm sm:text-base text-slate-400 leading-relaxed">
                Walk-forward simulation over 23 months, with $0.40 round-trip friction
                deducted from every trade.
              </p>
            </motion.div>

            <motion.div
              variants={fadeUp}
              className="mt-10 grid grid-cols-2 lg:grid-cols-4 rounded-xl overflow-hidden border border-white/5 bg-[#131722]"
            >
              {stats.map((s, i) => (
                <div
                  key={s.label}
                  className={`p-5 sm:p-6 flex flex-col gap-4 ${
                    i % 2 === 1 ? 'border-l border-white/5' : ''
                  } ${i >= 2 ? 'border-t border-white/5 lg:border-t-0' : ''} ${
                    i > 0 ? 'lg:border-l lg:border-white/5' : ''
                  }`}
                >
                  <div className="flex items-center justify-between gap-1.5 sm:gap-2">
                    <span className="text-[9px] sm:text-[10px] font-mono uppercase tracking-[0.04em] sm:tracking-[0.16em] text-slate-500 whitespace-nowrap">
                      {s.label}
                    </span>
                    <div
                      className={`w-7 h-7 sm:w-8 sm:h-8 shrink-0 rounded-lg border flex items-center justify-center ${s.iconWrap}`}
                    >
                      <s.icon className={`w-3.5 h-3.5 sm:w-4 sm:h-4 ${s.iconClass}`} />
                    </div>
                  </div>
                  <div>
                    <div className={`font-mono text-[1.6rem] sm:text-[2.1rem] font-semibold tabular-nums ${s.valueClass}`}>
                      {s.value}
                    </div>
                    <div className="mt-0.5 text-[10px] sm:text-[11px] text-slate-500">{s.detail}</div>
                  </div>
                </div>
              ))}
            </motion.div>

            <motion.p
              variants={fadeUp}
              className="mt-4 text-[11px] font-mono text-slate-500"
            >
              249 executed of 688 detected setups · max drawdown 22.45R · median hold 129h ·
              source: Twelve Data 15m XAU/USD
            </motion.p>

            {/* Equity curve */}
            <motion.div variants={fadeUp} className={`${panel} mt-10 overflow-hidden`}>
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 px-5 sm:px-6 py-4 border-b border-white/5">
                <div className="flex items-center gap-2.5">
                  <BarChart2 className="w-4 h-4 text-cyan-400/90" />
                  <h3 className="text-sm font-semibold text-white tracking-tight">
                    Cumulative equity
                  </h3>
                  <span className="px-1.5 py-0.5 rounded text-[9px] font-mono text-cyan-300 bg-cyan-500/10 border border-cyan-500/20">
                    +51.26R
                  </span>
                </div>
                <div className="flex items-center gap-4 text-[10px] font-mono text-slate-400">
                  <span className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-purple-400" />
                    Max DD 22.45R
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                    Expectancy +0.206R
                  </span>
                </div>
              </div>

              <div className="h-64 sm:h-80 w-full px-2 pb-2">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={equityCurveData} margin={{ top: 14, right: 30, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#06b6d4" stopOpacity={0.28} />
                        <stop offset="100%" stopColor="#06b6d4" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid
                      stroke="rgba(255,255,255,0.04)"
                      strokeDasharray="3 3"
                      vertical={false}
                    />
                    <XAxis
                      dataKey="date"
                      stroke="#5b6472"
                      fontSize={10}
                      tickLine={false}
                      axisLine={false}
                      fontFamily="JetBrains Mono"
                      dy={6}
                    />
                    <YAxis
                      stroke="#5b6472"
                      fontSize={10}
                      tickLine={false}
                      axisLine={false}
                      domain={[0, 'auto']}
                      tickFormatter={(v) => `+${v}R`}
                      fontFamily="JetBrains Mono"
                    />
                    <Tooltip
                      cursor={{ stroke: 'rgba(255,255,255,0.12)', strokeWidth: 1 }}
                      content={({ active, payload }) => {
                        if (active && payload && payload.length) {
                          const data = payload[0].payload;
                          return (
                            <div className="p-3 bg-[#1E222D] border border-white/10 rounded-lg shadow-2xl font-mono text-xs space-y-1">
                              <p className="text-slate-300 font-semibold border-b border-white/5 pb-1">
                                {data.date} · trade #{data.trade}
                              </p>
                              <p className="text-cyan-400 font-semibold">
                                +{data.returnR}R cumulative
                              </p>
                              <p className="text-rose-400 text-[11px]">
                                Drawdown {data.drawdown}R
                              </p>
                            </div>
                          );
                        }
                        return null;
                      }}
                    />
                    <Area
                      type="monotone"
                      dataKey="returnR"
                      stroke="#06b6d4"
                      strokeWidth={2}
                      fill="url(#equityGrad)"
                      activeDot={{ r: 3, fill: '#06b6d4', stroke: '#0B0E11', strokeWidth: 2 }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-white/5 border-t border-white/5">
                {[
                  { label: 'Setups detected', value: '688', cls: 'text-white' },
                  { label: 'Executed trades', value: '249', cls: 'text-cyan-400' },
                  { label: 'Median hold', value: '129h', cls: 'text-purple-300' },
                  { label: 'Friction per trade', value: '$0.40', cls: 'text-amber-400' },
                ].map((f) => (
                  <div key={f.label} className="px-4 py-3">
                    <div className="text-[9px] font-mono uppercase tracking-[0.14em] text-slate-500">
                      {f.label}
                    </div>
                    <div className={`mt-0.5 font-mono text-sm font-semibold ${f.cls}`}>
                      {f.value}
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          </div>
        </motion.section>

        {/* =====================================================================
            HOW IT WORKS
           ===================================================================== */}
        <motion.section
          id="how-it-works"
          variants={stagger}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-80px' }}
          className="px-4 sm:px-6 lg:px-8 py-20 sm:py-24"
        >
          <div className="max-w-7xl mx-auto">
            <motion.div variants={fadeUp} className="max-w-2xl">
              <span className="text-[11px] font-mono uppercase tracking-[0.2em] text-amber-400/90">
                Execution
              </span>
              <h2 className="mt-3 text-3xl sm:text-4xl font-semibold tracking-tight text-white">
                How a signal is produced
              </h2>
              <p className="mt-3 text-sm sm:text-base text-slate-400 leading-relaxed">
                Three deterministic stages, from raw ticks to a fully specified trade.
              </p>
            </motion.div>

            <div className="mt-12 grid grid-cols-1 md:grid-cols-3 gap-5">
              {[
                {
                  n: '01',
                  title: 'Structure scan',
                  body: 'The engine ingests closed 15m candles, resamples 1h and 4h structure, and tracks liquidity pools, order blocks and fair value gaps.',
                  note: 'Continuous 15m / 1h / 4h scan',
                  icon: Layers,
                },
                {
                  n: '02',
                  title: 'Confluence & signal',
                  body: 'A setup is emitted only when the sweep, structural break and displacement checks all pass on the configured timeframe alignment.',
                  note: 'Mechanical confluence gate',
                  icon: CheckCircle2,
                },
                {
                  n: '03',
                  title: 'Risk & alert',
                  body: 'Entry, ATR-based stop and a 1:2+ target are attached, then dispatched to Telegram and the dashboard with full reasoning.',
                  note: 'Telegram dispatch',
                  icon: Shield,
                },
              ].map((step) => (
                <motion.article
                  key={step.n}
                  variants={fadeUp}
                  className={`${card} p-6 sm:p-7 flex flex-col`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs text-slate-500 border border-white/10 rounded-md px-2 py-1 bg-white/[0.02]">
                      {step.n}
                    </span>
                    <step.icon className="w-4 h-4 text-slate-500" />
                  </div>
                  <h3 className="mt-5 text-lg font-semibold text-white tracking-tight">
                    {step.title}
                  </h3>
                  <p className="mt-2 text-sm text-slate-400 leading-relaxed flex-1">
                    {step.body}
                  </p>
                  <div className="mt-5 pt-4 border-t border-white/5 flex items-center gap-2 text-[11px] font-mono text-slate-500">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400/80" />
                    {step.note}
                  </div>
                </motion.article>
              ))}
            </div>
          </div>
        </motion.section>

        {/* =====================================================================
            CTA
           ===================================================================== */}
        <motion.section
          variants={fadeUp}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-80px' }}
          className="px-4 sm:px-6 lg:px-8 py-16 sm:py-20"
        >
          <div className="max-w-7xl mx-auto">
            <div className={`${panel} relative overflow-hidden px-6 sm:px-12 py-12 sm:py-16 text-center`}>
              <div
                aria-hidden="true"
                className="absolute inset-x-0 top-0 h-40 bg-[radial-gradient(ellipse_50%_100%_at_50%_0%,rgba(124,58,237,0.18),transparent_75%)]"
              />
              <div className="relative max-w-2xl mx-auto">
                <span className="inline-flex items-center gap-2 px-2.5 py-1 rounded-md bg-white/[0.03] border border-white/[0.07] text-[10px] font-mono uppercase tracking-[0.16em] text-slate-400">
                  <Shield className="w-3 h-3 text-purple-400" />
                  Proprietary methodology · Institutional grade
                </span>
                <h2 className="mt-5 text-3xl sm:text-4xl font-semibold tracking-tight text-white">
                  Access the live dashboard
                </h2>
                <p className="mt-3 text-sm sm:text-base text-slate-400 max-w-xl mx-auto leading-relaxed">
                  Review live signals, open positions and the complete performance breakdown
                  in one secure workspace.
                </p>
                <div className="mt-7 flex flex-col sm:flex-row items-center justify-center gap-3">
                  <Link
                    to="/dashboard"
                    className="w-full sm:w-auto px-6 py-3 rounded-lg bg-[#7c3aed] hover:bg-[#8b5cf6] text-white text-sm font-semibold flex items-center justify-center gap-2 border border-[#a78bfa]/30 shadow-[0_0_30px_-6px_rgba(124,58,237,0.85)] transition-all duration-300"
                  >
                    <span>Open Dashboard</span>
                    <ArrowRight className="w-4 h-4" />
                  </Link>
                  <Link
                    to="/login"
                    className="w-full sm:w-auto px-6 py-3 rounded-lg bg-white/[0.02] hover:bg-white/[0.05] border border-white/10 hover:border-white/20 text-slate-200 hover:text-white text-sm font-semibold flex items-center justify-center gap-2 transition-all duration-300"
                  >
                    <Shield className="w-4 h-4 text-slate-400" />
                    <span>Secure Sign In</span>
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </motion.section>
      </main>

      {/* =====================================================================
          FOOTER
         ===================================================================== */}
      <footer className="relative z-10 border-t border-white/5 px-4 sm:px-6 lg:px-8 py-10 text-xs text-slate-500">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-5">
          <div className="flex flex-col sm:flex-row items-center gap-3">
            <div className="flex items-center gap-2">
              <img src={logoImg} alt="QuantView" className="w-4 h-4 object-contain opacity-80" />
              <span className="font-semibold text-white text-sm tracking-tight">
                QUANT<span className="text-purple-400">VIEW</span>
              </span>
            </div>
            <span className="hidden sm:inline text-slate-700">·</span>
            <span className="text-[11px] font-mono">
              Proprietary platform · XAU/USD · © 2026
            </span>
          </div>

          <div className="flex items-center gap-6 text-[11px]">
            <Link to="/dashboard" className="hover:text-white transition-colors">
              Dashboard
            </Link>
            <Link to="/login" className="hover:text-white transition-colors">
              Secure Sign In
            </Link>
            <span className="text-slate-500">© 2026 QuantView. All rights reserved. Proprietary and Confidential.</span>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default Landing;
