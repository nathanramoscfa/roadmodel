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

import json
import os
import re
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

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
            cur.execute("drop table if exists public.model_availability cascade")
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
    assert len(files) >= 8, (
        f"expected ≥ 8 timestamped migrations under {MIGRATIONS_DIR}; "
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


def test_profiles_pool_states_defaults_to_unknown(db_conn: "psycopg.Connection") -> None:
    from uuid import uuid4

    user_id = uuid4()
    try:
        with db_conn.cursor() as cur:
            cur.execute("insert into auth.users (id) values (%s)", (user_id,))
            cur.execute(
                "insert into public.profiles (user_id) values (%s) returning pool_states",
                (user_id,),
            )
            assert cur.fetchone() == ([],)
            cur.execute(
                "select data_type, is_nullable from information_schema.columns "
                "where table_schema = 'public' and table_name = 'profiles' "
                "and column_name = 'pool_states'"
            )
            assert cur.fetchone() == ("jsonb", "NO")
    finally:
        db_conn.rollback()


@pytest.mark.parametrize("invalid", [{}, None, "unvalidated text", 42])
def test_profiles_pool_states_rejects_non_array(
    db_conn: "psycopg.Connection", invalid: object
) -> None:
    from uuid import uuid4

    import psycopg
    from psycopg.types.json import Jsonb

    user_id = uuid4()
    try:
        with db_conn.cursor() as cur:
            cur.execute("insert into auth.users (id) values (%s)", (user_id,))
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    "insert into public.profiles (user_id, pool_states) values (%s, %s)",
                    (user_id, Jsonb(invalid)),
                )
    finally:
        db_conn.rollback()


def test_profiles_pool_states_owner_roundtrip_and_isolation(
    db_conn: "psycopg.Connection",
) -> None:
    from uuid import uuid4

    from psycopg.types.json import Jsonb

    own, other = uuid4(), uuid4()
    observations = [
        {
            "pool": "codex:weekly",
            "platform_id": "codex-cli",
            "source": "codex",
            "state": "tight",
            "used_percent": 88,
            "observed_at": 1_800_000_000,
            "resets_at": 1_800_100_000,
            "window_minutes": 10080,
        }
    ]
    try:
        with db_conn.cursor() as cur:
            for user_id in (own, other):
                cur.execute("insert into auth.users (id) values (%s)", (user_id,))
                cur.execute("insert into public.profiles (user_id) values (%s)", (user_id,))
            # Bootstrap grants precede migrations; never restore a broad write
            # grant here that would conceal broken column protections.
            cur.execute("select set_config('request.jwt.claim.sub', %s, true)", (str(own),))
            cur.execute("set local role authenticated")
            cur.execute(
                "update public.profiles set pool_states = %s where user_id = %s "
                "returning pool_states, budget_priority",
                (Jsonb(observations), own),
            )
            assert cur.fetchone() == (observations, "balanced")
            cur.execute("select pool_states from public.profiles where user_id = %s", (own,))
            assert cur.fetchone() == (observations,)
            cur.execute("select pool_states from public.profiles where user_id = %s", (other,))
            assert cur.fetchone() is None
            cur.execute(
                "update public.profiles set pool_states = %s where user_id = %s",
                (Jsonb(observations), other),
            )
            assert cur.rowcount == 0
            cur.execute("set local role anon")
            cur.execute("select pool_states from public.profiles")
            assert cur.fetchall() == []
            with _rejected(db_conn, "42501"):
                cur.execute("update public.profiles set pool_states = '[]'::jsonb")
    finally:
        db_conn.rollback()


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
    assert data_type == "boolean", f"frontier_roadmap_override must be boolean, got {data_type}"
    assert is_nullable == "YES", "frontier_roadmap_override must be nullable (tri-state semantics)"
    assert column_default is None, (
        "frontier_roadmap_override default must be NULL "
        "(NULL = honor env var); got "
        f"{column_default!r}"
    )


