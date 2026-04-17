/* ─────────────────────────────────────────────────────────────────────────────
   MatchAnalysisPage — Deep-dive on a featured match.
   Structure: page header → hero match card → grid-2 (stats | model) → H2H
   ───────────────────────────────────────────────────────────────────────────── */

const MATCH = {
  league: 'Premier League',
  home: 'Man City',
  away: 'Arsenal',
  kickoff: 'Today 15:00 UTC',
  homeWin: 58,
  draw: 22,
  awayWin: 20,
  pick: 'Home Win',
  edge: '+3.8pp',
  confidence: 'HIGH',
};

const HOME_STATS = [
  { label: 'Form (last 5)', value: 'W W W D W', highlight: true },
  { label: 'Goals scored', value: '2.4 / game' },
  { label: 'Goals conceded', value: '0.8 / game' },
  { label: 'xG for', value: '2.61' },
  { label: 'xG against', value: '0.92' },
  { label: 'Clean sheets', value: '3 of 5' },
];

const AWAY_STATS = [
  { label: 'Form (last 5)', value: 'W W D W L', highlight: false },
  { label: 'Goals scored', value: '1.8 / game' },
  { label: 'Goals conceded', value: '1.1 / game' },
  { label: 'xG for', value: '1.94' },
  { label: 'xG against', value: '1.21' },
  { label: 'Clean sheets', value: '1 of 5' },
];

const MODEL_BREAKDOWN = [
  { model: 'Random Forest', homeProb: 61, awayProb: 19, drawProb: 20 },
  { model: 'XGBoost', homeProb: 57, awayProb: 21, drawProb: 22 },
  { model: 'LightGBM', homeProb: 59, awayProb: 20, drawProb: 21 },
  { model: 'Stacking Ensemble', homeProb: 58, awayProb: 20, drawProb: 22 },
];

const H2H = [
  { date: '2024-11-03', home: 'Man City', away: 'Arsenal', score: '2–1', winner: 'H' },
  { date: '2024-04-14', home: 'Arsenal', away: 'Man City', score: '0–0', winner: 'D' },
  { date: '2023-10-08', home: 'Man City', away: 'Arsenal', score: '3–1', winner: 'H' },
  { date: '2023-02-15', home: 'Arsenal', away: 'Man City', score: '1–3', winner: 'A' },
  { date: '2022-08-13', home: 'Man City', away: 'Arsenal', score: '0–2', winner: 'A' },
];

