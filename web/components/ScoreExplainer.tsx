// web/components/ScoreExplainer.tsx
//
// "What does +6.7 mean?" — the Score column, drawn. For one cost tier at a
// time: every measured model as a point (price on a log x-axis, AA Intelligence
// Index on y), the tier's fitted price line, and each model's SCORE as the
// vertical distance from its point to that line. The shaded band is ±1 residual
// σ: a model inside it is indistinguishable from the line, so two scores inside
// it are a tie rather than a ranking.
//
// Everything is computed from the same rows and the same ScoreFit the table
// uses, so the picture cannot disagree with the numbers beside it, and nothing
// here needs updating when the daily refresh moves the data.
"use client";

import { useState } from "react";

import { blendedPrice, formatScore, type ScoreFit } from "@/lib/benchmark-grid";
import { COST_TIER_DEFS, COST_TIER_DOT, type CostTier, type ModelRow } from "@/lib/catalog-fields";

// Validated against both the light and the dark chart surface (protan ΔE 23.4,
// normal ΔE 33.3). Sign is also encoded by direction and by the printed value,
// so color is never the only cue.
const ABOVE = "#0284c7";
const BELOW = "#ea580c";

const W = 760;
const H = 380;
const M = { top: 18, right: 20, bottom: 46, left: 54 };
const PLOT_W = W - M.left - M.right;
const PLOT_H = H - M.top - M.bottom;

interface Point {
  id: string;
  name: string;
  x: number; // log10 blended price
  index: number;
  predicted: number;
  score: number;
  frontier: boolean;
  labelY: number; // in index units, after collision nudging
}

function tierPoints(rows: ModelRow[], fit: ScoreFit, tier: CostTier): Point[] {
  const t = fit.tiers[tier];
  if (!t) return [];
  const pts = rows
    .filter((r) => r.tier_cost === tier && r.aa_index !== null && r.value_score !== null)
    .map((r) => {
      const x = Math.log10(blendedPrice(r.input_price_per_1m, r.output_price_per_1m));
      return {
        id: r.id,
        name: r.name,
        x,
        index: r.aa_index as number,
        predicted: t.intercept + fit.slope * x,
        score: r.value_score as number,
        frontier: r.value_frontier,
        labelY: r.aa_index as number,
      };
    })
    .sort((a, b) => a.x - b.x || b.index - a.index);

  // Nudge a label off its neighbour when two models share a price (Opus 5,
  // 4.8 and 4.7 all blend to $10.00), away from the line so it never lands on
  // the segment it belongs to.
  const span = Math.max(...pts.map((p) => p.x)) - Math.min(...pts.map((p) => p.x)) || 1;
  const placed: Point[] = [];
  for (const p of pts) {
    const dir = p.score >= 0 ? 1 : -1;
    while (
      placed.some(
        (q) => Math.abs(q.x - p.x) < span * 0.22 && Math.abs(q.labelY - p.labelY) < 2.6,
      )
    ) {
      p.labelY += dir * 2.6;
    }
    placed.push(p);
  }
  return placed;
}

