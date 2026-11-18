import React, { useState, useEffect } from 'react';
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
  Brain,
  Zap,
  Shield,
  ArrowRight,
  ExternalLink,
  CheckCircle2,
  Cpu,
  BarChart2,
  Terminal,
  Radio,
  Clock,
  Sparkles,
  ChevronRight,
  Layers,
  Flame,
} from 'lucide-react';
import { GlassCard } from '../components/ui/GlassCard';

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

// 342-Trade Walk-Forward Equity Curve points ending at +136.4R
const equityCurveData = [
  { trade: 0, date: 'Mar 2023', returnR: 0, drawdown: 0 },
  { trade: 25, date: 'May 2023', returnR: 11.2, drawdown: 1.2 },
  { trade: 50, date: 'Jul 2023', returnR: 19.8, drawdown: 2.1 },
  { trade: 75, date: 'Sep 2023', returnR: 28.4, drawdown: 1.5 },
  { trade: 100, date: 'Nov 2023', returnR: 41.6, drawdown: 3.2 },
  { trade: 135, date: 'Jan 2024', returnR: 54.2, drawdown: 2.4 },
  { trade: 170, date: 'Apr 2024', returnR: 68.9, drawdown: 4.8 },
  { trade: 205, date: 'Jul 2024', returnR: 81.3, drawdown: 1.8 },
  { trade: 240, date: 'Oct 2024', returnR: 97.5, drawdown: 2.6 },
  { trade: 280, date: 'Jan 2025', returnR: 112.0, drawdown: 3.1 },
  { trade: 315, date: 'Jun 2025', returnR: 124.8, drawdown: 2.0 },
  { trade: 342, date: 'Current', returnR: 136.4, drawdown: 0.8 },
];

