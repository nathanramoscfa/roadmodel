// web/lib/catalog-fields.ts
//
// Presentation metadata for the /models reference page: the model row type, the
// per-column field definitions (full name + plain-English meaning + source) that
// drive the header tooltips and the "How to read this" legend, the per-category
// and cost-tier and jurisdiction definitions, the S→D rating colors, and the
// provider → documentation map that makes each model name a link.
//
// PURE DATA — this module must NOT import data/catalog.json, so it is safe to
// import from the client `ModelCatalog` component. The server page reads the
// catalog, maps it to ModelRow[], and passes the rows down as props.

import type { BenchRow } from "@/lib/benchmark-grid";

export type Category =
  | "coding"
  | "planning"
  | "agentic"
  | "multimodal"
  | "long-context"
  | "knowledge"
  | "speed";

export type Rating = "S" | "A" | "B" | "C" | "D";
export type CostTier = "low" | "medium" | "high" | "very-high";

export interface ModelRow {
  id: string;
  name: string;
  // Provider display label ("Anthropic", "OpenAI", …) inferred from the id, or
  // null when no provider matches — the Provider column and filter read this.
  provider: string | null;
  input_price_per_1m: number;
  output_price_per_1m: number;
  cache_read_per_1m: number | null;
  tier_cost: CostTier;
  tiers: Record<Category, Rating>;
  jurisdiction: string;
  headline_benchmarks: string;
  pricing_notes: string;
  best_for: string;
  // Artificial Analysis Intelligence Index, or null when AA has not measured it.
  // Read from the structured benchmark layer when the model is mapped there,
  // else from the catalog prose (the cron's citation) as a fallback.
  aa_index: number | null;
  // The uniform Artificial Analysis figures (lib/benchmark-grid.ts), or null
  // when AA has not measured the model at all.
  bench: BenchRow | null;
  // Cost-adjusted value: AA Index minus the index the market-fitted
  // index-vs-log(blended price) line predicts for this model's price, in index
  // points (null when AA has not measured it). See fitValueLine().
  value_score: number | null;
  // On the cost/quality Pareto frontier: no catalog model is both cheaper
  // (output price) and higher on the AA Index. See paretoFrontier().
  value_frontier: boolean;
}

export interface FieldDef {
  // Short visible column label.
  label: string;
  // Even shorter form for a narrow, centered table header (defaults to label).
  short?: string;
  // Full name spelled out for the tooltip heading.
  fullName: string;
  // Plain-English definition.
  definition: string;
  // Optional canonical source the tooltip links to.
  url?: string;
}

// The seven quality categories, in display order. Each is rated S→D per model.
export const CATEGORY_ORDER: Category[] = [
  "coding",
  "planning",
  "agentic",
  "multimodal",
  "long-context",
  "knowledge",
  "speed",
];

export const CATEGORY_DEFS: Record<Category, FieldDef> = {
  coding: {
    label: "Coding",
    fullName: "Coding",
    definition: "Writing, refactoring, and debugging code across languages.",
    url: "/docs#ratings",
  },
  planning: {
    label: "Planning",
    fullName: "Planning",
    definition: "Decomposing a goal into an ordered, well-scoped plan.",
    url: "/docs#ratings",
  },
  agentic: {
    label: "Agentic",
    fullName: "Agentic",
    definition: "Multi-step autonomous tool use and long task execution.",
    url: "/docs#ratings",
  },
  multimodal: {
    label: "Multimodal",
    short: "Multi-modal",
    fullName: "Multimodal",
    definition: "Understanding non-text input such as images and diagrams.",
    url: "/docs#ratings",
  },
  "long-context": {
    label: "Long-context",
    short: "Long ctx",
    fullName: "Long-context",
    definition: "Working accurately over very large inputs (long files, big repos).",
    url: "/docs#ratings",
  },
  knowledge: {
    label: "Knowledge",
    fullName: "Knowledge",
    definition: "Breadth and accuracy of world knowledge and reasoning.",
    url: "/docs#ratings",
  },
  speed: {
    label: "Speed",
    fullName: "Speed",
    definition: "Output throughput and latency (tokens per second).",
    url: "/docs#ratings",
  },
};

// Non-category columns.
export type FieldKey =
  | "name"
  | "provider"
  | "jurisdiction"
  | "input_price_per_1m"
  | "output_price_per_1m"
  | "cache_read_per_1m"
  | "tier_cost"
  | "aa_index"
  | "value"
  | "benchmarks";

