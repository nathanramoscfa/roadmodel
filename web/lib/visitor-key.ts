// web/lib/visitor-key.ts
//
// The shape of a visitor's own API key, shared by the key field on /recommend
// and the edge's lane decision (lib/funding-lane.ts). Client-safe: no server
// imports, no storage. The key itself is never kept here; the page holds it in
// React state (lib/use-visitor-key.ts) and the edge reads it from its header.

export type VisitorProvider = "openai" | "google" | "anthropic";

export const VISITOR_PROVIDERS: readonly VisitorProvider[] = ["openai", "google", "anthropic"];

// The request headers the key and its provider travel in, browser -> edge ->
// service. Header names are case-insensitive; fetch sends them as written.
export const VISITOR_KEY_HEADER = "x-roadmodel-visitor-key";
export const VISITOR_PROVIDER_HEADER = "x-roadmodel-visitor-provider";

export const PROVIDER_LABEL: Record<VisitorProvider, string> = {
  openai: "OpenAI",
  google: "Google",
  anthropic: "Anthropic",
};

// How each provider's keys begin, as the key field explains it.
export const KEY_PREFIX_HINT: Record<VisitorProvider, string> = {
  openai: "sk-",
  google: "AIza",
  anthropic: "sk-ant-",
};

// OpenAI keys (sk-proj-, sk-svcacct-, …) share sk- with Anthropic's sk-ant-.
const PREFIX_MATCHES: Record<VisitorProvider, (key: string) => boolean> = {
  openai: (k) => k.startsWith("sk-") && !k.startsWith("sk-ant-"),
  google: (k) => k.startsWith("AIza"),
  anthropic: (k) => k.startsWith("sk-ant-"),
};

const KEY_CHARS = /^[A-Za-z0-9_\-.]{20,256}$/;

export function isVisitorProvider(value: unknown): value is VisitorProvider {
  return typeof value === "string" && (VISITOR_PROVIDERS as readonly string[]).includes(value);
}

// Whether `key` could be a `provider` API key: 20 to 256 characters of the
// key alphabet (letters, digits, _ - .), starting with that provider's prefix.
export function visitorKeyLooksValid(provider: VisitorProvider, key: string): boolean {
  return KEY_CHARS.test(key) && PREFIX_MATCHES[provider](key);
}
