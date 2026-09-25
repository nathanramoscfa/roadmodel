// web/components/FrontierChart.tsx
//
// The cost/quality frontier, drawn: every model with an AA Index on one chart,
// at its blended price (x, log scale) and AA Intelligence Index (y). The
// frontier models (the green ring in the table) are joined by a dotted green
// line that steps up at each one, so the line's height at any price is the top
// AA Index that price buys. The frontier comes straight from the data (sort by
// price, keep each model that outscores everything at its price or less); the
// grey lines behind it are the Score's fitted model, one price line per cost
// tier over the tier's own prices, all sharing one slope.
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
"use client";

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { blendedPrice, formatUsd, type ScoreFit } from "@/lib/benchmark-grid";
import { COST_TIER_DEFS, type CostTier, type ModelRow } from "@/lib/catalog-fields";
import {
  FilterNote,
  FRONTIER,
  LABEL_PX,
  LegendSwatch,
  pickPriceTicks,
  placeLabels,
  useWidth,
  type ChartFilter,
  type Label,
} from "./chart-kit";
import { FloatingCard, type AnchorRect } from "./FloatingCard";
import { FrontierPointCard, FrontierScope, FrontierStepCard } from "./ScoreCards";

const M = { top: 16, right: 24, bottom: 46, left: 46 };
const R = 5; // dot radius: this chart carries every model at once
const TIERS: CostTier[] = ["low", "medium", "high", "very-high"];

interface Pt {
  row: ModelRow;
  x: number; // log10 blended price
  price: number;
  index: number;
}

interface TierLine {
  tier: CostTier;
  a: number; // log10 price at the line's left end
  b: number; // … and right end
  ya: number;
  yb: number;
}

type Active = { kind: "point"; id: string } | { kind: "step"; x: number } | null;

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

