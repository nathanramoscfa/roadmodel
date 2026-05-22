-- infra/test-postgres/init.sql
--
-- Bootstraps the Supabase-managed surface area (schema, roles, RLS
-- helper) so migrations under infra/supabase/migrations/ apply
-- cleanly against a vanilla Postgres 16 container. Production
-- Supabase ships these out of the box; the test container needs
-- them stubbed before any application migration runs.

create schema if not exists auth;

create table if not exists auth.users (
  id uuid primary key default gen_random_uuid(),
  email text
);

-- Supabase RLS roles. CREATE ROLE IF NOT EXISTS isn't supported on
-- Postgres < 17, so we DO blocks to stay 16-compatible.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role;
  end if;
end
$$;

-- auth.uid() helper used by RLS USING expressions. Supabase
-- populates request.jwt.claim.sub from the access token; the test
-- harness sets it explicitly when exercising authenticated reads.
create or replace function auth.uid() returns uuid
language sql
stable
as $$
  select nullif(
    current_setting('request.jwt.claim.sub', true),
    ''
  )::uuid;
$$;
