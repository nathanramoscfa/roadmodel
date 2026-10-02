// web/components/PicksMatrix.tsx
//
// The three picks side by side: Cost, Balanced and Quality are COLUMNS and
// what they share are ROWS (your cost, the settings each surface exposes, the
// backup, the seven ratings), so each row is read once and scanned across.
// The catalog's own facts about each model sit in rows too, in the /models
// vocabulary: its blended price, AA Intelligence Index and Score (hover the
// index for where it stands against the frontier, the Score for how it adds
// up), and its S→D letters (filled = measured from an Artificial Analysis
// figure, dashed = estimated), so a pick reads the same here as in the
// catalog. The header says whether the pick is on the frontier: the viewer's
// own, drawn over the models their Settings reach, once they have saved them.
//
// Selecting a column shows that pick's rationale and cost below. Below the md
// breakpoint the columns become a segmented control over one pick at a time.
"use client";

import { Fragment, useEffect, useState, type ReactNode } from "react";

import type { PriorityRecommendation } from "@/lib/api";
import { BUDGET_PRIORITY_OPTIONS } from "@/lib/budget-priority";
import { formatScore, formatUsd } from "@/lib/benchmark-grid";
import {
  CATEGORY_DEFS,
  CATEGORY_ORDER,
  COST_TIER_DEFS,
  ESTIMATED_BADGE,
  RATING_COLORS,
  RATING_OUTLINE_COLORS,
  type Category,
} from "@/lib/catalog-fields";
import type { BudgetPriority } from "@/lib/profile";
import {
  blendedOf,
  inPool,
  rowForPick,
  type PicksData,
  type SlimRow,
} from "@/lib/recommend-picks";
import { formatSettingValue, humanizeSettingKey } from "@/lib/settings-format";
import { FRONTIER } from "./chart-kit";
import { HoverCard } from "./FloatingCard";
import {
  FrontierPointCard,
  ScoreBreakdownCard,
  scoreToneClass,
} from "./ScoreCards";

const LABELS = new Map(BUDGET_PRIORITY_OPTIONS.map((o) => [o.id, o]));

const SHORT_HINT: Record<string, string> = {
  cheap: "Cheapest that works",
  balanced: "Best value",
  best: "Highest quality",
};

// budget_priority is the column itself; the rationale renders below; Claude
// Code's Ultracode is the top of its one effort ladder, folded into the effort
// value (roadmodel >= 0.2.16), so a stale `orchestration` key is hidden too.
const HIDDEN_SETTING_KEYS = new Set([
  "rationale",
  "budget_priority",
  "orchestration",
]);

// A dial no pick sets carries no signal; a row where every pick is one of
// these is dropped (e.g. "Max Mode: Off / — / —").
const MEANINGLESS_VALUES = new Set(["", "—", "-", "off", "n/a", "na", "none"]);

const CATEGORY_INITIAL: Record<Category, string> = {
  coding: "C",
  planning: "P",
  agentic: "A",
  multimodal: "M",
  "long-context": "L",
  knowledge: "K",
  speed: "S",
};

// The selected column reads as one continuous outlined box: the header's
// accent border runs down every cell as inset side shadows, and the last
// cell closes it. #2563eb is brand-accent.
const ACTIVE_TINT = "bg-brand-accent/10";
const ACTIVE_HEAD = "border-brand-accent border-b-transparent " + ACTIVE_TINT;
const ACTIVE_CELL_SIDES =
  "shadow-[inset_1.5px_0_0_#2563eb,inset_-1.5px_0_0_#2563eb]";
const ACTIVE_CELL_LAST =
  "shadow-[inset_1.5px_0_0_#2563eb,inset_-1.5px_0_0_#2563eb,inset_0_-1.5px_0_#2563eb] rounded-b-lg";

// Below Tailwind's md breakpoint the picks become a segmented control. Only
// the active layout is rendered (a CSS-hidden twin would repeat every label
// to screen readers); results render after a request, so there is no
// server-rendered layout to mismatch.
function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const update = () => setNarrow(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return narrow;
}

function isMeaningful(value: string): boolean {
  return !MEANINGLESS_VALUES.has(value.trim().toLowerCase());
}

