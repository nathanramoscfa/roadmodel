// web/lib/ladder-view.ts
//
// One shape for everything /recommend shows about an answer, whichever lane
// wrote it: the AI recommender's three picks (lib/api.ts) or Quick pick's
// three rungs (lib/keyless.ts). Each becomes a column (Cost, Balanced,
// Quality) ranked three deep, the way a roadmap's Settings rank it: the Pick,
// a Runner-up from another maker and a Backup from a third, each option with
// the platform and level it runs at, its AA Intelligence Index there and its
// price there.
//
// The service ranks the column (service/app/ranks.py) and sends each option's
// figures, with the settings its ladder weighed: the points the frontier is
// drawn over (lib/frontier-points.ts), so each option's standing ("On your
// frontier", or the point that holds the top score at its price) is read
// from the frontier the picks themselves were read from. An answer from
// before it did (a saved run, an older service) has the Pick and its single
// cross-maker backup; their figures and the frontier are then read from the
// catalog rows the page already holds (lib/pick-effort.ts).
//
// Pure: safe to import from client components, and run as it is in tests.

import type { LadderTask, MultiRecommendResponse, PriorityRecommendation, RankedOption, Ranks } from "./api";
import type { Category } from "./catalog-fields";
import type { CostRow } from "./cost-format";
import {
  frontierOf,
  leaderAt,
  parsePoints,
  pointFor,
  pointRow,
  type Frontier,
  type PlotPoint,
} from "./frontier-points";
import type { KeylessPriority, KeylessResponse, KeylessRung } from "./keyless";
import { parseLadderTask } from "./ladder-task";
import {
  EFFORT_TOKEN_MULTIPLIER,
  effortLabel,
  effortPrice,
  headlinePrice,
  pickAtEffort,
  pickEffort,
  type EffortLevel,
} from "./pick-effort";
import type { BudgetPriority } from "./profile";
import { inPool, rowForPick, type PicksData, type SlimRow } from "./recommend-picks";
import { formatSettingValue, humanizeSettingKey } from "./settings-format";

export type Rank = "pick" | "runner_up" | "backup";

export const RANK_LABEL: Record<Rank, string> = {
  pick: "Pick",
  runner_up: "Runner-up",
  backup: "Backup",
};

export const PRIORITY_ORDER: readonly BudgetPriority[] = ["cheap", "balanced", "best"];

export const PRIORITY_LABEL: Record<BudgetPriority, { label: string; hint: string; letter: string }> = {
  cheap: { label: "Cost", hint: "Cheapest that does the job", letter: "C" },
  balanced: { label: "Balanced", hint: "Best value", letter: "B" },
  best: { label: "Quality", hint: "Strongest for the task", letter: "Q" },
};

// The platforms whose level dial is called Intelligence (the scorer's
// _DIAL_NAMES); every other surface with a dial calls it Effort.
const INTELLIGENCE_PLATFORMS = new Set(["codex-cli", "codex-api", "openai-api"]);
const INTELLIGENCE_NAMES = new Set(["codex", "codex api", "openai api"]);

// A dial no option sets carries no signal: a setting where every pick reads
// one of these is left out.
const NO_VALUE = new Set(["", "—", "-", "off", "n/a", "na", "none"]);

// The Pick's level has its own row, the tier is the column, and the
// rationale has its own panel. Claude Code's Ultracode arrives as `ultracode`
// (roadmodel >= 0.2.88), never as `orchestration`. Thinking has no row, as in
// a roadmap's ladder: it is on wherever a platform has that switch, and every
// AA Index and price is read with it on.
const SETTINGS_NOT_LISTED = new Set(["rationale", "budget_priority", "orchestration", "effort", "intelligence", "thinking"]);

