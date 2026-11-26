// web/components/ScoreCharts.tsx
//
// The Score column, drawn: one zoom chart per cost tier, all four on screen.
// Each plots the tier's measured models at their effort-adjusted blended price
// (x, log scale) and AA Intelligence Index (y) against the single continuous
// market price line, the ±σ tie band, and a stem from the line to each model —
// the stem's length IS the model's Score.
//
// The charts stay one per cost tier whichever way the table is grouped, zooming
// into each cost tier along the same continuous market price line. Grouped by
// quality, the panel says so and points to the frontier chart, which shades
// the quality bands (FrontierChart).
//
// Interactive: hover (mouse), tap (touch), or tab to (keyboard) any dot for a
// card with the model's name, Score, AA Index and prices; hover the line for
// its equation, what each term means, and the expected index at the pointer.
// Click or tap pins a card; a click elsewhere or Escape clears it.
//
// Each chart is laid out at its container's real pixel width (ResizeObserver),
// not scaled from a fixed viewBox, so type stays at full size on a phone and
// the plot fills a wide screen. Labels are placed greedily, most notable model
// first, and a label that would collide with another label or dot is left to
// the hover card instead of being drawn on top of something.
//
// Everything comes from the same rows and ScoreFit the table uses, and the
// page's Provider, Jurisdiction, Weights and Cost tier filters choose the
// dots: a tier the filters empty has no chart. The lines and Scores stay the whole-catalog
// fit, so a filter changes what is drawn, never where the line sits.
"use client";

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import {
  formatScore,
  formatUsd,
  sigmaAt,
  type ScoreFit,
} from "@/lib/benchmark-grid";
import { COST_TIER_DEFS, COST_TIER_DOT, type CostTier, type ModelRow } from "@/lib/catalog-fields";
import { headlinePrice } from "@/lib/pick-effort";
import type { Grouping } from "@/lib/models-prefs";
import {
  DOT_R,
  FRONTIER,
  LABEL_PX,
  LegendSwatch,
  FilterNote,
  pickPriceTicks,
  placeLabels,
  fitTitle,
  PRICE_AXIS_TITLES,
  useWidth,
  type ChartFilter,
  type Label,
} from "./chart-kit";
import { FloatingCard, type AnchorRect } from "./FloatingCard";
import { FrontierScope, ModelPointCard, PriceLineCard } from "./ScoreCards";

// Sign is also carried by direction and by the printed Score, so colour is
// never the only cue. Sky/orange stays distinct under protan and deutan
// vision, on both the light and the dark surface.
const ABOVE = "#0284c7";
const BELOW = "#ea580c";

const TIER_ORDER: CostTier[] = ["very-high", "high", "medium", "low"];
const M = { top: 12, right: 18, bottom: 46, left: 46 };

interface Pt {
  row: ModelRow;
  x: number; // log10 blended price
  price: number;
  index: number;
  score: number;
  predicted: number;
}

type Active = { kind: "point"; id: string } | { kind: "line"; x: number } | null;

// A dense tier labels its most notable models (frontier first, then the
// largest scores either way) and leaves the rest to the hover card: a crowd of
// labels is harder to read than none.
const MAX_LABELS = 9;

