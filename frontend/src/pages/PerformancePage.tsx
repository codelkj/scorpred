/* ─────────────────────────────────────────────────────────────────────────────
   PerformancePage — Model accuracy, ROI, calibration, and prediction log.
   Structure: page header → kpi-grid → grid-2 (accuracy | calibration) →
              grid-3 (model cards) → section (prediction log)
   ───────────────────────────────────────────────────────────────────────────── */

const MODELS = [
  { name: 'Random Forest', accuracy: 64.2, precision: 0.67, recall: 0.61, auc: 0.71, status: 'LIVE' },
  { name: 'XGBoost', accuracy: 65.8, precision: 0.69, recall: 0.63, auc: 0.73, status: 'LIVE' },
  { name: 'LightGBM', accuracy: 66.1, precision: 0.70, recall: 0.64, auc: 0.74, status: 'LIVE' },
  { name: 'Stacking Ensemble', accuracy: 67.2, precision: 0.71, recall: 0.66, auc: 0.76, status: 'LIVE' },
];

const ACCURACY_BY_LEAGUE = [
  { league: 'Premier League', accuracy: 69.1, n: 44 },
  { league: 'La Liga', accuracy: 67.8, n: 38 },
  { league: 'Bundesliga', accuracy: 65.4, n: 31 },
  { league: 'Serie A', accuracy: 63.9, n: 29 },
  { league: 'Ligue 1', accuracy: 66.2, n: 27 },
  { league: 'NBA', accuracy: 61.4, n: 38 },
];

const CALIBRATION = [
  { bucket: '50–60%', predicted: 55, actual: 53 },
  { bucket: '60–70%', predicted: 65, actual: 63 },
  { bucket: '70–80%', predicted: 75, actual: 71 },
  { bucket: '80–90%', predicted: 85, actual: 79 },
  { bucket: '90%+', predicted: 93, actual: 86 },
];

const RECENT_PREDS = [
  { date: '04-15', match: 'Liverpool vs Chelsea', pick: 'Home Win', prob: 71, result: 'WIN' },
  { date: '04-15', match: 'Knicks vs Nets', pick: 'Home Win', prob: 67, result: 'WIN' },
  { date: '04-14', match: 'PSG vs Lyon', pick: 'Home Win', prob: 78, result: 'WIN' },
  { date: '04-14', match: 'Spurs vs Villa', pick: 'Draw', prob: 38, result: 'LOSS' },
  { date: '04-13', match: 'Heat vs Bulls', pick: 'Home Win', prob: 59, result: 'WIN' },
  { date: '04-13', match: 'Dortmund vs Leverkusen', pick: 'Away Win', prob: 52, result: 'WIN' },
  { date: '04-12', match: 'Barcelona vs Atletico', pick: 'Home Win', prob: 61, result: 'LOSS' },
  { date: '04-12', match: 'Celtics vs Pacers', pick: 'Away Win', prob: 58, result: 'WIN' },
];

