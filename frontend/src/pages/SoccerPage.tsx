/* ─────────────────────────────────────────────────────────────────────────────
   SoccerPage — Today's fixtures with ML predictions.
   Structure: page header → kpi-grid → section-stack of full-width fixture cards
   ───────────────────────────────────────────────────────────────────────────── */

interface Fixture {
  league: string;
  home: string;
  away: string;
  kickoff: string;
  homeWin: number;
  draw: number;
  awayWin: number;
  confidence: 'HIGH' | 'MEDIUM' | 'LOW';
  edge: string | null;
  pick: 'Home Win' | 'Draw' | 'Away Win';
}

const FIXTURES: Fixture[] = [
  {
    league: 'Premier League',
    home: 'Man City', away: 'Arsenal',
    kickoff: '15:00 UTC',
    homeWin: 58, draw: 22, awayWin: 20,
    confidence: 'HIGH', edge: '+3.8pp', pick: 'Home Win',
  },
  {
    league: 'La Liga',
    home: 'Barcelona', away: 'Real Madrid',
    kickoff: '20:00 UTC',
    homeWin: 44, draw: 26, awayWin: 30,
    confidence: 'MEDIUM', edge: '+1.2pp', pick: 'Home Win',
  },
  {
    league: 'Bundesliga',
    home: 'Bayern München', away: 'Borussia Dortmund',
    kickoff: '17:30 UTC',
    homeWin: 62, draw: 19, awayWin: 19,
    confidence: 'HIGH', edge: '+4.1pp', pick: 'Home Win',
  },
  {
    league: 'Serie A',
    home: 'Inter Milan', away: 'AC Milan',
    kickoff: '19:45 UTC',
    homeWin: 48, draw: 27, awayWin: 25,
    confidence: 'MEDIUM', edge: null, pick: 'Home Win',
  },
  {
    league: 'Ligue 1',
    home: 'PSG', away: 'Marseille',
    kickoff: '20:45 UTC',
    homeWin: 71, draw: 16, awayWin: 13,
    confidence: 'HIGH', edge: '+5.2pp', pick: 'Home Win',
  },
];

const CONF_COLOR: Record<Fixture['confidence'], string> = {
  HIGH: '#00ff87',
  MEDIUM: '#00d4ff',
  LOW: '#f59e0b',
};

function FixtureCard({ f }: { f: Fixture }) {
  const accent = CONF_COLOR[f.confidence];
  const rows = [
    { label: f.home, pct: f.homeWin, isPick: f.pick === 'Home Win', barColor: '#00ff87' },
    { label: 'Draw', pct: f.draw, isPick: f.pick === 'Draw', barColor: '#6b7280' },
    { label: f.away, pct: f.awayWin, isPick: f.pick === 'Away Win', barColor: '#00d4ff' },
  ];

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span>⚽</span>
          <span className="text-[10px] tracking-[0.2em] uppercase font-mono text-neutral-500">
            {f.league}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {f.edge && (
            <span
              className="text-[9px] tracking-[0.2em] uppercase font-mono px-2 py-0.5 border"
              style={{ color: accent, borderColor: `${accent}33` }}
            >
              EDGE {f.edge}
            </span>
          )}
          <span
            className="text-[9px] tracking-[0.2em] uppercase font-mono px-2 py-0.5 border"
            style={{ color: accent, borderColor: `${accent}33` }}
          >
            {f.confidence}
          </span>
          <span className="text-[10px] text-neutral-600 font-mono">{f.kickoff}</span>
        </div>
      </div>

      {/* Teams */}
      <div className="flex items-center gap-3 mb-5">
        <span className="text-base font-bold tracking-wide uppercase text-white font-oswald">
          {f.home}
        </span>
        <span className="text-neutral-600 text-xs font-mono">vs</span>
        <span className="text-base font-bold tracking-wide uppercase text-white font-oswald">
          {f.away}
        </span>
      </div>

      {/* Probability bars */}
      <div className="space-y-2">
        {rows.map(({ label, pct, isPick, barColor }) => (
          <div key={label}>
            <div className="flex justify-between text-[11px] font-mono uppercase tracking-wider mb-1">
              <span className={isPick ? 'text-white font-bold' : 'text-neutral-600'}>
                {label}
                {isPick && (
                  <span className="ml-2 text-[9px]" style={{ color: accent }}>▲ PICK</span>
                )}
              </span>
              <span
                className={isPick ? 'font-bold' : 'text-neutral-600'}
                style={isPick ? { color: accent } : undefined}
              >
                {pct}%
              </span>
            </div>
            <div className="h-1 bg-white/5 overflow-hidden">
              <div
                className="h-full transition-all duration-500"
                style={{ width: `${pct}%`, backgroundColor: barColor, opacity: isPick ? 1 : 0.35 }}
              />
            </div>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="mt-4 pt-3 border-t border-white/5 flex items-center gap-2">
        {['ML', 'RULES', 'ELO'].map((t) => (
          <span key={t} className="text-[9px] tracking-widest font-mono text-neutral-700 border border-white/10 px-2 py-0.5">
            {t}
          </span>
        ))}
        <span className="ml-auto text-[10px] text-neutral-700 font-mono">Stacking Ensemble</span>
      </div>
    </div>
  );
}

export default function SoccerPage() {
  const highConf = FIXTURES.filter(f => f.confidence === 'HIGH').length;
  const withEdge = FIXTURES.filter(f => f.edge).length;

  return (
    <div className="page-stack">

      {/* Page header */}
      <div>
        <p className="page-eyebrow">// Today's Fixtures</p>
        <h1 className="page-title">Soccer Predictions</h1>
        <div className="mt-4 h-px bg-gradient-to-r from-[#00ff87]/20 to-transparent" />
      </div>

      {/* KPI row */}
      <div className="kpi-grid">
        {[
          { label: 'Fixtures', value: FIXTURES.length.toString(), sub: 'today' },
          { label: 'High Confidence', value: highConf.toString(), sub: 'strong signal' },
          { label: 'With Edge', value: withEdge.toString(), sub: 'vs market' },
          { label: 'Avg Confidence', value: '74%', sub: 'across picks' },
        ].map((k) => (
          <div key={k.label} className="card">
            <p className="section-label">{k.label}</p>
            <p className="text-2xl font-bold text-[#00ff87] font-oswald">{k.value}</p>
            <p className="text-[10px] text-neutral-600 font-mono mt-1">{k.sub}</p>
          </div>
        ))}
      </div>

      {/* Fixture cards — full-width stack */}
      <div className="section-stack">
        <p className="section-label">All Fixtures</p>
        {FIXTURES.map((f) => (
          <FixtureCard key={`${f.home}-${f.away}`} f={f} />
        ))}
      </div>

      <div className="h-px bg-[#00ff87]/10" />
    </div>
  );
}
