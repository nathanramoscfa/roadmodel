// web/lib/frontier-points.ts
//
// The points /recommend's cost/quality frontier is drawn over, and the
// frontier itself. A pick runs a model at an effort, so a point is a model at
// one effort: its price there (x) and its AA Intelligence Index there (y).
//
// An answer carries the points its own ladder weighed (lib/api.ts
// LadderPoint, from the service's scoring.ladder_points): every model the
// viewer can run, at each effort THIS task may run. Those are the points the
// picks were read from, so the frontier drawn over them is the one the
// recommender used: a pick sits on the line where the recommender found it,
// and each point says whether it meets the task's bar. A saved answer from
// before the field, and the page before any answer, have none; the frontier
// is then drawn over the catalog's rows the page already holds, each model at
// every effort Artificial Analysis measured it at (lib/pick-effort.ts).
//
// One rule for the frontier everywhere it is read (the cards' "On your
// frontier", the chart's ring, the dotted line): the rule /models draws its
// own by (lib/benchmark-grid.ts paretoFrontier), where a tie on the index
// goes to the cheaper point.
//
// Pure: safe to import from client components, and run as it is in tests.

import type { LadderPoint } from "./api";
import { paretoFrontier } from "./benchmark-grid";
import { EFFORT_TOKEN_MULTIPLIER, effortLabel, effortPoints, named, type EffortLevel } from "./pick-effort";
import type { PicksData, SlimRow } from "./recommend-picks";

// A page never needs more than the service sends (service/app/ranks.py
// MAX_POINTS); anything past it is not an answer's.
export const MAX_POINTS = 600;

export interface PlotPoint {
  // The model and effort, unique per point.
  key: string;
  // The catalog's row for the model.
  row: SlimRow;
  level: EffortLevel | null;
  // Where the point stands on the frontier: its AA Index as the recommender
  // counts it. An estimate is counted a margin below the figure it prints
  // (`shown`), for its uncertainty; a measurement is counted as it is.
  index: number;
  shown: number;
  price: number;
  // Artificial Analysis has not measured the model: the index is roadmodel's
  // estimate.
  estimated: boolean;
  // Meets the task's bar. True when the answer does not say (no task yet, or
  // an answer from before the field).
  adequate: boolean;
  // On the frontier over these points.
  frontier: boolean;
}

export interface Frontier {
  // Every point, cheapest first.
  points: PlotPoint[];
  byKey: Map<string, PlotPoint>;
  // The points are the answer's own (the efforts its task may run); false
  // when they are read from the catalog's rows (every measured effort).
  served: boolean;
}

export function pointKey(modelId: string, level: string | null | undefined): string {
  return `${modelId}@${level ?? "-"}`;
}

function levelOf(effort: unknown): EffortLevel | null {
  return typeof effort === "string" && effort in EFFORT_TOKEN_MULTIPLIER ? (effort as EffortLevel) : null;
}

function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

// The service's points, checked one by one before the page plots them: a
// saved run or an imported file can carry anything. Null when none is usable.
export function parsePoints(value: unknown): LadderPoint[] | null {
  if (!Array.isArray(value)) return null;
  const out: LadderPoint[] = [];
  for (const raw of value.slice(0, MAX_POINTS)) {
    if (typeof raw !== "object" || raw === null) continue;
    const v = raw as Record<string, unknown>;
    if (typeof v.model_id !== "string" || !v.model_id) continue;
    if (!finite(v.aa_index) || !finite(v.price_usd_per_1m) || !(v.price_usd_per_1m > 0)) continue;
    out.push({
      model_id: v.model_id,
      platform_id: typeof v.platform_id === "string" ? v.platform_id : "",
      effort: typeof v.effort === "string" ? v.effort : null,
      aa_index: v.aa_index,
      margin: finite(v.margin) && v.margin > 0 ? v.margin : 0,
      price_usd_per_1m: v.price_usd_per_1m,
      adequate: v.adequate !== false,
      estimated: v.estimated === true,
    });
  }
  return out.length > 0 ? out : null;
}