function TierChart({
  tier,
  rows,
  fit,
  byId,
}: {
  tier: CostTier;
  rows: ModelRow[];
  fit: ScoreFit;
  // Every row in the frontier's pool by id, for the model that beats a dot's
  // model (it may sit in a tier the Cost tier filter hides).
  byId: Map<string, ModelRow>;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const width = useWidth(wrap);
  const [active, setActive] = useState<Active>(null);
  const pinned = useRef(false);
  const pointer = useRef("mouse");
  const label = COST_TIER_DEFS[tier].label;

  const pts: Pt[] = useMemo(
    () =>
      rows
        // The charts show the fit through AA's measurements: an estimated
        // model's Score is in the table, not on the market line.
        .filter(
          (r) =>
            r.tier_cost === tier &&
            r.aa_index !== null &&
            r.value_score !== null &&
            r.aa_index_source !== "estimated" &&
            r.aa_index_source !== "inherited",
        )
        .map((r) => {
          const price = headlinePrice(r);
          const x = Math.log10(price);
          return {
            row: r,
            x,
            price,
            index: r.aa_index as number,
            score: r.value_score as number,
            predicted: fit.intercept + fit.slope * x,
          };
        })
        .sort((a, b) => a.x - b.x || b.index - a.index),
    [rows, tier, fit],
  );
  const inTier = rows.filter((r) => r.tier_cost === tier).length;
  // The caption's price ranges, over the plotted models: output (which sets
  // the tier) and blended (the x axis).
  const outs = pts.map((p) => p.row.output_price_per_1m);
  const blends = pts.map((p) => p.price);
  const range = (lo: number, hi: number) =>
    lo === hi ? formatUsd(lo) : `${formatUsd(lo)}–${formatUsd(hi)}`;

  const height = width > 0 && width < 480 ? 340 : 320;
  const plotW = Math.max(40, width - M.left - M.right);
  const plotH = height - M.top - M.bottom;

  const xs = pts.map((p) => p.x);
  const pad = Math.max(0.09, (Math.max(...xs) - Math.min(...xs)) * 0.14);
  const x0 = Math.min(...xs) - pad;
  const x1 = Math.max(...xs) + pad;
  const line = useCallback((x: number) => fit.intercept + fit.slope * x, [fit]);
  const sig0 = sigmaAt(fit, 10 ** x0) ?? fit.sigma;
  const sig1 = sigmaAt(fit, 10 ** x1) ?? fit.sigma;
  const yVals = [
    ...pts.map((p) => p.index),
    line(x0) - sig0,
    line(x0) + sig0,
    line(x1) - sig1,
    line(x1) + sig1,
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
    return placeLabels(
      pts.map((p) => ({
        id: p.row.id,
        cx: sx(p.x),
        cy: sy(p.index),
        text: `${p.row.name} ${formatScore(p.score)}`,
        priority: Math.abs(p.score - 50) + (p.row.value_frontier ? 100 : 0),
      })),
      { x: M.left + 2, y: M.top + 2, w: plotW - 4, h: plotH - 4 },
      Math.max(3, Math.min(MAX_LABELS, Math.floor(plotW / 60))),
    );
  }, [pts, width, sx, sy, plotW, plotH]);

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

  const xAt = (clientX: number): number => {
    const r = svgRef.current!.getBoundingClientRect();
    const frac = (clientX - r.left - M.left) / plotW;
    return x0 + Math.min(1, Math.max(0, frac)) * (x1 - x0);
  };

  const getAnchor = (): AnchorRect | null => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r || !active) return null;
    if (active.kind === "point") {
      const p = pts.find((q) => q.row.id === active.id);
      if (!p) return null;
      return { left: r.left + sx(p.x) - 9, top: r.top + sy(p.index) - 9, width: 18, height: 18 };
    }
    return { left: r.left + sx(active.x) - 6, top: r.top + sy(line(active.x)) - 6, width: 12, height: 12 };
  };

  const activePoint = active?.kind === "point" ? pts.find((p) => p.row.id === active.id) : undefined;
  const clipId = `plot-${tier}`;
  const bandSteps = 20;
  const bandXs = Array.from({ length: bandSteps + 1 }, (_, i) => x0 + ((x1 - x0) * i) / bandSteps);
  const bandTop = bandXs
    .map((x) => `${sx(x)},${sy(line(x) + (sigmaAt(fit, 10 ** x) ?? fit.sigma))}`)
    .join(" ");
  const bandBottom = [...bandXs]
    .reverse()
    .map((x) => `${sx(x)},${sy(line(x) - (sigmaAt(fit, 10 ** x) ?? fit.sigma))}`)
    .join(" ");

  return (
    <figure
      className="min-w-0 rounded-lg border border-brand-slate-200 bg-white px-4 pb-3 pt-3.5 dark:border-brand-slate-700 dark:bg-brand-slate-900"
      data-testid="score-chart"
      data-tier={tier}
    >
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <span className="inline-flex items-center gap-2 text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">
          <span className={"inline-block h-2.5 w-2.5 rounded-full " + COST_TIER_DOT[tier]} />
          {label} cost
        </span>
        <span className="text-xs tabular-nums text-brand-slate-500 dark:text-brand-slate-400">
          <span className="whitespace-nowrap">
            {pts.length === inTier
              ? `${pts.length} ${pts.length === 1 ? "model" : "models"}`
              : `${pts.length} of ${inTier} ${inTier === 1 ? "model" : "models"} measured`}
          </span>
          {" · "}
          <span className="whitespace-nowrap">
            output {range(Math.min(...outs), Math.max(...outs))}
          </span>
          {" · "}
          <span className="whitespace-nowrap">
            effort-adjusted {range(Math.min(...blends), Math.max(...blends))} per 1M
          </span>
        </span>
      </figcaption>

      <div ref={wrap} className="mt-2 w-full" style={{ height }}>
        {width > 0 && (
          <svg
            ref={svgRef}
            width={width}
            height={height}
            role="group"
            aria-label={`${label} cost: ${pts.length} ${pts.length === 1 ? "model" : "models"} plotted by blended price against AA Intelligence Index, with today's market price line. Each model's Value measures how far it sits above or below the line relative to the local spread.`}
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
              {/* Price-varying ±σ local spread ribbon */}
              <polygon
                points={`${bandTop} ${bandBottom}`}
                data-testid="score-chart-band"
                className="fill-brand-slate-900/[0.05] dark:fill-white/[0.06]"
              />
              {/* The continuous market price line */}
              <line
                x1={sx(x0)}
                y1={sy(line(x0))}
                x2={sx(x1)}
                y2={sy(line(x1))}
                strokeWidth={active?.kind === "line" ? 3 : 2}
                className="stroke-brand-slate-700 dark:stroke-brand-slate-200"
              />
            </g>

            {/* Wide invisible target along the line: hover for the equation. */}
            <line
              x1={sx(x0)}
              y1={sy(line(x0))}
              x2={sx(x1)}
              y2={sy(line(x1))}
              stroke="transparent"
              strokeWidth={18}
              tabIndex={0}
              role="button"
              aria-label={`Market price line: expected AA Index = ${fit.intercept.toFixed(1)} + ${fit.slope.toFixed(1)} × log10(blended price)`}
              data-testid="score-chart-line"
              className="cursor-crosshair outline-none"
              onPointerMove={(e) => {
                if (pinned.current || e.pointerType !== "mouse") return;
                setActive({ kind: "line", x: xAt(e.clientX) });
              }}
              onPointerLeave={(e) => {
                if (!pinned.current && e.pointerType === "mouse") setActive(null);
              }}
              onClick={(e) => {
                pinned.current = true;
                setActive({ kind: "line", x: xAt(e.clientX) });
              }}
              onFocus={(e) => {
                if (e.currentTarget.matches(":focus-visible")) setActive({ kind: "line", x: (x0 + x1) / 2 });
              }}
              onBlur={() => {
                if (!pinned.current) setActive(null);
              }}
            />

            {/* Stems: the Score, drawn as distance from the line. */}
            {pts.map((p) => {
              const dim = activePoint && activePoint !== p;
              return (
                <line
                  key={`stem-${p.row.id}`}
                  x1={sx(p.x)}
                  y1={sy(p.predicted)}
                  x2={sx(p.x)}
                  y2={sy(p.index)}
                  stroke={p.index >= p.predicted ? ABOVE : BELOW}
                  strokeWidth={activePoint === p ? 2.5 : 1.5}
                  strokeOpacity={dim ? 0.15 : 0.55}
                  pointerEvents="none"
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
                    fill={p.index >= p.predicted ? ABOVE : BELOW}
                    strokeWidth={isActive ? 2.5 : 1.5}
                    className={isActive ? "stroke-brand-slate-900 dark:stroke-white" : "stroke-white dark:stroke-brand-slate-900"}
                  />
                </g>
              );
            })}

            {/* Labels, with a halo so a line or band under the text never hurts it. */}
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
                cy={sy(line(active.x))}
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
                aria-label={`${p.row.name}: Value ${formatScore(p.score)}, AA Index ${p.index}, input ${formatUsd(p.row.input_price_per_1m)} and output ${formatUsd(p.row.output_price_per_1m)} per 1M tokens`}
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
              {fitTitle(PRICE_AXIS_TITLES, M.left + plotW / 2, width)}
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
            <PriceLineCard fit={fit} atPrice={10 ** active.x} />
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
  // The table's Group by choice. The charts are per cost tier either way;
  // grouped by quality, the panel says why.
  grouping: Grouping;
}) {
  const scope = useContext(FrontierScope);
  if (!fit) return null;
  // Every tier shares the single continuous market line, so any cost tier
  // with at least one measured model gets its zoom chart.
  const plotted = rows.filter(
    (r) =>
      r.aa_index !== null &&
      r.value_score !== null &&
      r.aa_index_source !== "estimated" &&
      r.aa_index_source !== "inherited",
  );
  const tiers = TIER_ORDER.filter((t) => plotted.some((r) => r.tier_cost === t));
  if (!filter && tiers.length === 0) return null;
  const byId = new Map(pool.map((r) => [r.id, r]));
  const sigma = fit.sigma.toFixed(1);

  return (
    <details
      open
      className="group rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40"
      data-testid="score-charts"
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-5 py-3 text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100">
        What Value means: AA Index against price, one chart per cost tier
        <span className="text-xs font-normal text-brand-slate-500 group-open:hidden dark:text-brand-slate-400">
          show
        </span>
        <span className="hidden text-xs font-normal text-brand-slate-500 group-open:inline dark:text-brand-slate-400">
          hide
        </span>
      </summary>

      <div className="space-y-4 border-t border-brand-slate-200 px-5 py-5 dark:border-brand-slate-700">
        <p className="max-w-4xl text-sm leading-6 text-brand-slate-600 dark:text-brand-slate-300">
          Pricier models score higher on average, so &ldquo;is this model good?&rdquo; and
          &ldquo;is it good <em>for its price</em>?&rdquo; are different questions. Each chart zooms
          into one cost tier along the market&rsquo;s continuous price line: every model sits at its
          effort-adjusted blended price (across) and AA Intelligence Index (up), and the line is
          what the market typically scores at each price. Output is scaled by the tokens drawn at
          the model&rsquo;s headline Effort, (3&nbsp;&times;&nbsp;input + m&nbsp;&times;&nbsp;output)&nbsp;&divide;&nbsp;4.{" "}
          <strong>A model&rsquo;s Value (0&ndash;100%)</strong> turns that vertical gap into a
          price-adjusted market percentile scaled by the local spread ribbon: 50% sits right on
          today&rsquo;s line, above 50% buys more intelligence than the price predicts, and below
          50% buys less.
        </p>

        {grouping === "quality" && (
          <p
            className="rounded-lg border border-brand-accent/30 bg-brand-accent/5 px-3 py-2 text-xs leading-5 text-brand-slate-700 dark:bg-brand-accent/10 dark:text-brand-slate-200"
            data-testid="score-charts-grouping-note"
          >
            <strong className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">
              The table is grouped by quality; these charts stay one per cost tier.
            </strong>{" "}
            Each chart zooms into one tier&rsquo;s price range along the same continuous market
            price line so every dot and label reads clearly. The frontier chart above shades the
            table&rsquo;s quality bands.
          </p>
        )}

        {filter && (
          <FilterNote filter={filter} testId="score-charts-filter">
            {plotted.length === 0
              ? "No measured model matches, so there is nothing to plot."
              : `${plotted.length} measured ${plotted.length === 1 ? "model" : "models"} in ${tiers.length} ${tiers.length === 1 ? "chart" : "charts"}.`}{" "}
            The market price line and Value stay fitted over the whole catalog, so a filter narrows
            the dots shown while keeping the line fixed.
          </FilterNote>
        )}

        <ul className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-brand-slate-600 dark:text-brand-slate-300">
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <circle cx={11} cy={7} r={5} fill={ABOVE} />
            </LegendSwatch>
            Above today’s line (&gt;50%)
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <circle cx={11} cy={7} r={5} fill={BELOW} />
            </LegendSwatch>
            Below today’s line (&lt;50%)
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
            Today’s expected AA Index for the price
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <polygon points="1,2 21,5 21,11 1,14" className="fill-brand-slate-900/[0.08] dark:fill-white/[0.1]" />
            </LegendSwatch>
            ±σ local spread (±{fit.sigmaMin.toFixed(1)}–{fit.sigmaMax.toFixed(1)})
          </li>
          <li className="text-brand-slate-500 dark:text-brand-slate-400">
            Hover or tap any dot or line for its numbers.
          </li>
        </ul>

        {tiers.length > 0 && (
          <div className={"grid grid-cols-1 gap-4" + (tiers.length > 1 ? " lg:grid-cols-2" : "")}>
            {tiers.map((t) => (
              <TierChart key={t} tier={t} rows={rows} fit={fit} byId={byId} />
            ))}
          </div>
        )}

        <p className="text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
          One continuous Huber-robust{fit.vintageAdjusted ? ", vintage-controlled" : ""} fit over
          all {fit.n} AA-measured models: AA Index = α + β&thinsp;×&thinsp;log<sub>10</sub>
          (effort-adjusted price), anchored at today&rsquo;s generation with α&nbsp;=&nbsp;
          {fit.intercept.toFixed(1)} at $1/1M and slope β&nbsp;=&nbsp;{fit.slope.toFixed(1)} index
          points per 10&times; price (R&sup2;&nbsp;{fit.r2.toFixed(2)}, midpoint σ&nbsp;{sigma},
          local ±σ narrowing from ±{fit.sigmaMax.toFixed(1)} to ±{fit.sigmaMin.toFixed(1)}). A dot
          inside the shaded ribbon sits close to today&rsquo;s market line.{" "}
          <strong className="text-brand-slate-700 dark:text-brand-slate-200">
            The green ring marks the cost/quality frontier: a model that scores higher than every
            other {scope ? `${scope} model` : "model in the catalog"} at its price or less.
          </strong>{" "}
          The frontier chart above plots every model together and draws the frontier as a line.
        </p>
      </div>
    </details>
  );
}