function settingKeys(recs: PriorityRecommendation[]): string[] {
  const seen: string[] = [];
  for (const rec of recs) {
    for (const key of Object.keys(rec.settings ?? {})) {
      if (!HIDDEN_SETTING_KEYS.has(key) && !seen.includes(key)) seen.push(key);
    }
  }
  return seen.filter((key) =>
    recs.some((rec) =>
      isMeaningful(formatSettingValue((rec.settings ?? {})[key])),
    ),
  );
}

// The pick's headline cost: the user's funded cost when the edge personalized
// the cost table, else the session estimate.
export function headlineCost(rec: PriorityRecommendation): {
  amount: string;
  source: string;
  funded: boolean;
} {
  const table = rec.comparison_table ?? [];
  const fundedRow = table.find(
    (row) => row.funded === true && typeof row.your_cost === "string",
  );
  if (fundedRow) {
    const [amount, ...rest] = String(fundedRow.your_cost)
      .replace(/^✓\s*/, "")
      .split(/\s*·\s*/);
    return { amount, source: rest.join(" · "), funded: true };
  }
  const total = rec.session_cost_estimate?.total_usd;
  if (typeof total === "number")
    return {
      amount: `$${total.toFixed(4)}`,
      source: "per session",
      funded: false,
    };
  return { amount: "—", source: "", funded: false };
}

function Ratings({ row, measured }: { row: SlimRow; measured: Category[] }) {
  return (
    <span className="inline-grid grid-cols-7 gap-1" data-testid="pick-ratings">
      {CATEGORY_ORDER.map((cat) => {
        const r = row.tiers[cat];
        const isMeasured = measured.includes(cat);
        return (
          <span key={cat} className="flex flex-col items-center gap-0.5">
            <span className="text-[9px] font-semibold uppercase leading-none text-brand-slate-400 dark:text-brand-slate-500">
              {CATEGORY_INITIAL[cat]}
            </span>
            <span
              className={
                "inline-flex h-5 w-5 items-center justify-center rounded text-[11px] font-bold " +
                (isMeasured
                  ? RATING_COLORS[r]
                  : `${ESTIMATED_BADGE} ${RATING_OUTLINE_COLORS[r]}`)
              }
              title={`${CATEGORY_DEFS[cat].fullName}: ${r}${isMeasured ? " (measured)" : " (estimated)"}`}
              data-basis={isMeasured ? "measured" : "estimated"}
            >
              {r}
            </span>
          </span>
        );
      })}
    </span>
  );
}

// Under a pick's name: whether it is on the cost/quality frontier (the
// viewer's own, when they have saved Settings), or the model that beats it,
// with the /models card on hover.
function PickFacts({ row, data }: { row: SlimRow | null; data: PicksData }) {
  if (!row) {
    return (
      <span className="text-[11px] text-brand-slate-400 dark:text-brand-slate-500">
        Not in the catalog
      </span>
    );
  }
  if (row.aa_index === null || !inPool(data, row)) return null;
  const yours = data.pool !== null;
  const leader = row.value_beaten_by
    ? (data.rows[row.value_beaten_by] ?? null)
    : null;
  if (row.value_frontier) {
    return (
      <span
        className="inline-flex items-center gap-1 text-[10.5px] font-medium"
        style={{ color: FRONTIER }}
        title={
          yours
            ? "On your cost/quality frontier: it scores highest on the AA Index of the models you can use at its price or less"
            : "On the cost/quality frontier: it scores highest on the AA Index of the catalog's models at its price or less"
        }
        data-testid="pick-frontier"
      >
        <span
          className="inline-block h-2 w-2 rounded-full border-2"
          style={{ borderColor: FRONTIER }}
        />
        {yours ? "your frontier" : "frontier"}
      </span>
    );
  }
  if (!leader) return null;
  return (
    <HoverCard
      label={`${row.name}: ${leader.name} scores higher at its price or less`}
      card={<FrontierPointCard model={row} leader={leader} />}
      className="self-start text-[10.5px] font-medium text-orange-700 dark:text-orange-300"
      triggerTestId="pick-beaten"
    >
      Beaten by {leader.name}
    </HoverCard>
  );
}

