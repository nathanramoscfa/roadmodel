// web/components/chart-kit.tsx
//
// What the charts share (the per-tier Score charts, the /models frontier chart
// and /recommend's): the chart's real width, label widths in the page's own
// font, label placement that never covers another label or dot (placeLabels,
// which leaves a crowded label out, and placeEveryLabel, which places every
// one and joins a displaced label to its mark with a line), round price ticks
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

// A chart that names every point on its frontier needs this much room for the
// names to sit by their points. In a narrower box it keeps this width and pans
// sideways inside the box, as the catalog's table does on a phone.
export const NAMED_MIN_WIDTH = 640;
// A box this close to that width is drawn at its own: a chart never pans by a
// few pixels.
const NAMED_SLACK = 24;

// The width to draw such a chart at inside the box it scrolls in, and whether
// it pans there.
export function useNamedWidth(scroller: RefObject<HTMLDivElement | null>): { width: number; pans: boolean } {
  const box = useWidth(scroller);
  const pans = box > 0 && box < NAMED_MIN_WIDTH - NAMED_SLACK;
  return { width: pans ? NAMED_MIN_WIDTH : box, pans };
}

// The index axis of a chart that pans, held in place over it (the catalog
// table's first column does the same): the chart slides under it, and the
// reader keeps the scale. Laid over the box's left edge by its parent.
export function PinnedIndexAxis({
  left,
  top,
  plotH,
  height,
  ticks,
  testId,
}: {
  // The chart's left margin: the strip the axis fills.
  left: number;
  top: number;
  plotH: number;
  height: number;
  ticks: { v: number; y: number }[];
  testId: string;
}) {
  return (
    <svg
      width={left}
      height={height}
      aria-hidden
      className="pointer-events-none absolute left-0 top-0 text-brand-slate-400 dark:text-brand-slate-500"
      data-testid={testId}
    >
      <rect width={left} height={height} className="fill-white dark:fill-brand-slate-900" />
      <line x1={left - 0.5} x2={left - 0.5} y1={top} y2={top + plotH} stroke="currentColor" strokeOpacity={0.55} />
      {ticks.map(({ v, y }) => (
        <text
          key={v}
          x={left - 8}
          y={y + 4}
          textAnchor="end"
          fontSize={11.5}
          className="fill-brand-slate-500 tabular-nums dark:fill-brand-slate-400"
        >
          {v}
        </text>
      ))}
      <text
        transform={`translate(13 ${top + plotH / 2}) rotate(-90)`}
        textAnchor="middle"
        fontSize={11.5}
        className="fill-brand-slate-500 dark:fill-brand-slate-400"
      >
        AA Intelligence Index
      </text>
    </svg>
  );
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

// An axis title centred at `cx` on a chart `width` px wide: the first of
// `titles` (longest first) that fits, so a phone-width chart reads a shorter
// wording instead of a clipped one.
export function fitTitle(titles: readonly string[], cx: number, width: number): string {
  const room = 2 * Math.min(cx, width - cx) - 4;
  return titles.find((t) => textWidth(t) <= room) ?? titles[titles.length - 1];
}

// The price axis's titles, longest first (fitTitle).
export const PRICE_AXIS_TITLES = [
  "Effort-adjusted blended price, $ per 1M tokens (log scale)",
  "Effort-adjusted price, $/1M tokens (log)",
  "Effort $/1M (log)",
] as const;

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
// that is not a dot (dot: false) keeps no clearance of its own. A chart that
// must name every one of its marks uses placeEveryLabel below.
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
  const dots = pts
    .filter((p) => p.dot !== false)
    .map((p) => {
      const reach = dotR + DOT_CLEARANCE;
      return { id: p.id, box: { x: p.cx - reach, y: p.cy - reach, w: 2 * reach, h: 2 * reach } };
    });
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

export interface Segment {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface PlacedLabel extends Label {
  // The line from the mark to its plate, when the plate sits off the mark.
  leader: Segment | null;
}

// A mark on the chart: one to label (text), or one that is only in the way.
export interface Mark {
  id: string;
  cx: number;
  cy: number;
  // Its radius: the clearance it keeps, and how far off it its label sits.
  r: number;
  // The label to place; null for a mark that is only an obstacle.
  text: string | null;
  // A label never covers it (a frontier ring, a pick). A quiet dot is covered
  // only when no spot clear of every dot is left.
  hard: boolean;
  // Higher chooses its spot first in the caller's own order, one of the
  // orders tried.
  priority: number;
}

// The directions a label is tried in, as unit vectors (y grows downward), each
// with what choosing it costs: left and right of the mark first, then above
// and below, then the diagonals, then the angles between.
const D = Math.SQRT1_2;
const C8 = Math.cos(Math.PI / 8);
const S8 = Math.sin(Math.PI / 8);
const DIRECTIONS: readonly [number, number, number][] = [
  [-1, 0, 0],
  [1, 0, 1],
  [0, -1, 2],
  [0, 1, 3],
  [-D, -D, 4],
  [D, -D, 5],
  [-D, D, 6],
  [D, D, 7],
  [-C8, -S8, 8],
  [C8, -S8, 9],
  [-S8, -C8, 10],
  [S8, -C8, 11],
  [-C8, S8, 12],
  [C8, S8, 13],
  [-S8, C8, 14],
  [S8, C8, 15],
];
// How far off its mark a label is tried, nearest first (px past the mark's
// edge). A label at the first sits against its mark and needs no line.
const GAPS = [0, 9, 20, 33, 48, 65, 84, 105, 128, 154, 184, 218, 258, 304, 360] as const;
// A label this far off its mark, or farther, is joined to it by a line.
const LEADER_FROM = 9;
const PLATE_PAD = 3;
// The paired moves that finish a layout (placeEveryLabel): how many rounds,
// how many of the worst-placed labels a round takes up, and how many of its
// nearest marks each is tried with.
const PAIR_ROUNDS = 2;
const PAIR_WORST = 5;
const PAIR_NEAR = 5;
// Once this many spots have been judged no further order is tried: a layout
// in a blink matters more than the last pixel of a line. Counted, not timed,
// so the same marks give the same layout on any machine.
const JUDGE_BUDGET = 40_000;

// Whether a segment passes through a box (Liang-Barsky clipping). These run
// tens of thousands of times a layout, so they allocate nothing.
function segmentHitsBox(s: Segment, b: Box): boolean {
  const dx = s.x2 - s.x1;
  const dy = s.y2 - s.y1;
  let t0 = 0;
  let t1 = 1;
  for (let edge = 0; edge < 4; edge++) {
    const p = edge === 0 ? -dx : edge === 1 ? dx : edge === 2 ? -dy : dy;
    const q = edge === 0 ? s.x1 - b.x : edge === 1 ? b.x + b.w - s.x1 : edge === 2 ? s.y1 - b.y : b.y + b.h - s.y1;
    if (p === 0) {
      if (q < 0) return false;
      continue;
    }
    const t = q / p;
    if (p < 0) {
      if (t > t1) return false;
      if (t > t0) t0 = t;
    } else {
      if (t < t0) return false;
      if (t < t1) t1 = t;
    }
  }
  return t0 <= t1;
}

const sideOf = (px: number, py: number, s: Segment) =>
  Math.sign((s.x2 - s.x1) * (py - s.y1) - (s.y2 - s.y1) * (px - s.x1));

function segmentsCross(a: Segment, b: Segment): boolean {
  return (
    sideOf(a.x1, a.y1, b) !== sideOf(a.x2, a.y2, b) && sideOf(b.x1, b.y1, a) !== sideOf(b.x2, b.y2, a)
  );
}

function segmentNearPoint(s: Segment, cx: number, cy: number, within: number): boolean {
  const dx = s.x2 - s.x1;
  const dy = s.y2 - s.y1;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((cx - s.x1) * dx + (cy - s.y1) * dy) / len2));
  return Math.hypot(s.x1 + t * dx - cx, s.y1 + t * dy - cy) < within;
}