# ---------------------------------------------------------------
# Phase 4 Step 7 — audit_log.latency_ms jsonb
# ---------------------------------------------------------------


def test_audit_log_latency_ms_column(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select data_type, is_nullable from information_schema.columns "
            "where table_schema = 'public' and table_name = 'audit_log' "
            "and column_name = 'latency_ms'"
        )
        row = cur.fetchone()
    assert row is not None, "audit_log.latency_ms column missing"
    data_type, is_nullable = row
    assert data_type == "jsonb", f"latency_ms must be jsonb, got {data_type}"
    assert is_nullable == "YES", (
        "latency_ms must be nullable — non-instrumented routes (Phase 4 "
        "/api/roadmap, gate/auth audit rows) write rows with this column null"
    )


def test_audit_log_latency_ms_accepts_documented_shape(
    db_conn: "psycopg.Connection",
) -> None:
    # Mirrors the per-request span bag the web tier and FastAPI
    # service emit. Eight keys, all integer ms. The migration's
    # column comment documents this shape; Postgres doesn't
    # enforce it on a jsonb column, so this row-write test is the
    # closest we get to schema-shape coverage.
    with db_conn.cursor() as cur:
        cur.execute(
            """
            insert into public.audit_log
              (ts, ip_hash, ua_hash, route, outcome, latency_ms)
            values (
              now(), 'h1', 'h2', '/api/recommend', 'ok',
              %s::jsonb
            )
            returning
              (latency_ms->>'total_ms')::int,
              (latency_ms->>'dispatch_ms')::int,
              (latency_ms->>'scoring_ms')::int,
              (latency_ms->>'provider_ms')::int,
              (latency_ms->>'service_scoring_ms')::int,
              (latency_ms->>'service_provider_ms')::int,
              (latency_ms->>'render_ms')::int,
              (latency_ms->>'cold_start_ms')::int
            """,
            (
                '{"total_ms":4500,'
                '"dispatch_ms":3,'
                '"scoring_ms":1,'
                '"provider_ms":4490,'
                '"service_scoring_ms":12,'
                '"service_provider_ms":4470,'
                '"render_ms":6,'
                '"cold_start_ms":0}',
            ),
        )
        row = cur.fetchone()
    db_conn.rollback()
    assert row is not None
    assert row == (4500, 3, 1, 4490, 12, 4470, 6, 0)


# ---------------------------------------------------------------
# Phase 4.11 Step 1 — audit_log.funded_by and the full outcome set
# ---------------------------------------------------------------


def test_audit_log_funded_by_column(db_conn: "psycopg.Connection") -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "select data_type, is_nullable from information_schema.columns "
            "where table_schema = 'public' and table_name = 'audit_log' "
            "and column_name = 'funded_by'"
        )
        row = cur.fetchone()
    assert row == ("text", "YES"), (
        "funded_by must be nullable text — refused requests and history carry null"
    )


def _insert_audit(db_conn: "psycopg.Connection", outcome: str, funded_by: str | None) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "insert into public.audit_log (ts, ip_hash, ua_hash, route, outcome, funded_by) "
            "values (now(), 'h1', 'h2', '/api/recommend', %s, %s)",
            (outcome, funded_by),
        )


@pytest.mark.parametrize("funded_by", ["operator", "visitor", "keyless", None])
def test_audit_log_funded_by_accepts_the_lanes(
    db_conn: "psycopg.Connection", funded_by: str | None
) -> None:
    try:
        _insert_audit(db_conn, "ok", funded_by)
    finally:
        db_conn.rollback()


def test_audit_log_funded_by_rejects_anything_else(db_conn: "psycopg.Connection") -> None:
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_audit(db_conn, "ok", "stranger")
    db_conn.rollback()


