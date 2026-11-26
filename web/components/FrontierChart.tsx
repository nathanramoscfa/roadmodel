// web/components/FrontierChart.tsx
//
// The cost/quality frontier, drawn: every model with an AA Index on one chart,
// at its blended price (x, log scale) and AA Intelligence Index (y). The
// frontier models (the green ring in the table) are joined by a dotted green
// line that steps up at each one, so the line's height at any price is the top
// AA Index that price buys. The frontier comes straight from the data (sort by
// price, keep each model that outscores everything at its price or less); the
// grey line behind it is the Score's continuous market price line across the
// catalog.
//
// Interactive like the tier charts: hover (mouse), tap (touch) or tab to
// (keyboard) any dot for its card; hover the green line for the top score at
// that price. Click or tap pins a card; a click elsewhere or Escape clears it.
// Laid out at the container's real pixel width (chart-kit useWidth).
//
// The page's filters (lib/catalog-filter): the dots are the models all three
// keep; the frontier is drawn from the models Provider and Jurisdiction keep,
// at every price. With a Cost tier chosen, the line is clipped to the band's
// prices and can step up where a model outside the band holds the top score:
// a step with no dot, which the panel names.
//
// Grouped by quality (the table's Group by), the chart marks the table's
// ten-point AA Index bands as rows between its gridlines, every other one
// shaded, and names each band that holds a model in the right margin. Within
// a row the models line up by price, and the cheapest way to reach a level is
// where the green line first reaches that row: the question the quality
// grouping asks, answered on the chart that compares every model at once.
"use client";

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import {
  formatQualityBand,
  formatUsd,
  QUALITY_BAND_WIDTH,
  qualityBand,
  sigmaAt,
  type ScoreFit,
} from "@/lib/benchmark-grid";
import { COST_TIER_DEFS, type ModelRow } from "@/lib/catalog-fields";
import { headlinePrice } from "@/lib/pick-effort";
import type { Grouping } from "@/lib/models-prefs";
import {
  FilterNote,
  FRONTIER,
  LABEL_PX,
  LegendSwatch,
  pickPriceTicks,
  PinnedIndexAxis,
  placeEveryLabel,
  fitTitle,
  PRICE_AXIS_TITLES,
  useNamedWidth,
  type ChartFilter,
  type Mark,
  type PlacedLabel,
  type Segment,
} from "./chart-kit";
import { FloatingCard, type AnchorRect } from "./FloatingCard";
import { FrontierPointCard, FrontierScope, FrontierStepCard } from "./ScoreCards";

const M = { top: 16, right: 24, bottom: 46, left: 46 };
// The right margin while the quality bands are named in it ("50–59.9"), on a
// chart wide enough to spare the room; a narrower chart shades the bands and
// leaves their names to the axis.
const BAND_MARGIN = 70;
const BAND_NAMES_MIN_WIDTH = 480;
const R = 5; // dot radius: this chart carries every model at once

interface Pt {
  row: ModelRow;
  x: number; // log10 blended price
  price: number;
  index: number;
}

interface MarketLine {
  a: number; // log10 price at the line's left end
  b: number; // … and right end
  ya: number;
  yb: number;
  fit: ScoreFit;
}

type Active = { kind: "point"; id: string } | { kind: "step"; x: number } | null;

// Every measured row at its blended price, cheapest first.
function toPts(rows: readonly ModelRow[]): Pt[] {
  return rows
    .filter((r) => r.aa_index !== null)
    .map((r) => {
      const price = headlinePrice(r);
      return { row: r, x: Math.log10(price), price, index: r.aa_index as number };
    })
    .sort((a, b) => a.x - b.x || b.index - a.index);
}

