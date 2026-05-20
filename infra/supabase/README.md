<!-- infra/supabase/README.md -->
# Supabase migrations

This directory holds the canonical SQL schema for the
`roadmodel-data` Supabase Postgres project (ID
`nbxzpqnmafcayeqnfvcv`; see
[infra/README.md](../README.md#cloud-projects)). Each migration is a
single `.sql` file applied in lexicographic order.

## Naming convention

```
<UTC-timestamp>_<snake_case_name>.sql
```

- `UTC-timestamp` is 14 digits (`YYYYMMDDHHMMSS`) chosen at write
  time. This guarantees lexicographic ordering matches chronological
  ordering across maintainers and matches the Supabase CLI's native
  migration ordering.
- `snake_case_name` is a short description (`audit_log`, `users`,
  `history`, etc.) — lowercase ASCII + underscores only.

The Phase 3 Step 6 migration
[`20260601000000_audit_log.sql`](migrations/20260601000000_audit_log.sql)
is the first in this tree; Phase 4 adds `users` and `history`
migrations with later timestamps as `/roadmap` and auth land.

## Applying migrations

Migrations are applied manually for now (no GitHub-Actions
auto-apply until Phase 7 — see
[private/ROADMAP.md](../../private/ROADMAP.md) §4 Phase 7.5
"Infrastructure and secrets"):

```bash
# One-time: link this repo to the Supabase project
supabase link --project-ref nbxzpqnmafcayeqnfvcv

# Apply all unapplied migrations in order
supabase db push --linked
```

The Supabase CLI tracks applied migrations in the project's
`supabase_migrations.schema_migrations` table — re-running
`db push --linked` is idempotent. After applying, verify the change
in the dashboard's Table Editor or via `supabase db diff --linked`.

## Row-level security posture

Every table in this tree must `enable row level security` and
declare explicit policies for the role(s) that may read/write it.
The Phase 3 audit log is service-role-only — the browser-facing
anon key cannot see it. Phase 4 introduces `users` and `history`
tables that need per-user policies keyed on `auth.uid()`; the
patterns for those land in their own migration files when Phase 4
ships.

## Rollback

The current posture is **forward-only**: a bad migration is fixed
by writing a new compensating migration, not by reverting the prior
file. This matches Supabase's CLI design and avoids divergence
between the file tree and the project's applied state. Disaster
recovery for a destroyed table uses the daily Supabase Pro backups
documented in [infra/README.md](../README.md#disaster-recovery).
