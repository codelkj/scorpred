/* ─────────────────────────────────────────────────────────────────────────────
   NBAPage — Tonight's NBA games with predictions.
   Structure: page header → kpi-grid → grid-2 of game cards
   ───────────────────────────────────────────────────────────────────────────── */

interface Game {
  home: string;
  away: string;
  time: string;
  homeWin: number;
  awayWin: number;
  confidence: 'HIGH' | 'MEDIUM' | 'LOW';
  edge: string | null;
  pick: 'Home Win' | 'Away Win';
  spread: string;
  ou: string;
}

const GAMES: Game[] = [
  {
    home: 'Lakers', away: 'Celtics',
    time: '19:30 ET', homeWin: 46, awayWin: 54,
    confidence: 'MEDIUM', edge: '+1.4pp', pick: 'Away Win',
    spread: 'CEL -2.5', ou: 'O 223.5',
  },
  {
    home: 'Warriors', away: 'Nuggets',
    time: '22:00 ET', homeWin: 54, awayWin: 46,
    confidence: 'HIGH', edge: '+3.1pp', pick: 'Home Win',
    spread: 'GSW -1', ou: 'U 221',
  },
  {
    home: 'Bucks', away: 'Heat',
    time: '20:30 ET', homeWin: 61, awayWin: 39,
    confidence: 'HIGH', edge: '+4.7pp', pick: 'Home Win',
    spread: 'MIL -3.5', ou: 'O 218',
  },
  {
    home: 'Suns', away: 'Clippers',
    time: '22:00 ET', homeWin: 49, awayWin: 51,
    confidence: 'LOW', edge: null, pick: 'Away Win',
    spread: 'LAC -1', ou: 'U 226',
  },
  {
    home: 'Knicks', away: 'Nets',
    time: '19:30 ET', homeWin: 67, awayWin: 33,
    confidence: 'HIGH', edge: '+5.3pp', pick: 'Home Win',
    spread: 'NYK -5', ou: 'O 214.5',
  },
  {
    home: 'Spurs', away: 'Rockets',
    time: '21:00 ET', homeWin: 38, awayWin: 62,
    confidence: 'MEDIUM', edge: '+2.1pp', pick: 'Away Win',
    spread: 'HOU -4.5', ou: 'U 229',
  },
];

const CONF_COLOR: Record<Game['confidence'], string> = {
  HIGH: '#00ff87',
  MEDIUM: '#00d4ff',
  LOW: '#f59e0b',
};

function GameCard({ g }: { g: Game }) {
  const accent = CONF_COLOR[g.confidence];
  const pickHome = g.pick === 'Home Win';

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span>🏀</span>
          <span className="text-[10px] tracking-[0.2em] uppercase font-mono text-neutral-500">
            NBA · {g.time}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {g.edge && (
            <span
              className="text-[9px] tracking-[0.2em] uppercase font-mono px-2 py-0.5 border"
              style={{ color: accent, borderColor: `${accent}33` }}
            >
              {g.edge}
            </span>
          )}
          <span
            className="text-[9px] tracking-[0.2em] uppercase font-mono px-2 py-0.5 border"
            style={{ color: accent, borderColor: `${accent}33` }}
          >
            {g.confidence}
          </span>
        </div>
      </div>

      {/* Teams + prob */}
      <div className="flex items-center justify-between mb-4">
        <div className="text-center flex-1">
          <p className={`text-sm font-bold font-oswald tracking-wide uppercase ${pickHome ? 'text-white' : 'text-neutral-500'}`}>
            {g.home}
          </p>
          <p className={`text-xl font-bold font-oswald mt-1 ${pickHome ? 'text-[#00ff87]' : 'text-neutral-600'}`}>
            {g.homeWin}%
            {pickHome && <span className="text-[9px] ml-1" style={{ color: accent }}>▲</span>}
          </p>
        </div>
        <div className="px-4 text-center">
          <span className="text-[10px] font-mono text-neutral-700 uppercase tracking-widest">vs</span>
        </div>
        <div className="text-center flex-1">
          <p className={`text-sm font-bold font-oswald tracking-wide uppercase ${!pickHome ? 'text-white' : 'text-neutral-500'}`}>
            {g.away}
          </p>
          <p className={`text-xl font-bold font-oswald mt-1 ${!pickHome ? 'text-[#00d4ff]' : 'text-neutral-600'}`}>
            {g.awayWin}%
            {!pickHome && <span className="text-[9px] ml-1" style={{ color: accent }}>▲</span>}
          </p>
        </div>
      </div>

      {/* Probability bar */}
      <div className="h-1.5 bg-white/5 overflow-hidden flex mb-4">
        <div className="h-full bg-[#00ff87]/60 transition-all" style={{ width: `${g.homeWin}%` }} />
        <div className="h-full bg-[#00d4ff]/60 transition-all" style={{ width: `${g.awayWin}%` }} />
      </div>

      {/* Lines */}
      <div className="flex items-center gap-4 pt-2 border-t border-white/5">
        <span className="text-[10px] font-mono text-neutral-600">{g.spread}</span>
        <span className="text-[10px] font-mono text-neutral-600">{g.ou}</span>
        <span className="ml-auto text-[10px] font-mono" style={{ color: accent }}>
          {g.pick}
        </span>
      </div>
    </div>
  );
}

export default function NBAPage() {
  const highConf = GAMES.filter(g => g.confidence === 'HIGH').length;
  const withEdge = GAMES.filter(g => g.edge).length;

  return (
    <div className="page-stack">

      {/* Page header */}
      <div>
        <p className="page-eyebrow">// Tonight's Slate</p>
        <h1 className="page-title">NBA Predictions</h1>
        <div className="mt-4 h-px bg-gradient-to-r from-[#00d4ff]/20 to-transparent" />
      </div>

      {/* KPIs */}
      <div className="kpi-grid">
        {[
          { label: 'Games Tonight', value: GAMES.length.toString(), sub: 'on the slate' },
          { label: 'High Confidence', value: highConf.toString(), sub: 'strong signal' },
          { label: 'With Edge', value: withEdge.toString(), sub: 'vs market' },
          { label: 'Model', value: 'Stack', sub: 'LR + RF + XGB + LGBM' },
        ].map((k) => (
          <div key={k.label} className="card">
            <p className="section-label">{k.label}</p>
            <p className="text-2xl font-bold text-[#00d4ff] font-oswald">{k.value}</p>
            <p className="text-[10px] text-neutral-600 font-mono mt-1">{k.sub}</p>
          </div>
        ))}
      </div>

      {/* Game cards — 2-column grid */}
      <div className="section">
        <p className="section-label">All Games</p>
        <div className="grid-2">
          {GAMES.map((g) => (
            <GameCard key={`${g.home}-${g.away}`} g={g} />
          ))}
        </div>
      </div>

      <div className="h-px bg-[#00d4ff]/10" />
    </div>
  );
}