@pytest.mark.parametrize(
    "outcome",
    [
        "roadmap_monthly_cap",
        "roadmap_error",
        "unauthorized",
        "daily_cost_cap",
        "bypassed_rate_limit",
        "funding_required",
        "visitor_key_rejected",
        "visitor_quota",
        "provider_error",
    ],
)
def test_audit_log_outcome_accepts_every_writer_outcome(
    db_conn: "psycopg.Connection", outcome: str
) -> None:
    """The outcomes the original five-value CHECK rejected, and Phase 4.11's."""
    try:
        _insert_audit(db_conn, outcome, None)
    finally:
        db_conn.rollback()


# Owner write permissions and bounded profile/content contracts.
_EDITABLE_PROFILE_COLUMNS = {
    "user_id",
    "subscriptions",
    "budget_priority",
    "allowed_jurisdictions",
    "onboarded_at",
    "api_providers",
    "consumption_headroom",
    "pool_states",
}
_OLD_TIMESTAMP = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _pool(
    pool: str = "codex:weekly", *, minutes: int = 10080, reset: int | None = 1700003600
) -> dict[str, Any]:
    source = pool.split(":", 1)[0]
    platform = {
        "claude": "claude-code",
        "codex": "codex-cli",
        "antigravity": "antigravity",
        "openrouter": "openrouter",
    }[source]
    return {
        "pool": pool,
        "source": source,
        "platform_id": platform,
        "state": "headroom",
        "observed_at": 1700000000,
        "resets_at": reset,
        "used_percent": 0,
        "window_minutes": minutes,
    }


@pytest.fixture
def hardening_users(
    db_conn: "psycopg.Connection",
) -> Generator[tuple["psycopg.Connection", UUID, UUID, UUID], None, None]:
    """Seed only synthetic identities; every test, including DCL, rolls back."""
    own, other, spare = uuid4(), uuid4(), uuid4()
    try:
        for user_id in (own, other, spare):
            db_conn.execute("insert into auth.users(id) values (%s)", (user_id,))
        yield db_conn, own, other, spare
    finally:
        db_conn.rollback()


def _role(conn: "psycopg.Connection", role: str, user_id: UUID | None = None) -> None:
    from psycopg import sql

    conn.execute(
        "select set_config('request.jwt.claim.sub', %s, true)", (str(user_id) if user_id else "",)
    )
    conn.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))


def _seed_profile(conn: "psycopg.Connection", user_id: UUID) -> None:
    conn.execute(
        "insert into public.profiles(user_id,created_at,updated_at) values (%s,%s,%s)",
        (user_id, _OLD_TIMESTAMP, _OLD_TIMESTAMP),
    )


def _returned_profile(cur: Any) -> dict[str, Any]:
    row = cur.fetchone()
    assert row is not None
    return dict(zip((column.name for column in cur.description), row, strict=True))


