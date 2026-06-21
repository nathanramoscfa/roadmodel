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
  input_price_per_1m: number;
  output_price_per_1m: number;
  cache_read_per_1m: number | null;
  tier_cost: CostTier;
  tiers: Record<Category, Rating>;
  jurisdiction: string;
  headline_benchmarks: string;
  pricing_notes: string;
  best_for: string;
}

export interface FieldDef {
  // Short visible column label.
  label: string;
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
    fullName: "Multimodal",
    definition: "Understanding non-text input such as images and diagrams.",
    url: "/docs#ratings",
  },
  "long-context": {
    label: "Long-context",
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
  | "jurisdiction"
  | "input_price_per_1m"
  | "output_price_per_1m"
  | "cache_read_per_1m"
  | "tier_cost"
  | "benchmarks";

export const FIELD_DEFS: Record<FieldKey, FieldDef> = {
  name: {
    label: "Model",
    fullName: "Model",
    definition:
      "The model name. Links to the provider's documentation. Hover a row's chevron for what it is best for.",
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
      "Cost of 1M generated tokens — the dominant cost driver for code, plans, and long answers. Sets the cost tier.",
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
  benchmarks: {
    label: "Benchmark scores",
    fullName: "Headline benchmarks",
    definition:
      "Curated public-leaderboard scores the rating synthesizes. Each benchmark name links to its source; some new models read 'pending refresh' until the daily benchmark pass fills them in.",
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
  us: "United States — Anthropic, OpenAI, Google, xAI, Cursor, Groq.",
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
  S: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300",
  A: "bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-300",
  B: "bg-brand-slate-100 text-brand-slate-700 dark:bg-brand-slate-700 dark:text-brand-slate-200",
  C: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  D: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
};

export const COST_TIER_RANK: Record<CostTier, number> = {
  low: 1,
  medium: 2,
  high: 3,
  "very-high": 4,
};

export const COST_TIER_COLORS: Record<CostTier, string> = {
  low: "bg-brand-slate-100 text-brand-slate-700 dark:bg-brand-slate-700 dark:text-brand-slate-200",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  high: "bg-orange-100 text-orange-800 dark:bg-orange-500/15 dark:text-orange-300",
  "very-high": "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
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
  return null;
}

export function formatPrice(value: number | null): string {
  if (value === null || value === undefined) return "—";
  // Trim trailing zeros but keep cents readable: 0.075, 0.6, 2.2, 50.
  return `$${Number(value.toFixed(4)).toString()}`;
}
