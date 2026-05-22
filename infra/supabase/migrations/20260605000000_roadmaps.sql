-- infra/supabase/migrations/20260605000000_roadmaps.sql
--
-- Phase 4 Step 5 — RoadmapDraft persistence. One row per
-- conversation (UNIQUE conversation_id) so the route handler can
-- UPSERT the latest snapshot as the stream completes without
-- bookkeeping. The draft is stored as jsonb verbatim — the
-- TypeScript RoadmapDraft type (web/lib/roadmap-types.ts) is the
-- consumer-side contract; this column is the storage-side
-- contract.
--
-- The /api/roadmaps/[id]/export route reads draft -> renders
-- template-compliant Markdown. The JSONB index on
-- draft->>'title' powers the /history page's project-name
-- substring search.

create table public.roadmaps (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  draft jsonb not null,
  generated_at timestamptz not null default now(),
  unique (conversation_id)
);

-- Index for project-name substring search on the /history page.
-- The expression matches the TypeScript engine's title extraction:
-- the H1 heading line is captured into draft.title at parse time.
create index roadmaps_draft_title_idx
  on public.roadmaps ((draft->>'title'));

alter table public.roadmaps enable row level security;

create policy "authenticated_select_own"
  on public.roadmaps
  for select
  to authenticated
  using (user_id = auth.uid());

create policy "authenticated_insert_own"
  on public.roadmaps
  for insert
  to authenticated
  with check (user_id = auth.uid());

create policy "authenticated_update_own"
  on public.roadmaps
  for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy "authenticated_delete_own"
  on public.roadmaps
  for delete
  to authenticated
  using (user_id = auth.uid());

create policy "service_role_select"
  on public.roadmaps
  for select
  to service_role
  using (true);

create policy "service_role_insert"
  on public.roadmaps
  for insert
  to service_role
  with check (true);

create policy "service_role_update"
  on public.roadmaps
  for update
  to service_role
  using (true)
  with check (true);

create policy "service_role_delete"
  on public.roadmaps
  for delete
  to service_role
  using (true);
