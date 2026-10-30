// web/components/QualityCharts.tsx
//
// Price for quality, drawn: one chart per quality band (the table's ten-point
// AA Index groups, best band first), shown while the table is grouped by
// quality. Each plots the band's measured models at their blended price (x,
// log scale) and AA Intelligence Index (y), the frontier chart's axes, so a
// band's chart is one row of the frontier chart, zoomed. The line is the
// typical price for each AA Index (lib/benchmark-grid fitPriceModel: one line
// across every band), the shaded band is ±σ around it, and a stem runs across
// from the line to each model: left of the line (−) costs less than its
// quality usually does, right of it (+) costs more. The printed figure is the
// model's price gap: its price over the typical price, less one.
//
// The Score is not drawn here. It is read against a model's cost tier, and a
// band picks its models by the AA Index the Score measures, so a band of
// Scores sits one-sided by construction (grouped by cost tier, ScoreCharts
// draws them). The price-for-quality line takes the AA Index as its input, so
// a band holds models on both sides of it.
//
// Interactive like the tier charts: hover (mouse), tap (touch), or tab to
// (keyboard) any dot for a card with the model's price gap, the typical price
// for its AA Index, its prices and its Score; hover the line for its equation
// and the typical price at the pointer. Click or tap pins a card; a click
// elsewhere or Escape clears it. Laid out at the container's real pixel
// width, with labels placed greedily, most notable first (chart-kit).
//
// The page's Provider, Jurisdiction, Weights and Cost tier filters choose the
// dots: a band the filters empty has no chart. The line stays the
// whole-catalog fit, so a filter changes what is drawn, never where it sits.
"use client";

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import {
  blendedPrice,
  formatPriceGap,
  formatQualityBand,
  formatUsd,
  QUALITY_BAND_WIDTH,
  qualityBand,
  type PriceFit,
} from "@/lib/benchmark-grid";
import type { ModelRow } from "@/lib/catalog-fields";
import {
  BETTER,
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
  WORSE,
  type ChartFilter,
  type Label,
} from "./chart-kit";
import { FloatingCard, type AnchorRect } from "./FloatingCard";
import { FrontierScope, GapPointCard, gapTieBand, TypicalPriceCard } from "./ScoreCards";

const M = { top: 12, right: 18, bottom: 46, left: 46 };
// A band is ten index points tall: a gridline every two.
const Y_STEP = 2;
// As on the tier charts: a dense band labels its most notable models and
// leaves the rest to the hover card.
const MAX_LABELS = 9;

interface Pt {
  row: ModelRow;
  x: number; // log10 blended price
  price: number;
  index: number;
  typical: number; // log10 typical price for the index
  gap: number;
}

type Active = { kind: "point"; id: string } | { kind: "line"; y: number } | null;

