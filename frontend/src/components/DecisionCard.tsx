export type StrengthTier = 'Best Bet' | 'Strong Lean' | 'Lean' | 'Risky' | 'No Pick';
export type DataConfidence = 'Strong Data' | 'Partial Data' | 'Limited Data';

export interface Decision {
  tier: StrengthTier;
  side: string;
  confidence: number;
  reason: string;
  data: DataConfidence;
  support?: string;
  cta?: string;
}

const TIER_STYLES: Record<StrengthTier, string> = {
  'Best Bet': 'text-emerald-300 border-emerald-400/25 bg-emerald-400/10',
  'Strong Lean': 'text-emerald-200 border-emerald-400/20 bg-emerald-400/10',
  Lean: 'text-amber-300 border-amber-400/25 bg-amber-400/10',
  Risky: 'text-slate-300 border-slate-500/30 bg-slate-500/10',
  'No Pick': 'text-slate-500 border-slate-500/20 bg-slate-500/5',
};

const BAR_STYLES: Record<StrengthTier, string> = {
  'Best Bet': 'bg-emerald-300',
  'Strong Lean': 'bg-emerald-200',
  Lean: 'bg-amber-300',
  Risky: 'bg-slate-500',
  'No Pick': 'bg-slate-700',
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
  return (
    <article className={`card decision-card ${featured ? 'decision-card-featured' : ''}`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-bold tracking-[0.16em] ${TIER_STYLES[decision.tier]}`}>
            {decision.tier}
          </span>
          <h2 className="mt-4 font-oswald text-3xl uppercase tracking-[0.08em] text-white">
            {decision.tier} - {decision.side}
          </h2>
        </div>
        <DataBadge label={decision.data} />
      </div>

      <div className="mt-5">
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="text-slate-500">Confidence</span>
          <strong className="text-white">{decision.confidence}%</strong>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-white/[0.06]">
          <div className={`h-full rounded-full ${BAR_STYLES[decision.tier]}`} style={{ width: `${decision.confidence}%` }} />
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
  bestBet,
  strongLean,
  lean,
  risky,
}: {
  bestBet: number;
  strongLean: number;
  lean: number;
  risky: number;
}) {
  return (
    <section className="plan-strip">
      <div>
        <p className="section-label">Today's Plan</p>
        <h2 className="font-oswald text-xl uppercase tracking-[0.08em] text-white">Every playable matchup gets a tier.</h2>
      </div>
      <div className="plan-pills">
        <span><strong>{bestBet}</strong> Best Bet</span>
        <span><strong>{strongLean}</strong> Strong Lean</span>
        <span><strong>{lean}</strong> Lean</span>
        <span><strong>{risky}</strong> Risky</span>
      </div>
    </section>
  );
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty-state">
      <p className="font-oswald text-lg uppercase tracking-[0.08em] text-white">{title}</p>
      <p className="mt-2 text-sm text-slate-500">{body}</p>
    </div>
  );
}
