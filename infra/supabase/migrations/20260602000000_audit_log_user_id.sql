-- infra/supabase/migrations/20260602000000_audit_log_user_id.sql
--
-- Phase 4 Step 1 — associate audit_log rows with authenticated users.
--
-- Adds a nullable user_id column referencing auth.users(id) with
-- ON DELETE SET NULL so user deletes don't cascade-delete audit
-- history. Anonymous traffic (the Phase 3 /api/recommend handler)
-- continues to write rows with user_id NULL — the column stays
-- nullable forever.
--
-- The RLS policy update is additive: service_role retains the full
-- read + write policies from 20260601000000_audit_log.sql; the new
-- authenticated_select_own policy lets a signed-in user read only
-- their own audit rows; the anon role retains NO read access.

alter table public.audit_log
  add column user_id uuid references auth.users(id) on delete set null;

-- BRIN index on the new column. Partial-WHERE excludes the anonymous
-- (NULL user_id) rows from the index entirely; anonymous traffic is
-- already chronologically clustered and served by audit_log_ts_brin.
create index audit_log_user_id_brin
  on public.audit_log
  using brin (user_id)
  where user_id is not null;

-- Signed-in users can read their own audit history. service_role
-- bypasses RLS regardless; anon has no SELECT policy and so cannot
-- read anything.
create policy "authenticated_select_own"
  on public.audit_log
  for select
  to authenticated
  using (user_id = auth.uid());
