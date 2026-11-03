"""Skill vocabulary + role/evidence linkage (spec section 14)."""
from __future__ import annotations

import sqlite3
from typing import Optional


def get_or_create_skill(
    conn: sqlite3.Connection, name: str, category: Optional[str] = None
) -> int:
    row = conn.execute(
        "SELECT id FROM skills WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO skills (name, category) VALUES (?, ?)", (name, category)
    )
    conn.commit()
    return cur.lastrowid


def link_role_skill(
    conn: sqlite3.Connection, role_id: int, skill_id: int, requirement_level: str = "mentioned"
) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO role_skills (role_id, skill_id, requirement_level)
           VALUES (?, ?, ?)""",
        (role_id, skill_id, requirement_level),
    )
    conn.commit()


def link_evidence_skill(conn: sqlite3.Connection, evidence_id: int, skill_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO evidence_skills (evidence_id, skill_id) VALUES (?, ?)",
        (evidence_id, skill_id),
    )
    conn.commit()


def role_requirements(conn: sqlite3.Connection, role_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT s.id, s.name, s.category, rs.requirement_level
           FROM role_skills rs JOIN skills s ON s.id = rs.skill_id
           WHERE rs.role_id = ? ORDER BY s.name""",
        (role_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def skills_with_evidence(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT DISTINCT skill_id FROM evidence_skills").fetchall()
    return {r["skill_id"] for r in rows}


def evidence_for_skill(conn: sqlite3.Connection, skill_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT e.* FROM evidence e JOIN evidence_skills es ON es.evidence_id = e.id
           WHERE es.skill_id = ?""",
        (skill_id,),
    ).fetchall()
    return [dict(r) for r in rows]