export default function MatchAnalysisPage() {
  return (
    <div className="page-stack">

      {/* Page header */}
      <div>
        <p className="page-eyebrow">// Match Intelligence</p>
        <h1 className="page-title">Match Analysis</h1>
        <div className="mt-4 h-px bg-gradient-to-r from-[#00ff87]/20 to-transparent" />
      </div>

      {/* Hero match card */}
      <div className="hero-card">
        <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
          <div>
            <p className="text-[10px] tracking-[0.25em] uppercase font-mono text-neutral-500 mb-1">
              {MATCH.league} · {MATCH.kickoff}
            </p>
            <h2 className="text-3xl font-oswald tracking-[0.08em] uppercase text-white">
              {MATCH.home}
              <span className="text-neutral-600 text-xl mx-4 font-normal">vs</span>
              {MATCH.away}
            </h2>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-[10px] tracking-[0.2em] uppercase font-mono text-[#00ff87] border border-[#00ff87]/20 px-3 py-1.5">
              EDGE {MATCH.edge}
            </span>
            <span className="text-[10px] tracking-[0.2em] uppercase font-mono text-[#00ff87] border border-[#00ff87]/20 px-3 py-1.5">
              HIGH CONF
            </span>
          </div>
        </div>

        {/* Three-way probabilities */}
        <div className="grid-3">
          {[
            { label: MATCH.home, pct: MATCH.homeWin, color: '#00ff87', isPick: true },
            { label: 'Draw', pct: MATCH.draw, color: '#6b7280', isPick: false },
            { label: MATCH.away, pct: MATCH.awayWin, color: '#00d4ff', isPick: false },
          ].map(({ label, pct, color, isPick }) => (
            <div key={label} className="text-center">
              <p className="text-[10px] tracking-widest uppercase font-mono text-neutral-500 mb-2">{label}</p>
              <p className="text-4xl font-bold font-oswald" style={{ color: isPick ? color : undefined, opacity: isPick ? 1 : 0.5 }}>
                {pct}%
              </p>
              {isPick && (
                <p className="text-[9px] tracking-[0.2em] uppercase font-mono text-[#00ff87] mt-1">▲ PICK</p>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Team stats + Model breakdown */}
      <div className="grid-2">

        {/* Team stats */}
        <div className="section">
          <p className="section-label">Team Statistics</p>
          <div className="card">
            <div className="grid-2" style={{ gap: '16px' }}>
              {/* Home */}
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider text-[#00ff87] font-oswald mb-3">{MATCH.home}</p>
                <div className="space-y-2">
                  {HOME_STATS.map((s) => (
                    <div key={s.label} className="flex justify-between text-[11px] font-mono">
                      <span className="text-neutral-600">{s.label}</span>
                      <span className={s.highlight ? 'text-[#00ff87]' : 'text-neutral-300'}>{s.value}</span>
                    </div>
                  ))}
                </div>
              </div>
              {/* Away */}
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider text-[#00d4ff] font-oswald mb-3">{MATCH.away}</p>
                <div className="space-y-2">
                  {AWAY_STATS.map((s) => (
                    <div key={s.label} className="flex justify-between text-[11px] font-mono">
                      <span className="text-neutral-600">{s.label}</span>
                      <span className="text-neutral-300">{s.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Model breakdown */}
        <div className="section">
          <p className="section-label">Model Breakdown</p>
          <div className="card">
            <div className="space-y-4">
              {MODEL_BREAKDOWN.map((m) => (
                <div key={m.model}>
                  <p className="text-[10px] font-mono tracking-[0.15em] uppercase text-neutral-500 mb-2">{m.model}</p>
                  <div className="flex items-center gap-3 text-[11px] font-mono">
                    <span className="text-[#00ff87] w-8 text-right">{m.homeProb}%</span>
                    <div className="flex-1 h-1.5 bg-white/5 overflow-hidden flex">
                      <div className="h-full bg-[#00ff87]/70" style={{ width: `${m.homeProb}%` }} />
                      <div className="h-full bg-[#6b7280]/40" style={{ width: `${m.drawProb}%` }} />
                      <div className="h-full bg-[#00d4ff]/70" style={{ width: `${m.awayProb}%` }} />
                    </div>
                    <span className="text-[#00d4ff] w-8">{m.awayProb}%</span>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 pt-3 border-t border-white/5 flex gap-4 text-[10px] font-mono text-neutral-600">
              <span className="flex items-center gap-1"><span className="w-2 h-2 bg-[#00ff87]/70 inline-block" /> Home</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 bg-[#6b7280]/40 inline-block" /> Draw</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 bg-[#00d4ff]/70 inline-block" /> Away</span>
            </div>
          </div>
        </div>
      </div>

      {/* Head-to-head */}
      <div className="section">
        <p className="section-label">Head-to-Head (last 5)</p>
        <div className="card overflow-x-auto">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-white/5 text-neutral-600 uppercase tracking-wider">
                <th className="text-left pb-3 pr-4 font-normal">Date</th>
                <th className="text-left pb-3 pr-4 font-normal">Home</th>
                <th className="text-left pb-3 pr-4 font-normal">Away</th>
                <th className="text-center pb-3 pr-4 font-normal">Score</th>
                <th className="text-right pb-3 font-normal">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {H2H.map((r) => (
                <tr key={r.date}>
                  <td className="py-2.5 pr-4 text-neutral-600">{r.date}</td>
                  <td className="py-2.5 pr-4 text-neutral-400">{r.home}</td>
                  <td className="py-2.5 pr-4 text-neutral-400">{r.away}</td>
                  <td className="py-2.5 pr-4 text-center text-white font-bold">{r.score}</td>
                  <td className="py-2.5 text-right">
                    <span className={
                      r.winner === 'H' ? 'text-[#00ff87]'
                      : r.winner === 'D' ? 'text-neutral-500'
                      : 'text-[#00d4ff]'
                    }>
                      {r.winner === 'H' ? 'Home' : r.winner === 'D' ? 'Draw' : 'Away'}
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