const MUTED_UNIT = "font-normal text-brand-slate-400 dark:text-brand-slate-500";

// Blended price, as /models prices every model: (3 × input + output) ÷ 4.
function PriceCell({ row }: { row: SlimRow }) {
  return (
    <span
      title={`(3 × ${formatUsd(row.input_price_per_1m)} input + ${formatUsd(row.output_price_per_1m)} output) ÷ 4 · ${COST_TIER_DEFS[row.tier_cost].label} cost tier`}
    >
      <span className="tabular-nums" data-testid="pick-price">
        ${blendedOf(row).toFixed(2)}
      </span>{" "}
      <span className={MUTED_UNIT}>per 1M tokens</span>
    </span>
  );
}

function IndexCell({ row, data }: { row: SlimRow; data: PicksData }) {
  if (row.aa_index === null) {
    return <span className={MUTED_UNIT}>not measured</span>;
  }
  const value = row.aa_index.toFixed(1);
  if (!inPool(data, row)) {
    return (
      <span className="tabular-nums" data-testid="pick-aa-index">
        {value}
      </span>
    );
  }
  const leader = row.value_beaten_by
    ? (data.rows[row.value_beaten_by] ?? null)
    : null;
  return (
    <HoverCard
      label={`${row.name}: AA Intelligence Index ${value}`}
      card={<FrontierPointCard model={row} leader={leader} />}
      className="tabular-nums"
      triggerTestId="pick-aa-index"
    >
      {value}
    </HoverCard>
  );
}

// The /models Score: AA Index points above or below what the model's price
// predicts among its cost tier.
function ScoreCell({ row, data }: { row: SlimRow; data: PicksData }) {
  if (row.value_score === null) return <span className={MUTED_UNIT}>—</span>;
  const tone = data.fit
    ? scoreToneClass(row.value_score, data.fit.sigma)
    : "";
  const shown = formatScore(row.value_score);
  if (!data.fit || !inPool(data, row)) {
    return (
      <span className={"font-semibold tabular-nums " + tone} data-testid="pick-score">
        {shown}
      </span>
    );
  }
  const leader = row.value_beaten_by
    ? (data.rows[row.value_beaten_by] ?? null)
    : null;
  return (
    <HoverCard
      label={`${row.name}: Score ${shown}. Show how it adds up`}
      card={
        <ScoreBreakdownCard
          model={row}
          fit={data.fit}
          snapshot={data.snapshot}
          leader={leader}
        />
      }
      className={"font-semibold tabular-nums " + tone}
      triggerTestId="pick-score"
    >
      {shown}
    </HoverCard>
  );
}

interface MatrixRow {
  key: string;
  label: string;
  cell: (
    rec: PriorityRecommendation,
    row: SlimRow | null,
  ) => { node: ReactNode; funded?: boolean };
}

