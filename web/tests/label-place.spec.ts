// web/tests/label-place.spec.ts
//
// placeEveryLabel (components/chart-kit.tsx): the placer behind the frontier
// charts on /recommend and /models, which name EVERY point on the frontier and
// no other point. A name sits against its mark where a spot there is clear;
// where the crowd leaves none it moves a little off, joined to its mark by a
// line; and it is never left out. Pure tests over synthetic marks, with label
// widths from a fixed rule so they run without a browser.

import { test, expect } from "@playwright/test";

import { LABEL_H, placeEveryLabel, type Box, type Mark, type PlacedLabel, type Segment } from "../components/chart-kit";

const measure = (text: string) => text.length * 6.4;
const BOUNDS: Box = { x: 48, y: 2, w: 640, h: 400 };

function named(id: string, cx: number, cy: number, text = `Model ${id} · High`): Mark {
  return { id, cx, cy, r: 7.5, text, hard: true, priority: 1000 - cy };
}
function quiet(id: string, cx: number, cy: number): Mark {
  return { id, cx, cy, r: 3, text: null, hard: false, priority: 0 };
}

const overlaps = (a: Box, b: Box) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const dotBox = (m: Mark): Box => ({ x: m.cx - m.r, y: m.cy - m.r, w: 2 * m.r, h: 2 * m.r });
const inside = (b: Box, bounds: Box) =>
  b.x >= bounds.x - 0.01 && b.y >= bounds.y - 0.01 && b.x + b.w <= bounds.x + bounds.w + 0.01 && b.y + b.h <= bounds.y + bounds.h + 0.01;

// Where a line meets a box, by sampling: enough for a test.
function lineCrosses(l: Segment, b: Box): boolean {
  for (let i = 1; i < 40; i++) {
    const x = l.x1 + ((l.x2 - l.x1) * i) / 40;
    const y = l.y1 + ((l.y2 - l.y1) * i) / 40;
    if (x > b.x + 0.5 && x < b.x + b.w - 0.5 && y > b.y + 0.5 && y < b.y + b.h - 0.5) return true;
  }
  return false;
}

// What a clean layout holds: every plate in the plot, no two plates over one
// another, none over a mark it must keep off, and no line through a plate or
// such a mark.
function problems(marks: Mark[], placed: Map<string, PlacedLabel>, bounds: Box): string[] {
  const out: string[] = [];
  const labels = [...placed.entries()];
  for (const [id, l] of labels) {
    if (!inside(l.box, bounds)) out.push(`${id} leaves the plot`);
    for (const m of marks) {
      if (m.hard && overlaps(dotBox(m), l.box)) out.push(`${id} covers ${m.id}`);
      if (m.hard && m.id !== id && l.leader && lineCrosses(l.leader, dotBox(m))) out.push(`${id}'s line crosses ${m.id}`);
    }
    for (const [other, o] of labels) {
      if (other === id) continue;
      if (id < other && overlaps(l.box, o.box)) out.push(`${id} overlaps ${other}`);
      if (l.leader && lineCrosses(l.leader, o.box)) out.push(`${id}'s line crosses ${other}'s name`);
    }
  }
  return out;
}

// A frontier as the charts draw it: a staircase rising to the right, with a
// tight run low on the left and another at the top, over a scatter of quiet
// dots below the line.
function staircase(): Mark[] {
  const steps: [number, number][] = [
    [70, 330], [112, 312], [126, 302], [141, 280], [146, 250],
    [330, 232], [352, 208], [392, 198], [398, 172],
    [425, 160], [428, 148], [452, 136], [560, 128], [640, 124],
  ];
  const marks = steps.map(([x, y], i) => named(`f${String(i).padStart(2, "0")}`, x, y));
  let q = 0;
  for (let x = 110; x < 680; x += 47) {
    for (let y = 150; y < 390; y += 53) {
      const line = steps.filter(([sx]) => sx <= x).pop();
      // Only below the line: nothing off the frontier scores above it.
      if (line && y > line[1] + 22) marks.push(quiet(`q${q++}`, x + ((y * 7) % 19), y));
    }
  }
  return marks;
}

