// web/components/PicksChart.tsx
//
// Where the three picks sit in the market. A pick runs a model at an effort,
// and Artificial Analysis measures a reasoning model at each effort
// separately, so every model appears at each effort AA measured it at (x:
// blended price times its measured token use there, log scale; y: its AA
// Intelligence Index there), joined by a faint line, and the green
// cost/quality frontier steps up through the points nothing beats for less:
// the frontier the picks are read from (roadmodel scoring.effort_settings,
// lib/pick-effort.ts). The picks are drawn large, each at the effort it runs.
// For a viewer with saved Settings the points and the frontier are the models
// they can run (PicksData.pool), and the rest of the catalog stays faintly in
// the background. /models plots each model once, at its headline figures.
//
// Hover (mouse), tap (touch) or tab to (keyboard) any dot for the card /models
// shows for it; a click elsewhere or Escape closes it.
"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { blendedPrice, formatUsd, paretoFrontier } from "@/lib/benchmark-grid";
import type { PriorityRecommendation } from "@/lib/api";
import { effortLabel, effortPoints, named, type EffortLevel } from "@/lib/pick-effort";
import type { SlimRow } from "@/lib/recommend-picks";
import { FRONTIER, LABEL_PX, pickPriceTicks, placeLabels, useWidth } from "./chart-kit";
import { FloatingCard, type AnchorRect } from "./FloatingCard";
import { FrontierPointCard } from "./ScoreCards";

const M = { top: 14, right: 16, bottom: 40, left: 40 };
const PICK_LABEL: Record<string, string> = { cheap: "Cost", balanced: "Balanced", best: "Quality" };

interface Pt {
  // The model and effort, unique per point.
  key: string;
  row: SlimRow;
  level: EffortLevel | null;
  x: number;
  index: number;
  price: number;
}

// A model's points: one per effort AA measured, else its headline figure.
function ptsOf(row: SlimRow): Pt[] {
  return effortPoints(row).map((p) => ({
    key: `${row.id}@${p.level ?? "-"}`,
    row,
    level: p.level,
    x: Math.log10(p.price),
    index: p.index,
    price: p.price,
  }));
}

function nameOf(p: Pt): string {
  return p.level ? `${p.row.name} · ${effortLabel(p.level)}` : p.row.name;
}

// The point a pick runs at: its effort's, where AA measured it, else the
// model's headline figure at list price.
function pickPt(row: SlimRow, level: EffortLevel | null): Pt | null {
  const at = ptsOf(row).find((p) => p.level === level && level !== null);
  if (at) return at;
  if (row.aa_index === null) return null;
  const price = blendedPrice(row.input_price_per_1m, row.output_price_per_1m);
  return { key: `${row.id}@-`, row, level: null, x: Math.log10(price), index: row.aa_index, price };
}

export interface ChartPick {
  priority: PriorityRecommendation["priority"];
  row: SlimRow | null;
  model: string;
  // The effort the pick runs at (lib/pick-effort.ts pickEffort).
  level: EffortLevel | null;
}

