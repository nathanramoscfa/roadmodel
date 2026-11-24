// web/components/PicksChart.tsx
//
// Where the picks sit. A pick runs a model at an effort, so the chart plots
// each model the viewer can run at each effort (x: its price at that effort's
// token use, log scale; y: its AA Intelligence Index there), and the green
// cost/quality frontier steps up through the points that score higher than
// every other point at their price or less. The points are the answer's own
// (lib/frontier-points.ts): the settings its ladder weighed, at the efforts
// this task may run, so the line is the one the picks were read from and
// each point says whether it meets the task's bar.
//
// It is drawn to be read at a glance, like the /models frontier chart:
//   - every point off the frontier is a small quiet dot with no label;
//   - only a model on the frontier is named, once, at its top frontier point
//     (a picked model at the point it was picked at, with its level);
//   - each pick is a lettered marker (C, B, Q), so a pick is found without a
//     label of its own;
//   - a point below the task's bar is hollow, so Cost reads as what it is:
//     the cheapest filled point on the line;
//   - a model's efforts are joined only for the selected pick and for the
//     point under the pointer.
// /models plots each model once, at its headline figures.
//
// Hover (mouse), tap (touch) or tab to (keyboard) any dot for the card
// /models shows for it; a click elsewhere or Escape closes it. Without picks
// (before a first recommendation) the chart is the frontier alone.
"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { formatUsd } from "@/lib/benchmark-grid";
import { leaderAt, pointName, pointRow, type Frontier, type PlotPoint } from "@/lib/frontier-points";
import { PRIORITY_LABEL, type OptionView } from "@/lib/ladder-view";
import type { BudgetPriority } from "@/lib/profile";
import type { SlimRow } from "@/lib/recommend-picks";
import {
  fitTitle,
  FRONTIER,
  LABEL_PX,
  LegendSwatch,
  pickPriceTicks,
  placeLabels,
  PRICE_AXIS_TITLES,
  useWidth,
  type Label,
} from "./chart-kit";
import { FloatingCard, type AnchorRect } from "./FloatingCard";
import { FrontierPointCard } from "./ScoreCards";

// The top margin is tall enough to hold a label over the highest point.
const M = { top: 30, right: 22, bottom: 46, left: 46 };
const R_DOT = 3; // a point off the frontier
const R_FRONT = 4.5; // a frontier point, inside its ring
const R_RING = 7.5;
const R_PICK = 10;
// Two picks on one point (the same model at the same level) sit side by side.
const PICK_SPREAD = 2 * R_PICK + 3;

export interface ChartPick {
  priority: BudgetPriority;
  option: OptionView;
}

interface PickPoint {
  priority: BudgetPriority;
  // The pick's point among the frontier's own, or its own figures when it is
  // none of them (a model outside the viewer's).
  point: PlotPoint;
  plotted: boolean;
  dx: number;
}

