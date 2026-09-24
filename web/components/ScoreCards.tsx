// web/components/ScoreCards.tsx
//
// What the /models hover cards say. Four cards, one visual language:
//   ScoreBreakdownCard — a table Score, taken apart into parts that add up to
//                        the printed figure (lib/benchmark-grid scoreBreakdown)
//   IndexCard          — a table AA Index: the figure, its source, and whether
//                        anything in the catalog beats it (the frontier)
//   ModelPointCard     — a chart dot: the model, its Score, AA Index and prices
//   PriceLineCard      — a chart's fitted line: the equation, what each term
//                        means, and the expected index at the pointer
// Every card that shows a Score also shows FrontierStatus, because the Score
// only compares a model with its own cost tier.
// Figures come from the same ScoreFit the table and charts use, so a card can
// never disagree with the cell or the dot it explains.
import type { ReactNode } from "react";

import {
  blendedPrice,
  formatScore,
  formatUsd,
  scoreBreakdown,
  type ScoreFit,
} from "@/lib/benchmark-grid";
import { COST_TIER_DEFS, COST_TIER_DOT, type CostTier, type ModelRow } from "@/lib/catalog-fields";

const MUTED = "text-brand-slate-500 dark:text-brand-slate-400";
const STRONG = "text-brand-slate-900 dark:text-brand-slate-50";
const RULE = "border-brand-slate-200 dark:border-brand-slate-600";

// A price in a card: always two decimals, so "$8.00" lines up with "$6.65".
const usd = (v: number) => `$${v.toFixed(2)}`;

// One decimal, typographic minus, no sign for positives: "57.6", "−5.2".
function num(v: number): string {
  const r = Math.round(v * 10) / 10;
  return (r < 0 ? "−" : "") + Math.abs(r).toFixed(1);
}

// The table's colour rule for a Score: clearly above the line reads green,
// clearly below reads orange, inside the tie band stays neutral.
export function scoreToneClass(score: number, sigma: number): string {
  if (score >= sigma) return "text-emerald-700 dark:text-emerald-300";
  if (score <= -sigma) return "text-orange-700 dark:text-orange-300";
  return STRONG;
}

function CardHeader({ name, tier }: { name: string; tier: CostTier }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <p className={"text-sm font-semibold " + STRONG}>{name}</p>
      <span className={"inline-flex shrink-0 items-center gap-1.5 text-xs " + MUTED}>
        <span className={"inline-block h-2 w-2 rounded-full " + COST_TIER_DOT[tier]} />
        {COST_TIER_DEFS[tier].label} cost
      </span>
    </div>
  );
}

function Row({
  label,
  value,
  className = "",
  valueClass = "",
  testId,
}: {
  label: ReactNode;
  value: ReactNode;
  className?: string;
  valueClass?: string;
  testId?: string;
}) {
  return (
    <div className={"flex items-baseline justify-between gap-6 " + className}>
      <span>{label}</span>
      <span
        className={"whitespace-nowrap text-right tabular-nums " + valueClass}
        data-testid={testId}
      >
        {value}
      </span>
    </div>
  );
}

