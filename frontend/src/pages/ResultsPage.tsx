import { useEffect, useState } from 'react';

function statusClass(status: string) {
  if (status === 'correct') return 'text-emerald-300';
  if (status === 'incorrect') return 'text-rose-300';
  return 'text-amber-300';
}

type LiveResult = {
  date: string;
  competition: string;
  matchup: string;
  final_score: string;
  action_label: string;
  recommended_side: string;
  result: string;
  result_label: string;
  confidence_pct: number;
  team_a_logo?: string;
  team_b_logo?: string;
};

type LivePayload = {
  recent_nba?: LiveResult[];
  recent_soccer?: LiveResult[];
  summary?: {
    total_graded?: number;
    win_rate?: number;
    recent_win_rate?: number;
    correct?: number;
    incorrect?: number;
    pushes?: number;
  };
};

function ResultTable({ title, rows }: { title: string; rows: LiveResult[] }) {
  return (
    <section className="section">
      <p className="section-label">{title}</p>
      <div className="overflow-x-auto">
        <table className="results-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Competition</th>
              <th>Match</th>
              <th>Final</th>
              <th>Action</th>
              <th>Side</th>
              <th>Confidence</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${row.date}-${row.matchup}-${index}`}>
                <td>{row.date}</td>
                <td>{row.competition}</td>
                <td className="text-slate-200">{row.matchup}</td>
                <td>{row.final_score}</td>
                <td>{row.action_label}</td>
                <td>{row.recommended_side}</td>
                <td>{row.confidence_pct}%</td>
                <td className={statusClass(row.result)}>{row.result_label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function ResultsPage() {
  const [payload, setPayload] = useState<LivePayload>({});

  useEffect(() => {
    fetch('/api/results/live')
      .then((response) => response.json())
      .then((data) => setPayload(data))
      .catch(() => setPayload({}));
  }, []);

  const summary = payload.summary || {};
  const nba = payload.recent_nba || [];
  const soccer = payload.recent_soccer || [];

  return (
    <div className="page-stack">
      <section className="hero-card">
        <p className="page-eyebrow">Results</p>
        <h1 className="page-title">Live Recent Results</h1>
        <p className="mt-4 max-w-2xl text-slate-400">
          Transparent tracking for every action, side, confidence score, and final outcome.
        </p>
      </section>

      <section className="kpi-grid">
        <article className="card"><p className="section-label">Total graded</p><strong className="font-oswald text-3xl text-white">{summary.total_graded || 0}</strong></article>
        <article className="card"><p className="section-label">Win rate</p><strong className="font-oswald text-3xl text-white">{summary.win_rate || 0}%</strong></article>
        <article className="card"><p className="section-label">Recent win rate</p><strong className="font-oswald text-3xl text-white">{summary.recent_win_rate || 0}%</strong></article>
        <article className="card"><p className="section-label">Correct / Incorrect</p><strong className="font-oswald text-3xl text-white">{summary.correct || 0} / {summary.incorrect || 0}</strong></article>
      </section>

      <ResultTable title="NBA (Last 10)" rows={nba} />
      <ResultTable title="Soccer (Last 50)" rows={soccer} />
    </div>
  );
}
