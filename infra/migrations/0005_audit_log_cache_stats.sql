-- infra/migrations/0005_audit_log_cache_stats.sql
--
-- Phase 4 Step 6 — provider-discriminated cache stats on the audit
-- log. Additive: a nullable jsonb column, no new index, no RLS
-- changes. Phase 8 dashboards add query indexes when the
-- latency / cost views light up.
--
-- The jsonb shape is a DISCRIMINATED UNION on `provider`. Phase 4
-- writes Google rows only; Phase 5 paid-frontier rollout starts
-- writing Anthropic rows against the SAME column, which is why
-- the schema's forward-compatibility comment is committed here.
--
-- Google variant (Phase 4):
--   {
--     "provider": "google",
--     "promptTokenCount":              integer,
--     "candidatesTokenCount":          integer,
--     "cachedContentTokenCount":       integer,
--     "cachedContentTokenCountUsed":   integer
--   }
--
-- Anthropic variant (Phase 5 — documented here, written by Phase 5):
--   {
--     "provider": "anthropic",
--     "input_tokens":                  integer,
--     "output_tokens":                 integer,
--     "cache_read_input_tokens":       integer,
--     "cache_creation_input_tokens":   integer
--   }
--
-- The discriminator lets Phase 8 dashboards compute "% cached" with
-- a single CASE expression keyed on `provider` rather than
-- re-deriving from the engine/model string.

alter table public.audit_log
  add column cache_stats jsonb;

comment on column public.audit_log.cache_stats is
  'Provider-discriminated cache usage stats. Discriminator: provider. '
  'Google: {provider,promptTokenCount,candidatesTokenCount,'
  'cachedContentTokenCount,cachedContentTokenCountUsed}. '
  'Anthropic (Phase 5+): {provider,input_tokens,output_tokens,'
  'cache_read_input_tokens,cache_creation_input_tokens}.';
