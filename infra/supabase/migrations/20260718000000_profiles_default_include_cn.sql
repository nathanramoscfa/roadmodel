-- infra/supabase/migrations/20260718000000_profiles_default_include_cn.sql
--
-- Align the profiles.allowed_jurisdictions COLUMN DEFAULT with the app default
-- flipped in #445/#452: "Restrict to low-risk jurisdictions" now ships OFF, so
-- Chinese-jurisdiction models are available by default. The web
-- DEFAULT_PROFILE.allowed_jurisdictions gained 'cn' (web/lib/profile.ts); this
-- makes the DB fallback match.
--
-- DEFAULT ONLY, no backfill: existing rows hold each user's explicit
-- jurisdiction selection (or the set they onboarded under) and must not be
-- rewritten — the app always sends allowed_jurisdictions on onboarding, so this
-- default is only the fallback for a row inserted without the column. The
-- existing profiles_allowed_jurisdictions_check already permits 'cn', so no
-- constraint change is needed.

alter table public.profiles
  alter column allowed_jurisdictions
  set default array['us', 'eu', 'uk', 'ca', 'au', 'jp', 'kr', 'cn'];
