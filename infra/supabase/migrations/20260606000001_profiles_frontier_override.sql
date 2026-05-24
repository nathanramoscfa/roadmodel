-- infra/supabase/migrations/20260606000001_profiles_frontier_override.sql
--
-- Phase 4 Step 6 — per-user frontier-roadmap override. The Phase 5
-- paid-frontier rollout flips this to TRUE on the rows whose
-- subscription state qualifies for the frontier engine. Phase 4
-- only READS this column (via getProfile() into the resolver);
-- the column stays nullable forever so the env-var-level default
-- (FRONTIER_ROADMAP_ENABLED, defaulting to false in Phase 4) remains
-- the fallback for users who haven't been explicitly opted in/out.
--
-- Tri-state semantics (deliberately not a boolean default false):
--   NULL  → honor env-var-level default (FRONTIER_ROADMAP_ENABLED)
--   TRUE  → force frontier on for this user (Phase 5 paid path)
--   FALSE → force frontier off for this user (regression escape
--           hatch; lets the maintainer turn the frontier branch off
--           for a single user without flipping the env var)
--
-- No new index: the column is only ever read alongside an existing
-- profile row lookup (eq user_id), and the row is already keyed by
-- user_id. RLS policies inherit from 20260603000000_profiles.sql
-- (authenticated_select_own etc.) — no policy changes here.

alter table public.profiles
  add column frontier_roadmap_override boolean;

comment on column public.profiles.frontier_roadmap_override is
  'Per-user override of the frontier_roadmap_enabled flag. '
  'NULL = honor env-var default (FRONTIER_ROADMAP_ENABLED); '
  'TRUE = force frontier on; FALSE = force frontier off. '
  'Phase 5 paid-frontier rollout populates this column.';
