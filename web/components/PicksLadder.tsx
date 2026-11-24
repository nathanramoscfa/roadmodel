// web/components/PicksLadder.tsx
//
// The answer, as a roadmap's Settings lay it out: Cost, Balanced and Quality
// side by side, each ranked three deep. The Pick leads its card with the
// platform to run it on and the level to set, then its figures at that level
// in the /models vocabulary (AA Intelligence Index, price, Score; hover any
// of them for how it is read), what it costs this viewer and its seven S→D
// letters. Under it sit the Runner-up and the Backup, each from another
// maker, with the same platform, level, AA Index and price, so a full pool or
// an outage has somewhere to go.
//
// The three cards share their rows (CSS subgrid), so a figure is read across
// the tiers on one line. Selecting a card shows that pick's reasoning and
// cost below and marks it on the chart. Below the md breakpoint the cards
// become tabs over one card at a time.
"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { blendedPrice, formatScore, formatUsd } from "@/lib/benchmark-grid";
import {
  CATEGORY_DEFS,
  CATEGORY_ORDER,
  COST_TIER_DEFS,
  ESTIMATED_BADGE,
  RATING_COLORS,
  RATING_OUTLINE_COLORS,
  type Category,
} from "@/lib/catalog-fields";
import {
  PRIORITY_LABEL,
  RANK_LABEL,
  type ColumnView,
  type LadderView,
  type OptionView,
  type Rank,
} from "@/lib/ladder-view";
import { rankedFor } from "@/lib/ladder-task";
import { effortLabel, effortWord } from "@/lib/pick-effort";
import type { BudgetPriority } from "@/lib/profile";
import type { PicksData } from "@/lib/recommend-picks";
import { FRONTIER } from "./chart-kit";
import { HoverCard } from "./FloatingCard";
import { FrontierPointCard, indexText, ScoreBreakdownCard, scoreToneClass } from "./ScoreCards";

const MUTED = "text-brand-slate-500 dark:text-brand-slate-400";
const FAINT = "text-brand-slate-400 dark:text-brand-slate-500";
const STRONG = "text-brand-slate-900 dark:text-brand-slate-50";
const RULE = "border-brand-slate-200 dark:border-brand-slate-700/80";
const CAPTION = "text-[10px] font-semibold uppercase tracking-wide " + MUTED;

const CATEGORY_INITIAL: Record<Category, string> = {
  coding: "C",
  planning: "P",
  agentic: "A",
  multimodal: "M",
  "long-context": "L",
  knowledge: "K",
  speed: "S",
};

// The card's rows, by how many of the two lower ranks the answer carries:
// Tailwind needs each span spelled out.
const ROW_SPAN: Record<number, string> = {
  5: "md:row-span-5",
  6: "md:row-span-6",
  7: "md:row-span-7",
};

// Below Tailwind's md breakpoint the cards become tabs. Only the active
// layout is rendered (a CSS-hidden twin would repeat every label to screen
// readers); a result renders after a request, so there is no server-rendered
// layout to mismatch.
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

// An option's AA Index as the catalog's own cards print it, so a cell and the
// card it opens never disagree: AA's figure to one decimal, an estimate ≈.
export function aaText(o: OptionView): string {
  if (o.aa === null) return "—";
  if (o.row) return indexText({ ...o.row, aa_index: o.aa });
  return `${o.aaEstimated ? "≈" : ""}${o.aa.toFixed(1)}`;
}

export function priceText(o: OptionView): string {
  return o.price === null ? "—" : `${o.priceEstimated ? "≈" : ""}$${o.price.toFixed(2)}`;
}

// "Claude Code · Extra high": where an option runs and at what level.
export function whereText(o: OptionView): string {
  return [o.platform, o.level].filter(Boolean).join(" · ");
}

