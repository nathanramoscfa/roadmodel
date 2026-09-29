// web/components/ScoreCharts.tsx
//
// The Score column, drawn, in the groups the table's Group by switch chooses:
//   Cost tier — one chart per cost tier, priciest first. Each plots the tier's
//     measured models at their blended price (x, log scale) and AA
//     Intelligence Index (y), with the tier's fitted price line, the ±σ tie
//     band, and a stem from the line to each model: the stem's length IS the
//     model's Score.
//   Quality — one chart per ten-point AA Index band, best band first, the
//     table's quality groups. A band holds models from several cost tiers and
//     a model's Score is read against its own tier's line, so each tier in the
//     band gets its line (and tie band) across the prices of its models there,
//     named on the chart, and each stem runs to its own tier's line. The tiers
//     share one slope, so their lines run parallel.
// Both groupings plot the same models with the same Scores.
//
// Interactive: hover (mouse), tap (touch), or tab to (keyboard) any dot for a
// card with the model's name, Score, AA Index and prices; hover a line for
// its equation, what each term means, and the expected index at the pointer.
// Click or tap pins a card; a click elsewhere or Escape clears it.
//
// Each chart is laid out at its container's real pixel width (ResizeObserver),
// not scaled from a fixed viewBox, so type stays at full size on a phone and
// the plot fills a wide screen. Labels are placed greedily, a band's line
// names first, then the most notable models, and a label that would collide
// with another label or dot is left to the hover card instead of being drawn
// on top of something.
//
// Everything comes from the same rows and ScoreFit the table uses, and the
// page's Provider, Jurisdiction and Cost tier filters choose the dots: a group
// the filters empty has no chart. The lines and Scores stay the whole-catalog
// fit, so a filter changes what is drawn, never where a line sits.
"use client";

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import {
  blendedPrice,
  formatQualityBand,
  formatScore,
  formatUsd,
  qualityBand,
  type ScoreFit,
} from "@/lib/benchmark-grid";
import { COST_TIER_DEFS, COST_TIER_DOT, type CostTier, type ModelRow } from "@/lib/catalog-fields";
import type { Grouping } from "@/lib/models-prefs";
import {
  DOT_R,
  FRONTIER,
  LABEL_PX,
  LegendSwatch,
  FilterNote,
  pickPriceTicks,
  placeLabels,
  useWidth,
  type ChartFilter,
  type Label,
  type Spot,
} from "./chart-kit";
import { FloatingCard, type AnchorRect } from "./FloatingCard";
import { FrontierScope, ModelPointCard, PriceLineCard, topScoreSentence } from "./ScoreCards";

// Sign is also carried by direction and by the printed Score, so colour is
// never the only cue. Sky/orange stays distinct under protan and deutan
// vision, on both the light and the dark surface.
const ABOVE = "#0284c7";
const BELOW = "#ea580c";

// Priciest first: the table's order for cost-tier groups.
const TIER_ORDER: CostTier[] = ["very-high", "high", "medium", "low"];
const M = { top: 12, right: 18, bottom: 46, left: 46 };

interface Pt {
  row: ModelRow;
  x: number; // log10 blended price
  price: number;
  index: number;
  score: number;
  predicted: number; // its own tier's line at its price
}

// What one chart holds: a cost tier, or a ten-point AA Index band (named by
// its lower bound, as lib/benchmark-grid qualityBand gives it).
type ChartGroup = { kind: "tier"; tier: CostTier } | { kind: "quality"; band: number };

interface ChartSpec {
  key: string;
  group: ChartGroup;
  // The group's rows the filters keep. A tier's include its unmeasured models
  // (the caption counts them); a band's are the models it plots.
  members: ModelRow[];
}

// A cost tier's price line as one chart draws it, from log10 price a to b:
// edge to edge on the tier's own chart, across the prices of the tier's
// models on a quality band's.
interface Segment {
  tier: CostTier;
  a: number;
  b: number;
}

type Active = { kind: "point"; id: string } | { kind: "line"; tier: CostTier; x: number } | null;

// A dense chart labels its most notable models (frontier first, then the
// largest scores either way) and leaves the rest to the hover card: a crowd of
// labels is harder to read than none.
const MAX_LABELS = 9;

