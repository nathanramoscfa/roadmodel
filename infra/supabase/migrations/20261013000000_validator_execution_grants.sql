-- Hosted defaults may grant anon EXECUTE directly when functions are created.
-- Removing PUBLIC privileges alone does not remove those explicit role grants.
begin;

revoke all on function public.valid_profile_ids(text[]) from public, anon;
revoke all on function public.valid_profile_jurisdictions(text[]) from public, anon;
revoke all on function public.valid_pool_states(jsonb) from public, anon;

grant execute on function public.valid_profile_ids(text[]) to authenticated, service_role;
grant execute on function public.valid_profile_jurisdictions(text[]) to authenticated, service_role;
grant execute on function public.valid_pool_states(jsonb) to authenticated, service_role;

commit;
