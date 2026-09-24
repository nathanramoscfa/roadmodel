// web/components/ScoreCharts.tsx
//
// The Score column, drawn: one chart per cost tier, all four on screen. Each
// plots the tier's measured models at their blended price (x, log scale) and
// AA Intelligence Index (y), with the tier's fitted price line, the ±σ tie
// band, and a stem from the line to each model — the stem's length IS the
// model's Score.
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
// Everything comes from the same rows and ScoreFit the table uses.
"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";

import {
  blendedPrice,
  formatScore,
  formatUsd,
  priceTicks,
  type ScoreFit,
} from "@/lib/benchmark-grid";
import { COST_TIER_DEFS, COST_TIER_DOT, type CostTier, type ModelRow } from "@/lib/catalog-fields";
import { FloatingCard, type AnchorRect } from "./FloatingCard";
import { ModelPointCard, PriceLineCard } from "./ScoreCards";

// Sign is also carried by direction and by the printed Score, so colour is
// never the only cue. Sky/orange stays distinct under protan and deutan
// vision, on both the light and the dark surface.
const ABOVE = "#0284c7";
const BELOW = "#ea580c";
const FRONTIER = "#10b981";

const TIER_ORDER: CostTier[] = ["very-high", "high", "medium", "low"];
const M = { top: 12, right: 18, bottom: 46, left: 46 };
const DOT_R = 6;
const LABEL_PX = 11.5;
const LABEL_H = 14;

interface Pt {
  row: ModelRow;
  x: number; // log10 blended price
  price: number;
  index: number;
  score: number;
  predicted: number;
}

type Active = { kind: "point"; id: string } | { kind: "line"; x: number } | null;

