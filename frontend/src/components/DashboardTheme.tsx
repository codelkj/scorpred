import { useEffect, useState, type ReactNode } from 'react';
import { Activity, CheckCircle2, Dumbbell, Hexagon, Home, Search, Trophy } from 'lucide-react';

interface NavItem {
  label: string;
  icon: ReactNode;
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Home', icon: <Home className="h-4 w-4" /> },
  { label: 'Soccer', icon: <Trophy className="h-4 w-4" /> },
  { label: 'NBA', icon: <Dumbbell className="h-4 w-4" /> },
  { label: 'Match Analysis', icon: <Search className="h-4 w-4" /> },
  { label: 'Results', icon: <CheckCircle2 className="h-4 w-4" /> },
];

function LiveClock() {
  const [time, setTime] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <span className="rounded-full border border-white/[0.08] px-3 py-1 text-[11px] text-slate-400">
      {time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
    </span>
  );
}

export default function DashboardLayout({
  children,
  activeItem = 'Home',
  onNavigate,
}: {
  children: ReactNode;
  activeItem?: string;
  onNavigate?: (item: string) => void;
}) {
  return (
    <div className="app-layout">
      <aside className="sidebar hidden flex-col border-r border-white/[0.07] bg-[#0c1424] md:flex">
        <div className="border-b border-white/[0.07] px-5 py-6">
          <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl border border-emerald-400/25 bg-emerald-400/10">
            <Hexagon className="h-5 w-5 text-emerald-300" strokeWidth={1.6} />
          </div>
          <p className="font-oswald text-xl uppercase tracking-[0.18em] text-white">ScorPred</p>
          <p className="mt-1 text-xs text-slate-500">Decision Intelligence</p>
        </div>

        <nav className="flex-1 space-y-2 px-4 py-6">
          {NAV_ITEMS.map((item) => {
            const active = item.label === activeItem;
            return (
              <button
                key={item.label}
                type="button"
                onClick={() => onNavigate?.(item.label)}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition ${
                  active
                    ? 'border border-emerald-400/20 bg-emerald-400/10 text-emerald-200 shadow-[0_0_24px_rgba(20,184,166,0.08)]'
                    : 'text-slate-500 hover:bg-white/[0.04] hover:text-slate-200'
                }`}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="border-t border-white/[0.07] p-5">
          <p className="text-xs leading-5 text-slate-500">
            Clear actions, confidence, and trust signals for every slate.
          </p>
        </div>
      </aside>

      <div className="content-area">
        <header className="topbar">
          <div>
            <p className="text-[11px] uppercase tracking-[0.2em] text-emerald-300">ScorPred</p>
            <h1 className="font-oswald text-lg uppercase tracking-[0.08em] text-white">{activeItem}</h1>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden items-center gap-2 rounded-full border border-white/[0.08] px-3 py-1 text-[11px] text-slate-400 sm:flex">
              <Activity className="h-3.5 w-3.5 text-emerald-300" />
              Data-aware
            </span>
            <LiveClock />
          </div>
        </header>

        <div className="mobile-nav md:hidden">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.label}
              type="button"
              onClick={() => onNavigate?.(item.label)}
              className={item.label === activeItem ? 'text-emerald-200' : 'text-slate-500'}
            >
              {item.label}
            </button>
          ))}
        </div>

        <main className="main-content">{children}</main>
      </div>
    </div>
  );
}

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
    <section className={`card ${className}`}>
      {title && <p className="section-label">{title}</p>}
      {children}
    </section>
  );
}
