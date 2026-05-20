"""tests/test_audit_log_migration.py

Structural checks on the Phase 3 Step 6 Supabase audit_log migration.
Parses the SQL with sqlparse and asserts the column list, BRIN
index, RLS enable, and the two service_role policies are all
present and in the documented order. Also asserts the migration
filename matches the `^\\d{14}_[a-z_]+\\.sql$` convention.
"""

from __future__ import annotations

import re
from pathlib import Path

import sqlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "infra" / "supabase" / "migrations"
MIGRATION_FILENAME = "20260601000000_audit_log.sql"
MIGRATION_PATH = MIGRATIONS_DIR / MIGRATION_FILENAME

# The columns audit_log declares, in declaration order. Step 6 ships
# all of them; later phases extend the table via additive migrations.
EXPECTED_COLUMNS = [
    "id",
    "ts",
    "ip_hash",
    "ua_hash",
    "route",
    "provider",
    "model",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "outcome",
    "error_class",
]


def _read_sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _statements(sql: str) -> list[str]:
    stripped = sqlparse.format(sql, strip_comments=True)
    return [s.strip() for s in sqlparse.split(stripped) if s.strip()]


def _create_table_column_list(create_table_sql: str) -> list[str]:
    """Extract column names from the `create table ... (...)` body.

    The body is the parenthesized block right after the table name.
    Top-level commas split column definitions; nested parens (e.g.
    the `check (outcome in (...))` constraint) must be skipped.
    """
    # Locate the outermost parens after `create table ...`
    start = create_table_sql.index("(")
    depth = 0
    end = -1
    for i in range(start, len(create_table_sql)):
        ch = create_table_sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    assert end > start, "could not find matching close paren"
    body = create_table_sql[start + 1 : end]

    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in body:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())

    columns: list[str] = []
    for part in parts:
        first_token = part.split()[0].lower()
        # Skip table-level constraints; only column defs make the list.
        if first_token in {"constraint", "check", "primary", "foreign", "unique"}:
            continue
        columns.append(first_token)
    return columns


def test_migration_filename_matches_convention() -> None:
    assert re.match(r"^\d{14}_[a-z_]+\.sql$", MIGRATION_FILENAME), (
        f"migration filename {MIGRATION_FILENAME!r} must match "
        r"^\d{14}_[a-z_]+\.sql$"
    )


def test_migration_file_exists() -> None:
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_create_table_declares_all_columns_in_order() -> None:
    sql = _read_sql()
    statements = _statements(sql)
    create_stmts = [
        s for s in statements if re.match(r"(?i)^\s*create\s+table\b", s)
    ]
    assert len(create_stmts) == 1, (
        f"expected exactly one create-table statement, found {len(create_stmts)}"
    )
    columns = _create_table_column_list(create_stmts[0])
    assert columns == EXPECTED_COLUMNS, (
        f"audit_log columns drifted from documented order.\n"
        f"  expected: {EXPECTED_COLUMNS}\n"
        f"  got:      {columns}"
    )


def test_brin_index_present() -> None:
    sql = _read_sql()
    # BRIN index on ts is the chronological scan optimization
    # documented for the audit_log table.
    assert re.search(
        r"(?is)create\s+index\s+audit_log_ts_brin\s+on\s+public\.audit_log\s+using\s+brin\s*\(\s*ts\s*\)",
        sql,
    ), "expected `create index audit_log_ts_brin on public.audit_log using brin (ts)`"


def test_row_level_security_enabled() -> None:
    sql = _read_sql()
    assert re.search(
        r"(?is)alter\s+table\s+public\.audit_log\s+enable\s+row\s+level\s+security",
        sql,
    ), "expected `alter table public.audit_log enable row level security`"


def test_service_role_policies_present() -> None:
    sql = _read_sql()
    # Two policies, both scoped `to service_role`: insert + select.
    insert_pat = (
        r"(?is)create\s+policy\s+\"service_role_only_insert\"\s+"
        r"on\s+public\.audit_log\s+for\s+insert\s+to\s+service_role"
    )
    select_pat = (
        r"(?is)create\s+policy\s+\"service_role_only_select\"\s+"
        r"on\s+public\.audit_log\s+for\s+select\s+to\s+service_role"
    )
    assert re.search(insert_pat, sql), (
        "missing `service_role_only_insert` policy for `for insert to service_role`"
    )
    assert re.search(select_pat, sql), (
        "missing `service_role_only_select` policy for `for select to service_role`"
    )


def test_outcome_check_constraint_lists_all_outcomes() -> None:
    """The audit-log writer in web/lib/audit.ts allows exactly five
    outcome strings; the DB check constraint must match them or
    inserts will fail at runtime.
    """
    sql = _read_sql()
    required = {
        "ok",
        "rate_limited",
        "burst_dropped",
        "recommender_error",
        "bad_input",
    }
    # Grab everything between `outcome in (` and the matching `)`.
    match = re.search(r"(?is)outcome\s+in\s*\(([^)]+)\)", sql)
    assert match, "could not find `outcome in (...)` check constraint"
    declared = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    assert declared == required, (
        f"outcome check constraint drifted from audit.ts AuditOutcome.\n"
        f"  expected: {sorted(required)}\n"
        f"  got:      {sorted(declared)}"
    )