function useWidth(ref: RefObject<HTMLDivElement | null>): number {
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(Math.floor(el.getBoundingClientRect().width));
    const ro = new ResizeObserver((entries) => {
      const next = Math.floor(entries[0].contentRect.width);
      setW((prev) => (prev === next ? prev : next));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

// Label widths from the page's own font, so placement matches what renders.
let measureCtx: CanvasRenderingContext2D | null | undefined;
function textWidth(text: string): number {
  if (measureCtx === undefined) {
    try {
      measureCtx = document.createElement("canvas").getContext("2d");
      if (measureCtx) {
        const family = getComputedStyle(document.body).fontFamily || "system-ui, sans-serif";
        measureCtx.font = `500 ${LABEL_PX}px ${family}`;
      }
    } catch {
      measureCtx = null;
    }
  }
  return measureCtx ? measureCtx.measureText(text).width : text.length * LABEL_PX * 0.56;
}

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}
const overlaps = (a: Box, b: Box) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

interface Label {
  text: string;
  x: number;
  y: number; // baseline
  anchor: "start" | "middle" | "end";
  box: Box; // the backing plate behind the text
}

// A dense tier labels its most notable models (frontier first, then the
// largest scores either way) and leaves the rest to the hover card: a crowd of
// labels is harder to read than none.
const MAX_LABELS = 9;
// Clearance between a label and any OTHER model's dot, so a label never sits
// closer to a neighbour than to its own dot.
const DOT_CLEARANCE = 3;

function placeLabels(
  pts: { id: string; cx: number; cy: number; text: string; priority: number }[],
  bounds: Box,
  maxLabels: number,
): Map<string, Label> {
  const taken: Box[] = [];
  const reach = DOT_R + DOT_CLEARANCE;
  const dots = pts.map((p) => ({
    id: p.id,
    box: { x: p.cx - reach, y: p.cy - reach, w: 2 * reach, h: 2 * reach },
  }));
  const out = new Map<string, Label>();
  for (const p of [...pts].sort((a, b) => b.priority - a.priority)) {
    if (out.size >= maxLabels) break;
    const w = textWidth(p.text);
    const off = DOT_R + 5;
    // Right, left, above, below the dot: the plate's top-left corner, the
    // text's anchor point, and its alignment.
    const d = off - 3; // diagonal offset: the plate's corner sits just off the dot
    const spots: [number, number, number, number, Label["anchor"]][] = [
      [p.cx + off, p.cy - LABEL_H / 2, p.cx + off + 3, p.cy + 4, "start"],
      [p.cx - off - w - 6, p.cy - LABEL_H / 2, p.cx - off - 3, p.cy + 4, "end"],
      [p.cx - w / 2 - 3, p.cy - off - LABEL_H, p.cx, p.cy - off - 4, "middle"],
      [p.cx - w / 2 - 3, p.cy + off, p.cx, p.cy + off + 10, "middle"],
      [p.cx + d, p.cy - d - LABEL_H, p.cx + d + 3, p.cy - d - 4, "start"],
      [p.cx - d - w - 6, p.cy - d - LABEL_H, p.cx - d - 3, p.cy - d - 4, "end"],
      [p.cx + d, p.cy + d, p.cx + d + 3, p.cy + d + 10, "start"],
      [p.cx - d - w - 6, p.cy + d, p.cx - d - 3, p.cy + d + 10, "end"],
      // Above/below but flush with the dot's side, for a dot near a plot edge.
      [p.cx - 8, p.cy - off - LABEL_H, p.cx - 5, p.cy - off - 4, "start"],
      [p.cx + 8 - w - 6, p.cy - off - LABEL_H, p.cx + 5, p.cy - off - 4, "end"],
      [p.cx - 8, p.cy + off, p.cx - 5, p.cy + off + 10, "start"],
      [p.cx + 8 - w - 6, p.cy + off, p.cx + 5, p.cy + off + 10, "end"],
    ];
    for (const [bx, by, tx, ty, anchor] of spots) {
      const box = { x: bx, y: by, w: w + 6, h: LABEL_H };
      const inside =
        box.x >= bounds.x &&
        box.y >= bounds.y &&
        box.x + box.w <= bounds.x + bounds.w &&
        box.y + box.h <= bounds.y + bounds.h;
      if (!inside) continue;
      const pad = { x: box.x - 2, y: box.y - 1, w: box.w + 4, h: box.h + 2 };
      if (taken.some((t) => overlaps(t, pad))) continue;
      if (dots.some((d) => d.id !== p.id && overlaps(d.box, box))) continue;
      taken.push(pad);
      out.set(p.id, { text: p.text, x: tx, y: ty, anchor, box });
      break;
    }
  }
  return out;
}

function TierChart({
  tier,
  rows,
  fit,
  byId,
}: {
  tier: CostTier;
  rows: ModelRow[];
  fit: ScoreFit;
  // Every catalog row by id, for the model that beats a dot's model.
  byId: Map<string, ModelRow>;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const width = useWidth(wrap);
  const [active, setActive] = useState<Active>(null);
  const pinned = useRef(false);
  const pointer = useRef("mouse");
  const t = fit.tiers[tier];
  const label = COST_TIER_DEFS[tier].label;

  const pts: Pt[] = useMemo(
    () =>
      rows
        .filter((r) => r.tier_cost === tier && r.aa_index !== null && r.value_score !== null)
        .map((r) => {
          const price = blendedPrice(r.input_price_per_1m, r.output_price_per_1m);
          const x = Math.log10(price);
          return {
            row: r,
            x,
            price,
            index: r.aa_index as number,
            score: r.value_score as number,
            predicted: t.intercept + fit.slope * x,
          };
        })
        .sort((a, b) => a.x - b.x || b.index - a.index),
    [rows, tier, fit, t],
  );
  const inTier = rows.filter((r) => r.tier_cost === tier).length;
  // The caption's price ranges, over the plotted models: output (which sets
  // the tier) and blended (the x axis).
  const outs = pts.map((p) => p.row.output_price_per_1m);
  const range = (lo: number, hi: number) =>
    lo === hi ? formatUsd(lo) : `${formatUsd(lo)}–${formatUsd(hi)}`;

  const height = width > 0 && width < 480 ? 340 : 320;
  const plotW = Math.max(40, width - M.left - M.right);
  const plotH = height - M.top - M.bottom;

  const xs = pts.map((p) => p.x);
  const pad = Math.max(0.09, (Math.max(...xs) - Math.min(...xs)) * 0.14);
  const x0 = Math.min(...xs) - pad;
  const x1 = Math.max(...xs) + pad;
  const line = useCallback((x: number) => t.intercept + fit.slope * x, [t, fit]);
  const yVals = [
    ...pts.map((p) => p.index),
    line(x0) - fit.sigma,
    line(x0) + fit.sigma,
    line(x1) - fit.sigma,
    line(x1) + fit.sigma,
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

  // x ticks: the roundest prices claim their place first ($1, $10, then $2,
  // $5, then $1.50, $3 …), and a tick is kept only if its label clears every
  // label already kept — so a narrow chart shows $10 and $20, never $9 alone.
  const xTicks = useMemo(() => {
    if (width === 0) return [];
    const roundness = (v: number) => {
      const m = Number((v / 10 ** Math.floor(Math.log10(v) + 1e-9)).toPrecision(3));
      if (m === 1) return 0;
      if (m === 2 || m === 5) return 1;
      if (m === 1.5 || m === 2.5 || m === 3) return 2;
      return 3;
    };
    const kept: { v: number; px: number; half: number }[] = [];
    const candidates = priceTicks(10 ** x0, 10 ** x1).sort(
      (a, b) => roundness(a) - roundness(b) || a - b,
    );
    for (const v of candidates) {
      const px = sx(Math.log10(v));
      const half = textWidth(formatUsd(v)) / 2;
      if (px - half < M.left - 12 || px + half > M.left + plotW + 12) continue;
      if (kept.some((k) => Math.abs(k.px - px) < k.half + half + 8)) continue;
      kept.push({ v, px, half });
    }
    return kept.sort((a, b) => a.v - b.v);
  }, [width, x0, x1, sx, plotW]);

  const labels = useMemo(() => {
    if (width === 0) return new Map<string, Label>();
    return placeLabels(
      pts.map((p) => ({
        id: p.row.id,
        cx: sx(p.x),
        cy: sy(p.index),
        text: `${p.row.name} ${formatScore(p.score)}`,
        priority: Math.abs(p.score) + (p.row.value_frontier ? 100 : 0),
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
  const bandTop = `${sx(x0)},${sy(line(x0) + fit.sigma)} ${sx(x1)},${sy(line(x1) + fit.sigma)}`;
  const bandBottom = `${sx(x1)},${sy(line(x1) - fit.sigma)} ${sx(x0)},${sy(line(x0) - fit.sigma)}`;

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
              ? `${pts.length} models`
              : `${pts.length} of ${inTier} models measured`}
          </span>
          {" · "}
          <span className="whitespace-nowrap">
            output {range(Math.min(...outs), Math.max(...outs))}
          </span>
          {" · "}
          <span className="whitespace-nowrap">
            blended {range(t.minPrice, t.maxPrice)} per 1M
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
            aria-label={`${label} cost: ${pts.length} models plotted by blended price against AA Intelligence Index, with the tier's price line. Each model's Score is its vertical distance from the line.`}
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
                points={`${bandTop} ${bandBottom}`}
                className="fill-brand-slate-900/[0.05] dark:fill-white/[0.06]"
              />
              {/* The tier's price line */}
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
              aria-label={`${label}-cost price line: expected AA Index = ${t.intercept.toFixed(1)} + ${fit.slope.toFixed(1)} × log10(blended price)`}
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
                if (e.currentTarget.matches(":focus-visible")) setActive({ kind: "line", x: t.meanLogPrice });
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
                  stroke={p.score >= 0 ? ABOVE : BELOW}
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
                    fill={p.score >= 0 ? ABOVE : BELOW}
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
            <PriceLineCard tier={tier} fit={fit} atPrice={10 ** active.x} />
          ) : null}
        </FloatingCard>
      )}
    </figure>
  );
}

function LegendSwatch({ children }: { children: ReactNode }) {
  return (
    <svg width={22} height={14} viewBox="0 0 22 14" aria-hidden className="shrink-0">
      {children}
    </svg>
  );
}

export function ScoreCharts({ rows, fit }: { rows: ModelRow[]; fit: ScoreFit | null }) {
  if (!fit) return null;
  const tiers = TIER_ORDER.filter((t) => (fit.tiers[t]?.n ?? 0) >= 2);
  const byId = new Map(rows.map((r) => [r.id, r]));
  if (tiers.length === 0) return null;
  const sigma = fit.sigma.toFixed(1);

  return (
    <details
      open
      className="group rounded-xl border border-brand-slate-200 bg-brand-slate-50/60 dark:border-brand-slate-700 dark:bg-brand-slate-800/40"
      data-testid="score-charts"
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-5 py-3 text-sm font-semibold text-brand-slate-800 dark:text-brand-slate-100">
        What the Score means: AA Index against price, one chart per cost tier
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
          &ldquo;is it good <em>for its price</em>?&rdquo; are different questions. Each chart
          answers the second for one cost tier: every model sits at its blended price (across) and
          AA Intelligence Index (up), and the line is what a model of that tier typically scores
          at each price. The blended price is (3&nbsp;&times;&nbsp;input + 1&nbsp;&times;&nbsp;output)
          &divide;&nbsp;4, one price per model, which is why it reads below the output prices
          that set the tier. <strong>A model&rsquo;s Score is its vertical distance from the line</strong>
          , in index points: above it (+) buys more intelligence than the price predicts, below it
          (&minus;) buys less.
        </p>

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
            Cost/quality frontier (whole catalog)
          </li>
          <li className="inline-flex items-center gap-1.5">
            <LegendSwatch>
              <line x1={1} y1={11} x2={21} y2={3} strokeWidth={2} className="stroke-brand-slate-700 dark:stroke-brand-slate-200" />
            </LegendSwatch>
            Expected AA Index for the price
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

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {tiers.map((t) => (
            <TierChart key={t} tier={t} rows={rows} fit={fit} byId={byId} />
          ))}
        </div>

        <p className="text-xs leading-5 text-brand-slate-500 dark:text-brand-slate-400">
          One least-squares fit over all {fit.n} AA-measured models: AA Index = α<sub>tier</sub>
          {" "}+ β&thinsp;×&thinsp;log<sub>10</sub>(blended price), with a separate intercept
          α for each cost tier and one shared slope β&nbsp;=&nbsp;{fit.slope.toFixed(1)} index
          points per 10&times; price (R&sup2;&nbsp;{fit.r2.toFixed(2)}, residual
          σ&nbsp;{sigma}). A dot inside the shaded band is level with its line: treat scores that
          close together as a tie, not a ranking.{" "}
          <strong className="text-brand-slate-700 dark:text-brand-slate-200">
            The frontier ring is catalog-wide, not per tier: nothing in any cost tier costs less
            and scores higher.
          </strong>{" "}
          A chart can have no ring at all when a cheaper tier&rsquo;s model beats every model in it.
        </p>
      </div>
    </details>
  );
}
