import { DashboardCard } from './DashboardTheme';

/* ─────────────────────────────────────────────────────────────────────────────
   StrategyLabSection — Editorial intelligence page.
   Structure: page header → grid-2 (article | pull quote) → grid-3 insight cards
   ───────────────────────────────────────────────────────────────────────────── */

const INSIGHTS = [
  {
    tag: 'NBA',
    tagColor: '#00d4ff',
    title: 'Home-court advantage fading in 2024–25',
    body: 'Road teams covering the spread 53.1% over the last 30 days. Adjust your model priors accordingly.',
  },
  {
    tag: 'SOCCER',
    tagColor: '#00ff87',
    title: 'Draw suppression boosting ROI',
    body: 'Stacking ensemble suppresses draws when base learners show strong directional agreement. +2.4pp edge since deployment.',
  },
  {
    tag: 'ML MODEL',
    tagColor: '#c084fc',
    title: 'XGBoost recalibrated after feature drift',
    body: 'Feature importance shifted: "recent_form_weighted" now top-3. Retrained on 2,400 new samples. CV AUC 0.71.',
  },
];

export default function StrategyLabSection() {
  return (
    <div className="page-stack">

      {/* Page header */}
      <div>
        <p className="page-eyebrow">// Analysis</p>
        <h1 className="page-title font-playfair italic" style={{ fontFamily: "'Playfair Display', serif", textTransform: 'none', fontSize: '2.5rem' }}>
          Strategy Lab
        </h1>
        <div className="mt-4 h-px bg-gradient-to-r from-[#00ff87]/20 to-transparent" />
      </div>

      {/* Article + pull quote */}
      <div className="grid-2">
        {/* Main article */}
        <div className="section-stack">
          <p className="text-neutral-300 leading-[1.85] text-[15px] font-serif">
            <span className="float-left text-5xl font-playfair text-[#00ff87] leading-none mr-3 mt-1">T</span>
            he Strategy Lab is where conviction meets data. Every prediction flows through
            a four-layer pipeline: base model inference, stacking ensemble aggregation,
            rule engine filtering, and prediction policy gating. The result is not just a
            probability — it is a <em className="text-[#00ff87]">calibrated decision</em> backed
            by agreement signals, market edges, and historical validation.
          </p>
          <p className="text-neutral-500 leading-[1.85] text-[15px] font-serif">
            Below you'll find the latest strategic insights distilled from our model
            monitoring dashboards. Each card represents a live observation from the
            prediction tracking system — not retrospective analysis, but forward-looking
            intelligence for your next slate.
          </p>
        </div>

        {/* Pull quote */}
        <div className="flex items-start">
          <blockquote className="border-l-2 border-[#00ff87]/30 pl-6 py-2">
            <p className="text-xl text-neutral-300 italic font-playfair leading-relaxed">
              "Edge isn't found in the model alone — it's in the discipline to trust the
              signal when the crowd disagrees."
            </p>
            <cite className="block mt-4 text-[10px] tracking-[0.2em] text-neutral-600 uppercase font-mono not-italic">
              — ScorPred Strategy Engine
            </cite>
          </blockquote>
        </div>
      </div>

      {/* Insight cards */}
      <div className="section">
        <p className="section-label">Live Intelligence</p>
        <div className="grid-3">
          {INSIGHTS.map((insight) => (
            <DashboardCard key={insight.tag} className="space-y-3">
              <span
                className="inline-block text-[9px] tracking-[0.25em] uppercase font-mono px-2 py-0.5 border"
                style={{ color: insight.tagColor, borderColor: `${insight.tagColor}33` }}
              >
                {insight.tag}
              </span>
              <h3 className="text-sm font-bold text-white leading-snug font-playfair">
                {insight.title}
              </h3>
              <p className="text-xs text-neutral-500 leading-relaxed font-serif">
                {insight.body}
              </p>
            </DashboardCard>
          ))}
        </div>
      </div>

      <div className="h-px bg-[#00ff87]/10" />
    </div>
  );
}
