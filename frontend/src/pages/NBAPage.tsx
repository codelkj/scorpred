import { DecisionCard, PlanStrip, type Decision } from '../components/DecisionCard';

const games: Decision[] = [
  {
    tier: 'Best Bet',
    side: 'Knicks',
    confidence: 64,
    reason: 'Home shot profile and recent defensive form create a clear edge.',
    data: 'Strong Data',
    support: 'NBA | Knicks vs Nets',
    cta: 'Analyze Match',
  },
  {
    tier: 'Strong Lean',
    side: 'Celtics',
    confidence: 59,
    reason: 'More stable two-way form with a cleaner late-game profile.',
    data: 'Partial Data',
    support: 'NBA | Lakers vs Celtics',
    cta: 'View Matchup',
  },
  {
    tier: 'Risky',
    side: 'Suns',
    confidence: 52,
    reason: 'Higher offensive upside, but rotation uncertainty keeps volatility live.',
    data: 'Limited Data',
    support: 'NBA | Suns vs Clippers',
    cta: 'View Matchup',
  },
];

export default function NBAPage() {
  return (
    <div className="page-stack">
      <section className="hero-card">
        <p className="page-eyebrow">NBA</p>
        <h1 className="page-title">Tonight&apos;s NBA Plan</h1>
        <p className="mt-4 max-w-2xl text-slate-400">
          The same strength-tier workflow: side, confidence, reason, and trust signal.
        </p>
      </section>

      <PlanStrip bestBet={1} strongLean={1} lean={0} risky={1} />

      <section className="section">
        <div>
          <p className="section-label">Top Opportunities Today</p>
          <h2 className="font-oswald text-2xl uppercase tracking-[0.08em] text-white">Premium NBA cards, same rules.</h2>
        </div>
        <div className="grid-2">
          {games.slice(0, 2).map((decision) => (
            <DecisionCard key={decision.side} decision={decision} featured={decision.tier === 'Best Bet'} />
          ))}
        </div>
      </section>

      <section className="section">
        <p className="section-label">Full Slate</p>
        <div className="grid-2">
          {games.map((decision) => (
            <DecisionCard key={`${decision.tier}-${decision.side}`} decision={decision} />
          ))}
        </div>
      </section>
    </div>
  );
}
