// web/lib/recommend-context.ts
//
// The part of the upstream `context` a browser may set. The service reads a
// dozen context keys (service/app/models.py); the edge sets all of them from
// the session, the profile and the engine menu, except the operator's hard
// platform filters, which only narrow what may be recommended. Those two are
// the allowlist. Every other key a request body carries is dropped here and
// never forwarded, so a browser cannot pin an engine (`force_provider`),
// override funding, or reach a key the service adds later.

export const CLIENT_CONTEXT_KEYS = ["platforms_allowed", "platforms_excluded"] as const;

type ClientContextKey = (typeof CLIENT_CONTEXT_KEYS)[number];
export type ClientContext = Partial<Record<ClientContextKey, string[]>>;

// Bounds on a forwarded list: the catalog has a few dozen platforms.
const MAX_ITEMS = 64;
const MAX_ITEM_CHARS = 100;

function stringList(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const items = value
    .filter((v): v is string => typeof v === "string" && v.length > 0 && v.length <= MAX_ITEM_CHARS)
    .slice(0, MAX_ITEMS);
  return items;
}

// The allowlisted keys of a request body's `context`, each a list of strings.
export function clientContext(raw: unknown): ClientContext {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return {};
  const source = raw as Record<string, unknown>;
  const out: ClientContext = {};
  for (const key of CLIENT_CONTEXT_KEYS) {
    const list = stringList(source[key]);
    if (list !== undefined) out[key] = list;
  }
  return out;
}
