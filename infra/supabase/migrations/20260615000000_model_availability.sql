-- infra/supabase/migrations/20260615000000_model_availability.sql
--
-- Phase 4.9 B2 — runtime model availability.
-- A small, service-role-only table the recommend path consults so a model whose
-- provider has pulled or restricted access can be benched (or un-benched) WITHOUT
-- a roadmodel package release. The web /api/recommend route reads the rows where
-- available = false and forwards the ids to the service, which passes them to the
-- selector as a runtime Step-0a override (roadmodel >=0.2.9 `unavailable_models`).
-- Maintained by the daily availability probe (auto-PR -> git source of truth ->
-- synced here). The bundled <availability-context> stays as the static default,
-- so this layer is additive and fail-open: an empty/absent table changes nothing.
--
-- Not user-scoped: availability is global. RLS is enabled with NO anon/authenticated
-- policies, so only the service role (the server-side recommend read + the sync job)
-- can see or write it. Never client-readable.

create table if not exists public.model_availability (
  model_id   text primary key,
  available  boolean     not null default true,
  reason     text,
  source     text        not null default 'manual',
  updated_at timestamptz not null default now()
);

comment on table public.model_availability is
  'Phase 4.9: runtime model availability. A row with available=false marks a '
  'catalogued model id as currently unavailable; the recommend path forwards these '
  'to the selector as a runtime Step-0a override. Maintained by the availability '
  'probe. Service-role only.';

alter table public.model_availability enable row level security;

-- Service role only (server-side recommend read + the sync job). service_role
-- bypasses RLS, but an explicit policy documents intent and survives any future
-- default-deny tightening. No anon/authenticated policies => not client-readable.
create policy "service_role_all"
  on public.model_availability
  for all
  to service_role
  using (true)
  with check (true);
