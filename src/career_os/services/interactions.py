"""Interaction log (touchpoints with a contact)."""
from __future__ import annotations

import sqlite3
from typing import Optional


def log_interaction(
    conn: sqlite3.Connection,
    contact_id: int,
    summary: str,
    *,
    role_id: Optional[int] = None,
    channel: Optional[str] = None,
    direction: Optional[str] = None,
    follow_up: Optional[str] = None,
    raw_source_id: Optional[int] = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO interactions (contact_id, role_id, channel, direction, summary, follow_up, raw_source_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (contact_id, role_id, channel, direction, summary, follow_up, raw_source_id),
    )
    conn.commit()
    return cur.lastrowid


def interactions_for_role(conn: sqlite3.Connection, role_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT i.*, c.name AS contact_name FROM interactions i
           LEFT JOIN contacts c ON c.id = i.contact_id
           WHERE i.role_id = ? ORDER BY i.date DESC""",
        (role_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def interactions_for_contact(conn: sqlite3.Connection, contact_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM interactions WHERE contact_id = ? ORDER BY date DESC", (contact_id,)
    ).fetchall()
    return [dict(r) for r in rows]
