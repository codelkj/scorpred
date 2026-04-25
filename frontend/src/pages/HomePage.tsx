import { useFetch } from '../hooks/useFetch';
import { DecisionCard, EmptyState, PlanStrip, type Decision } from '../components/DecisionCard';

interface HomeData {
  topOpportunities: Decision[];
  insightRows: { match: string; action: string; side: string; confidence: string; trust: string }[];
  plan: { bet: number; consider: number; skip: number };
}

const quickLinks = [
  { title: 'Soccer', body: 'Today plan, top opportunities, and full slate.' },
  { title: 'NBA', body: 'Same decision-first workflow for tonight.' },
  { title: 'Match Analysis', body: 'Focused breakdown of one matchup.' },
  { title: 'Insights', body: 'Opportunity radar and trust mix.' },
];

export default function HomePage() {
  const { data, loading, error } = useFetch<HomeData>('/api/dashboard/home');

  const topOpportunities = data?.topOpportunities ?? [];
  const insightRows = data?.insightRows ?? [];
  const plan = data?.plan ?? { bet: 0, consider: 0, skip: 0 };

  return (
    <div className="page-stack">
      <section className="hero-card">
        <p className="page-eyebrow">Decision Intelligence</p>
        <h1 className="page-title">Clear actions for matchday.</h1>
        <p className="mt-4 max-w-2xl text-slate-400">
          ScorPred ranks every playable matchup with a side, action, confidence context, and the trust signal behind it.
        </p>
      </section>

      <PlanStrip bet={plan.bet} consider={plan.consider} skip={plan.skip} />

      <section className="section">
        <div>
          <p className="section-label">Top Opportunities Today</p>
          <h2 className="font-oswald text-2xl uppercase tracking-[0.08em] text-white">
            Only the strongest data-backed opportunities.
          </h2>
        </div>
        {loading ? (
          <div className="empty-state">
            <p className="font-oswald text-lg uppercase tracking-normal text-white">Loading opportunities…</p>
          </div>
        ) : error ? (
          <EmptyState title="Data unavailable" body="Could not load today's opportunities. The server may still be warming up." />
        ) : topOpportunities.length > 0 ? (
          <div className="grid-2">
            {topOpportunities.map((decision) => (
              <DecisionCard key={`${decision.action}-${decision.side}-${decision.matchup}`} decision={decision} featured />
            ))}
          </div>
        ) : (
          <EmptyState title="Slate still forming" body="Once fixtures load, the strongest playable sides rise here automatically." />
        )}
      </section>

      <section className="section">
        <p className="section-label">Opportunity Radar</p>
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead>
              <tr className="border-b border-white/[0.06] text-left text-xs uppercase tracking-[0.12em] text-slate-500">
                <th className="pb-3 font-medium">Match</th>
                <th className="pb-3 font-medium">Action</th>
                <th className="pb-3 font-medium">Side</th>
                <th className="pb-3 font-medium">Confidence</th>
                <th className="pb-3 font-medium">Trust</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {loading ? (
                <tr><td colSpan={5} className="py-4 text-center text-slate-500">Loading…</td></tr>
              ) : insightRows.length === 0 ? (
                <tr><td colSpan={5} className="py-4 text-center text-slate-500">No data available yet.</td></tr>
              ) : (
                insightRows.map((row) => (
                  <tr key={row.match}>
                    <td className="py-3 text-slate-200">{row.match}</td>
                    <td className="py-3 text-slate-400">{row.action}</td>
                    <td className="py-3 text-slate-400">{row.side}</td>
                    <td className="py-3 text-emerald-300">{row.confidence}</td>
                    <td className="py-3 text-slate-400">{row.trust}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid-2">
        {quickLinks.map((link) => (
          <article key={link.title} className="card">
            <h3 className="font-oswald text-xl uppercase tracking-[0.08em] text-white">{link.title}</h3>
            <p className="mt-2 text-sm text-slate-500">{link.body}</p>
          </article>
        ))}
      </section>
    </div>
  );
}