export function PicksChart({
  frontier,
  yours,
  picks,
  selected = null,
  onSelect,
}: {
  // The points and the frontier over them (lib/frontier-points.ts).
  frontier: Frontier;
  // The points are the models this viewer's Settings reach, not the catalog.
  yours: boolean;
  // The picks to mark; none before a first recommendation.
  picks: ChartPick[];
  selected?: BudgetPriority | null;
  onSelect?: (p: BudgetPriority) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const width = useWidth(wrap);
  const [active, setActive] = useState<string | null>(null);

  const all = frontier.points;
  const line = useMemo(() => all.filter((p) => p.frontier), [all]);
  const models = useMemo(() => new Set(all.map((p) => p.row.id)).size, [all]);
  // The axis starts a round ten under the lowest frontier point and the
  // lowest pick, so the line the picks are read from fills the plot. A point
  // far under the whole frontier says nothing about a pick and is left off.
  const yLo = useMemo(() => {
    const floor = Math.min(
      ...line.map((p) => p.index),
      ...picks.flatMap((p) => (p.option.point ? [p.option.point.index] : p.option.aa !== null ? [p.option.aa] : [])),
    );
    return Number.isFinite(floor) ? Math.max(0, Math.floor((floor - 8) / 10) * 10) : 0;
  }, [line, picks]);
  const pts = useMemo(() => all.filter((p) => p.index >= yLo), [all, yLo]);
  const below = all.length - pts.length;
  // The answer says which points meet its task's bar, and some do not.
  const barShown = useMemo(() => frontier.served && pts.some((p) => !p.adequate), [frontier.served, pts]);

  const pickPts = useMemo(() => {
    const placed = picks.flatMap(({ priority, option: o }): PickPoint[] => {
      if (o.point) return [{ priority, point: o.point, plotted: true, dx: 0 }];
      if (!o.row || o.aa === null || o.price === null || !(o.price > 0)) return [];
      const own: PlotPoint = {
        key: `pick:${priority}`,
        row: o.row,
        level: null,
        index: o.aa,
        shown: o.aa,
        price: o.price,
        estimated: o.aaEstimated,
        adequate: true,
        frontier: false,
      };
      return [{ priority, point: own, plotted: false, dx: 0 }];
    });
    for (const p of placed) {
      const same = placed.filter((q) => q.point.key === p.point.key);
      p.dx = same.length > 1 ? (same.indexOf(p) - (same.length - 1) / 2) * PICK_SPREAD : 0;
    }
    return placed;
  }, [picks]);
  const unplotted = picks.filter((p) => !pickPts.some((q) => q.priority === p.priority));
  const pickedKeys = useMemo(() => new Set(pickPts.map((p) => p.point.key)), [pickPts]);

  const drawn = useMemo(
    () => [...pts, ...pickPts.filter((p) => !p.plotted).map((p) => p.point)],
    [pts, pickPts],
  );
  const height = width > 0 && width < 640 ? 340 : 440;
  const plotW = Math.max(40, width - M.left - M.right);
  const plotH = height - M.top - M.bottom;
  const xs = drawn.map((p) => Math.log10(p.price));
  const span = xs.length ? Math.max(...xs) - Math.min(...xs) : 1;
  const pad = Math.max(0.06, span * 0.04);
  const x0 = (xs.length ? Math.min(...xs) : 0) - pad;
  const x1 = (xs.length ? Math.max(...xs) : 1) + pad;
  const indexes = drawn.map((p) => p.index);
  const yHi = indexes.length ? Math.min(100, Math.ceil((Math.max(...indexes) + 2) / 10) * 10) : 100;
  // A log10 price to its x, and a price to its x.
  const lx = useCallback((x: number) => M.left + ((x - x0) / (x1 - x0)) * plotW, [x0, x1, plotW]);
  const sx = useCallback((price: number) => lx(Math.log10(price)), [lx]);
  const sy = useCallback(
    (y: number) => M.top + plotH - ((y - yLo) / Math.max(1, yHi - yLo)) * plotH,
    [yLo, yHi, plotH],
  );

  const stepPath = useMemo(() => {
    if (line.length === 0) return "";
    let d = `M ${sx(line[0].price)} ${sy(line[0].index)}`;
    for (const f of line.slice(1)) d += ` H ${sx(f.price)} V ${sy(f.index)}`;
    return `${d} H ${M.left + plotW}`;
  }, [line, sx, sy, plotW]);

  // One name per frontier model: a picked model at the point it was picked
  // at, with its level; any other at its top frontier point. Every other dot
  // keeps its clearance and no label.
  const labelled = useMemo(() => {
    const out = new Map<string, { text: string; pick: boolean; priority: number }>();
    const pickedModels = new Set<string>();
    for (const p of pickPts) {
      if (!p.plotted || !p.point.frontier) continue;
      pickedModels.add(p.point.row.id);
      out.set(p.point.key, {
        text: pointName(p.point),
        pick: true,
        priority: 3000 + (p.priority === selected ? 100 : 0),
      });
    }
    const top = new Map<string, PlotPoint>();
    for (const f of line) {
      if (pickedModels.has(f.row.id) || f.index < yLo) continue;
      const best = top.get(f.row.id);
      if (!best || f.index > best.index) top.set(f.row.id, f);
    }
    for (const f of top.values()) out.set(f.key, { text: f.row.name, pick: false, priority: 1000 + f.index });
    return out;
  }, [pickPts, line, selected, yLo]);

  const labels = useMemo(() => {
    if (width === 0) return new Map<string, Label>();
    return placeLabels(
      drawn.map((p) => {
        const label = labelled.get(p.key);
        // A model named at its top frontier point may be named at any of
        // its frontier points instead, where that one is crowded.
        const others =
          label && !label.pick
            ? line.filter((f) => f.row.id === p.row.id && f.key !== p.key && f.index >= yLo).reverse()
            : [];
        return {
          id: p.key,
          cx: sx(p.price),
          cy: sy(p.index),
          text: label?.text ?? "",
          priority: label?.priority ?? 0,
          label: label !== undefined,
          r: pickedKeys.has(p.key) ? R_PICK + 4 : p.frontier ? R_RING : R_DOT,
          ...(others.length > 0
            ? { anchors: [p, ...others].map((f) => ({ cx: sx(f.price), cy: sy(f.index) })) }
            : {}),
        };
      }),
      // Into the top margin: a label may sit over the highest point.
      { x: M.left + 2, y: 2, w: plotW - 4, h: M.top + plotH - 4 },
      Math.max(4, Math.min(16, Math.floor(plotW / 70))),
      R_RING,
    );
  }, [drawn, labelled, pickedKeys, line, yLo, width, sx, sy, plotW, plotH]);

  useEffect(() => {
    if (!active) return;
    const away = (e: PointerEvent) => {
      if (svgRef.current && !svgRef.current.contains(e.target as Node)) setActive(null);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setActive(null);
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [active]);

  const xTicks = useMemo(
    () => (width === 0 ? [] : pickPriceTicks(x0, x1, lx, M.left, plotW)),
    [width, x0, x1, lx, plotW],
  );
  const yTicks: number[] = [];
  for (let v = yLo; v <= yHi; v += 10) yTicks.push(v);

  const activePt = active ? drawn.find((p) => p.key === active) : undefined;
  const getAnchor = (): AnchorRect | null => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r || !activePt) return null;
    return { left: r.left + sx(activePt.price) - 8, top: r.top + sy(activePt.index) - 8, width: 16, height: 16 };
  };
  // A point as /models' card reads a model, and the point that leads it.
  const cardRow = (p: PlotPoint): SlimRow => {
    if (frontier.byKey.has(p.key)) return pointRow(frontier, p);
    // A pick plotted at its own figures: the row its card already reads.
    const lead = leaderAt(frontier, p);
    return { ...p.row, value_frontier: false, value_beaten_by: lead ? lead.key : null };
  };
  const cardLeader = (p: PlotPoint): SlimRow | null => {
    const lead = p.frontier ? null : leaderAt(frontier, p);
    return lead ? pointRow(frontier, lead) : null;
  };

  // A model's efforts, joined lowest to highest: drawn for the selected pick
  // and for the point under the pointer.
  const pathOf = useCallback((id: string) => pts.filter((p) => p.row.id === id), [pts]);
  const selectedPick = pickPts.find((p) => p.priority === selected && p.plotted);
  const selectedPath = selectedPick ? pathOf(selectedPick.point.row.id) : [];
  const activePath =
    activePt && activePt.row.id !== selectedPick?.point.row.id ? pathOf(activePt.row.id) : [];

  if (all.length < 2) return null;

  const hasPicks = pickPts.length > 0;
  const scope = yours ? "models you can use" : "measured models";
  const possessive = yours ? "your" : "the";

  return (
    <figure
      className="min-w-0 rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40"
      data-testid="picks-chart"
      data-served={frontier.served ? "1" : "0"}
    >
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-5 py-3">
        <span className="inline-flex items-center gap-2 text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100">
          <span className="inline-block h-2.5 w-2.5 rounded-full border-2" style={{ borderColor: FRONTIER }} />
          {hasPicks ? "Where the picks sit" : yours ? "Your cost/quality frontier" : "The cost/quality frontier"}
        </span>
        <span className="text-xs tabular-nums text-brand-slate-500 dark:text-brand-slate-400" data-testid="picks-chart-scope">
          {models} {scope} · {all.length} effort settings · {line.length} on {possessive} frontier
        </span>
      </figcaption>

      <div className="space-y-4 border-t border-brand-slate-200 px-5 py-5 dark:border-brand-slate-700">
        <div className="rounded-lg border border-brand-slate-200 bg-white px-3 pb-2 pt-3 dark:border-brand-slate-700 dark:bg-brand-slate-900 sm:px-4">
          <div ref={wrap} className="w-full" style={{ height }}>
            {width > 0 && (
              <svg
                ref={svgRef}
                width={width}
                height={height}
                role="group"
                aria-label={
                  `${models} ${scope}, each at its effort settings, by price and AA Intelligence Index. ` +
                  `The cost/quality frontier passes through ${line.length} of the ${all.length} points` +
                  (hasPicks
                    ? `. The picks: ${pickPts
                        .map(
                          (p) =>
                            `${PRIORITY_LABEL[p.priority].label} ${pointName(p.point)}, AA ${p.point.shown}, ${formatUsd(p.point.price)} per 1M`,
                        )
                        .join("; ")}.`
                    : ".")
                }
                className="block touch-manipulation select-none text-brand-slate-400 dark:text-brand-slate-500"
              >
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

                {/* The efforts of the model under the pointer, then of the
                    selected pick's model. */}
                {activePath.length > 1 && (
                  <polyline
                    points={activePath.map((p) => `${sx(p.price)},${sy(p.index)}`).join(" ")}
                    fill="none"
                    stroke="currentColor"
                    strokeOpacity={0.7}
                    strokeWidth={1.25}
                    pointerEvents="none"
                    data-testid="picks-chart-effort-path"
                    data-path="active"
                  />
                )}
                {selectedPath.length > 1 && (
                  <polyline
                    points={selectedPath.map((p) => `${sx(p.price)},${sy(p.index)}`).join(" ")}
                    fill="none"
                    strokeOpacity={0.6}
                    strokeWidth={1.5}
                    pointerEvents="none"
                    className="stroke-brand-accent"
                    data-testid="picks-chart-effort-path"
                    data-path="selected"
                  />
                )}

                {/* Every point off the frontier: small and quiet, hollow when
                    it is below the task's bar. */}
                {pts.map((p) => {
                  if (p.frontier || pickedKeys.has(p.key)) return null;
                  const sameModel =
                    (activePt && activePt.row.id === p.row.id) || selectedPick?.point.row.id === p.row.id;
                  const paint = sameModel
                    ? p.adequate
                      ? "fill-brand-slate-600 dark:fill-brand-slate-300"
                      : "fill-transparent stroke-brand-slate-600 dark:stroke-brand-slate-300"
                    : p.adequate
                      ? "fill-brand-slate-400 dark:fill-brand-slate-500"
                      : "fill-transparent stroke-brand-slate-400 dark:stroke-brand-slate-500";
                  return (
                    <circle
                      key={p.key}
                      cx={sx(p.price)}
                      cy={sy(p.index)}
                      r={sameModel ? R_DOT + 0.75 : R_DOT}
                      pointerEvents="none"
                      opacity={activePt && !sameModel ? 0.35 : sameModel ? 1 : 0.65}
                      strokeWidth={p.adequate ? 0 : 1.25}
                      className={paint}
                    />
                  );
                })}

                {/* The frontier line, then its points. */}
                <path
                  d={stepPath}
                  fill="none"
                  stroke={FRONTIER}
                  strokeWidth={2.5}
                  strokeDasharray="0.5 6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  pointerEvents="none"
                  data-testid="picks-chart-frontier"
                  data-frontier-keys={line.map((f) => f.key).join(",")}
                />
                {line.map((p) => {
                  if (pickedKeys.has(p.key)) return null;
                  const dim = activePt && activePt.key !== p.key;
                  return (
                    <g key={p.key} pointerEvents="none" opacity={dim ? 0.45 : 1}>
                      <circle cx={sx(p.price)} cy={sy(p.index)} r={R_RING} fill="none" stroke={FRONTIER} strokeWidth={1.75} />
                      {p.adequate ? (
                        <circle
                          cx={sx(p.price)}
                          cy={sy(p.index)}
                          r={R_FRONT}
                          fill={FRONTIER}
                          strokeWidth={1.25}
                          className="stroke-white dark:stroke-brand-slate-900"
                        />
                      ) : (
                        <circle cx={sx(p.price)} cy={sy(p.index)} r={R_FRONT - 1.75} fill="none" stroke={FRONTIER} strokeWidth={1.25} />
                      )}
                    </g>
                  );
                })}

                {/* Labels: frontier models only, on plates so a line under
                    the text never hurts it. */}
                {[...labels.entries()].map(([id, l]) => {
                  const isPick = labelled.get(id)?.pick === true;
                  const dim = activePt && activePt.key !== id;
                  return (
                    <g
                      key={`label-${id}`}
                      pointerEvents="none"
                      opacity={dim ? 0.4 : 1}
                      data-testid="picks-chart-label"
                      data-key={id}
                      data-pick={isPick ? "1" : "0"}
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
                        fontWeight={isPick ? 650 : 500}
                        className={
                          isPick
                            ? "fill-brand-accent dark:fill-blue-400"
                            : "fill-brand-slate-700 dark:fill-brand-slate-200"
                        }
                      >
                        {l.text}
                      </text>
                    </g>
                  );
                })}

                {/* The picks: lettered, the selected one filled. */}
                {pickPts.map((p) => {
                  const isSel = p.priority === selected;
                  const cx = sx(p.point.price) + p.dx;
                  const cy = sy(p.point.index);
                  const r = isSel ? R_PICK + 1.5 : R_PICK;
                  return (
                    <g
                      key={`pick-${p.priority}`}
                      pointerEvents="none"
                      opacity={activePt && activePt.key !== p.point.key ? 0.6 : 1}
                    >
                      {p.plotted && p.point.frontier && (
                        <circle cx={cx} cy={cy} r={r + 3.5} fill="none" stroke={FRONTIER} strokeWidth={2} />
                      )}
                      <circle
                        cx={cx}
                        cy={cy}
                        r={r}
                        strokeWidth={2}
                        className={
                          isSel
                            ? "fill-brand-accent stroke-white dark:stroke-brand-slate-900"
                            : "fill-white stroke-brand-accent dark:fill-brand-slate-900 dark:stroke-blue-400"
                        }
                      />
                      <text
                        x={cx}
                        y={cy + 3.75}
                        textAnchor="middle"
                        fontSize={10.5}
                        fontWeight={700}
                        className={isSel ? "fill-white" : "fill-brand-accent dark:fill-blue-400"}
                      >
                        {PRIORITY_LABEL[p.priority].letter}
                      </text>
                    </g>
                  );
                })}

                {/* Hit targets on top: bigger than the dots, easy to hover
                    and tap. A pick and a frontier point take keyboard focus. */}
                {[
                  ...pts
                    .filter((p) => !pickedKeys.has(p.key))
                    .map((p) => ({ point: p, pick: null as BudgetPriority | null, dx: 0 })),
                  ...pickPts.map((p) => ({ point: p.point, pick: p.priority as BudgetPriority | null, dx: p.dx })),
                ].map(({ point: p, pick, dx }) => (
                  <circle
                    key={`hit-${p.key}${pick ? `-${pick}` : ""}`}
                    cx={sx(p.price) + dx}
                    cy={sy(p.index)}
                    r={pick ? 14 : p.frontier ? 10 : 7}
                    fill="transparent"
                    tabIndex={pick || p.frontier ? 0 : -1}
                    role="button"
                    aria-label={`${pick ? `${PRIORITY_LABEL[pick].label} pick: ` : ""}${pointName(p)}, AA Index ${p.estimated ? "about " : ""}${p.shown}, ${formatUsd(p.price)} per 1M tokens at its effort's token use${p.frontier ? ", on the cost/quality frontier" : ""}${barShown && !p.adequate ? ", below this task's bar" : ""}`}
                    data-testid={pick ? "picks-chart-pick" : "picks-chart-point"}
                    data-model-id={p.row.id}
                    data-key={p.key}
                    data-frontier={p.frontier ? "1" : "0"}
                    data-adequate={p.adequate ? "1" : "0"}
                    data-pick={pick ?? undefined}
                    className="cursor-pointer outline-none"
                    onPointerEnter={(e) => {
                      if (e.pointerType === "mouse") setActive(p.key);
                    }}
                    onPointerLeave={(e) => {
                      if (e.pointerType === "mouse") setActive(null);
                    }}
                    onClick={() => {
                      setActive(p.key);
                      if (pick && onSelect) onSelect(pick);
                    }}
                    onFocus={(e) => {
                      if (e.currentTarget.matches(":focus-visible")) setActive(p.key);
                    }}
                    onBlur={() => setActive(null)}
                  />
                ))}

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

        <ul className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-brand-slate-600 dark:text-brand-slate-300">
          {hasPicks && (
            <li className="inline-flex items-center gap-1.5">
              <LegendSwatch>
                <circle cx={11} cy={7} r={6.5} className="fill-brand-accent" />
                <text x={11} y={10.25} textAnchor="middle" fontSize={8.5} fontWeight={700} className="fill-white">
                  {PRIORITY_LABEL.balanced.letter}
                </text>
              </LegendSwatch>
              A pick: {PRIORITY_LABEL.cheap.letter} Cost, {PRIORITY_LABEL.balanced.letter} Balanced,{" "}
              {PRIORITY_LABEL.best.letter} Quality
            </li>
          )}
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <circle cx={11} cy={7} r={3.5} fill={FRONTIER} />
              <circle cx={11} cy={7} r={6} fill="none" stroke={FRONTIER} strokeWidth={1.5} />
            </LegendSwatch>
            On {possessive} frontier
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <path d="M 1 11 H 9 V 3 H 21" fill="none" stroke={FRONTIER} strokeWidth={2} strokeDasharray="0.5 4" strokeLinecap="round" />
            </LegendSwatch>
            Frontier: the top score at each price
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <circle cx={11} cy={7} r={3} className="fill-brand-slate-400 dark:fill-brand-slate-500" />
            </LegendSwatch>
            A model at one effort
          </li>
          {barShown && (
            <li className="inline-flex items-center gap-1.5" data-testid="picks-chart-bar-legend">
              <LegendSwatch>
                <circle
                  cx={11}
                  cy={7}
                  r={3}
                  fill="none"
                  strokeWidth={1.25}
                  className="stroke-brand-slate-400 dark:stroke-brand-slate-500"
                />
              </LegendSwatch>
              Hollow: below this task&rsquo;s bar
            </li>
          )}
          <li className="text-brand-slate-500 dark:text-brand-slate-400">Hover or tap any dot for its numbers.</li>
        </ul>

        <p className="max-w-4xl text-sm leading-6 text-brand-slate-600 dark:text-brand-slate-300">
          Each dot is a model {yours ? "you can run" : "in the catalog"} at one effort
          {frontier.served ? " this task may run" : " Artificial Analysis measured it at"}: a higher effort scores
          higher and writes more tokens, so the same model sits up and to the right.{" "}
          <strong>
            The green points are {possessive} cost/quality frontier: each one scores higher than every other
            point at its price or less.
          </strong>{" "}
          The dotted line joins them, so its height at any price is the top AA Index that price buys
          {yours ? " you" : ""}.{" "}
          {hasPicks ? (
            <>
              The picks are read from that line: Cost is the cheapest point that meets the task&rsquo;s bar
              {barShown ? " (a filled dot)" : ""}, Quality the strongest, and Balanced the best value between
              them.
            </>
          ) : (
            <>
              A recommendation reads its three picks from that line: the cheapest point that meets the task&rsquo;s
              bar, the strongest, and the best value between them.
            </>
          )}
          {!yours && (
            <>
              {" "}
              <Link href="/settings" className="font-medium text-brand-accent hover:underline">
                Save your plans in Settings
              </Link>{" "}
              to draw it over the models you can use.
            </>
          )}
        </p>

        {(unplotted.length > 0 || below > 0) && (
          <p className="text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
            {below > 0 && (
              <span data-testid="picks-chart-below">
                The axis starts at {yLo}: {below} more effort {below === 1 ? "setting scores" : "settings score"}{" "}
                under it, far below the frontier.{" "}
              </span>
            )}
            {unplotted.length > 0 && (
              <span data-testid="picks-chart-unplotted">
                Not plotted: {unplotted.map((p) => p.option.model).join(", ")} (no AA Index yet).
              </span>
            )}
          </p>
        )}
      </div>

      {activePt && (
        <FloatingCard getAnchor={getAnchor} placement="side" testId="picks-chart-card">
          <FrontierPointCard model={cardRow(activePt)} leader={cardLeader(activePt)} />
        </FloatingCard>
      )}
    </figure>
  );
}
