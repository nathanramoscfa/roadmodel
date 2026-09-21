// web/lib/benchmark-grid.ts
//
// The UNIFORM benchmark layer for /models: column definitions over the
// Artificial Analysis dataset in data/benchmarks.json (built by
// update/fetch_aa_benchmarks.py). One lab, one methodology, one scale per
// column — so every number in a column is comparable with every other, and a
// blank means "AA has not measured this model on this test", never "we did
// not look". This is what replaced the per-row prose mining in
// lib/benchmark-scores.ts, which could only show whatever each row's cron
// text happened to cite, on whatever scale the citation used.
//
// PURE DATA — no JSON import here, so the client table can import it. The
// server page reads data/benchmarks.json, projects each model to a BenchRow
// with exactly the GRID_COLUMNS keys, and passes it down as props.

import type { Category } from "@/lib/catalog-fields";

// Keys as the AA Insights API names them (evaluations.<key>), plus the two
// performance fields promoted to columns.
export type BenchKey =
  | "artificial_analysis_intelligence_index"
  | "artificial_analysis_coding_index"
  | "hle"
  | "gpqa"
  | "scicode"
  | "terminalbench_v2_1"
  | "tau_banking"
  | "ifbench"
  | "lcr"
  | "median_output_tokens_per_second";

export type BenchUnit = "index" | "fraction" | "tok/s";

export interface BenchColumn {
  key: BenchKey;
  // Column header (short) and the full benchmark name for the tooltip.
  short: string;
  label: string;
  definition: string;
  unit: BenchUnit;
  // Source leaderboard / methodology page for the tooltip link.
  url: string;
  // The rating category this figure is evidence for, if any. The ratings view
  // shows this column's value under that category's letter.
  category?: Category;
}

export const AA_HOME = "https://artificialanalysis.ai/";

// Display order for the "Benchmark scores" grid. Composites first, then the
// individual evaluations grouped roughly by what they measure, speed last.
export const GRID_COLUMNS: BenchColumn[] = [
  {
    key: "artificial_analysis_intelligence_index",
    short: "AA Index",
    label: "Artificial Analysis Intelligence Index",
    definition:
      "AA's composite over ten evaluations (v4.3: HLE, GPQA Diamond, SciCode, Terminal-Bench, τ²-bench, AA-LCR, IFBench, AA-Omniscience, …). The one published overall number; 0–100.",
    unit: "index",
    url: "https://artificialanalysis.ai/evaluations/artificial-analysis-intelligence-index",
  },
  {
    key: "artificial_analysis_coding_index",
    short: "Coding Idx",
    label: "Artificial Analysis Coding Index",
    definition:
      "AA's composite of its coding evaluations (Terminal-Bench Hard and SciCode); 0–100. The uniform coding figure — every model here was run by the same lab under the same harness.",
    unit: "index",
    url: "https://artificialanalysis.ai/evaluations/artificial-analysis-coding-index",
    category: "coding",
  },
  {
    key: "hle",
    short: "HLE",
    label: "Humanity's Last Exam",
    definition:
      "Frontier-difficulty exam across academic disciplines; percent correct as measured by AA. The hardest general-knowledge test in wide use.",
    unit: "fraction",
    url: "https://agi.safe.ai/",
    category: "knowledge",
  },
  {
    key: "gpqa",
    short: "GPQA",
    label: "GPQA Diamond",
    definition:
      "Graduate-level science questions written to be Google-proof; percent correct as measured by AA.",
    unit: "fraction",
    url: "https://github.com/idavidrein/gpqa",
  },
  {
    key: "scicode",
    short: "SciCode",
    label: "SciCode",
    definition:
      "Coding problems drawn from real scientific research workflows; percent of sub-problems solved, as measured by AA.",
    unit: "fraction",
    url: "https://scicode-bench.github.io/",
  },
  {
    key: "terminalbench_v2_1",
    short: "TB 2.1",
    label: "Terminal-Bench 2.1",
    definition:
      "Autonomous multi-step tasks in a real terminal — the agentic benchmark; percent of tasks completed, as run by AA.",
    unit: "fraction",
    url: "https://www.tbench.ai/",
    category: "agentic",
  },
  {
    key: "tau_banking",
    short: "τ² Bank",
    label: "τ²-bench (banking)",
    definition:
      "Tool-use with a simulated customer in the banking domain; pass^1 rate, as run by AA. A conversation-plus-tools agentic test, complementing Terminal-Bench's solo terminal tasks.",
    unit: "fraction",
    url: "https://github.com/sierra-research/tau2-bench",
  },
  {
    key: "ifbench",
    short: "IFBench",
    label: "IFBench",
    definition:
      "Precise instruction-following under unusual, verifiable constraints; percent of constraints satisfied, as measured by AA.",
    unit: "fraction",
    url: "https://github.com/allenai/IFBench",
  },
  {
    key: "lcr",
    short: "AA-LCR",
    label: "AA Long Context Reasoning",
    definition:
      "Reasoning over ~100k-token documents (multi-document question answering); percent correct, as measured by AA. The uniform long-context figure.",
    unit: "fraction",
    url: "https://artificialanalysis.ai/evaluations/artificial-analysis-long-context-reasoning",
    category: "long-context",
  },
  {
    key: "median_output_tokens_per_second",
    short: "Speed",
    label: "Output speed (tokens/s)",
    definition:
      "Median output tokens per second on the provider's first-party API, as measured by AA. Blank where AA has not benchmarked the endpoint's throughput.",
    unit: "tok/s",
    url: "https://artificialanalysis.ai/",
    category: "speed",
  },
];

