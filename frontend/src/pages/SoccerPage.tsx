import { DecisionCard, EmptyState, PlanStrip, type Decision } from '../components/DecisionCard';

const slate: Decision[] = [
  {
    action: 'BET',
    pick: 'Arsenal',
    confidence: 68,
    reason: 'Strong attacking form plus home edge.',
    data: 'Strong Data',
    support: 'Premier League | Arsenal vs Bournemouth',
    cta: 'Analyze Match',
  },
  {
    action: 'CONSIDER',
    pick: 'Barcelona',
    confidence: 55,
    reason: 'Attacking edge, but opponent chance quality is live.',
    data: 'Partial Data',
    support: 'La Liga | Barcelona vs Real Madrid',
    cta: 'View Matchup',
  },
  {
    action: 'SKIP',
    pick: 'No reliable edge',
    confidence: 49,
    reason: 'Even matchup with elevated late-lineup sensitivity.',
    data: 'Limited Data',
    support: 'Serie A | Inter Milan vs AC Milan',
    cta: 'View Matchup',
  },
];

export default function SoccerPage() {
  const top = slate.filter((item) => item.action === 'BET');

  return (
    <div className="page-stack">
      <section className="hero-card">
        <p className="page-eyebrow">EPL, La Liga, Bundesliga, Serie A</p>
        <h1 className="page-title">Today&apos;s Soccer Plan</h1>
        <p className="mt-4 max-w-2xl text-slate-400">
          Start with the plan, scan the strongest edges, then open a focused matchup when more context is needed.
        </p>
      </section>

      <PlanStrip bet={1} consider={1} skip={1} />

      <section className="section">
        <div>
          <p className="section-label">Top Opportunities Today</p>
          <h2 className="font-oswald text-2xl uppercase tracking-[0.08em] text-white">Strongest picks first.</h2>
        </div>
        {top.length ? (
          <div className="grid-2">
            {top.map((decision) => (
              <DecisionCard key={decision.pick} decision={decision} featured />
            ))}
          </div>
        ) : (
          <EmptyState title="No strong opportunities today" body="Most matches are thin-edge today. The full slate still shows transparent reasons." />
        )}
      </section>

      <section className="section">
        <p className="section-label">Full Slate</p>
        <div className="grid-2">
          {slate.map((decision) => (
            <DecisionCard key={`${decision.action}-${decision.pick}`} decision={decision} />
          ))}
        </div>
      </section>
    </div>
  );
}
