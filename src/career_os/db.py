"""Database connection + schema init for Career OS.

SQLite only (section 8 of the design spec). One file, no server.
"""
from __future__ import annotations

import re
import sqlite3
import os
from pathlib import Path

# career-os/src/career_os/db.py -> career-os/
CAREER_OS_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = Path(os.environ["CAREER_OS_DB"]) if os.environ.get("CAREER_OS_DB") else CAREER_OS_ROOT / "data" / "career.db"
SCHEMA_PATH = CAREER_OS_ROOT / "schemas" / "schema.sql"


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection with sane defaults. Creates parent dir if needed."""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# v2 columns for databases created before the problem-shape framework.
# SQLite has no ADD COLUMN IF NOT EXISTS, so check pragma table_info first.
# schema.sql carries the same columns for fresh databases.
_V2_COLUMNS = {
    "roles": [
        "problem_shape", "rate_of_change", "interconnectedness",
        "critical_depth_lever", "depth_lever_importance", "judgment_requirement",
        "depth_match", "depth_match_reason", "missing_depth_evidence",
        "judgment_surface_expansion", "specialist_spike_deepening",
        "job_code",
    ],
    "evidence": ["critical_lever"],
    "stories": ["critical_lever"],
}
SCHEMA_VERSION = "5"


def _drop_organizations(conn: sqlite3.Connection) -> None:
    """v5: remove the unused `organizations` table and `roles.organization_id`.

    SQLite cannot drop a column that carries a foreign key, and dropping only the parent table
    would break every insert into roles, so roles is rebuilt without the column (copy, drop,
    rename) inside one transaction. Skipped, never forced, if any organization data exists.
    """
    has_col = any(r["name"] == "organization_id" for r in conn.execute("PRAGMA table_info(roles)"))
    has_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'organizations'").fetchone()
    if not (has_col or has_table):
        return
    if has_table and conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]:
        return
    if has_col and conn.execute("SELECT COUNT(*) FROM roles WHERE organization_id IS NOT NULL").fetchone()[0]:
        return
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        if has_col:
            old_cols = [r["name"] for r in conn.execute("PRAGMA table_info(roles)") if r["name"] != "organization_id"]
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'roles'").fetchone()["sql"]
            sql = re.sub(r"\n[ \t]*organization_id[^\n]*", "", sql, count=1)                       # own-line column
            sql = re.sub(r",\s*organization_id\s+INTEGER\s+REFERENCES\s+organizations\(id\)", "", sql, count=1)  # ALTER-added
            sql = re.sub(r"CREATE TABLE (IF NOT EXISTS )?\"?roles\"?", "CREATE TABLE roles_new", sql, count=1)
            cols = ", ".join(old_cols)
            conn.execute(sql)
            conn.execute(f"INSERT INTO roles_new ({cols}) SELECT {cols} FROM roles")  # noqa: S608 - names from PRAGMA
            conn.execute("DROP TABLE roles")
            conn.execute("ALTER TABLE roles_new RENAME TO roles")
        conn.execute("DROP TABLE IF EXISTS organizations")
        bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise sqlite3.IntegrityError(f"foreign key check failed after removing organizations: {len(bad)} problem(s)")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in _V2_COLUMNS.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}  # noqa: S608 - fixed allowlist
        for col in columns:
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")  # noqa: S608
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (SCHEMA_VERSION,),
    )


def init_db(db_path: Path | str | None = None) -> Path:
    """Create all tables if they don't exist. Idempotent, safe to call every run."""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    conn = get_connection(path)
    try:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)
        _migrate(conn)
        conn.commit()
        _drop_organizations(conn)
        conn.executescript(schema_sql)  # recreate indexes the roles rebuild dropped (idempotent)
        conn.commit()
    finally:
        conn.close()
    return path


def schema_version(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    return row["value"] if row else None
