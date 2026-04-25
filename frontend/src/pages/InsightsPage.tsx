import { useState } from 'react';
import { DashboardCard } from '../components/DashboardTheme';
import { DecisionCard, EmptyState, PlanStrip, type Decision } from '../components/DecisionCard';
import { useFetch } from '../hooks/useFetch';

interface VolatilityRow {
  side: string;
  matchup: string;
  action: string;
  confidence: number;
  note: string;
}

interface InsightsData {
  radarCards: Decision[];
  volatilityRows: VolatilityRow[];
  confidenceGroups: Record<string, number>;
  plan: { bet: number; consider: number; skip: number };
  sportFilter: string;
}

const SPORT_FILTERS = ['All', 'Soccer', 'NBA'];

export default function InsightsPage() {
  const [sport, setSport] = useState('All');
  const sportParam = sport === 'All' ? 'all' : sport.toLowerCase();
  const { data, loading } = useFetch<InsightsData>(`/api/dashboard/insights?sport=${sportParam}`, [sport]);

  const radarCards = data?.radarCards ?? [];
  const volatilityRows = data?.volatilityRows ?? [];
  const plan = data?.plan ?? { bet: 0, consider: 0, skip: 0 };
  const confidenceGroups = data?.confidenceGroups ?? {
    'Top confidence': 0,
    'Playable range': 0,
    'Caution range': 0,
  };

  return (
    <div className="page-stack">
      <section className="hero-card">
        <p className="page-eyebrow">Command Center</p>
        <h1 className="page-title">Find the best reads, the risky reads, and what to check next.</h1>
        <p className="mt-4 max-w-2xl text-slate-400">
          Scan cross-sport opportunities, action mix, confidence context, volatility flags, and trust signals before opening deeper matchup analysis.
        </p>
      </section>

      <div className="flex flex-wrap gap-2">
        {SPORT_FILTERS.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setSport(item)}
            className={`rounded-full border px-4 py-2 text-sm transition ${
              item === sport
                ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200'
                : 'border-white/[0.08] text-slate-400 hover:border-white/20 hover:text-slate-200'
            }`}
          >
            {item}
          </button>
        ))}
      </div>

      <PlanStrip bet={plan.bet} consider={plan.consider} skip={plan.skip} />

      <section className="grid-2">
        {Object.entries(confidenceGroups).map(([label, value]) => (
          <DashboardCard key={label} title={label}>
            <p className="font-oswald text-3xl uppercase text-white">
              {loading ? '—' : value}
            </p>
          </DashboardCard>
        ))}
      </section>

      <section className="section">
        <div>
          <p className="section-label">Top Cross-Sport Reads</p>
          <h2 className="font-oswald text-2xl uppercase tracking-[0.08em] text-white">Best current opportunities by confidence and trust.</h2>
        </div>
        {loading ? (
          <div className="empty-state">
            <p className="font-oswald text-lg uppercase tracking-normal text-white">Loading opportunities…</p>
          </div>
        ) : radarCards.length > 0 ? (
          <div className="grid-2">
            {radarCards.map((decision) => (
              <div key={`${decision.matchup}-${decision.side}`} className="space-y-3">
                <DecisionCard decision={decision} featured />
                <div className="grid grid-cols-2 gap-2 text-xs text-slate-400">
                  <span className="rounded-lg border border-white/[0.08] bg-white/[0.03] p-3">Confidence: {decision.confidence}%</span>
                  <span className="rounded-lg border border-white/[0.08] bg-white/[0.03] p-3">Trust: {decision.data}</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState title="No reads available" body="No opportunities found for the selected sport filter." />
        )}
      </section>

      <section className="section">
        <div>
          <p className="section-label">Volatility Watch</p>
          <h2 className="font-oswald text-2xl uppercase tracking-[0.08em] text-white">Playable reads that need one more context check.</h2>
        </div>
        {loading ? (
          <div className="empty-state">
            <p className="font-oswald text-lg uppercase tracking-normal text-white">Loading…</p>
          </div>
        ) : volatilityRows.length > 0 ? (
          <div className="grid-2">
            {volatilityRows.map((row) => (
              <article key={`${row.matchup}-${row.side}`} className="card">
                <p className="text-xs uppercase tracking-[0.14em] text-amber-300">{row.action}</p>
                <h3 className="mt-2 font-oswald text-2xl uppercase tracking-normal text-white">{row.side}</h3>
                <p className="mt-1 text-sm text-slate-500">{row.matchup}</p>
                <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/[0.06]">
                  <div className="h-full rounded-full bg-amber-300" style={{ width: `${row.confidence}%` }} />
                </div>
                <p className="mt-4 text-sm text-slate-400">{row.note}</p>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="No volatility flags" body="All current reads are clean — no elevated volatility detected." />
        )}
      </section>
    </div>
  );
}