function matrixRows(
  recs: PriorityRecommendation[],
  data: PicksData,
): MatrixRow[] {
  const keys = settingKeys(recs);
  const showBackup = recs.some((r) => r.backup?.model);
  const inCatalog = recs.some((r) => rowForPick(data, r.model));
  const facts: MatrixRow[] = inCatalog
    ? [
        {
          key: "__price",
          label: "Blended price",
          cell: (_rec, row) => ({ node: row ? <PriceCell row={row} /> : "—" }),
        },
        {
          key: "__aa",
          label: "AA Index",
          cell: (_rec, row) => ({
            node: row ? <IndexCell row={row} data={data} /> : "—",
          }),
        },
        {
          key: "__score",
          label: "Score",
          cell: (_rec, row) => ({
            node: row ? <ScoreCell row={row} data={data} /> : "—",
          }),
        },
      ]
    : [];
  return [
    {
      key: "__cost",
      label: "Your cost",
      cell: (rec) => {
        const c = headlineCost(rec);
        return {
          node: (
            <>
              <span>{c.amount}</span>
              {c.source ? (
                <span className="font-normal text-brand-slate-400 dark:text-brand-slate-500">
                  {c.source}
                </span>
              ) : null}
            </>
          ),
          funded: c.funded,
        };
      },
    },
    ...facts,
    ...keys
      // Codex names its reasoning dial "Intelligence"; every other surface
      // calls it Effort. When the picks span both, one Effort row carries
      // either value (the Codex cell says so) instead of two half-empty rows.
      .filter((key) => !(key === "intelligence" && keys.includes("effort")))
      .map((key): MatrixRow => ({
        key,
        label: humanizeSettingKey(key),
        cell: (rec) => {
          const settings = rec.settings ?? {};
          if (
            key === "effort" &&
            !isMeaningful(formatSettingValue(settings.effort)) &&
            settings.intelligence
          ) {
            return {
              node: (
                <>
                  <span>{formatSettingValue(settings.intelligence)}</span>
                  <span className="text-xs text-brand-slate-400 dark:text-brand-slate-500">
                    Intelligence
                  </span>
                </>
              ),
            };
          }
          return { node: formatSettingValue(settings[key]) };
        },
      })),
    ...(showBackup
      ? [
          {
            key: "__backup",
            label: "Backup",
            cell: (rec: PriorityRecommendation) => ({
              node: rec.backup?.model ?? "—",
            }),
          } satisfies MatrixRow,
        ]
      : []),
    ...(inCatalog
      ? [
          {
            key: "__ratings",
            label: "Ratings",
            cell: (_rec: PriorityRecommendation, row: SlimRow | null) => ({
              node: row ? (
                <Ratings row={row} measured={data.measured[row.id] ?? []} />
              ) : (
                "—"
              ),
            }),
          } satisfies MatrixRow,
        ]
      : []),
  ];
}

function PickHead({
  rec,
  row,
  data,
  selected,
  primary,
  onSelect,
}: {
  rec: PriorityRecommendation;
  row: SlimRow | null;
  data: PicksData;
  selected: boolean;
  primary: boolean;
  onSelect: () => void;
}) {
  const meta = LABELS.get(rec.priority);
  return (
    <div
      data-priority={rec.priority}
      onClick={onSelect}
      className={
        "flex cursor-pointer flex-col gap-1 rounded-t-lg border-[1.5px] px-3 pb-2.5 pt-2 transition-colors " +
        (selected
          ? ACTIVE_HEAD
          : "border-transparent hover:bg-brand-slate-50 dark:hover:bg-brand-slate-800/60")
      }
    >
      <button
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        className="flex flex-col gap-0.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-brand-accent rounded"
      >
        <span className="flex items-start justify-between gap-1.5">
          <span className="text-xs font-semibold uppercase tracking-wide text-brand-accent">
            {meta?.label ?? rec.priority}
          </span>
          {primary ? (
            <span className="shrink-0 rounded-full bg-brand-accent/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-accent">
              Default
            </span>
          ) : null}
        </span>
        <span className="text-[11px] leading-tight text-brand-slate-500 dark:text-brand-slate-400">
          {SHORT_HINT[rec.priority] ?? meta?.hint}
        </span>
        <span className="mt-0.5 text-lg font-bold leading-tight text-brand-slate-900 dark:text-brand-slate-50">
          {rec.model}
        </span>
        <span className="text-[11px] font-medium leading-snug text-brand-accent">
          {rec.platform}
        </span>
      </button>
      <PickFacts row={row} data={data} />
    </div>
  );
}

