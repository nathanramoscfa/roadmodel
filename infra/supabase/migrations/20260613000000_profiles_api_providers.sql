-- infra/supabase/migrations/20260613000000_profiles_api_providers.sql
--
-- Phase 4.8 T1 (#260) — per-user API / pay-per-token access dimension.
-- Settings now captures which providers the user reaches via their OWN direct
-- API key (a boolean signal per provider — NEVER the key itself), alongside the
-- existing flat-monthly `subscriptions`. Phase 4.8 T2 (#163) will weigh
-- subscription-$0 vs API-PAYG using this column.
--
-- Additive + backward-compatible: NOT NULL DEFAULT '{}' so every existing row
-- reads as "no API providers declared" with no backfill needed. Mirrors the
-- `subscriptions text[]` column's shape; RLS policies inherit from
-- 20260603000000_profiles.sql (authenticated_*_own + service_role_*). No key
-- material is ever stored here — only provider ids.

alter table public.profiles
  add column api_providers text[] not null default '{}';

comment on column public.profiles.api_providers is
  'Phase 4.8: catalog provider ids (access_methods with billing '
  'per-token / subscription-or-key) the user reaches via their own API key. '
  'A boolean signal per provider, never the key itself. Default empty = none.';
