import { useFetch } from '../hooks/useFetch';
import { DecisionCard, EmptyState, PlanStrip, type Decision } from '../components/DecisionCard';

interface SoccerData {
  slate: Decision[];
  topOpportunities: Decision[];
  plan: { bet: number; consider: number; skip: number };
  error?: string | null;
}

export default function SoccerPage() {
  const { data, loading, error } = useFetch<SoccerData>('/api/dashboard/soccer');

  const slate = data?.slate ?? [];
  const top = data?.topOpportunities ?? [];
  const plan = data?.plan ?? { bet: 0, consider: 0, skip: 0 };

  return (
    <div className="page-stack">
      <section className="hero-card">
        <p className="page-eyebrow">EPL, La Liga, Bundesliga, Serie A</p>
        <h1 className="page-title">Today&apos;s Soccer Plan</h1>
        <p className="mt-4 max-w-2xl text-slate-400">
          Start with the strongest actions, scan the full slate, then open a focused matchup when more context is needed.
        </p>
      </section>

      <PlanStrip bet={plan.bet} consider={plan.consider} skip={plan.skip} />

      <section className="section">
        <div>
          <p className="section-label">Top Opportunities Today</p>
          <h2 className="font-oswald text-2xl uppercase tracking-[0.08em] text-white">Strongest picks first.</h2>
        </div>
        {loading ? (
          <div className="empty-state">
            <p className="font-oswald text-lg uppercase tracking-normal text-white">Loading fixtures…</p>
          </div>
        ) : error || data?.error ? (
          <EmptyState
            title="Data unavailable"
            body={data?.error ?? 'Could not load today\'s soccer fixtures. Check back shortly.'}
          />
        ) : top.length > 0 ? (
          <div className="grid-2">
            {top.map((decision) => (
              <DecisionCard key={`${decision.action}-${decision.side}-${decision.matchup}`} decision={decision} featured />
            ))}
          </div>
        ) : (
          <EmptyState title="Slate still forming" body="Once fixtures load, the strongest playable sides rise here automatically." />
        )}
      </section>

      <section className="section">
        <p className="section-label">Full Slate</p>
        {loading ? (
          <div className="empty-state">
            <p className="font-oswald text-lg uppercase tracking-normal text-white">Loading slate…</p>
          </div>
        ) : slate.length > 0 ? (
          <div className="grid-2">
            {slate.map((decision) => (
              <DecisionCard key={`${decision.action}-${decision.side}-${decision.matchup}`} decision={decision} />
            ))}
          </div>
        ) : !loading ? (
          <EmptyState title="No fixtures found" body="No soccer matches are available for the current league and date." />
        ) : null}
      </section>
    </div>
  );
}
