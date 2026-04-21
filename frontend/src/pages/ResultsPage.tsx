const summary = [
  { label: 'Total graded picks', value: '126' },
  { label: 'Win rate', value: '61.9%' },
  { label: 'Correct picks', value: '78' },
  { label: 'Incorrect picks', value: '43' },
  { label: 'Pushes', value: '5' },
  { label: 'Skips', value: '31' },
];

const recentForm = ['W', 'W', 'L', 'P', 'W', 'S', 'W', 'L', 'W', 'W'];

const rows = [
  {
    date: '2026-04-20',
    competition: 'Premier League',
    match: 'Arsenal vs Bournemouth',
    score: '1-2',
    action: 'BET',
    side: 'Arsenal',
    status: 'Incorrect',
  },
  {
    date: '2026-04-20',
    competition: 'NBA',
    match: 'Celtics vs Heat',
    score: '112-108',
    action: 'CONSIDER',
    side: 'Celtics',
    status: 'Correct',
  },
  {
    date: '2026-04-19',
    competition: 'Premier League',
    match: 'Burnley vs Everton',
    score: '0-0',
    action: 'SKIP',
    side: 'No reliable edge',
    status: 'Skipped',
  },
];

const breakdown = [
  { label: 'BET win rate', value: '64.4%' },
  { label: 'CONSIDER win rate', value: '55.8%' },
  { label: 'SKIP usage', value: '19.7%' },
  { label: 'Current streak', value: 'W2' },
  { label: 'Best league', value: 'Premier League' },
];

function statusClass(status: string) {
  if (status === 'Correct') return 'text-emerald-300';
  if (status === 'Incorrect') return 'text-rose-300';
  if (status === 'Skipped') return 'text-slate-500';
  return 'text-amber-300';
}

export default function ResultsPage() {
  return (
    <div className="page-stack">
      <section className="hero-card">
        <p className="page-eyebrow">Accountability</p>
        <h1 className="page-title">Results</h1>
        <p className="mt-4 max-w-2xl text-slate-400">
          A transparent record of what ScorPred recommended and what happened after the final whistle.
        </p>
      </section>

      <section className="kpi-grid">
        {summary.map((item) => (
          <article key={item.label} className="card">
            <p className="section-label">{item.label}</p>
            <strong className="font-oswald text-3xl text-white">{item.value}</strong>
          </article>
        ))}
      </section>

      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="section-label">Recent Form</p>
            <h2 className="font-oswald text-xl uppercase tracking-[0.08em] text-white">Last 10 graded actions</h2>
          </div>
          <div className="form-strip">
            {recentForm.map((item, index) => (
              <span key={`${item}-${index}`} className={`form-dot form-dot-${item}`}>{item}</span>
            ))}
          </div>
        </div>
      </section>

      <section className="card">
        <div className="mb-5 flex flex-wrap gap-3">
          {['All leagues', 'Last 30 days', 'All actions'].map((filter) => (
            <button key={filter} type="button" className="rounded-full border border-white/[0.1] px-4 py-2 text-sm text-slate-300">
              {filter}
            </button>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="border-b border-white/[0.06] text-left text-xs uppercase tracking-[0.12em] text-slate-500">
                <th className="pb-3 font-medium">Date</th>
                <th className="pb-3 font-medium">Competition</th>
                <th className="pb-3 font-medium">Match</th>
                <th className="pb-3 font-medium">Final score</th>
                <th className="pb-3 font-medium">Action</th>
                <th className="pb-3 font-medium">Side</th>
                <th className="pb-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {rows.map((row) => (
                <tr key={`${row.date}-${row.match}`}>
                  <td className="py-3 text-slate-500">{row.date}</td>
                  <td className="py-3 text-slate-400">{row.competition}</td>
                  <td className="py-3 text-slate-200">{row.match}</td>
                  <td className="py-3 text-slate-400">{row.score}</td>
                  <td className="py-3 text-slate-300">{row.action}</td>
                  <td className="py-3 text-slate-400">{row.side}</td>
                  <td className={`py-3 font-semibold ${statusClass(row.status)}`}>{row.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid-2">
        {breakdown.map((item) => (
          <article key={item.label} className="card">
            <p className="section-label">{item.label}</p>
            <strong className="font-oswald text-2xl text-white">{item.value}</strong>
          </article>
        ))}
      </section>
    </div>
  );
}