// How an option's price is read: the list price with its output part scaled
// by the tokens the model writes at the level.
function PriceCard({ option: o }: { option: OptionView }) {
  const row = o.row;
  if (!row || o.price === null) return null;
  const list = blendedPrice(row.input_price_per_1m, row.output_price_per_1m);
  const share = o.tokenShare;
  return (
    <div className="w-[21rem] max-w-full" data-testid="price-card">
      <div className="flex items-baseline justify-between gap-4">
        <p className={"text-sm font-semibold " + STRONG}>{row.name}</p>
        <span className={"shrink-0 text-xs " + MUTED}>{COST_TIER_DEFS[row.tier_cost].label} cost</span>
      </div>
      <div className="mt-2 flex items-baseline justify-between gap-6">
        <span>{o.level && o.effort ? `Price at ${o.level}` : "Blended price"}</span>
        <span className={"whitespace-nowrap font-semibold tabular-nums " + STRONG}>
          {priceText(o)} per 1M tokens
        </span>
      </div>
      <p className={"text-right text-xs tabular-nums " + MUTED}>
        (3 × {formatUsd(row.input_price_per_1m)} input + {formatUsd(row.output_price_per_1m)} output
        {share !== null && <> × {share.toFixed(2)}</>}) ÷ 4
      </p>
      <p className="mt-2 text-xs leading-[1.125rem]">
        {share !== null && o.level ? (
          <>
            A model is billed per token, and an effort changes how many it writes: at {o.level} this
            one writes {share.toFixed(2)}× the tokens a typical model writes at High. Its output is
            priced at that and its input as listed, three input tokens to one output.
          </>
        ) : (
          <>The list price per 1M tokens, three input tokens to one output.</>
        )}
      </p>
      <div className={"mt-2 flex items-baseline justify-between gap-6 border-t pt-2 text-xs " + RULE}>
        <span>List price</span>
        <span className={"whitespace-nowrap tabular-nums " + STRONG}>${list.toFixed(2)} per 1M tokens</span>
      </div>
      {o.priceEstimated && (
        <p className={"mt-1.5 text-xs leading-[1.125rem] " + MUTED}>
          ≈ The tokens it writes at this level are derived from the levels roadmodel measured it at.
        </p>
      )}
    </div>
  );
}

// The Pick's figures and a lower rank's are told apart in tests.
function testId(o: OptionView, figure: string): string {
  return `${o.rank === "pick" ? "pick" : "rank"}-${figure}`;
}

function AaFigure({ option: o, className = "" }: { option: OptionView; className?: string }) {
  const text = aaText(o);
  if (!o.row || o.aa === null || !o.inPool) {
    return (
      <span className={"tabular-nums " + className} data-testid={testId(o, "aa-index")}>
        {text}
      </span>
    );
  }
  return (
    <HoverCard
      label={`${o.row.name}: AA Intelligence Index ${text}`}
      card={<FrontierPointCard model={o.row} leader={o.leader} />}
      className={"tabular-nums " + className}
      triggerTestId={testId(o, "aa-index")}
    >
      {text}
    </HoverCard>
  );
}

function PriceFigure({ option: o, className = "" }: { option: OptionView; className?: string }) {
  const text = priceText(o);
  if (!o.row || o.price === null) {
    return (
      <span className={"tabular-nums " + className} data-testid={testId(o, "price")}>
        {text}
      </span>
    );
  }
  return (
    <HoverCard
      label={`${o.row.name}: ${text} per 1M tokens. Show how it is priced`}
      card={<PriceCard option={o} />}
      className={"tabular-nums " + className}
      triggerTestId={testId(o, "price")}
    >
      {text}
    </HoverCard>
  );
}

function ScoreFigure({ option: o, data }: { option: OptionView; data: PicksData }) {
  if (o.score === null || !o.row) return <span className={FAINT}>—</span>;
  const tone = data.fit ? scoreToneClass(o.score, data.fit.sigma) : STRONG;
  const text = formatScore(o.score);
  if (!data.fit || !o.inPool) {
    return (
      <span className={"tabular-nums " + tone} data-testid="pick-score">
        {text}
      </span>
    );
  }
  return (
    <HoverCard
      label={`${o.row.name}: Score ${text}. Show how it adds up`}
      card={
        <ScoreBreakdownCard
          model={o.row}
          fit={data.fit}
          snapshot={data.snapshot}
          leader={o.leader}
          effort={o.level && o.effort && o.tokenShare !== null ? { label: o.level, tokenShare: o.tokenShare } : null}
        />
      }
      className={"tabular-nums " + tone}
      triggerTestId="pick-score"
    >
      {text}
    </HoverCard>
  );
}

