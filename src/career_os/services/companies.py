"""Company lookups."""
from __future__ import annotations

import sqlite3
from typing import Optional


def get_or_create_company(
    conn: sqlite3.Connection, name: str, tier: Optional[str] = None
) -> int:
    row = conn.execute(
        "SELECT id, tier FROM companies WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row:
        if tier and not row["tier"]:
            conn.execute(
                "UPDATE companies SET tier = ?, updated_at = datetime('now') WHERE id = ?",
                (tier, row["id"]),
            )
            conn.commit()
        return row["id"]
    cur = conn.execute(
        "INSERT INTO companies (name, tier) VALUES (?, ?)", (name, tier)
    )
    conn.commit()
    return cur.lastrowid


def list_companies(conn: sqlite3.Connection, tier: Optional[str] = None) -> list[dict]:
    if tier:
        rows = conn.execute(
            "SELECT * FROM companies WHERE tier = ? ORDER BY name", (tier,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM companies ORDER BY tier, name").fetchall()
    return [dict(r) for r in rows]