export function ScoreExplainer({ rows, fit }: { rows: ModelRow[]; fit: ScoreFit | null }) {
  const tiers = (Object.keys(COST_TIER_DEFS) as CostTier[]).filter(
    (t) => fit?.tiers[t] && fit.tiers[t].n >= 2,
  );
  const [tier, setTier] = useState<CostTier>(tiers.includes("very-high") ? "very-high" : tiers[0]);
  if (!fit || tiers.length === 0) return null;

  const pts = tierPoints(rows, fit, tier);
  if (pts.length === 0) return null;
  const t = fit.tiers[tier];

  const xs = pts.map((p) => p.x);
  const pad = Math.max(0.1, (Math.max(...xs) - Math.min(...xs)) * 0.22);
  const x0 = Math.min(...xs) - pad;
  const x1 = Math.max(...xs) + pad;
  const lineY0 = t.intercept + fit.slope * x0;
  const lineY1 = t.intercept + fit.slope * x1;
  const ys = [
    ...pts.map((p) => p.index),
    ...pts.map((p) => p.labelY),
    lineY0 - fit.sigma,
    lineY1 + fit.sigma,
  ];
  const yLo = Math.min(...ys) - 2;
  const yHi = Math.max(...ys) + 2;

  const sx = (x: number) => M.left + ((x - x0) / (x1 - x0)) * PLOT_W;
  const sy = (y: number) => M.top + PLOT_H - ((y - yLo) / (yHi - yLo)) * PLOT_H;

  const insideBand = pts.filter((p) => Math.abs(p.score) < fit.sigma).length;
  const priceTicks = Array.from(new Set(pts.map((p) => Math.round(p.x * 100) / 100))).sort(
    (a, b) => a - b,
  );
  const yTicks: number[] = [];
  for (let v = Math.ceil(yLo / 5) * 5; v <= yHi; v += 5) yTicks.push(v);

  return (
    <details
      className="rounded-xl border border-brand-slate-200 bg-white p-4 dark:border-brand-slate-700 dark:bg-brand-slate-900"
      data-testid="score-explainer"
    >
      <summary className="cursor-pointer text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-100">
        What a Score means — the price line, drawn
      </summary>

      <div className="mt-3 space-y-3 text-sm text-brand-slate-600 dark:text-brand-slate-300">
        <p>
          Pricier models score higher on average, so &ldquo;is this model good?&rdquo; and
          &ldquo;is this model good <em>for its price</em>?&rdquo; are different questions. The
          line below is the second one: fitted across every measured model, it says what a model
          at a given price typically scores. <strong>Score is the vertical distance from a model
          to that line</strong>, in AA Intelligence Index points — the same 0&ndash;100 scale as
          the AA Index column. Above the line (+) is more intelligence than that price usually
          buys; below (&minus;) is less. Each cost tier gets its own line, so a model is only
          ever compared with its own price band.
        </p>

        <div className="flex flex-wrap items-center gap-2">
          {tiers.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setTier(id)}
              aria-pressed={id === tier}
              data-testid="score-explainer-tier"
              data-tier={id}
              className={
                "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition " +
                (id === tier
                  ? "border-brand-accent bg-brand-accent/10 text-brand-slate-900 dark:text-brand-slate-50"
                  : "border-brand-slate-200 text-brand-slate-600 hover:border-brand-slate-400 dark:border-brand-slate-700 dark:text-brand-slate-300")
              }
            >
              <span className={"h-2 w-2 rounded-full " + COST_TIER_DOT[id]} />
              {COST_TIER_DEFS[id].label}
              <span className="text-brand-slate-400">({fit.tiers[id].n})</span>
            </button>
          ))}
        </div>

        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full text-brand-slate-500 dark:text-brand-slate-400"
          role="img"
          data-testid="score-explainer-chart"
          aria-label={`${COST_TIER_DEFS[tier].label} tier: ${pts.length} models plotted by blended price against Artificial Analysis Intelligence Index, with the fitted price line. Each model's Score is its distance from that line. The table below this chart carries the same numbers.`}
        >
          {yTicks.map((v) => (
            <g key={v}>
              <line
                x1={M.left}
                x2={W - M.right}
                y1={sy(v)}
                y2={sy(v)}
                stroke="currentColor"
                strokeOpacity={0.18}
              />
              <text x={M.left - 8} y={sy(v) + 4} textAnchor="end" fontSize={11} fill="currentColor">
                {v}
              </text>
            </g>
          ))}

          {/* ±1σ: inside this band a model is indistinguishable from the line. */}
          <polygon
            points={[
              `${sx(x0)},${sy(lineY0 + fit.sigma)}`,
              `${sx(x1)},${sy(lineY1 + fit.sigma)}`,
              `${sx(x1)},${sy(lineY1 - fit.sigma)}`,
              `${sx(x0)},${sy(lineY0 - fit.sigma)}`,
            ].join(" ")}
            fill="currentColor"
            fillOpacity={0.08}
          />
          <line
            x1={sx(x0)}
            y1={sy(lineY0)}
            x2={sx(x1)}
            y2={sy(lineY1)}
            className="stroke-brand-slate-800 dark:stroke-brand-slate-200"
            strokeWidth={2}
          />

          {pts.map((p) => {
            const color = p.score >= 0 ? ABOVE : BELOW;
            const displaced = Math.abs(p.labelY - p.index) > 1.5;
            // Label to the LEFT when another model sits just to the right (its
            // segment is where the text would land), or near the right edge.
            const crowdedRight = pts.some((q) => q.x > p.x && q.x - p.x < (x1 - x0) * 0.3);
            const right = crowdedRight || p.x > x0 + (x1 - x0) * 0.68;
            const labelX = sx(p.x) + (right ? -12 : 12);
            return (
              <g key={p.id} data-testid="score-explainer-point" data-model-id={p.id}>
                <line
                  x1={sx(p.x)}
                  y1={sy(p.predicted)}
                  x2={sx(p.x)}
                  y2={sy(p.index)}
                  stroke={color}
                  strokeWidth={2}
                />
                <circle cx={sx(p.x)} cy={sy(p.predicted)} r={3} fill="currentColor" />
                <circle
                  cx={sx(p.x)}
                  cy={sy(p.index)}
                  r={5.5}
                  fill={color}
                  className="stroke-white dark:stroke-brand-slate-900"
                  strokeWidth={1.5}
                />
                {displaced && (
                  <line
                    x1={sx(p.x)}
                    y1={sy(p.index)}
                    x2={labelX}
                    y2={sy(p.labelY)}
                    stroke="currentColor"
                    strokeOpacity={0.5}
                  />
                )}
                <text
                  x={labelX}
                  y={sy(p.labelY) + 4}
                  textAnchor={right ? "end" : "start"}
                  fontSize={11}
                  className="fill-brand-slate-700 dark:fill-brand-slate-200"
                >
                  {p.name} {formatScore(p.score)}
                  {p.frontier ? " ●" : ""}
                </text>
              </g>
            );
          })}

          {priceTicks.map((v) => (
            <text
              key={v}
              x={sx(v)}
              y={H - M.bottom + 18}
              textAnchor="middle"
              fontSize={11}
              fill="currentColor"
            >
              ${(10 ** v).toFixed(2)}
            </text>
          ))}
          <text
            x={M.left + PLOT_W / 2}
            y={H - 8}
            textAnchor="middle"
            fontSize={11}
            fill="currentColor"
          >
            Blended price per 1M tokens (3 input : 1 output), log scale
          </text>
          <text
            x={-(M.top + PLOT_H / 2)}
            y={14}
            transform="rotate(-90)"
            textAnchor="middle"
            fontSize={11}
            fill="currentColor"
          >
            AA Intelligence Index
          </text>
        </svg>

        <p className="text-xs">
          Fit over {fit.n} measured models in {Object.keys(fit.tiers).length} cost tiers:{" "}
          {fit.slope.toFixed(1)} index points per 10&times; price, R&sup2; {fit.r2.toFixed(2)},
          residual &sigma; {fit.sigma.toFixed(1)} (the shaded band).{" "}
          <strong>
            {insideBand} of {pts.length} models in this tier sit inside that band
          </strong>{" "}
          — scores that close together are a tie, not a ranking. A{" "}
          <span aria-hidden>●</span> marks the cost/quality frontier: nothing in the whole catalog
          is both cheaper and higher on the AA Index, which is a statement about every model, not
          just this tier. The table below carries these same numbers.
        </p>
      </div>
    </details>
  );
}
