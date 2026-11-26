// web/components/ScoreCards.tsx
//
// What the /models hover cards say. One visual language:
//   ScoreBreakdownCard — a table Score, taken apart into parts that add up to
//                        the printed figure (lib/benchmark-grid scoreBreakdown)
//   IndexCard          — a table AA Index: the figure, the AA model it was
//                        measured as, the model's own benchmarks ranked in the
//                        catalog with a verdict on whether they bear the index
//                        out (lib/benchmark-grid indexEvidence), and the top
//                        score at its price or less (the frontier)
//   ModelPointCard     — a chart dot: the model, its Score, AA Index and prices
//   PriceLineCard      — a chart's fitted line: the equation, what each term
//                        means, and the expected index at the pointer
//   FrontierPointCard  — a dot on the frontier chart: AA Index, blended price,
//                        and where it stands across the whole catalog
//   FrontierStepCard   — the frontier line: the top score a price buys
// Every card that shows a Score also shows FrontierStatus: the Score measures
// vertical distance from the continuous whole-catalog price line, and
// FrontierStatus shows the top model at that price or less in the whole catalog
// or the active Provider/Jurisdiction pool (FrontierScope).
// Figures come from the same ScoreFit the table and charts use, so a card can
// never disagree with the cell or the dot it explains.
import { createContext, useContext, type ReactNode } from "react";

import {
  blendedPrice,
  DERIVATION_BANDS,
  ESTIMATE_CEILING,
  formatBench,
  formatScore,
  formatSigned,
  formatUsd,
  GRID_COLUMN_BY_KEY,
  scoreBreakdown,
  scoreFor,
  sigmaAt,
  VALUE_HIGH,
  VALUE_LOW,
  type BenchColumn,
  type EvidenceVerdict,
  type IndexEvidence,
  type ScoreFit,
} from "@/lib/benchmark-grid";
import {
  CATEGORY_DEFS,
  COST_TIER_DEFS,
  COST_TIER_DOT,
  ESTIMATED_BADGE,
  RATING_COLORS,
  RATING_OUTLINE_COLORS,
  type Category,
  type CostTier,
  type ModelRow,
  type Rating,
} from "@/lib/catalog-fields";
import { RATING_SCALE } from "@/lib/glossary";
import { EFFORT_TOKEN_MULTIPLIER, effortLabel, effortPrice, effortWord, headlinePrice, headlineTokenShare, type EffortLevel } from "@/lib/pick-effort";

const RATING_MEANING: Record<string, string> = Object.fromEntries(
  RATING_SCALE.map((r) => [r.rating, r.meaning]),
);

// Which models the frontier compares (lib/catalog-filter poolScope), as a
// modifier for "every ___ model": null for the whole catalog, else "US + EU"
// or "Anthropic" on /models, or YOUR_MODELS on /recommend. The pages provide
// it; the cards read it.
export const FrontierScope = createContext<string | null>(null);

// The /recommend scope: the models the viewer's Settings reach.
export const YOUR_MODELS = "your";

const MUTED = "text-brand-slate-500 dark:text-brand-slate-400";
const STRONG = "text-brand-slate-900 dark:text-brand-slate-50";
const RULE = "border-brand-slate-200 dark:border-brand-slate-600";

// A price in a card: always two decimals, so "$8.00" lines up with "$6.65".
const usd = (v: number) => `$${v.toFixed(2)}`;

// One decimal, typographic minus, no sign for positives: "57.6", "−5.2".
// "≈" before an index AA has not measured: an earlier version's copy,
// roadmodel's estimate from the launch table, or, on /recommend, a measured
// model read at an effort AA did not measure it at.
function approx(m: Pick<ModelRow, "aa_index_source" | "aa_index_level_estimated">): string {
  return m.aa_index_source === "inherited" || m.aa_index_source === "estimated" || m.aa_index_level_estimated
    ? "≈"
    : "";
}

