// web/lib/recommend-engines.ts
//
// The recommender's ENGINES: the models that read a task and write the three
// picks (not the models they recommend). service/app/engines.json is the one
// registry both deployments read: the service runs an engine from it, and the
// web build copies it beside the catalog (scripts/sync-catalog.mjs) so this
// module can build the /recommend engine menu from the same file. Prices come
// from the catalog entry each engine bills as; the measured figures (pass
// rate, latency, cost per recommendation) come from docs/engine-eval.json,
// which scripts/eval_recommend_engines.py --summary-json writes.
//
// Who may choose an engine is enforced HERE, at the edge, before any paid
// call: `public` engines are open to everyone, `signed_in` ones to any
// account, `founder` ones to the operator allowlist. The service runs
// whatever the authenticated edge forwards.

import catalog from "@/data/catalog.json";
import evals from "@/data/engine-eval.json";
import registry from "@/data/engines.json";

import { modelProvider } from "./catalog-fields";
import { isRateLimitExempt } from "./ratelimit";

export type EngineAccess = "public" | "signed_in" | "founder";
export type Viewer = "anonymous" | "signed_in" | "founder";

const ACCESS_RANK: Record<EngineAccess, number> = { public: 0, signed_in: 1, founder: 2 };

// An engine is offered once it has answered the engine eval in full on at
// least this share of the probe tasks (docs/engine-eval.json). Until then it
// is listed as awaiting evaluation, and cannot be chosen: the menu offers
// engines that are known to work. The default engine is always runnable.
const PASS_SHARE = 0.9;
const VIEWER_RANK: Record<Viewer, number> = { anonymous: 0, signed_in: 1, founder: 2 };

// Measured on the live ladder prompt (2026-10-02): every recommendation sends
// the selector + catalog prefix (~240k characters) plus the task, and gets
// ~700-1,200 output tokens back (reasoning included). The same prompt is a
// different number of tokens to each provider's tokenizer. Used only where an
// engine has no measured figure yet, and for the ledger when a provider
// reports no usage.
const PROMPT_TOKENS_BY_PROVIDER: Record<string, number> = {
  openai: 61_000,
  google: 66_500,
  anthropic: 94_000,
};
export const PROMPT_TOKENS = PROMPT_TOKENS_BY_PROVIDER.openai;
export const OUTPUT_TOKENS = 750;

export function promptTokens(engine: Pick<Engine, "provider">): number {
  return PROMPT_TOKENS_BY_PROVIDER[engine.provider] ?? PROMPT_TOKENS;
}
// Cache reads cost a tenth of the input price at OpenAI, Google and on Claude
// Haiku; the catalog's own cache price wins where it lists one.
const CACHE_READ_SHARE = 0.1;
// Anthropic bills a 5-minute cache write at 1.25x the input price.
const CACHE_WRITE_MULTIPLIER = 1.25;

interface RegistryEntry {
  hint: string;
  catalog_id: string;
  provider: string;
  model: string;
  menu: EngineAccess | null;
}

interface CatalogEntry {
  id: string;
  name: string;
  input_price_per_1m: number;
  output_price_per_1m: number;
  cache_read_per_1m?: number | null;
  tier_cost?: string;
}

export interface EngineEval {
  evaluated_on: string;
  probes: number;
  parsed: number;
  passed: number;
  p50_latency_s: number | null;
  mean_cost_usd: number | null;
  cached_share: number | null;
  quality_pick_blended_per_1m: number | null;
  via: "service" | "package";
}

export interface Engine {
  // The engines.json hint: the wire id the edge forwards as force_provider.
  hint: string;
  catalogId: string;
  provider: string;
  name: string;
  maker: string;
  // Who may choose it on the menu; null for a runnable engine the menu does
  // not offer (rollback and comparison engines).
  access: EngineAccess | null;
  isDefault: boolean;
  inputPer1m: number;
  outputPer1m: number;
  cacheReadPer1m: number;
  // One three-pick recommendation at catalog prices: nothing cached, and with
  // the static prompt prefix served from the provider's cache.
  coldUsd: number;
  warmUsd: number;
  eval: EngineEval | null;
}

const CATALOG = new Map((catalog.models as CatalogEntry[]).map((m) => [m.id, m]));
const EVALS = ((evals as { engines?: Record<string, EngineEval> }).engines ?? {}) as Record<
  string,
  EngineEval
>;
const REGISTRY = registry as { default: string; engines: RegistryEntry[] };

const MAKER: Record<string, string> = { openai: "OpenAI", google: "Google", anthropic: "Anthropic" };

function toEngine(entry: RegistryEntry): Engine | null {
  const model = CATALOG.get(entry.catalog_id);
  if (!model) return null;
  const input = model.input_price_per_1m;
  const output = model.output_price_per_1m;
  const cache = model.cache_read_per_1m ?? input * CACHE_READ_SHARE;
  const out = OUTPUT_TOKENS * output;
  const prompt = promptTokens(entry);
  return {
    hint: entry.hint,
    catalogId: entry.catalog_id,
    provider: entry.provider,
    name: model.name,
    maker: MAKER[entry.provider] ?? modelProvider(entry.catalog_id)?.label ?? entry.provider,
    access: entry.menu,
    isDefault: entry.hint === REGISTRY.default,
    inputPer1m: input,
    outputPer1m: output,
    cacheReadPer1m: cache,
    coldUsd: (prompt * input + out) / 1_000_000,
    warmUsd: (prompt * cache + out) / 1_000_000,
    eval: EVALS[entry.hint] ?? null,
  };
}

