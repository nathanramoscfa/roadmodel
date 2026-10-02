// web/components/PicksChart.tsx
//
// Where the three picks sit in the market: every measured catalog model at
// its blended price (x, log scale) and AA Intelligence Index (y), the green
// cost/quality frontier stepping up through the models nothing beats for
// less, and the picks drawn large and named. It shows in one glance what the
// Cost, Balanced and Quality picks trade: how many AA Index points each step
// up buys, and at what price. The same chart, at full size and with every
// filter, is on /models.
//
// Hover (mouse), tap (touch) or tab to (keyboard) any dot for the card /models
// shows for it; a click elsewhere or Escape closes it.
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { blendedPrice, formatUsd } from "@/lib/benchmark-grid";
import type { PriorityRecommendation } from "@/lib/api";
import type { SlimRow } from "@/lib/recommend-picks";
import { FRONTIER, LABEL_PX, pickPriceTicks, placeLabels, useWidth } from "./chart-kit";
import { FloatingCard, type AnchorRect } from "./FloatingCard";
import { FrontierPointCard } from "./ScoreCards";

const M = { top: 14, right: 16, bottom: 40, left: 40 };
const PICK_LABEL: Record<string, string> = { cheap: "Cost", balanced: "Balanced", best: "Quality" };

interface Pt {
  row: SlimRow;
  x: number;
  index: number;
}

function toPt(row: SlimRow): Pt | null {
  if (row.aa_index === null) return null;
  return { row, x: Math.log10(blendedPrice(row.input_price_per_1m, row.output_price_per_1m)), index: row.aa_index };
}

export interface ChartPick {
  priority: PriorityRecommendation["priority"];
  row: SlimRow | null;
  model: string;
}

