// web/lib/availability.ts
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { env } from "./env";

// Runtime model availability (Phase 4.9 B2). The /api/recommend route reads the
// currently-unavailable model ids here and forwards them to the service, which
// passes them to the selector as a runtime Step-0a override (roadmodel >=0.2.9
// `unavailable_models`). This lets the availability probe bench / un-bench a model
// WITHOUT a roadmodel package release.
//
// Availability is GLOBAL and changes at most daily (the probe cadence), so the
// list is cached in-memory with a short TTL to keep the Supabase read off the
// per-request hot path. FAIL-OPEN: any error (the table not existing before the
// migration is applied, a transient network blip) yields an empty list, so the
// bundled <availability-context> defaults still apply and a recommendation is
// never blocked on this read.

// Lazy-init mirrors lib/audit.ts: importing must not trigger
// @supabase/realtime-js' WebSocket constructor lookup at module load.
let supabaseClient: SupabaseClient | null = null;
function getSupabase(): SupabaseClient {
  if (!supabaseClient) {
    supabaseClient = createClient(
      env.SUPABASE_URL,
      env.SUPABASE_SERVICE_ROLE_KEY,
      {
        auth: { persistSession: false },
      },
    );
  }
  return supabaseClient;
}

export const AVAILABILITY_CACHE_TTL_MS = 60_000;

export interface ModelAvailability {
  /** Ids currently marked unavailable (available = false). */
  ids: string[];
  /**
   * True when the table read SUCCEEDED — the list is then the complete current
   * truth, so the selector treats it as authoritative and a restored model absent
   * from it is recommendable (no package release needed). False when the read
   * failed (fail-open): the service keeps its conservative bundled
   * <availability-context> static defaults instead.
   */
  authoritative: boolean;
}

let cache: { value: ModelAvailability; at: number } | null = null;

/** Reset the in-memory cache. Test-only. */
export function _resetAvailabilityCache(): void {
  cache = null;
}

/**
 * Current runtime availability: the unavailable-id list plus whether the read
 * was authoritative. Cached for AVAILABILITY_CACHE_TTL_MS. On any error, fail-open
 * to an empty list with `authoritative: false` so the service keeps its
 * fail-closed static defaults rather than the read blocking a recommendation.
 * `now` is injectable for tests.
 */
export async function getModelAvailability(
  now: number = Date.now(),
): Promise<ModelAvailability> {
  if (cache && now - cache.at < AVAILABILITY_CACHE_TTL_MS) {
    return cache.value;
  }
  try {
    const { data, error } = await getSupabase()
      .from("model_availability")
      .select("model_id")
      .eq("available", false);
    if (error) throw error;
    const ids = (data ?? [])
      .map((row) => (row as { model_id?: unknown }).model_id)
      .filter((id): id is string => typeof id === "string" && id.length > 0);
    // Read succeeded (even when empty) -> authoritative.
    const value: ModelAvailability = { ids, authoritative: true };
    cache = { value, at: now };
    return value;
  } catch {
    // Never block a recommendation on the availability read.
    const value: ModelAvailability = { ids: [], authoritative: false };
    cache = { value, at: now };
    return value;
  }
}

/**
 * Back-compat shim: just the unavailable-id list. Prefer getModelAvailability(),
 * which also reports whether the read was authoritative.
 */
export async function getUnavailableModelIds(now: number = Date.now()): Promise<string[]> {
  return (await getModelAvailability(now)).ids;
}