// The charts for one grouping, in the table's group order, and the rows they
// plot: measured, scored, and in a tier with a fitted line (two measured
// models or more), whichever grouping is chosen. Null when no tier has a line.
function chartSpecs(
  rows: readonly ModelRow[],
  fit: ScoreFit | null,
  grouping: Grouping,
): { plotted: ModelRow[]; charts: ChartSpec[] } | null {
  if (!fit) return null;
  const fitted = TIER_ORDER.filter((t) => (fit.tiers[t]?.n ?? 0) >= 2);
  if (fitted.length === 0) return null;
  const plotted = rows.filter(
    (r) => r.aa_index !== null && r.value_score !== null && fitted.includes(r.tier_cost),
  );
  if (grouping === "tier") {
    return {
      plotted,
      charts: fitted
        .filter((t) => plotted.some((r) => r.tier_cost === t))
        .map((t) => ({
          key: `tier-${t}`,
          group: { kind: "tier", tier: t },
          members: rows.filter((r) => r.tier_cost === t),
        })),
    };
  }
  const bands = [...new Set(plotted.map((r) => qualityBand(r.aa_index) as number))].sort((a, b) => b - a);
  return {
    plotted,
    charts: bands.map((band) => ({
      key: `band-${band}`,
      group: { kind: "quality", band },
      members: plotted.filter((r) => qualityBand(r.aa_index) === band),
    })),
  };
}

