-- infra/migrations/0003_conversations_and_messages.sql
--
-- Phase 4 Step 5 — durable storage for the multi-turn /roadmap
-- conversation. The /api/roadmap route writes the user message on
-- POST and the assistant message on stream completion. Each
-- conversation belongs to exactly one auth.users row; RLS pins
-- every read + write to auth.uid() so cross-user reads are
-- impossible from the anon or authenticated roles.
--
-- The roadmaps table that persists the parsed RoadmapDraft
-- snapshot lives in 0004_roadmaps.sql and references
-- conversations.id via ON DELETE CASCADE so deleting a
-- conversation deletes its draft in lockstep.

create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null default 'Untitled roadmap',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  created_at timestamptz not null default now()
);

-- BRIN on (user_id, updated_at) for the /history list query, which
-- always filters by auth.uid() and orders by updated_at desc. BRIN
-- is the right shape here: rows append-only with strong physical
-- correlation on updated_at, and the index is two orders of
-- magnitude smaller than a btree for the same coverage.
create index conversations_user_id_updated_at_brin
  on public.conversations using brin (user_id, updated_at);

-- btree on (conversation_id, created_at) for the chat-rehydration
-- read path: load all messages for one conversation in chronological
-- order. Cardinality here is moderate (≤ ~50 per conversation by
-- Zod cap) so btree beats BRIN.
create index messages_conversation_id_created_at_btree
  on public.messages (conversation_id, created_at);

alter table public.conversations enable row level security;
alter table public.messages enable row level security;

-- conversations: authenticated CRUD scoped to auth.uid().
create policy "authenticated_select_own"
  on public.conversations
  for select
  to authenticated
  using (user_id = auth.uid());

create policy "authenticated_insert_own"
  on public.conversations
  for insert
  to authenticated
  with check (user_id = auth.uid());

create policy "authenticated_update_own"
  on public.conversations
  for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy "authenticated_delete_own"
  on public.conversations
  for delete
  to authenticated
  using (user_id = auth.uid());

-- service_role bypass (matches the 0002_profiles.sql precedent).
create policy "service_role_select"
  on public.conversations
  for select
  to service_role
  using (true);

create policy "service_role_insert"
  on public.conversations
  for insert
  to service_role
  with check (true);

create policy "service_role_update"
  on public.conversations
  for update
  to service_role
  using (true)
  with check (true);

create policy "service_role_delete"
  on public.conversations
  for delete
  to service_role
  using (true);

-- messages: RLS resolves ownership by joining through
-- conversations.user_id. Subselect is index-backed by the
-- conversations primary key so the per-row check is O(log n).
create policy "authenticated_select_own"
  on public.messages
  for select
  to authenticated
  using (
    exists (
      select 1 from public.conversations c
      where c.id = messages.conversation_id
        and c.user_id = auth.uid()
    )
  );

create policy "authenticated_insert_own"
  on public.messages
  for insert
  to authenticated
  with check (
    exists (
      select 1 from public.conversations c
      where c.id = messages.conversation_id
        and c.user_id = auth.uid()
    )
  );

create policy "authenticated_update_own"
  on public.messages
  for update
  to authenticated
  using (
    exists (
      select 1 from public.conversations c
      where c.id = messages.conversation_id
        and c.user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from public.conversations c
      where c.id = messages.conversation_id
        and c.user_id = auth.uid()
    )
  );

create policy "authenticated_delete_own"
  on public.messages
  for delete
  to authenticated
  using (
    exists (
      select 1 from public.conversations c
      where c.id = messages.conversation_id
        and c.user_id = auth.uid()
    )
  );

create policy "service_role_select"
  on public.messages
  for select
  to service_role
  using (true);

create policy "service_role_insert"
  on public.messages
  for insert
  to service_role
  with check (true);

create policy "service_role_update"
  on public.messages
  for update
  to service_role
  using (true)
  with check (true);

create policy "service_role_delete"
  on public.messages
  for delete
  to service_role
  using (true);

-- Touch conversations.updated_at on any related insert so the
-- /history list reflects the most recent activity ordering. Fired
-- as AFTER INSERT to keep the message-insert visible to the
-- subquery before the parent row's updated_at is bumped.
create or replace function public.bump_conversation_updated_at()
returns trigger
language plpgsql
as $$
begin
  update public.conversations
    set updated_at = now()
    where id = new.conversation_id;
  return new;
end;
$$;

create trigger messages_bump_conversation_updated_at
  after insert on public.messages
  for each row
  execute function public.bump_conversation_updated_at();
