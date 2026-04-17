import { motion } from 'framer-motion';
import HudCorners from './HudCorners';
import { Hexagon } from 'lucide-react';

/* ─────────────────────────────────────────────────────────────────────────────
   DarkHUD — Full-screen landing page with terminal/HUD aesthetic.
   Background #060612, accent #00ff87, Oswald headings, scanlines + grid.
   ───────────────────────────────────────────────────────────────────────────── */

/* Animated news ticker items */
const TICKER_ITEMS = [
  '⚽ Man City 2-1 Liverpool — CONFIRMED',
  '🏀 Lakers 112-108 Celtics — FINAL',
  '📊 Model accuracy: 67.2% across 207 tracked predictions',
  '🔥 New stacking ensemble deployed — LR + RF + XGB + LGBM',
  '💰 Combined Signal edge: +4.1pp over baseline',
];

export default function DarkHUD() {
  return (
    <div className="relative min-h-screen bg-[#060612] text-white overflow-hidden font-oswald">

      {/* ── Grid background ────────────────────────────────────────────── */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage:
            'linear-gradient(#00ff87 1px, transparent 1px), linear-gradient(90deg, #00ff87 1px, transparent 1px)',
          backgroundSize: '48px 48px',
        }}
      />

      {/* ── Scanlines ──────────────────────────────────────────────────── */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage:
            'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,255,135,0.06) 2px, rgba(0,255,135,0.06) 4px)',
        }}
      />

      {/* ── Ticker bar ─────────────────────────────────────────────────── */}
      <div className="relative z-10 border-b border-[#00ff87]/10 bg-black/30 py-2 overflow-hidden">
        <motion.div
          className="flex gap-16 whitespace-nowrap text-xs tracking-widest text-neutral-500 uppercase"
          animate={{ x: ['0%', '-50%'] }}
          transition={{ repeat: Infinity, duration: 30, ease: 'linear' }}
        >
          {[...TICKER_ITEMS, ...TICKER_ITEMS].map((item, i) => (
            <span key={i} className="shrink-0">{item}</span>
          ))}
        </motion.div>
      </div>

      {/* ── Navbar ─────────────────────────────────────────────────────── */}
      <nav className="relative z-10 flex items-center justify-between px-8 py-5 border-b border-[#00ff87]/10">
        <div className="flex items-center gap-2">
          <Hexagon className="w-7 h-7 text-[#00ff87]" strokeWidth={1.5} />
          <span className="text-xl tracking-[0.25em] uppercase">
            SCOR<span className="text-[#00ff87]">PRED</span>
          </span>
        </div>
        <div className="hidden md:flex gap-8 text-xs tracking-[0.2em] text-neutral-400 uppercase">
          <a href="#" className="hover:text-[#00ff87] transition-colors">Dashboard</a>
          <a href="#" className="hover:text-[#00ff87] transition-colors">Matches</a>
          <a href="#" className="hover:text-[#00ff87] transition-colors">Props</a>
          <a href="#" className="hover:text-[#00ff87] transition-colors">Strategy Lab</a>
        </div>
        <button className="border border-[#00ff87]/30 text-[#00ff87] px-5 py-2 text-xs tracking-widest uppercase hover:bg-[#00ff87]/10 transition-colors">
          Launch App →
        </button>
      </nav>

      {/* ── Hero ───────────────────────────────────────────────────────── */}
      <section className="relative z-10 grid lg:grid-cols-2 gap-12 items-center px-8 py-20 max-w-7xl mx-auto">

        {/* Left — headline + CTA */}
        <div className="space-y-8">
          <div>
            <p className="text-[#00ff87] text-xs tracking-[0.3em] uppercase mb-3 font-mono">
              // SYSTEM ONLINE
            </p>
            <h1 className="text-5xl lg:text-6xl font-bold leading-[1.1] tracking-tight uppercase">
              Predict.<br />
              <span className="text-[#00ff87]">Win.</span><br />
              Repeat.
            </h1>
          </div>
          <p className="text-neutral-400 text-base max-w-md leading-relaxed font-sans">
            ML-powered sports predictions combining stacking ensembles, rule engines,
            and live market edges. Built for sharp bettors who demand data-driven conviction.
          </p>
          <div className="flex gap-4">
            <button className="bg-[#00ff87] text-black px-8 py-3 text-sm font-bold tracking-widest uppercase hover:bg-[#00ff87]/90 transition-colors">
              Get Started
            </button>
            <button className="border border-white/20 text-white px-8 py-3 text-sm tracking-widest uppercase hover:border-[#00ff87]/40 hover:text-[#00ff87] transition-colors">
              View Demo
            </button>
          </div>

          {/* Mini stats row */}
          <div className="flex gap-8 pt-4">
            {[
              { label: 'Models', value: '4' },
              { label: 'Accuracy', value: '67.2%' },
              { label: 'Edge', value: '+4.1pp' },
            ].map((stat) => (
              <div key={stat.label} className="text-center">
                <p className="text-2xl font-bold text-[#00ff87]">{stat.value}</p>
                <p className="text-[10px] tracking-widest text-neutral-500 uppercase">{stat.label}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Right — Floating prediction cards (Upgrade 1) */}
        <div className="relative h-[500px] hidden lg:block">

          {/* Card 1 — Match prediction (floats up/down) */}
          <motion.div
            className="absolute top-8 right-4 w-80"
            animate={{ y: [0, -15, 0] }}
            transition={{ repeat: Infinity, duration: 4, ease: 'easeInOut' }}
          >
            <div className="relative bg-black/40 border border-[#00ff87]/20 rounded-sm p-5 backdrop-blur-sm">
              <HudCorners />
              <div className="flex items-center gap-2 mb-3">
                <span className="text-lg">⚽</span>
                <span className="text-[10px] tracking-[0.2em] text-neutral-500 uppercase">Premier League</span>
              </div>
              <h3 className="text-lg font-bold tracking-wide uppercase mb-4">
                Man City <span className="text-neutral-500 text-sm font-normal">vs</span> Arsenal
              </h3>
              <div className="space-y-2">
                <div className="flex justify-between text-xs text-neutral-400 uppercase tracking-wider">
                  <span>Home Win</span>
                  <span className="text-[#00ff87] font-bold">68%</span>
                </div>
                <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                  <motion.div
                    className="h-full bg-[#00ff87] rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: '68%' }}
                    transition={{ duration: 1.5, ease: 'easeOut', delay: 0.5 }}
                  />
                </div>
                <div className="flex justify-between text-xs text-neutral-500 uppercase tracking-wider pt-1">
                  <span>Draw 18%</span>
                  <span>Away 14%</span>
                </div>
              </div>
              <div className="mt-4 pt-3 border-t border-[#00ff87]/10 flex items-center justify-between">
                <span className="text-[10px] tracking-widest text-neutral-500 uppercase font-mono">Stacking Ensemble</span>
                <span className="text-[10px] tracking-widest text-[#00ff87] font-mono">LIVE</span>
              </div>
            </div>
          </motion.div>

          {/* Card 2 — High value pick (floats down/up, offset) */}
          <motion.div
            className="absolute bottom-8 left-4 w-72"
            animate={{ y: [0, 15, 0] }}
            transition={{ repeat: Infinity, duration: 5, ease: 'easeInOut' }}
          >
            <div className="relative bg-black/40 border border-[#00ff87]/20 rounded-sm p-5 backdrop-blur-sm">
              <HudCorners />
              <div className="flex items-center gap-2 mb-2">
                <span className="inline-block w-2 h-2 rounded-full bg-[#00d4ff] animate-pulse" />
                <span className="text-[10px] tracking-[0.2em] text-[#00d4ff] uppercase font-mono">High Value Pick</span>
              </div>
              <p className="text-sm text-neutral-300 leading-relaxed mb-3 font-sans">
                Model detects <span className="text-[#00ff87] font-bold">4.2% edge</span>.
                Sharp money moving.
              </p>
              <p className="text-xs font-mono tracking-wider text-[#00d4ff]">
                CONFIDENCE: 0.89 [HIGH]
              </p>
              <div className="mt-3 pt-3 border-t border-[#00ff87]/10">
                <div className="flex gap-3">
                  {['ML', 'RULES', 'EDGE'].map((tag) => (
                    <span
                      key={tag}
                      className="text-[9px] tracking-widest text-neutral-500 border border-white/10 px-2 py-0.5 rounded-sm uppercase"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </motion.div>

          {/* Background decoration — faint concentric rings */}
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none opacity-[0.04]">
            <div className="w-80 h-80 border border-[#00ff87] rounded-full" />
            <div className="absolute w-56 h-56 border border-[#00ff87] rounded-full" />
            <div className="absolute w-32 h-32 border border-[#00ff87] rounded-full" />
          </div>
        </div>
      </section>

      {/* ── Bottom border accent ───────────────────────────────────────── */}
      <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-[#00ff87]/30 to-transparent" />
    </div>
  );
}
