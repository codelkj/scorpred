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

const volatilityRows = [
  {
    side: 'Napoli',
    matchup: 'Napoli vs Lazio',
    action: 'CONSIDER',
    confidence: 57,
    note: 'Playable read with lineup and finishing volatility still worth checking.',
  },
  {
    side: 'Suns',
    matchup: 'Suns vs Clippers',
    action: 'CONSIDER',
    confidence: 55,
    note: 'Higher offensive upside, but rotation context can swing the read.',
  },
];

const trustRows = [
  { label: 'Strong or partial data', value: '12' },
  { label: 'Top confidence reads', value: '3' },
  { label: 'Caution range', value: '2' },
];

export default function InsightsPage() {
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
        {['All', 'Soccer', 'NBA'].map((item, index) => (
          <button
            key={item}
            type="button"
            className={`rounded-full border px-4 py-2 text-sm ${index === 0 ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200' : 'border-white/[0.08] text-slate-400'}`}
          >
            {item}
          </button>
        ))}
      </div>

      <PlanStrip bet={2} consider={12} skip={1} />

      <section className="grid-2">
        {trustRows.map((row) => (
          <DashboardCard key={row.label} title={row.label}>
            <p className="font-oswald text-3xl uppercase text-white">{row.value}</p>
          </DashboardCard>
        ))}
      </section>

      <section className="section">
        <div>
          <p className="section-label">Top Cross-Sport Reads</p>
          <h2 className="font-oswald text-2xl uppercase tracking-[0.08em] text-white">Best current opportunities by confidence and trust.</h2>
        </div>
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
      </section>

      <section className="section">
        <div>
          <p className="section-label">Volatility Watch</p>
          <h2 className="font-oswald text-2xl uppercase tracking-[0.08em] text-white">Playable reads that need one more context check.</h2>
        </div>
        <div className="grid-2">
          {volatilityRows.map((row) => (
            <article key={row.matchup} className="card">
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
      </section>
    </div>
  );
}
