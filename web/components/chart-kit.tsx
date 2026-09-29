// web/components/chart-kit.tsx
//
// What the /models charts share (the per-tier Score charts and the frontier
// chart): the chart's real width, label widths in the page's own font, greedy
// label placement that never covers another label or dot, round price ticks
// for a log axis, the legend swatch, the frontier colour, and the note a
// panel shows while the page's filters narrow it.
"use client";

import { useEffect, useState, type ReactNode, type RefObject } from "react";

import { formatUsd, priceTicks } from "@/lib/benchmark-grid";

// The frontier's green: the ring in the table, the charts and the legend.
export const FRONTIER = "#10b981";
export const DOT_R = 6;
export const LABEL_PX = 11.5;
export const LABEL_H = 14;

// A chart is laid out at its container's real pixel width, not scaled from a
// fixed viewBox, so type stays at full size on a phone.
export function useWidth(ref: RefObject<HTMLDivElement | null>): number {
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
export function textWidth(text: string): number {
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

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}
const overlaps = (a: Box, b: Box) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

export interface Label {
  text: string;
  x: number;
  y: number; // baseline
  anchor: "start" | "middle" | "end";
  box: Box; // the backing plate behind the text
}

// Clearance between a label and any OTHER model's dot, so a label never sits
// closer to a neighbour than to its own dot.
const DOT_CLEARANCE = 3;

// Places labels greedily, highest priority first, at the first of twelve spots
// around each dot that stays inside the plot and clears every label already
// placed and every other dot. A label with no clear spot is left to the hover
// card: a crowd of labels is harder to read than none. An item can offer
// other anchors to try in turn (a line's two ends and middle), and an item
// that is not a dot (dot: false) keeps no clearance of its own.
export interface LabelItem {
  id: string;
  cx: number;
  cy: number;
  text: string;
  priority: number;
  anchors?: { cx: number; cy: number }[];
  dot?: boolean;
}

export function placeLabels(
  pts: LabelItem[],
  bounds: Box,
  maxLabels: number,
  dotR: number = DOT_R,
): Map<string, Label> {
  const taken: Box[] = [];
  const reach = dotR + DOT_CLEARANCE;
  const dots = pts
    .filter((p) => p.dot !== false)
    .map((p) => ({
      id: p.id,
      box: { x: p.cx - reach, y: p.cy - reach, w: 2 * reach, h: 2 * reach },
    }));
  const out = new Map<string, Label>();
  for (const p of [...pts].sort((a, b) => b.priority - a.priority)) {
    if (out.size >= maxLabels) break;
    const w = textWidth(p.text);
    const off = dotR + 5;
    // The diagonal offset: the plate's corner sits just off the dot.
    const d = off - 3;
    for (const { cx, cy } of p.anchors ?? [{ cx: p.cx, cy: p.cy }]) {
      // Right, left, above, below the dot, then the diagonals: the plate's
      // top-left corner, the text's anchor point, and its alignment.
      const spots: [number, number, number, number, Label["anchor"]][] = [
        [cx + off, cy - LABEL_H / 2, cx + off + 3, cy + 4, "start"],
        [cx - off - w - 6, cy - LABEL_H / 2, cx - off - 3, cy + 4, "end"],
        [cx - w / 2 - 3, cy - off - LABEL_H, cx, cy - off - 4, "middle"],
        [cx - w / 2 - 3, cy + off, cx, cy + off + 10, "middle"],
        [cx + d, cy - d - LABEL_H, cx + d + 3, cy - d - 4, "start"],
        [cx - d - w - 6, cy - d - LABEL_H, cx - d - 3, cy - d - 4, "end"],
        [cx + d, cy + d, cx + d + 3, cy + d + 10, "start"],
        [cx - d - w - 6, cy + d, cx - d - 3, cy + d + 10, "end"],
        // Above/below but flush with the dot's side, for a dot near a plot edge.
        [cx - 8, cy - off - LABEL_H, cx - 5, cy - off - 4, "start"],
        [cx + 8 - w - 6, cy - off - LABEL_H, cx + 5, cy - off - 4, "end"],
        [cx - 8, cy + off, cx - 5, cy + off + 10, "start"],
        [cx + 8 - w - 6, cy + off, cx + 5, cy + off + 10, "end"],
      ];
      let placed = false;
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
        if (dots.some((dt) => dt.id !== p.id && overlaps(dt.box, box))) continue;
        taken.push(pad);
        out.set(p.id, { text: p.text, x: tx, y: ty, anchor, box });
        placed = true;
        break;
      }
      if (placed) break;
    }
  }
  return out;
}

// x ticks for a log price axis: the roundest prices claim their place first
// ($1, $10, then $2, $5, then $1.50, $3 …), and a tick is kept only if its
// label clears every label already kept, so a narrow chart shows $10 and $20,
// never $9 alone.
export function pickPriceTicks(
  x0: number,
  x1: number,
  sx: (x: number) => number,
  left: number,
  plotW: number,
): { v: number; px: number; half: number }[] {
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
    if (px - half < left - 12 || px + half > left + plotW + 12) continue;
    if (kept.some((k) => Math.abs(k.px - px) < k.half + half + 8)) continue;
    kept.push({ v, px, half });
  }
  return kept.sort((a, b) => a.v - b.v);
}

export function LegendSwatch({ children }: { children: ReactNode }) {
  return (
    <svg width={22} height={14} viewBox="0 0 22 14" aria-hidden className="shrink-0">
      {children}
    </svg>
  );
}

// The page's active filters, as a chart panel shows them (ModelsExplorer).
export interface ChartFilter {
  // Every active filter in a line: "Jurisdiction: US + EU · High cost".
  summary: string;
  onClear: () => void;
}

// A filtered panel says so at its top, far below the controls that set it,
// and offers the way back.
export function FilterNote({
  filter,
  testId,
  children,
}: {
  filter: ChartFilter;
  testId: string;
  children: ReactNode;
}) {
  return (
    <div
      className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 rounded-lg border border-brand-accent/30 bg-brand-accent/5 px-3 py-2 text-xs leading-5 text-brand-slate-700 dark:bg-brand-accent/10 dark:text-brand-slate-200"
      data-testid={testId}
    >
      <p>
        <strong className="font-semibold text-brand-slate-900 dark:text-brand-slate-50">
          Filtered: {filter.summary}.
        </strong>{" "}
        {children}
      </p>
      <button
        type="button"
        onClick={filter.onClear}
        className="shrink-0 font-medium text-brand-accent hover:underline"
      >
        Show every model
      </button>
    </div>
  );
}