export default function PerformancePage() {
  const wins = RECENT_PREDS.filter(p => p.result === 'WIN').length;

  return (
    <div className="page-stack">

      {/* Page header */}
      <div>
        <p className="page-eyebrow">// Model Evaluation</p>
        <h1 className="page-title">Performance</h1>
        <div className="mt-4 h-px bg-gradient-to-r from-[#00ff87]/20 to-transparent" />
      </div>

      {/* KPI row */}
      <div className="kpi-grid">
        {[
          { label: 'Overall Accuracy', value: '67.2%', sub: 'last 207 predictions', color: '#00ff87' },
          { label: 'ROI (Kelly)', value: '+8.4%', sub: 'on tracked bets', color: '#00ff87' },
          { label: 'Predictions', value: '207', sub: 'tracked total', color: '#00d4ff' },
          { label: 'Recent (8)', value: `${wins}/8`, sub: 'last 8 predictions', color: wins >= 6 ? '#00ff87' : '#f59e0b' },
        ].map((k) => (
          <div key={k.label} className="card">
            <p className="section-label">{k.label}</p>
            <p className="text-2xl font-bold font-oswald" style={{ color: k.color }}>{k.value}</p>
            <p className="text-[10px] text-neutral-600 font-mono mt-1">{k.sub}</p>
          </div>
        ))}
      </div>

      {/* Accuracy by league + Calibration */}
      <div className="grid-2">

        {/* Accuracy by league */}
        <div className="section">
          <p className="section-label">Accuracy by League / Sport</p>
          <div className="card">
            <div className="space-y-3">
              {ACCURACY_BY_LEAGUE.map((l) => (
                <div key={l.league}>
                  <div className="flex justify-between text-[11px] font-mono mb-1">
                    <span className="text-neutral-400">{l.league}</span>
                    <div className="flex gap-3">
                      <span className="text-neutral-600">n={l.n}</span>
                      <span className={l.accuracy >= 66 ? 'text-[#00ff87]' : 'text-neutral-300'}>
                        {l.accuracy}%
                      </span>
                    </div>
                  </div>
                  <div className="h-1 bg-white/5 overflow-hidden">
                    <div
                      className="h-full"
                      style={{
                        width: `${l.accuracy}%`,
                        backgroundColor: l.accuracy >= 66 ? '#00ff87' : '#00d4ff',
                        opacity: 0.7,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Calibration */}
        <div className="section">
          <p className="section-label">Confidence Calibration</p>
          <div className="card">
            <div className="space-y-3">
              {CALIBRATION.map((c) => (
                <div key={c.bucket}>
                  <div className="flex justify-between text-[11px] font-mono mb-1">
                    <span className="text-neutral-500">{c.bucket}</span>
                    <div className="flex gap-4">
                      <span className="text-neutral-600">pred {c.predicted}%</span>
                      <span className={Math.abs(c.predicted - c.actual) <= 4 ? 'text-[#00ff87]' : 'text-[#f59e0b]'}>
                        actual {c.actual}%
                      </span>
                    </div>
                  </div>
                  <div className="h-1 bg-white/5 overflow-hidden relative">
                    <div className="h-full bg-neutral-700/40" style={{ width: `${c.predicted}%` }} />
                    <div
                      className="h-full absolute top-0 left-0"
                      style={{ width: `${c.actual}%`, backgroundColor: '#00ff87', opacity: 0.6 }}
                    />
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[10px] font-mono text-neutral-700 mt-4 pt-3 border-t border-white/5">
              green = actual · grey = predicted
            </p>
          </div>
        </div>
      </div>

      {/* Model cards */}
      <div className="section">
        <p className="section-label">Individual Models</p>
        <div className="grid-3">
          {MODELS.map((m) => (
            <div key={m.name} className="card">
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs font-bold font-oswald tracking-wider uppercase text-white">{m.name}</p>
                <span className="text-[9px] tracking-[0.2em] uppercase font-mono text-[#00ff87] border border-[#00ff87]/20 px-1.5 py-0.5">
                  {m.status}
                </span>
              </div>
              <div className="space-y-2">
                {[
                  { label: 'Accuracy', value: `${m.accuracy}%` },
                  { label: 'Precision', value: m.precision.toFixed(2) },
                  { label: 'Recall', value: m.recall.toFixed(2) },
                  { label: 'AUC', value: m.auc.toFixed(2) },
                ].map((s) => (
                  <div key={s.label} className="flex justify-between text-[11px] font-mono">
                    <span className="text-neutral-600">{s.label}</span>
                    <span className="text-neutral-300">{s.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Prediction log */}
      <div className="section">
        <p className="section-label">Recent Predictions</p>
        <div className="card overflow-x-auto">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-white/5 text-neutral-600 uppercase tracking-wider">
                <th className="text-left pb-3 pr-4 font-normal">Date</th>
                <th className="text-left pb-3 pr-4 font-normal">Match</th>
                <th className="text-left pb-3 pr-4 font-normal">Pick</th>
                <th className="text-right pb-3 pr-4 font-normal">Prob</th>
                <th className="text-right pb-3 font-normal">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {RECENT_PREDS.map((r) => (
                <tr key={`${r.date}-${r.match}`}>
                  <td className="py-2.5 pr-4 text-neutral-600">{r.date}</td>
                  <td className="py-2.5 pr-4 text-neutral-300">{r.match}</td>
                  <td className="py-2.5 pr-4 text-neutral-500">{r.pick}</td>
                  <td className="py-2.5 pr-4 text-right text-neutral-400">{r.prob}%</td>
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
