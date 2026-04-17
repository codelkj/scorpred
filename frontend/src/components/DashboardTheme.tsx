import { useState, useEffect, type ReactNode } from 'react';
import {
  Hexagon, BarChart3, FlaskConical, Settings, User,
  TrendingUp, LayoutDashboard, Trophy, Activity, Dumbbell,
} from 'lucide-react';

/* ─────────────────────────────────────────────────────────────────────────────
   DashboardTheme — Global app shell.
   Uses .app-layout / .content-area / .main-content from index.css.
   Sidebar is fixed-width; content area scrolls independently.
   ───────────────────────────────────────────────────────────────────────────── */

interface NavItem { label: string; icon: ReactNode }

const SECTIONS: { heading: string; items: NavItem[] }[] = [
  {
    heading: 'Analysis',
    items: [
      { label: 'Dashboard',      icon: <LayoutDashboard className="w-4 h-4" /> },
      { label: 'Soccer',         icon: <TrendingUp className="w-4 h-4" /> },
      { label: 'NBA',            icon: <Dumbbell className="w-4 h-4" /> },
      { label: 'Match Analysis', icon: <Activity className="w-4 h-4" /> },
    ],
  },
  {
    heading: 'Tools',
    items: [
      { label: 'Strategy Lab',   icon: <FlaskConical className="w-4 h-4" /> },
      { label: 'Performance',    icon: <BarChart3 className="w-4 h-4" /> },
      { label: 'Props Engine',   icon: <Trophy className="w-4 h-4" /> },
    ],
  },
  {
    heading: 'Account',
    items: [
      { label: 'Settings',       icon: <Settings className="w-4 h-4" /> },
    ],
  },
];

/* ── Live clock ─────────────────────────────────────────────────────────── */
function LiveClock() {
  const [time, setTime] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const p = (n: number) => String(n).padStart(2, '0');
  return (
    <span className="text-[10px] tracking-widest text-neutral-600 font-mono border border-white/[0.06] px-2.5 py-1">
      {p(time.getMonth() + 1)}-{p(time.getDate())} {p(time.getHours())}:{p(time.getMinutes())}:{p(time.getSeconds())}
    </span>
  );
}

/* ── DashboardLayout ─────────────────────────────────────────────────────── */
export default function DashboardLayout({
  children,
  activeItem = 'Dashboard',
  onNavigate,
}: {
  children: ReactNode;
  activeItem?: string;
  onNavigate?: (item: string) => void;
}) {
  return (
    <div className="app-layout">

      {/* ── Sidebar ───────────────────────────────────────────────────── */}
      <aside className="sidebar hidden md:flex flex-col border-r border-white/[0.06] bg-[#0f172a]">
        {/* Logo */}
        <div className="flex items-center gap-2 px-5 py-5 border-b border-white/[0.06] shrink-0">
          <Hexagon className="w-5 h-5 text-[#00ff87]" strokeWidth={1.5} />
          <span className="text-sm tracking-[0.2em] uppercase font-oswald">
            SCOR<span className="text-[#00ff87]">PRED</span>
          </span>
        </div>

        {/* Nav sections */}
        <nav className="flex-1 py-4 space-y-6 overflow-y-auto">
          {SECTIONS.map((sec) => (
            <div key={sec.heading} className="px-4">
              <p className="text-[10px] tracking-[0.2em] text-neutral-600 uppercase font-mono mb-2 px-2">
                {sec.heading}
              </p>
              <ul className="space-y-0.5">
                {sec.items.map((item) => {
                  const active = item.label === activeItem;
                  return (
                    <li key={item.label}>
                      <button
                        onClick={() => onNavigate?.(item.label)}
                        className={`w-full flex items-center gap-3 px-3 py-2 text-xs tracking-wider transition-colors text-left ${
                          active
                            ? 'text-[#00ff87] border-l-2 border-[#00ff87] bg-[#00ff87]/5'
                            : 'text-neutral-500 hover:text-white hover:bg-white/5'
                        }`}
                      >
                        {item.icon}
                        {item.label}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className="border-t border-white/[0.06] p-4 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-[#00ff87]/10 flex items-center justify-center">
              <User className="w-4 h-4 text-[#00ff87]" />
            </div>
            <div>
              <p className="text-xs text-neutral-300">Analyst</p>
              <p className="text-[10px] text-neutral-600 font-mono">v2.4.0</p>
            </div>
          </div>
        </div>
      </aside>

      {/* ── Content column ────────────────────────────────────────────── */}
      <div className="content-area">

        {/* Top bar */}
        <header className="shrink-0 sticky top-0 z-20 flex items-center justify-between px-6 py-4 border-b border-white/[0.06] bg-[#0f172a]/90 backdrop-blur-sm">
          <h2 className="text-sm tracking-[0.15em] uppercase text-neutral-300 font-oswald">
            {activeItem}
          </h2>
          <div className="flex items-center gap-4">
            <LiveClock />
            <span className="text-[10px] tracking-widest text-neutral-600 uppercase font-mono hidden sm:inline">
              Models: 4 active
            </span>
            <div className="w-2 h-2 bg-[#00ff87] animate-pulse" />
          </div>
        </header>

        {/* Scrollable main */}
        <div className="main-content">
          {children}
        </div>

      </div>
    </div>
  );
}

/* ── DashboardCard (reusable panel) ──────────────────────────────────────── */
export function DashboardCard({
  title,
  children,
  className = '',
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`card ${className}`}>
      {title && (
        <p className="section-label">{title}</p>
      )}
      {children}
    </div>
  );
}
