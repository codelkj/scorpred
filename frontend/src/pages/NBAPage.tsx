import { useFetch } from '../hooks/useFetch';
import { DecisionCard, EmptyState, PlanStrip, type Decision } from '../components/DecisionCard';

interface NBAData {
  slate: Decision[];
  topOpportunities: Decision[];
  plan: { bet: number; consider: number; skip: number };
  error?: string | null;
}

export default function NBAPage() {
  const { data, loading, error } = useFetch<NBAData>('/api/dashboard/nba');

  const slate = data?.slate ?? [];
  const top = data?.topOpportunities ?? [];
  const plan = data?.plan ?? { bet: 0, consider: 0, skip: 0 };

  return (
    <div className="page-stack">
      <section className="hero-card">
        <p className="page-eyebrow">NBA</p>
        <h1 className="page-title">Tonight&apos;s NBA Plan</h1>
        <p className="mt-4 max-w-2xl text-slate-400">
          The same action-first workflow: side, confidence, reason, and trust signal.
        </p>
      </section>

      <PlanStrip bet={plan.bet} consider={plan.consider} skip={plan.skip} />

      <section className="section">
        <div>
          <p className="section-label">Top Opportunities Today</p>
          <h2 className="font-oswald text-2xl uppercase tracking-[0.08em] text-white">Premium NBA cards, same rules.</h2>
        </div>
        {loading ? (
          <div className="empty-state">
            <p className="font-oswald text-lg uppercase tracking-normal text-white">Loading games…</p>
          </div>
        ) : error || data?.error ? (
          <EmptyState
            title="Data unavailable"
            body={data?.error ?? 'Could not load tonight\'s NBA games. Check back shortly.'}
          />
        ) : top.length > 0 ? (
          <div className="grid-2">
            {top.map((decision) => (
              <DecisionCard
                key={`${decision.action}-${decision.side}-${decision.matchup}`}
                decision={decision}
                featured={decision.action === 'BET'}
              />
            ))}
          </div>
        ) : (
          <EmptyState title="Slate still forming" body="No NBA games scheduled yet or data is still loading." />
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
          <EmptyState title="No games found" body="No NBA games are available for tonight." />
        ) : null}
      </section>
    </div>
  );
}