// Where the Pick stands among the models the frontier was drawn over: on it,
// the top model for its category, or under the point that holds the top
// score at its price.
function Standing({ column, data }: { column: ColumnView; data: PicksData }) {
  const o = column.pick;
  const row = o.row;
  if (!row) return <span className={"text-[11px] " + FAINT}>Not in the catalog</span>;
  const yours = data.pool !== null;
  if (column.specialist && !row.value_frontier) {
    return (
      <span
        className="inline-flex items-center gap-1.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-300"
        title={`Rated above every model on ${yours ? "your" : "the"} cost/quality frontier for ${column.specialist} work`}
        data-testid="pick-specialist"
      >
        <span className="inline-block h-2 w-2 rounded-full bg-current" />
        Top for {column.specialist} work
      </span>
    );
  }
  if (row.aa_index === null || !o.inPool) return null;
  if (row.value_frontier) {
    return (
      <span
        className="inline-flex items-center gap-1.5 text-[11px] font-medium"
        style={{ color: FRONTIER }}
        title={
          yours
            ? "On your cost/quality frontier: it scores higher on the AA Index than every other model you can use at its price or less"
            : "On the cost/quality frontier: it scores higher on the AA Index than every other model at its price or less"
        }
        data-testid="pick-frontier"
      >
        <span className="inline-block h-2.5 w-2.5 rounded-full border-2" style={{ borderColor: FRONTIER }} />
        {yours ? "On your frontier" : "On the frontier"}
      </span>
    );
  }
  if (!o.leader) return null;
  return (
    <HoverCard
      label={`${row.name}: the top score at its price is ${o.leader.name}`}
      card={<FrontierPointCard model={row} leader={o.leader} />}
      className={"self-start text-[11px] font-medium " + MUTED}
      triggerTestId="pick-beaten"
    >
      Top score at this price: {o.leader.name}
    </HoverCard>
  );
}

