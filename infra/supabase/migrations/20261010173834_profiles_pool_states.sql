-- Per-user usage-pool observations for a future authenticated Mac push.
-- Schema only: apply manually before adding any profile writer or reader.
-- Existing profiles retain their current behavior: [] means no pool observations.
-- Existing owner-only profiles RLS and updated_at trigger cover this column.

alter table public.profiles
  add column pool_states jsonb not null default '[]'::jsonb;

alter table public.profiles
  add constraint profiles_pool_states_array_check check (
    jsonb_typeof(pool_states) = 'array'
  );

comment on column public.profiles.pool_states is
  'Per-user normalized usage-pool observations; empty array means unknown. '
  'Future writers must validate allowlisted pool identifiers, states, usage '
  'percentages and UTC observation/reset timestamps. Never store credentials, '
  'raw provider responses or transcripts. Stale/missing data cannot lower a state.';