function finish(points: PlotPoint[], served: boolean): Frontier {
  const sorted = [...points].sort((a, b) => a.price - b.price || b.index - a.index || a.key.localeCompare(b.key));
  const on = paretoFrontier(sorted);
  for (const p of sorted) p.frontier = on.has(p);
  return { points: sorted, byKey: new Map(sorted.map((p) => [p.key, p])), served };
}

// The frontier for a page: over the answer's own points when it carries
// them, else over the catalog rows the viewer can run (data.pool; the whole
// catalog without saved Settings).
export function frontierOf(data: PicksData, served: readonly LadderPoint[] | null | undefined): Frontier {
  if (served && served.length > 0) {
    const seen = new Set<string>();
    const points: PlotPoint[] = [];
    for (const p of served) {
      const row = data.rows[p.model_id];
      if (!row) continue;
      const level = levelOf(p.effort);
      const key = pointKey(row.id, level);
      if (seen.has(key)) continue;
      seen.add(key);
      points.push({
        key,
        row,
        level,
        index: p.aa_index - (p.margin > 0 ? p.margin : 0),
        shown: p.aa_index,
        price: p.price_usd_per_1m,
        estimated: p.estimated === true,
        adequate: p.adequate !== false,
        frontier: false,
      });
    }
    // An answer whose models the catalog no longer lists draws nothing
    // useful: fall through to the catalog's own points.
    if (points.length >= 2) return finish(points, true);
  }
  const mine = data.pool ? new Set(data.pool) : null;
  const points = Object.values(data.rows)
    .filter((row) => !mine || mine.has(row.id))
    .flatMap((row) =>
      effortPoints(row).map(
        (p): PlotPoint => ({
          key: pointKey(row.id, p.level),
          row,
          level: p.level,
          index: p.index,
          shown: p.index,
          price: p.price,
          estimated: row.aa_index_source === "estimated" || row.aa_index_source === "inherited",
          adequate: true,
          frontier: false,
        }),
      ),
    );
  return finish(points, false);
}

// The point a model run at `level` is plotted at: its own, else the one point
// of a model the frontier holds at no named effort.
export function pointFor(frontier: Frontier, modelId: string, level: EffortLevel | null): PlotPoint | null {
  const own = frontier.byKey.get(pointKey(modelId, level));
  if (own) return own;
  const of = frontier.points.filter((p) => p.row.id === modelId);
  return of.length === 1 && of[0].level === null ? of[0] : null;
}

// The point that holds the top score at a price or less: the highest index
// among the points that cost no more, a tie going to the cheaper. Null when
// nothing there scores higher (or the same for less) than `at` itself.
export function leaderAt(
  frontier: Frontier,
  at: { price: number; index: number; key?: string },
): PlotPoint | null {
  let best: PlotPoint | null = null;
  for (const p of frontier.points) {
    if (p.price > at.price + 1e-9) break;
    if (p.key === at.key) continue;
    if (best === null || p.index > best.index) best = p;
  }
  if (best === null) return null;
  if (best.index > at.index) return best;
  return best.index === at.index && best.price < at.price - 1e-9 ? best : null;
}

export function pointName(p: PlotPoint): string {
  return p.level ? `${p.row.name} · ${effortLabel(p.level)}` : p.row.name;
}

// A point as /models' cards read a model: named for its effort, with its AA
// Index there as a ladder prints it, how far below that the recommender counts
// it, and where it stands on this frontier.
export function pointRow(frontier: Frontier, p: PlotPoint): SlimRow {
  const base = p.level ? named(p.row, p.level, p.shown) : { ...p.row, aa_index: p.shown };
  const leader = p.frontier ? null : leaderAt(frontier, p);
  return {
    ...base,
    aa_index_margin: p.shown - p.index,
    // A measured model read at a level of the answer's own.
    aa_index_level_estimated:
      p.level !== null && p.row.aa_index_source === "snapshot" && p.row.aa_index_by_effort?.[p.level] === undefined,
    value_frontier: p.frontier,
    value_beaten_by: leader ? leader.key : null,
  };
}
