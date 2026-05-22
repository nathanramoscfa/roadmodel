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
            # by postgres; CASCADE removes audit_log, indexes, RLS.
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
    assert len(files) >= 2, (
        f"expected ≥ 2 timestamped migrations under {MIGRATIONS_DIR}; "
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
