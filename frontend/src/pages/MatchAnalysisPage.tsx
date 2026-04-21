import { DataBadge, DecisionCard, type Decision } from '../components/DecisionCard';

const decision: Decision = {
  tier: 'Best Bet',
  side: 'Arsenal',
  confidence: 68,
  reason: 'Strong attacking form plus home advantage.',
  data: 'Strong Data',
  support: 'Clear statistical advantage with clean recent data.',
};

const reasons = [
  'Stronger recent form across the last five matches.',
  'Better attacking output in repeatable chance creation.',
  'Home advantage increases the reliability of the side edge.',
  'Opponent defensive weakness shows up in conceded chances.',
];

const context = [
  { label: 'Competition', value: 'Premier League' },
  { label: 'Venue', value: 'Emirates Stadium' },
  { label: 'Draw risk', value: 'Moderate' },
  { label: 'Data confidence', value: 'Strong Data' },
];

export default function MatchAnalysisPage() {
  return (
    <div className="page-stack">
      <section className="hero-card">
        <p className="page-eyebrow">Premier League</p>
        <h1 className="page-title">Arsenal vs Bournemouth</h1>
        <p className="mt-4 max-w-2xl text-slate-400">
          A focused breakdown that keeps the main decision first and the supporting evidence secondary.
        </p>
      </section>

      <div className="analysis-layout">
        <div className="section">
          <DecisionCard decision={decision} featured />

          <section className="card">
            <p className="section-label">Why This Pick</p>
            <ul className="why-list">
              {reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </section>
        </div>

        <aside className="card">
          <p className="section-label">Trust Check</p>
          <DataBadge label="Strong Data" />
          <p className="mt-4 text-sm text-slate-500">
            Recent form, venue context, and side-level matchup data all support the same direction.
          </p>
          <div className="mt-5 space-y-3">
            <div>
              <div className="mb-2 flex justify-between text-xs uppercase tracking-[0.12em] text-slate-500">
                <span>Win probability</span>
                <span>68%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white/[0.06]">
                <div className="h-full rounded-full bg-emerald-300" style={{ width: '68%' }} />
              </div>
            </div>
            <div>
              <div className="mb-2 flex justify-between text-xs uppercase tracking-[0.12em] text-slate-500">
                <span>Attack edge</span>
                <span>72 / 100</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white/[0.06]">
                <div className="h-full rounded-full bg-cyan-300" style={{ width: '72%' }} />
              </div>
            </div>
            {context.map((item) => (
              <div key={item.label} className="flex justify-between gap-4 border-b border-white/[0.05] pb-3 text-sm">
                <span className="text-slate-500">{item.label}</span>
                <strong className="text-right text-slate-200">{item.value}</strong>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