export const GRID_COLUMN_BY_KEY: Record<BenchKey, BenchColumn> = Object.fromEntries(
  GRID_COLUMNS.map((c) => [c.key, c]),
) as Record<BenchKey, BenchColumn>;

// Category → the uniform column that is evidence for that category's letter
// (named in the category header's tooltip). Planning and multimodal have no
// single-lab public benchmark in this dataset.
export const CATEGORY_FIGURE: Partial<Record<Category, BenchKey>> = Object.fromEntries(
  GRID_COLUMNS.filter((c) => c.category).map((c) => [c.category, c.key]),
);

// The four categories whose letter is DERIVED from its evidence column by
// update/derive_ratings.py (gap to the category leader, in points:
// S ≤ 5, A ≤ 20, B ≤ 35, C ≤ 50, else D) for every model AA measures.
// Speed has an evidence column for display but stays editorial: AA's tokens/s
// is measured on the provider's first-party endpoint at max effort.
export const DERIVED_CATEGORIES: ReadonlySet<Category> = new Set<Category>([
  "coding",
  "agentic",
  "long-context",
  "knowledge",
]);
export const DERIVATION_BANDS: readonly { max: number; letter: string }[] = [
  { max: 5, letter: "S" },
  { max: 20, letter: "A" },
  { max: 35, letter: "B" },
  { max: 50, letter: "C" },
];

// Points on the derivation scale: indices as-is, fractions ×100.
export function benchPoints(value: number, unit: BenchUnit): number {
  return unit === "fraction" ? value * 100 : value;
}

// Within-column quintile band for a measured value: 5 = top 20% of measured
// models on that column … 1 = bottom 20%. Every grid column is higher-is-
// better on one scale, so the band is comparable across columns even though
// the units are not — that is what the cell colors encode. Ranks among
// MEASURED values only; a "—" has no band.
export type Band = 1 | 2 | 3 | 4 | 5;

export function bandFor(value: number | null, sortedMeasured: number[]): Band | null {
  if (value === null || sortedMeasured.length === 0) return null;
  // Share of measured values strictly below this one → quintile.
  let below = 0;
  while (below < sortedMeasured.length && sortedMeasured[below] < value) below += 1;
  const pct = below / sortedMeasured.length;
  return (Math.min(4, Math.floor(pct * 5)) + 1) as Band;
}

// Cost/quality Pareto frontier: a model is on it when NO other model is both
// cheaper (output price) and higher on the AA Intelligence Index. Zero
// tunable weights — the standard answer to "what is the best value" that a
// quality ÷ price ratio gets wrong (a ratio is dominated by the two-orders-of-
// magnitude price range and crowns the cheapest weak model). Ties on price
// resolve to the higher index; ties on index to the cheaper price.
export function paretoFrontier<T extends { price: number; index: number | null }>(
  rows: readonly T[],
): Set<T> {
  const measured = rows.filter((r): r is T & { index: number } => r.index !== null);
  const sorted = [...measured].sort((a, b) => a.price - b.price || b.index - a.index);
  const frontier = new Set<T>();
  let best = Number.NEGATIVE_INFINITY;
  for (const r of sorted) {
    if (r.index > best) {
      frontier.add(r);
      best = r.index;
    }
  }
  return frontier;
}

// What the page carries per model: just the column values (null = not
// measured) plus the AA identity for the tooltip/attribution.
export interface BenchRow {
  aa_slug: string;
  aa_name: string;
  values: Record<BenchKey, number | null>;
}

export function formatBench(value: number | null, unit: BenchUnit): string {
  if (value === null || Number.isNaN(value)) return "—";
  switch (unit) {
    case "fraction":
      return `${(value * 100).toFixed(1)}%`;
    case "tok/s":
      return `${Math.round(value)}`;
    default:
      return value.toFixed(1);
  }
}

// Numeric value for sorting; missing sorts last in either direction.
export function benchSortValue(row: BenchRow | null, key: BenchKey): number | null {
  const v = row?.values[key];
  return v === undefined ? null : v;
}
