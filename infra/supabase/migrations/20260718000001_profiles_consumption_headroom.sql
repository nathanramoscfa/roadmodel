-- infra/supabase/migrations/20260718000001_profiles_consumption_headroom.sql
--
-- Consumption-headroom effort axis — per-user control over whether the
-- recommender keeps reasoning EFFORT maxed across all three picks (Cost /
-- Balanced / Quality) or scales it down the ladder.
--
-- Effort and capability TIER are separate axes: scaling effort down only helps
-- when effort costs the user something (per-token dollars, a usage cap they can
-- hit, or valued latency). A user on a top-tier flat subscription who never
-- exhausts the budget pays nothing for max effort, so scaling it on the Cost
-- pick only lowers quality. This column lets that user (or the auto-derivation)
-- keep effort maxed while still differentiating the picks by model tier.
--
-- Hybrid activation (mirrors the Settings control + service funding logic):
--   'auto'     — derive from funded tiers (top consumer band >= $200/mo =>
--                effort stays maxed; else scale) — the DEFAULT
--   'uncapped' — explicit: never scale effort (user rarely/never hits limits)
--   'capped'   — explicit: always scale effort down the ladder
--
-- Additive + backward-compatible: NOT NULL DEFAULT 'auto' so every existing row
-- reads as "derive from tier" with no backfill. CHECK-constrained text, mirroring
-- profiles_budget_priority_check. RLS policies inherit from
-- 20260603000000_profiles.sql; the updated_at trigger already covers all columns.

alter table public.profiles
  add column consumption_headroom text not null default 'auto';

alter table public.profiles
  add constraint profiles_consumption_headroom_check check (
    consumption_headroom in ('auto', 'uncapped', 'capped')
  );

comment on column public.profiles.consumption_headroom is
  'Effort-axis control: auto (derive from funded tier price), uncapped (never '
  'scale reasoning effort down the Cost/Balanced/Quality ladder), or capped '
  '(always scale). Default auto. Governs effort level only, never model choice.';
