import { DecisionCard, PlanStrip, type Decision } from '../components/DecisionCard';

const topOpportunities: Decision[] = [
  {
    tier: 'Best Bet',
    side: 'Arsenal',
    confidence: 68,
    reason: 'Strong attacking form plus home edge.',
    data: 'Strong Data',
    support: 'Clear advantage across recent form and chance quality.',
    cta: 'Analyze Match',
  },
  {
    tier: 'Strong Lean',
    side: 'Napoli',
    confidence: 57,
    reason: 'More stable attack metrics with a useful venue edge.',
    data: 'Partial Data',
    support: 'Solid side profile, with lineup confirmation still worth tracking.',
    cta: 'View Matchup',
  },
];

const recentResults = [
  { match: 'Arsenal vs Bournemouth', tier: 'Best Bet', side: 'Arsenal', score: '1-2', status: 'Incorrect' },
  { match: 'Celtics vs Heat', tier: 'Strong Lean', side: 'Celtics', score: '112-108', status: 'Correct' },
  { match: 'Inter Milan vs AC Milan', tier: 'Risky', side: 'Inter Milan', score: '1-1', status: 'Push' },
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
          ScorPred ranks every playable matchup with a side, strength tier, confidence context, and the trust signal behind it.
        </p>
      </section>

      <PlanStrip bestBet={2} strongLean={5} lean={9} risky={4} />

      <section className="section">
        <div>
          <p className="section-label">Top Opportunities Today</p>
          <h2 className="font-oswald text-2xl uppercase tracking-[0.08em] text-white">
            Only the strongest data-backed opportunities.
          </h2>
        </div>
        <div className="grid-2">
          {topOpportunities.map((decision) => (
            <DecisionCard key={`${decision.tier}-${decision.side}`} decision={decision} featured />
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
                <th className="pb-3 font-medium">Tier</th>
                <th className="pb-3 font-medium">Side</th>
                <th className="pb-3 font-medium">Final</th>
                <th className="pb-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {recentResults.map((row) => (
                <tr key={row.match}>
                  <td className="py-3 text-slate-200">{row.match}</td>
                  <td className="py-3 text-slate-400">{row.tier}</td>
                  <td className="py-3 text-slate-400">{row.side}</td>
                  <td className="py-3 text-slate-400">{row.score}</td>
                  <td className={row.status === 'Correct' ? 'py-3 text-emerald-300' : row.status === 'Push' ? 'py-3 text-amber-300' : 'py-3 text-rose-300'}>
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
