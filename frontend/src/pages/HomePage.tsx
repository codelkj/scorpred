import { DecisionCard, PlanStrip, type Decision } from '../components/DecisionCard';

const topOpportunities: Decision[] = [
  {
    action: 'BET',
    pick: 'Arsenal',
    confidence: 68,
    reason: 'Strong attacking form plus home edge.',
    data: 'Strong Data',
    support: 'Clear advantage across recent form and chance quality.',
    cta: 'Analyze Match',
  },
  {
    action: 'CONSIDER',
    pick: 'Napoli',
    confidence: 54,
    reason: 'Slight edge with a few open questions.',
    data: 'Partial Data',
    support: 'Monitor team news before committing.',
    cta: 'View Matchup',
  },
];

const recentResults = [
  { match: 'Arsenal vs Bournemouth', action: 'BET', side: 'Arsenal', score: '1-2', status: 'Incorrect' },
  { match: 'Celtics vs Heat', action: 'CONSIDER', side: 'Celtics', score: '112-108', status: 'Correct' },
  { match: 'Burnley vs Everton', action: 'SKIP', side: 'No reliable edge', score: '0-0', status: 'Skipped' },
];

const quickLinks = [
  { title: 'Soccer', body: 'Today plan, top opportunities, and full slate.' },
  { title: 'NBA', body: 'Same decision-first workflow for tonight.' },
  { title: 'Match Analysis', body: 'Focused breakdown of one matchup.' },
  { title: 'Results', body: 'Transparent tracking and recent form.' },
];

export default function HomePage() {
  return (
    <div className="page-stack">
      <section className="hero-card">
        <p className="page-eyebrow">Decision Intelligence</p>
        <h1 className="page-title">Clear actions for matchday.</h1>
        <p className="mt-4 max-w-2xl text-slate-400">
          ScorPred turns each slate into a simple decision: what to do, why it matters, and how trustworthy the data is.
        </p>
      </section>

      <PlanStrip bet={2} consider={5} skip={14} />

      <section className="section">
        <div>
          <p className="section-label">Top Opportunities Today</p>
          <h2 className="font-oswald text-2xl uppercase tracking-[0.08em] text-white">
            Only the strongest data-backed opportunities.
          </h2>
        </div>
        <div className="grid-2">
          {topOpportunities.map((decision) => (
            <DecisionCard key={`${decision.action}-${decision.pick}`} decision={decision} featured />
          ))}
        </div>
      </section>

      <section className="section">
        <p className="section-label">Recent Results</p>
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead>
              <tr className="border-b border-white/[0.06] text-left text-xs uppercase tracking-[0.12em] text-slate-500">
                <th className="pb-3 font-medium">Match</th>
                <th className="pb-3 font-medium">Action</th>
                <th className="pb-3 font-medium">Side</th>
                <th className="pb-3 font-medium">Final</th>
                <th className="pb-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {recentResults.map((row) => (
                <tr key={row.match}>
                  <td className="py-3 text-slate-200">{row.match}</td>
                  <td className="py-3 text-slate-400">{row.action}</td>
                  <td className="py-3 text-slate-400">{row.side}</td>
                  <td className="py-3 text-slate-400">{row.score}</td>
                  <td className={row.status === 'Correct' ? 'py-3 text-emerald-300' : row.status === 'Skipped' ? 'py-3 text-slate-500' : 'py-3 text-rose-300'}>
                    {row.status}
                  </td>
                </tr>
              ))}
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
