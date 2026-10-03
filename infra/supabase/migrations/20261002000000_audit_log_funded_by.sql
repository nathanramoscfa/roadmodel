-- infra/supabase/migrations/20261002000000_audit_log_funded_by.sql
--
-- Phase 4.11 Step 1 — who paid for each request, and an outcome CHECK that
-- matches the writer. Additive: a nullable column and a wider CHECK, no new
-- index, no RLS or grant changes.
--
-- funded_by: the funding lane of the request (web/lib/funding-lane.ts).
-- 'operator' is roadmodel's own provider keys (the founder, the invite list,
-- the maintainer's bypass header); 'visitor' a visitor's own key (Step 2);
-- 'keyless' a pick computed in code at $0 (Step 5). Null on a refused request
-- and on every row written before this migration. The daily spend guard sums
-- cost_usd over operator rows and that null history only.
--
-- outcome: the original CHECK (20260601000000) allowed five values while the
-- writer's AuditOutcome union (web/lib/audit.ts) grew to ten, so every
-- daily_cost_cap, bypassed_rate_limit, unauthorized and roadmap_* row failed
-- to insert, silently (audit writes are fire-and-forget). Production still
-- carried the original five-value audit_log_outcome_check when this was
-- written (read with pg_get_constraintdef on 2026-10-02). Dropping it by name
-- and adding the full set converges that state and a fresh database alike.
-- The set is the union plus Phase 4.11's outcomes: funding_required (Step 1)
-- and visitor_key_rejected, visitor_quota, provider_error (Step 2, added now
-- so Step 2 needs no migration). tests/test_audit_log_migration.py asserts
-- this list equals the TypeScript union.

alter table public.audit_log
  add column funded_by text null
  constraint audit_log_funded_by_check
  check (funded_by in ('operator', 'visitor', 'keyless'));

comment on column public.audit_log.funded_by is
  'Funding lane of the request: operator (roadmodel''s keys: founder, invited, '
  'bypass), visitor (the visitor''s own key) or keyless (computed at $0). '
  'Null on refused requests and on rows written before 2026-10-02.';

alter table public.audit_log
  drop constraint if exists audit_log_outcome_check;

alter table public.audit_log
  add constraint audit_log_outcome_check check (
    outcome in (
      'ok',
      'rate_limited',
      'burst_dropped',
      'recommender_error',
      'bad_input',
      'roadmap_monthly_cap',
      'roadmap_error',
      'unauthorized',
      'daily_cost_cap',
      'bypassed_rate_limit',
      'funding_required',
      'visitor_key_rejected',
      'visitor_quota',
      'provider_error'
    )
  );
