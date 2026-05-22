-- infra/supabase/migrations/20260603000000_profiles.sql

create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  subscriptions text[] not null default '{}',
  budget_priority text not null default 'balanced',
  allowed_jurisdictions text[] not null default array[
    'us', 'eu', 'uk', 'ca', 'au', 'jp', 'kr'
  ],
  onboarded_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint profiles_budget_priority_check check (
    budget_priority in ('cheap', 'balanced', 'best')
  ),
  constraint profiles_allowed_jurisdictions_check check (
    allowed_jurisdictions <@ array[
      'us', 'eu', 'uk', 'ca', 'au', 'jp', 'kr', 'cn', 'ru', 'unknown'
    ]::text[]
  )
);

create index profiles_onboarded_at_null_idx
  on public.profiles (onboarded_at)
  where onboarded_at is null;

alter table public.profiles enable row level security;

create policy "authenticated_select_own"
  on public.profiles
  for select
  to authenticated
  using (user_id = auth.uid());

create policy "authenticated_insert_own"
  on public.profiles
  for insert
  to authenticated
  with check (user_id = auth.uid());

create policy "authenticated_update_own"
  on public.profiles
  for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy "service_role_select"
  on public.profiles
  for select
  to service_role
  using (true);

create policy "service_role_insert"
  on public.profiles
  for insert
  to service_role
  with check (true);

create policy "service_role_update"
  on public.profiles
  for update
  to service_role
  using (true)
  with check (true);

create policy "service_role_delete"
  on public.profiles
  for delete
  to service_role
  using (true);

create or replace function public.set_profiles_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row
  execute function public.set_profiles_updated_at();
