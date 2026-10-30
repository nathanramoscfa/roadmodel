// web/components/QualityCharts.tsx
//
// The frontier, one quality band at a time: shown while the table is grouped
// by quality, one chart per band (the table's ten-point AA Index groups, best
// band first). Each zooms into its band's row of the frontier chart: the
// band's models at their blended price (x, log scale) and AA Intelligence
// Index (y), green when on the cost/quality frontier and grey when beaten, and
// the dotted green line, the top AA Index each price buys. A model above the
// band that beats one of its models is marked in a strip above the plot at
// its price, so a band with no green model still shows what beats it.
//
// No fitted line and no new figure: green and grey are the table's ring, and
// each card is the frontier chart's, naming the model that scores higher at
// the same price or less. (A price-for-quality line was tried and dropped:
// most of its verdicts sat inside its own noise, and it contradicted the
// Score on a third of the models. The Score has its own charts, one per cost
// tier, under Group by -> Cost tier.)
//
// Interactive like the frontier chart: hover (mouse), tap (touch) or tab to
// (keyboard) any dot for its card, or the green line for the top score at
// that price. Click or tap pins a card; a click elsewhere or Escape clears
// it. Laid out at the container's real pixel width, with labels placed
// greedily, frontier models first (chart-kit).
//
// The page's filters (lib/catalog-filter): the dots are the models all of
// them keep, a band they empty has no chart, and the frontier is the one the
// frontier chart draws, over the models Provider and Jurisdiction keep.
"use client";

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import {
  blendedPrice,
  formatQualityBand,
  formatUsd,
  QUALITY_BAND_WIDTH,
  qualityBand,
} from "@/lib/benchmark-grid";
import type { ModelRow } from "@/lib/catalog-fields";
import {
  DOT_R,
  FilterNote,
  fitTitle,
  FRONTIER,
  LABEL_PX,
  LegendSwatch,
  pickPriceTicks,
  placeLabels,
  PRICE_AXIS_TITLES,
  useWidth,
  type ChartFilter,
  type Label,
} from "./chart-kit";
import { FloatingCard, type AnchorRect } from "./FloatingCard";
import { FrontierPointCard, FrontierScope, FrontierStepCard } from "./ScoreCards";

const M = { top: 12, right: 18, bottom: 46, left: 46 };
// While any band is beaten from above, every chart carries a strip over its
// plot (so the charts in a row line up): an up-triangle at each such model's
// price, its name beside or over it, two rows deep.
const STRIP = 34;
const LEAD_Y = 32; // the triangle's centre
const LEAD_R = 5; // its clearance, as a dot's radius
// A band is ten index points tall: a gridline every two.
const Y_STEP = 2;

interface Pt {
  row: ModelRow;
  x: number; // log10 blended price
  price: number;
  index: number;
}

type Active = { kind: "point"; id: string } | { kind: "step"; x: number; y: number } | null;

// Every measured row at its blended price, cheapest first.
function toPts(rows: readonly ModelRow[]): Pt[] {
  return rows
    .filter((r) => r.aa_index !== null)
    .map((r) => {
      const price = blendedPrice(r.input_price_per_1m, r.output_price_per_1m);
      return { row: r, x: Math.log10(price), price, index: r.aa_index as number };
    })
    .sort((a, b) => a.x - b.x || b.index - a.index);
}

// The ringed models that beat one of a band's models and have no dot in it:
// above the band, or in it but hidden by the Cost tier filter.
function leadersOf(pts: Pt[], frontier: Pt[]): Pt[] {
  const shown = new Set(pts.map((p) => p.row.id));
  return frontier.filter(
    (f) => !shown.has(f.row.id) && pts.some((p) => p.row.value_beaten_by === f.row.id),
  );
}