// The cross-tier half of the story, in every card: is anything in the WHOLE
// catalog both cheaper and higher on the AA Index? The Score cannot say — it
// compares a model with its own tier only — so a card that shows a Score
// shows this too, naming the model that beats it when one does.
export function FrontierStatus({
  model: m,
  leader,
}: {
  model: ModelRow;
  // The row m.value_beaten_by names; null on the frontier.
  leader: ModelRow | null;
}) {
  if (m.aa_index === null) return null;
  const heading = (
    <p className={"mb-1 text-[11px] font-semibold uppercase tracking-wide " + MUTED}>
      Across every cost tier
    </p>
  );
  if (m.value_frontier || !leader || leader.aa_index === null) {
    return (
      <div
        className="rounded-md border border-emerald-500/40 bg-emerald-50 px-3 py-2 text-xs leading-[1.125rem] dark:bg-emerald-500/10"
        data-testid="frontier-status"
        data-frontier="1"
      >
        {heading}
        <p className="flex items-start gap-2">
          <span className="mt-[4px] inline-block h-2.5 w-2.5 shrink-0 rounded-full border-2 border-emerald-500" />
          <span>
            <span className={"font-semibold " + STRONG}>On the cost/quality frontier.</span> Nothing
            in the catalog, in any cost tier, costs less and scores higher on the AA Index.
          </span>
        </p>
      </div>
    );
  }
  const price = blendedPrice(m.input_price_per_1m, m.output_price_per_1m);
  const leaderPrice = blendedPrice(leader.input_price_per_1m, leader.output_price_per_1m);
  const higher = leader.aa_index > m.aa_index;
  const cheaper = leaderPrice < price;
  const how = `${higher ? "scores higher" : "scores the same"} ${cheaper ? "for less" : "at the same price"}`;
  return (
    <div
      className="rounded-md border border-brand-slate-200 bg-brand-slate-50 px-3 py-2 text-xs leading-[1.125rem] dark:border-brand-slate-600 dark:bg-brand-slate-900/70"
      data-testid="frontier-status"
      data-frontier="0"
      data-beaten-by={leader.id}
    >
      {heading}
      <p>
        <span className={"font-semibold " + STRONG}>Off the frontier:</span>{" "}
        {leader.name} ({COST_TIER_DEFS[leader.tier_cost].label} cost) {how}.
      </p>
      <Row
        className="mt-1"
        label="AA Index"
        value={`${num(leader.aa_index)}${leader.aa_index_source === "cited" ? " (cited)" : ""} vs ${num(m.aa_index)}`}
        valueClass={STRONG}
      />
      <Row label="Blended price" value={`${usd(leaderPrice)} vs ${usd(price)}`} valueClass={STRONG} />
    </div>
  );
}

// The AA Index cell's card: the figure, where it came from, and the frontier.
export function IndexCard({
  model: m,
  leader,
  snapshot,
}: {
  model: ModelRow;
  leader: ModelRow | null;
  snapshot: string;
}) {
  if (m.aa_index === null) return null;
  return (
    <div className="w-[20rem] max-w-full" data-testid="index-card">
      <CardHeader name={m.name} tier={m.tier_cost} />
      <div className="mt-2">
        <Row
          label={<span className={"font-semibold " + STRONG}>AA Intelligence Index</span>}
          value={num(m.aa_index)}
          valueClass={"text-sm font-bold " + STRONG}
        />
      </div>
      <p className={"mt-1 text-xs leading-[1.125rem] " + MUTED}>
        Artificial Analysis&rsquo;s weighted average over its evaluation suite, 0&ndash;100.{" "}
        {m.aa_index_source === "cited"
          ? "As cited in the catalog; this model is not in the Artificial Analysis data snapshot yet."
          : `From the snapshot of ${snapshot}.`}
      </p>
      <div className="mt-2.5">
        <FrontierStatus model={m} leader={leader} />
      </div>
    </div>
  );
}

