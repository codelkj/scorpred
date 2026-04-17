/* ─────────────────────────────────────────────────────────────────────────────
   HomePage — Decision intelligence dashboard.
   Structure: page header → hero pick → kpi-grid → grid-2 previews → section
   ───────────────────────────────────────────────────────────────────────────── */

const TOP_PICK = {
  sport: 'Soccer',
  league: 'Premier League',
  match: 'Man City vs Arsenal',
  pick: 'Home Win',
  confidence: 0.87,
  edge: '+3.8pp',
  prob: 58,
};

const KPIS = [
  { label: 'Predictions Today', value: '18', sub: '6 high-confidence' },
  { label: 'Model Accuracy', value: '67.2%', sub: 'last 90 days' },
  { label: 'Combined Edge', value: '+4.1pp', sub: 'vs market baseline' },
  { label: 'Active Models', value: '4', sub: 'RF · XGB · LGBM · Stack' },
];

const SOCCER_PREVIEW = [
  { home: 'Man City', away: 'Arsenal', prob: 58, pick: 'H', conf: 'HIGH' },
  { home: 'Barcelona', away: 'Real Madrid', prob: 44, pick: 'H', conf: 'MED' },
  { home: 'Bayern', away: 'Dortmund', prob: 62, pick: 'H', conf: 'HIGH' },
];

const NBA_PREVIEW = [
  { home: 'Lakers', away: 'Celtics', prob: 46, pick: 'A', conf: 'MED' },
  { home: 'Warriors', away: 'Nuggets', prob: 54, pick: 'H', conf: 'HIGH' },
  { home: 'Bucks', away: 'Heat', prob: 61, pick: 'H', conf: 'HIGH' },
];

const RECENT = [
  { match: 'Liverpool vs Chelsea', pick: 'Home Win', result: 'WIN', pct: 71 },
  { match: 'Knicks vs Nets', pick: 'Away Win', result: 'WIN', pct: 63 },
  { match: 'PSG vs Lyon', pick: 'Home Win', result: 'WIN', pct: 78 },
  { match: 'Spurs vs Villa', pick: 'Draw', result: 'LOSS', pct: 38 },
  { match: 'Heat vs Bulls', pick: 'Home Win', result: 'WIN', pct: 59 },
];

function ConfBadge({ conf }: { conf: string }) {
  const color = conf === 'HIGH' ? '#00ff87' : '#00d4ff';
  return (
    <span
      className="text-[9px] tracking-[0.2em] uppercase font-mono px-1.5 py-0.5 border"
      style={{ color, borderColor: `${color}33` }}
    >
      {conf}
    </span>
  );
}

