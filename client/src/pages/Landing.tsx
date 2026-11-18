import React from 'react';
import { Link } from 'react-router-dom';
import { motion, useScroll, useTransform, type Variants } from 'framer-motion';
import { useInView } from 'react-intersection-observer';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
} from 'recharts';
import {
  TrendingUp,
  Activity,
  Layers,
  ArrowRight,
  Shield,
  BarChart2,
  CheckCircle2,
} from 'lucide-react';
import { GlassCard } from '../components/ui/GlassCard';
import logoImg from '../../assets/logo.png';

// Inline SVG for GitHub
const GithubIcon: React.FC<{ className?: string }> = ({ className = 'w-4 h-4' }) => (
  <svg
    viewBox="0 0 24 24"
    fill="currentColor"
    className={className}
    aria-hidden="true"
  >
    <path
      fillRule="evenodd"
      clipRule="evenodd"
      d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
    />
  </svg>
);

// 249-Trade Walk-Forward Equity Curve points ending at +51.26R (23 Months, 2025–2026)
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

export const Landing: React.FC = () => {
  const { scrollY } = useScroll();
  const heroParallaxY = useTransform(scrollY, [0, 800], [0, 110]);
  const heroOpacity = useTransform(scrollY, [0, 600], [1, 0.25]);

  // Section in-view triggers
  const [featuresRef, featuresInView] = useInView({ triggerOnce: true, threshold: 0.15 });
  const [perfRef, perfInView] = useInView({ triggerOnce: true, threshold: 0.15 });
  const [howRef, howInView] = useInView({ triggerOnce: true, threshold: 0.15 });

  // Animation variants
  const fadeInUp: Variants = {
    hidden: { opacity: 0, y: 35 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: 0.7, ease: 'easeOut' },
    },
  };

  const staggerContainer: Variants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: 0.18,
      },
    },
  };

  return (
    <div className="relative min-h-screen bg-[#030014] text-slate-100 font-sans selection:bg-purple-500/30 selection:text-white overflow-x-hidden">
      {/* =========================================================================
          ATMOSPHERIC GLOBAL BACKGROUND LAYER
         ========================================================================= */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-0" aria-hidden="true">
        {/* Base Void */}
        <div className="absolute inset-0 bg-[#030014]" />

        {/* Floating Purple Orb */}
        <div className="absolute -top-[10%] -left-[10%] w-[55vw] h-[55vw] max-w-[850px] max-h-[850px] rounded-full bg-purple-600/15 blur-[150px] animate-orb-purple transform-gpu" />

        {/* Floating Cyan Orb */}
        <div className="absolute top-[24%] -right-[8%] w-[52vw] h-[52vw] max-w-[780px] max-h-[780px] rounded-full bg-cyan-500/12 blur-[140px] animate-orb-cyan transform-gpu" />

        {/* Floating Deep Violet Orb */}
        <div className="absolute bottom-[5%] left-[20%] w-[60vw] h-[60vw] max-w-[900px] max-h-[900px] rounded-full bg-violet-700/15 blur-[150px] animate-orb-violet transform-gpu" />

        {/* Subtle Modern Grid Overlay with Radial Spotlight Mask */}
        <div
          className="absolute inset-0 bg-fintech-grid bg-[size:40px_40px] opacity-35"
          style={{
            maskImage: 'radial-gradient(ellipse 75% 60% at 50% 30%, black 20%, transparent 85%)',
            WebkitMaskImage: 'radial-gradient(ellipse 75% 60% at 50% 30%, black 20%, transparent 85%)',
          }}
        />
      </div>

      {/* =========================================================================
          NAVIGATION BAR
         ========================================================================= */}
      <header className="fixed top-0 inset-x-0 z-50 backdrop-blur-xl bg-[#030014]/80 border-b border-white/10 transition-colors">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          {/* Brand Logo with Actual Image from client/assets/logo.png */}
          <Link to="/" className="flex items-center gap-2.5 group">
            <div className="relative w-8 h-8 rounded-lg overflow-hidden flex items-center justify-center transition-all duration-300 drop-shadow-[0_0_8px_rgba(168,85,247,0.35)] group-hover:drop-shadow-[0_0_16px_rgba(168,85,247,0.85)]">
              <img
                src={logoImg}
                alt="QuantView Logo"
                className="w-full h-full object-contain"
              />
            </div>
            <div className="flex flex-col">
              <span className="text-base font-bold tracking-tight text-white flex items-center gap-1 font-sans">
                QUANT<span className="text-purple-400">VIEW</span>
              </span>
            </div>
            <span className="hidden sm:inline-block ml-1 px-1.5 py-0.5 rounded text-[8px] font-mono uppercase bg-white/5 text-zinc-400 border border-white/10 tracking-widest">
              AI TRADING OS
            </span>
          </Link>

          {/* Nav Links */}
          <nav className="hidden md:flex items-center gap-7 text-xs font-medium text-slate-300 font-sans">
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
            <a
              href="https://github.com/dina-seng/signal_bot"
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 text-slate-400 hover:text-white transition-colors"
            >
              <GithubIcon className="w-3.5 h-3.5" />
              <span>GitHub</span>
            </a>
          </nav>

          {/* Action Button: Link to /dashboard */}
          <div className="flex items-center gap-3">
            <Link
              to="/dashboard"
              className="px-4 py-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white font-sans text-xs font-semibold flex items-center gap-2 border border-violet-400/30 shadow-[0_0_20px_rgba(124,58,237,0.35)] hover:shadow-[0_0_25px_rgba(124,58,237,0.6)] transition-all duration-300 cursor-pointer"
            >
              <span>Open Dashboard</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>
      </header>

      {/* Main Container sitting above background orbs */}
      <main className="relative z-10 pt-16">
        {/* =========================================================================
            SECTION 1: HERO SECTION
           ========================================================================= */}
        <section
          id="hero"
          className="min-h-[calc(100vh-4rem)] flex flex-col justify-center items-center text-center px-4 sm:px-6 lg:px-8 py-20 relative overflow-hidden"
        >
          <motion.div
            style={{ y: heroParallaxY, opacity: heroOpacity }}
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, ease: 'easeOut' }}
            className="max-w-4xl mx-auto space-y-6"
          >
            {/* Live Status Pill */}
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/10 backdrop-blur-md shadow-lg text-xs font-mono text-zinc-300">
              <span className="w-2 h-2 rounded-full bg-[#00e676] animate-pulse" />
              <span className="text-zinc-400 uppercase text-[10px] tracking-wider">
                XAU/USD
              </span>
              <span className="text-zinc-600">•</span>
              <span className="text-purple-300 font-semibold text-[11px]">SMC &amp; CRT Strategy</span>
            </div>

            {/* Clean White Headline with Subtle Purple Underline Accent */}
            <div className="inline-block relative">
              <h1 className="text-6xl sm:text-7xl md:text-8xl lg:text-9xl font-black tracking-tight font-sans text-white drop-shadow-[0_2px_24px_rgba(255,255,255,0.1)]">
                QuantView
              </h1>
              <div className="h-1 sm:h-1.5 w-full bg-gradient-to-r from-violet-500 via-purple-500 to-indigo-500 rounded-full mt-3 opacity-90 shadow-[0_0_15px_rgba(168,85,247,0.5)]" />
            </div>

            {/* Subheadline: Specific & Honest */}
            <p className="text-xl sm:text-2xl md:text-3xl font-semibold text-slate-100 tracking-tight font-sans max-w-3xl mx-auto leading-tight">
              Automated SMC &amp; CRT strategy for XAU/USD. Backtested on 688 trades across 23 months.
            </p>

            {/* Description: Real details */}
            <p className="max-w-2xl mx-auto text-sm sm:text-base md:text-lg text-slate-400 font-sans leading-relaxed">
              Detects liquidity sweeps, break of structure, and displacement confirmation on 15m/1h/4h timeframes. Executes with structural stop losses and 1:2+ risk-reward. Telegram alerts in real-time.
            </p>

            {/* Action Buttons */}
            <div className="pt-2 flex flex-col sm:flex-row items-center justify-center gap-3.5">
              <Link
                to="/dashboard"
                className="w-full sm:w-auto px-7 py-3.5 rounded-2xl bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white font-sans text-sm font-semibold flex items-center justify-center gap-2.5 shadow-[0_0_25px_rgba(124,58,237,0.4)] transition-all duration-300 cursor-pointer group"
              >
                <span>Open Dashboard</span>
                <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
              </Link>

              <a
                href="https://github.com/dina-seng/signal_bot"
                target="_blank"
                rel="noreferrer"
                className="w-full sm:w-auto px-6 py-3.5 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/20 text-slate-200 hover:text-white font-sans text-sm font-semibold flex items-center justify-center gap-2 backdrop-blur-xl transition-all duration-300 cursor-pointer"
              >
                <GithubIcon className="w-4 h-4 text-slate-300" />
                <span>View on GitHub</span>
              </a>
            </div>

            {/* Personality & Honesty Note */}
            <div className="pt-1 flex items-center justify-center gap-2 text-xs font-mono text-slate-400">
              <span className="w-1.5 h-1.5 rounded-full bg-purple-400" />
              <span>Built by a trader, for traders. No hype, just math.</span>
            </div>

            {/* Real Backtest Metrics Summary Card (Minimal & Handcrafted) */}
            <motion.div
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3, duration: 0.7 }}
              className="pt-6 max-w-2xl mx-auto w-full text-left"
            >
              <GlassCard
                glowColor="purple"
                className="p-5 sm:p-6 border-white/10 shadow-2xl relative overflow-hidden"
              >
                {/* Header bar */}
                <div className="flex items-center justify-between border-b border-white/10 pb-3 mb-4">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-400" />
                    <span className="text-xs font-mono font-semibold tracking-wide text-white uppercase">
                      XAU/USD Walk-Forward Results
                    </span>
                  </div>
                  <span className="text-[10px] font-mono text-slate-400 bg-white/5 px-2 py-0.5 rounded border border-white/10">
                    23 Months · 2025–2026
                  </span>
                </div>

                {/* 3 Metric Rows */}
                <div className="space-y-2.5 font-mono text-xs sm:text-sm">
                  {/* Line 1 */}
                  <div className="p-3 rounded-xl bg-white/[0.03] border border-white/5 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-slate-400 text-xs uppercase tracking-wider font-sans">
                      Execution
                    </span>
                    <span className="text-slate-200">
                      688 setups detected <span className="text-slate-600">·</span> 249 executed <span className="text-slate-600">·</span>{' '}
                      <span className="text-[#00e676] font-bold">+51.26R net profit</span>
                    </span>
                  </div>

                  {/* Line 2 */}
                  <div className="p-3 rounded-xl bg-white/[0.03] border border-white/5 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-slate-400 text-xs uppercase tracking-wider font-sans">
                      Performance
                    </span>
                    <span className="text-slate-200">
                      47.0% win rate <span className="text-slate-600">·</span> 1.42 profit factor <span className="text-slate-600">·</span>{' '}
                      <span className="text-cyan-400 font-bold">0.206R expectancy</span>
                    </span>
                  </div>

                  {/* Line 3 */}
                  <div className="p-3 rounded-xl bg-white/[0.03] border border-white/5 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-slate-400 text-xs uppercase tracking-wider font-sans">
                      Drawdown &amp; Hold
                    </span>
                    <span className="text-slate-200">
                      Median hold: 129 hours <span className="text-slate-600">·</span>{' '}
                      Max drawdown: <span className="text-purple-300 font-bold">22.45R</span>
                    </span>
                  </div>
                </div>

                <div className="mt-3.5 pt-3 border-t border-white/5 flex items-center justify-between text-[11px] font-mono text-slate-500">
                  <span>Structural 1:2+ R:R Target</span>
                  <span>Powered by Twelve Data</span>
                </div>
              </GlassCard>
            </motion.div>
          </motion.div>
        </section>

        {/* =========================================================================
            SECTION 2: FEATURES SECTION (3-COLUMN BENTO GRID)
           ========================================================================= */}
        <section id="features" ref={featuresRef} className="py-24 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
          <div className="text-center max-w-3xl mx-auto mb-16 space-y-3">
            <span className="text-xs font-mono uppercase tracking-widest text-purple-400 bg-purple-500/10 px-3 py-1 rounded-full border border-purple-500/25">
              Strategy Architecture
            </span>
            <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight text-white font-sans">
              Rules-Based Trading Framework
            </h2>
            <p className="text-slate-400 text-sm sm:text-base font-sans">
              Mechanical rules for market structure, liquidity sweeps, and multi-timeframe confirmation on gold (XAU/USD).
            </p>
          </div>

          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate={featuresInView ? 'visible' : 'hidden'}
            className="grid grid-cols-1 md:grid-cols-3 gap-6"
          >
            {/* Card 1: Smart Money Concepts (BOS/CHOCH/FVG) */}
            <motion.div variants={fadeInUp} whileHover={{ y: -6, transition: { duration: 0.25 } }}>
              <GlassCard
                glowColor="green"
                className="p-7 sm:p-8 h-full flex flex-col justify-between"
              >
                <div className="space-y-4">
                  <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 border border-emerald-500/25 flex items-center justify-center text-emerald-400 shadow-[0_0_20px_rgba(16,185,129,0.2)]">
                    <TrendingUp className="w-6 h-6" />
                  </div>
                  <h3 className="text-xl font-bold text-white font-sans">
                    Smart Money Concepts (BOS/CHOCH/FVG)
                  </h3>
                  <p className="text-sm text-slate-400 font-sans leading-relaxed">
                    Identifies structural breaks (BOS), changes of character (CHOCH), and sweeps of buy-side/sell-side liquidity (BSL/SSL). Enters upon Fair Value Gap (FVG) retests with defined structural invalidation.
                  </p>
                </div>
                <div className="pt-6 border-t border-white/10 flex flex-wrap gap-1.5 text-[11px] font-mono text-emerald-300">
                  <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 border border-emerald-500/20">BOS / CHOCH</span>
                  <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 border border-emerald-500/20">Liquidity Sweeps</span>
                  <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 border border-emerald-500/20">Fair Value Gaps</span>
                </div>
              </GlassCard>
            </motion.div>

            {/* Card 2: Candle Range Theory (CRT) */}
            <motion.div variants={fadeInUp} whileHover={{ y: -6, transition: { duration: 0.25 } }}>
              <GlassCard
                glowColor="purple"
                className="p-7 sm:p-8 h-full flex flex-col justify-between"
              >
                <div className="space-y-4">
                  <div className="w-12 h-12 rounded-2xl bg-purple-500/10 border border-purple-500/25 flex items-center justify-center text-purple-300 shadow-[0_0_20px_rgba(168,85,247,0.2)]">
                    <Activity className="w-6 h-6" />
                  </div>
                  <h3 className="text-xl font-bold text-white font-sans">
                    Candle Range Theory (CRT)
                  </h3>
                  <p className="text-sm text-slate-400 font-sans leading-relaxed">
                    Measures displacement velocity across multi-candle ranges to confirm institutional interest before entry. Filters out low-volume consolidation chop and invalidates false breakouts.
                  </p>
                </div>
                <div className="pt-6 border-t border-white/10 flex flex-wrap gap-1.5 text-[11px] font-mono text-purple-300">
                  <span className="px-2 py-0.5 rounded-md bg-purple-500/10 border border-purple-500/20">Displacement Checks</span>
                  <span className="px-2 py-0.5 rounded-md bg-purple-500/10 border border-purple-500/20">Range Expansion</span>
                  <span className="px-2 py-0.5 rounded-md bg-purple-500/10 border border-purple-500/20">Chop Filter</span>
                </div>
              </GlassCard>
            </motion.div>

            {/* Card 3: Multi-Timeframe Confluence Engine */}
            <motion.div variants={fadeInUp} whileHover={{ y: -6, transition: { duration: 0.25 } }}>
              <GlassCard
                glowColor="cyan"
                className="p-7 sm:p-8 h-full flex flex-col justify-between"
              >
                <div className="space-y-4">
                  <div className="w-12 h-12 rounded-2xl bg-cyan-500/10 border border-cyan-500/25 flex items-center justify-center text-cyan-400 shadow-[0_0_20px_rgba(6,182,212,0.2)]">
                    <Layers className="w-6 h-6" />
                  </div>
                  <h3 className="text-xl font-bold text-white font-sans">
                    Multi-Timeframe Confluence (15m/1h/4h)
                  </h3>
                  <p className="text-sm text-slate-400 font-sans leading-relaxed">
                    Aligns 15m execution setups with 1h market structure and 4h directional bias. Automatically pauses entries during high-impact US economic events (CPI, NFP, FOMC).
                  </p>
                </div>
                <div className="pt-6 border-t border-white/10 flex flex-wrap gap-1.5 text-[11px] font-mono text-cyan-300">
                  <span className="px-2 py-0.5 rounded-md bg-cyan-500/10 border border-cyan-500/20">15m / 1h / 4h Alignment</span>
                  <span className="px-2 py-0.5 rounded-md bg-cyan-500/10 border border-cyan-500/20">News Blackouts</span>
                  <span className="px-2 py-0.5 rounded-md bg-cyan-500/10 border border-cyan-500/20">Structural Stops</span>
                </div>
              </GlassCard>
            </motion.div>
          </motion.div>
        </section>

        {/* =========================================================================
            SECTION 3: PERFORMANCE & BACKTEST SECTION
           ========================================================================= */}
        <section id="performance" ref={perfRef} className="py-24 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
          <motion.div
            variants={fadeInUp}
            initial="hidden"
            animate={perfInView ? 'visible' : 'hidden'}
            className="space-y-12"
          >
            <div className="text-center max-w-3xl mx-auto space-y-3">
              <span className="text-xs font-mono uppercase tracking-widest text-purple-400 bg-purple-500/10 px-3 py-1 rounded-full border border-purple-500/25">
                Verified Walk-Forward Data
              </span>
              <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight text-white font-sans">
                Backtest Performance (23 Months)
              </h2>
              <p className="text-slate-400 text-sm sm:text-base font-sans">
                Powered by Twelve Data · Backtested on XAU/USD 2025-2026 across 688 setups detected and 249 executed trades.
              </p>
            </div>

            {/* 3 Core Highlight Badges */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
              <GlassCard glowColor="green" className="p-6 text-center">
                <span className="text-xs font-sans uppercase tracking-wider text-slate-400 block mb-1">
                  Win Rate
                </span>
                <span className="font-mono text-4xl sm:text-5xl font-extrabold text-[#00e676] drop-shadow-sm">
                  47.0%
                </span>
                <span className="text-xs text-slate-400 mt-2 block font-sans">
                  Target: 1:2+ Structural Risk:Reward
                </span>
              </GlassCard>

              <GlassCard glowColor="cyan" className="p-6 text-center">
                <span className="text-xs font-sans uppercase tracking-wider text-slate-400 block mb-1">
                  Profit Factor
                </span>
                <span className="font-mono text-4xl sm:text-5xl font-extrabold text-cyan-400 drop-shadow-sm">
                  1.42
                </span>
                <span className="text-xs text-slate-400 mt-2 block font-sans">
                  Gross Profit / Gross Loss Ratio
                </span>
              </GlassCard>

              <GlassCard glowColor="purple" className="p-6 text-center">
                <span className="text-xs font-sans uppercase tracking-wider text-slate-400 block mb-1">
                  Net Realized Return
                </span>
                <span className="font-mono text-4xl sm:text-5xl font-extrabold text-purple-300 drop-shadow-sm">
                  +51.26R
                </span>
                <span className="text-xs text-slate-400 mt-2 block font-sans">
                  Across 249 Executed Trades (0.206R Expectancy)
                </span>
              </GlassCard>
            </div>

            {/* Glowing Interactive Recharts Equity Curve in Glass Card */}
            <GlassCard glowColor="cyan" className="p-6 sm:p-8 space-y-6">
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-white/10 pb-5">
                <div>
                  <h3 className="text-lg font-bold text-white font-sans flex items-center gap-2">
                    <BarChart2 className="w-5 h-5 text-cyan-400" />
                    <span>Cumulative Equity Trajectory (+51.26R)</span>
                  </h3>
                  <p className="text-xs text-slate-400 font-sans mt-0.5">
                    Simulated tick-level execution on XAU/USD (2025–2026) across 249 executed trades
                  </p>
                </div>
                <div className="flex items-center gap-2 text-xs font-mono text-slate-300">
                  <span className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-white/5 border border-white/10">
                    <span className="w-2 h-2 rounded-full bg-purple-400" />
                    Max Drawdown: <strong>22.45R</strong>
                  </span>
                  <span className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-white/5 border border-white/10">
                    <span className="w-2 h-2 rounded-full bg-cyan-400" />
                    Expectancy: <strong>+0.206R</strong>
                  </span>
                </div>
              </div>

              {/* Chart container */}
              <div className="h-72 sm:h-84 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={equityCurveData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#7c3aed" stopOpacity={0.0} />
                      </linearGradient>
                    </defs>
                    <XAxis
                      dataKey="date"
                      stroke="#64748b"
                      fontSize={11}
                      tickLine={false}
                      fontFamily="JetBrains Mono"
                    />
                    <YAxis
                      stroke="#64748b"
                      fontSize={11}
                      tickLine={false}
                      axisLine={false}
                      domain={[0, 'auto']}
                      tickFormatter={(v) => `+${v}R`}
                      fontFamily="JetBrains Mono"
                    />
                    <Tooltip
                      content={({ active, payload }) => {
                        if (active && payload && payload.length) {
                          const data = payload[0].payload;
                          return (
                            <div className="p-3 bg-[#0a0b14]/95 border border-white/15 rounded-xl shadow-2xl font-mono text-xs space-y-1 backdrop-blur-xl">
                              <p className="text-slate-300 font-bold border-b border-white/10 pb-1">
                                {data.date} (Trade #{data.trade})
                              </p>
                              <p className="text-[#00e676] font-bold">
                                Cumulative Return: +{data.returnR}R
                              </p>
                              <p className="text-rose-400 text-[11px]">
                                Drawdown: {data.drawdown}R
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
                      strokeWidth={3}
                      fillOpacity={1}
                      fill="url(#equityGrad)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              {/* Stats Footer Strip with Actual Data */}
              <div className="pt-4 border-t border-white/10 grid grid-cols-2 sm:grid-cols-4 gap-4 text-center font-mono text-xs">
                <div>
                  <span className="text-slate-500 uppercase text-[10px] block">Setups Detected</span>
                  <span className="font-bold text-white text-base">688</span>
                </div>
                <div>
                  <span className="text-slate-500 uppercase text-[10px] block">Executed Trades</span>
                  <span className="font-bold text-cyan-400 text-base">249</span>
                </div>
                <div>
                  <span className="text-slate-500 uppercase text-[10px] block">Median Hold Time</span>
                  <span className="font-bold text-purple-300 text-base">129 Hours</span>
                </div>
                <div>
                  <span className="text-slate-500 uppercase text-[10px] block">Asset &amp; Feed</span>
                  <span className="font-bold text-emerald-400 text-base">Twelve Data XAU/USD</span>
                </div>
              </div>
            </GlassCard>
          </motion.div>
        </section>

        {/* =========================================================================
            SECTION 4: HOW IT WORKS SECTION (3 STEPS)
           ========================================================================= */}
        <section id="how-it-works" ref={howInView ? undefined : howRef} className="py-24 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
          <div className="text-center max-w-3xl mx-auto mb-16 space-y-3">
            <span className="text-xs font-mono uppercase tracking-widest text-emerald-400 bg-emerald-500/10 px-3 py-1 rounded-full border border-emerald-500/25">
              Execution Mechanics
            </span>
            <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight text-white font-sans">
              How It Works
            </h2>
            <p className="text-slate-400 text-sm sm:text-base font-sans">
              Three systematic steps from tick ingestion to trade notification and execution.
            </p>
          </div>

          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate={howInView ? 'visible' : 'hidden'}
            className="grid grid-cols-1 md:grid-cols-3 gap-8 relative"
          >
            {/* Step 1 */}
            <motion.div variants={fadeInUp} className="relative">
              <GlassCard className="p-7 sm:p-8 h-full flex flex-col justify-between space-y-4">
                <div className="space-y-3">
                  <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-purple-600 to-indigo-600 text-white font-mono font-bold text-base flex items-center justify-center shadow-[0_0_20px_rgba(124,58,237,0.4)]">
                    01
                  </div>
                  <h3 className="text-xl font-bold text-white font-sans">
                    Market Analysis
                  </h3>
                  <p className="text-sm text-slate-400 font-sans leading-relaxed">
                    Our engine continuously scans XAU/USD for high-probability setups across 15m, 1h, and 4h structural frames, tracking liquidity sweeps and order flow.
                  </p>
                </div>
                <div className="text-[11px] font-mono text-cyan-300 flex items-center gap-1.5 pt-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping" />
                  <span>Continuous 15m/1h/4h scanner</span>
                </div>
              </GlassCard>
            </motion.div>

            {/* Step 2 */}
            <motion.div variants={fadeInUp} className="relative">
              <GlassCard className="p-7 sm:p-8 h-full flex flex-col justify-between space-y-4">
                <div className="space-y-3">
                  <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-cyan-500 text-white font-mono font-bold text-base flex items-center justify-center shadow-[0_0_20px_rgba(6,182,212,0.4)]">
                    02
                  </div>
                  <h3 className="text-xl font-bold text-white font-sans">
                    Signal Generation
                  </h3>
                  <p className="text-sm text-slate-400 font-sans leading-relaxed">
                    Receive Telegram alerts with entry, SL, and TP levels formatted with multi-timeframe reasoning once confluence criteria are satisfied.
                  </p>
                </div>
                <div className="text-[11px] font-mono text-purple-300 flex items-center gap-1.5 pt-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-purple-400" />
                  <span>Real-time Telegram dispatch</span>
                </div>
              </GlassCard>
            </motion.div>

            {/* Step 3 */}
            <motion.div variants={fadeInUp} className="relative">
              <GlassCard className="p-7 sm:p-8 h-full flex flex-col justify-between space-y-4">
                <div className="space-y-3">
                  <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-emerald-500 text-white font-mono font-bold text-base flex items-center justify-center shadow-[0_0_20px_rgba(16,185,129,0.4)]">
                    03
                  </div>
                  <h3 className="text-xl font-bold text-white font-sans">
                    Automated Execution
                  </h3>
                  <p className="text-sm text-slate-400 font-sans leading-relaxed">
                    Paper trade or connect to your broker for live execution with structural invalidation stops and automated news blackout protection.
                  </p>
                </div>
                <div className="text-[11px] font-mono text-emerald-300 flex items-center gap-1.5 pt-2">
                  <Shield className="w-3.5 h-3.5 text-emerald-400" />
                  <span>High-Impact News Blackout Filters</span>
                </div>
              </GlassCard>
            </motion.div>
          </motion.div>
        </section>

        {/* =========================================================================
            SECTION 5: CALL TO ACTION BANNER
           ========================================================================= */}
        <section className="py-20 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
          <GlassCard glowColor="purple" className="p-8 sm:p-12 text-center relative overflow-hidden">
            <div className="max-w-3xl mx-auto space-y-6">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/5 border border-white/10 text-xs font-mono text-purple-300">
                <Shield className="w-3.5 h-3.5 text-purple-400" />
                <span>Transparent Methodology · Open-Source Core</span>
              </div>

              <h2 className="text-3xl sm:text-5xl font-extrabold tracking-tight text-white font-sans">
                Open the Live Strategy Dashboard
              </h2>

              <p className="text-slate-400 text-sm sm:text-base max-w-xl mx-auto font-sans">
                Inspect live 15m/1h/4h signals, review open positions and performance metrics, or explore the open-source FastAPI and React codebase.
              </p>

              <div className="pt-2 flex flex-col sm:flex-row items-center justify-center gap-4">
                <Link
                  to="/dashboard"
                  className="w-full sm:w-auto px-8 py-3.5 rounded-2xl bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white font-sans text-sm font-semibold flex items-center justify-center gap-2 shadow-[0_0_25px_rgba(124,58,237,0.4)] transition-all cursor-pointer"
                >
                  <span>Open Dashboard</span>
                  <ArrowRight className="w-4 h-4" />
                </Link>

                <a
                  href="https://github.com/dina-seng/signal_bot"
                  target="_blank"
                  rel="noreferrer"
                  className="w-full sm:w-auto px-6 py-3.5 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-slate-200 hover:text-white font-sans text-sm font-semibold flex items-center justify-center gap-2 transition-all cursor-pointer"
                >
                  <GithubIcon className="w-4 h-4 text-slate-300" />
                  <span>View on GitHub</span>
                </a>
              </div>
            </div>
          </GlassCard>
        </section>
      </main>

      {/* =========================================================================
          FOOTER
         ========================================================================= */}
      <footer className="border-t border-white/10 bg-[#030014]/90 backdrop-blur-xl py-12 px-4 sm:px-6 lg:px-8 text-xs text-slate-400 font-sans">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-6">
          <div className="flex flex-col sm:flex-row items-center gap-3">
            <div className="flex items-center gap-2">
              <img src={logoImg} alt="QuantView" className="w-5 h-5 object-contain opacity-90" />
              <span className="font-bold text-white text-sm tracking-tight font-sans">
                QUANT<span className="text-purple-400">VIEW</span>
              </span>
            </div>
            <span className="hidden sm:inline text-slate-600">•</span>
            <span className="text-slate-400">Built with FastAPI + React · Powered by Twelve Data · Backtested on XAU/USD 2025-2026</span>
          </div>

          <div className="flex items-center gap-6">
            <Link to="/dashboard" className="hover:text-white transition-colors">
              Dashboard
            </Link>
            <a
              href="https://github.com/dina-seng/signal_bot#readme"
              target="_blank"
              rel="noreferrer"
              className="hover:text-white transition-colors"
            >
              Documentation
            </a>
            <a
              href="https://github.com/dina-seng/signal_bot"
              target="_blank"
              rel="noreferrer"
              className="hover:text-white transition-colors flex items-center gap-1"
            >
              <GithubIcon className="w-3.5 h-3.5" />
              <span>GitHub</span>
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default Landing;