export const FIELD_DEFS: Record<FieldKey, FieldDef> = {
  name: {
    label: "Model",
    fullName: "Model",
    definition:
      "The model name as the provider brands it, without the family prefix (Opus 4.8, not Claude Opus 4.8). Links to the provider's documentation; expand the row for what it is best for, full pricing, and the benchmarks cited.",
  },
  provider: {
    label: "Provider",
    fullName: "Provider",
    definition:
      "The company that trains and serves the model (Anthropic, OpenAI, Google, …). Open-weight models list the host that serves them here (gpt-oss → Groq).",
  },
  jurisdiction: {
    label: "Juris.",
    fullName: "Jurisdiction",
    definition:
      "The operator's HQ jurisdiction — whose terms govern the data path when a call is placed. The recommender can filter models outside your allowed regions.",
    url: "/docs",
  },
  input_price_per_1m: {
    label: "Input",
    fullName: "Input price (USD per 1M tokens)",
    definition:
      "Cost to send 1M tokens of input (your prompt + context) to the model. Sourced from each provider's own pricing page (federated) or Cursor's pool.",
  },
  output_price_per_1m: {
    label: "Output",
    fullName: "Output price (USD per 1M tokens)",
    definition:
      "Cost of 1M generated tokens — the dominant cost driver for code, plans, and long answers. The dot beside it is the cost tier: Low < $10, Medium $10–14.99, High $15–24.99, Very High ≥ $25.",
  },
  cache_read_per_1m: {
    label: "Cache",
    fullName: "Cache-read price (USD per 1M tokens)",
    definition:
      "Cost of reading 1M cached input tokens — relevant for sustained sessions reusing a system prompt or persistent context. '—' means not published.",
  },
  tier_cost: {
    label: "Cost tier",
    fullName: "Cost tier",
    definition:
      "Bucket by output price: Low < $10, Medium $10–14.99, High $15–24.99, Very High ≥ $25 per 1M tokens.",
    url: "/docs",
  },
  aa_index: {
    label: "AA Index",
    fullName: "Artificial Analysis Intelligence Index",
    definition:
      "The one published composite number: Artificial Analysis's index over ten evaluations (v4.3: Humanity's Last Exam, GPQA Diamond, SciCode, Terminal-Bench, τ²-bench, AA-LCR, IFBench, AA-Omniscience, …), independently measured on a 0–100 scale. The closest thing to a single numeric rating — use it to separate models that share a letter. '—' means AA has not measured the model.",
    url: "https://artificialanalysis.ai/",
  },
  value: {
    label: "Value",
    fullName: "Value (cost-adjusted intelligence)",
    definition:
      "AA Intelligence Index minus the index a model's price predicts, in index points. The prediction is a least-squares line of index against log10(blended price — 3 input : 1 output tokens) fitted over every AA-measured model, so the cost weight is estimated from the market rather than chosen. +10 means ten more index points than models at that price typically deliver; negative means less. The fit's n, R² and residual σ are shown in the header — treat two models within about σ of each other as a tie. A dot marks the cost/quality frontier: no catalog model is both cheaper and higher on the index.",
    url: "https://artificialanalysis.ai/",
  },
  benchmarks: {
    label: "Benchmarks cited",
    fullName: "Benchmarks cited by the catalog",
    definition:
      "The public-leaderboard figures the daily curation cited when it set this row's ratings — mixed sources and versions, so compare them only like with like. The Benchmark scores grid is the uniform, single-source alternative.",
    url: "/docs#benchmarks",
  },
};

export const COST_TIER_DEFS: Record<CostTier, { label: string; definition: string }> = {
  low: { label: "Low", definition: "Output price < $10 per 1M tokens." },
  medium: { label: "Medium", definition: "Output price $10–$14.99 per 1M tokens." },
  high: { label: "High", definition: "Output price $15–$24.99 per 1M tokens." },
  "very-high": { label: "Very High", definition: "Output price ≥ $25 per 1M tokens." },
};

export const JURISDICTION_DEFS: Record<string, string> = {
  us: "United States — Anthropic, OpenAI, Google, xAI, Meta, Cursor, Groq.",
  eu: "European Union — Mistral (data-sovereignty / EU-regulatory workloads).",
  cn: "China — DeepSeek, z.ai (Zhipu), Moonshot. Excluded by default unless opted in.",
  uk: "United Kingdom.",
  ca: "Canada.",
  au: "Australia.",
  jp: "Japan.",
  kr: "South Korea.",
  ru: "Russia.",
  unknown: "Provider HQ not yet editorially verified.",
};

export function jurisdictionDef(code: string): string {
  return JURISDICTION_DEFS[code] ?? `Jurisdiction code: ${code}.`;
}