function BandChart({
  band,
  pts,
  frontier,
  byId,
  strip,
}: {
  band: number;
  // The band's plotted models, cheapest first.
  pts: Pt[];
  // The pool's ringed models, cheapest first, in any band.
  frontier: Pt[];
  byId: Map<string, ModelRow>;
  // Whether the charts carry the strip that marks models above a band.
  strip: boolean;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const width = useWidth(wrap);
  const [active, setActive] = useState<Active>(null);
  const pinned = useRef(false);
  const label = formatQualityBand(band);
  const yLo = band;
  const yHi = band + QUALITY_BAND_WIDTH;

  // The models that beat one of this band's and have no dot here: above the
  // band (marked in the strip over the plot), or in it but hidden by the
  // Cost tier filter (marked where the line turns, as a ring with no dot).
  const leaders = useMemo(() => leadersOf(pts, frontier), [pts, frontier]);
  const above = leaders.filter((f) => f.index >= yHi);
  const ringed = pts.filter((p) => p.row.value_frontier).length;

  const top = M.top + (strip ? STRIP : 0);
  const height = (width > 0 && width < 480 ? 340 : 320) + (strip ? STRIP : 0);
  const plotW = Math.max(40, width - M.left - M.right);
  const plotH = height - top - M.bottom;

  const xs = [...pts.map((p) => p.x), ...leaders.map((f) => f.x)];
  const pad = Math.max(0.09, (Math.max(...xs) - Math.min(...xs)) * 0.12);
  const x0 = Math.min(...xs) - pad;
  const x1 = Math.max(...xs) + pad;
  const sx = useCallback((x: number) => M.left + ((x - x0) / (x1 - x0)) * plotW, [x0, x1, plotW]);
  const sy = useCallback(
    (y: number) => top + plotH - ((y - yLo) / (yHi - yLo)) * plotH,
    [top, yLo, yHi, plotH],
  );
  // Where a marker's ring sits: at its score, or in the strip when above the band.
  const markerY = useCallback((f: Pt) => (f.index >= yHi ? LEAD_Y : sy(f.index)), [sy, yHi]);

  const yTicks: number[] = [];
  for (let v = yLo; v <= yHi; v += Y_STEP) yTicks.push(v);
  const xTicks = useMemo(
    () => (width === 0 ? [] : pickPriceTicks(x0, x1, sx, M.left, plotW)),
    [width, x0, x1, sx, plotW],
  );

  // The frontier line across the chart's prices, as the frontier chart draws
  // it, clipped to the band: a flat run inside the band is a ringed model's
  // score holding until the next one, and a rise across it is a step up past
  // the whole band at that price.
  const drawn = useMemo(() => {
    const before = frontier.filter((f) => f.x <= x0);
    return [...before.slice(-1), ...frontier.filter((f) => f.x > x0 && f.x <= x1)];
  }, [frontier, x0, x1]);
  const stepPath = useMemo(() => {
    if (drawn.length === 0) return "";
    let d = `M ${sx(Math.max(drawn[0].x, x0))} ${sy(drawn[0].index)}`;
    for (const f of drawn.slice(1)) d += ` H ${sx(f.x)} V ${sy(f.index)}`;
    return `${d} H ${sx(x1)}`;
  }, [drawn, sx, sy, x0, x1]);

  // The ringed model that holds the top score at a price (log10), if any.
  const holderAt = useCallback(
    (x: number): Pt | null => {
      let holder: Pt | null = null;
      for (const f of frontier) if (f.x <= x + 1e-9) holder = f;
      return holder;
    },
    [frontier],
  );

  const labels = useMemo(() => {
    if (width === 0) return new Map<string, Label>();
    const leadLabel = (f: Pt) => ({
      id: `lead-${f.row.id}`,
      cx: sx(f.x),
      cy: markerY(f),
      text: `${f.row.name} (${f.index.toFixed(1)})`,
      priority: f.index,
    });
    // The strip's markers name themselves within the strip.
    const strip = placeLabels(
      above.map(leadLabel),
      { x: M.left, y: 2, w: plotW, h: top - 6 },
      above.length,
      LEAD_R,
    );
    const plot = placeLabels(
      [
        // A hidden leader first (it explains a grey dot), then ringed models,
        // then the highest-scoring of the rest while there is room.
        ...leaders.filter((f) => f.index < yHi).map((f) => ({ ...leadLabel(f), priority: 2000 })),
        ...pts.map((p) => ({
          id: p.row.id,
          cx: sx(p.x),
          cy: sy(p.index),
          text: p.row.name,
          priority: (p.row.value_frontier ? 1000 : 0) + p.index,
        })),
      ],
      { x: M.left + 2, y: top + 2, w: plotW - 4, h: plotH - 4 },
      Math.max(4, Math.min(12, Math.floor(plotW / 50))),
    );
    return new Map([...strip, ...plot]);
  }, [pts, leaders, above, width, sx, sy, markerY, yHi, top, plotW, plotH]);

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

  // The pointer's price (log10) and height in the chart.
  const at = (clientX: number, clientY: number): { x: number; y: number } => {
    const r = svgRef.current!.getBoundingClientRect();
    const frac = (clientX - r.left - M.left) / plotW;
    return {
      x: x0 + Math.min(1, Math.max(0, frac)) * (x1 - x0),
      y: Math.min(top + plotH, Math.max(top, clientY - r.top)),
    };
  };

  const activePoint = active?.kind === "point" ? pts.find((p) => p.row.id === active.id) : undefined;
  const stepHolder = active?.kind === "step" ? holderAt(active.x) : null;
  // The readout sits on the line: at the holder's score when that is in the
  // band, else where the pointer meets a rise across it.
  const readoutY =
    active?.kind === "step" && stepHolder
      ? stepHolder.index >= yLo && stepHolder.index <= yHi
        ? sy(stepHolder.index)
        : active.y
      : 0;

  const getAnchor = (): AnchorRect | null => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r || !active) return null;
    if (active.kind === "point") {
      if (!activePoint) return null;
      return { left: r.left + sx(activePoint.x) - 9, top: r.top + sy(activePoint.index) - 9, width: 18, height: 18 };
    }
    if (!stepHolder) return null;
    return { left: r.left + sx(active.x) - 6, top: r.top + readoutY - 6, width: 12, height: 12 };
  };

  const leaderOf = (m: ModelRow): ModelRow | null =>
    m.value_beaten_by ? (byId.get(m.value_beaten_by) ?? null) : null;

  const card =
    active?.kind === "point" && activePoint ? (
      <FrontierPointCard model={activePoint.row} leader={leaderOf(activePoint.row)} />
    ) : active?.kind === "step" && stepHolder ? (
      <FrontierStepCard atPrice={10 ** active.x} model={stepHolder.row} />
    ) : null;

  const clipId = `plot-band-${band}`;

  return (
    <figure
      className="min-w-0 rounded-lg border border-brand-slate-200 bg-white px-4 pb-3 pt-3.5 dark:border-brand-slate-700 dark:bg-brand-slate-900"
      data-testid="quality-chart"
      data-band={band}
    >
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <span className="text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">
          AA Index {label}
        </span>
        <span className="text-xs tabular-nums text-brand-slate-500 dark:text-brand-slate-400">
          {pts.length} {pts.length === 1 ? "model" : "models"} ·{" "}
          {ringed === 0 ? "none" : ringed} on the frontier
        </span>
      </figcaption>
      {/* A band with no model on the frontier says what beats it. */}
      {ringed === 0 && above.length > 0 && (
        <p
          className="mt-1 text-xs leading-5 text-brand-slate-600 dark:text-brand-slate-300"
          data-testid="quality-chart-beaten"
        >
          {pts.length === 1 ? "Beaten" : `All ${pts.length} beaten`} from above:{" "}
          {above
            .map((f) => `${f.row.name} scores ${f.index.toFixed(1)} at ${formatUsd(f.price)}`)
            .join("; ")}
          .
        </p>
      )}

      <div ref={wrap} className="mt-2 w-full" style={{ height }}>
        {width > 0 && (
          <svg
            ref={svgRef}
            width={width}
            height={height}
            role="group"
            aria-label={`AA Index ${label}: ${pts.length} ${pts.length === 1 ? "model" : "models"} by blended price and AA Intelligence Index, ${ringed === 0 ? "none" : ringed} on the cost/quality frontier.`}
            className="block touch-manipulation select-none text-brand-slate-400 dark:text-brand-slate-500"
            onPointerDown={(e) => {
              if (e.target === e.currentTarget) clear();
            }}
          >
            <defs>
              <clipPath id={clipId}>
                <rect x={M.left} y={top} width={plotW} height={plotH} />
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
                <line x1={px} x2={px} y1={top + plotH} y2={top + plotH + 5} stroke="currentColor" strokeOpacity={0.55} />
                <text
                  x={px}
                  y={top + plotH + 18}
                  textAnchor="middle"
                  fontSize={11.5}
                  className="fill-brand-slate-500 tabular-nums dark:fill-brand-slate-400"
                >
                  {formatUsd(v)}
                </text>
              </g>
            ))}

            <g clipPath={`url(#${clipId})`}>
              {/* The frontier line. */}
              <path
                d={stepPath}
                fill="none"
                stroke={FRONTIER}
                strokeWidth={active?.kind === "step" ? 3.5 : 2.5}
                strokeDasharray="0.5 6"
                strokeLinecap="round"
                strokeLinejoin="round"
                data-testid="quality-chart-line"
                data-frontier-ids={drawn.map((f) => f.row.id).join(",")}
                pointerEvents="none"
              />
              {/* Wide invisible target along it: hover for the top score at that price. */}
              <path
                d={stepPath}
                fill="none"
                stroke="transparent"
                strokeWidth={16}
                tabIndex={0}
                role="button"
                aria-label="Cost/quality frontier line: the top AA Index at each price or less"
                data-testid="quality-chart-line-target"
                className="cursor-crosshair outline-none"
                onPointerMove={(e) => {
                  if (pinned.current || e.pointerType !== "mouse") return;
                  setActive({ kind: "step", ...at(e.clientX, e.clientY) });
                }}
                onPointerLeave={(e) => {
                  if (!pinned.current && e.pointerType === "mouse") setActive(null);
                }}
                onClick={(e) => {
                  pinned.current = true;
                  setActive({ kind: "step", ...at(e.clientX, e.clientY) });
                }}
                onFocus={(e) => {
                  if (!e.currentTarget.matches(":focus-visible")) return;
                  const first = drawn.find((f) => f.index >= yLo && f.index <= yHi) ?? drawn[0];
                  if (first) setActive({ kind: "step", x: Math.max(first.x, x0), y: top });
                }}
                onBlur={() => {
                  if (!pinned.current) setActive(null);
                }}
              />
            </g>

            {/* The models that beat this band's and have no dot here: an
                up-triangle in the strip when above the band, a dashed ring
                where the line turns when a filter hides it. */}
            {leaders.map((f) => {
              const cx = sx(f.x);
              const cy = markerY(f);
              const up = f.index >= yHi;
              return (
                <g
                  key={`lead-${f.row.id}`}
                  data-testid="quality-chart-leader"
                  data-model-id={f.row.id}
                  data-above={up ? "1" : "0"}
                  pointerEvents="none"
                >
                  {up ? (
                    <path d={`M ${cx - 5} ${cy + 4} L ${cx} ${cy - 5} L ${cx + 5} ${cy + 4} Z`} fill={FRONTIER} />
                  ) : (
                    <circle cx={cx} cy={cy} r={DOT_R} fill="none" stroke={FRONTIER} strokeWidth={2} strokeDasharray="2 2" />
                  )}
                </g>
              );
            })}

            {/* Dots: beaten models grey, the frontier green with its ring. */}
            {pts.map((p) => {
              const isActive = activePoint === p;
              const dim = activePoint && !isActive;
              const cx = sx(p.x);
              const cy = sy(p.index);
              const onFrontier = p.row.value_frontier;
              return (
                <g key={p.row.id} opacity={dim ? 0.35 : 1} pointerEvents="none">
                  {onFrontier && (
                    <circle cx={cx} cy={cy} r={DOT_R + 3.5} fill="none" stroke={FRONTIER} strokeWidth={2} />
                  )}
                  <circle
                    cx={cx}
                    cy={cy}
                    r={isActive ? DOT_R + 1.5 : DOT_R}
                    fill={onFrontier ? FRONTIER : undefined}
                    strokeWidth={isActive ? 2.5 : 1.5}
                    className={
                      (onFrontier ? "" : "fill-brand-slate-400 dark:fill-brand-slate-500 ") +
                      (isActive
                        ? "stroke-brand-slate-900 dark:stroke-white"
                        : "stroke-white dark:stroke-brand-slate-900")
                    }
                  />
                </g>
              );
            })}

            {/* Labels, on plates so the line under the text never hurts it. */}
            {[...labels.entries()].map(([id, l]) => {
              const dim = activePoint && activePoint.row.id !== id;
              const lead = id.startsWith("lead-");
              return (
                <g key={`label-${id}`} opacity={dim ? 0.35 : 1} pointerEvents="none">
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
                    className={
                      lead
                        ? "fill-emerald-700 tabular-nums dark:fill-emerald-300"
                        : "fill-brand-slate-700 tabular-nums dark:fill-brand-slate-200"
                    }
                  >
                    {l.text}
                  </text>
                </g>
              );
            })}

            {/* The line readout marker */}
            {active?.kind === "step" && stepHolder && (
              <circle
                cx={sx(active.x)}
                cy={readoutY}
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
                aria-label={`${p.row.name}: AA Index ${p.index}, blended ${formatUsd(p.price)} per 1M tokens, ${p.row.value_frontier ? "on the cost/quality frontier" : `beaten by ${leaderOf(p.row)?.name ?? "a model that scores higher at its price or less"}`}`}
                data-testid="quality-chart-point"
                data-model-id={p.row.id}
                data-frontier={p.row.value_frontier ? "1" : "0"}
                className="cursor-pointer outline-none"
                onPointerEnter={(e) => {
                  if (e.pointerType === "mouse" && !pinned.current) setActive({ kind: "point", id: p.row.id });
                }}
                onPointerLeave={(e) => {
                  if (e.pointerType === "mouse" && !pinned.current) setActive(null);
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
              transform={`translate(13 ${top + plotH / 2}) rotate(-90)`}
              textAnchor="middle"
              fontSize={11.5}
              className="fill-brand-slate-500 dark:fill-brand-slate-400"
            >
              AA Intelligence Index
            </text>
          </svg>
        )}
      </div>

      {card && (
        <FloatingCard getAnchor={getAnchor} placement="side" testId="chart-card">
          {card}
        </FloatingCard>
      )}
    </figure>
  );
}

