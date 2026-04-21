import { DecisionCard, PlanStrip, type Decision } from '../components/DecisionCard';

const games: Decision[] = [
  {
    action: 'BET',
    pick: 'Knicks',
    confidence: 64,
    reason: 'Home shot profile and recent defensive form create a clear edge.',
    data: 'Strong Data',
    support: 'NBA | Knicks vs Nets',
    cta: 'Analyze Match',
  },
  {
    action: 'CONSIDER',
    pick: 'Celtics',
    confidence: 56,
    reason: 'Slight side edge, but spread value is thin.',
    data: 'Partial Data',
    support: 'NBA | Lakers vs Celtics',
    cta: 'View Matchup',
  },
  {
    action: 'SKIP',
    pick: 'No reliable edge',
    confidence: 48,
    reason: 'Rotation uncertainty makes the matchup too fragile.',
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
          The same decision-first workflow: action, side, confidence, reason, and trust signal.
        </p>
      </section>

      <PlanStrip bet={1} consider={1} skip={1} />

      <section className="section">
        <div>
          <p className="section-label">Top Opportunities Today</p>
          <h2 className="font-oswald text-2xl uppercase tracking-[0.08em] text-white">Premium NBA cards, same rules.</h2>
        </div>
        <div className="grid-2">
          {games.slice(0, 2).map((decision) => (
            <DecisionCard key={decision.pick} decision={decision} featured={decision.action === 'BET'} />
          ))}
        </div>
      </section>

      <section className="section">
        <p className="section-label">Full Slate</p>
        <div className="grid-2">
          {games.map((decision) => (
            <DecisionCard key={`${decision.action}-${decision.pick}`} decision={decision} />
          ))}
        </div>
      </section>
    </div>
  );
}