def _sdk_upsert(
    conn: "psycopg.Connection",
    user_id: UUID,
    *,
    budget: str = "balanced",
    pools: list[dict[str, Any]] | None = None,
    protected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Installed SDK capture: payload keys are insert AND conflict-update columns.

    Object upsert sends select=*, resolution=merge-duplicates; no columns query.
    Omitted pool_states stays out of both insert and update column sets.
    """
    from psycopg import sql
    from psycopg.types.json import Jsonb

    payload: dict[str, Any] = {
        "user_id": user_id,
        "subscriptions": ["claude-max"],
        "api_providers": ["openai"],
        "budget_priority": budget,
        "consumption_headroom": "auto",
        "allowed_jurisdictions": ["us", "eu"],
        "onboarded_at": _OLD_TIMESTAMP,
    }
    if pools is not None:
        payload["pool_states"] = Jsonb(pools)
    payload.update(protected or {})
    names = list(payload)
    statement = sql.SQL(
        "insert into public.profiles ({columns}) values ({values}) "
        "on conflict(user_id) do update set {updates} returning *"
    ).format(
        columns=sql.SQL(",").join(map(sql.Identifier, names)),
        values=sql.SQL(",").join(sql.Placeholder() for _ in names),
        updates=sql.SQL(",").join(
            sql.SQL("{column}=excluded.{column}").format(column=sql.Identifier(name))
            for name in names
        ),
    )
    return _returned_profile(conn.execute(statement, list(payload.values())))


@contextmanager
def _rejected(conn: "psycopg.Connection", sqlstate: str) -> Generator[None, None, None]:
    import psycopg

    # A savepoint restores the usable outer transaction after the failed write.
    with pytest.raises(psycopg.Error) as error, conn.transaction():
        yield
    assert error.value.sqlstate == sqlstate


def test_hardened_sdk_profile_create_conflict_and_omitted_fields(hardening_users: Any) -> None:
    conn, own, _, _ = hardening_users
    _role(conn, "authenticated", own)
    first = _sdk_upsert(conn, own, pools=[_pool()])
    assert first["pool_states"] == [_pool()]
    assert first["subscriptions"] == ["claude-max"]
    assert first["api_providers"] == ["openai"]
    assert first["budget_priority"] == "balanced"
    assert first["consumption_headroom"] == "auto"
    assert first["allowed_jurisdictions"] == ["us", "eu"]
    assert first["onboarded_at"] == _OLD_TIMESTAMP
    assert first["user_id"] == own
    assert first["frontier_roadmap_override"] is None
    assert isinstance(first["created_at"], datetime)
    assert isinstance(first["updated_at"], datetime)
    credits = _pool("openrouter:credits", minutes=0, reset=None)
    updated = _sdk_upsert(conn, own, pools=[credits], budget="cheap")
    assert updated["pool_states"] == [credits]
    assert updated["budget_priority"] == "cheap"
    assert updated["created_at"] == first["created_at"]
    # Server-owned state must survive the same 7-column settings upsert used by
    # the route when pool_states is omitted.
    conn.execute("reset role")
    conn.execute(
        "update public.profiles set frontier_roadmap_override=true where user_id=%s", (own,)
    )
    _role(conn, "authenticated", own)
    partial = _sdk_upsert(conn, own, budget="best")
    assert partial["pool_states"] == [credits]
    assert partial["frontier_roadmap_override"] is True
    assert partial["created_at"] == first["created_at"]


@pytest.mark.parametrize(
    "column,value",
    [
        ("created_at", _OLD_TIMESTAMP),
        ("updated_at", _OLD_TIMESTAMP),
        ("frontier_roadmap_override", True),
    ],
)
@pytest.mark.parametrize("operation", ["new_upsert", "existing_update"])
def test_hardened_protected_profile_writes_rejected(
    hardening_users: Any, column: str, value: Any, operation: str
) -> None:
    from psycopg import sql

    conn, own, _, _ = hardening_users
    if operation == "existing_update":
        _seed_profile(conn, own)
    _role(conn, "authenticated", own)
    with _rejected(conn, "42501"):
        if operation == "new_upsert":
            _sdk_upsert(conn, own, protected={column: value})
        else:
            conn.execute(
                sql.SQL("update public.profiles set {}=%s where user_id=%s returning *").format(
                    sql.Identifier(column)
                ),
                (value, own),
            )
    assert conn.execute("select count(*) from public.profiles").fetchone() == (
        0 if operation == "new_upsert" else 1,
    )


def test_hardened_profile_owner_isolation_and_identity_reassignment(hardening_users: Any) -> None:
    conn, own, other, spare = hardening_users
    for user_id in (own, other):
        _seed_profile(conn, user_id)
    _role(conn, "authenticated", own)
    assert (
        conn.execute("select * from public.profiles where user_id=%s", (other,)).fetchone() is None
    )
    assert (
        conn.execute(
            "update public.profiles set budget_priority='best' where user_id=%s returning *",
            (other,),
        ).fetchone()
        is None
    )
    with _rejected(conn, "42501"):
        conn.execute("update public.profiles set user_id=%s where user_id=%s", (spare, own))
    with _rejected(conn, "42501"):
        _sdk_upsert(conn, other)
    assert conn.execute("select user_id from public.profiles").fetchone() == (own,)
    _role(conn, "anon")
    assert conn.execute("select * from public.profiles").fetchall() == []
    with _rejected(conn, "42501"):
        conn.execute("update public.profiles set pool_states='[]'::jsonb")


def test_hardened_roadmap_parent_ownership_insert_update_and_isolation(
    hardening_users: Any,
) -> None:
    conn, own, other, _ = hardening_users
    own_a, own_b, foreign_a, foreign_b = (uuid4() for _ in range(4))
    for conversation, user in [(own_a, own), (own_b, own), (foreign_a, other), (foreign_b, other)]:
        conn.execute(
            "insert into public.conversations(id,user_id) values (%s,%s)", (conversation, user)
        )
    foreign_roadmap = conn.execute(
        "insert into public.roadmaps(conversation_id,user_id,draft) values (%s,%s,'{}') returning id",
        (foreign_b, other),
    ).fetchone()[0]
    _role(conn, "authenticated", own)
    with _rejected(conn, "42501"):
        conn.execute(
            "insert into public.roadmaps(conversation_id,user_id,draft) values (%s,%s,'{}')",
            (foreign_a, own),
        )
    own_roadmap = conn.execute(
        "insert into public.roadmaps(conversation_id,user_id,draft) values (%s,%s,'{}') returning id",
        (own_a, own),
    ).fetchone()[0]
    assert conn.execute(
        "update public.roadmaps set conversation_id=%s where id=%s returning id",
        (own_b, own_roadmap),
    ).fetchone() == (own_roadmap,)
    with _rejected(conn, "42501"):
        conn.execute(
            "update public.roadmaps set conversation_id=%s where id=%s", (foreign_a, own_roadmap)
        )
    assert (
        conn.execute(
            "update public.roadmaps set draft='{}' where id=%s returning id", (foreign_roadmap,)
        ).fetchone()
        is None
    )
    assert (
        conn.execute("select id from public.roadmaps where id=%s", (foreign_roadmap,)).fetchone()
        is None
    )


def test_hardened_pool_cas_rejects_stale_token(hardening_users: Any) -> None:
    from psycopg.types.json import Jsonb

    conn, own, _, _ = hardening_users
    _seed_profile(conn, own)  # Old timestamp differs from now() even within one transaction.
    _role(conn, "authenticated", own)
    query = (
        "update public.profiles set pool_states=%s where user_id=%s and updated_at=%s returning *"
    )
    fresh = _returned_profile(conn.execute(query, (Jsonb([_pool()]), own, _OLD_TIMESTAMP)))
    assert fresh["updated_at"] != _OLD_TIMESTAMP
    assert conn.execute(query, (Jsonb([]), own, _OLD_TIMESTAMP)).fetchone() is None
    assert conn.execute("select pool_states from public.profiles").fetchone() == ([_pool()],)
    current = _returned_profile(conn.execute(query, (Jsonb([]), own, fresh["updated_at"])))
    assert current["pool_states"] == []


_VALID_POOL_FORMS = [
    pytest.param(_pool("claude:weekly"), id="claude-weekly"),
    pytest.param(_pool("claude:5h", minutes=300, reset=1700000300), id="claude-5h"),
    pytest.param(_pool(), id="codex-weekly"),
    pytest.param(_pool("codex:5h", minutes=300, reset=1700000300), id="codex-5h"),
    pytest.param(_pool("antigravity:all", minutes=300, reset=None), id="antigravity-5h-idle"),
    pytest.param(
        _pool("antigravity:all", minutes=10080, reset=1700003600), id="antigravity-weekly"
    ),
    pytest.param(_pool("openrouter:credits", minutes=0, reset=None), id="openrouter-credits"),
]


@pytest.mark.parametrize("observation", _VALID_POOL_FORMS)
def test_hardened_valid_pool_roundtrip(hardening_users: Any, observation: dict[str, Any]) -> None:
    from psycopg.types.json import Jsonb

    conn, own, _, _ = hardening_users
    _seed_profile(conn, own)
    _role(conn, "authenticated", own)
    row = _returned_profile(
        conn.execute(
            "update public.profiles set pool_states=%s where user_id=%s returning *",
            (Jsonb([observation]), own),
        )
    )
    assert row["pool_states"] == [observation]
    omitted = {k: v for k, v in observation.items() if k not in {"source", "platform_id"}}
    assert conn.execute(
        "update public.profiles set pool_states=%s where user_id=%s returning pool_states",
        (Jsonb([omitted]), own),
    ).fetchone() == ([omitted],)


def _invalid_pool_cases() -> list[Any]:
    base = _pool()
    cases = {
        "null-element": [None],
        "nested-element": [[]],
        "missing-reset": [{k: v for k, v in base.items() if k != "resets_at"}],
        "null-source": [dict(base, source=None)],
        "null-platform": [dict(base, platform_id=None)],
        "boolean-number": [dict(base, observed_at=True)],
        "string-number": [dict(base, used_percent="1")],
        "null-number": [dict(base, used_percent=None)],
        "unknown-field": [dict(base, unexpected="synthetic")],
        "unknown-pool": [dict(base, pool="unknown:weekly")],
        "unknown-state": [dict(base, state="unknown")],
        "wrong-origin": [dict(base, source="claude")],
        "wrong-window": [dict(base, window_minutes=300)],
        "reset-not-later": [dict(base, resets_at=base["observed_at"])],
        "reset-too-late": [dict(base, resets_at=base["observed_at"] + 10080 * 60 + 61)],
        "duplicate-pool": [base, base],
        "seven-rows": [base] * 7,
        "subscription-null-reset": [dict(base, resets_at=None)],
        "used-antigravity-null-reset": [
            dict(_pool("antigravity:all", minutes=300, reset=None), used_percent=1)
        ],
        "credits-non-null-reset": [_pool("openrouter:credits", minutes=0, reset=1700000300)],
    }
    result = [pytest.param(json.dumps(value), id=name) for name, value in cases.items()]
    credits = json.dumps([_pool("openrouter:credits", minutes=0, reset=None)])
    result += [
        pytest.param(
            credits.replace('"observed_at": 1700000000', '"observed_at": 1e400'),
            id="float-overflow",
        ),
        pytest.param(
            credits.replace('"observed_at": 1700000000', '"observed_at": 1e-1000'),
            id="float-underflow",
        ),
        pytest.param(
            json.dumps([base]).replace(
                '"resets_at": 1700003600', '"resets_at": 1700000000.0000000001'
            ),
            id="float-collapse",
        ),
    ]
    result.append(
        pytest.param(
            credits.replace('"used_percent": 0', '"used_percent": 0.' + "0" * 8200 + "1"),
            id="oversized-number",
        )
    )
    return result


@pytest.mark.parametrize("payload", _invalid_pool_cases())
def test_hardened_invalid_pool_owner_write_rejected(hardening_users: Any, payload: str) -> None:
    conn, own, _, _ = hardening_users
    _seed_profile(conn, own)
    _role(conn, "authenticated", own)
    with _rejected(conn, "23514"):
        conn.execute(
            "update public.profiles set pool_states=%s::jsonb where user_id=%s", (payload, own)
        )
    assert conn.execute("select pool_states from public.profiles").fetchone() == ([],)


@pytest.mark.parametrize("column", ["subscriptions", "api_providers"])
@pytest.mark.parametrize(
    "value",
    [
        pytest.param([None], id="null-element"),
        pytest.param([["valid"]], id="nested"),
        pytest.param([""], id="empty-id"),
        pytest.param(["x" * 101], id="long-id"),
        pytest.param(["bad id"], id="non-identifier"),
        pytest.param(["valid"] * 65, id="65-items"),
    ],
)
def test_hardened_identifier_array_owner_write_rejected(
    hardening_users: Any, column: str, value: Any
) -> None:
    from psycopg import sql

    conn, own, _, _ = hardening_users
    _seed_profile(conn, own)
    _role(conn, "authenticated", own)
    with _rejected(conn, "23514"):
        conn.execute(
            sql.SQL("update public.profiles set {}=%s where user_id=%s").format(
                sql.Identifier(column)
            ),
            (value, own),
        )


@pytest.mark.parametrize(
    "value",
    [
        pytest.param([None], id="null-element"),
        pytest.param([["us"]], id="nested"),
        pytest.param([], id="empty"),
        pytest.param(["us"] * 11, id="11-items"),
        pytest.param(["invalid"], id="unknown"),
    ],
)
def test_hardened_jurisdiction_array_owner_write_rejected(hardening_users: Any, value: Any) -> None:
    conn, own, _, _ = hardening_users
    _seed_profile(conn, own)
    _role(conn, "authenticated", own)
    with _rejected(conn, "23514"):
        conn.execute(
            "update public.profiles set allowed_jurisdictions=%s where user_id=%s", (value, own)
        )


def test_hardened_profile_array_valid_limits_and_null_helpers(hardening_users: Any) -> None:
    conn, own, _, _ = hardening_users
    _seed_profile(conn, own)
    _role(conn, "authenticated", own)
    values = ["a" * 100] * 64
    jurisdictions = ["us", "eu", "uk", "ca", "au", "jp", "kr", "cn", "ru", "unknown"]
    row = conn.execute(
        "update public.profiles set subscriptions=%s,api_providers=%s,allowed_jurisdictions=%s "
        "where user_id=%s returning subscriptions,api_providers,allowed_jurisdictions",
        (values, values, jurisdictions, own),
    ).fetchone()
    assert row == (values, values, jurisdictions)
    assert conn.execute(
        "update public.profiles set subscriptions='{}',api_providers='{}' "
        "where user_id=%s returning subscriptions,api_providers",
        (own,),
    ).fetchone() == ([], [])
    assert conn.execute(
        "select public.valid_pool_states(null::jsonb),public.valid_profile_ids(null::text[]),"
        "public.valid_profile_jurisdictions(null::text[])"
    ).fetchone() == (False, False, False)


@pytest.mark.parametrize(
    "column", ["subscriptions", "api_providers", "allowed_jurisdictions", "pool_states"]
)
def test_hardened_profile_null_column_rejected(hardening_users: Any, column: str) -> None:
    from psycopg import sql

    conn, own, _, _ = hardening_users
    _seed_profile(conn, own)
    _role(conn, "authenticated", own)
    with _rejected(conn, "23502"):
        conn.execute(
            sql.SQL("update public.profiles set {}=null where user_id=%s").format(
                sql.Identifier(column)
            ),
            (own,),
        )


def test_hardened_content_bounds_accept_boundary_and_reject_above(hardening_users: Any) -> None:
    from psycopg.types.json import Jsonb

    conn, own, _, _ = hardening_users
    _role(conn, "authenticated", own)
    conversation = conn.execute(
        "insert into public.conversations(user_id,title) values (%s,%s) returning id",
        (own, "é" * 1000),
    ).fetchone()[0]
    with _rejected(conn, "23514"):
        conn.execute(
            "update public.conversations set title=%s where id=%s", ("é" * 1001, conversation)
        )
    # UTF-8 bytes, not character count, govern message content.
    message = conn.execute(
        "insert into public.messages(conversation_id,role,content) values (%s,'user',%s) returning id",
        (conversation, "é" * (1048576 // 2)),
    ).fetchone()[0]
    with _rejected(conn, "23514"):
        conn.execute("update public.messages set content=content || 'é' where id=%s", (message,))
    draft = {"x": "a" * (1048576 - len(json.dumps({"x": ""})))}
    roadmap = conn.execute(
        "insert into public.roadmaps(conversation_id,user_id,draft) values (%s,%s,%s) returning id",
        (conversation, own, Jsonb(draft)),
    ).fetchone()[0]
    assert conn.execute(
        "select octet_length(draft::text) from public.roadmaps where id=%s", (roadmap,)
    ).fetchone() == (1048576,)
    with _rejected(conn, "23514"):
        conn.execute(
            "update public.roadmaps set draft=%s where id=%s",
            (Jsonb({"x": draft["x"] + "a"}), roadmap),
        )
    with _rejected(conn, "23514"):
        conn.execute("update public.roadmaps set draft='[]'::jsonb where id=%s", (roadmap,))


def test_hardened_effective_profile_grants(hardening_users: Any) -> None:
    conn, _, _, _ = hardening_users
    names = [
        row[0]
        for row in conn.execute(
            "select attname from pg_attribute where attrelid='public.profiles'::regclass "
            "and attnum>0 and not attisdropped"
        ).fetchall()
    ]
    for column in names:
        for privilege in ("INSERT", "UPDATE"):
            actual = conn.execute(
                "select has_column_privilege('authenticated','public.profiles',%s,%s)",
                (column, privilege),
            ).fetchone()[0]
            assert actual is (column in _EDITABLE_PROFILE_COLUMNS)
            assert conn.execute(
                "select has_column_privilege('anon','public.profiles',%s,%s)", (column, privilege)
            ).fetchone() == (False,)
        assert conn.execute(
            "select has_column_privilege('authenticated','public.profiles',%s,'SELECT')", (column,)
        ).fetchone() == (True,)
    assert conn.execute(
        "select has_table_privilege('authenticated','public.profiles','INSERT'),"
        "has_table_privilege('authenticated','public.profiles','UPDATE')"
    ).fetchone() == (False, False)


def test_hardened_function_configuration_and_validator_permissions(hardening_users: Any) -> None:
    conn, _, _, _ = hardening_users
    rows = conn.execute(
        "select p.proname,p.prosecdef,p.provolatile,p.proconfig,"
        "has_function_privilege('anon',p.oid,'EXECUTE'),"
        "has_function_privilege('authenticated',p.oid,'EXECUTE'),"
        "has_function_privilege('service_role',p.oid,'EXECUTE') "
        "from pg_proc p join pg_namespace n on n.oid=p.pronamespace "
        "where n.nspname='public' and p.proname in ('valid_profile_ids','valid_profile_jurisdictions','valid_pool_states',"
        "'set_profiles_updated_at','bump_conversation_updated_at')"
    ).fetchall()
    assert {r[0] for r in rows} == {
        "valid_profile_ids",
        "valid_profile_jurisdictions",
        "valid_pool_states",
        "set_profiles_updated_at",
        "bump_conversation_updated_at",
    }
    for name, definer, volatility, config, anon, authenticated, service in rows:
        assert definer is False
        path = next(
            (item.split("=", 1)[1] for item in config or [] if item.startswith("search_path=")),
            None,
        )
        if name.startswith("valid_"):
            assert volatility == "i"
            assert path == "pg_catalog"
            assert (anon, authenticated, service) == (False, True, True)
        else:
            assert path in ("", '""')


def test_hardened_service_role_preserves_server_profile_writes(hardening_users: Any) -> None:
    conn, own, _, _ = hardening_users
    _role(conn, "service_role")
    result = _sdk_upsert(
        conn,
        own,
        pools=[_pool()],
        protected={
            "created_at": _OLD_TIMESTAMP,
            "updated_at": _OLD_TIMESTAMP,
            "frontier_roadmap_override": True,
        },
    )
    assert result["created_at"] == _OLD_TIMESTAMP
    assert result["frontier_roadmap_override"] is True