export function PicksMatrix({
  recommendations,
  data,
  selected,
  primary,
  onSelect,
}: {
  recommendations: PriorityRecommendation[];
  data: PicksData;
  selected: BudgetPriority;
  primary: BudgetPriority;
  onSelect: (priority: BudgetPriority) => void;
}) {
  const rows = matrixRows(recommendations, data);
  const pickRows = new Map(
    recommendations.map((r) => [r.priority, rowForPick(data, r.model)]),
  );
  const n = recommendations.length;
  const cellBase =
    "flex flex-wrap items-center gap-x-1.5 px-3 py-1.5 text-sm border-t border-brand-slate-100 dark:border-brand-slate-800";
  const rowLabel =
    "flex items-center py-1.5 text-xs font-medium text-brand-slate-500 dark:text-brand-slate-400 border-t border-brand-slate-100 dark:border-brand-slate-800";
  const selectedRec =
    recommendations.find((r) => r.priority === selected) ?? recommendations[0];
  const narrow = useNarrow();

  if (!narrow) {
    return (
      <div
        className="grid"
        style={{
          gridTemplateColumns: `minmax(84px, 108px) repeat(${n}, minmax(0, 1fr))`,
        }}
        data-testid="picks-matrix"
      >
        <div aria-hidden />
        {recommendations.map((rec) => (
          <PickHead
            key={rec.priority}
            rec={rec}
            row={pickRows.get(rec.priority) ?? null}
            data={data}
            selected={rec.priority === selected}
            primary={rec.priority === primary}
            onSelect={() => onSelect(rec.priority)}
          />
        ))}
        {rows.map((row, i) => {
          const last = i === rows.length - 1;
          return (
            <Fragment key={row.key}>
              <div className={rowLabel}>{row.label}</div>
              {recommendations.map((rec) => {
                const { node, funded } = row.cell(
                  rec,
                  pickRows.get(rec.priority) ?? null,
                );
                const active =
                  rec.priority === selected
                    ? ` ${ACTIVE_TINT} ${last ? ACTIVE_CELL_LAST : ACTIVE_CELL_SIDES}`
                    : "";
                const color = funded
                  ? "font-semibold text-green-600 dark:text-green-400"
                  : "text-brand-slate-700 dark:text-brand-slate-200";
                return (
                  <div
                    key={rec.priority}
                    className={`${cellBase} ${color}${active}`}
                    data-pick={rec.priority}
                    data-row={row.key}
                  >
                    {node}
                  </div>
                );
              })}
            </Fragment>
          );
        })}
      </div>
    );
  }

  return (
    <div data-testid="picks-segmented">
      <div
        role="tablist"
        aria-label="Picks"
        className="grid grid-cols-3 gap-1 rounded-lg bg-brand-slate-100 p-1 dark:bg-brand-slate-900"
      >
        {recommendations.map((rec) => (
          <button
            key={rec.priority}
            type="button"
            role="tab"
            aria-selected={rec.priority === selected}
            onClick={() => onSelect(rec.priority)}
            className={
              "rounded-md px-2 py-1.5 text-xs font-semibold uppercase tracking-wide " +
              (rec.priority === selected
                ? "bg-white text-brand-accent shadow-sm dark:bg-brand-slate-700"
                : "text-brand-slate-500 dark:text-brand-slate-400")
            }
          >
            {LABELS.get(rec.priority)?.label ?? rec.priority}
          </button>
        ))}
      </div>
      {selectedRec && (
        <div className="mt-3">
          <p className="text-[11px] text-brand-slate-500 dark:text-brand-slate-400">
            {SHORT_HINT[selectedRec.priority]}
            {selectedRec.priority === primary ? " · your default" : ""}
          </p>
          <p className="text-xl font-bold text-brand-slate-900 dark:text-brand-slate-50">
            {selectedRec.model}
          </p>
          <p className="text-xs font-medium text-brand-accent">
            {selectedRec.platform}
          </p>
          <div className="mt-1.5">
            <PickFacts
              row={pickRows.get(selectedRec.priority) ?? null}
              data={data}
            />
          </div>
          <dl className="mt-3 divide-y divide-brand-slate-100 dark:divide-brand-slate-800">
            {rows.map((row) => {
              const { node, funded } = row.cell(
                selectedRec,
                pickRows.get(selectedRec.priority) ?? null,
              );
              return (
                <div
                  key={row.key}
                  className="flex items-center justify-between gap-3 py-2"
                  data-pick={selectedRec.priority}
                  data-row={row.key}
                >
                  <dt className="text-xs font-medium text-brand-slate-500 dark:text-brand-slate-400">
                    {row.label}
                  </dt>
                  <dd
                    className={
                      "flex flex-wrap items-center justify-end gap-x-1.5 text-right text-sm " +
                      (funded
                        ? "font-semibold text-green-600 dark:text-green-400"
                        : "text-brand-slate-700 dark:text-brand-slate-200")
                    }
                  >
                    {node}
                  </dd>
                </div>
              );
            })}
          </dl>
        </div>
      )}
    </div>
  );
}