export function QualityCharts({
  rows,
  pool,
  filter,
}: {
  // The rows the page's filters keep: the dots.
  rows: ModelRow[];
  // The rows the Provider and Jurisdiction filters keep, frontier marked over
  // them: the line, and the models the cards name.
  pool: ModelRow[];
  // The active filters; null when the page shows every model.
  filter: ChartFilter | null;
}) {
  const scope = useContext(FrontierScope);
  const pts = toPts(rows);
  const frontier = toPts(pool.filter((r) => r.value_frontier));
  const byId = new Map(pool.map((r) => [r.id, r]));
  // Best band first, as the table lists them.
  const bands = [...new Set(pts.map((p) => qualityBand(p.index) as number))].sort((a, b) => b - a);
  const inBand = new Map(bands.map((b) => [b, pts.filter((p) => qualityBand(p.index) === b)]));
  const strip = bands.some((b) =>
    leadersOf(inBand.get(b)!, frontier).some((f) => f.index >= b + QUALITY_BAND_WIDTH),
  );
  const ringed = pts.filter((p) => p.row.value_frontier).length;

  return (
    <details
      open
      className="group rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40"
      data-testid="quality-charts"
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-5 py-3 text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100">
        The best buy at each quality level: the frontier, one chart per quality band
        <span className="text-xs font-normal text-brand-slate-500 group-open:hidden dark:text-brand-slate-400">
          show
        </span>
        <span className="hidden text-xs font-normal text-brand-slate-500 group-open:inline dark:text-brand-slate-400">
          hide
        </span>
      </summary>

      <div className="space-y-4 border-t border-brand-slate-200 px-5 py-5 dark:border-brand-slate-700">
        <p className="max-w-4xl text-sm leading-6 text-brand-slate-600 dark:text-brand-slate-300">
          Each chart zooms into one of the table&rsquo;s AA Index bands on the frontier chart
          above: every model at its blended price (across) and AA Intelligence Index (up), and the
          dotted green line, the top AA Index each price buys.{" "}
          <strong>
            A green model is on the cost/quality frontier: it scores higher than every other
            {scope ? ` ${scope} model` : " model"} at its price or less.
          </strong>{" "}
          A grey model is beaten: another model scores higher and costs no more, and its card
          names it. When that model sits above the band, it is marked over the chart at its
          price.
        </p>

        {filter && (
          <FilterNote filter={filter} testId="quality-charts-filter">
            {pts.length === 0
              ? "No measured model matches, so there is nothing to plot."
              : `${pts.length} measured ${pts.length === 1 ? "model" : "models"} in ${bands.length} ${bands.length === 1 ? "chart" : "charts"}.`}{" "}
            {scope
              ? `The frontier is redrawn over the ${scope} models, at every price.`
              : "The frontier still compares every model in the catalog."}
          </FilterNote>
        )}

        <ul className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-brand-slate-600 dark:text-brand-slate-300">
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <circle cx={11} cy={7} r={3.5} fill={FRONTIER} />
              <circle cx={11} cy={7} r={6} fill="none" stroke={FRONTIER} strokeWidth={1.5} />
            </LegendSwatch>
            On the frontier ({scope ? `${scope} models` : "whole catalog"})
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <circle cx={11} cy={7} r={4.5} className="fill-brand-slate-400 dark:fill-brand-slate-500" />
            </LegendSwatch>
            Beaten: a model scores higher for no more
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <path d="M 1 11 H 11 V 3 H 21" fill="none" stroke={FRONTIER} strokeWidth={2} strokeDasharray="0.5 4" strokeLinecap="round" />
            </LegendSwatch>
            Top AA Index at each price
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <path d="M 6 11 L 11 2 L 16 11 Z" fill={FRONTIER} />
            </LegendSwatch>
            The model above the band that beats one here
          </li>
          <li className="text-brand-slate-500 dark:text-brand-slate-400">
            Hover or tap any dot or the green line for its numbers.
          </li>
        </ul>

        {bands.length > 0 && (
          <div className={"grid grid-cols-1 gap-4" + (bands.length > 1 ? " lg:grid-cols-2" : "")}>
            {bands.map((b) => (
              <BandChart
                key={b}
                band={b}
                pts={inBand.get(b)!}
                frontier={frontier}
                byId={byId}
                strip={strip}
              />
            ))}
          </div>
        )}

        <p className="text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
          The frontier comes straight from the data, as on the frontier chart: sort every
          {scope ? ` ${scope}` : ""} model by blended price and keep each one that scores higher
          than every model at its price or less. That keeps {ringed} of the {pts.length} models
          plotted. The table&rsquo;s Score asks a different question, a model against its own
          cost tier; group by Cost tier for the charts that draw it.
        </p>
      </div>
    </details>
  );
}