test("every mark with a name is named, and the layout is clean", () => {
  const marks = staircase();
  const placed = placeEveryLabel(marks, BOUNDS, [], measure);
  const want = marks.filter((m) => m.text !== null).map((m) => m.id);
  expect([...placed.keys()].sort()).toEqual(want.sort());
  expect(problems(marks, placed, BOUNDS)).toEqual([]);
  // No quiet dot is under a name here: there is room to keep off all of them.
  const covered = [...placed.entries()].flatMap(([id, l]) =>
    marks.filter((m) => !m.hard && overlaps(dotBox(m), l.box)).map((m) => `${id} covers ${m.id}`),
  );
  expect(covered).toEqual([]);
  // And only a mark with a name gets one.
  for (const id of placed.keys()) expect(id.startsWith("f")).toBe(true);
});

test("a mark with room keeps its name against it, with no line", () => {
  const placed = placeEveryLabel([named("a", 300, 200, "Opus 5.5 · Max")], BOUNDS, [], measure);
  const label = placed.get("a")!;
  expect(label.leader).toBeNull();
  expect(label.text).toBe("Opus 5.5 · Max");
  // To the left of the mark, on its level: above the staircase, where no dot is.
  expect(label.anchor).toBe("end");
  expect(label.box.x + label.box.w).toBeLessThan(300 - 7.5);
  expect(label.box.y + LABEL_H / 2).toBeCloseTo(200, 0);
});

test("in a crowd a name sits off its mark and a line joins the two", () => {
  // Three marks a few pixels apart: one name fits against its mark, not three.
  const marks = [named("a", 300, 200), named("b", 312, 194), named("c", 324, 188)];
  const placed = placeEveryLabel(marks, BOUNDS, [], measure);
  expect(placed.size).toBe(3);
  expect(problems(marks, placed, BOUNDS)).toEqual([]);
  const joined = marks.filter((m) => placed.get(m.id)!.leader !== null);
  expect(joined.length).toBeGreaterThan(0);
  for (const m of joined) {
    const { leader, box } = placed.get(m.id)!;
    // From the mark's own edge to its own plate.
    expect(Math.hypot(leader!.x1 - m.cx, leader!.y1 - m.cy)).toBeLessThan(m.r + 4);
    expect(leader!.x2).toBeGreaterThanOrEqual(box.x - 0.01);
    expect(leader!.x2).toBeLessThanOrEqual(box.x + box.w + 0.01);
    expect(leader!.y2).toBeGreaterThanOrEqual(box.y - 0.01);
    expect(leader!.y2).toBeLessThanOrEqual(box.y + box.h + 0.01);
  }
});

test("a name keeps off a quiet dot, and off a line it is asked to avoid, while a spot as near is clear", () => {
  // A quiet dot where the name would first go (left): it goes right instead.
  const dotted = [named("a", 300, 200), quiet("q", 270, 200)];
  const beside = placeEveryLabel(dotted, BOUNDS, [], measure).get("a")!;
  expect(overlaps(dotBox(dotted[1]), beside.box)).toBe(false);
  expect(beside.leader).toBeNull();
  // The frontier's own run to the right of a mark at the plot's left edge,
  // where no name fits to the left: the name goes above or below the run.
  const edge = [named("a", 60, 200)];
  const run: Segment = { x1: 60, y1: 200, x2: 400, y2: 200 };
  const off = placeEveryLabel(edge, BOUNDS, [run], measure).get("a")!;
  expect(off.box.y + off.box.h <= 200 || off.box.y >= 200).toBe(true);
});

test("with no room at all every mark is still named", () => {
  // Six names in a plot that holds two: overlap is the least bad, absence is
  // not an option.
  const tight: Box = { x: 0, y: 0, w: 150, h: 36 };
  const marks = Array.from({ length: 6 }, (_, i) => named(`m${i}`, 20 + i * 22, 18));
  const placed = placeEveryLabel(marks, tight, [], measure);
  expect(placed.size).toBe(6);
  for (const l of placed.values()) expect(inside(l.box, tight)).toBe(true);
});

test("the same marks give the same layout, whichever pick is selected", () => {
  const marks = staircase();
  const once = placeEveryLabel(marks, BOUNDS, [], measure);
  const again = placeEveryLabel([...marks].reverse(), BOUNDS, [], measure);
  expect(Object.fromEntries(again)).toEqual(Object.fromEntries(once));
});