export default function HomePage() {
  return (
    <div className="page-stack">

      {/* ── Page header ────────────────────────────────────────────────── */}
      <div>
        <p className="page-eyebrow">// System Online</p>
        <h1 className="page-title">Decision Intelligence</h1>
        <div className="mt-4 h-px bg-gradient-to-r from-[#00ff87]/20 to-transparent" />
      </div>

      {/* ── Hero pick ──────────────────────────────────────────────────── */}
      <div className="hero-card">
        <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
          <div>
            <p className="text-[10px] tracking-[0.25em] uppercase font-mono text-[#00ff87] mb-1">
              Top Pick Today
            </p>
            <p className="text-[10px] tracking-[0.2em] uppercase font-mono text-neutral-500">
              {TOP_PICK.sport} · {TOP_PICK.league}
            </p>
          </div>
          <span className="text-[10px] tracking-[0.2em] uppercase font-mono text-[#00ff87] border border-[#00ff87]/20 px-2.5 py-1">
            EDGE {TOP_PICK.edge}
          </span>
        </div>
        <h2 className="text-2xl font-oswald tracking-[0.08em] uppercase text-white mb-5">
          {TOP_PICK.match}
        </h2>
        <div className="flex items-end gap-6 flex-wrap">
          <div>
            <p className="text-[10px] tracking-[0.2em] uppercase font-mono text-neutral-500 mb-1">Pick</p>
            <p className="text-lg font-bold text-[#00ff87] tracking-wider">{TOP_PICK.pick}</p>
          </div>
          <div>
            <p className="text-[10px] tracking-[0.2em] uppercase font-mono text-neutral-500 mb-1">Probability</p>
            <p className="text-lg font-bold text-white">{TOP_PICK.prob}%</p>
          </div>
          <div>
            <p className="text-[10px] tracking-[0.2em] uppercase font-mono text-neutral-500 mb-1">Confidence</p>
            <p className="text-lg font-bold text-white">{(TOP_PICK.confidence * 100).toFixed(0)}%</p>
          </div>
          <div className="ml-auto">
            <div className="flex gap-2">
              {['ML', 'RULES', 'ELO', 'STACK'].map((t) => (
                <span key={t} className="text-[9px] tracking-widest font-mono text-neutral-600 border border-white/10 px-2 py-0.5">
                  {t}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── KPI row ────────────────────────────────────────────────────── */}
      <div className="kpi-grid">
        {KPIS.map((k) => (
          <div key={k.label} className="card">
            <p className="section-label">{k.label}</p>
            <p className="text-2xl font-bold text-[#00ff87] font-oswald">{k.value}</p>
            <p className="text-[10px] text-neutral-600 font-mono mt-1">{k.sub}</p>
          </div>
        ))}
      </div>

      {/* ── Soccer + NBA previews ───────────────────────────────────────── */}
      <div className="grid-2">
        {/* Soccer */}
        <div className="section-stack">
          <p className="section-label">⚽ Soccer · Today</p>
          {SOCCER_PREVIEW.map((g) => (
            <div key={g.home} className="card flex items-center justify-between gap-4">
              <div className="flex-1 min-w-0">
                <p className="text-xs font-bold text-white tracking-wide truncate">
                  {g.home} <span className="text-neutral-600 font-normal">vs</span> {g.away}
                </p>
                <div className="mt-2 h-1 bg-white/5 overflow-hidden">
                  <div className="h-full bg-[#00ff87]/60" style={{ width: `${g.prob}%` }} />
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-xs font-mono text-[#00ff87]">{g.prob}%</span>
                <ConfBadge conf={g.conf} />
              </div>
            </div>
          ))}
        </div>

        {/* NBA */}
        <div className="section-stack">
          <p className="section-label">🏀 NBA · Tonight</p>
          {NBA_PREVIEW.map((g) => (
            <div key={g.home} className="card flex items-center justify-between gap-4">
              <div className="flex-1 min-w-0">
                <p className="text-xs font-bold text-white tracking-wide truncate">
                  {g.home} <span className="text-neutral-600 font-normal">vs</span> {g.away}
                </p>
                <div className="mt-2 h-1 bg-white/5 overflow-hidden">
                  <div className="h-full bg-[#00d4ff]/60" style={{ width: `${g.prob}%` }} />
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-xs font-mono text-[#00d4ff]">{g.prob}%</span>
                <ConfBadge conf={g.conf} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Recent results ──────────────────────────────────────────────── */}
      <div className="section">
        <p className="section-label">Recent Results</p>
        <div className="card overflow-x-auto">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-white/5 text-neutral-600 uppercase tracking-wider">
                <th className="text-left pb-3 pr-4 font-normal">Match</th>
                <th className="text-left pb-3 pr-4 font-normal">Pick</th>
                <th className="text-right pb-3 pr-4 font-normal">Prob</th>
                <th className="text-right pb-3 font-normal">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {RECENT.map((r) => (
                <tr key={r.match}>
                  <td className="py-2.5 pr-4 text-neutral-300">{r.match}</td>
                  <td className="py-2.5 pr-4 text-neutral-500">{r.pick}</td>
                  <td className="py-2.5 pr-4 text-right text-neutral-400">{r.pct}%</td>
                  <td className="py-2.5 text-right">
                    <span className={r.result === 'WIN' ? 'text-[#00ff87]' : 'text-red-400'}>
                      {r.result}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="h-px bg-[#00ff87]/10" />
    </div>
  );
}
