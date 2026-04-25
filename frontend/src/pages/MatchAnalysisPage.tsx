import { useFetch } from '../hooks/useFetch';
import { DataBadge, DecisionCard, EmptyState, type Decision, type DataConfidence } from '../components/DecisionCard';

interface SoccerData {
  topOpportunities: Decision[];
  slate: Decision[];
}

interface ContextRow {
  label: string;
  value: string;
}

function AnalysisDetail({ decision }: { decision: Decision }) {
  const [competition, venue] = (decision.support || '').split(' | ');
  const contextRows: ContextRow[] = [
    { label: 'Competition', value: competition || 'Unknown' },
    { label: 'Venue', value: venue || 'TBD' },
    { label: 'Draw risk', value: decision.confidence >= 66 ? 'Low' : decision.confidence >= 55 ? 'Moderate' : 'High' },
    { label: 'Data confidence', value: decision.data },
  ];

  const dataLabel = decision.data as DataConfidence;

  return (
    <div className="analysis-layout">
      <div className="section">
        <DecisionCard decision={decision} featured />
        <section className="card">
          <p className="section-label">Why This Pick</p>
          <ul className="why-list">
            {(decision.reason || 'No analysis available.')
              .split(' | ')
              .filter(Boolean)
              .map((line) => (
                <li key={line}>{line}</li>
              ))}
          </ul>
        </section>
      </div>

      <aside className="card">
        <p className="section-label">Trust Check</p>
        <DataBadge label={dataLabel} />
        <p className="mt-4 text-sm text-slate-500">
          {decision.data === 'Strong Data'
            ? 'Recent form, venue context, and side-level matchup data all support the same direction.'
            : decision.data === 'Partial Data'
            ? 'Enough data to act, but worth confirming lineup news before committing.'
            : 'Limited data available. Treat this pick with extra caution.'}
        </p>
        <div className="mt-5 space-y-3">
          <div>
            <div className="mb-2 flex justify-between text-xs uppercase tracking-[0.12em] text-slate-500">
              <span>Win probability</span>
              <span>{decision.confidence}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-white/[0.06]">
              <div className="h-full rounded-full bg-emerald-300" style={{ width: `${decision.confidence}%` }} />
            </div>
          </div>
          {contextRows.map((item) => (
            <div key={item.label} className="flex justify-between gap-4 border-b border-white/[0.05] pb-3 text-sm">
              <span className="text-slate-500">{item.label}</span>
              <strong className="text-right text-slate-200">{item.value}</strong>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}

export default function MatchAnalysisPage() {
  const { data, loading, error } = useFetch<SoccerData>('/api/dashboard/soccer');

  const decisions = data?.topOpportunities?.length
    ? data.topOpportunities
    : data?.slate ?? [];

  const decision = decisions[0] ?? null;

  const matchup = decision?.matchup || 'Match Analysis';
  const competition = (decision?.support || '').split(' | ')[0] || 'Soccer';

  return (
    <div className="page-stack">
      <section className="hero-card">
        <p className="page-eyebrow">{competition}</p>
        <h1 className="page-title">{matchup}</h1>
        <p className="mt-4 max-w-2xl text-slate-400">
          A focused breakdown that keeps the main decision first and the supporting evidence secondary.
        </p>
      </section>

      {loading ? (
        <div className="empty-state">
          <p className="font-oswald text-lg uppercase tracking-normal text-white">Loading match analysis…</p>
        </div>
      ) : error ? (
        <EmptyState title="Analysis unavailable" body="Could not load match data. The server may still be warming up." />
      ) : decision ? (
        <AnalysisDetail decision={decision} />
      ) : (
        <EmptyState title="No match selected" body="Navigate to Soccer or NBA to find a match, then open Match Analysis." />
      )}
    </div>
  );
}