function BandChart({
  band,
  rows,
  fit,
  byId,
}: {
  band: number;
  rows: ModelRow[];
  fit: PriceFit;
  // Every row in the frontier's pool by id, for the model that beats a dot's
  // model (it may sit in a band the filters hide).
  byId: Map<string, ModelRow>;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const width = useWidth(wrap);
  const [active, setActive] = useState<Active>(null);
  const pinned = useRef(false);
  const label = formatQualityBand(band);

  // The line, as log10 price at an AA Index.
  const line = useCallback((y: number) => fit.intercept + fit.slope * y, [fit]);

  const pts: Pt[] = useMemo(
    () =>
      rows
        .filter((r) => r.aa_index !== null && qualityBand(r.aa_index) === band)
        .map((r) => {
          const index = r.aa_index as number;
          const price = blendedPrice(r.input_price_per_1m, r.output_price_per_1m);
          const x = Math.log10(price);
          const typical = line(index);
          return { row: r, x, price, index, typical, gap: 10 ** (x - typical) - 1 };
        })
        .sort((a, b) => a.x - b.x || b.index - a.index),
    [rows, band, line],
  );
  const blends = pts.map((p) => p.price);
  const range = (lo: number, hi: number) =>
    lo === hi ? formatUsd(lo) : `${formatUsd(lo)}–${formatUsd(hi)}`;

  const height = width > 0 && width < 480 ? 340 : 320;
  const plotW = Math.max(40, width - M.left - M.right);
  const plotH = height - M.top - M.bottom;

  // The band's own ten points up; across, every dot and the whole tie band.
  const yLo = band;
  const yHi = band + QUALITY_BAND_WIDTH;
  const xVals = [
    ...pts.map((p) => p.x),
    line(yLo) - fit.sigma,
    line(yLo) + fit.sigma,
    line(yHi) - fit.sigma,
    line(yHi) + fit.sigma,
  ];
  const pad = Math.max(0.06, (Math.max(...xVals) - Math.min(...xVals)) * 0.06);
  const x0 = Math.min(...xVals) - pad;
  const x1 = Math.max(...xVals) + pad;
  const sx = useCallback((x: number) => M.left + ((x - x0) / (x1 - x0)) * plotW, [x0, x1, plotW]);
  const sy = useCallback(
    (y: number) => M.top + plotH - ((y - yLo) / (yHi - yLo)) * plotH,
    [yLo, yHi, plotH],
  );

  const yTicks: number[] = [];
  for (let v = yLo; v <= yHi; v += Y_STEP) yTicks.push(v);

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
        text: `${p.row.name} ${formatPriceGap(p.gap)}`,
        priority: Math.abs(p.x - p.typical) + (p.row.value_frontier ? 100 : 0),
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

  const yAt = (clientY: number): number => {
    const r = svgRef.current!.getBoundingClientRect();
    const frac = (M.top + plotH - (clientY - r.top)) / plotH;
    return yLo + Math.min(1, Math.max(0, frac)) * (yHi - yLo);
  };

  const getAnchor = (): AnchorRect | null => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r || !active) return null;
    if (active.kind === "point") {
      const p = pts.find((q) => q.row.id === active.id);
      if (!p) return null;
      return { left: r.left + sx(p.x) - 9, top: r.top + sy(p.index) - 9, width: 18, height: 18 };
    }
    return { left: r.left + sx(line(active.y)) - 6, top: r.top + sy(active.y) - 6, width: 12, height: 12 };
  };

  const activePoint = active?.kind === "point" ? pts.find((p) => p.row.id === active.id) : undefined;
  const clipId = `plot-band-${band}`;
  const band0 = `${sx(line(yLo) - fit.sigma)},${sy(yLo)} ${sx(line(yHi) - fit.sigma)},${sy(yHi)}`;
  const band1 = `${sx(line(yHi) + fit.sigma)},${sy(yHi)} ${sx(line(yLo) + fit.sigma)},${sy(yLo)}`;

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
          <span className="whitespace-nowrap">
            {pts.length} {pts.length === 1 ? "model" : "models"}
          </span>
          {" · "}
          <span className="whitespace-nowrap">
            blended {range(Math.min(...blends), Math.max(...blends))} per 1M
          </span>
          {" · "}
          <span className="whitespace-nowrap">
            typical {range(10 ** line(yLo), 10 ** line(yHi))}
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
            aria-label={`AA Index ${label}: ${pts.length} ${pts.length === 1 ? "model" : "models"} plotted by blended price against AA Intelligence Index, with the typical price for each AA Index. Each model's price gap is its horizontal distance from the line.`}
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
              {/* ±σ tie band */}
              <polygon
                points={`${band0} ${band1}`}
                className="fill-brand-slate-900/[0.05] dark:fill-white/[0.06]"
              />
              {/* The typical price for each AA Index */}
              <line
                x1={sx(line(yLo))}
                y1={sy(yLo)}
                x2={sx(line(yHi))}
                y2={sy(yHi)}
                strokeWidth={active?.kind === "line" ? 3 : 2}
                className="stroke-brand-slate-700 dark:stroke-brand-slate-200"
              />
            </g>

            {/* Wide invisible target along the line: hover for the equation. */}
            <line
              x1={sx(line(yLo))}
              y1={sy(yLo)}
              x2={sx(line(yHi))}
              y2={sy(yHi)}
              stroke="transparent"
              strokeWidth={18}
              tabIndex={0}
              role="button"
              aria-label={`Typical price line: log10(typical blended price) = ${fit.intercept.toFixed(2)} + ${fit.slope.toFixed(3)} × AA Index`}
              data-testid="quality-chart-line"
              className="cursor-crosshair outline-none"
              onPointerMove={(e) => {
                if (pinned.current || e.pointerType !== "mouse") return;
                setActive({ kind: "line", y: yAt(e.clientY) });
              }}
              onPointerLeave={(e) => {
                if (!pinned.current && e.pointerType === "mouse") setActive(null);
              }}
              onClick={(e) => {
                pinned.current = true;
                setActive({ kind: "line", y: yAt(e.clientY) });
              }}
              onFocus={(e) => {
                if (e.currentTarget.matches(":focus-visible")) setActive({ kind: "line", y: band + QUALITY_BAND_WIDTH / 2 });
              }}
              onBlur={() => {
                if (!pinned.current) setActive(null);
              }}
            />

            {/* Stems: the price gap, drawn as distance across from the line. */}
            {pts.map((p) => {
              const dim = activePoint && activePoint !== p;
              return (
                <line
                  key={`stem-${p.row.id}`}
                  x1={sx(p.typical)}
                  y1={sy(p.index)}
                  x2={sx(p.x)}
                  y2={sy(p.index)}
                  stroke={p.gap <= 0 ? BETTER : WORSE}
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
                    fill={p.gap <= 0 ? BETTER : WORSE}
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
                cx={sx(line(active.y))}
                cy={sy(active.y)}
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
                aria-label={`${p.row.name}: price gap ${formatPriceGap(p.gap)}, blended ${formatUsd(p.price)} against a typical ${formatUsd(10 ** p.typical)} for AA Index ${p.index}`}
                data-testid="quality-chart-point"
                data-model-id={p.row.id}
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

      {active && (
        <FloatingCard getAnchor={getAnchor} placement="side" testId="chart-card">
          {active.kind === "point" && activePoint ? (
            <GapPointCard
              model={activePoint.row}
              fit={fit}
              leader={
                activePoint.row.value_beaten_by
                  ? (byId.get(activePoint.row.value_beaten_by) ?? null)
                  : null
              }
            />
          ) : active.kind === "line" ? (
            <TypicalPriceCard fit={fit} atIndex={active.y} />
          ) : null}
        </FloatingCard>
      )}
    </figure>
  );
}

export function QualityCharts({
  rows,
  pool,
  fit,
  filter,
}: {
  // The rows the page's filters keep: the dots.
  rows: ModelRow[];
  // The rows the Provider and Jurisdiction filters keep (the frontier's pool),
  // for the models the cards name.
  pool: ModelRow[];
  fit: PriceFit | null;
  // The active filters; null when the page shows every model.
  filter: ChartFilter | null;
}) {
  const scope = useContext(FrontierScope);
  if (!fit) return null;
  const plotted = rows.filter((r) => r.aa_index !== null);
  // Best band first, as the table lists them.
  const bands = [...new Set(plotted.map((r) => qualityBand(r.aa_index) as number))].sort((a, b) => b - a);
  const byId = new Map(pool.map((r) => [r.id, r]));
  const perTen = 10 ** (10 * fit.slope);
  // Two decimals, typographic minus, as the cards print them.
  const fixed2 = (v: number) => (v < 0 ? "−" : "") + Math.abs(v).toFixed(2);

  return (
    <details
      open
      className="group rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40"
      data-testid="quality-charts"
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-5 py-3 text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100">
        What a quality level costs: price against AA Index, one chart per quality band
        <span className="text-xs font-normal text-brand-slate-500 group-open:hidden dark:text-brand-slate-400">
          show
        </span>
        <span className="hidden text-xs font-normal text-brand-slate-500 group-open:inline dark:text-brand-slate-400">
          hide
        </span>
      </summary>

      <div className="space-y-4 border-t border-brand-slate-200 px-5 py-5 dark:border-brand-slate-700">
        <p className="max-w-4xl text-sm leading-6 text-brand-slate-600 dark:text-brand-slate-300">
          Grouped by quality, the question is what a level of quality costs. Each chart is one of
          the table&rsquo;s AA Index bands: every model sits at its blended price (across) and AA
          Intelligence Index (up), as on the frontier chart, and the line is the price a model of
          that AA Index typically sells for. <strong>A model&rsquo;s price gap is how far its price
          sits from the line</strong>: left of it (&minus;) costs less than its quality usually
          does, right of it (+) costs more. &minus;50% is half the typical price; +100% is
          twice it.
        </p>

        <p
          className="rounded-lg border border-brand-accent/30 bg-brand-accent/5 px-3 py-2 text-xs leading-5 text-brand-slate-700 dark:bg-brand-accent/10 dark:text-brand-slate-200"
          data-testid="quality-charts-score-note"
        >
          <strong className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">
            The price gap compares a model with every model of its quality; the table&rsquo;s
            Score compares it with its own cost tier.
          </strong>{" "}
          Group by Cost tier for the charts that draw the Score. Each dot&rsquo;s card shows both.
        </p>

        {filter && (
          <FilterNote filter={filter} testId="quality-charts-filter">
            {plotted.length === 0
              ? "No measured model matches, so there is nothing to plot."
              : `${plotted.length} measured ${plotted.length === 1 ? "model" : "models"} in ${bands.length} ${bands.length === 1 ? "chart" : "charts"}.`}{" "}
            The typical-price line is still fitted over the whole catalog, so a filter changes
            which dots are drawn, never where the line sits.
          </FilterNote>
        )}

        <ul className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-brand-slate-600 dark:text-brand-slate-300">
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <circle cx={11} cy={7} r={5} fill={BETTER} />
            </LegendSwatch>
            Cheaper than typical (&minus;)
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <circle cx={11} cy={7} r={5} fill={WORSE} />
            </LegendSwatch>
            Dearer than typical (+)
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <circle cx={11} cy={7} r={5.5} fill="none" stroke={FRONTIER} strokeWidth={2} />
            </LegendSwatch>
            Cost/quality frontier ({scope ? `${scope} models` : "whole catalog"})
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <line x1={8} y1={13} x2={14} y2={1} strokeWidth={2} className="stroke-brand-slate-700 dark:stroke-brand-slate-200" />
            </LegendSwatch>
            Typical price for the AA Index
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <rect x={1} y={2} width={20} height={10} rx={2} className="fill-brand-slate-900/[0.08] dark:fill-white/[0.1]" />
            </LegendSwatch>
            Tie band, {gapTieBand(fit)} typical
          </li>
          <li className="text-brand-slate-500 dark:text-brand-slate-400">
            Hover or tap any dot or line for its numbers.
          </li>
        </ul>

        {bands.length > 0 && (
          <div className={"grid grid-cols-1 gap-4" + (bands.length > 1 ? " lg:grid-cols-2" : "")}>
            {bands.map((b) => (
              <BandChart key={b} band={b} rows={rows} fit={fit} byId={byId} />
            ))}
          </div>
        )}

        <p className="text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
          One least-squares fit over all {fit.n} AA-measured models: log<sub>10</sub>(blended
          price) = a + b&thinsp;×&thinsp;AA Index, with a&nbsp;=&nbsp;{fixed2(fit.intercept)} and
          b&nbsp;=&nbsp;{fit.slope.toFixed(3)}, so every 10 index points costs{" "}
          {perTen.toFixed(2)}&times; more on average (R&sup2;&nbsp;{fit.r2.toFixed(2)}, residual
          σ&nbsp;{fit.sigma.toFixed(2)} in log<sub>10</sub> price). One line serves every band,
          and the bands are cut on its input, so a band&rsquo;s models can fall on either side
          of it.
          A dot inside the shaded band costs about what its quality usually does: treat gaps
          that small as a tie, not a ranking.{" "}
          <strong className="text-brand-slate-700 dark:text-brand-slate-200">
            The green ring marks the cost/quality frontier: a model that scores higher than every
            other {scope ? `${scope} model` : "model in the catalog"} at its price or less.
          </strong>
        </p>
      </div>
    </details>
  );
}