export interface OptionView {
  rank: Rank;
  model: string;
  platform: string | null;
  // The level as the dials word it ("Extra high"), "Fixed" for a preset whose
  // level is not set, or null where the surface names none.
  level: string | null;
  // What the platform calls that dial: Effort, or Intelligence on Codex.
  dial: string;
  // The same level as the scorer names it; null for a preset or no level.
  effort: EffortLevel | null;
  // The Pick's own model one or two levels lower: no other maker's model
  // fills this rank.
  steppedDown: boolean;
  ultracode: boolean;
  // The catalog's row read at this option's level (named for it, with its AA
  // Index, Score and frontier mark there), for the cards /models shows; null
  // for a model the catalog does not list.
  row: SlimRow | null;
  // The point that holds the top score at this option's price or less, read
  // the same way; null on the frontier.
  leader: SlimRow | null;
  // Where the option sits among the points the frontier is drawn over; null
  // when it is none of them (a model outside the viewer's, or no figures).
  point: PlotPoint | null;
  // The tokens the model draws at this level relative to a typical model at
  // high, which the price scales its output by; null with no measured level.
  tokenShare: number | null;
  // AA Intelligence Index at the level; `aaEstimated` when Artificial
  // Analysis has not measured the model there.
  aa: number | null;
  aaEstimated: boolean;
  // USD per 1M blended tokens at the level's token use; `priceEstimated`
  // when that token use was derived, not measured.
  price: number | null;
  priceEstimated: boolean;
  // The /models Score at these figures.
  score: number | null;
  // Among the models the frontier is drawn over.
  inPool: boolean;
}

export interface SettingView {
  key: string;
  label: string;
  value: string;
}

export interface WhySection {
  key: string;
  label: string;
  text: string;
}

export interface ColumnView {
  priority: BudgetPriority;
  pick: OptionView;
  runnerUp: OptionView | null;
  backup: OptionView | null;
  // The service ranked this column three deep; false for an answer that
  // carries the Pick and one backup only.
  ranked: boolean;
  // What to set beside the level, on the surfaces that expose it.
  settings: SettingView[];
  // What the Pick costs this viewer, when the answer says.
  cost: { amount: string; source: string; funded: boolean } | null;
  // The category this Pick is the top model for, when it is a specialist off
  // the frontier.
  specialist: string | null;
  // The reasoning, as labelled sections, with the engine's single string
  // when it wrote no sections.
  why: { sections: WhySection[]; rationale: string | null };
  costRows: CostRow[];
  // The Pick's categories rated from an Artificial Analysis figure.
  measured: Category[];
}

export interface LadderView {
  source: "engine" | "quick";
  task: LadderTask | null;
  // The tier the answer leads with, and what its card calls that: the
  // viewer's saved default, or the priority they chose for a Quick pick.
  primary: BudgetPriority;
  primaryLabel: string;
  columns: ColumnView[];
  // Any column carries a Runner-up.
  ranked: boolean;
  backupWarning: string | null;
  // The points the picks were read from and the frontier over them.
  frontier: Frontier;
}

function isShown(value: string): boolean {
  return !NO_VALUE.has(value.trim().toLowerCase());
}

// A level as the page words it: the scorer's five as the dials do ("xhigh" and
// "XHigh" both read "Extra high"), a preset as "Fixed", anything else as given.
function levelWord(raw: string | null | undefined): { word: string | null; effort: EffortLevel | null } {
  const text = (raw ?? "").trim();
  if (!isShown(text)) return { word: null, effort: null };
  const effort = pickEffort({ effort: text });
  if (effort) return { word: effortLabel(effort), effort };
  return { word: formatSettingValue(text), effort: null };
}

function dialFor(platformId: string | null | undefined, platform: string | null | undefined, intelligence = false): string {
  if (intelligence) return "Intelligence";
  if (platformId && INTELLIGENCE_PLATFORMS.has(platformId.toLowerCase())) return "Intelligence";
  if (platform && INTELLIGENCE_NAMES.has(platform.trim().toLowerCase())) return "Intelligence";
  return "Effort";
}

interface OptionSource {
  rank: Rank;
  model: string;
  platform: string | null;
  platformId?: string | null;
  // The level as the answer words it, for display.
  level: string | null | undefined;
  // The scorer's level the figures are read at, when the answer names it
  // apart from the word (a surface with no dial shows no level, and its
  // figures are still read at one).
  effort?: string | null;
  intelligence?: boolean;
  ultracode?: boolean;
  steppedDown?: boolean;
  // The service's figures at the level, where it sent them.
  aa?: number | null;
  aaEstimated?: boolean;
  price?: number | null;
  priceMeasured?: boolean | null;
}

function headlineLevel(row: SlimRow): EffortLevel | null {
  const level = row.aa_index_effort;
  return level && level in EFFORT_TOKEN_MULTIPLIER ? (level as EffortLevel) : null;
}