function ScoreChart({
  group,
  members,
  fit,
  byId,
}: {
  group: ChartGroup;
  members: ModelRow[];
  fit: ScoreFit;
  // Every row in the frontier's pool by id, for the model that beats a dot's
  // model (it may sit in a group the chart leaves to another chart, or one
  // the Cost tier filter hides).
  byId: Map<string, ModelRow>;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const width = useWidth(wrap);
  const [active, setActive] = useState<Active>(null);
  const pinned = useRef(false);
  const pointer = useRef("mouse");
  const byBand = group.kind === "quality";
  const title = byBand ? `AA Index ${formatQualityBand(group.band)}` : `${COST_TIER_DEFS[group.tier].label} cost`;

  // A tier's line: the expected AA Index at a log10 price.
  const lineY = useCallback((tier: CostTier, x: number) => fit.tiers[tier].intercept + fit.slope * x, [fit]);

  const pts: Pt[] = useMemo(
    () =>
      members
        .filter((r) => r.aa_index !== null && r.value_score !== null && fit.tiers[r.tier_cost])
        .map((r) => {
          const price = blendedPrice(r.input_price_per_1m, r.output_price_per_1m);
          const x = Math.log10(price);
          return {
            row: r,
            x,
            price,
            index: r.aa_index as number,
            score: r.value_score as number,
            predicted: lineY(r.tier_cost, x),
          };
        })
        .sort((a, b) => a.x - b.x || b.index - a.index),
    [members, fit, lineY],
  );
  // The caption's price ranges, over the plotted models: output (which sets
  // the tier) and blended (the x axis).
  const outs = pts.map((p) => p.row.output_price_per_1m);
  const blends = pts.map((p) => p.price);
  const range = (lo: number, hi: number) =>
    lo === hi ? formatUsd(lo) : `${formatUsd(lo)}–${formatUsd(hi)}`;
  // When the top score at this chart's prices belongs to a model outside it,
  // the chart names it: each tier's Scores average zero, so the words carry
  // what the lines leave out.
  const note = topScoreSentence(pts.map((p) => p.row), byId, "a dot");

  const height = width > 0 && width < 480 ? 340 : 320;
  const plotW = Math.max(40, width - M.left - M.right);
  const plotH = height - M.top - M.bottom;

  const xs = pts.map((p) => p.x);
  const pad = Math.max(0.09, (Math.max(...xs) - Math.min(...xs)) * 0.14);
  const x0 = Math.min(...xs) - pad;
  const x1 = Math.max(...xs) + pad;

  // The lines this chart draws, cheapest first. On a band's chart each runs a
  // little past its tier's end models, so every stem meets it inside its ends
  // and a tier with one model still gets a stub to read, but no further than
  // halfway to the next tier's models: neighbouring lines and tie bands meet
  // instead of overlapping.
  const segments: Segment[] = useMemo(() => {
    if (group.kind === "tier") return [{ tier: group.tier, a: x0, b: x1 }];
    const spans = TIER_ORDER.flatMap((tier) => {
      const tx = pts.filter((p) => p.row.tier_cost === tier).map((p) => p.x);
      return tx.length === 0 ? [] : [{ tier, lo: Math.min(...tx), hi: Math.max(...tx) }];
    }).sort((p, q) => p.lo - q.lo);
    const reach = (x1 - x0) * 0.04;
    return spans.map((s, i) => {
      const prev = spans[i - 1];
      const next = spans[i + 1];
      const a = prev && prev.hi < s.lo ? Math.max(s.lo - reach, (prev.hi + s.lo) / 2) : s.lo - reach;
      const b = next && s.hi < next.lo ? Math.min(s.hi + reach, (s.hi + next.lo) / 2) : s.hi + reach;
      return { tier: s.tier, a: Math.max(x0, a), b: Math.min(x1, b) };
    });
  }, [group, pts, x0, x1]);

  // The y range: every dot, and every line's two ends. A tier's chart keeps
  // its whole tie band in view too; a band's models can sit well above or
  // below their tiers' lines, so its tie bands run off the plot where they
  // must and the room goes to the dots and stems.
  const margin = byBand ? 0 : fit.sigma;
  const yVals = [
    ...pts.map((p) => p.index),
    ...segments.flatMap((s) => [
      lineY(s.tier, s.a) - margin,
      lineY(s.tier, s.a) + margin,
      lineY(s.tier, s.b) - margin,
      lineY(s.tier, s.b) + margin,
    ]),
  ];
  const rawLo = Math.min(...yVals);
  const rawHi = Math.max(...yVals);
  const step = rawHi - rawLo > 45 ? 10 : 5;
  const yLo = Math.max(0, Math.floor((rawLo - 1) / step) * step);
  const yHi = Math.min(100, Math.ceil((rawHi + 1) / step) * step);
  const sx = useCallback((x: number) => M.left + ((x - x0) / (x1 - x0)) * plotW, [x0, x1, plotW]);
  const sy = useCallback(
    (y: number) => M.top + plotH - ((y - yLo) / (yHi - yLo)) * plotH,
    [yLo, yHi, plotH],
  );

  const yTicks: number[] = [];
  for (let v = yLo; v <= yHi; v += step) yTicks.push(v);

  // x ticks: round prices, thinned so no two labels touch (chart-kit).
  const xTicks = useMemo(
    () => (width === 0 ? [] : pickPriceTicks(x0, x1, sx, M.left, plotW)),
    [width, x0, x1, sx, plotW],
  );

  const labels = useMemo(() => {
    if (width === 0) return new Map<string, Label>();
    // A band's chart names each line first, since a stem reads against its
    // own tier's line. The name runs along its own line on the side the line
    // leaves open (a rising line: under it from its left end, or over it
    // ending at its right end, else either way from its middle, else centred
    // under or over the middle), so it never sits past the line's end beside
    // a neighbouring tier's line. A line's name keeps no clearance of its own.
    const named = byBand ? segments : [];
    // The open side from each end: under a rising line from its left end and
    // over it from its right end; the other way round on a falling one.
    const [fromLeft, fromRight]: Spot[] =
      fit.slope >= 0 ? ["below-right", "above-left"] : ["above-right", "below-left"];
    return placeLabels(
      [
        ...named.map((s) => {
          const mid = (s.a + s.b) / 2;
          const at = (x: number) => ({ cx: sx(x), cy: sy(lineY(s.tier, x)) });
          return {
            id: `tier-${s.tier}`,
            ...at(mid),
            text: `${COST_TIER_DEFS[s.tier].label} tier`,
            priority: 1000,
            dot: false,
            anchors: [
              { ...at(s.a), spots: [fromLeft] },
              { ...at(s.b), spots: [fromRight] },
              { ...at(mid), spots: [fromLeft, fromRight, "below", "above"] },
            ],
          };
        }),
        ...pts.map((p) => ({
          id: p.row.id,
          cx: sx(p.x),
          cy: sy(p.index),
          text: `${p.row.name} ${formatScore(p.score)}`,
          priority: Math.abs(p.score) + (p.row.value_frontier ? 100 : 0),
        })),
      ],
      { x: M.left + 2, y: M.top + 2, w: plotW - 4, h: plotH - 4 },
      named.length + Math.max(3, Math.min(MAX_LABELS, Math.floor(plotW / 60))),
    );
  }, [byBand, segments, pts, width, sx, sy, lineY, fit, plotW, plotH]);

  const clear = useCallback(() => {
    pinned.current = false;
    setActive(null);
  }, []);

  // A pinned card clears on a click or tap anywhere outside this chart, or Escape.
  useEffect(() => {
    if (!active) return;
    const away = (e: PointerEvent) => {
      if (pinned.current && svgRef.current && !svgRef.current.contains(e.target as Node)) clear();
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") clear();
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [active, clear]);

  // The log10 price under the pointer, held to the line's own span.
  const xAt = (clientX: number, s: Segment): number => {
    const r = svgRef.current!.getBoundingClientRect();
    const x = x0 + ((clientX - r.left - M.left) / plotW) * (x1 - x0);
    return Math.min(s.b, Math.max(s.a, x));
  };

  const getAnchor = (): AnchorRect | null => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r || !active) return null;
    if (active.kind === "point") {
      const p = pts.find((q) => q.row.id === active.id);
      if (!p) return null;
      return { left: r.left + sx(p.x) - 9, top: r.top + sy(p.index) - 9, width: 18, height: 18 };
    }
    return {
      left: r.left + sx(active.x) - 6,
      top: r.top + sy(lineY(active.tier, active.x)) - 6,
      width: 12,
      height: 12,
    };
  };

  const activePoint = active?.kind === "point" ? pts.find((p) => p.row.id === active.id) : undefined;
  const clipId = byBand ? `plot-band-${group.band}` : `plot-tier-${group.tier}`;
  const tieBand = (s: Segment) => {
    const top = `${sx(s.a)},${sy(lineY(s.tier, s.a) + fit.sigma)} ${sx(s.b)},${sy(lineY(s.tier, s.b) + fit.sigma)}`;
    const bottom = `${sx(s.b)},${sy(lineY(s.tier, s.b) - fit.sigma)} ${sx(s.a)},${sy(lineY(s.tier, s.a) - fit.sigma)}`;
    return `${top} ${bottom}`;
  };
  // With a dot active, the other tiers' lines step back: its own line is the
  // one its Score is read from.
  const lineDim = (tier: CostTier) => activePoint !== undefined && activePoint.row.tier_cost !== tier;
  const plural = (n: number) => `${n} ${n === 1 ? "model" : "models"}`;
  const tierNames = segments.map((s) => COST_TIER_DEFS[s.tier].label).join(", ");

  return (
    <figure
      className="min-w-0 rounded-lg border border-brand-slate-200 bg-white px-4 pb-3 pt-3.5 dark:border-brand-slate-700 dark:bg-brand-slate-900"
      data-testid="score-chart"
      data-grouping={group.kind}
      data-tier={group.kind === "tier" ? group.tier : undefined}
      data-band={group.kind === "quality" ? String(group.band) : undefined}
    >
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <span className="inline-flex items-center gap-2 text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">
          {group.kind === "tier" && (
            <span className={"inline-block h-2.5 w-2.5 rounded-full " + COST_TIER_DOT[group.tier]} />
          )}
          {title}
        </span>
        <span className="text-xs tabular-nums text-brand-slate-500 dark:text-brand-slate-400">
          <span className="whitespace-nowrap">
            {pts.length === members.length
              ? plural(pts.length)
              : `${pts.length} of ${members.length} models measured`}
          </span>
          {" · "}
          <span className="whitespace-nowrap">
            output {range(Math.min(...outs), Math.max(...outs))}
          </span>
          {" · "}
          <span className="whitespace-nowrap">
            blended {range(Math.min(...blends), Math.max(...blends))} per 1M
          </span>
        </span>
      </figcaption>
      {note && (
        <p className="mt-1 text-xs font-medium text-emerald-700 dark:text-emerald-300" data-testid="chart-beaten">
          {note}
        </p>
      )}

      <div ref={wrap} className="mt-2 w-full" style={{ height }}>
        {width > 0 && (
          <svg
            ref={svgRef}
            width={width}
            height={height}
            role="group"
            aria-label={
              byBand
                ? `${title}: ${plural(pts.length)} plotted by blended price against AA Intelligence Index, with the price line of each cost tier among them (${tierNames}). Each model's Score is its vertical distance from its own tier's line.`
                : `${title}: ${pts.length} models plotted by blended price against AA Intelligence Index, with the tier's price line. Each model's Score is its vertical distance from the line.`
            }
            className="block touch-manipulation select-none text-brand-slate-400 dark:text-brand-slate-500"
            onPointerDown={(e) => {
              if (e.target === e.currentTarget) clear();
            }}
          >
            <defs>
              <clipPath id={clipId}>
                <rect x={M.left} y={M.top} width={plotW} height={plotH} />
              </clipPath>
            </defs>

            {/* Grid and y axis */}
            {yTicks.map((v) => (
              <g key={v}>
                <line
                  x1={M.left}
                  x2={M.left + plotW}
                  y1={sy(v)}
                  y2={sy(v)}
                  stroke="currentColor"
                  strokeOpacity={v === yLo ? 0.55 : 0.2}
                />
                <text
                  x={M.left - 8}
                  y={sy(v) + 4}
                  textAnchor="end"
                  fontSize={11.5}
                  className="fill-brand-slate-500 tabular-nums dark:fill-brand-slate-400"
                >
                  {v}
                </text>
              </g>
            ))}

            {/* x axis ticks */}
            {xTicks.map(({ v, px }) => (
              <g key={v}>
                <line x1={px} x2={px} y1={M.top + plotH} y2={M.top + plotH + 5} stroke="currentColor" strokeOpacity={0.55} />
                <text
                  x={px}
                  y={M.top + plotH + 18}
                  textAnchor="middle"
                  fontSize={11.5}
                  className="fill-brand-slate-500 tabular-nums dark:fill-brand-slate-400"
                >
                  {formatUsd(v)}
                </text>
              </g>
            ))}

            <g clipPath={`url(#${clipId})`}>
              {/* ±σ tie bands, then the price lines */}
              {segments.map((s) => (
                <polygon
                  key={`band-${s.tier}`}
                  points={tieBand(s)}
                  opacity={lineDim(s.tier) ? 0.4 : 1}
                  className="fill-brand-slate-900/[0.05] dark:fill-white/[0.06]"
                />
              ))}
              {segments.map((s) => (
                <line
                  key={`line-${s.tier}`}
                  x1={sx(s.a)}
                  y1={sy(lineY(s.tier, s.a))}
                  x2={sx(s.b)}
                  y2={sy(lineY(s.tier, s.b))}
                  strokeWidth={active?.kind === "line" && active.tier === s.tier ? 3 : 2}
                  strokeLinecap={byBand ? "round" : undefined}
                  opacity={lineDim(s.tier) ? 0.3 : 1}
                  className="stroke-brand-slate-700 dark:stroke-brand-slate-200"
                />
              ))}
            </g>

            {/* Wide invisible target along each line: hover for its equation. */}
            {segments.map((s) => {
              const tier = COST_TIER_DEFS[s.tier].label;
              const t = fit.tiers[s.tier];
              return (
                <line
                  key={`target-${s.tier}`}
                  x1={sx(s.a)}
                  y1={sy(lineY(s.tier, s.a))}
                  x2={sx(s.b)}
                  y2={sy(lineY(s.tier, s.b))}
                  stroke="transparent"
                  strokeWidth={18}
                  tabIndex={0}
                  role="button"
                  aria-label={`${tier}-cost price line: expected AA Index = ${t.intercept.toFixed(1)} + ${fit.slope.toFixed(1)} × log10(blended price)`}
                  data-testid="score-chart-line"
                  data-tier={s.tier}
                  className="cursor-crosshair outline-none"
                  onPointerMove={(e) => {
                    if (pinned.current || e.pointerType !== "mouse") return;
                    setActive({ kind: "line", tier: s.tier, x: xAt(e.clientX, s) });
                  }}
                  onPointerLeave={(e) => {
                    if (!pinned.current && e.pointerType === "mouse") setActive(null);
                  }}
                  onClick={(e) => {
                    pinned.current = true;
                    setActive({ kind: "line", tier: s.tier, x: xAt(e.clientX, s) });
                  }}
                  onFocus={(e) => {
                    if (e.currentTarget.matches(":focus-visible")) {
                      setActive({ kind: "line", tier: s.tier, x: Math.min(s.b, Math.max(s.a, t.meanLogPrice)) });
                    }
                  }}
                  onBlur={() => {
                    if (!pinned.current) setActive(null);
                  }}
                />
              );
            })}

            {/* Stems: the Score, drawn as distance from the model's own tier's line. */}
            {pts.map((p) => {
              const dim = activePoint && activePoint !== p;
              return (
                <line
                  key={`stem-${p.row.id}`}
                  x1={sx(p.x)}
                  y1={sy(p.predicted)}
                  x2={sx(p.x)}
                  y2={sy(p.index)}
                  stroke={p.score >= 0 ? ABOVE : BELOW}
                  strokeWidth={activePoint === p ? 2.5 : 1.5}
                  strokeOpacity={dim ? 0.15 : 0.55}
                  pointerEvents="none"
                  data-testid="score-chart-stem"
                  data-model-id={p.row.id}
                  data-tier={p.row.tier_cost}
                />
              );
            })}

            {/* Dots */}
            {pts.map((p) => {
              const isActive = activePoint === p;
              const dim = activePoint && !isActive;
              const cx = sx(p.x);
              const cy = sy(p.index);
              return (
                <g key={p.row.id} opacity={dim ? 0.3 : 1} pointerEvents="none">
                  {p.row.value_frontier && (
                    <circle cx={cx} cy={cy} r={DOT_R + 3.5} fill="none" stroke={FRONTIER} strokeWidth={2} />
                  )}
                  <circle
                    cx={cx}
                    cy={cy}
                    r={isActive ? DOT_R + 1.5 : DOT_R}
                    fill={p.score >= 0 ? ABOVE : BELOW}
                    strokeWidth={isActive ? 2.5 : 1.5}
                    className={isActive ? "stroke-brand-slate-900 dark:stroke-white" : "stroke-white dark:stroke-brand-slate-900"}
                  />
                </g>
              );
            })}

            {/* Labels, with a halo so a line or band under the text never hurts
                it: the lines' names (a band's chart), then the models'. */}
            {segments.map((s) => {
              const l = labels.get(`tier-${s.tier}`);
              if (!l) return null;
              return (
                <g
                  key={`label-tier-${s.tier}`}
                  opacity={lineDim(s.tier) ? 0.3 : 1}
                  pointerEvents="none"
                  data-testid="score-chart-line-label"
                  data-tier={s.tier}
                >
                  <rect
                    x={l.box.x}
                    y={l.box.y}
                    width={l.box.w}
                    height={l.box.h}
                    rx={3}
                    className="fill-white/90 dark:fill-brand-slate-900/90"
                  />
                  <text
                    x={l.x}
                    y={l.y}
                    textAnchor={l.anchor}
                    fontSize={LABEL_PX}
                    className="fill-brand-slate-500 italic dark:fill-brand-slate-400"
                  >
                    {l.text}
                  </text>
                </g>
              );
            })}
            {pts.map((p) => {
              const l = labels.get(p.row.id);
              if (!l) return null;
              const dim = activePoint && activePoint !== p;
              return (
                <g key={`label-${p.row.id}`} opacity={dim ? 0.3 : 1} pointerEvents="none">
                  <rect
                    x={l.box.x}
                    y={l.box.y}
                    width={l.box.w}
                    height={l.box.h}
                    rx={3}
                    className="fill-white/90 dark:fill-brand-slate-900/90"
                  />
                  <text
                    x={l.x}
                    y={l.y}
                    textAnchor={l.anchor}
                    fontSize={LABEL_PX}
                    fontWeight={500}
                    className="fill-brand-slate-700 tabular-nums dark:fill-brand-slate-200"
                  >
                    {l.text}
                  </text>
                </g>
              );
            })}

            {/* The line readout marker */}
            {active?.kind === "line" && (
              <circle
                cx={sx(active.x)}
                cy={sy(lineY(active.tier, active.x))}
                r={5}
                strokeWidth={2.5}
                pointerEvents="none"
                className="fill-white stroke-brand-accent dark:fill-brand-slate-900"
              />
            )}

            {/* Hit targets on top: bigger than the dots, easy to hover and tap. */}
            {pts.map((p) => (
              <circle
                key={`hit-${p.row.id}`}
                cx={sx(p.x)}
                cy={sy(p.index)}
                r={12}
                fill="transparent"
                tabIndex={0}
                role="button"
                aria-label={`${p.row.name}: Score ${formatScore(p.score)}, AA Index ${p.index}, input ${formatUsd(p.row.input_price_per_1m)} and output ${formatUsd(p.row.output_price_per_1m)} per 1M tokens`}
                data-testid="score-chart-point"
                data-model-id={p.row.id}
                className="cursor-pointer outline-none"
                onPointerEnter={(e) => {
                  pointer.current = e.pointerType;
                  if (e.pointerType === "mouse" && !pinned.current) setActive({ kind: "point", id: p.row.id });
                }}
                onPointerLeave={(e) => {
                  if (e.pointerType === "mouse" && !pinned.current) setActive(null);
                }}
                onPointerDown={(e) => {
                  pointer.current = e.pointerType;
                }}
                onClick={() => {
                  if (pinned.current && active?.kind === "point" && active.id === p.row.id) {
                    clear();
                    return;
                  }
                  pinned.current = true;
                  setActive({ kind: "point", id: p.row.id });
                }}
                onFocus={(e) => {
                  if (e.currentTarget.matches(":focus-visible")) setActive({ kind: "point", id: p.row.id });
                }}
                onBlur={() => {
                  if (!pinned.current) setActive(null);
                }}
              />
            ))}

            {/* Axis titles */}
            <text
              x={M.left + plotW / 2}
              y={height - 6}
              textAnchor="middle"
              fontSize={11.5}
              className="fill-brand-slate-500 dark:fill-brand-slate-400"
            >
              Blended price, $ per 1M tokens (log scale)
            </text>
            <text
              transform={`translate(13 ${M.top + plotH / 2}) rotate(-90)`}
              textAnchor="middle"
              fontSize={11.5}
              className="fill-brand-slate-500 dark:fill-brand-slate-400"
            >
              AA Intelligence Index
            </text>
          </svg>
        )}
      </div>

      {active && (
        <FloatingCard getAnchor={getAnchor} placement="side" testId="chart-card">
          {active.kind === "point" && activePoint ? (
            <ModelPointCard
              model={activePoint.row}
              fit={fit}
              leader={
                activePoint.row.value_beaten_by
                  ? (byId.get(activePoint.row.value_beaten_by) ?? null)
                  : null
              }
            />
          ) : active.kind === "line" ? (
            <PriceLineCard tier={active.tier} fit={fit} atPrice={10 ** active.x} />
          ) : null}
        </FloatingCard>
      )}
    </figure>
  );
}

export function ScoreCharts({
  rows,
  pool,
  fit,
  filter,
  grouping,
}: {
  // The rows the page's filters keep: the dots.
  rows: ModelRow[];
  // The rows the Provider and Jurisdiction filters keep (the frontier's pool),
  // for the models the cards and notes name.
  pool: ModelRow[];
  fit: ScoreFit | null;
  // The active filters; null when the page shows every model.
  filter: ChartFilter | null;
  // The table's Group by choice: one chart per quality band or per cost tier.
  grouping: Grouping;
}) {
  const scope = useContext(FrontierScope);
  const specs = useMemo(() => chartSpecs(rows, fit, grouping), [rows, fit, grouping]);
  const byId = useMemo(() => new Map(pool.map((r) => [r.id, r])), [pool]);
  if (!fit || !specs) return null;
  const { plotted, charts } = specs;
  const sigma = fit.sigma.toFixed(1);
  const byBand = grouping === "quality";

  return (
    <details
      open
      className="group rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40"
      data-testid="score-charts"
      data-grouping={grouping}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-5 py-3 text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100">
        {`What the Score means: AA Index against price, one chart per ${byBand ? "quality band" : "cost tier"}`}
        <span className="text-xs font-normal text-brand-slate-500 group-open:hidden dark:text-brand-slate-400">
          show
        </span>
        <span className="hidden text-xs font-normal text-brand-slate-500 group-open:inline dark:text-brand-slate-400">
          hide
        </span>
      </summary>

      <div className="space-y-4 border-t border-brand-slate-200 px-5 py-5 dark:border-brand-slate-700">
        <p className="max-w-4xl text-sm leading-6 text-brand-slate-600 dark:text-brand-slate-300" data-testid="score-charts-intro">
          Pricier models score higher on average, so &ldquo;is this model good?&rdquo; and
          &ldquo;is it good <em>for its price</em>?&rdquo; are different questions.{" "}
          {byBand ? (
            <>
              Each chart answers the second for one quality band, ten points of AA Index: every
              model sits at its blended price (across) and AA Intelligence Index (up), and each
              line, named for its cost tier, is what a model of that tier typically scores at each
              price, drawn across the tier&rsquo;s models in the band.
            </>
          ) : (
            <>
              Each chart answers the second for one cost tier: every model sits at its blended
              price (across) and AA Intelligence Index (up), and the line is what a model of that
              tier typically scores at each price.
            </>
          )}{" "}
          The blended price is (3&nbsp;&times;&nbsp;input + 1&nbsp;&times;&nbsp;output)
          &divide;&nbsp;4, one price per model, which is why it reads below the output prices
          that set the tier.{" "}
          <strong>
            A model&rsquo;s Score is its vertical distance from{" "}
            {byBand ? <>its own tier&rsquo;s line</> : "the line"}
          </strong>
          , in index points: above it (+) buys more intelligence than the price predicts, below it
          (&minus;) buys less.
          {byBand && (
            <>
              {" "}
              Because a band is chosen by AA Index, the top bands gather models that sit above
              their lines and the bottom bands models that sit below them; within one chart, the
              highest Score is the best buy at that level.
            </>
          )}{" "}
          The table&rsquo;s Group by switch groups these charts too.
        </p>

        {filter && (
          <FilterNote filter={filter} testId="score-charts-filter">
            {plotted.length === 0
              ? "No measured model matches, so there is nothing to plot."
              : `${plotted.length} measured ${plotted.length === 1 ? "model" : "models"} in ${charts.length} ${charts.length === 1 ? "chart" : "charts"}.`}{" "}
            The price lines and Scores are still fitted over the whole catalog, so a filter changes
            which dots are drawn, never where a line sits.
          </FilterNote>
        )}

        <ul className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-brand-slate-600 dark:text-brand-slate-300">
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <circle cx={11} cy={7} r={5} fill={ABOVE} />
            </LegendSwatch>
            Above the line (+)
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <circle cx={11} cy={7} r={5} fill={BELOW} />
            </LegendSwatch>
            Below the line (&minus;)
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <circle cx={11} cy={7} r={5.5} fill="none" stroke={FRONTIER} strokeWidth={2} />
            </LegendSwatch>
            Cost/quality frontier ({scope ? `${scope} models` : "whole catalog"})
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <line x1={1} y1={11} x2={21} y2={3} strokeWidth={2} className="stroke-brand-slate-700 dark:stroke-brand-slate-200" />
            </LegendSwatch>
            {byBand ? "Expected AA Index for the price, one line per cost tier" : "Expected AA Index for the price"}
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <rect x={1} y={2} width={20} height={10} rx={2} className="fill-brand-slate-900/[0.08] dark:fill-white/[0.1]" />
            </LegendSwatch>
            ±{sigma} tie band
          </li>
          <li className="text-brand-slate-500 dark:text-brand-slate-400">
            Hover or tap any dot or line for its numbers.
          </li>
        </ul>

        {charts.length > 0 && (
          <div className={"grid grid-cols-1 gap-4" + (charts.length > 1 ? " lg:grid-cols-2" : "")}>
            {charts.map((c) => (
              <ScoreChart key={c.key} group={c.group} members={c.members} fit={fit} byId={byId} />
            ))}
          </div>
        )}

        <p className="text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
          One least-squares fit over all {fit.n} AA-measured models: AA Index = α<sub>tier</sub>
          {" "}+ β&thinsp;×&thinsp;log<sub>10</sub>(blended price), with a separate intercept
          α for each cost tier and one shared slope β&nbsp;=&nbsp;{fit.slope.toFixed(1)} index
          points per 10&times; price (R&sup2;&nbsp;{fit.r2.toFixed(2)}, residual
          σ&nbsp;{sigma}).{byBand && " The shared slope keeps the tier lines on a band's chart parallel."}{" "}
          A dot inside the shaded band is level with its line: treat scores that close together as
          a tie, not a ranking.{" "}
          <strong className="text-brand-slate-700 dark:text-brand-slate-200">
            The green ring marks the cost/quality frontier: a model that scores higher than every
            other {scope ? `${scope} model` : "model in the catalog"} at its price or less.
          </strong>{" "}
          {byBand
            ? "When the top score at a band's prices belongs to a model outside the chart, the chart names that model under its title."
            : "When the top score at a tier's prices belongs to a cheaper tier, that tier's chart names the model under its title."}{" "}
          The frontier chart above plots every model together and draws the frontier as a line.
        </p>
      </div>
    </details>
  );
}