// Rating rank (for sorting; higher = better) and badge colors (good → poor).
export const RATING_RANK: Record<Rating, number> = { S: 5, A: 4, B: 3, C: 2, D: 1 };

export const RATING_COLORS: Record<Rating, string> = {
  S: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/35 dark:text-emerald-300",
  A: "bg-sky-100 text-sky-800 dark:bg-sky-500/35 dark:text-sky-300",
  B: "bg-brand-slate-100 text-brand-slate-700 dark:bg-brand-slate-700 dark:text-brand-slate-200",
  C: "bg-amber-100 text-amber-800 dark:bg-amber-500/35 dark:text-amber-300",
  D: "bg-rose-100 text-rose-700 dark:bg-rose-500/35 dark:text-rose-300",
};

export const COST_TIER_RANK: Record<CostTier, number> = {
  low: 1,
  medium: 2,
  high: 3,
  "very-high": 4,
};

// Solid swatch for the tier dot beside the output price.
export const COST_TIER_DOT: Record<CostTier, string> = {
  low: "bg-emerald-500",
  medium: "bg-amber-500",
  high: "bg-orange-500",
  "very-high": "bg-rose-500",
};

export const COST_TIER_COLORS: Record<CostTier, string> = {
  low: "bg-brand-slate-100 text-brand-slate-700 dark:bg-brand-slate-700 dark:text-brand-slate-200",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-500/35 dark:text-amber-300",
  high: "bg-orange-100 text-orange-800 dark:bg-orange-500/35 dark:text-orange-300",
  "very-high": "bg-rose-100 text-rose-700 dark:bg-rose-500/35 dark:text-rose-300",
};

// Provider → documentation. modelProvider() infers the provider from the model id
// so the model name can link to the right docs (per-model deep links mostly do not
// exist; the provider's model page is the canonical target).
export interface ProviderInfo {
  key: string;
  label: string;
  docUrl: string;
}

const PROVIDERS: Record<string, ProviderInfo> = {
  anthropic: {
    key: "anthropic",
    label: "Anthropic",
    docUrl: "https://docs.claude.com/en/docs/about-claude/models/overview",
  },
  openai: { key: "openai", label: "OpenAI", docUrl: "https://platform.openai.com/docs/models" },
  google: { key: "google", label: "Google", docUrl: "https://ai.google.dev/gemini-api/docs/models" },
  xai: { key: "xai", label: "xAI", docUrl: "https://docs.x.ai/docs/models" },
  deepseek: { key: "deepseek", label: "DeepSeek", docUrl: "https://api-docs.deepseek.com/" },
  mistral: {
    key: "mistral",
    label: "Mistral",
    docUrl: "https://docs.mistral.ai/getting-started/models/models_overview/",
  },
  zai: { key: "zai", label: "z.ai (Zhipu)", docUrl: "https://docs.z.ai/guides/overview/pricing" },
  groq: { key: "groq", label: "Groq", docUrl: "https://console.groq.com/docs/models" },
  cursor: { key: "cursor", label: "Cursor", docUrl: "https://cursor.com/docs/models" },
  moonshot: { key: "moonshot", label: "Moonshot", docUrl: "https://platform.moonshot.ai/docs" },
  meta: { key: "meta", label: "Meta", docUrl: "https://ai.meta.com/" },
};

// Order matters: gpt-oss must be tested before "gpt".
export function modelProvider(id: string): ProviderInfo | null {
  const s = id.toLowerCase();
  if (s.includes("gpt-oss")) return PROVIDERS.groq;
  if (/claude|opus|sonnet|haiku|fable/.test(s)) return PROVIDERS.anthropic;
  if (s.includes("gpt")) return PROVIDERS.openai;
  if (s.includes("gemini")) return PROVIDERS.google;
  if (s.includes("grok")) return PROVIDERS.xai;
  if (s.includes("deepseek")) return PROVIDERS.deepseek;
  if (s.includes("mistral") || s.includes("codestral")) return PROVIDERS.mistral;
  if (s.includes("glm")) return PROVIDERS.zai;
  if (s.includes("composer")) return PROVIDERS.cursor;
  if (s.includes("kimi")) return PROVIDERS.moonshot;
  if (s.includes("muse")) return PROVIDERS.meta;
  return null;
}

export function formatPrice(value: number | null): string {
  if (value === null || value === undefined) return "—";
  // Trim trailing zeros but keep cents readable: 0.075, 0.6, 2.2, 50.
  return `$${Number(value.toFixed(4)).toString()}`;
}
