-- infra/supabase/migrations/20260601000000_audit_log.sql

create table public.audit_log (
  id bigserial primary key,
  ts timestamptz not null default now(),
  ip_hash text not null,
  ua_hash text not null,
  route text not null,
  provider text,
  model text,
  input_tokens integer,
  output_tokens integer,
  cost_usd numeric(10, 6),
  outcome text not null check (
    outcome in (
      'ok',
      'rate_limited',
      'burst_dropped',
      'recommender_error',
      'bad_input'
    )
  ),
  error_class text
);

create index audit_log_ts_brin on public.audit_log using brin (ts);

alter table public.audit_log enable row level security;

-- Service role only. The browser anon key cannot read or write this
-- table; only the Next.js server using the service-role key writes.
create policy "service_role_only_insert"
  on public.audit_log
  for insert
  to service_role
  with check (true);

create policy "service_role_only_select"
  on public.audit_log
  for select
  to service_role
  using (true);
