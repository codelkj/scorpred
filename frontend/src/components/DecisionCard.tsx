export type DecisionAction = 'BET' | 'CONSIDER' | 'SKIP';
export type DataConfidence = 'Strong Data' | 'Partial Data' | 'Limited Data';

export interface Decision {
  action: DecisionAction;
  side: string;
  matchup?: string;
  confidence: number;
  reason: string;
  data: DataConfidence;
  support?: string;
  cta?: string;
  logo?: string;
  leagueLogo?: string;
}

const ACTION_STYLES: Record<DecisionAction, string> = {
  BET: 'text-emerald-300 border-emerald-400/25 bg-emerald-400/10',
  CONSIDER: 'text-amber-300 border-amber-400/25 bg-amber-400/10',
  SKIP: 'text-slate-300 border-slate-500/30 bg-slate-500/10',
};

const BAR_STYLES: Record<DecisionAction, string> = {
  BET: 'bg-emerald-300',
  CONSIDER: 'bg-amber-300',
  SKIP: 'bg-slate-500',
};

const DATA_STYLES: Record<DataConfidence, string> = {
  'Strong Data': 'text-emerald-200 border-emerald-400/25 bg-emerald-400/10',
  'Partial Data': 'text-amber-200 border-amber-400/25 bg-amber-400/10',
  'Limited Data': 'text-rose-200 border-rose-400/20 bg-rose-400/10',
};

export function DataBadge({ label }: { label: DataConfidence }) {
  return (
    <span className={`inline-flex rounded-full border px-3 py-1 text-[11px] font-semibold ${DATA_STYLES[label]}`}>
      {label}
    </span>
  );
}

export function DecisionCard({ decision, featured = false }: { decision: Decision; featured?: boolean }) {
  const initials = decision.side
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('') || 'TM';

  return (
    <article className={`card decision-card ${featured ? 'decision-card-featured' : ''}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          {decision.logo ? (
            <img
              src={decision.logo}
              alt={`${decision.side} logo`}
              className="h-10 w-10 rounded-lg border border-white/[0.1] bg-white object-contain p-1"
              onError={(event) => { event.currentTarget.style.display = 'none'; }}
            />
          ) : (
            <span className="grid h-10 w-10 place-items-center rounded-lg border border-white/[0.1] bg-white/[0.05] font-oswald text-sm text-white">
              {initials}
            </span>
          )}
          <div>
            <p className="text-xs uppercase tracking-[0.14em] text-slate-500">{decision.matchup || 'Matchup'}</p>
            <h2 className="mt-2 font-oswald text-3xl uppercase tracking-normal text-white">
              {decision.action} - {decision.side}
            </h2>
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          {decision.leagueLogo && (
            <img
              src={decision.leagueLogo}
              alt=""
              className="h-7 w-7 rounded-md border border-white/[0.1] bg-white object-contain p-1"
              onError={(event) => { event.currentTarget.style.display = 'none'; }}
            />
          )}
          <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-bold ${ACTION_STYLES[decision.action]}`}>
            {decision.action}
          </span>
          <DataBadge label={decision.data} />
        </div>
      </div>

      <div className="mt-5">
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="text-slate-500">Confidence</span>
          <strong className="text-white">{decision.confidence}%</strong>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-white/[0.06]">
          <div className={`h-full rounded-full ${BAR_STYLES[decision.action]}`} style={{ width: `${decision.confidence}%` }} />
        </div>
      </div>

      <p className="mt-5 text-base text-slate-200">{decision.reason}</p>
      {decision.support && <p className="mt-2 text-sm text-slate-500">{decision.support}</p>}
      {decision.cta && (
        <button type="button" className="mt-5 rounded-lg border border-white/[0.1] px-4 py-2 text-sm text-slate-200 transition hover:border-emerald-400/30 hover:text-emerald-200">
          {decision.cta}
        </button>
      )}
    </article>
  );
}

export function PlanStrip({
  bet,
  consider,
  skip,
}: {
  bet: number;
  consider: number;
  skip: number;
}) {
  return (
    <section className="plan-strip">
      <div>
        <p className="section-label">Today's Plan</p>
        <h2 className="font-oswald text-xl uppercase tracking-normal text-white">Every normal matchup gets a side and action.</h2>
      </div>
      <div className="plan-pills">
        <span><strong>{bet}</strong> BET</span>
        <span><strong>{consider}</strong> CONSIDER</span>
        <span><strong>{skip}</strong> SKIP</span>
      </div>
    </section>
  );
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty-state">
      <p className="font-oswald text-lg uppercase tracking-normal text-white">{title}</p>
      <p className="mt-2 text-sm text-slate-500">{body}</p>
    </div>
  );
}