function option(data: PicksData, frontier: Frontier, src: OptionSource): OptionView {
  const shown = levelWord(src.level);
  const word = shown.word;
  const effort = src.effort != null ? pickEffort({ effort: src.effort }) : shown.effort;
  const ultracode = src.ultracode === true;
  const base = rowForPick(data, src.model);
  const at = base
    ? pickAtEffort(data, base, effort, { index: src.aa, indexEstimated: src.aaEstimated, price: src.price })
    : null;
  let row = at?.row ?? null;
  const aa = at?.level ? row!.aa_index : (src.aa ?? row?.aa_index ?? null);
  const price =
    src.price ??
    (base ? (at?.level ? effortPrice(base, at.level) : headlinePrice(base)) : null);
  const among = base
    ? frontier.served
      ? frontier.points.some((p) => p.row.id === base.id)
      : inPool(data, base)
    : false;

  // Where it stands on the frontier the picks were read from: at its own
  // point when it is one of them (the level its figures are read at), else by
  // its figures against them.
  let point: PlotPoint | null = null;
  let leader: SlimRow | null = null;
  if (base && row && among && aa !== null && price !== null) {
    point = pointFor(frontier, base.id, at?.level ?? headlineLevel(row));
    const lead = point ? (point.frontier ? null : leaderAt(frontier, point)) : leaderAt(frontier, { price, index: aa });
    row = {
      ...row,
      // An estimate stands on the frontier where the recommender counts it.
      aa_index_margin: point ? point.shown - point.index : 0,
      value_frontier: point ? point.frontier : lead === null,
      value_beaten_by: lead ? lead.key : null,
    };
    leader = lead ? pointRow(frontier, lead) : null;
  } else if (row) {
    row = { ...row, value_frontier: false, value_beaten_by: null };
  }

  const estimatedModel = row?.aa_index_source === "estimated" || row?.aa_index_source === "inherited";
  return {
    rank: src.rank,
    model: src.model,
    platform: src.platform && src.platform.trim() ? src.platform : null,
    level: word,
    dial: dialFor(src.platformId, src.platform, src.intelligence),
    effort,
    steppedDown: src.steppedDown === true,
    ultracode,
    row,
    leader,
    point,
    tokenShare: at?.tokenShare ?? null,
    aa,
    aaEstimated: row ? Boolean(estimatedModel || row.aa_index_level_estimated) : src.aaEstimated === true,
    price,
    priceEstimated: src.priceMeasured === false,
    score: row?.value_score ?? null,
    inPool: among,
  };
}

function isNumberOrNull(v: unknown): v is number | null {
  return v === null || (typeof v === "number" && Number.isFinite(v));
}

function parseOption(value: unknown): RankedOption | null {
  if (typeof value !== "object" || value === null) return null;
  const v = value as Record<string, unknown>;
  for (const key of ["model", "model_id", "platform", "platform_id", "effort", "level"]) {
    if (typeof v[key] !== "string") return null;
  }
  if (!(v.model as string).trim()) return null;
  return {
    model: v.model as string,
    model_id: v.model_id as string,
    platform: v.platform as string,
    platform_id: v.platform_id as string,
    effort: v.effort as string,
    level: v.level as string,
    aa_index: isNumberOrNull(v.aa_index) ? v.aa_index : null,
    aa_estimated: v.aa_estimated === true,
    price_usd_per_1m: isNumberOrNull(v.price_usd_per_1m) ? v.price_usd_per_1m : null,
    price_measured: typeof v.price_measured === "boolean" ? v.price_measured : null,
    stepped_down: v.stepped_down === true,
    ultracode: v.ultracode === true,
  };
}

// The service's ranks, checked before the page reads them: a saved run or an
// imported file can carry anything. Null when there is no usable Pick.
export function parseRanks(value: unknown): Ranks | null {
  if (typeof value !== "object" || value === null) return null;
  const v = value as Record<string, unknown>;
  const pick = parseOption(v.pick);
  if (!pick) return null;
  return { pick, runner_up: parseOption(v.runner_up), backup: parseOption(v.backup) };
}

function fromRanked(data: PicksData, frontier: Frontier, rank: Rank, o: RankedOption): OptionView {
  return option(data, frontier, {
    rank,
    model: o.model,
    platform: o.platform,
    platformId: o.platform_id,
    level: o.level,
    effort: o.effort,
    ultracode: o.ultracode,
    steppedDown: o.stepped_down,
    aa: o.aa_index,
    aaEstimated: o.aa_estimated,
    price: o.price_usd_per_1m,
    priceMeasured: o.price_measured,
  });
}

