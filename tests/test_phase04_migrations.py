"""tests/test_phase04_migrations.py

Phase 4 live-Postgres migration tests. Applies every migration in
``infra/supabase/migrations`` in lexicographic (timestamp) order
against a running Postgres instance, then asserts the audit_log
schema, indexes, and RLS policies are exactly as Phase 4 Step 1
ships them.

Layout mirrors :mod:`tests.test_audit_log_migration` (module-level
constants, small assertion helpers, one assertion per concern); the
actual checks query Postgres catalog tables rather than parsing SQL
with sqlparse because Step 1 changes RLS behavior, which is a
runtime property, not a syntactic one.

Skipped at the module level when ``DATABASE_URL`` is unset, so
local ``pytest`` invocations without the
``infra/test-postgres/docker-compose.yml`` Postgres up still pass.
The ``migration-tests`` CI job in ``.github/workflows/tests.yml``
spins the container up and sets ``DATABASE_URL``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    DATABASE_URL is None,
    reason="DATABASE_URL not set; skipping live-Postgres migration tests",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "infra" / "supabase" / "migrations"
TIMESTAMP_RE = re.compile(r"^\d{14}_[a-z_]+\.sql$")


def _migration_files() -> list[Path]:
    return sorted(f for f in MIGRATIONS_DIR.iterdir() if TIMESTAMP_RE.match(f.name))


@pytest.fixture(scope="module")
def db_conn() -> "psycopg.Connection":
    import psycopg

    assert DATABASE_URL is not None  # mypy + pytest.skip narrowing
    conn = psycopg.connect(DATABASE_URL, autocommit=False)
    try:
        with conn.cursor() as cur:
            # Reset the test database between module runs so reruns
            # don't trip "object already exists". The schema is owned
            # by postgres; CASCADE removes audit_log, profiles,
            # conversations, messages, roadmaps, indexes, RLS.
            cur.execute("drop table if exists public.roadmaps cascade")
            cur.execute("drop table if exists public.messages cascade")
            cur.execute("drop table if exists public.conversations cascade")
            cur.execute("drop table if exists public.profiles cascade")
            cur.execute("drop table if exists public.audit_log cascade")
        conn.commit()
        for path in _migration_files():
            sql = path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        yield conn
    finally:
        conn.close()


def test_at_least_two_migrations_present() -> None:
    files = _migration_files()
    assert len(files) >= 7, (
        f"expected ≥ 7 timestamped migrations under {MIGRATIONS_DIR}; "
        f"found {[f.name for f in files]}"
    )


def test_migration_filenames_match_convention() -> None:
    for path in _migration_files():
        assert TIMESTAMP_RE.match(path.name), (
            f"migration {path.name!r} must match {TIMESTAMP_RE.pattern}"
        )


def test_audit_log_table_exists(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select 1 from information_schema.tables "
            "where table_schema = 'public' and table_name = 'audit_log'"
        )
        assert cur.fetchone() is not None, "audit_log table missing"


def test_user_id_column_uuid_nullable(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select data_type, is_nullable from information_schema.columns "
            "where table_schema = 'public' and table_name = 'audit_log' "
            "and column_name = 'user_id'"
        )
        row = cur.fetchone()
    assert row is not None, "user_id column missing on audit_log"
    data_type, is_nullable = row
    assert data_type == "uuid", f"user_id must be uuid, got {data_type}"
    assert is_nullable == "YES", "user_id must be nullable"


def test_user_id_fk_to_auth_users_set_null(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            """
            select
              rc.delete_rule,
              ccu.table_schema,
              ccu.table_name,
              ccu.column_name
            from information_schema.table_constraints tc
            join information_schema.key_column_usage kcu
              on tc.constraint_name = kcu.constraint_name
              and tc.table_schema = kcu.table_schema
            join information_schema.referential_constraints rc
              on tc.constraint_name = rc.constraint_name
            join information_schema.constraint_column_usage ccu
              on rc.unique_constraint_name = ccu.constraint_name
            where tc.table_schema = 'public'
              and tc.table_name = 'audit_log'
              and tc.constraint_type = 'FOREIGN KEY'
              and kcu.column_name = 'user_id'
            """
        )
        row = cur.fetchone()
    assert row is not None, "user_id foreign key to auth.users is missing"
    delete_rule, ref_schema, ref_table, ref_column = row
    assert delete_rule == "SET NULL", f"user_id FK delete rule must be SET NULL, got {delete_rule}"
    assert (ref_schema, ref_table, ref_column) == ("auth", "users", "id"), (
        f"user_id FK must reference auth.users(id); got {ref_schema}.{ref_table}({ref_column})"
    )


def test_user_id_brin_partial_index(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select indexdef from pg_indexes "
            "where schemaname = 'public' and tablename = 'audit_log' "
            "and indexname = 'audit_log_user_id_brin'"
        )
        row = cur.fetchone()
    assert row is not None, "audit_log_user_id_brin index missing"
    idx_def = row[0]
    assert "USING brin" in idx_def, f"index must use BRIN access method; got {idx_def}"
    assert "user_id IS NOT NULL" in idx_def, (
        f"index must be partial WHERE user_id IS NOT NULL; got {idx_def}"
    )


def test_authenticated_select_policy_filters_by_auth_uid(
    db_conn: "psycopg.Connection",
) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select pol.polname, pg_get_expr(pol.polqual, pol.polrelid), "
            "       array(select rolname from pg_roles where oid = any(pol.polroles)) "
            "from pg_policy pol "
            "join pg_class c on c.oid = pol.polrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relname = 'audit_log' "
            "  and pol.polname = 'authenticated_select_own'"
        )
        row = cur.fetchone()
    assert row is not None, "authenticated_select_own policy missing"
    _name, qual, roles = row
    assert "authenticated" in roles, f"policy must be scoped to authenticated role; got {roles}"
    # qual is the USING expression, normalized by Postgres. Look for
    # the user_id = auth.uid() shape (whitespace/casing-tolerant).
    assert qual is not None and "user_id" in qual and "uid()" in qual, (
        f"policy USING expression must compare user_id to auth.uid(); got {qual!r}"
    )


def test_anon_has_no_select_policy(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute("select oid from pg_roles where rolname = 'anon'")
        anon = cur.fetchone()
        assert anon is not None, "anon role not provisioned by init.sql"
        anon_oid = anon[0]
        cur.execute(
            "select count(*) from pg_policy pol "
            "join pg_class c on c.oid = pol.polrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' "
            "  and c.relname = 'audit_log' "
            "  and %s = any(pol.polroles)",
            (anon_oid,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 0, f"anon role must have no audit_log policies; found {row[0]}"


def test_service_role_policies_preserved(db_conn: "psycopg.Connection") -> None:
    # Step 6's service_role_only_insert + service_role_only_select
    # policies must survive Step 1's additive change.
    with db_conn.cursor() as cur:
        cur.execute(
            "select polname from pg_policy pol "
            "join pg_class c on c.oid = pol.polrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relname = 'audit_log'"
        )
        names = {row[0] for row in cur.fetchall()}
    assert "service_role_only_insert" in names, (
        f"service_role_only_insert (Step 6) regressed; policies: {names}"
    )
    assert "service_role_only_select" in names, (
        f"service_role_only_select (Step 6) regressed; policies: {names}"
    )


def test_profiles_table_exists(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select 1 from information_schema.tables "
            "where table_schema = 'public' and table_name = 'profiles'"
        )
        assert cur.fetchone() is not None, "profiles table missing"


def test_profiles_columns_and_defaults(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            """
            select column_name, data_type, column_default
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'profiles'
            order by ordinal_position
            """
        )
        rows = {name: (dtype, default) for name, dtype, default in cur.fetchall()}
    expected = [
        "user_id",
        "subscriptions",
        "budget_priority",
        "allowed_jurisdictions",
        "onboarded_at",
        "created_at",
        "updated_at",
    ]
    for column in expected:
        assert column in rows, f"{column} column missing on profiles"
    assert rows["subscriptions"][0] == "ARRAY"
    assert rows["allowed_jurisdictions"][0] == "ARRAY"
    assert "'balanced'" in (rows["budget_priority"][1] or "")
    assert "'us'" in (rows["allowed_jurisdictions"][1] or "")


def test_profiles_check_constraints(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            """
            select conname, pg_get_constraintdef(oid)
            from pg_constraint
            where conrelid = 'public.profiles'::regclass
              and contype = 'c'
            """
        )
        defs = {name: definition for name, definition in cur.fetchall()}
    assert any(
        "budget_priority" in definition and "balanced" in definition for definition in defs.values()
    ), "budget_priority CHECK constraint missing"
    assert any(
        "allowed_jurisdictions" in definition and "<@" in definition for definition in defs.values()
    ), "allowed_jurisdictions subset CHECK constraint missing"


def test_profiles_onboarded_at_partial_index(
    db_conn: "psycopg.Connection",
) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select indexdef from pg_indexes "
            "where schemaname = 'public' and tablename = 'profiles' "
            "and indexname = 'profiles_onboarded_at_null_idx'"
        )
        row = cur.fetchone()
    assert row is not None, "profiles_onboarded_at_null_idx index missing"
    idx_def = row[0]
    assert "onboarded_at" in idx_def
    assert "IS NULL" in idx_def


def test_profiles_authenticated_policies(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select polname from pg_policy pol "
            "join pg_class c on c.oid = pol.polrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relname = 'profiles'"
        )
        names = {row[0] for row in cur.fetchall()}
    for policy in (
        "authenticated_select_own",
        "authenticated_insert_own",
        "authenticated_update_own",
    ):
        assert policy in names, f"{policy} missing on profiles"


def test_profiles_service_role_policies(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select polname from pg_policy pol "
            "join pg_class c on c.oid = pol.polrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relname = 'profiles'"
        )
        names = {row[0] for row in cur.fetchall()}
    for policy in (
        "service_role_select",
        "service_role_insert",
        "service_role_update",
        "service_role_delete",
    ):
        assert policy in names, f"{policy} missing on profiles"


def test_profiles_anon_has_no_policies(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute("select oid from pg_roles where rolname = 'anon'")
        anon = cur.fetchone()
        assert anon is not None, "anon role not provisioned by init.sql"
        anon_oid = anon[0]
        cur.execute(
            "select count(*) from pg_policy pol "
            "join pg_class c on c.oid = pol.polrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' "
            "  and c.relname = 'profiles' "
            "  and %s = any(pol.polroles)",
            (anon_oid,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 0, f"anon role must have no profiles policies; found {row[0]}"


def test_profiles_updated_at_trigger(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute("select 1 from pg_proc where proname = 'set_profiles_updated_at'")
        assert cur.fetchone() is not None, "set_profiles_updated_at function missing"
        cur.execute("select 1 from pg_trigger where tgname = 'profiles_set_updated_at'")
        assert cur.fetchone() is not None, "profiles_set_updated_at trigger missing"


# ---------------------------------------------------------------
# Phase 4 Step 5 — conversations + messages + roadmaps
# ---------------------------------------------------------------


def test_conversations_table_exists(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select 1 from information_schema.tables "
            "where table_schema = 'public' and table_name = 'conversations'"
        )
        assert cur.fetchone() is not None, "conversations table missing"


def test_conversations_columns(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            """
            select column_name, data_type
            from information_schema.columns
            where table_schema = 'public' and table_name = 'conversations'
            order by ordinal_position
            """
        )
        rows = {name: dtype for name, dtype in cur.fetchall()}
    for column in ("id", "user_id", "title", "created_at", "updated_at"):
        assert column in rows, f"{column} column missing on conversations"
    assert rows["id"] == "uuid"
    assert rows["user_id"] == "uuid"
    assert rows["title"] == "text"


def test_conversations_user_id_brin_index(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select indexdef from pg_indexes "
            "where schemaname = 'public' and tablename = 'conversations' "
            "and indexname = 'conversations_user_id_updated_at_brin'"
        )
        row = cur.fetchone()
    assert row is not None, "conversations_user_id_updated_at_brin index missing"
    idx_def = row[0]
    assert "USING brin" in idx_def, f"index must use BRIN; got {idx_def}"
    assert "user_id" in idx_def
    assert "updated_at" in idx_def


def test_conversations_user_id_fk_cascade(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            """
            select rc.delete_rule, ccu.table_schema, ccu.table_name, ccu.column_name
            from information_schema.table_constraints tc
            join information_schema.key_column_usage kcu
              on tc.constraint_name = kcu.constraint_name
              and tc.table_schema = kcu.table_schema
            join information_schema.referential_constraints rc
              on tc.constraint_name = rc.constraint_name
            join information_schema.constraint_column_usage ccu
              on rc.unique_constraint_name = ccu.constraint_name
            where tc.table_schema = 'public'
              and tc.table_name = 'conversations'
              and tc.constraint_type = 'FOREIGN KEY'
              and kcu.column_name = 'user_id'
            """
        )
        row = cur.fetchone()
    assert row is not None, "conversations.user_id FK missing"
    delete_rule, ref_schema, ref_table, ref_column = row
    assert delete_rule == "CASCADE"
    assert (ref_schema, ref_table, ref_column) == ("auth", "users", "id")


def test_conversations_authenticated_policies(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select polname from pg_policy pol "
            "join pg_class c on c.oid = pol.polrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relname = 'conversations'"
        )
        names = {row[0] for row in cur.fetchall()}
    for policy in (
        "authenticated_select_own",
        "authenticated_insert_own",
        "authenticated_update_own",
        "authenticated_delete_own",
    ):
        assert policy in names, f"{policy} missing on conversations"


def test_conversations_service_role_policies(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select polname from pg_policy pol "
            "join pg_class c on c.oid = pol.polrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relname = 'conversations'"
        )
        names = {row[0] for row in cur.fetchall()}
    for policy in (
        "service_role_select",
        "service_role_insert",
        "service_role_update",
        "service_role_delete",
    ):
        assert policy in names, f"{policy} missing on conversations"


def test_conversations_anon_has_no_policies(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute("select oid from pg_roles where rolname = 'anon'")
        anon = cur.fetchone()
        assert anon is not None
        anon_oid = anon[0]
        cur.execute(
            "select count(*) from pg_policy pol "
            "join pg_class c on c.oid = pol.polrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' "
            "  and c.relname = 'conversations' "
            "  and %s = any(pol.polroles)",
            (anon_oid,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 0, f"anon role must have no conversations policies; found {row[0]}"


def test_messages_table_exists(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select 1 from information_schema.tables "
            "where table_schema = 'public' and table_name = 'messages'"
        )
        assert cur.fetchone() is not None, "messages table missing"


def test_messages_columns(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            """
            select column_name, data_type
            from information_schema.columns
            where table_schema = 'public' and table_name = 'messages'
            order by ordinal_position
            """
        )
        rows = {name: dtype for name, dtype in cur.fetchall()}
    for column in ("id", "conversation_id", "role", "content", "created_at"):
        assert column in rows, f"{column} column missing on messages"
    assert rows["id"] == "uuid"
    assert rows["conversation_id"] == "uuid"


def test_messages_role_check_constraint(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            """
            select pg_get_constraintdef(oid)
            from pg_constraint
            where conrelid = 'public.messages'::regclass and contype = 'c'
            """
        )
        defs = [row[0] for row in cur.fetchall()]
    assert any("role" in d and "user" in d and "assistant" in d for d in defs), (
        f"messages.role CHECK constraint missing or wrong: {defs}"
    )


def test_messages_btree_index(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select indexdef from pg_indexes "
            "where schemaname = 'public' and tablename = 'messages' "
            "and indexname = 'messages_conversation_id_created_at_btree'"
        )
        row = cur.fetchone()
    assert row is not None, "messages_conversation_id_created_at_btree index missing"
    idx_def = row[0]
    assert "USING btree" in idx_def
    assert "conversation_id" in idx_def
    assert "created_at" in idx_def


def test_messages_conversation_fk_cascade(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            """
            select rc.delete_rule, ccu.table_schema, ccu.table_name, ccu.column_name
            from information_schema.table_constraints tc
            join information_schema.key_column_usage kcu
              on tc.constraint_name = kcu.constraint_name
              and tc.table_schema = kcu.table_schema
            join information_schema.referential_constraints rc
              on tc.constraint_name = rc.constraint_name
            join information_schema.constraint_column_usage ccu
              on rc.unique_constraint_name = ccu.constraint_name
            where tc.table_schema = 'public'
              and tc.table_name = 'messages'
              and tc.constraint_type = 'FOREIGN KEY'
              and kcu.column_name = 'conversation_id'
            """
        )
        row = cur.fetchone()
    assert row is not None, "messages.conversation_id FK missing"
    delete_rule, ref_schema, ref_table, ref_column = row
    assert delete_rule == "CASCADE"
    assert (ref_schema, ref_table, ref_column) == ("public", "conversations", "id")


def test_messages_bump_conversation_trigger(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute("select 1 from pg_proc where proname = 'bump_conversation_updated_at'")
        assert cur.fetchone() is not None, "bump_conversation_updated_at function missing"
        cur.execute(
            "select 1 from pg_trigger where tgname = 'messages_bump_conversation_updated_at'"
        )
        assert cur.fetchone() is not None, "messages_bump_conversation_updated_at trigger missing"


def test_messages_authenticated_policies(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select polname from pg_policy pol "
            "join pg_class c on c.oid = pol.polrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relname = 'messages'"
        )
        names = {row[0] for row in cur.fetchall()}
    for policy in (
        "authenticated_select_own",
        "authenticated_insert_own",
        "authenticated_update_own",
        "authenticated_delete_own",
    ):
        assert policy in names, f"{policy} missing on messages"


def test_messages_anon_has_no_policies(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute("select oid from pg_roles where rolname = 'anon'")
        anon = cur.fetchone()
        assert anon is not None
        anon_oid = anon[0]
        cur.execute(
            "select count(*) from pg_policy pol "
            "join pg_class c on c.oid = pol.polrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' "
            "  and c.relname = 'messages' "
            "  and %s = any(pol.polroles)",
            (anon_oid,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 0, f"anon role must have no messages policies; found {row[0]}"


def test_roadmaps_table_exists(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select 1 from information_schema.tables "
            "where table_schema = 'public' and table_name = 'roadmaps'"
        )
        assert cur.fetchone() is not None, "roadmaps table missing"


def test_roadmaps_columns(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            """
            select column_name, data_type
            from information_schema.columns
            where table_schema = 'public' and table_name = 'roadmaps'
            order by ordinal_position
            """
        )
        rows = {name: dtype for name, dtype in cur.fetchall()}
    for column in ("id", "conversation_id", "user_id", "draft", "generated_at"):
        assert column in rows, f"{column} column missing on roadmaps"
    assert rows["draft"] == "jsonb"


def test_roadmaps_unique_conversation_id(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            """
            select conname, pg_get_constraintdef(oid)
            from pg_constraint
            where conrelid = 'public.roadmaps'::regclass
              and contype = 'u'
            """
        )
        defs = [definition for _, definition in cur.fetchall()]
    assert any("conversation_id" in d for d in defs), (
        f"roadmaps UNIQUE(conversation_id) constraint missing: {defs}"
    )


def test_roadmaps_draft_title_index(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select indexdef from pg_indexes "
            "where schemaname = 'public' and tablename = 'roadmaps' "
            "and indexname = 'roadmaps_draft_title_idx'"
        )
        row = cur.fetchone()
    assert row is not None, "roadmaps_draft_title_idx index missing"
    idx_def = row[0]
    assert "draft" in idx_def and "title" in idx_def, (
        f"roadmaps_draft_title_idx must index draft->>'title'; got {idx_def}"
    )


def test_roadmaps_authenticated_policies(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select polname from pg_policy pol "
            "join pg_class c on c.oid = pol.polrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relname = 'roadmaps'"
        )
        names = {row[0] for row in cur.fetchall()}
    for policy in (
        "authenticated_select_own",
        "authenticated_insert_own",
        "authenticated_update_own",
        "authenticated_delete_own",
    ):
        assert policy in names, f"{policy} missing on roadmaps"


def test_roadmaps_anon_has_no_policies(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute("select oid from pg_roles where rolname = 'anon'")
        anon = cur.fetchone()
        assert anon is not None
        anon_oid = anon[0]
        cur.execute(
            "select count(*) from pg_policy pol "
            "join pg_class c on c.oid = pol.polrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' "
            "  and c.relname = 'roadmaps' "
            "  and %s = any(pol.polroles)",
            (anon_oid,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 0, f"anon role must have no roadmaps policies; found {row[0]}"


# ---------------------------------------------------------------
# Phase 4 Step 6 — audit_log.cache_stats jsonb + profiles
# .frontier_roadmap_override boolean
# ---------------------------------------------------------------


def test_audit_log_cache_stats_column(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select data_type, is_nullable from information_schema.columns "
            "where table_schema = 'public' and table_name = 'audit_log' "
            "and column_name = 'cache_stats'"
        )
        row = cur.fetchone()
    assert row is not None, "audit_log.cache_stats column missing"
    data_type, is_nullable = row
    assert data_type == "jsonb", f"cache_stats must be jsonb, got {data_type}"
    assert is_nullable == "YES", "cache_stats must be nullable (Phase 4 writes Google rows only)"


def test_audit_log_cache_stats_accepts_google_shape(
    db_conn: "psycopg.Connection",
) -> None:
    # Insert + read-back the Google-discriminated variant. The
    # service_role inserts here because RLS would block anon;
    # the test connection is the migrations runner (service_role-
    # equivalent). Verifies the schema accepts the documented
    # shape — the column comment documents the union but Postgres
    # doesn't enforce it, so this row-write test is the closest
    # we get to schema-shape coverage on a jsonb column.
    with db_conn.cursor() as cur:
        cur.execute(
            """
            insert into public.audit_log
              (ts, ip_hash, ua_hash, route, outcome, cache_stats)
            values (
              now(), 'h1', 'h2', '/api/roadmap', 'ok',
              %s::jsonb
            )
            returning cache_stats->>'provider'
            """,
            (
                '{"provider":"google",'
                '"promptTokenCount":4096,'
                '"candidatesTokenCount":512,'
                '"cachedContentTokenCount":3500,'
                '"cachedContentTokenCountUsed":3500}',
            ),
        )
        provider = cur.fetchone()
    db_conn.rollback()
    assert provider is not None and provider[0] == "google"


def test_audit_log_cache_stats_accepts_anthropic_shape(
    db_conn: "psycopg.Connection",
) -> None:
    # The Anthropic variant is documented in the migration column
    # comment for Phase 5 to start writing. Verify Postgres
    # accepts the shape so the Phase 5 PR is a code change, not
    # a migration change.
    with db_conn.cursor() as cur:
        cur.execute(
            """
            insert into public.audit_log
              (ts, ip_hash, ua_hash, route, outcome, cache_stats)
            values (
              now(), 'h1', 'h2', '/api/roadmap', 'ok',
              %s::jsonb
            )
            returning cache_stats->>'provider'
            """,
            (
                '{"provider":"anthropic",'
                '"input_tokens":4096,'
                '"output_tokens":512,'
                '"cache_read_input_tokens":3500,'
                '"cache_creation_input_tokens":0}',
            ),
        )
        provider = cur.fetchone()
    db_conn.rollback()
    assert provider is not None and provider[0] == "anthropic"


def test_profiles_frontier_roadmap_override_column(
    db_conn: "psycopg.Connection",
) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select data_type, is_nullable, column_default "
            "from information_schema.columns "
            "where table_schema = 'public' and table_name = 'profiles' "
            "and column_name = 'frontier_roadmap_override'"
        )
        row = cur.fetchone()
    assert row is not None, "profiles.frontier_roadmap_override column missing"
    data_type, is_nullable, column_default = row
    assert data_type == "boolean", (
        f"frontier_roadmap_override must be boolean, got {data_type}"
    )
    assert is_nullable == "YES", (
        "frontier_roadmap_override must be nullable (tri-state semantics)"
    )
    assert column_default is None, (
        "frontier_roadmap_override default must be NULL "
        "(NULL = honor env var); got "
        f"{column_default!r}"
    )