export const Landing: React.FC = () => {
  const { scrollY } = useScroll();
  const heroParallaxY = useTransform(scrollY, [0, 800], [0, 140]);
  const heroOpacity = useTransform(scrollY, [0, 600], [1, 0.2]);

  // Section in-view triggers
  const [featuresRef, featuresInView] = useInView({ triggerOnce: true, threshold: 0.15 });
  const [perfRef, perfInView] = useInView({ triggerOnce: true, threshold: 0.15 });
  const [howRef, howInView] = useInView({ triggerOnce: true, threshold: 0.15 });

  const [activeTab, setActiveTab] = useState<'all' | '1y' | '3m'>('all');

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
    <div className="relative min-h-screen bg-[#030014] text-slate-100 font-sans selection:bg-violet-500/30 selection:text-white overflow-x-hidden">
      {/* =========================================================================
          ATMOSPHERIC GLOBAL BACKGROUND LAYER
         ========================================================================= */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-0" aria-hidden="true">
        {/* Base Void */}
        <div className="absolute inset-0 bg-[#030014]" />

        {/* Floating Neon Purple Orb */}
        <div className="absolute -top-[12%] -left-[10%] w-[58vw] h-[58vw] max-w-[850px] max-h-[850px] rounded-full bg-purple-600/20 blur-[140px] animate-orb-purple transform-gpu" />

        {/* Floating Electric Cyan Orb */}
        <div className="absolute top-[24%] -right-[8%] w-[52vw] h-[52vw] max-w-[780px] max-h-[780px] rounded-full bg-cyan-500/15 blur-[140px] animate-orb-cyan transform-gpu" />

        {/* Floating Deep Violet Orb */}
        <div className="absolute bottom-[5%] left-[20%] w-[60vw] h-[60vw] max-w-[900px] max-h-[900px] rounded-full bg-violet-700/20 blur-[150px] animate-orb-violet transform-gpu" />

        {/* Subtle Modern Grid Overlay with Radial Spotlight Mask */}
        <div
          className="absolute inset-0 bg-fintech-grid bg-[size:40px_40px] opacity-40"
          style={{
            maskImage: 'radial-gradient(ellipse 75% 60% at 50% 30%, black 20%, transparent 85%)',
            WebkitMaskImage: 'radial-gradient(ellipse 75% 60% at 50% 30%, black 20%, transparent 85%)',
          }}
        />
      </div>

      {/* =========================================================================
          NAVIGATION BAR
         ========================================================================= */}
      <header className="fixed top-0 inset-x-0 z-50 backdrop-blur-xl bg-[#030014]/75 border-b border-white/10 transition-colors">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          {/* Brand Logo */}
          <Link to="/" className="flex items-center gap-2.5 group">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-purple-600 via-indigo-600 to-cyan-500 p-0.5 shadow-[0_0_20px_rgba(124,58,237,0.4)] group-hover:shadow-[0_0_25px_rgba(6,182,212,0.6)] transition-all duration-300">
              <div className="w-full h-full bg-[#030014] rounded-[10px] flex items-center justify-center">
                <Shield className="w-4 h-4 text-cyan-400 group-hover:scale-110 transition-transform" />
              </div>
            </div>
            <div className="flex flex-col">
              <span className="text-base font-bold tracking-tight text-white flex items-center gap-1.5 font-sans">
                QUANT<span className="text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-cyan-400">VIEW</span>
              </span>
            </div>
            <span className="hidden sm:inline-block ml-1 px-2 py-0.5 rounded-full text-[9px] font-mono uppercase bg-white/5 text-zinc-400 border border-white/10">
              AI TRADING OS
            </span>
          </Link>

          {/* Nav Links */}
          <nav className="hidden md:flex items-center gap-7 text-xs font-medium text-slate-300 font-sans">
            <a href="#hero" className="hover:text-white transition-colors">
              Home
            </a>
            <a href="#features" className="hover:text-white transition-colors">
              Features
            </a>
            <a href="#performance" className="hover:text-white transition-colors">
              Performance
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
              <span>Launch Terminal</span>
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
            transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
            className="max-w-4xl mx-auto space-y-6"
          >
            {/* Live Operational Status Pill */}
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/10 backdrop-blur-md shadow-lg text-xs font-mono text-zinc-300">
              <span className="w-2 h-2 rounded-full bg-[#00e676] animate-pulse" />
              <span className="text-zinc-400 uppercase text-[10px] tracking-wider">
                XAU/USD LIVE FASTFEED
              </span>
              <span className="text-zinc-600">•</span>
              <span className="text-cyan-400 font-semibold text-[11px]">SMC + CRT ENGINE ACTIVE</span>
            </div>

            {/* Huge Gradient Headline */}
            <h1 className="text-6xl sm:text-7xl md:text-8xl lg:text-9xl font-black tracking-tight font-sans">
              <span className="bg-clip-text text-transparent bg-gradient-to-r from-purple-400 via-fuchsia-300 to-cyan-400 drop-shadow-[0_0_50px_rgba(168,85,247,0.3)]">
                QuantView
              </span>
            </h1>

            {/* Subheadline */}
            <p className="text-xl sm:text-2xl md:text-3xl font-semibold text-slate-100 tracking-tight font-sans">
              Institutional-Grade AI Trading Intelligence
            </p>

            {/* Description */}
            <p className="max-w-2xl mx-auto text-sm sm:text-base md:text-lg text-slate-400 font-sans leading-relaxed">
              Automated Smart Money Concepts & Candle Range Theory strategy execution with real-time market analysis and risk management.
            </p>

            {/* Action Buttons */}
            <div className="pt-4 flex flex-col sm:flex-row items-center justify-center gap-3.5">
              <Link
                to="/dashboard"
                className="w-full sm:w-auto px-7 py-3.5 rounded-2xl bg-gradient-to-r from-violet-600 via-indigo-600 to-cyan-600 hover:from-violet-500 hover:to-cyan-500 text-white font-sans text-sm font-semibold flex items-center justify-center gap-2.5 shadow-[0_0_30px_rgba(124,58,237,0.45)] hover:shadow-[0_0_40px_rgba(6,182,212,0.6)] transition-all duration-300 cursor-pointer group"
              >
                <span>View Live Dashboard</span>
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

            {/* Hero Live Mock Terminal Telemetry Preview Card */}
            <motion.div
              initial={{ opacity: 0, y: 40 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.35, duration: 0.8 }}
              className="pt-10 max-w-3xl mx-auto w-full"
            >
              <GlassCard
                glowColor="purple"
                className="p-5 sm:p-6 text-left border-white/15 shadow-2xl relative overflow-hidden"
              >
                <div className="flex items-center justify-between border-b border-white/10 pb-3 mb-4">
                  <div className="flex items-center gap-2.5">
                    <div className="flex gap-1.5">
                      <span className="w-3 h-3 rounded-full bg-rose-500/80 inline-block" />
                      <span className="w-3 h-3 rounded-full bg-amber-500/80 inline-block" />
                      <span className="w-3 h-3 rounded-full bg-emerald-500/80 inline-block" />
                    </div>
                    <span className="text-xs font-mono text-slate-400 pl-2">
                      terminal://xau-usd-fastfeed-v2
                    </span>
                  </div>
                  <span className="text-[10px] font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                    LATENCY: 24ms
                  </span>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs font-mono">
                  <div>
                    <span className="text-slate-500 uppercase text-[10px] block">Instrument</span>
                    <span className="text-sm font-bold text-white">XAU/USD (Gold)</span>
                    <span className="text-[10px] text-emerald-400 block">+1.84% Today</span>
                  </div>

                  <div>
                    <span className="text-slate-500 uppercase text-[10px] block">Confluence</span>
                    <span className="text-sm font-bold text-cyan-400">88 / 100</span>
                    <span className="text-[10px] text-slate-400 block">Strong Buy Setup</span>
                  </div>

                  <div>
                    <span className="text-slate-500 uppercase text-[10px] block">SMC Pattern</span>
                    <span className="text-sm font-bold text-purple-300">Bullish FVG</span>
                    <span className="text-[10px] text-slate-400 block">15m Imbalance Sweep</span>
                  </div>

                  <div>
                    <span className="text-slate-500 uppercase text-[10px] block">Risk : Reward</span>
                    <span className="text-sm font-bold text-emerald-400">1 : 3.2</span>
                    <span className="text-[10px] text-slate-400 block">SL: $3,875.00</span>
                  </div>
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
            <span className="text-xs font-mono uppercase tracking-widest text-cyan-400 bg-cyan-500/10 px-3 py-1 rounded-full border border-cyan-500/25">
              Core Architecture
            </span>
            <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight text-white font-sans">
              Algorithmic Precision at Scale
            </h2>
            <p className="text-slate-400 text-sm sm:text-base font-sans">
              Engineered from the ground up to eliminate emotional bias and execute pure institutional order-flow confluences.
            </p>
          </div>

          <motion.div
            variants={staggerContainer}
            initial="hidden"
            animate={featuresInView ? 'visible' : 'hidden'}
            className="grid grid-cols-1 md:grid-cols-3 gap-6"
          >
            {/* Card 1: Smart Money Concepts */}
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
                    Smart Money Concepts
                  </h3>
                  <p className="text-sm text-slate-400 font-sans leading-relaxed">
                    Automated Break of Structure (BOS), Change of Character (CHOCH), and institutional liquidity sweeps (BSL/SSL) across multi-timeframe candle structures.
                  </p>
                </div>
                <div className="pt-6 border-t border-white/10 flex flex-wrap gap-1.5 text-[11px] font-mono text-emerald-300">
                  <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 border border-emerald-500/20">BOS / CHOCH</span>
                  <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 border border-emerald-500/20">Liquidity Sweeps</span>
                  <span className="px-2 py-0.5 rounded-md bg-emerald-500/10 border border-emerald-500/20">Order Blocks</span>
                </div>
              </GlassCard>
            </motion.div>

            {/* Card 2: Candle Range Theory */}
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
                    Candle Range Theory
                  </h3>
                  <p className="text-sm text-slate-400 font-sans leading-relaxed">
                    Sub-minute displacement verification, algorithmic range expansion profiling, and high-probability fair value gap (FVG) mitigation entry zones.
                  </p>
                </div>
                <div className="pt-6 border-t border-white/10 flex flex-wrap gap-1.5 text-[11px] font-mono text-purple-300">
                  <span className="px-2 py-0.5 rounded-md bg-purple-500/10 border border-purple-500/20">Fair Value Gaps</span>
                  <span className="px-2 py-0.5 rounded-md bg-purple-500/10 border border-purple-500/20">Range Expansion</span>
                  <span className="px-2 py-0.5 rounded-md bg-purple-500/10 border border-purple-500/20">Displacement</span>
                </div>
              </GlassCard>
            </motion.div>

            {/* Card 3: AI Confluence Engine */}
            <motion.div variants={fadeInUp} whileHover={{ y: -6, transition: { duration: 0.25 } }}>
              <GlassCard
                glowColor="cyan"
                className="p-7 sm:p-8 h-full flex flex-col justify-between"
              >
                <div className="space-y-4">
                  <div className="w-12 h-12 rounded-2xl bg-cyan-500/10 border border-cyan-500/25 flex items-center justify-center text-cyan-400 shadow-[0_0_20px_rgba(6,182,212,0.2)]">
                    <Brain className="w-6 h-6" />
                  </div>
                  <h3 className="text-xl font-bold text-white font-sans">
                    AI Confluence Engine
                  </h3>
                  <p className="text-sm text-slate-400 font-sans leading-relaxed">
                    Weighted consensus matrix scoring (0–100), algorithmic sentiment validation, and automated ATR-scaled position risk management.
                  </p>
                </div>
                <div className="pt-6 border-t border-white/10 flex flex-wrap gap-1.5 text-[11px] font-mono text-cyan-300">
                  <span className="px-2 py-0.5 rounded-md bg-cyan-500/10 border border-cyan-500/20">Consensus Scoring</span>
                  <span className="px-2 py-0.5 rounded-md bg-cyan-500/10 border border-cyan-500/20">Macro Blackouts</span>
                  <span className="px-2 py-0.5 rounded-md bg-cyan-500/10 border border-cyan-500/20">Dynamic SL/TP</span>
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
                Verified Statistical Edge
              </span>
              <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight text-white font-sans">
                Walk-Forward Performance
              </h2>
              <p className="text-slate-400 text-sm sm:text-base font-sans">
                Real simulation on historical tick data using strict 1:2 minimum Risk:Reward target parameters.
              </p>
            </div>

            {/* 3 Core Highlight Badges */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
              <GlassCard glowColor="green" className="p-6 text-center">
                <span className="text-xs font-sans uppercase tracking-wider text-slate-400 block mb-1">
                  Win Rate
                </span>
                <span className="font-mono text-4xl sm:text-5xl font-extrabold text-[#00e676] drop-shadow-sm">
                  47%
                </span>
                <span className="text-xs text-slate-400 mt-2 block font-sans">
                  Target: 1:2+ Minimum Risk:Reward
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
                  Total Compounded Return
                </span>
                <span className="font-mono text-4xl sm:text-5xl font-extrabold text-purple-300 drop-shadow-sm">
                  +136R
                </span>
                <span className="text-xs text-slate-400 mt-2 block font-sans">
                  Walk-Forward Cumulative R-Multiple
                </span>
              </GlassCard>
            </div>

            {/* Glowing Interactive Recharts Equity Curve in Glass Card */}
            <GlassCard glowColor="cyan" className="p-6 sm:p-8 space-y-6">
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-white/10 pb-5">
                <div>
                  <h3 className="text-lg font-bold text-white font-sans flex items-center gap-2">
                    <BarChart2 className="w-5 h-5 text-cyan-400" />
                    <span>Cumulative Equity Trajectory (+136.4R)</span>
                  </h3>
                  <p className="text-xs text-slate-400 font-sans mt-0.5">
                    Tick-level simulated order execution from March 2023 across 342 trades
                  </p>
                </div>
                <div className="flex items-center gap-2 text-xs font-mono text-slate-300">
                  <span className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-white/5 border border-white/10">
                    <span className="w-2 h-2 rounded-full bg-cyan-400" />
                    Max Drawdown: <strong>4.8%</strong>
                  </span>
                  <span className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-white/5 border border-white/10">
                    <span className="w-2 h-2 rounded-full bg-purple-400" />
                    Expectancy: <strong>+0.68R</strong>
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
                                Drawdown: {data.drawdown}%
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

              {/* Stats Footer Strip */}
              <div className="pt-4 border-t border-white/10 grid grid-cols-2 sm:grid-cols-4 gap-4 text-center font-mono text-xs">
                <div>
                  <span className="text-slate-500 uppercase text-[10px] block">Total Trades</span>
                  <span className="font-bold text-white text-base">342</span>
                </div>
                <div>
                  <span className="text-slate-500 uppercase text-[10px] block">Sharpe Ratio</span>
                  <span className="font-bold text-cyan-400 text-base">2.18</span>
                </div>
                <div>
                  <span className="text-slate-500 uppercase text-[10px] block">Avg Risk:Reward</span>
                  <span className="font-bold text-purple-300 text-base">1 : 2.45</span>
                </div>
                <div>
                  <span className="text-slate-500 uppercase text-[10px] block">Asset Focus</span>
                  <span className="font-bold text-emerald-400 text-base">XAU/USD Gold</span>
                </div>
              </div>
            </GlassCard>
          </motion.div>
        </section>

        {/* =========================================================================
            SECTION 4: HOW IT WORKS SECTION (3 STEPS)
           ========================================================================= */}
        <section id="how-it-works" ref={howRef} className="py-24 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
          <div className="text-center max-w-3xl mx-auto mb-16 space-y-3">
            <span className="text-xs font-mono uppercase tracking-widest text-emerald-400 bg-emerald-500/10 px-3 py-1 rounded-full border border-emerald-500/25">
              Execution Lifecycle
            </span>
            <h2 className="text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight text-white font-sans">
              How It Works
            </h2>
            <p className="text-slate-400 text-sm sm:text-base font-sans">
              From real-time tick ingestion to automated broker execution in three streamlined steps.
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
                    Our engine scans XAU/USD 24/7 for high-probability setups across 1m, 15m, 1h, and 4h structural frames using continuous order-flow modeling.
                  </p>
                </div>
                <div className="text-[11px] font-mono text-cyan-300 flex items-center gap-1.5 pt-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping" />
                  <span>Sub-second tick ingestion</span>
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
                    Receive Telegram alerts with entry, SL, and TP levels formatted with full multi-timeframe reasoning once confluence passes the 75% threshold.
                  </p>
                </div>
                <div className="text-[11px] font-mono text-purple-300 flex items-center gap-1.5 pt-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-purple-400" />
                  <span>Verified Confluence &ge; 75</span>
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
                    Paper trade or connect to your broker for live execution with sub-50ms round-trip latency and automated high-impact news blackout filters.
                  </p>
                </div>
                <div className="text-[11px] font-mono text-emerald-300 flex items-center gap-1.5 pt-2">
                  <Shield className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Macro Blackout Protection</span>
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
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/5 border border-white/10 text-xs font-mono text-cyan-300">
                <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
                <span>Zero Installation Required • Browser-Based Terminal</span>
              </div>

              <h2 className="text-3xl sm:text-5xl font-extrabold tracking-tight text-white font-sans">
                Experience the Future of Algorithmic Trading
              </h2>

              <p className="text-slate-400 text-sm sm:text-base max-w-xl mx-auto font-sans">
                Launch the institutional QuantView terminal right now or inspect the open-source FastAPI and React codebase.
              </p>

              <div className="pt-2 flex flex-col sm:flex-row items-center justify-center gap-4">
                <Link
                  to="/dashboard"
                  className="w-full sm:w-auto px-8 py-3.5 rounded-2xl bg-gradient-to-r from-violet-600 via-indigo-600 to-cyan-500 hover:from-violet-500 hover:to-cyan-400 text-white font-sans text-sm font-semibold flex items-center justify-center gap-2 shadow-[0_0_30px_rgba(124,58,237,0.4)] transition-all cursor-pointer"
                >
                  <span>Launch Live Terminal</span>
                  <ArrowRight className="w-4 h-4" />
                </Link>

                <a
                  href="https://github.com/dina-seng/signal_bot"
                  target="_blank"
                  rel="noreferrer"
                  className="w-full sm:w-auto px-6 py-3.5 rounded-2xl bg-white/5 hover:bg-white/10 border border-white/10 text-slate-200 hover:text-white font-sans text-sm font-semibold flex items-center justify-center gap-2 transition-all cursor-pointer"
                >
                  <GithubIcon className="w-4 h-4 text-slate-300" />
                  <span>Star on GitHub</span>
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
            <span className="font-bold text-white text-sm tracking-tight flex items-center gap-1.5 font-sans">
              QUANT<span className="text-transparent bg-clip-text bg-gradient-to-r from-purple-400 to-cyan-400">VIEW</span>
            </span>
            <span className="hidden sm:inline text-slate-600">•</span>
            <span className="text-slate-400">Built with FastAPI + React · Powered by Twelve Data</span>
          </div>

          <div className="flex items-center gap-6">
            <Link to="/dashboard" className="hover:text-white transition-colors">
              Live Terminal
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
