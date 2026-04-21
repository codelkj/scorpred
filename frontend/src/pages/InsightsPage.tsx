import { DashboardCard } from '../components/DashboardTheme';
import { DecisionCard, PlanStrip, type Decision } from '../components/DecisionCard';

const radarCards: Decision[] = [
  {
    action: 'BET',
    side: 'Arsenal',
    matchup: 'Arsenal vs Bournemouth',
    confidence: 68,
    reason: 'Strong attacking profile and cleaner venue context.',
    data: 'Strong Data',
    support: 'Top confidence range',
    cta: 'Analyze Match',
  },
  {
    action: 'CONSIDER',
    side: 'Celtics',
    matchup: '76ers vs Celtics',
    confidence: 61,
    reason: 'More stable scoring path with useful home context.',
    data: 'Partial Data',
    support: 'Playable range',
    cta: 'View Matchup',
  },
];

export default function InsightsPage() {
  return (
    <div className="page-stack">
      <section className="hero-card">
        <p className="page-eyebrow">Opportunity Radar</p>
        <h1 className="page-title">Live slate insight without dashboard clutter.</h1>
        <p className="mt-4 max-w-2xl text-slate-400">
          Scan cross-sport opportunities, action mix, confidence context, and trust signals before opening deeper matchup analysis.
        </p>
      </section>

      <PlanStrip bet={2} consider={12} skip={1} />

      <section className="section">
        <div>
          <p className="section-label">Top Cross-Sport Reads</p>
          <h2 className="font-oswald text-2xl uppercase tracking-[0.08em] text-white">Best current opportunities by confidence and trust.</h2>
        </div>
        <div className="grid-2">
          {radarCards.map((decision) => (
            <DecisionCard key={`${decision.matchup}-${decision.side}`} decision={decision} featured />
          ))}
        </div>
      </section>

      <section className="grid-2">
        <DashboardCard title="Sport Split">
          <p className="text-sm text-slate-400">Soccer and NBA stay separated so each slate keeps its own clean decision surface.</p>
        </DashboardCard>
        <DashboardCard title="Trust Mix">
          <p className="text-sm text-slate-400">Strong, partial, and limited data tags stay visible without making the product feel empty.</p>
        </DashboardCard>
      </section>
    </div>
  );
}
