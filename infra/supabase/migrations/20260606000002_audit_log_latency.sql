-- infra/supabase/migrations/20260606000002_audit_log_latency.sql
--
-- Phase 4 Step 7 — per-request latency spans on the audit log.
-- Additive: a nullable jsonb column. Sequenced after 0005
-- (audit_log.cache_stats) and 0005a (profiles.frontier_roadmap_override);
-- no other schema changes, no new index, no RLS changes.
--
-- The jsonb shape is a fixed-key bag of millisecond integers. Both
-- the web-tier span recorder (web/lib/latency.ts) and the FastAPI
-- service-side timing header (X-Roadmodel-Timing emitted from
-- service/app/main.py) write into the SAME bag — the web tier
-- composes them before INSERT.
--
-- Keys (all integer milliseconds, all nullable for forward-compat):
--   total_ms              — earliest span start → latest span end
--   dispatch_ms           — input parse + profile load + engine resolve
--   scoring_ms            — web-tier local scoring / audit-row assembly
--   provider_ms           — opaque time spent in the upstream FastAPI fetch
--   service_scoring_ms    — service-side scoring / payload assembly
--   service_provider_ms   — service-side recommend_structured (Gemini call)
--   render_ms             — JSON parse + jurisdiction filter + response assemble
--   cold_start_ms         — 0 on warm calls; > 0 on the first call after a cold start
--
-- service_scoring_ms + service_provider_ms together decompose
-- provider_ms; the web tier ingests them from the upstream's
-- X-Roadmodel-Timing response header.
--
-- Phase 9 observability dashboards inherit this column without a
-- retrofit; until then the column is write-only from Phase 4 code
-- and read by the measurement script in scripts/measure-recommend-latency.ts.

alter table public.audit_log
  add column latency_ms jsonb;

comment on column public.audit_log.latency_ms is
  'Per-request latency spans (integer ms). Keys: total_ms, dispatch_ms, '
  'scoring_ms, provider_ms, service_scoring_ms, service_provider_ms, '
  'render_ms, cold_start_ms. service_scoring_ms + service_provider_ms '
  'decompose provider_ms via the upstream X-Roadmodel-Timing header.';
