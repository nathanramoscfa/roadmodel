-- Quota-aware effort (2026-09-21): `auto` no longer derives `uncapped` from the
-- funded tier price: subscription price does not guarantee remaining quota.
-- Comment-only: no data or constraint change.
comment on column public.profiles.consumption_headroom is
  'Effort-axis control: auto (resolves to capped service-side), uncapped '
  '(explicit opt-in: never scale reasoning effort down; also satisfies the '
  'selector''s flat-funding gate so the model tier is held), or capped '
  '(calibrate effort and tier to the task). Default auto.';
