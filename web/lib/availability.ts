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

let cache: { ids: string[]; at: number } | null = null;

/** Reset the in-memory cache. Test-only. */
export function _resetAvailabilityCache(): void {
  cache = null;
}

/**
 * Model ids currently marked unavailable (available = false). Cached for
 * AVAILABILITY_CACHE_TTL_MS; fail-open to [] on any error. `now` is injectable
 * for tests.
 */
export async function getUnavailableModelIds(now: number = Date.now()): Promise<string[]> {
  if (cache && now - cache.at < AVAILABILITY_CACHE_TTL_MS) {
    return cache.ids;
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
    cache = { ids, at: now };
    return ids;
  } catch {
    // Never block a recommendation on the availability read.
    cache = { ids: [], at: now };
    return [];
  }
}