export function ScoreBreakdownCard({
  model: m,
  fit,
  snapshot,
  leader,
}: {
  model: ModelRow;
  fit: ScoreFit;
  // Artificial Analysis snapshot stamp, e.g. "2026-09-22 22:09 UTC".
  snapshot: string;
  // The model that beats this one across the whole catalog (null on the frontier).
  leader: ModelRow | null;
}) {
  const price = blendedPrice(m.input_price_per_1m, m.output_price_per_1m);
  const b = scoreBreakdown(fit, m.tier_cost, price, m.aa_index);
  if (!b) return null;
  const tier = COST_TIER_DEFS[m.tier_cost].label;
  const s = b.shown;
  const sigma = fit.sigma;
  const adj = Math.abs(s.priceAdjustment);
  const ratio = b.priceRatio;

  let priceSentence: string;
  if (adj === 0) {
    priceSentence = `${m.name} costs about the tier's typical price, so there is nothing to adjust for.`;
  } else if (s.priceAdjustment < 0) {
    priceSentence = `${m.name} costs ${ratio.toFixed(2)}× the typical price. Pricier models usually score higher, so ${num(adj)} of its points are credited to price and taken off.`;
  } else {
    priceSentence = `${m.name} costs ${ratio.toFixed(2)}× the typical price. Cheaper models usually score lower, so the ${num(adj)} points its price predicts it would lose are added back.`;
  }

  const outside = Math.abs(b.score) >= sigma;
  const bandSentence = outside
    ? `Outside the ±${num(sigma)} tie band, so this is a real ${b.score > 0 ? "lead over" : "shortfall against"} the line, not noise.`
    : `Inside the ±${num(sigma)} tie band: within the line's normal scatter, so treat it as a tie.`;

  return (
    <div className="w-[22rem] max-w-full" data-testid="score-breakdown">
      <CardHeader name={m.name} tier={m.tier_cost} />
      <p className={"mt-1 text-xs leading-[1.125rem] " + MUTED}>
        Score: AA Index points above (+) or below (−) what this model&rsquo;s price predicts
        among {tier}-cost models.
      </p>

      <div className="mt-3 rounded-md bg-brand-slate-50 px-3 py-2.5 dark:bg-brand-slate-900/70">
        <p className={"mb-1.5 text-[11px] font-semibold uppercase tracking-wide " + MUTED}>
          How the score adds up
        </p>
        <Row label="AA Intelligence Index" value={num(s.index)} valueClass={STRONG} />
        <Row
          label={`${tier}-cost average (${b.tierN} models)`}
          value={`− ${num(s.tierMean)}`}
          valueClass={STRONG}
        />
        <div className={"my-1.5 border-t " + RULE} />
        <Row
          label={s.vsAverage >= 0 ? "Above the tier average" : "Below the tier average"}
          value={formatScore(s.vsAverage)}
          valueClass={STRONG}
        />
        <Row label="Price adjustment" value={formatScore(s.priceAdjustment)} valueClass={STRONG} />
        <div className={"mt-1.5 border-t-2 border-double pt-1.5 " + RULE}>
          <Row
            label={<span className={"font-semibold " + STRONG}>Score</span>}
            value={formatScore(s.score)}
            valueClass={"text-sm font-bold " + scoreToneClass(b.score, sigma)}
            testId="score-breakdown-total"
          />
        </div>
      </div>

      <div className="mt-3">
        <p className={"mb-1 text-[11px] font-semibold uppercase tracking-wide " + MUTED}>
          The price adjustment
        </p>
        <Row label="Blended price" value={`${usd(b.price)} per 1M tokens`} valueClass={STRONG} />
        <p className={"-mt-0.5 mb-1 text-right text-xs tabular-nums " + MUTED}>
          (3 × {formatUsd(m.input_price_per_1m)} input + {formatUsd(m.output_price_per_1m)} output) ÷ 4
        </p>
        <Row
          label={`Typical ${tier}-cost price`}
          value={`${usd(b.typicalPrice)} per 1M tokens`}
          valueClass={STRONG}
        />
        <Row label="Price effect" value={`${num(b.slope)} points per 10× price`} valueClass={STRONG} />
        <p className="mt-1.5 text-xs leading-[1.125rem]">{priceSentence}</p>
      </div>

      <div className={"mt-3 space-y-1.5 border-t pt-2.5 text-xs leading-[1.125rem] " + RULE}>
        <p>{bandSentence}</p>
        <p className={MUTED}>
          {m.aa_index_source === "cited"
            ? "AA Index as cited in the catalog; this model is not in the Artificial Analysis data snapshot yet."
            : `AA Index from the Artificial Analysis snapshot of ${snapshot}.`}
        </p>
      </div>

      <div className="mt-3">
        <FrontierStatus model={m} leader={leader} />
      </div>
    </div>
  );
}

export function ModelPointCard({
  model: m,
  fit,
  leader,
}: {
  model: ModelRow;
  fit: ScoreFit;
  leader: ModelRow | null;
}) {
  const price = blendedPrice(m.input_price_per_1m, m.output_price_per_1m);
  const b = scoreBreakdown(fit, m.tier_cost, price, m.aa_index);
  if (!b) return null;
  return (
    <div className="w-[18rem] max-w-full" data-testid="point-card">
      <CardHeader name={m.name} tier={m.tier_cost} />
      <div className="mt-2.5 space-y-0.5">
        <Row
          label={<span className={"font-semibold " + STRONG}>Score</span>}
          value={formatScore(b.shown.score)}
          valueClass={"text-sm font-bold " + scoreToneClass(b.score, fit.sigma)}
          testId="point-card-score"
        />
        <Row label="AA Index" value={num(b.shown.index)} valueClass={STRONG} />
        <Row label="Expected at this price" value={num(b.shown.expected)} valueClass={STRONG} />
      </div>
      <p className={"mt-1 text-xs " + MUTED}>
        Score = AA Index − expected: {num(b.shown.index)} − {num(b.shown.expected)}
      </p>
      <div className={"mt-2.5 space-y-0.5 border-t pt-2.5 " + RULE}>
        <Row label="Input" value={`${usd(m.input_price_per_1m)} per 1M tokens`} valueClass={STRONG} />
        <Row label="Output" value={`${usd(m.output_price_per_1m)} per 1M tokens`} valueClass={STRONG} />
        <Row label="Blended (3 : 1)" value={`${usd(b.price)} per 1M tokens`} valueClass={STRONG} />
      </div>
      <div className="mt-2.5">
        <FrontierStatus model={m} leader={leader} />
      </div>
    </div>
  );
}