const ALL: Engine[] = REGISTRY.engines.flatMap((e) => toEngine(e) ?? []);
const BY_HINT = new Map(ALL.map((e) => [e.hint, e]));

// The menu: every offered engine, cheapest first (the default leads its price).
export const MENU: Engine[] = ALL.filter((e) => e.access !== null).sort(
  (a, b) => a.coldUsd - b.coldUsd || Number(b.isDefault) - Number(a.isDefault),
);

export const DEFAULT_ENGINE: Engine = BY_HINT.get(REGISTRY.default) as Engine;

export function engineByHint(hint: string | null | undefined): Engine | undefined {
  return hint ? BY_HINT.get(hint) : undefined;
}

// The operator allowlist doubles as the founder tier: the same signed-in ids
// that skip the rate limit (RECOMMEND_RATELIMIT_EXEMPT_USER_IDS).
export function viewerFor(userId: string | null | undefined): Viewer {
  if (!userId) return "anonymous";
  return isRateLimitExempt(userId) ? "founder" : "signed_in";
}

export function isEvaluated(engine: Engine): boolean {
  if (engine.isDefault) return true;
  const e = engine.eval;
  return e !== null && e.probes > 0 && e.passed / e.probes >= PASS_SHARE;
}

export function canUse(viewer: Viewer, engine: Engine): boolean {
  return (
    engine.access !== null &&
    VIEWER_RANK[viewer] >= ACCESS_RANK[engine.access] &&
    isEvaluated(engine)
  );
}

export type EngineChoice =
  | { ok: true; engine: Engine }
  | { ok: false; error: "unknown_engine" }
  | { ok: false; error: "engine_not_allowed" | "engine_not_evaluated"; engine: Engine };

// The engine a request runs on: the one asked for when this viewer may use it,
// the default when none was asked for.
export function chooseEngine(requested: unknown, viewer: Viewer): EngineChoice {
  if (requested === undefined || requested === null || requested === "") {
    return { ok: true, engine: DEFAULT_ENGINE };
  }
  const engine = typeof requested === "string" ? BY_HINT.get(requested) : undefined;
  if (!engine || engine.access === null) return { ok: false, error: "unknown_engine" };
  if (!isEvaluated(engine)) return { ok: false, error: "engine_not_evaluated", engine };
  if (!canUse(viewer, engine)) return { ok: false, error: "engine_not_allowed", engine };
  return { ok: true, engine };
}

// The provider-reported counts of one engine call (roadmodel.usage), as the
// service returns them.
export interface EngineUsage {
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  output_tokens: number;
  reasoning_tokens?: number | null;
}

export function isEngineUsage(value: unknown): value is EngineUsage {
  if (!value || typeof value !== "object") return false;
  const u = value as Record<string, unknown>;
  return ["input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens"].every(
    (k) => typeof u[k] === "number" && Number.isFinite(u[k]) && (u[k] as number) >= 0,
  );
}

// What a call cost at the engine's catalog prices: uncached input at the input
// price, cache reads at the cache price, Anthropic cache writes at 1.25x.
export function costFromUsage(engine: Engine, u: EngineUsage): number {
  const uncached = Math.max(0, u.input_tokens - u.cached_input_tokens - u.cache_write_tokens);
  const usd =
    uncached * engine.inputPer1m +
    u.cached_input_tokens * engine.cacheReadPer1m +
    u.cache_write_tokens * engine.inputPer1m * CACHE_WRITE_MULTIPLIER +
    u.output_tokens * engine.outputPer1m;
  return Number((usd / 1_000_000).toFixed(6));
}

// The cost estimate for a call whose provider reported no usage: the cold
// price (nothing cached), the conservative side for the daily spend guard.
export function estimatedCost(
  engine: Engine,
  taskChars: number,
  { inputCalls = 1, outputCalls = 1 }: { inputCalls?: number; outputCalls?: number } = {},
): EngineUsage & { costUsd: number } {
  const input = (promptTokens(engine) + Math.ceil(taskChars / 4)) * inputCalls;
  const output = OUTPUT_TOKENS * outputCalls;
  const usage = {
    input_tokens: input,
    cached_input_tokens: 0,
    cache_write_tokens: 0,
    output_tokens: output,
  };
  return { ...usage, costUsd: costFromUsage(engine, usage) };
}

// A compact, client-safe view of an engine for the menu (no internals).
export interface EngineOption {
  hint: string;
  name: string;
  maker: string;
  access: EngineAccess;
  isDefault: boolean;
  // Passed the engine eval (or is the default): see isEvaluated.
  evaluated: boolean;
  allowed: boolean;
  coldUsd: number;
  warmUsd: number;
  eval: EngineEval | null;
}

export function menuFor(viewer: Viewer): EngineOption[] {
  return MENU.map((e) => ({
    hint: e.hint,
    name: e.name,
    maker: e.maker,
    access: e.access as EngineAccess,
    isDefault: e.isDefault,
    evaluated: isEvaluated(e),
    allowed: canUse(viewer, e),
    coldUsd: e.coldUsd,
    warmUsd: e.warmUsd,
    eval: e.eval,
  }));
}