interface Spot {
  label: PlacedLabel;
  // What makes it no spot at all (a plate over another plate, a hard mark or
  // another label's line; a line through any of those), counted so the last
  // resort is the least bad.
  blocked: number;
  // What a clear spot still costs: how far off its mark it is, its direction,
  // and anything quiet it covers.
  cost: number;
}

const total = (s: Spot) => s.blocked * 1000 + s.cost;

// Places a label for EVERY mark that has text: against its mark where a spot
// there is clear, else at the nearest clear spot farther off, joined to the
// mark by a line. A plate stays inside the plot, never covers another plate, a
// hard mark or another label's line, and its own line crosses none of those;
// it covers a quiet dot or one of the `avoid` lines (the frontier's own) only
// when the nearest spot clear of them is much farther off. Where the plot is
// too crowded for all of that the label still gets the least-bad spot: a mark
// asked to be named is always named.
//
// Labels are placed one at a time, so the order decides who gets the spot
// against its mark. Several orders are tried, each then improved by moving one
// label at a time while that shortens the lines, and the layout with the least
// to answer for is kept. The same marks always give the same layout.
export function placeEveryLabel(
  marks: readonly Mark[],
  bounds: Box,
  avoid: readonly Segment[] = [],
  measure: (text: string) => number = textWidth,
): Map<string, PlacedLabel> {
  // Each mark's clearance, as the box a plate must keep out of.
  const dots = marks.map((m) => {
    const reach = m.r + DOT_CLEARANCE;
    return { m, x0: m.cx - reach, y0: m.cy - reach, x1: m.cx + reach, y1: m.cy + reach };
  });
  const dotOf = new Map(dots.map((d) => [d.m.id, d]));
  const named = marks.filter((m) => m.text !== null);
  const widths = new Map(named.map((m) => [m.id, measure(m.text as string) + 2 * PLATE_PAD]));
  // Spots judged so far: the search stops widening once it has done enough.
  let judged = 0;

  // How a label at `label` stands for `m` among the labels in `placed`. Two
  // plates keep 4px apart across and 2px up and down.
  const judge = (m: Mark, label: PlacedLabel, off: number, turn: number, placed: Map<string, PlacedLabel>): Spot => {
    judged += 1;
    const b = label.box;
    const pad: Box = { x: b.x - 2, y: b.y - 1, w: b.w + 4, h: b.h + 2 };
    const leader = label.leader;
    let blocked = 0;
    for (const [id, other] of placed) {
      if (id === m.id) continue;
      const o = other.box;
      if (b.x < o.x + o.w + 4 && o.x < b.x + b.w + 4 && b.y < o.y + o.h + 2 && o.y < b.y + b.h + 2) blocked += 4;
      if (other.leader !== null && segmentHitsBox(other.leader, pad)) blocked += 2;
      if (leader !== null) {
        if (segmentHitsBox(leader, o)) blocked += 2;
        if (other.leader !== null && segmentsCross(leader, other.leader)) blocked += 2;
      }
    }
    // Close beats far, and a long line costs more than its length: two short
    // lines read better than one long one.
    let cost = off + Math.max(0, off - 30) + 2 * Math.max(0, off - 70) + turn * 0.75 + (leader ? 4 : 0);
    for (const d of dots) {
      if (d.m === m) continue;
      const over = d.x0 < b.x + b.w && b.x < d.x1 && d.y0 < b.y + b.h && b.y < d.y1;
      const through = leader !== null && segmentNearPoint(leader, d.m.cx, d.m.cy, d.m.r + 1.5);
      if (d.m.hard) {
        blocked += (over ? 4 : 0) + (through ? 2 : 0);
      } else if (over) {
        // Over the dot itself is far worse than inside the clearance round it:
        // a name may stand close to a quiet dot in a tight plot, where the
        // other choice is a long line, and never on it while a spot is clear.
        const r = d.m.r;
        const onDot =
          d.m.cx - r < b.x + b.w && b.x < d.m.cx + r && d.m.cy - r < b.y + b.h && b.y < d.m.cy + r;
        cost += onDot ? 120 : 40;
      } else if (through) {
        cost += 10;
      }
    }
    for (const line of avoid) if (segmentHitsBox(line, b)) cost += 22;
    return { label, blocked, cost };
  };

  // The spot for `m` at one distance in one direction, judged among `placed`.
  const spotAt = (
    m: Mark,
    gap: number,
    [ux, uy, turn]: readonly [number, number, number],
    placed: Map<string, PlacedLabel>,
  ): Spot => {
    const w = widths.get(m.id) as number;
    const reach = m.r + 5 + gap;
    const ax = m.cx + ux * reach;
    const ay = m.cy + uy * reach;
    const anchor: Label["anchor"] = ux > 0.5 ? "start" : ux < -0.5 ? "end" : "middle";
    const bx = anchor === "start" ? ax : anchor === "end" ? ax - w : ax - w / 2;
    const by = uy < -0.5 ? ay - LABEL_H : uy > 0.5 ? ay : ay - LABEL_H / 2;
    // Kept inside the plot by sliding along its edge, not by giving up.
    const box: Box = {
      x: Math.min(Math.max(bx, bounds.x), Math.max(bounds.x, bounds.x + bounds.w - w)),
      y: Math.min(Math.max(by, bounds.y), Math.max(bounds.y, bounds.y + bounds.h - LABEL_H)),
      w,
      h: LABEL_H,
    };
    // Kept inside, the plate can land on its own mark: the last resort of all,
    // taken only in a plot with no room for the name anywhere.
    const own = dotOf.get(m.id) as (typeof dots)[number];
    const onOwnMark = own.x0 < box.x + box.w && box.x < own.x1 && own.y0 < box.y + box.h && box.y < own.y1;
    // The line runs from the mark's edge to the nearest point of the plate.
    const qx = Math.min(Math.max(m.cx, box.x), box.x + box.w);
    const qy = Math.min(Math.max(m.cy, box.y), box.y + box.h);
    const dist = Math.hypot(qx - m.cx, qy - m.cy);
    const off = dist - m.r;
    const leader: Segment | null =
      off >= LEADER_FROM && dist > 0
        ? {
            x1: m.cx + ((qx - m.cx) / dist) * (m.r + 2),
            y1: m.cy + ((qy - m.cy) / dist) * (m.r + 2),
            x2: qx,
            y2: qy,
          }
        : null;
    const spot = judge(
      m,
      {
        text: m.text as string,
        x: anchor === "start" ? box.x + PLATE_PAD : anchor === "end" ? box.x + w - PLATE_PAD : box.x + w / 2,
        y: box.y + 10.5,
        anchor,
        box,
        leader,
      },
      Math.max(0, off),
      turn,
      placed,
    );
    return onOwnMark ? { ...spot, blocked: spot.blocked + 50 } : spot;
  };

  // The best spot for `m` among the labels in `placed`.
  const best = (m: Mark, placed: Map<string, PlacedLabel>): Spot => {
    let found = spotAt(m, GAPS[0], DIRECTIONS[0], placed);
    for (const gap of GAPS) {
      // Nothing farther off can beat a clear spot already found this near.
      if (found.blocked === 0 && gap > found.cost) break;
      for (const direction of DIRECTIONS) {
        const spot = spotAt(m, gap, direction, placed);
        if (total(spot) < total(found)) found = spot;
      }
    }
    return found;
  };

  // How many clear spots `m` has against its mark: the fewer, the sooner it
  // should choose.
  const room = (m: Mark, placed: Map<string, PlacedLabel>): number => {
    let n = 0;
    for (const direction of DIRECTIONS) {
      const spot = spotAt(m, GAPS[0], direction, placed);
      if (spot.blocked === 0 && spot.cost < 30) n += 1;
    }
    return n;
  };

  type Layout = { placed: Map<string, PlacedLabel>; spots: Map<string, Spot>; sum: number };
  const sumOf = (spots: Map<string, Spot>) => {
    let sum = 0;
    for (const spot of spots.values()) sum += total(spot);
    return sum;
  };

  // A layout, improved until nothing moves: first one label at a time to a
  // better spot now that every other label has one, then a label with a long
  // line together with one in its way, placed afresh in either order.
  const improve = (order: readonly Mark[], placed: Map<string, PlacedLabel>, spots: Map<string, Spot>): Layout => {
    const settle = () => {
      for (let round = 0; round < 4; round++) {
        let moved = false;
        for (const m of order) {
          const now = spots.get(m.id);
          if (!now) continue;
          const next = best(m, placed);
          if (total(next) < total(now) - 0.01) {
            placed.set(m.id, next.label);
            spots.set(m.id, next);
            moved = true;
          }
        }
        if (!moved) break;
      }
    };
    settle();
    for (let round = 0; round < PAIR_ROUNDS; round++) {
      if (judged > JUDGE_BUDGET) break;
      let moved = false;
      // The few labels with the most to answer for, each tried with the few
      // marks nearest it: the work stays small however long the frontier is.
      const worst = order
        .filter((m) => total(spots.get(m.id) as Spot) >= 40)
        .sort((a, b) => total(spots.get(b.id) as Spot) - total(spots.get(a.id) as Spot))
        .slice(0, PAIR_WORST);
      for (const a of worst) {
        const near = order
          .filter((b) => b !== a)
          .sort((x, y) => Math.hypot(x.cx - a.cx, x.cy - a.cy) - Math.hypot(y.cx - a.cx, y.cy - a.cy))
          .slice(0, PAIR_NEAR);
        for (const b of near) {
          const wasB = spots.get(b.id);
          const nowA = spots.get(a.id);
          if (!wasB || !nowA) continue;
          const before = total(nowA) + total(wasB);
          let kept: { a: Spot; b: Spot } | null = null;
          for (const [first, second] of [
            [a, b],
            [b, a],
          ] as const) {
            const trial = new Map(placed);
            trial.delete(a.id);
            trial.delete(b.id);
            const one = best(first, trial);
            trial.set(first.id, one.label);
            const two = best(second, trial);
            if (total(one) + total(two) < (kept ? total(kept.a) + total(kept.b) : before) - 0.01) {
              kept = first === a ? { a: one, b: two } : { a: two, b: one };
            }
          }
          if (kept) {
            placed.set(a.id, kept.a.label);
            placed.set(b.id, kept.b.label);
            spots.set(a.id, kept.a);
            spots.set(b.id, kept.b);
            moved = true;
          }
        }
      }
      if (!moved) break;
      settle();
    }
    return { placed, spots, sum: sumOf(spots) };
  };

  // Labels placed in a given order.
  const inOrder = (order: readonly Mark[]): Layout => {
    const placed = new Map<string, PlacedLabel>();
    const spots = new Map<string, Spot>();
    for (const m of order) {
      const spot = best(m, placed);
      placed.set(m.id, spot.label);
      spots.set(m.id, spot);
    }
    return improve(order, placed, spots);
  };

  // Labels placed tightest first: each time, the mark with the fewest clear
  // spots left against it chooses.
  const tightestFirst = (): Layout => {
    const placed = new Map<string, PlacedLabel>();
    const spots = new Map<string, Spot>();
    const left = [...named].sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id));
    const order: Mark[] = [];
    while (left.length > 0) {
      let at = 0;
      let fewest = Infinity;
      left.forEach((m, i) => {
        const n = room(m, placed);
        if (n < fewest) {
          fewest = n;
          at = i;
        }
      });
      const [m] = left.splice(at, 1);
      order.push(m);
      const spot = best(m, placed);
      placed.set(m.id, spot.label);
      spots.set(m.id, spot);
    }
    return improve(order, placed, spots);
  };

  // The orders tried: tightest first, the caller's, across the plot each way,
  // and the most crowded marks first or last.
  const crowd = new Map(
    named.map((m) => [m.id, named.filter((o) => o !== m && Math.hypot(o.cx - m.cx, o.cy - m.cy) < 90).length]),
  );
  const by = (cmp: (a: Mark, b: Mark) => number) => [...named].sort((a, b) => cmp(a, b) || a.id.localeCompare(b.id));
  const tries: (() => Layout)[] = [
    tightestFirst,
    () => inOrder(by((a, b) => b.priority - a.priority)),
    () => inOrder(by((a, b) => a.cx - b.cx)),
    () => inOrder(by((a, b) => b.cx - a.cx)),
    () => inOrder(by((a, b) => (crowd.get(b.id) as number) - (crowd.get(a.id) as number) || a.cx - b.cx)),
    () => inOrder(by((a, b) => (crowd.get(a.id) as number) - (crowd.get(b.id) as number) || a.cx - b.cx)),
  ];
  let kept: Layout | null = null;
  for (const attempt of tries) {
    if (kept !== null && judged > JUDGE_BUDGET) break;
    const tried = attempt();
    if (kept === null || tried.sum < kept.sum - 0.01) kept = tried;
  }
  return kept?.placed ?? new Map();
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