function fromSettings(
  data: PicksData,
  frontier: Frontier,
  rank: Rank,
  model: string,
  platform: string | null,
  settings: Record<string, unknown> | null | undefined,
): OptionView {
  const s = settings ?? {};
  const effort = formatSettingValue(s.effort);
  const intelligence = !isShown(effort) && isShown(formatSettingValue(s.intelligence));
  // An answer from before the level had a field of its own carried it as
  // `thinking` ("High"); the switch's own values (On, Off) name no level.
  const carried =
    !isShown(effort) && !intelligence && typeof s.thinking === "string" && pickEffort({ effort: s.thinking }) !== null
      ? s.thinking
      : null;
  return option(data, frontier, {
    rank,
    model,
    platform,
    level: intelligence ? String(s.intelligence) : typeof s.effort === "string" && isShown(effort) ? s.effort : carried,
    intelligence,
    ultracode: String(s.ultracode ?? "").toLowerCase() === "on",
  });
}

// The settings every Pick's card lists beside its level: each dial at least
// one pick sets, in the order the answer names them.
function settingKeys(recs: readonly PriorityRecommendation[]): string[] {
  const seen: string[] = [];
  for (const rec of recs) {
    for (const key of Object.keys(rec.settings ?? {})) {
      if (!SETTINGS_NOT_LISTED.has(key) && !seen.includes(key)) seen.push(key);
    }
  }
  return seen.filter((key) => recs.some((rec) => isShown(formatSettingValue((rec.settings ?? {})[key]))));
}

// The pick's headline cost: the viewer's funded cost when the edge
// personalized the cost table, else the session estimate.
export function headlineCost(rec: PriorityRecommendation): { amount: string; source: string; funded: boolean } | null {
  const table = rec.comparison_table ?? [];
  const fundedRow = table.find((row) => row.funded === true && typeof row.your_cost === "string");
  if (fundedRow) {
    const [amount, ...rest] = String(fundedRow.your_cost).replace(/^✓\s*/, "").split(/\s*·\s*/);
    return { amount, source: rest.join(" · "), funded: true };
  }
  const total = rec.session_cost_estimate?.total_usd;
  if (typeof total === "number") return { amount: `$${total.toFixed(4)}`, source: "per session", funded: false };
  return null;
}

// The rationale string the edge assembles into settings.rationale; structured
// sections, when the service sent them, take precedence where it is shown.
function rationaleOf(rec: PriorityRecommendation): string | null {
  const fromSettings = rec.settings?.rationale;
  if (typeof fromSettings === "string" && fromSettings.trim()) return fromSettings;
  const first = rec.comparison_table?.[0];
  return first && typeof first.rationale === "string" ? first.rationale : null;
}

// roadmodel answers what to run and with which settings, so the sections are
// the task as read, why the pick, and why the level (a legacy "run" segment,
// how to invoke it, is not shown).
const ENGINE_SECTIONS: { key: string; label: string }[] = [
  { key: "task", label: "The task" },
  { key: "pick", label: "Why this pick" },
  { key: "effort", label: "Why this effort" },
];

function sectionsOf(
  source: Record<string, unknown> | null | undefined,
  labels: readonly { key: string; label: string }[],
): WhySection[] {
  return labels.flatMap(({ key, label }) => {
    const text = source?.[key];
    return typeof text === "string" && text.trim() ? [{ key, label, text: text.trim() }] : [];
  });
}

function engineColumn(
  data: PicksData,
  frontier: Frontier,
  rec: PriorityRecommendation,
  keys: readonly string[],
): ColumnView {
  const ranks = parseRanks(rec.ranks);
  const pick = ranks
    ? fromRanked(data, frontier, "pick", ranks.pick)
    : fromSettings(data, frontier, "pick", rec.model, rec.platform, rec.settings);
  const legacyBackup = rec.backup?.model
    ? fromSettings(data, frontier, "backup", rec.backup.model, rec.backup.platform, rec.backup.settings)
    : null;
  const settings = rec.settings ?? {};
  return {
    priority: rec.priority,
    pick,
    runnerUp: ranks?.runner_up ? fromRanked(data, frontier, "runner_up", ranks.runner_up) : null,
    backup: ranks ? (ranks.backup ? fromRanked(data, frontier, "backup", ranks.backup) : null) : legacyBackup,
    ranked: ranks !== null,
    settings: keys.map((key) => ({
      key,
      label: humanizeSettingKey(key),
      value: formatSettingValue(settings[key]),
    })),
    cost: headlineCost(rec),
    specialist: rec.specialist && rec.specialist_category ? rec.specialist_category : null,
    why: { sections: sectionsOf(rec.rationale_sections, ENGINE_SECTIONS), rationale: rationaleOf(rec) },
    costRows: rec.comparison_table ?? [],
    measured: pick.row ? (data.measured[pick.row.id] ?? []) : [],
  };
}

