import { DecisionCard, EmptyState, PlanStrip, type Decision } from '../components/DecisionCard';

const slate: Decision[] = [
  {
    tier: 'Best Bet',
    side: 'Arsenal',
    confidence: 68,
    reason: 'Strong attacking form plus home edge.',
    data: 'Strong Data',
    support: 'Premier League | Arsenal vs Bournemouth',
    cta: 'Analyze Match',
  },
  {
    tier: 'Strong Lean',
    side: 'Barcelona',
    confidence: 58,
    reason: 'Attacking edge, but opponent chance quality is live.',
    data: 'Partial Data',
    support: 'La Liga | Barcelona vs Real Madrid',
    cta: 'View Matchup',
  },
  {
    tier: 'Risky',
    side: 'Inter Milan',
    confidence: 51,
    reason: 'Narrow venue-led edge with elevated derby volatility.',
    data: 'Limited Data',
    support: 'Serie A | Inter Milan vs AC Milan',
    cta: 'View Matchup',
  },
];

export default function SoccerPage() {
  const top = slate.filter((item) => item.tier === 'Best Bet' || item.tier === 'Strong Lean');

  return (
    <div className="page-stack">
      <section className="hero-card">
        <p className="page-eyebrow">EPL, La Liga, Bundesliga, Serie A</p>
        <h1 className="page-title">Today&apos;s Soccer Plan</h1>
        <p className="mt-4 max-w-2xl text-slate-400">
          Start with the strongest tiers, scan the full slate, then open a focused matchup when more context is needed.
        </p>
      </section>

      <PlanStrip bestBet={1} strongLean={1} lean={0} risky={1} />

      <section className="section">
        <div>
          <p className="section-label">Top Opportunities Today</p>
          <h2 className="font-oswald text-2xl uppercase tracking-[0.08em] text-white">Strongest picks first.</h2>
        </div>
        {top.length ? (
          <div className="grid-2">
            {top.map((decision) => (
              <DecisionCard key={decision.side} decision={decision} featured />
            ))}
          </div>
        ) : (
          <EmptyState title="Slate still forming" body="Once fixtures load, the strongest playable sides rise here automatically." />
        )}
      </section>

      <section className="section">
        <p className="section-label">Full Slate</p>
        <div className="grid-2">
          {slate.map((decision) => (
            <DecisionCard key={`${decision.tier}-${decision.side}`} decision={decision} />
          ))}
        </div>
      </section>
    </div>
  );
}