function FrontierPlot({
  pts,
  frontier,
  drawn,
  x0,
  x1,
  lines,
  byId,
}: {
  pts: Pt[];
  // The pool's ringed models, cheapest first, shown or not.
  frontier: Pt[];
  // The ones the line passes through inside [x0, x1], cheapest first.
  drawn: Pt[];
  // The plotted price range, log10.
  x0: number;
  x1: number;
  lines: TierLine[];
  byId: Map<string, ModelRow>;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const width = useWidth(wrap);
  const [active, setActive] = useState<Active>(null);
  const pinned = useRef(false);

  const height = width > 0 && width < 640 ? 400 : 460;
  const plotW = Math.max(40, width - M.left - M.right);
  const plotH = height - M.top - M.bottom;

  const yLo = 0;
  // Tall enough for every dot, every step of the line and both ends of every
  // tier line (a filtered chart's line can run above its highest dot).
  const top = Math.max(
    ...pts.map((p) => p.index),
    ...drawn.map((f) => f.index),
    ...lines.flatMap((l) => [l.ya, l.yb]),
  );
  const yHi = Math.min(100, Math.ceil((top + 4) / 10) * 10);
  const sx = useCallback((x: number) => M.left + ((x - x0) / (x1 - x0)) * plotW, [x0, x1, plotW]);
  const sy = useCallback(
    (y: number) => M.top + plotH - ((y - yLo) / (yHi - yLo)) * plotH,
    [yHi, plotH],
  );
  const yTicks: number[] = [];
  for (let v = yLo; v <= yHi; v += 10) yTicks.push(v);
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

  const labels = useMemo(() => {
    if (width === 0) return new Map<string, Label>();
    return placeLabels(
      [
        // Ringed models first, then the tier lines' names, then the
        // highest-scoring of the rest while there is room.
        ...pts.map((p) => ({
          id: p.row.id,
          cx: sx(p.x),
          cy: sy(p.index),
          text: p.row.name,
          priority: (p.row.value_frontier ? 1000 : 0) + p.index,
        })),
        // A tier line's name tries the line's right end, then its left end,
        // then its middle, and keeps no clearance of its own.
        ...lines.map((l) => ({
          id: `tier-${l.tier}`,
          cx: sx(l.b),
          cy: sy(l.yb),
          text: `${COST_TIER_DEFS[l.tier].label} tier`,
          priority: 500,
          dot: false,
          anchors: [
            { cx: sx(l.b), cy: sy(l.yb) },
            { cx: sx(l.a), cy: sy(l.ya) },
            { cx: sx((l.a + l.b) / 2), cy: sy((l.ya + l.yb) / 2) },
          ],
        })),
      ],
      { x: M.left + 2, y: M.top + 2, w: plotW - 4, h: plotH - 4 },
      Math.max(4, Math.min(16, Math.floor(plotW / 70))),
      R,
    );
  }, [pts, lines, width, sx, sy, plotW, plotH]);

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

      <div ref={wrap} className="mt-2 w-full" style={{ height }}>
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

            {/* The Score's price lines, one per cost tier, over the tier's own prices. */}
            {lines.map((l) => (
              <line
                key={l.tier}
                x1={sx(l.a)}
                y1={sy(l.ya)}
                x2={sx(l.b)}
                y2={sy(l.yb)}
                strokeWidth={2}
                strokeLinecap="round"
                data-testid="frontier-tier-line"
                data-tier={l.tier}
                className="stroke-brand-slate-400 dark:stroke-brand-slate-500"
                pointerEvents="none"
              />
            ))}

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
              const isTier = id.startsWith("tier-");
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
                    fontWeight={isTier ? 400 : 500}
                    className={
                      isTier
                        ? "fill-brand-slate-500 italic dark:fill-brand-slate-400"
                        : "fill-brand-slate-700 dark:fill-brand-slate-200"
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
}: {
  // The rows the page's filters keep: the dots.
  rows: ModelRow[];
  // The rows the Provider and Jurisdiction filters keep, frontier marked over
  // them: the line, and the models the cards name.
  pool: ModelRow[];
  fit: ScoreFit | null;
  // The active filters; null when the page shows every model.
  filter: ChartFilter | null;
}) {
  const scope = useContext(FrontierScope);
  const pts = toPts(rows);
  if (!filter && pts.length < 2) return null;
  const frontier = toPts(pool.filter((r) => r.value_frontier));
  const byId = new Map(pool.map((r) => [r.id, r]));

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

  // The Score's price lines, one per cost tier on the chart, each over the
  // prices of that tier's plotted models (a tier priced at one point gets a
  // short stub so it still shows).
  const lines: TierLine[] = fit
    ? TIERS.filter((t) => fit.tiers[t] && pts.some((p) => p.row.tier_cost === t)).map((t) => {
        const tf = fit.tiers[t];
        const tx = pts.filter((p) => p.row.tier_cost === t).map((p) => p.x);
        let a = Math.min(...tx);
        let b = Math.max(...tx);
        if (b - a < 0.04) {
          a -= 0.03;
          b += 0.03;
        }
        return { tier: t, a, b, ya: tf.intercept + fit.slope * a, yb: tf.intercept + fit.slope * b };
      })
    : [];

  return (
    <details
      open
      className="group rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40"
      data-testid="frontier-panel"
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
        <p className="max-w-4xl text-sm leading-6 text-brand-slate-600 dark:text-brand-slate-300">
          Every model with an AA Index, on one chart: blended price across (log scale) and AA
          Intelligence Index up.{" "}
          <strong>
            The green models are the cost/quality frontier: each one scores higher than every other
            {scope ? ` ${scope} model` : " model"} at its price or less.
          </strong>{" "}
          The dotted green line joins them from cheapest to priciest and steps up at each one, so
          its height at any price is the top AA Index that price buys. The grey lines are the
          Score&rsquo;s price lines, one per cost tier, drawn for comparison.
        </p>

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
            A cost tier&rsquo;s Score line
          </li>
          <li className="text-brand-slate-500 dark:text-brand-slate-400">
            Hover or tap any dot or the green line for its numbers.
          </li>
        </ul>

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

        {pts.length > 0 && (
          <FrontierPlot
            pts={pts}
            frontier={frontier}
            drawn={drawn}
            x0={x0}
            x1={x1}
            lines={lines}
            byId={byId}
          />
        )}

        <p className="text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
          The frontier comes straight from the data: sort every{scope ? ` ${scope}` : ""} model by
          blended price and keep each one that scores higher than every model at its price or less.
          That keeps {ringed} of the {pts.length} models plotted.
          {fit && (
            <>
              {" "}
              The grey lines are the Score&rsquo;s fit: AA Index = α<sub>tier</sub> + β&thinsp;×&thinsp;log
              <sub>10</sub>(blended price), with β&nbsp;=&nbsp;{fit.slope.toFixed(1)} index points per
              10&times; price shared by every tier, each line drawn over its own tier&rsquo;s prices.
            </>
          )}
        </p>
      </div>
    </details>
  );
}
