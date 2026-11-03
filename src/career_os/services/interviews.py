"""Interviews + qualitative interview signals (spec section 11)."""
from __future__ import annotations

import sqlite3
from typing import Optional

VALID_SIGNALS = ("Strong", "Mixed", "Weak", "Unknown")
SIGNAL_DIMENSIONS = (
    "technical_ownership", "metrics", "system_design", "coding",
    "product_judgment", "leadership", "communication",
)


def add_interview(
    conn: sqlite3.Connection,
    role_id: int,
    *,
    stage: Optional[str] = None,
    interviewer_contact_id: Optional[int] = None,
    date: Optional[str] = None,
    notes: Optional[str] = None,
    outcome: Optional[str] = None,
    raw_source_id: Optional[int] = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO interviews (role_id, stage, interviewer_contact_id, date, notes, outcome, raw_source_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (role_id, stage, interviewer_contact_id, date, notes, outcome, raw_source_id),
    )
    conn.commit()
    return cur.lastrowid


def add_signal(
    conn: sqlite3.Connection,
    interview_id: int,
    dimension: str,
    signal: str,
    *,
    root_cause: Optional[str] = None,
    repair: Optional[str] = None,
    retest: Optional[str] = None,
) -> int:
    if signal not in VALID_SIGNALS:
        raise ValueError(f"signal must be one of {VALID_SIGNALS}")
    cur = conn.execute(
        """INSERT INTO interview_signals (interview_id, dimension, signal, root_cause, repair, retest)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (interview_id, dimension, signal, root_cause, repair, retest),
    )
    conn.commit()
    return cur.lastrowid


def interviews_for_role(conn: sqlite3.Connection, role_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM interviews WHERE role_id = ? ORDER BY date DESC", (role_id,)
    ).fetchall()
    result = []
    for r in rows:
        iv = dict(r)
        iv["signals"] = [
            dict(s)
            for s in conn.execute(
                "SELECT * FROM interview_signals WHERE interview_id = ?", (iv["id"],)
            ).fetchall()
        ]
        result.append(iv)
    return result


def recent_weak_signals(conn: sqlite3.Connection, limit: int = 5) -> list[dict]:
    rows = conn.execute(
        """SELECT isg.*, iv.role_id, r.title, c.name AS company_name
           FROM interview_signals isg
           JOIN interviews iv ON iv.id = isg.interview_id
           JOIN roles r ON r.id = iv.role_id
           JOIN companies c ON c.id = r.company_id
           WHERE isg.signal IN ('Weak','Mixed')
           ORDER BY isg.created_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