export function PicksChart({
  rows,
  pool,
  picks,
  selected,
  onSelect,
}: {
  rows: SlimRow[];
  // The ids of the models the viewer can run; null for the whole catalog.
  pool: string[] | null;
  picks: ChartPick[];
  selected: PriorityRecommendation["priority"];
  onSelect: (p: PriorityRecommendation["priority"]) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const width = useWidth(wrap);
  const [active, setActive] = useState<string | null>(null);

  const all = useMemo(() => rows.flatMap(ptsOf).sort((a, b) => a.x - b.x), [rows]);
  const pts = useMemo(() => {
    if (!pool) return all;
    const mine = new Set(pool);
    return all.filter((p) => mine.has(p.row.id));
  }, [all, pool]);
  const models = useMemo(() => new Set(pts.map((p) => p.row.id)).size, [pts]);
  // Catalog models outside the viewer's Settings: context, not candidates.
  const outside = useMemo(() => (pool ? all.filter((p) => !pts.includes(p)) : []), [all, pts, pool]);
  const onFrontier = useMemo(() => paretoFrontier(pts), [pts]);
  const frontier = useMemo(() => pts.filter((p) => onFrontier.has(p)), [pts, onFrontier]);
  // Each model's efforts, joined lowest to highest.
  const paths = useMemo(() => {
    const byModel = new Map<string, Pt[]>();
    for (const p of pts) byModel.set(p.row.id, [...(byModel.get(p.row.id) ?? []), p]);
    return [...byModel.values()].filter((ps) => ps.length > 1);
  }, [pts]);
  const pickPts = useMemo(
    () =>
      picks.flatMap((p) => {
        const pt = p.row ? pickPt(p.row, p.level) : null;
        return pt ? [{ ...pt, priority: p.priority }] : [];
      }),
    [picks],
  );
  const unmeasured = picks.filter((p) => !p.row || p.row.aa_index === null);
  // The point that beats p: the strongest at its price or less that scores higher.
  const leaderOf = useCallback(
    (p: Pt): Pt | null =>
      pts
        .filter((q) => q.price <= p.price + 1e-9 && q.index > p.index)
        .sort((a, b) => b.index - a.index || a.price - b.price)[0] ?? null,
    [pts],
  );
  // A point as /models' card reads a model: named for its effort, its AA
  // Index and frontier mark there.
  const asRow = useCallback(
    (p: Pt): SlimRow => {
      const base = p.level ? named(p.row, p.level, p.index) : p.row;
      const leader = leaderOf(p);
      return { ...base, value_frontier: leader === null, value_beaten_by: leader ? leader.key : null };
    },
    [leaderOf],
  );

  const height = width > 0 && width < 520 ? 260 : 300;
  const plotW = Math.max(40, width - M.left - M.right);
  const plotH = height - M.top - M.bottom;
  const xs = all.map((p) => p.x);
  const x0 = Math.min(...xs) - 0.08;
  const x1 = Math.max(...xs) + 0.08;
  const yHi = Math.min(100, Math.ceil((Math.max(...all.map((p) => p.index)) + 4) / 10) * 10);
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
          text: `${PICK_LABEL[p.priority]}: ${nameOf(p)}`,
          priority: 2000 + (p.priority === selected ? 100 : 0),
        })),
        // The other frontier models' names, while there is room; a pick on
        // the frontier is already named by its pick label.
        ...frontier
          .filter((f) => !pickPts.some((p) => p.key === f.key))
          .map((f) => ({
            id: f.key,
            cx: sx(f.x),
            cy: sy(f.index),
            text: nameOf(f),
            priority: 100 + f.index,
            // With a point per effort the frontier is dense; its dots must
            // not crowd the picks' names out.
            dot: false,
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

  const activePt = active
    ? (pts.find((p) => p.key === active) ?? pickPts.find((p) => p.key === active))
    : undefined;
  const getAnchor = (): AnchorRect | null => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r || !activePt) return null;
    return { left: r.left + sx(activePt.x) - 8, top: r.top + sy(activePt.index) - 8, width: 16, height: 16 };
  };
  const pickKeys = new Map(pickPts.map((p) => [p.key, p.priority]));

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
        <span className="text-xs text-brand-slate-500 dark:text-brand-slate-400" data-testid="picks-chart-scope">
          {pool ? `${models} models you can use` : `${models} measured models`} · each at its measured efforts
        </span>
      </figcaption>

      <div ref={wrap} className="mt-2 w-full" style={{ height }}>
        {width > 0 && (
          <svg
            ref={svgRef}
            width={width}
            height={height}
            role="group"
            aria-label={`The picks among ${models} ${pool ? "models you can use" : "measured models"}, each at its measured efforts, by price and AA Intelligence Index: ${pickPts
              .map((p) => `${PICK_LABEL[p.priority]} ${nameOf(p)}, AA ${p.index}, ${formatUsd(p.price)} per 1M`)
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
              {"Blended price × measured token use, $ per 1M (log scale)"}
            </text>

            {outside.map((p) => (
              <circle
                key={`outside-${p.key}`}
                cx={sx(p.x)}
                cy={sy(p.index)}
                r={3}
                fill="none"
                stroke="currentColor"
                strokeOpacity={0.45}
                pointerEvents="none"
                data-testid="picks-chart-outside"
              />
            ))}

            {paths.map((ps) => (
              <polyline
                key={`path-${ps[0].row.id}`}
                points={ps.map((p) => `${sx(p.x)},${sy(p.index)}`).join(" ")}
                fill="none"
                stroke="currentColor"
                strokeOpacity={0.3}
                strokeWidth={1}
                pointerEvents="none"
                data-testid="picks-chart-effort-path"
              />
            ))}

            <path d={stepPath} fill="none" stroke={FRONTIER} strokeWidth={2.2} strokeDasharray="0.5 6" strokeLinecap="round" pointerEvents="none" />

            {pts.map((p) => {
              if (pickKeys.has(p.key)) return null;
              const front = onFrontier.has(p);
              return (
                <g key={p.key} pointerEvents="none" opacity={activePt && activePt !== p ? 0.45 : 1}>
                  {front && <circle cx={sx(p.x)} cy={sy(p.index)} r={6} fill="none" stroke={FRONTIER} strokeWidth={1.5} />}
                  <circle
                    cx={sx(p.x)}
                    cy={sy(p.index)}
                    r={3.5}
                    fill={front ? FRONTIER : undefined}
                    className={front ? "" : "fill-brand-slate-300 dark:fill-brand-slate-600"}
                  />
                </g>
              );
            })}

            {pickPts.map((p) => {
              const isSel = p.priority === selected;
              return (
                <g key={`pick-${p.priority}`} pointerEvents="none">
                  {leaderOf(p) === null && (
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

            {[...pts.filter((p) => !pickKeys.has(p.key)), ...pickPts].map((p) => {
              const pick = pickKeys.get(p.key);
              return (
                <circle
                  key={`hit-${p.key}`}
                  cx={sx(p.x)}
                  cy={sy(p.index)}
                  r={pick ? 12 : 8}
                  fill="transparent"
                  tabIndex={0}
                  role="button"
                  aria-label={`${pick ? `${PICK_LABEL[pick]} pick: ` : ""}${nameOf(p)}, AA Index ${p.index}, ${formatUsd(p.price)} per 1M tokens at its effort's token use`}
                  data-testid={pick ? "picks-chart-pick" : "picks-chart-point"}
                  data-model-id={p.row.id}
                  className="cursor-pointer outline-none"
                  onPointerEnter={(e) => {
                    if (e.pointerType === "mouse") setActive(p.key);
                  }}
                  onPointerLeave={(e) => {
                    if (e.pointerType === "mouse") setActive(null);
                  }}
                  onClick={() => {
                    setActive(p.key);
                    if (pick) onSelect(pick);
                  }}
                  onFocus={(e) => {
                    if (e.currentTarget.matches(":focus-visible")) setActive(p.key);
                  }}
                  onBlur={() => setActive(null)}
                />
              );
            })}
          </svg>
        )}
      </div>

      <p className="mt-1 text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
        {pool ? (
          <>
            Each model appears at every effort Artificial Analysis measured it at, joined by a faint
            line: a higher effort scores higher and draws more tokens, so it sits further right. Its
            price is its blended price times the tokens the model drew at that effort on our test
            tasks, relative to a typical model at high. The
            dotted green line is your cost/quality frontier over those points, drawn over the models
            your plans and API providers reach: its height at any price is the top AA Index you can
            get for that price, and the picks are read from it. Grey dots are your other points;
            hollow rings are the rest of the catalog.
          </>
        ) : (
          <>
            Each model appears at every effort Artificial Analysis measured it at, joined by a faint
            line: a higher effort scores higher and draws more tokens, so it sits further right. Its
            price is its blended price times the tokens the model drew at that effort on our test
            tasks, relative to a typical model at high. The
            dotted green line is the cost/quality frontier over those points: its height at any price
            is the top AA Index that price buys. Grey dots are the rest of the catalog.{" "}
            <Link href="/settings" className="font-medium text-brand-accent hover:underline">
              Save your plans in Settings
            </Link>{" "}
            to draw it over the models you can use.
          </>
        )}
        {unmeasured.length > 0 &&
          ` Not plotted: ${unmeasured.map((p) => p.model).join(", ")} (no AA Index yet).`}
      </p>

      {activePt && (
        <FloatingCard getAnchor={getAnchor} placement="side" testId="picks-chart-card">
          <FrontierPointCard
            model={asRow(activePt)}
            leader={(() => {
              const l = leaderOf(activePt);
              return l ? asRow(l) : null;
            })()}
          />
        </FloatingCard>
      )}
    </figure>
  );
}