// Subscript ten for log₁₀, kept as one unit so it never wraps apart.
const LOG10 = (
  <span className="whitespace-nowrap">
    log<sub className="text-[0.7em]">10</sub>
  </span>
);

export function PriceLineCard({
  tier,
  fit,
  atPrice,
}: {
  tier: CostTier;
  fit: ScoreFit;
  // The blended price under the pointer, for the live readout.
  atPrice: number;
}) {
  const t = fit.tiers[tier];
  const label = COST_TIER_DEFS[tier].label;
  const typical = 10 ** t.meanLogPrice;
  const expected = t.intercept + fit.slope * Math.log10(atPrice);
  const tierCount = Object.keys(fit.tiers).length;
  const sign = (v: number) => (v < 0 ? "−" : "+");
  return (
    <div className="w-[23rem] max-w-full" data-testid="line-card">
      <p className={"text-sm font-semibold " + STRONG}>Price line: {label} cost</p>
      <p className={"mt-0.5 text-xs " + MUTED}>
        What a model in this tier is expected to score at each price.
      </p>

      <div
        className={
          "mt-2.5 rounded-md bg-brand-slate-50 px-3 py-2.5 text-[14px] font-semibold tabular-nums dark:bg-brand-slate-900/70 " +
          STRONG
        }
        data-testid="line-equation"
      >
        Expected AA Index = {num(t.intercept)} + {num(fit.slope)} × {LOG10}(p)
      </div>

      <dl className="mt-2.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs leading-[1.125rem]">
        <dt className={"font-semibold tabular-nums " + STRONG}>p</dt>
        <dd>
          Blended price, $ per 1M tokens
          <span className={"block " + MUTED}>= (3 × input + 1 × output) ÷ 4</span>
        </dd>
        <dt className={"font-semibold tabular-nums " + STRONG}>{num(t.intercept)}</dt>
        <dd>Intercept for this tier: the line&rsquo;s height at p&nbsp;=&nbsp;$1</dd>
        <dt className={"font-semibold tabular-nums " + STRONG}>{num(fit.slope)}</dt>
        <dd>
          Slope: AA Index points per 10× price, one value shared by all {tierCount} cost tiers
        </dd>
      </dl>

      <div className={"mt-2.5 border-t pt-2 text-xs leading-[1.125rem] " + RULE}>
        <p className={"font-semibold " + STRONG}>The same line, centred on this tier</p>
        <p className={"mt-0.5 font-semibold tabular-nums " + STRONG}>
          Expected = {num(t.meanIndex)} {sign(fit.slope)} {num(Math.abs(fit.slope))} × {LOG10}(p ÷{" "}
          {usd(typical)})
        </p>
        <p className="mt-0.5">
          {num(t.meanIndex)} is the average AA Index of this tier&rsquo;s {t.n} models, and{" "}
          {usd(typical)} their typical (geometric-mean) blended price.
        </p>
      </div>

      <div
        className="mt-2.5 flex items-baseline justify-between gap-4 rounded-md border border-brand-accent/40 bg-brand-accent/5 px-3 py-1.5 text-[13px] tabular-nums"
        data-testid="line-readout"
      >
        <span>At {usd(atPrice)} per 1M tokens</span>
        <span className={"font-semibold " + STRONG}>expected {num(expected)}</span>
      </div>

      <p className={"mt-2.5 border-t pt-2 text-xs leading-[1.125rem] " + RULE + " " + MUTED}>
        Least squares over {fit.n} AA-measured models. R² {fit.r2.toFixed(2)}: price and tier
        explain {Math.round(fit.r2 * 100)}% of the spread in AA Index. Residual σ {num(fit.sigma)}{" "}
        is the shaded band. A model&rsquo;s Score is its height above (+) or below (−) this line.
      </p>
    </div>
  );
}