// The Pick's letters at the level it runs: a derived category Artificial
// Analysis measured there reads the letter that run earns
// (docs/effort-ratings.json); the rest, and a pick at its top level, read the
// model's headline letters. Filled is measured, dashed estimated.
function Ratings({ column }: { column: ColumnView }) {
  const o = column.pick;
  const row = o.row;
  if (!row) return <span className={FAINT}>—</span>;
  const atEffort = o.effort ? row.tiers_by_effort?.[o.effort] : undefined;
  return (
    <span className="inline-grid grid-cols-7 gap-1" data-testid="pick-ratings">
      {CATEGORY_ORDER.map((cat) => {
        const own = atEffort?.[cat];
        const r = own ?? row.tiers[cat];
        const isMeasured = own !== undefined || column.measured.includes(cat);
        const at = own !== undefined && o.effort ? ` at ${effortLabel(o.effort)}` : "";
        return (
          <span key={cat} className="flex flex-col items-center gap-0.5">
            <span className={"text-[9px] font-semibold uppercase leading-none " + FAINT}>{CATEGORY_INITIAL[cat]}</span>
            <span
              className={
                "inline-flex h-5 w-5 items-center justify-center rounded text-[11px] font-bold " +
                (isMeasured ? RATING_COLORS[r] : `${ESTIMATED_BADGE} ${RATING_OUTLINE_COLORS[r]}`)
              }
              title={`${CATEGORY_DEFS[cat].fullName}: ${r}${at}${isMeasured ? " (measured)" : " (estimated)"}`}
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

function Stat({ label, sub, children }: { label: string; sub: ReactNode; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className={CAPTION}>{label}</dt>
      <dd className={"mt-1 text-lg font-semibold leading-6 " + STRONG}>{children}</dd>
      <dd className={"mt-0.5 text-[11px] leading-4 " + MUTED}>{sub}</dd>
    </div>
  );
}

// A Runner-up or Backup: the model, where it runs and at what level, and its
// AA Index and price there. A rank the viewer's models cannot fill says so.
function LowerRank({ rank, option: o }: { rank: Rank; option: OptionView | null }) {
  return (
    <div className={"border-t px-4 py-3 " + RULE} data-rank={rank} data-testid={`rank-${rank}`}>
      <p className={CAPTION}>{RANK_LABEL[rank]}</p>
      {o ? (
        // On a phone the two figures sit on one line under the name: each is
        // a touch target a finger's height tall, and two stacked would double
        // the row.
        <div className="mt-1 flex flex-col gap-x-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <p className={"text-sm font-semibold leading-5 " + STRONG}>
              {o.model}
              {o.steppedDown && (
                <span
                  className={"ml-1 font-normal " + MUTED}
                  title="The Pick's own model one level lower: no other maker's model you can run fills this rank"
                  data-testid="rank-stepped-down"
                >
                  ↓
                </span>
              )}
            </p>
            <p className={"text-xs leading-5 " + MUTED} data-testid={`${rank}-detail`}>
              {whereText(o) || "—"}
              {o.ultracode && " · Ultracode"}
            </p>
          </div>
          {(o.aa !== null || o.price !== null) && (
            <dl className={"flex shrink-0 gap-x-4 text-xs leading-5 md:block md:text-right " + MUTED}>
              {o.aa !== null && (
                <div>
                  <dt className="inline">AA </dt>
                  <dd className={"inline font-medium " + STRONG}>
                    <AaFigure option={o} />
                  </dd>
                </div>
              )}
              {o.price !== null && (
                <div>
                  <dt className="sr-only">Price per 1M tokens</dt>
                  <dd className="inline">
                    <PriceFigure option={o} className={"font-medium " + STRONG} />
                    /1M
                  </dd>
                </div>
              )}
            </dl>
          )}
        </div>
      ) : (
        <p className={"mt-1 text-xs leading-5 " + FAINT}>No other maker&rsquo;s model in reach</p>
      )}
    </div>
  );
}

function PickCard({
  column,
  data,
  selected,
  isDefault,
  defaultLabel,
  onSelect,
  showCost,
  showRunnerUp,
  showBackup,
  subgrid,
}: {
  column: ColumnView;
  data: PicksData;
  selected: boolean;
  // The tier the answer leads with wears a badge saying why.
  isDefault: boolean;
  defaultLabel: string;
  onSelect: () => void;
  // The answer says what a pick costs this viewer (Quick pick's does not).
  showCost: boolean;
  showRunnerUp: boolean;
  showBackup: boolean;
  // Share the rows of the cards beside it (desktop); a lone card on a phone
  // lays its rows out itself.
  subgrid: boolean;
}) {
  const o = column.pick;
  const meta = PRIORITY_LABEL[column.priority];
  const rows = 5 + (showRunnerUp ? 1 : 0) + (showBackup ? 1 : 0);
  // The level the index was read at: the Pick's own where Artificial Analysis
  // measured it (or roadmodel estimated it) there, else the model's headline.
  const readAt = o.aa !== null ? (o.row?.aa_index_effort ?? null) : null;
  return (
    <article
      data-priority={column.priority}
      data-selected={selected ? "1" : "0"}
      onClick={onSelect}
      className={
        "cursor-pointer rounded-xl border bg-white transition-colors dark:bg-brand-slate-900 " +
        (subgrid ? `md:grid md:grid-rows-subgrid ${ROW_SPAN[rows]} ` : "") +
        (selected
          ? "border-brand-accent shadow-sm ring-1 ring-brand-accent/60"
          : "border-brand-slate-200 hover:border-brand-slate-300 dark:border-brand-slate-700 dark:hover:border-brand-slate-500")
      }
    >
      <header className="px-4 pt-3.5">
        <button
          type="button"
          aria-pressed={selected}
          onClick={(e) => {
            e.stopPropagation();
            onSelect();
          }}
          className="flex w-full items-start justify-between gap-2 rounded text-left outline-none focus-visible:ring-2 focus-visible:ring-brand-accent"
        >
          <span>
            <span className="block text-xs font-semibold uppercase tracking-wide text-brand-accent">{meta.label}</span>
            <span className={"block text-[11px] leading-4 " + MUTED}>{meta.hint}</span>
          </span>
          {isDefault && (
            <span
              className="shrink-0 rounded-full bg-brand-accent/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-accent"
              data-testid="pick-default-badge"
            >
              {defaultLabel}
            </span>
          )}
        </button>
      </header>

      <div className="flex flex-col gap-1 px-4 pt-3">
        <p className={CAPTION}>{RANK_LABEL.pick}</p>
        <h3 className={"text-xl font-bold leading-6 tracking-tight " + STRONG} data-testid="pick-model">
          {o.model}
        </h3>
        <Standing column={column} data={data} />
      </div>

      <dl className="px-4 pt-3 text-sm" data-testid="pick-settings">
        <div className={"flex items-baseline justify-between gap-3 border-t py-1.5 " + RULE}>
          <dt className={MUTED}>Platform</dt>
          <dd className={"text-right font-semibold " + STRONG} data-testid="pick-platform">
            {o.platform ?? "—"}
          </dd>
        </div>
        {o.level && (
          <div className={"flex items-baseline justify-between gap-3 border-t py-1.5 " + RULE}>
            <dt className={MUTED}>{o.dial}</dt>
            <dd className={"text-right font-semibold " + STRONG} data-testid="pick-level">
              {o.level}
            </dd>
          </div>
        )}
        {column.settings.map((s) => (
          <div key={s.key} className={"flex items-baseline justify-between gap-3 border-t py-1.5 " + RULE} data-setting={s.key}>
            <dt className={MUTED}>{s.label}</dt>
            {s.value === "—" ? (
              // Another pick sets this; this pick's model or platform has no
              // such setting.
              <dd className={"text-right " + FAINT} title={`No ${s.label} setting for this pick`}>
                —
              </dd>
            ) : (
              <dd className={"text-right font-semibold " + STRONG}>{s.value}</dd>
            )}
          </div>
        ))}
      </dl>

      <dl className={"mx-4 mt-1 grid grid-cols-3 gap-3 border-t pt-3 " + RULE}>
        <Stat
          label="AA Index"
          sub={
            readAt ? (
              <span data-testid="pick-aa-effort">at {effortWord(readAt)}</span>
            ) : o.aa === null ? (
              "not measured"
            ) : (
              "Intelligence Index"
            )
          }
        >
          <AaFigure option={o} />
        </Stat>
        <Stat label="Price" sub="per 1M tokens">
          <PriceFigure option={o} />
        </Stat>
        <Stat label="Score" sub="vs the price line">
          <ScoreFigure option={o} data={data} />
        </Stat>
      </dl>

      <div className="space-y-2.5 px-4 pb-4 pt-3">
        {showCost && (
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className={MUTED}>Your cost</span>
            {column.cost ? (
              <span
                className={
                  "text-right " +
                  (column.cost.funded ? "font-semibold text-green-600 dark:text-green-400" : "font-semibold " + STRONG)
                }
                data-testid="pick-cost"
              >
                {column.cost.amount}
                {column.cost.source && (
                  <span className={"ml-1.5 font-normal " + (column.cost.funded ? "" : MUTED)}>
                    {column.cost.funded ? `· ${column.cost.source}` : column.cost.source}
                  </span>
                )}
              </span>
            ) : (
              <span className={FAINT}>—</span>
            )}
          </div>
        )}
        <div className="flex items-end justify-between gap-3 text-sm">
          <span className={MUTED}>Ratings</span>
          <Ratings column={column} />
        </div>
      </div>

      {showRunnerUp && <LowerRank rank="runner_up" option={column.runnerUp} />}
      {showBackup && <LowerRank rank="backup" option={column.backup} />}
    </article>
  );
}

// The line under the cards, as a roadmap's ladder notes it: what the task
// was ranked as, how this answer's ranks were chosen and how the figures are
// read.
export function LadderNote({ view }: { view: LadderView }) {
  const lower = view.columns.flatMap((c) => [c.runnerUp, c.backup]).filter((o): o is OptionView => o !== null);
  const otherMakers = lower.some((o) => !o.steppedDown);
  const stepped = lower.some((o) => o.steppedDown);
  return (
    <p className={"text-xs leading-5 " + MUTED} data-testid="ladder-note">
      {view.task && <>Ranked for {rankedFor(view.task)}. </>}
      {!view.ranked ? (
        lower.length > 0 ? (
          <>Each Pick names a Backup from another maker. </>
        ) : null
      ) : otherMakers ? (
        <>
          Each column ranks makers apart: the Pick, a Runner-up with the Pick&rsquo;s maker left out, and a
          Backup with both left out.{" "}
        </>
      ) : null}
      {stepped && (
        <span data-testid="ladder-note-stepped">
          ↓ is the Pick&rsquo;s own model one level lower: no other maker&rsquo;s model you can run fills that rank
          {otherMakers ? "" : ", so a full usage pool or an outage has nowhere else to go"}.{" "}
          {!otherMakers && (
            <>
              <Link href="/settings" className="font-medium text-brand-accent hover:underline">
                Add another maker&rsquo;s plan or API key
              </Link>{" "}
              to rank one here.{" "}
            </>
          )}
        </span>
      )}
      AA Index and price are read at the level shown: the price is the list price per 1M tokens (3 input : 1
      output) with its output part scaled by the tokens the model writes at that level. ≈ marks an estimate.
    </p>
  );
}

export function PicksLadder({
  view,
  data,
  selected,
  primary,
  onSelect,
}: {
  view: LadderView;
  data: PicksData;
  selected: BudgetPriority;
  primary: BudgetPriority;
  onSelect: (priority: BudgetPriority) => void;
}) {
  const narrow = useNarrow();
  const showCost = view.columns.some((c) => c.cost !== null);
  const showRunnerUp = view.columns.some((c) => c.runnerUp !== null);
  const showBackup = view.ranked || view.columns.some((c) => c.backup !== null);
  const card = (column: ColumnView, subgrid: boolean) => (
    <PickCard
      key={column.priority}
      column={column}
      data={data}
      selected={column.priority === selected}
      isDefault={column.priority === primary}
      defaultLabel={view.primaryLabel}
      onSelect={() => onSelect(column.priority)}
      showCost={showCost}
      showRunnerUp={showRunnerUp}
      showBackup={showBackup}
      subgrid={subgrid}
    />
  );

  if (!narrow) {
    return (
      <div
        className="grid gap-x-3 gap-y-0"
        style={{ gridTemplateColumns: `repeat(${view.columns.length}, minmax(0, 1fr))` }}
        data-testid="picks-ladder"
      >
        {view.columns.map((column) => card(column, true))}
      </div>
    );
  }

  const active = view.columns.find((c) => c.priority === selected) ?? view.columns[0];
  return (
    <div data-testid="picks-segmented">
      <div
        role="tablist"
        aria-label="Picks"
        className="grid gap-1 rounded-lg bg-brand-slate-100 p-1 dark:bg-brand-slate-900"
        style={{ gridTemplateColumns: `repeat(${view.columns.length}, minmax(0, 1fr))` }}
      >
        {view.columns.map((column) => (
          <button
            key={column.priority}
            type="button"
            role="tab"
            aria-selected={column.priority === selected}
            onClick={() => onSelect(column.priority)}
            className={
              "rounded-md px-2 py-1.5 text-xs font-semibold uppercase tracking-wide " +
              (column.priority === selected
                ? "bg-white text-brand-accent shadow-sm dark:bg-brand-slate-700"
                : MUTED)
            }
          >
            {PRIORITY_LABEL[column.priority].label}
          </button>
        ))}
      </div>
      {active && <div className="mt-3">{card(active, false)}</div>}
    </div>
  );
}