function FrontierPlot({
  pts,
  frontier,
  drawn,
  x0,
  x1,
  marketLine,
  byId,
  bands,
}: {
  pts: Pt[];
  // The pool's ringed models, cheapest first, shown or not.
  frontier: Pt[];
  // The ones the line passes through inside [x0, x1], cheapest first.
  drawn: Pt[];
  // The plotted price range, log10.
  x0: number;
  x1: number;
  marketLine: MarketLine | null;
  byId: Map<string, ModelRow>;
  // Grouped by quality: the lower bound of each band that holds a plotted
  // model (the table's quality groups). Null when grouped by cost tier.
  bands: number[] | null;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  // In a box too narrow for its names (a phone) the chart keeps the width
  // they need and pans sideways there.
  const { width, pans } = useNamedWidth(scroller);
  const [active, setActive] = useState<Active>(null);
  const pinned = useRef(false);

  const height = 460;
  const namedBands = bands !== null && width >= BAND_NAMES_MIN_WIDTH;
  const plotW = Math.max(40, width - M.left - (namedBands ? BAND_MARGIN : M.right));
  const plotH = height - M.top - M.bottom;

  const yLo = 0;
  // Tall enough for every dot, every step of the frontier line, and the
  // continuous market price line across the plotted range.
  const top = Math.max(
    ...pts.map((p) => p.index),
    ...drawn.map((f) => f.index),
    ...(marketLine ? [marketLine.ya, marketLine.yb] : []),
  );
  const yHi = Math.min(100, Math.ceil((top + 4) / 10) * 10);
  const sx = useCallback((x: number) => M.left + ((x - x0) / (x1 - x0)) * plotW, [x0, x1, plotW]);
  const sy = useCallback(
    (y: number) => M.top + plotH - ((y - yLo) / (yHi - yLo)) * plotH,
    [yHi, plotH],
  );
  const yTicks: number[] = [];
  for (let v = yLo; v <= yHi; v += 10) yTicks.push(v);
  // Grouped by quality: one row per ten-point band from the axis's foot to its
  // top, on the gridlines above (the top band, 90–100, holds the 100 too).
  const bandRows: number[] = [];
  if (bands) for (let v = yLo; v < yHi; v += QUALITY_BAND_WIDTH) bandRows.push(v);
  const xTicks = useMemo(
    () => (width === 0 ? [] : pickPriceTicks(x0, x1, sx, M.left, plotW)),
    [width, x0, x1, sx, plotW],
  );

  // The frontier line: from the cheapest ringed model (or the chart's left
  // edge, when a cheaper model outside the plotted band holds the top score
  // there), flat until the next ringed model's price, then up to its score,
  // and flat to the right edge after the last one. Its height at any price is
  // the top score that buys.
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

  // Every frontier (ringed) model is named and no other: a name with no room
  // against its dot sits a little off it, joined by a thin line. The other
  // dots are in the names' way, and each one's card names it.
  const labels = useMemo(() => {
    if (width === 0) return new Map<string, PlacedLabel>();
    const marks: Mark[] = pts.map((p) => ({
      id: p.row.id,
      cx: sx(p.x),
      cy: sy(p.index),
      r: R,
      text: p.row.value_frontier ? p.row.name : null,
      hard: p.row.value_frontier,
      priority: 1000 + p.index,
    }));
    // The frontier line's runs and risers, for the names to keep off it.
    const line: Segment[] = [];
    drawn.forEach((f, i) => {
      const x = sx(Math.max(f.x, x0));
      const y = sy(f.index);
      const next = drawn[i + 1];
      const end = next ? sx(next.x) : sx(x1);
      line.push({ x1: x, y1: y, x2: end, y2: y });
      if (next) line.push({ x1: end, y1: y, x2: end, y2: sy(next.index) });
    });
    // And off the market price line, where there is another spot as near.
    if (marketLine) {
      line.push({ x1: sx(marketLine.a), y1: sy(marketLine.ya), x2: sx(marketLine.b), y2: sy(marketLine.yb) });
    }
    return placeEveryLabel(marks, { x: M.left + 2, y: M.top + 2, w: plotW - 4, h: plotH - 4 }, line);
  }, [pts, drawn, marketLine, x0, x1, width, sx, sy, plotW, plotH]);

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

  const activePoint = active?.kind === "point" ? pts.find((p) => p.row.id === active.id) : undefined;
  const stepHolder = active?.kind === "step" ? holderAt(active.x) : null;

  const getAnchor = (): AnchorRect | null => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r || !active) return null;
    if (active.kind === "point") {
      if (!activePoint) return null;
      return { left: r.left + sx(activePoint.x) - 8, top: r.top + sy(activePoint.index) - 8, width: 16, height: 16 };
    }
    if (!stepHolder) return null;
    return { left: r.left + sx(active.x) - 6, top: r.top + sy(stepHolder.index) - 6, width: 12, height: 12 };
  };

  const leaderOf = (m: ModelRow): ModelRow | null =>
    m.value_beaten_by ? (byId.get(m.value_beaten_by) ?? null) : null;

  const card =
    active?.kind === "point" && activePoint ? (
      <FrontierPointCard model={activePoint.row} leader={leaderOf(activePoint.row)} />
    ) : active?.kind === "step" && stepHolder ? (
      <FrontierStepCard atPrice={10 ** active.x} model={stepHolder.row} />
    ) : null;

  return (
    <figure
      className="min-w-0 rounded-lg border border-brand-slate-200 bg-white px-4 pb-3 pt-3.5 dark:border-brand-slate-700 dark:bg-brand-slate-900"
      data-testid="frontier-chart"
    >
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <span className="inline-flex items-center gap-2 text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">
          <span
            className="inline-block h-2.5 w-2.5 rounded-full border-2"
            style={{ borderColor: FRONTIER }}
          />
          Every model, one chart
        </span>
        <span className="text-xs tabular-nums text-brand-slate-500 dark:text-brand-slate-400">
          {pts.length} {pts.length === 1 ? "model" : "models"} ·{" "}
          {pts.filter((p) => p.row.value_frontier).length} on the frontier
        </span>
      </figcaption>

      <div className="relative mt-2">
        <div ref={scroller} className="overflow-x-auto overscroll-x-contain" data-testid="frontier-chart-scroll">
      <div style={{ height, width: pans ? width : "100%" }}>
        {width > 0 && (
          <svg
            ref={svgRef}
            width={width}
            height={height}
            role="group"
            aria-label={`Every model with an AA Index, ${pts.length} in all, by blended price and AA Intelligence Index. The cost/quality frontier passes through ${drawn.length} ${drawn.length === 1 ? "model" : "models"}: ${drawn.map((f) => f.row.name).join(", ")}.`}
            className="block touch-manipulation select-none text-brand-slate-400 dark:text-brand-slate-500"
            onPointerDown={(e) => {
              if (e.target === e.currentTarget) clear();
            }}
          >
            <defs>
              <clipPath id="frontier-plot-clip">
                <rect x={M.left} y={M.top} width={plotW} height={plotH} />
              </clipPath>
            </defs>
            {/* Grouped by quality: the table's bands as rows behind everything
                else, every other one shaded, and each band that holds a model
                named in the margin. */}
            {bandRows.map((lo) => {
              const shaded = (lo / QUALITY_BAND_WIDTH) % 2 === 1;
              return (
                <rect
                  key={`band-${lo}`}
                  x={M.left}
                  y={sy(lo + QUALITY_BAND_WIDTH)}
                  width={plotW}
                  height={sy(lo) - sy(lo + QUALITY_BAND_WIDTH)}
                  fill={shaded ? undefined : "transparent"}
                  className={shaded ? "fill-brand-slate-900/[0.045] dark:fill-white/[0.05]" : undefined}
                  pointerEvents="none"
                  data-testid="frontier-band-stripe"
                  data-band={lo}
                  data-shaded={shaded ? "1" : "0"}
                />
              );
            })}
            {namedBands &&
              bands?.map((lo) => (
                <text
                  key={`band-name-${lo}`}
                  x={M.left + plotW + 8}
                  y={(sy(lo) + sy(lo + QUALITY_BAND_WIDTH)) / 2 + 4}
                  fontSize={11}
                  pointerEvents="none"
                  data-testid="frontier-band-label"
                  data-band={lo}
                  className="fill-brand-slate-500 tabular-nums dark:fill-brand-slate-400"
                >
                  {formatQualityBand(lo)}
                </text>
              ))}

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

            {/* Value's continuous market price line and narrowing ±σ local spread ribbon. */}
            {marketLine && (() => {
              const steps = 24;
              const xsRibbon = Array.from(
                { length: steps + 1 },
                (_, i) => marketLine.a + ((marketLine.b - marketLine.a) * i) / steps,
              );
              const upper = xsRibbon.map((x) => {
                const y = marketLine.fit.intercept + marketLine.fit.slope * x;
                const s = sigmaAt(marketLine.fit, 10 ** x) ?? marketLine.fit.sigma;
                return `${sx(x)},${sy(y + s)}`;
              });
              const lower = [...xsRibbon].reverse().map((x) => {
                const y = marketLine.fit.intercept + marketLine.fit.slope * x;
                const s = sigmaAt(marketLine.fit, 10 ** x) ?? marketLine.fit.sigma;
                return `${sx(x)},${sy(y - s)}`;
              });
              return (
                <g clipPath="url(#frontier-plot-clip)">
                  <polygon
                    points={[...upper, ...lower].join(" ")}
                    data-testid="frontier-market-band"
                    className="fill-brand-slate-900/[0.045] dark:fill-white/[0.055]"
                    pointerEvents="none"
                  />
                  <line
                    x1={sx(marketLine.a)}
                    y1={sy(marketLine.ya)}
                    x2={sx(marketLine.b)}
                    y2={sy(marketLine.yb)}
                    strokeWidth={2}
                    strokeLinecap="round"
                    data-testid="frontier-market-line"
                    className="stroke-brand-slate-400 dark:stroke-brand-slate-500"
                    pointerEvents="none"
                  />
                </g>
              );
            })()}

            {/* The frontier line. */}
            <path
              d={stepPath}
              fill="none"
              stroke={FRONTIER}
              strokeWidth={active?.kind === "step" ? 3.5 : 2.5}
              strokeDasharray="0.5 6"
              strokeLinecap="round"
              strokeLinejoin="round"
              data-testid="frontier-line"
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
              data-testid="frontier-line-target"
              className="cursor-crosshair outline-none"
              onPointerMove={(e) => {
                if (pinned.current || e.pointerType !== "mouse") return;
                setActive({ kind: "step", x: xAt(e.clientX) });
              }}
              onPointerLeave={(e) => {
                if (!pinned.current && e.pointerType === "mouse") setActive(null);
              }}
              onClick={(e) => {
                pinned.current = true;
                setActive({ kind: "step", x: xAt(e.clientX) });
              }}
              onFocus={(e) => {
                if (e.currentTarget.matches(":focus-visible") && drawn.length > 0) {
                  setActive({ kind: "step", x: Math.max(drawn[0].x, x0) });
                }
              }}
              onBlur={() => {
                if (!pinned.current) setActive(null);
              }}
            />

            {/* Dots: every model grey, the frontier green with its ring. */}
            {pts.map((p) => {
              const isActive = activePoint === p;
              const dim = activePoint && !isActive;
              const cx = sx(p.x);
              const cy = sy(p.index);
              const onFrontier = p.row.value_frontier;
              return (
                <g key={p.row.id} opacity={dim ? 0.35 : 1} pointerEvents="none">
                  {onFrontier && (
                    <circle cx={cx} cy={cy} r={R + 3.5} fill="none" stroke={FRONTIER} strokeWidth={2} />
                  )}
                  <circle
                    cx={cx}
                    cy={cy}
                    r={isActive ? R + 1.5 : R}
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

            {/* Labels, on plates so a line under the text never hurts it. */}
            {[...labels.entries()].map(([id, l]) => {
              const dim = activePoint && activePoint.row.id !== id;
              return (
                <g
                  key={`label-${id}`}
                  opacity={dim ? 0.35 : 1}
                  pointerEvents="none"
                  data-testid="frontier-model-label"
                  data-model-id={id}
                >
                  {l.leader && (
                    <line
                      x1={l.leader.x1}
                      y1={l.leader.y1}
                      x2={l.leader.x2}
                      y2={l.leader.y2}
                      strokeWidth={1}
                      strokeLinecap="round"
                      className="stroke-brand-slate-400 dark:stroke-brand-slate-500"
                      data-testid="frontier-label-leader"
                    />
                  )}
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
                    className="fill-brand-slate-700 dark:fill-brand-slate-200"
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
                cy={sy(stepHolder.index)}
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
                r={10}
                fill="transparent"
                tabIndex={0}
                role="button"
                aria-label={`${p.row.name}: AA Index ${p.index}, blended ${formatUsd(p.price)} per 1M tokens${p.row.value_frontier ? ", on the cost/quality frontier" : ""}`}
                data-testid="frontier-chart-point"
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
        </div>
        {pans && width > 0 && (
          <PinnedIndexAxis
            left={M.left}
            top={M.top}
            plotH={plotH}
            height={height}
            ticks={yTicks.map((v) => ({ v, y: sy(v) }))}
            testId="frontier-chart-pinned-axis"
          />
        )}
      </div>
      {pans && (
        <p
          className="mt-1 text-xs text-brand-slate-500 dark:text-brand-slate-400"
          data-testid="frontier-chart-pan-hint"
        >
          Swipe the chart sideways to see all of it.
        </p>
      )}

      {card && (
        <FloatingCard getAnchor={getAnchor} placement="side" testId="frontier-card">
          {card}
        </FloatingCard>
      )}
    </figure>
  );
}

export function FrontierChart({
  rows,
  pool,
  fit,
  filter,
  grouping,
}: {
  // The rows the page's filters keep: the dots.
  rows: ModelRow[];
  // The rows the Provider and Jurisdiction filters keep, frontier marked over
  // them: the line, and the models the cards name.
  pool: ModelRow[];
  fit: ScoreFit | null;
  // The active filters; null when the page shows every model.
  filter: ChartFilter | null;
  // The table's Group by choice: grouped by quality, the chart marks its bands.
  grouping: Grouping;
}) {
  const scope = useContext(FrontierScope);
  const pts = toPts(rows);
  if (!filter && pts.length < 2) return null;
  const frontier = toPts(pool.filter((r) => r.value_frontier));
  const byId = new Map(pool.map((r) => [r.id, r]));
  // Grouped by quality: the bands that hold a plotted model, best first, the
  // table's quality groups.
  const bands =
    grouping === "quality"
      ? [...new Set(pts.map((p) => qualityBand(p.index) as number))].sort((a, b) => b - a)
      : null;

  // The plotted price range (log10), padded so no dot sits on the frame.
  const xs = pts.map((p) => p.x);
  const pad = Math.max(0.06, (Math.max(...xs) - Math.min(...xs)) * 0.04);
  const x0 = Math.min(...xs) - pad;
  const x1 = Math.max(...xs) + pad;
  // The line inside that range: the model holding the top score at the left
  // edge, then each one that steps up before the right edge. Unfiltered, that
  // is every ringed model, all of them dots.
  const before = frontier.filter((f) => f.x <= x0);
  const drawn =
    pts.length === 0 ? [] : [...before.slice(-1), ...frontier.filter((f) => f.x > x0 && f.x <= x1)];
  const shownIds = new Set(pts.map((p) => p.row.id));
  const offBand = drawn.filter((f) => !shownIds.has(f.row.id));
  const ringed = pts.filter((p) => p.row.value_frontier).length;

  // The Score's continuous market price line across the plotted price range
  // (a single plotted price gets a short stub so the line still shows).
  const marketLine: MarketLine | null =
    fit && xs.length > 0
      ? (() => {
          let a = Math.min(...xs);
          let b = Math.max(...xs);
          if (b - a < 0.04) {
            a -= 0.03;
            b += 0.03;
          }
          return { a, b, ya: fit.intercept + fit.slope * a, yb: fit.intercept + fit.slope * b, fit };
        })()
      : null;

  return (
    <details
      open
      className="group rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40"
      data-testid="frontier-panel"
      data-grouping={grouping}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-5 py-3 text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100">
        The cost/quality frontier: every model on one chart
        <span className="text-xs font-normal text-brand-slate-500 group-open:hidden dark:text-brand-slate-400">
          show
        </span>
        <span className="hidden text-xs font-normal text-brand-slate-500 group-open:inline dark:text-brand-slate-400">
          hide
        </span>
      </summary>

      <div className="space-y-4 border-t border-brand-slate-200 px-5 py-5 dark:border-brand-slate-700">
        {filter && (
          <FilterNote filter={filter} testId="frontier-filter">
            {pts.length === 0
              ? "No measured model matches, so there is nothing to plot."
              : `${pts.length} measured ${pts.length === 1 ? "model" : "models"} plotted.`}{" "}
            {scope
              ? `The frontier is redrawn over the ${scope} models, at every price.`
              : "The frontier still compares every model in the catalog."}
            {offBand.length > 0 && (
              <span data-testid="frontier-off-band">
                {" "}
                Where the green line steps up with no dot, the top score belongs to a model your Cost
                tier choice hides: {offBand.map((f) => `${f.row.name} (${COST_TIER_DEFS[f.row.tier_cost].label} cost)`).join(", ")}.
              </span>
            )}
          </FilterNote>
        )}

        {/* The plot first, so it is what the page's first screen shows; its
            legend and the reading of it follow. */}
        {pts.length > 0 && (
          <FrontierPlot
            pts={pts}
            frontier={frontier}
            drawn={drawn}
            x0={x0}
            x1={x1}
            marketLine={marketLine}
            byId={byId}
            bands={bands}
          />
        )}

        <ul className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-brand-slate-600 dark:text-brand-slate-300">
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <circle cx={11} cy={7} r={4.5} className="fill-brand-slate-400 dark:fill-brand-slate-500" />
            </LegendSwatch>
            A model
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <circle cx={11} cy={7} r={3.5} fill={FRONTIER} />
              <circle cx={11} cy={7} r={6} fill="none" stroke={FRONTIER} strokeWidth={1.5} />
            </LegendSwatch>
            On the frontier
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <path
                d="M 1 11 H 9 V 3 H 21"
                fill="none"
                stroke={FRONTIER}
                strokeWidth={2}
                strokeDasharray="0.5 4"
                strokeLinecap="round"
              />
            </LegendSwatch>
            Frontier: the top score at each price
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <line x1={1} y1={10} x2={21} y2={5} strokeWidth={2} className="stroke-brand-slate-400 dark:stroke-brand-slate-500" />
            </LegendSwatch>
            Today&rsquo;s expected AA Index for the price
          </li>
          {fit && (
            <li className="inline-flex items-center gap-1.5">
              <LegendSwatch>
                <polygon points="1,2 21,5 21,11 1,14" className="fill-brand-slate-900/[0.09] dark:fill-white/[0.12]" />
              </LegendSwatch>
              ±σ local spread (±{fit.sigmaMin.toFixed(1)}–{fit.sigmaMax.toFixed(1)})
            </li>
          )}
          {bands && (
            <li className="inline-flex items-center gap-1.5">
              <LegendSwatch>
                <rect x={1} y={1} width={20} height={12} rx={1} className="fill-brand-slate-900/[0.08] dark:fill-white/[0.1]" />
              </LegendSwatch>
              A quality band: ten AA Index points, every other one shaded
            </li>
          )}
          <li className="text-brand-slate-500 dark:text-brand-slate-400">
            Hover or tap any dot or the green line for its numbers.
          </li>
        </ul>

        <p className="max-w-4xl text-sm leading-6 text-brand-slate-600 dark:text-brand-slate-300">
          Every model with an AA Index, on one chart: effort-adjusted blended price across (log scale) and AA
          Intelligence Index up.{" "}
          <strong>
            The green models are the cost/quality frontier: each one scores higher than every other
            {scope ? ` ${scope} model` : " model"} at its price or less.
          </strong>{" "}
          The dotted green line joins them from cheapest to priciest and steps up at each one, so
          its height at any price is the top AA Index that price buys. The grey line and shaded ribbon show Value&rsquo;s continuous market price line and
          narrowing ±σ local spread for today&rsquo;s generation across every cost tier; the charts
          below zoom into each cost tier along that line.
          {bands && (
            <span data-testid="frontier-bands-note">
              {" "}
              Grouped by quality, the rows between the gridlines are the table&rsquo;s ten-point
              AA Index bands, every other one shaded: within a band the models line up by price,
              and the cheapest way to reach a level is where the green line first reaches that
              band.
            </span>
          )}
        </p>

        <p className="text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
          The frontier comes straight from the data: sort every{scope ? ` ${scope}` : ""} model by
          effort-adjusted blended price and keep each one that scores higher than every model at its price or less.
          That keeps {ringed} of the {pts.length} models plotted.
          {fit && (
            <>
              {" "}
              The grey line is Value&rsquo;s Huber-robust{fit.vintageAdjusted ? ", vintage-controlled" : ""} fit
              across all {fit.n} AA-measured models: AA Index = {fit.intercept.toFixed(1)} +{" "}
              {fit.slope.toFixed(1)}&thinsp;×&thinsp;log<sub>10</sub>(effort-adjusted price), a
              continuous baseline of {fit.slope.toFixed(1)} index points per 10&times; price
              (R&sup2;&nbsp;{fit.r2.toFixed(2)}, local ±σ narrowing from ±{fit.sigmaMax.toFixed(1)} to ±
              {fit.sigmaMin.toFixed(1)}).
            </>
          )}
        </p>
      </div>
    </details>
  );
}