// "A", "A and B", "A, B and C".
function listNames(names: readonly string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

function num(v: number): string {
  const r = Math.round(v * 10) / 10;
  return (r < 0 ? "−" : "") + Math.abs(r).toFixed(1);
}

// Signed two-decimal figure for standardised gaps ("+1.37", "−0.86", "0.00").
function signed2(v: number): string {
  const r = Math.round(v * 100) / 100;
  if (r === 0) return "0.00";
  return (r > 0 ? "+" : "−") + Math.abs(r).toFixed(2);
}

function ordinal(n: number): string {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}

// A model's index as the cards print it: AA's to one decimal; an estimate, good
// to about four points, as the whole number the table shows; either marked ≈
// when AA has not measured it.
export function indexText(
  m: Pick<ModelRow, "aa_index" | "aa_index_source" | "aa_index_level_estimated">,
): string {
  if (m.aa_index === null) return "—";
  return `${approx(m)}${m.aa_index_source === "estimated" ? String(Math.round(m.aa_index)) : num(m.aa_index)}`;
}

// Colour rule for a 0–100% Value percentile: top quartile (≥75%) reads green,
// bottom quartile (≤25%) reads orange, middle half stays neutral.
export function scoreToneClass(score: number): string {
  if (score >= VALUE_HIGH) return "text-emerald-700 dark:text-emerald-300";
  if (score <= VALUE_LOW) return "text-orange-700 dark:text-orange-300";
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

// The whole-catalog half of the story, in every card (the filtered pool's,
// when the filters narrow it). A green ring marks a model on the cost/quality
// frontier: the top AA Index at its price or less.
// Any other model is shown with the model that holds the top score at its
// price or less, so a card that shows a Score shows this too.
export function FrontierStatus({
  model: m,
  leader,
}: {
  model: ModelRow;
  // The row m.value_beaten_by names; null on the frontier.
  leader: ModelRow | null;
}) {
  const scope = useContext(FrontierScope);
  if (m.aa_index === null) return null;
  const heading = (
    <p className={"mb-1 text-[11px] font-semibold uppercase tracking-wide " + MUTED}>
      {scope ? `Across ${scope} models` : "Across the whole catalog"}
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
            <span className={"font-semibold " + STRONG}>On the cost/quality frontier.</span> It
            scores higher on the AA Index than every other{" "}
            {scope === YOUR_MODELS ? "model you can use" : scope ? `${scope} model` : "model"} at its
            price or less.
          </span>
        </p>
      </div>
    );
  }
  const price = headlinePrice(m);
  const leaderPrice = headlinePrice(leader);
  // On /recommend an estimate stands on the frontier where the recommender
  // counts it, a margin below the figure it prints (aa_index_margin), so the
  // two are compared as counted.
  const counted = (r: ModelRow) => (r.aa_index ?? 0) - (r.aa_index_margin ?? 0);
  const asCounted = (m.aa_index_margin ?? 0) > 0 || (leader.aa_index_margin ?? 0) > 0;
  const scores = counted(leader) > counted(m) ? "scores higher" : "scores the same";
  const costs = leaderPrice < price - 1e-9 ? "costs less" : "costs the same";
  const priceLabel = m.aa_index_effort || leader.aa_index_effort ? "Effort-adjusted price" : "Blended price";
  return (
    <div
      className="rounded-md border border-brand-slate-200 bg-brand-slate-50 px-3 py-2 text-xs leading-[1.125rem] dark:border-brand-slate-600 dark:bg-brand-slate-900/70"
      data-testid="frontier-status"
      data-frontier="0"
      data-beaten-by={leader.id}
    >
      {heading}
      <p>
        <span className={"font-semibold " + STRONG}>
          Top score at this price or less: {leader.name}
        </span>{" "}
        ({COST_TIER_DEFS[leader.tier_cost].label} cost). It {scores} and {costs}.
      </p>
      <Row
        className="mt-1"
        label={asCounted ? "AA Index, as counted" : "AA Index"}
        value={
          asCounted
            ? `${num(counted(leader))} vs ${num(counted(m))}`
            : `${indexText(leader)}${leader.aa_index_source === "cited" ? " (cited)" : ""} vs ${indexText(m)}`
        }
        valueClass={STRONG}
        testId="frontier-status-index"
      />
      <Row label={priceLabel} value={`${usd(leaderPrice)} vs ${usd(price)}`} valueClass={STRONG} />
    </div>
  );
}

// A dot on the frontier chart: the model, its AA Index and blended price, and
// where it stands across the whole catalog.
export function FrontierPointCard({ model: m, leader }: { model: ModelRow; leader: ModelRow | null }) {
  if (m.aa_index === null) return null;
  const price = headlinePrice(m);
  const share = headlineTokenShare(m);
  // /recommend: how far below its estimate the recommender counts this point.
  const margin = m.aa_index_margin ?? 0;
  return (
    <div className="w-[19rem] max-w-full" data-testid="frontier-point-card">
      <CardHeader name={m.name} tier={m.tier_cost} />
      <div className="mt-2 space-y-0.5">
        <Row label="AA Index" value={`${indexText(m)}`} valueClass={"font-semibold " + STRONG} />
        {margin > 0 && (
          <Row
            label="Counted as"
            value={num(m.aa_index - margin)}
            valueClass={STRONG}
            testId="frontier-point-counted"
          />
        )}
        <Row
          label={m.aa_index_effort ? `Price at ${effortWord(m.aa_index_effort)}` : "Blended price"}
          value={`${usd(price)} per 1M tokens`}
          valueClass={STRONG}
        />
        <p className={"text-right text-xs tabular-nums " + MUTED}>
          (3 × {formatUsd(m.input_price_per_1m)} input + {formatUsd(m.output_price_per_1m)} output
          {share !== null && <> × {share.toFixed(2)}</>}) ÷ 4
        </p>
        {margin > 0 && (
          <p className={"pt-1 text-xs leading-[1.125rem] " + MUTED}>
            The index is roadmodel&rsquo;s estimate until Artificial Analysis measures this model. The
            recommender counts it {num(margin)} points lower for its uncertainty, and the chart plots it
            there.
          </p>
        )}
      </div>
      <div className="mt-2.5">
        <FrontierStatus model={m} leader={leader} />
      </div>
    </div>
  );
}

// The frontier line under the pointer: the top AA Index that price buys, and
// the model that holds it.
export function FrontierStepCard({ atPrice, model: m }: { atPrice: number; model: ModelRow }) {
  if (m.aa_index === null) return null;
  const price = headlinePrice(m);
  return (
    <div className="w-[19rem] max-w-full" data-testid="frontier-step-card">
      <p className={"text-sm font-semibold " + STRONG}>Top score at {usd(atPrice)} or less</p>
      <div className="mt-2 rounded-md border border-emerald-500/40 bg-emerald-50 px-3 py-2 dark:bg-emerald-500/10">
        <CardHeader name={m.name} tier={m.tier_cost} />
        <div className="mt-1.5 space-y-0.5 text-xs">
          <Row label="AA Index" value={`${indexText(m)}`} valueClass={"font-semibold " + STRONG} />
          <Row
            label={m.aa_index_effort ? `Price at ${effortWord(m.aa_index_effort)}` : "Blended price"}
            value={`${usd(price)} per 1M tokens`}
            valueClass={STRONG}
          />
        </div>
      </div>
      <p className={"mt-2 text-xs leading-[1.125rem] " + MUTED}>
        The line holds this height until the next ringed model, where it steps up.
      </p>
    </div>
  );
}

// A superseded model's card: what its successor, from the same maker, beats it
// on, and the day it leaves the catalog (update/supersede.py).
export function SupersededCard({ model: m, successor }: { model: ModelRow; successor: ModelRow | null }) {
  const name = successor?.name ?? m.superseded_by ?? "";
  const price = blendedPrice(m.input_price_per_1m, m.output_price_per_1m);
  const successorPrice = successor
    ? blendedPrice(successor.input_price_per_1m, successor.output_price_per_1m)
    : null;
  const samePriceOrLess = successorPrice !== null && successorPrice <= price;
  // A successor Artificial Analysis has not measured supersedes on its
  // estimate less half the estimate's margin (update/supersede.py).
  const unmeasured =
    successor !== null &&
    (successor.aa_index_source === "estimated" || successor.aa_index_source === "inherited");
  const score = unmeasured
    ? "has no AA Index measurement yet but is estimated to score higher, by more than the estimate's margin"
    : "scores higher on the AA Index";
  return (
    <div className="w-[20rem] max-w-full" data-testid="superseded-card-body">
      <CardHeader name={m.name} tier={m.tier_cost} />
      <p className={"mt-2 text-xs leading-[1.125rem] " + STRONG}>
        <span className="font-semibold">Superseded by {name}.</span> {name}, from the same
        maker, {samePriceOrLess ? `costs the same or less, ${score}` : `${score} in the next version of this series`}, and
        replaces {m.name} across its maker&rsquo;s surfaces.
      </p>
      {successor && successor.aa_index !== null && m.aa_index !== null && successorPrice !== null && (
        <div className="mt-2 space-y-0.5 text-xs">
          <Row label="AA Index" value={`${indexText(successor)} vs ${indexText(m)}`} valueClass={STRONG} />
          <Row label="Blended price" value={`${usd(successorPrice)} vs ${usd(price)}`} valueClass={STRONG} />
        </div>
      )}
      <p className={"mt-2 text-xs leading-[1.125rem] " + MUTED}>
        The recommender considers {name} in its place.
        {m.retires_on ? ` ${m.name} leaves the catalog on ${m.retires_on}.` : ""}
      </p>
    </div>
  );
}

// The AA Index cell's card: the figure, where it came from, and the frontier.
export function IndexCard({
  model: m,
  leader,
  snapshot,
  evidence = null,
}: {
  model: ModelRow;
  leader: ModelRow | null;
  snapshot: string;
  // The model's own benchmarks ranked in the catalog (null when AA has no
  // index for it in the snapshot).
  evidence?: IndexEvidence | null;
}) {
  if (m.aa_index === null) return null;
  return (
    <div className="w-[20rem] max-w-full" data-testid="index-card">
      <CardHeader name={m.name} tier={m.tier_cost} />
      <div className="mt-2">
        <Row
          label={<span className={"font-semibold " + STRONG}>AA Intelligence Index</span>}
          value={`${indexText(m)}${m.aa_index_effort ? ` at ${effortWord(m.aa_index_effort)}` : ""}`}
          valueClass={"text-sm font-bold " + STRONG}
        />
      </div>
      <p className={"mt-1 text-xs leading-[1.125rem] " + MUTED}>
        Artificial Analysis&rsquo;s weighted average over its evaluation suite, 0&ndash;100.{" "}
        {m.aa_index_source === "cited"
          ? "As cited in the catalog; this model is not in the Artificial Analysis data snapshot yet."
          : m.aa_index_source === "inherited"
            ? `An estimate: ${m.aa_inherited_from}'s index from the snapshot of ${snapshot}, which ${m.name} stands on until Artificial Analysis measures it. The recommender ranks it the same way.`
            : m.aa_index_source === "estimated"
              ? m.aa_estimate_method === "prior"
                ? `roadmodel's day-one estimate, within about ${m.aa_index_band} points: placed against measured catalog models at ${m.name}'s price and role until Artificial Analysis measures it or its vendor publishes a benchmark comparison table. The recommender ranks it on this estimate, ${Math.round((m.aa_index_band ?? 6) * 5) / 10} points lower for its uncertainty.`
                : m.aa_estimate_method === "predecessor"
                  ? `roadmodel's estimate, within about ${m.aa_index_band} points: ${m.aa_estimate_anchors?.[0] ?? m.aa_inherited_from}'s measured AA Index, until Artificial Analysis measures ${m.name}. The recommender ranks it on this estimate, ${Math.round((m.aa_index_band ?? 5) * 5) / 10} points lower for its uncertainty.`
                  : (m.aa_estimate_anchors?.length ?? 0) === 0
                    ? `roadmodel's estimate, within about ${m.aa_index_band} points: ${m.name}'s published component benchmarks placed on Artificial Analysis's scale until Artificial Analysis measures ${m.name}. The recommender ranks it on this estimate, ${Math.round((m.aa_index_band ?? 3.5) * 5) / 10} points lower for its uncertainty.`
                    : `roadmodel's estimate, within about ${m.aa_index_band} points: ${m.aa_estimate_via ? `${m.name}'s scores in the launch benchmarks of ${listNames(m.aa_estimate_via)}` : `${m.name}'s launch benchmarks`} set beside ${listNames(m.aa_estimate_anchors ?? [])}, which Artificial Analysis has measured, until it measures ${m.name} too${m.aa_estimate_via ? "" : ", and adjusted by how its maker's earlier launch benchmarks compared with Artificial Analysis's measurements"}. The recommender ranks it on this estimate, ${Math.round((m.aa_index_band ?? 3.5) * 5) / 10} points lower for its uncertainty.`
              : `From the snapshot of ${snapshot}.`}
      </p>
      {m.bench && (
        <p className={"mt-1 text-xs leading-[1.125rem] " + MUTED} data-testid="index-measured-as">
          Measured as <span className={STRONG}>{m.bench.aa_name}</span>
          {m.bench.release_date ? `, released ${m.bench.release_date}` : ""}.
        </p>
      )}
      {evidence && evidence.items.length > 0 && <IndexEvidenceBlock evidence={evidence} />}
      <div className="mt-2.5">
        <FrontierStatus model={m} leader={leader} />
      </div>
    </div>
  );
}

const VERDICT_TEXT: Record<EvidenceVerdict, string> = {
  agrees: "Its benchmark ranks agree with its index rank: its own results bear the index out.",
  above: "Its index ranks above most of its own benchmarks; weigh the index alongside them.",
  below: "Its index ranks below most of its own benchmarks; its individual results run stronger.",
};

const VERDICT_TONE: Record<EvidenceVerdict, string> = {
  agrees: "text-emerald-700 dark:text-emerald-300",
  above: "text-amber-700 dark:text-amber-300",
  below: "text-amber-700 dark:text-amber-300",
};

// Where the model's index comes from, in its own results: each benchmark AA
// measured it on, its rank in this catalog, then the index's rank, and the
// verdict (lib/benchmark-grid indexEvidence).
function IndexEvidenceBlock({ evidence: e }: { evidence: IndexEvidence }) {
  const rank = (r: number, of: number) => (
    <span className={"ml-2 inline-block min-w-[4.25rem] text-left " + MUTED}>
      #{r} of {of}
    </span>
  );
  return (
    <div
      className="mt-2.5 rounded-md bg-brand-slate-50 px-3 py-2 dark:bg-brand-slate-900/70"
      data-testid="index-evidence"
      data-verdict={e.verdict ?? ""}
    >
      <p className={"mb-1 text-[11px] font-semibold uppercase tracking-wide " + MUTED}>
        Its own benchmarks, ranked in this catalog
      </p>
      {e.items.map((it) => {
        const col = GRID_COLUMN_BY_KEY[it.key];
        return (
          <Row
            key={it.key}
            className="text-xs"
            label={col.label}
            value={
              <>
                <span className={STRONG}>{formatBench(it.value, col.unit)}</span>
                {rank(it.rank, it.of)}
              </>
            }
            testId="index-evidence-row"
          />
        );
      })}
      <div className={"my-1 border-t " + RULE} />
      <Row
        className="text-xs"
        label={<span className="font-semibold">AA Intelligence Index</span>}
        value={
          <>
            <span className={"font-semibold " + STRONG}>{num(e.index.value)}</span>
            {rank(e.index.rank, e.index.of)}
          </>
        }
        testId="index-evidence-index"
      />
      {e.verdict && (
        <p
          className={"mt-1.5 text-xs leading-[1.125rem] " + VERDICT_TONE[e.verdict]}
          data-testid="index-verdict"
        >
          {VERDICT_TEXT[e.verdict]}
        </p>
      )}
    </div>
  );
}

// Subscript ten for log₁₀, kept as one unit so it never wraps apart.
const LOG10 = (
  <span className="whitespace-nowrap">
    log<sub className="text-[0.7em]">10</sub>
  </span>
);

interface BestEffortInsight {
  label: string;
  price: number;
  index: number;
  score: number;
}

// Check if another AA-measured effort for this model achieves materially higher
// Value (≥ 5 percentage points above the currently shown effort). Surfaces
// cases like Opus 5.5 (74% at Max $40.08 vs 88% at Extra high $8.29).
function bestValueEffort(
  m: ModelRow,
  fit: ScoreFit,
  currentScore: number,
  currentEffortLabel: string | null,
): BestEffortInsight | null {
  const byEffort = m.aa_index_by_effort;
  if (!byEffort) return null;
  let best: BestEffortInsight | null = null;
  for (const [level, aa] of Object.entries(byEffort)) {
    if (!(level in EFFORT_TOKEN_MULTIPLIER)) continue;
    const eff = level as EffortLevel;
    const label = effortLabel(eff);
    if (currentEffortLabel && label.toLowerCase() === currentEffortLabel.toLowerCase()) continue;
    const p = effortPrice(m, eff);
    const sc = scoreFor(fit, p, aa);
    if (sc === null) continue;
    if (!best || sc > best.score) {
      best = { label, price: p, index: aa, score: sc };
    }
  }
  if (!best || best.score < currentScore + 5) return null;
  return best;
}

export function ScoreBreakdownCard({
  model: m,
  fit,
  snapshot,
  leader,
  effort = null,
}: {
  model: ModelRow;
  fit: ScoreFit;
  // Artificial Analysis snapshot stamp, e.g. "2026-09-22 22:09 UTC".
  snapshot: string;
  // The model that beats this one across the whole catalog (null on the frontier).
  leader: ModelRow | null;
  // A /recommend pick read at the effort it runs: its AA Index is the one
  // measured there, and its price is the blended price with its output part
  // scaled by the tokens it draws there relative to a typical model at high
  // (lib/pick-effort.ts effortPrice), the figure the frontier chart plots.
  effort?: { label: string; tokenShare: number } | null;
}) {
  const listPrice = blendedPrice(m.input_price_per_1m, m.output_price_per_1m);
  const defaultShare = headlineTokenShare(m);
  const activeEffort =
    effort ??
    (m.aa_index_effort && defaultShare !== null
      ? { label: effortWord(m.aa_index_effort), tokenShare: defaultShare }
      : null);
  const price = activeEffort
    ? (3 * m.input_price_per_1m + m.output_price_per_1m * activeEffort.tokenShare) / 4
    : listPrice;
  const b = scoreBreakdown(fit, price, m.aa_index);
  if (!b) return null;
  const s = b.shown;
  const delta = -s.priceAdjustment;
  const absDelta = Math.abs(delta);
  const perDouble = b.slope * Math.log10(2);
  const factor = delta >= 0 ? Math.max(1, b.priceRatio) : Math.max(1, 1 / b.priceRatio);
  const factorText = factor >= 10 ? factor.toFixed(1) : factor.toFixed(2);
  const rangeText = `${usd(fit.minPrice)}–${usd(fit.maxPrice)}`;
  const bestAlt = bestValueEffort(m, fit, b.score, activeEffort?.label ?? null);

  let marketLineSentence: ReactNode;
  if (absDelta === 0) {
    marketLineSentence = (
      <>
        The {b.marketN} measured models span {rangeText} (geometric midpoint {usd(b.typicalPrice)}).
        At {usd(b.price)}, right at that midpoint, today&rsquo;s market line sits at {num(s.marketMean)} AA.
      </>
    );
  } else if (delta > 0) {
    marketLineSentence = (
      <>
        The {b.marketN} measured models span {rangeText} (geometric midpoint {usd(b.typicalPrice)}).
        At {usd(b.price)} ({factorText}× that midpoint), today&rsquo;s log-scale line adds{" "}
        <span className="tabular-nums">
          {num(b.slope)} × {LOG10}({factorText}) = +{num(absDelta)}
        </span>{" "}
        points to {num(s.marketMean)}, giving {num(s.expected)}.
      </>
    );
  } else {
    marketLineSentence = (
      <>
        The {b.marketN} measured models span {rangeText} (geometric midpoint {usd(b.typicalPrice)}).
        At {usd(b.price)} ({factorText}× below that midpoint), today&rsquo;s log-scale line subtracts{" "}
        <span className="tabular-nums">
          {num(b.slope)} × {LOG10}({factorText}) = {num(absDelta)}
        </span>{" "}
        points from {num(s.marketMean)}, giving {num(s.expected)}.
      </>
    );
  }

  let bandSentence: string;
  if (b.score >= VALUE_HIGH) {
    bandSentence =
      b.z >= 1
        ? `Top quartile (${VALUE_HIGH}%+, green in table): outside the local ±${num(s.sigma)} band (${signed2(b.z)}σ) — a clear lead over today\u2019s market line.`
        : `Top quartile (${VALUE_HIGH}%+, green in table): ${signed2(b.z)}σ above today\u2019s line (local band ±${num(s.sigma)}).`;
  } else if (b.score <= VALUE_LOW) {
    bandSentence =
      b.z <= -1
        ? `Bottom quartile (≤${VALUE_LOW}%, muted in table): outside the local ±${num(s.sigma)} band (${signed2(b.z)}σ) — well below today\u2019s market line.`
        : `Bottom quartile (≤${VALUE_LOW}%, muted in table): ${signed2(b.z)}σ vs. today\u2019s line (local band ±${num(s.sigma)}).`;
  } else {
    bandSentence = `Middle half (${VALUE_LOW + 1}–${VALUE_HIGH - 1}%, neutral in table): inside the local ±${num(s.sigma)} band (${signed2(b.z)}σ), close to today\u2019s market line.`;
  }

  return (
    <div className="w-[22rem] max-w-full" data-testid="score-breakdown">
      <CardHeader name={m.name} tier={m.tier_cost} />
      <p className={"mt-1 text-xs leading-[1.125rem] " + MUTED}>
        Score: 0&ndash;100% cost-adjusted market percentile &mdash; how far above or below today&rsquo;s market
        line this model sits at its {activeEffort ? "effort-adjusted" : "blended"} price, scaled by
        the local spread (50% = on the line).
      </p>

      <div className="mt-3 rounded-md bg-brand-slate-50 px-3 py-2.5 dark:bg-brand-slate-900/70">
        <p className={"mb-1.5 text-[11px] font-semibold uppercase tracking-wide " + MUTED}>
          How Score is computed
        </p>
        <Row
          label="AA Intelligence Index"
          value={
            m.aa_index_source === "estimated" || m.aa_index_source === "inherited" || m.aa_index_level_estimated
              ? indexText(m)
              : num(s.index)
          }
          valueClass={STRONG}
          testId="score-breakdown-index"
        />
        <Row
          label={`Expected at ${usd(b.price)} (today’s line)`}
          value={`− ${num(s.expected)}`}
          valueClass={STRONG}
          testId="score-breakdown-expected"
        />
        <div className={"mt-1 border-t pt-1 " + RULE}>
          <Row
            label="Gap vs. today’s line"
            value={`${formatSigned(s.gap)} pts`}
            valueClass={"font-medium " + STRONG}
            testId="score-breakdown-gap"
          />
        </div>
        <div className={"mt-1.5 space-y-0.5 border-t pt-1.5 " + RULE}>
          <Row
            label={`Local spread (σ at ${usd(b.price)})`}
            value={`${num(s.sigma)} pts`}
            valueClass={MUTED}
          />
          <Row
            label={
              <span className="tabular-nums">
                Standardised gap (z = {formatSigned(s.gap)} ÷ {num(s.sigma)})
              </span>
            }
            value={`${signed2(b.z)}σ`}
            valueClass={"font-medium " + STRONG}
            testId="score-breakdown-sigma"
          />
        </div>
        <div className={"mt-1.5 border-t-2 border-double pt-1.5 " + RULE}>
          <Row
            label={
              <span>
                <span className={"font-semibold " + STRONG}>Score</span>{" "}
                <span className={"text-xs tabular-nums " + MUTED}>
                  = Student-t<sub className="text-[0.7em]">{fit.df}</sub> CDF({signed2(b.z)}σ)
                </span>
              </span>
            }
            value={formatScore(s.value)}
            valueClass={"text-sm font-bold " + scoreToneClass(b.score)}
            testId="score-breakdown-total"
          />
          <p className={"mt-1 text-[11px] leading-4 " + MUTED} data-testid="score-breakdown-formula">
            On a Student-t (df&nbsp;=&nbsp;{fit.df}) distribution centred on today&rsquo;s line
            (0σ&nbsp;=&nbsp;50%), {signed2(b.z)}σ sits at the {ordinal(s.value)} percentile.
          </p>
        </div>
      </div>

      {bestAlt && (
        <div
          className="mt-3 rounded-md border border-brand-accent/30 bg-brand-accent/5 px-3 py-2 text-xs leading-[1.125rem] dark:bg-brand-accent/10"
          data-testid="score-breakdown-best-effort"
        >
          <p className={"mb-1 text-[11px] font-semibold uppercase tracking-wide " + MUTED}>
            Highest-Score effort
          </p>
          <Row
            label={
              <span className={"font-semibold " + STRONG}>
                {bestAlt.label} ({num(bestAlt.index)} AA at {usd(bestAlt.price)})
              </span>
            }
            value={formatScore(bestAlt.score)}
            valueClass={"font-bold " + scoreToneClass(bestAlt.score)}
          />
          {activeEffort && bestAlt.price < b.price && (
            <p className={"mt-0.5 " + MUTED}>
              {activeEffort.label} costs {(b.price / bestAlt.price).toFixed(1)}× more for{" "}
              {formatSigned(b.index - bestAlt.index)} AA points.
            </p>
          )}
        </div>
      )}

      <div className="mt-3">
        <p className={"mb-1 text-[11px] font-semibold uppercase tracking-wide " + MUTED}>
          {activeEffort ? "Effort-adjusted price" : "Blended price"}
        </p>
        <Row
          label={activeEffort ? `Price at ${activeEffort.label}` : "3 input : 1 output"}
          value={`${usd(b.price)} per 1M tokens`}
          valueClass={STRONG}
        />
        <p className={"-mt-0.5 text-right text-xs tabular-nums " + MUTED}>
          (3 × {formatUsd(m.input_price_per_1m)} input + {formatUsd(m.output_price_per_1m)} output
          {activeEffort && <> × {activeEffort.tokenShare.toFixed(2)}</>}) ÷ 4
        </p>
        {activeEffort && (
          <p className={"mt-1 text-xs leading-[1.125rem] " + MUTED} data-testid="score-breakdown-effort">
            Blends 3 input + 1 output ({usd(listPrice)} list). At {activeEffort.label} effort, this
            model writes {activeEffort.tokenShare.toFixed(2)}× the output tokens of a typical model
            at High, bringing its effective blended price to {usd(b.price)}.
          </p>
        )}
      </div>

      <div className={"mt-3 border-t pt-2.5 " + RULE}>
        <p className={"mb-1 text-[11px] font-semibold uppercase tracking-wide " + MUTED}>
          How today&rsquo;s market line predicts {num(s.expected)}
        </p>
        <Row
          label={`Today’s midpoint (${b.marketN} models)`}
          value={`${num(s.marketMean)} AA at ${usd(b.typicalPrice)}`}
          valueClass={STRONG}
        />
        <Row
          label="Price slope"
          value={`${formatSigned(perDouble)} pts per 2× price`}
          valueClass={STRONG}
        />
        <p className={"-mt-0.5 text-right text-xs tabular-nums " + MUTED}>
          ({formatSigned(b.slope)} pts per 10×)
        </p>
        <p className="mt-1.5 text-xs leading-[1.125rem]" data-testid="score-breakdown-market">
          {marketLineSentence}
          {b.vintageAdjusted && (
            <>
              {" "}
              Controlling for release age ({formatSigned(b.ageSlope)} pts/month) keeps older models
              from tilting today&rsquo;s baseline.
            </>
          )}
        </p>
      </div>

      <div className={"mt-3 space-y-1.5 border-t pt-2.5 text-xs leading-[1.125rem] " + RULE}>
        <p data-testid="score-breakdown-band">{bandSentence}</p>
        <p className={MUTED}>
          {m.aa_index_source === "cited"
            ? "AA Index as cited in the catalog; this model is not in the Artificial Analysis data snapshot yet."
            : m.aa_index_level_estimated && m.aa_index_source === "snapshot"
              ? `Artificial Analysis measured this model at other efforts (snapshot of ${snapshot}); roadmodel estimates its AA Index${m.aa_index_effort ? ` at ${effortWord(m.aa_index_effort)}` : ""} from those, so this Score is an estimate too.`
            : m.aa_index_source === "inherited"
              ? `AA Index estimated from ${m.aa_inherited_from}'s in the Artificial Analysis snapshot of ${snapshot}.`
              : m.aa_index_source === "estimated"
                ? m.aa_estimate_method === "prior"
                  ? `AA Index estimated by roadmodel from measured catalog peers at ${m.name}'s price and role (±${m.aa_index_band}), so this Score is an estimate too.`
                  : m.aa_estimate_method === "predecessor"
                    ? `AA Index estimated by roadmodel from ${m.aa_estimate_anchors?.[0] ?? m.aa_inherited_from}'s measured AA Index (±${m.aa_index_band}), so this Score is an estimate too.`
                    : `AA Index estimated by roadmodel from ${m.aa_estimate_via ? `the launch benchmarks of ${listNames(m.aa_estimate_via)}` : `${m.name}'s launch benchmarks`} (±${m.aa_index_band}), so this Score is an estimate too.`
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
  const listPrice = blendedPrice(m.input_price_per_1m, m.output_price_per_1m);
  const share = headlineTokenShare(m);
  const price = headlinePrice(m);
  const b = scoreBreakdown(fit, price, m.aa_index);
  if (!b) return null;
  return (
    <div className="w-[18rem] max-w-full" data-testid="point-card">
      <CardHeader name={m.name} tier={m.tier_cost} />
      <div className="mt-2.5 space-y-0.5">
        <Row
          label={<span className={"font-semibold " + STRONG}>Score</span>}
          value={formatScore(b.shown.value)}
          valueClass={"text-sm font-bold " + scoreToneClass(b.score)}
          testId="point-card-score"
        />
        <Row label="AA Index" value={num(b.shown.index)} valueClass={STRONG} />
        <Row
          label="Expected at this price"
          value={`${num(b.shown.expected)} (±${num(b.shown.sigma)})`}
          valueClass={STRONG}
        />
      </div>
      <p className={"mt-1 text-xs tabular-nums " + MUTED}>
        z = {formatSigned(b.shown.gap)} ÷ {num(b.shown.sigma)} = {signed2(b.z)}σ &rarr;{" "}
        {formatScore(b.shown.value)} (Student-t<sub className="text-[0.7em]">{fit.df}</sub> CDF)
      </p>
      <div className={"mt-2.5 space-y-0.5 border-t pt-2.5 " + RULE}>
        <Row label="Input" value={`${usd(m.input_price_per_1m)} per 1M tokens`} valueClass={STRONG} />
        <Row label="Output" value={`${usd(m.output_price_per_1m)} per 1M tokens`} valueClass={STRONG} />
        <Row label="Blended (3 : 1)" value={`${usd(listPrice)} per 1M tokens`} valueClass={STRONG} />
        {m.aa_index_effort && share !== null && (
          <Row
            label={`At ${effortWord(m.aa_index_effort)} (${share.toFixed(2)}× out)`}
            value={`${usd(b.price)} per 1M tokens`}
            valueClass={STRONG}
          />
        )}
      </div>
      <div className="mt-2.5">
        <FrontierStatus model={m} leader={leader} />
      </div>
    </div>
  );
}

export function PriceLineCard({
  fit,
  atPrice,
}: {
  fit: ScoreFit;
  // The blended price under the pointer, for the live readout.
  atPrice: number;
}) {
  const typical = 10 ** fit.meanLogPrice;
  const expected = fit.intercept + fit.slope * Math.log10(atPrice);
  const localSigma = sigmaAt(fit, atPrice) ?? fit.sigma;
  const sign = (v: number) => (v < 0 ? "−" : "+");
  return (
    <div className="w-[23rem] max-w-full" data-testid="line-card">
      <p className={"text-sm font-semibold " + STRONG}>Today&rsquo;s market price line</p>
      <p className={"mt-0.5 text-xs " + MUTED}>
        What a current-generation model is expected to score at each effort-adjusted price, across
        every cost tier.
      </p>

      <div
        className={
          "mt-2.5 rounded-md bg-brand-slate-50 px-3 py-2.5 text-[14px] font-semibold tabular-nums dark:bg-brand-slate-900/70 " +
          STRONG
        }
        data-testid="line-equation"
      >
        Expected AA Index = {num(fit.intercept)} + {num(fit.slope)} × {LOG10}(p)
      </div>

      <dl className="mt-2.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs leading-[1.125rem]">
        <dt className={"font-semibold tabular-nums " + STRONG}>p</dt>
        <dd>
          Effort-adjusted blended price, $ per 1M tokens
          <span className={"block " + MUTED}>= (3 × input + m × output) ÷ 4</span>
        </dd>
        <dt className={"font-semibold tabular-nums " + STRONG}>{num(fit.intercept)}</dt>
        <dd>Intercept: today&rsquo;s expected AA Index at p&nbsp;=&nbsp;$1</dd>
        <dt className={"font-semibold tabular-nums " + STRONG}>{num(fit.slope)}</dt>
        <dd>
          Slope: AA Index points per 10× price ({formatSigned(fit.slope * Math.log10(2))} per 2×),
          controlling for release age
        </dd>
      </dl>

      <div className={"mt-2.5 border-t pt-2 text-xs leading-[1.125rem] " + RULE}>
        <p className={"font-semibold " + STRONG}>The same line, centred on the market</p>
        <p className={"mt-0.5 font-semibold tabular-nums " + STRONG}>
          Expected = {num(fit.meanIndex)} {sign(fit.slope)} {num(Math.abs(fit.slope))} × {LOG10}(p ÷{" "}
          {usd(typical)})
        </p>
        <p className="mt-0.5">
          {num(fit.meanIndex)} is today&rsquo;s expected AA Index at {usd(typical)}, the geometric-mean
          blended price across all {fit.n} measured models.
        </p>
      </div>

      <div
        className="mt-2.5 flex items-baseline justify-between gap-4 rounded-md border border-brand-accent/40 bg-brand-accent/5 px-3 py-1.5 text-[13px] tabular-nums"
        data-testid="line-readout"
      >
        <span>At {usd(atPrice)} per 1M tokens</span>
        <span className={"font-semibold " + STRONG}>
          expected {num(expected)} (±{num(localSigma)})
        </span>
      </div>

      <p className={"mt-2.5 border-t pt-2 text-xs leading-[1.125rem] " + RULE + " " + MUTED}>
        Huber-robust {fit.vintageAdjusted ? "vintage-controlled " : ""}fit over {fit.n} AA-measured
        models (R² {fit.r2.toFixed(2)}
        {fit.vintageAdjusted ? `, age trend ${formatSigned(fit.ageSlope)} pts/month` : ""}). The
        shaded ribbon is the local ±σ band (±{num(fit.sigmaMin)}–{num(fit.sigmaMax)}, narrowing as
        price rises). Score maps z = (AA − expected) ÷ local σ through the Student-t (df&nbsp;=&nbsp;{fit.df})
        CDF to a 0–100% market percentile (0σ = 50%).
      </p>
    </div>
  );
}


export type RatingEvidence =
  | {
      kind: "rank";
      benchmarkLabel: string;
      detail: string;
      rank: number;
      tiedEnd?: number;
      of: number;
      ruleText: string;
    }
  | {
      kind: "gap";
      benchmarkLabel: string;
      modelValue: string;
      leaderName: string;
      leaderValue: string;
      gapPoints: number;
    }
  | {
      kind: "launch-estimated";
      benchmarkLabel: string;
      launchFigures: { label: string; value: string }[];
    }
  | {
      kind: "capped-estimated";
      benchmarkLabel: string;
      measuredCount: number;
    }
  | {
      kind: "automation-estimated";
    };

// A category rating cell's hover card: the category + styled letter badge,
// scale meaning, and the benchmark measurement (or estimation basis) behind it.
export function RatingCard({
  model: m,
  category,
  rating,
  derived,
  evidence,
}: {
  model: ModelRow;
  category: Category;
  rating: Rating;
  derived: boolean;
  evidence: RatingEvidence;
}) {
  const def = CATEGORY_DEFS[category];
  return (
    <div className="w-[21rem] max-w-full" data-testid="rating-card-body">
      <CardHeader name={m.name} tier={m.tier_cost} />
      <div className="mt-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className={"text-xs font-semibold " + STRONG}>{def.fullName}</span>
          <span
            className={
              "rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide " +
              (derived
                ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200"
                : "bg-brand-slate-100 text-brand-slate-600 dark:bg-brand-slate-700 dark:text-brand-slate-300")
            }
          >
            {derived ? "Measured" : "Estimated"}
          </span>
        </div>
        <span
          className={
            "inline-flex min-w-[1.75rem] items-center justify-center rounded px-1.5 py-0.5 text-xs font-semibold " +
            (derived ? RATING_COLORS[rating] : `${ESTIMATED_BADGE} ${RATING_OUTLINE_COLORS[rating]}`)
          }
        >
          {rating}
        </span>
      </div>
      <p className={"mt-1 text-xs leading-[1.125rem] " + MUTED}>
        <span className={"font-semibold " + STRONG}>{rating}:</span> {RATING_MEANING[rating]}
      </p>
      <div
        className="mt-2.5 rounded-md bg-brand-slate-50 px-3 py-2 text-xs leading-[1.125rem] dark:bg-brand-slate-900/70"
        data-testid="rating-evidence"
      >
        <p className={"mb-1 text-[11px] font-semibold uppercase tracking-wide " + MUTED}>
          {derived ? "Measured evidence" : "Rating basis"}
        </p>
        {evidence.kind === "rank" && (
          <>
            <Row label="Benchmark" value={evidence.benchmarkLabel} valueClass={STRONG} />
            <Row label={m.name} value={evidence.detail} valueClass={STRONG} />
            <Row
              label="Catalog rank"
              value={
                evidence.tiedEnd
                  ? `Tied #${evidence.rank}–${evidence.tiedEnd} of ${evidence.of}`
                  : `#${evidence.rank} of ${evidence.of}`
              }
              valueClass={"font-semibold " + STRONG}
            />
            <div className={"my-1.5 border-t " + RULE} />
            <p className={MUTED}>
              Rule: {evidence.ruleText}
              {evidence.tiedEnd ? ". Ties take their middle place." : "."}
            </p>
          </>
        )}
        {evidence.kind === "gap" && (
          <>
            <Row label="Benchmark" value={evidence.benchmarkLabel} valueClass={STRONG} />
            <Row label={m.name} value={evidence.modelValue} valueClass={STRONG} />
            <Row label={`Leader (${evidence.leaderName})`} value={evidence.leaderValue} valueClass={STRONG} />
            <Row
              label="Gap to leader"
              value={`${evidence.gapPoints.toFixed(1)} pts`}
              valueClass={"font-semibold " + STRONG}
            />
            <div className={"my-1.5 border-t " + RULE} />
            <p className={MUTED}>
              Bands: {DERIVATION_BANDS.map((b) => `${b.letter} ≤ ${b.max}`).join(", ")} pts, else D.
            </p>
          </>
        )}
        {evidence.kind === "launch-estimated" && (
          <>
            <Row label="Benchmark" value={evidence.benchmarkLabel} valueClass={STRONG} />
            {evidence.launchFigures.map((f) => (
              <Row key={f.label} label={`${f.label} (launch est.)`} value={f.value} valueClass={STRONG} />
            ))}
            <p className={(evidence.launchFigures.length > 0 ? "mt-1.5 border-t pt-1.5 " + RULE + " " : "") + MUTED}>
              roadmodel placed {m.name}&rsquo;s launch benchmarks onto Artificial Analysis&rsquo;s scale and
              lettered it by the same rule until Artificial Analysis measures it.
            </p>
          </>
        )}
        {evidence.kind === "capped-estimated" && (
          <>
            <Row label="Benchmark" value={evidence.benchmarkLabel} valueClass={STRONG} />
            <Row label="Catalog measured" value={`${evidence.measuredCount} models`} valueClass={STRONG} />
            <Row label="Unmeasured ceiling" value={ESTIMATE_CEILING} valueClass={STRONG} />
            <p className={"mt-1.5 border-t pt-1.5 " + RULE + " " + MUTED}>
              Estimated by the daily catalog automation from each provider&rsquo;s published results
              until Artificial Analysis measures {m.name}; an unmeasured estimate stops at{" "}
              {ESTIMATE_CEILING} because S takes a measurement.
            </p>
          </>
        )}
        {evidence.kind === "automation-estimated" && (
          <p className={MUTED}>
            Estimated by the daily catalog automation from each provider&rsquo;s published results;
            a new model starts from its predecessor&rsquo;s letter. Artificial Analysis runs no
            uniform benchmark for {def.label.toLowerCase()}.
          </p>
        )}
      </div>
    </div>
  );
}

const EFFORT_LEVEL_ORDER = ["max", "xhigh", "high", "medium", "low", "minimal"] as const;

// The Effort cell's hover card: the headline reasoning setting, AA Index across
// measured efforts with relative output-token multipliers, and per-surface vendor defaults.
export function EffortCard({ model: m }: { model: ModelRow }) {
  const byEffort = m.aa_index_by_effort ?? {};
  const multByEffort = m.token_multiplier_by_effort ?? {};
  const levelSet = new Set([...Object.keys(byEffort), ...Object.keys(multByEffort)]);
  const levels = EFFORT_LEVEL_ORDER.filter((lvl) => levelSet.has(lvl));
  if (!m.aa_index_effort && levels.length === 0 && !(m.default_efforts?.length)) return null;
  const isEstimate = m.aa_index_source === "estimated" || m.aa_index_source === "inherited";
  return (
    <div className="w-[20rem] max-w-full" data-testid="effort-card-body">
      <CardHeader name={m.name} tier={m.tier_cost} />
      {m.aa_index_effort && (
        <div className="mt-2">
          <Row
            label={<span className={"font-semibold " + STRONG}>Headline effort</span>}
            value={effortWord(m.aa_index_effort)}
            valueClass={"text-sm font-bold " + STRONG}
          />
          <p className={"mt-1 text-xs leading-[1.125rem] " + MUTED}>
            {isEstimate
              ? `Top setting ${m.name} offers and the level its launch estimates target.`
              : `Reasoning setting Artificial Analysis ran for ${m.name}'s headline row.`}
          </p>
        </div>
      )}
      {levels.length > 0 && (
        <div
          className="mt-2.5 rounded-md bg-brand-slate-50 px-3 py-2 text-xs leading-[1.125rem] dark:bg-brand-slate-900/70"
          data-testid="effort-variants"
        >
          <p className={"mb-1 text-[11px] font-semibold uppercase tracking-wide " + MUTED}>
            AA Index by effort
          </p>
          {levels.map((lvl) => {
            const idx = byEffort[lvl];
            const mult =
              multByEffort[lvl] ??
              (lvl in EFFORT_TOKEN_MULTIPLIER ? EFFORT_TOKEN_MULTIPLIER[lvl as EffortLevel] : undefined);
            const parts: string[] = [];
            if (typeof idx === "number") parts.push(num(idx));
            if (typeof mult === "number") parts.push(`${mult.toFixed(1)}× tokens`);
            return (
              <Row
                key={lvl}
                label={
                  <span>
                    {effortWord(lvl)}
                    {lvl === m.aa_index_effort && (
                      <span className={"ml-1.5 text-[10px] " + MUTED}>(headline)</span>
                    )}
                  </span>
                }
                value={parts.join(" · ") || "—"}
                valueClass={lvl === m.aa_index_effort ? "font-semibold " + STRONG : STRONG}
              />
            );
          })}
        </div>
      )}
      {m.default_efforts && m.default_efforts.length > 0 && (
        <div
          className="mt-2 rounded-md bg-brand-slate-50 px-3 py-2 text-xs leading-[1.125rem] dark:bg-brand-slate-900/70"
          data-testid="effort-defaults"
        >
          <p className={"mb-1 text-[11px] font-semibold uppercase tracking-wide " + MUTED}>
            Default setting by surface
          </p>
          {m.default_efforts.map((d) => (
            <Row key={d.surface} label={d.surface} value={effortWord(d.effort)} valueClass={STRONG} />
          ))}
        </div>
      )}
    </div>
  );
}

// A Benchmark-scores cell's hover card: the measured value, rank, percentile band, and leader.
export function BenchCellCard({
  model: m,
  column,
  value,
  rank,
  of,
  leaderValue,
  bandLabel,
}: {
  model: ModelRow;
  column: BenchColumn;
  value: number;
  rank: number;
  of: number;
  leaderValue: string;
  bandLabel: string;
}) {
  return (
    <div className="w-[19rem] max-w-full" data-testid="bench-card-body">
      <CardHeader name={m.name} tier={m.tier_cost} />
      <div className="mt-2.5 rounded-md bg-brand-slate-50 px-3 py-2 text-xs leading-[1.125rem] dark:bg-brand-slate-900/70">
        <Row label={column.label} value={formatBench(value, column.unit)} valueClass={"font-semibold " + STRONG} />
        <Row label="Catalog rank" value={`#${rank} of ${of}`} valueClass={STRONG} />
        <Row label="Percentile band" value={bandLabel} valueClass={STRONG} />
        <Row label="Column leader" value={leaderValue} valueClass={STRONG} />
      </div>
      <p className={"mt-2 text-xs leading-[1.125rem] " + MUTED}>
        Measured by Artificial Analysis{m.bench ? ` as ${m.bench.aa_name}` : ""}.
      </p>
    </div>
  );
}