export function PicksChart({
  rows,
  picks,
  selected,
  onSelect,
}: {
  rows: SlimRow[];
  picks: ChartPick[];
  selected: PriorityRecommendation["priority"];
  onSelect: (p: PriorityRecommendation["priority"]) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const width = useWidth(wrap);
  const [active, setActive] = useState<string | null>(null);

  const pts = useMemo(() => rows.flatMap((r) => toPt(r) ?? []).sort((a, b) => a.x - b.x), [rows]);
  const frontier = useMemo(() => pts.filter((p) => p.row.value_frontier), [pts]);
  const pickPts = useMemo(
    () =>
      picks.flatMap((p) => {
        const pt = p.row ? toPt(p.row) : null;
        return pt ? [{ ...pt, priority: p.priority }] : [];
      }),
    [picks],
  );
  const unmeasured = picks.filter((p) => !p.row || p.row.aa_index === null);
  const byId = useMemo(() => new Map(rows.map((r) => [r.id, r])), [rows]);

  const height = width > 0 && width < 520 ? 260 : 300;
  const plotW = Math.max(40, width - M.left - M.right);
  const plotH = height - M.top - M.bottom;
  const xs = pts.map((p) => p.x);
  const x0 = Math.min(...xs) - 0.08;
  const x1 = Math.max(...xs) + 0.08;
  const yHi = Math.min(100, Math.ceil((Math.max(...pts.map((p) => p.index)) + 4) / 10) * 10);
  const sx = useCallback((x: number) => M.left + ((x - x0) / (x1 - x0)) * plotW, [x0, x1, plotW]);
  const sy = useCallback((y: number) => M.top + plotH - (y / yHi) * plotH, [yHi, plotH]);

  const stepPath = useMemo(() => {
    if (frontier.length === 0) return "";
    let d = `M ${sx(frontier[0].x)} ${sy(frontier[0].index)}`;
    for (const f of frontier.slice(1)) d += ` H ${sx(f.x)} V ${sy(f.index)}`;
    return `${d} H ${sx(x1)}`;
  }, [frontier, sx, sy, x1]);

  const labels = useMemo(() => {
    if (width === 0) return new Map();
    return placeLabels(
      [
        ...pickPts.map((p) => ({
          id: `pick-${p.priority}`,
          cx: sx(p.x),
          cy: sy(p.index),
          text: `${PICK_LABEL[p.priority]}: ${p.row.name}`,
          priority: 2000 + (p.priority === selected ? 100 : 0),
        })),
        // The other frontier models' names, while there is room; a pick on
        // the frontier is already named by its pick label.
        ...frontier
          .filter((f) => !pickPts.some((p) => p.row.id === f.row.id))
          .map((f) => ({
          id: f.row.id,
          cx: sx(f.x),
          cy: sy(f.index),
          text: f.row.name,
          priority: 100 + f.index,
          })),
      ],
      { x: M.left + 2, y: M.top + 2, w: plotW - 4, h: plotH - 4 },
      Math.max(3, Math.min(9, Math.floor(plotW / 80))),
      7,
    );
  }, [pickPts, frontier, width, sx, sy, plotW, plotH, selected]);

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
    () => (width === 0 ? [] : pickPriceTicks(x0, x1, sx, M.left, plotW)),
    [width, x0, x1, sx, plotW],
  );
  const yTicks: number[] = [];
  for (let v = 0; v <= yHi; v += 10) yTicks.push(v);

  const activePt = active ? pts.find((p) => p.row.id === active) : undefined;
  const getAnchor = (): AnchorRect | null => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r || !activePt) return null;
    return { left: r.left + sx(activePt.x) - 8, top: r.top + sy(activePt.index) - 8, width: 16, height: 16 };
  };
  const pickIds = new Map(pickPts.map((p) => [p.row.id, p.priority]));

  if (pts.length < 2) return null;

  return (
    <figure
      className="min-w-0 rounded-lg border border-brand-slate-200 bg-white px-4 pb-3 pt-3.5 dark:border-brand-slate-700 dark:bg-brand-slate-900"
      data-testid="picks-chart"
    >
      <figcaption className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <span className="text-sm font-semibold text-brand-slate-900 dark:text-brand-slate-50">
          Where the picks sit
        </span>
        <span className="text-xs text-brand-slate-500 dark:text-brand-slate-400">
          {pts.length} measured models · price vs AA Index
        </span>
      </figcaption>

      <div ref={wrap} className="mt-2 w-full" style={{ height }}>
        {width > 0 && (
          <svg
            ref={svgRef}
            width={width}
            height={height}
            role="group"
            aria-label={`The picks among ${pts.length} measured models by blended price and AA Intelligence Index: ${pickPts
              .map((p) => `${PICK_LABEL[p.priority]} ${p.row.name}, AA ${p.index}, ${formatUsd(10 ** p.x)} per 1M`)
              .join("; ")}.`}
            className="block touch-manipulation select-none text-brand-slate-400 dark:text-brand-slate-500"
          >
            {yTicks.map((v) => (
              <g key={v}>
                <line x1={M.left} x2={M.left + plotW} y1={sy(v)} y2={sy(v)} stroke="currentColor" strokeOpacity={v === 0 ? 0.5 : 0.16} />
                <text x={M.left - 7} y={sy(v) + 4} textAnchor="end" fontSize={11} className="fill-brand-slate-500 tabular-nums dark:fill-brand-slate-400">
                  {v}
                </text>
              </g>
            ))}
            {xTicks.map(({ v, px }) => (
              <text key={v} x={px} y={M.top + plotH + 17} textAnchor="middle" fontSize={11} className="fill-brand-slate-500 tabular-nums dark:fill-brand-slate-400">
                {formatUsd(v)}
              </text>
            ))}
            <text x={M.left + plotW / 2} y={height - 4} textAnchor="middle" fontSize={11} className="fill-brand-slate-500 dark:fill-brand-slate-400">
              Blended price, $ per 1M tokens (log scale)
            </text>

            <path d={stepPath} fill="none" stroke={FRONTIER} strokeWidth={2.2} strokeDasharray="0.5 6" strokeLinecap="round" pointerEvents="none" />

            {pts.map((p) => {
              if (pickIds.has(p.row.id)) return null;
              const onFrontier = p.row.value_frontier;
              return (
                <g key={p.row.id} pointerEvents="none" opacity={activePt && activePt !== p ? 0.45 : 1}>
                  {onFrontier && <circle cx={sx(p.x)} cy={sy(p.index)} r={6} fill="none" stroke={FRONTIER} strokeWidth={1.5} />}
                  <circle
                    cx={sx(p.x)}
                    cy={sy(p.index)}
                    r={3.5}
                    fill={onFrontier ? FRONTIER : undefined}
                    className={onFrontier ? "" : "fill-brand-slate-300 dark:fill-brand-slate-600"}
                  />
                </g>
              );
            })}

            {pickPts.map((p) => {
              const isSel = p.priority === selected;
              return (
                <g key={`pick-${p.priority}`} pointerEvents="none">
                  {p.row.value_frontier && (
                    <circle cx={sx(p.x)} cy={sy(p.index)} r={isSel ? 11.5 : 10} fill="none" stroke={FRONTIER} strokeWidth={2} />
                  )}
                  <circle
                    cx={sx(p.x)}
                    cy={sy(p.index)}
                    r={isSel ? 8 : 6.5}
                    strokeWidth={2}
                    className={
                      (isSel ? "fill-brand-accent " : "fill-brand-accent/60 ") + "stroke-white dark:stroke-brand-slate-900"
                    }
                  />
                </g>
              );
            })}

            {[...labels.entries()].map(([id, l]) => {
              const isPick = String(id).startsWith("pick-");
              return (
                <g key={`label-${id}`} pointerEvents="none">
                  <rect x={l.box.x} y={l.box.y} width={l.box.w} height={l.box.h} rx={3} className="fill-white/90 dark:fill-brand-slate-900/90" />
                  <text
                    x={l.x}
                    y={l.y}
                    textAnchor={l.anchor}
                    fontSize={LABEL_PX}
                    fontWeight={isPick ? 650 : 400}
                    className={isPick ? "fill-brand-accent" : "fill-brand-slate-500 dark:fill-brand-slate-400"}
                  >
                    {l.text}
                  </text>
                </g>
              );
            })}

            {pts.map((p) => {
              const pick = pickIds.get(p.row.id);
              return (
                <circle
                  key={`hit-${p.row.id}`}
                  cx={sx(p.x)}
                  cy={sy(p.index)}
                  r={pick ? 12 : 8}
                  fill="transparent"
                  tabIndex={0}
                  role="button"
                  aria-label={`${pick ? `${PICK_LABEL[pick]} pick: ` : ""}${p.row.name}, AA Index ${p.index}, blended ${formatUsd(10 ** p.x)} per 1M tokens`}
                  data-testid={pick ? "picks-chart-pick" : "picks-chart-point"}
                  data-model-id={p.row.id}
                  className="cursor-pointer outline-none"
                  onPointerEnter={(e) => {
                    if (e.pointerType === "mouse") setActive(p.row.id);
                  }}
                  onPointerLeave={(e) => {
                    if (e.pointerType === "mouse") setActive(null);
                  }}
                  onClick={() => {
                    setActive(p.row.id);
                    if (pick) onSelect(pick);
                  }}
                  onFocus={(e) => {
                    if (e.currentTarget.matches(":focus-visible")) setActive(p.row.id);
                  }}
                  onBlur={() => setActive(null)}
                />
              );
            })}
          </svg>
        )}
      </div>

      <p className="mt-1 text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
        The dotted green line is the cost/quality frontier: its height at any price is the top AA
        Index that price buys. Grey dots are the rest of the catalog.
        {unmeasured.length > 0 &&
          ` Not plotted: ${unmeasured.map((p) => p.model).join(", ")} (no AA Index yet).`}
      </p>

      {activePt && (
        <FloatingCard getAnchor={getAnchor} placement="side" testId="picks-chart-card">
          <FrontierPointCard
            model={activePt.row}
            leader={activePt.row.value_beaten_by ? (byId.get(activePt.row.value_beaten_by) ?? null) : null}
          />
        </FloatingCard>
      )}
    </figure>
  );
}
