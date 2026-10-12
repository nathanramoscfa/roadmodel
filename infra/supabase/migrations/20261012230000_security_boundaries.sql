-- Enforce owner relationships, editable profile columns and bounded stored input.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '60s';

-- Require the referenced conversation to belong to the same authenticated owner.
alter policy authenticated_insert_own on public.roadmaps
  with check (user_id = auth.uid() and exists (
    select 1 from public.conversations c
    where c.id = conversation_id and c.user_id = auth.uid()
  ));
alter policy authenticated_update_own on public.roadmaps
  using (user_id = auth.uid())
  with check (user_id = auth.uid() and exists (
    select 1 from public.conversations c
    where c.id = conversation_id and c.user_id = auth.uid()
  ));

-- Revoking a column alone does not override an existing table-level grant.
revoke insert, update on public.profiles from anon, authenticated;
grant insert (user_id, subscriptions, budget_priority, allowed_jurisdictions,
  onboarded_at, api_providers, consumption_headroom, pool_states)
  on public.profiles to authenticated;
grant update (user_id, subscriptions, budget_priority, allowed_jurisdictions,
  onboarded_at, api_providers, consumption_headroom, pool_states)
  on public.profiles to authenticated;
-- user_id remains an update column for PostgREST UPSERT; USING/WITH CHECK pin it.
-- created_at/updated_at defaults+trigger apply without client write grants.

alter function public.set_profiles_updated_at() set search_path = '';
alter function public.bump_conversation_updated_at() set search_path = '';

create or replace function public.valid_profile_ids(value text[]) returns boolean
language plpgsql immutable set search_path = pg_catalog
as $$
declare
  item text;
begin
  if value is null or cardinality(value) > 64 then return false; end if;
  if cardinality(value) = 0 then return true; end if;
  if array_ndims(value) is distinct from 1 then return false; end if;
  foreach item in array value loop
    if item is null or char_length(item) not between 1 and 100
       or item !~ '^[A-Za-z0-9][A-Za-z0-9._-]*$' then return false; end if;
  end loop;
  return true;
end;
$$;
revoke all on function public.valid_profile_ids(text[]) from public;
grant execute on function public.valid_profile_ids(text[]) to authenticated, service_role;

create or replace function public.valid_profile_jurisdictions(value text[]) returns boolean
language plpgsql immutable set search_path = pg_catalog
as $$
declare item text;
begin
  if value is null or cardinality(value) not between 1 and 10
     or array_ndims(value) is distinct from 1 then return false; end if;
  foreach item in array value loop
    if item is null or item not in
      ('us','eu','uk','ca','au','jp','kr','cn','ru','unknown') then return false; end if;
  end loop;
  return true;
end;
$$;

revoke all on function public.valid_profile_jurisdictions(text[]) from public;
grant execute on function public.valid_profile_jurisdictions(text[]) to authenticated, service_role;

create or replace function public.valid_pool_states(value jsonb) returns boolean
language plpgsql immutable set search_path = pg_catalog
as $$
declare
  item jsonb;
  pool_name text;
  expected_source text;
  expected_platform text;
  minutes numeric;
  observed double precision;
  reset_at double precision;
  seen text[] := '{}';
begin
  if value is null then return false; end if;
  if jsonb_typeof(value) <> 'array' then return false; end if;
  if octet_length(value::text) > 8192 or jsonb_array_length(value) > 6 then
    return false;
  end if;
  for item in select * from jsonb_array_elements(value) loop
    if jsonb_typeof(item) <> 'object' then return false; end if;
    if not (item ?& array['pool','state','observed_at','resets_at','used_percent','window_minutes'])
       or (item - array['pool','state','observed_at','resets_at','used_percent','window_minutes','source','platform_id']) <> '{}'::jsonb then return false; end if;
    if jsonb_typeof(item->'pool') <> 'string' or jsonb_typeof(item->'state') <> 'string'
       or jsonb_typeof(item->'observed_at') <> 'number'
       or jsonb_typeof(item->'used_percent') <> 'number'
       or jsonb_typeof(item->'window_minutes') <> 'number' then return false; end if;
    -- PostgreSQL numeric accepts values JSON clients round to infinity/zero.
    observed := (item->>'observed_at')::double precision;
    if observed <= 0 then return false; end if;
    pool_name := item->>'pool';
    if pool_name = any(seen) then return false; end if;
    seen := array_append(seen,pool_name);
    if item->>'state' not in ('headroom','tight','exhausted')
       or (item->>'observed_at')::numeric <= 0
       or (item->>'used_percent')::numeric not between 0 and 100 then return false; end if;
    expected_source := split_part(pool_name,':',1);
    expected_platform := case expected_source when 'claude' then 'claude-code'
      when 'codex' then 'codex-cli' when 'antigravity' then 'antigravity'
      when 'openrouter' then 'openrouter' else null end;
    if pool_name not in ('claude:weekly','claude:5h','codex:weekly','codex:5h','antigravity:all','openrouter:credits') then return false; end if;
    if item ? 'source' and (jsonb_typeof(item->'source') <> 'string' or item->>'source' <> expected_source) then return false; end if;
    if item ? 'platform_id' and (jsonb_typeof(item->'platform_id') <> 'string' or item->>'platform_id' <> expected_platform) then return false; end if;
    minutes := (item->>'window_minutes')::numeric;
    if (pool_name like '%:weekly' and minutes <> 10080)
       or (pool_name like '%:5h' and minutes <> 300)
       or (pool_name = 'antigravity:all' and minutes not in (300,10080))
       or (pool_name = 'openrouter:credits' and minutes <> 0) then return false; end if;
    if pool_name = 'openrouter:credits' then
      if item->'resets_at' <> 'null'::jsonb then return false; end if;
    elsif item->'resets_at' = 'null'::jsonb then
      if pool_name <> 'antigravity:all' or (item->>'used_percent')::numeric <> 0
         or item->>'state' <> 'headroom' then return false; end if;
    else
      if jsonb_typeof(item->'resets_at') <> 'number' then return false; end if;
      reset_at := (item->>'resets_at')::double precision;
      if reset_at <= observed
         or reset_at > observed + minutes::double precision * 60 + 60 then return false; end if;
    end if;
  end loop;
  return true;
exception
  when numeric_value_out_of_range or invalid_text_representation then
    return false;
end;
$$;
revoke all on function public.valid_pool_states(jsonb) from public;
grant execute on function public.valid_pool_states(jsonb) to authenticated, service_role;
alter table public.profiles add constraint profiles_pool_states_valid
  check (public.valid_pool_states(pool_states));
alter table public.profiles add constraint profiles_preferences_bounded check (
  public.valid_profile_ids(subscriptions) and octet_length(subscriptions::text) <= 16384
  and public.valid_profile_ids(api_providers) and octet_length(api_providers::text) <= 8192
  and public.valid_profile_jurisdictions(allowed_jurisdictions)
);
-- Tighten the remaining JSONB containers without assuming full future schemas.
alter table public.roadmaps add constraint roadmaps_draft_bounded check (
  jsonb_typeof(draft) = 'object' and octet_length(draft::text) <= 1048576
);
alter table public.conversations add constraint conversations_title_bounded
  check (char_length(title) <= 1000);
alter table public.messages add constraint messages_content_bounded
  check (octet_length(content) <= 1048576);
commit;