export function engineLadder(data: PicksData, answer: MultiRecommendResponse): LadderView {
  const recs = [...answer.recommendations].sort(
    (a, b) => PRIORITY_ORDER.indexOf(a.priority) - PRIORITY_ORDER.indexOf(b.priority),
  );
  const keys = settingKeys(recs);
  const frontier = frontierOf(data, parsePoints(answer.points));
  const columns = recs.map((rec) => engineColumn(data, frontier, rec, keys));
  return {
    source: "engine",
    task: parseLadderTask(answer.task),
    primary: answer.primary,
    primaryLabel: "Default",
    columns,
    ranked: columns.some((c) => c.ranked),
    backupWarning: null,
    frontier,
  };
}

const RUNG_PRIORITY: Record<KeylessPriority, BudgetPriority> = {
  cost: "cheap",
  balanced: "balanced",
  quality: "best",
};

const QUICK_SECTIONS: { key: string; label: string }[] = [
  { key: "quality", label: "Strength" },
  { key: "requirement_shortfall", label: "Fit to the task" },
  { key: "cost", label: "Cost" },
];

function quickColumn(data: PicksData, frontier: Frontier, rung: KeylessRung, category: string): ColumnView {
  const ranks = parseRanks(rung.ranks);
  const pick = ranks
    ? fromRanked(data, frontier, "pick", ranks.pick)
    : option(data, frontier, {
        rank: "pick",
        model: rung.model_name,
        platform: rung.platform_name,
        platformId: rung.platform_id,
        level: rung.effort,
        ultracode: rung.ultracode === true,
      });
  const legacyBackup = rung.backup
    ? option(data, frontier, {
        rank: "backup",
        model: rung.backup.model_name,
        platform: rung.backup.platform_name,
        platformId: rung.backup.platform_id,
        level: rung.backup.effort,
        ultracode: rung.backup.ultracode === true,
      })
    : null;
  return {
    priority: RUNG_PRIORITY[rung.priority],
    pick,
    runnerUp: ranks?.runner_up ? fromRanked(data, frontier, "runner_up", ranks.runner_up) : null,
    backup: ranks ? (ranks.backup ? fromRanked(data, frontier, "backup", ranks.backup) : null) : legacyBackup,
    ranked: ranks !== null,
    settings: pick.ultracode ? [{ key: "ultracode", label: "Ultracode", value: "On" }] : [],
    cost: null,
    specialist: rung.specialist ? category : null,
    why: { sections: sectionsOf(rung.why, QUICK_SECTIONS), rationale: null },
    costRows: [],
    measured: pick.row ? (data.measured[pick.row.id] ?? []) : [],
  };
}

export function quickLadder(data: PicksData, answer: KeylessResponse): LadderView {
  const frontier = frontierOf(data, parsePoints(answer.points));
  const columns = answer.rungs
    .map((rung) => quickColumn(data, frontier, rung, answer.task.category))
    .sort((a, b) => PRIORITY_ORDER.indexOf(a.priority) - PRIORITY_ORDER.indexOf(b.priority));
  const budget = answer.task.budget_priority;
  return {
    source: "quick",
    task: parseLadderTask(answer.task),
    primary: (PRIORITY_ORDER as readonly string[]).includes(budget) ? (budget as BudgetPriority) : "balanced",
    primaryLabel: "Your priority",
    columns,
    ranked: columns.some((c) => c.ranked),
    backupWarning: answer.backup_warning,
    frontier,
  };
}

// The trade-off line when every Pick costs the viewer $0 (a subscription
// funds all of them): then they differ in capability and effort, not price.
// The funding source when all name the same one.
export function fundedZero(view: LadderView): { source: string | null } | null {
  if (view.columns.length < 2) return null;
  const costs = view.columns.map((c) => c.cost);
  if (costs.some((c) => !c || !c.funded || !/^\$0(?![.\d])/.test(c.amount.trim()))) return null;
  const sources = new Set(
    costs.map((c) => {
      const s = c!.source.trim();
      return !s || s.length > 24 || s.includes("$") ? "" : s;
    }),
  );
  const source = sources.size === 1 ? [...sources][0] : "";
  return { source: source || null };
}
