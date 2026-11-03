"""Human-readable pipeline view (no SQL required from the user)."""
from __future__ import annotations

import sqlite3
from typing import Optional


def get_pipeline(conn: sqlite3.Connection, status: Optional[str] = None) -> list[dict]:
    query = """
        SELECT r.id AS role_id, c.name AS company, c.tier AS company_tier,
               r.title, r.job_code, r.archetype, r.role_tier, r.fit_confidence,
               r.source AS found_via, a.channel AS applied_via, a.date_applied,
               rc.name AS referrer, r.problem_shape, r.depth_match, r.judgment_surface_expansion, r.specialist_spike_deepening,
               a.status AS application_status, a.next_action, a.next_action_date,
               r.updated_at
        FROM roles r
        JOIN companies c ON c.id = r.company_id
        LEFT JOIN applications a ON a.role_id = r.id
        LEFT JOIN contacts rc ON rc.id = a.referral_contact_id
    """
    params: list = []
    if status:
        query += " WHERE a.status = ?"
        params.append(status)
    query += " ORDER BY r.role_tier ASC, r.updated_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def stalled(conn: sqlite3.Connection, days: int = 14) -> list[dict]:
    rows = conn.execute(
        """
        SELECT r.id AS role_id, c.name AS company, r.title, a.status,
               a.next_action_date, r.updated_at
        FROM roles r
        JOIN companies c ON c.id = r.company_id
        LEFT JOIN applications a ON a.role_id = r.id
        WHERE a.status NOT IN ('rejected','withdrawn','closed','offer')
          AND julianday('now') - julianday(r.updated_at) > ?
        ORDER BY r.updated_at ASC
        """,
        (days,),
    ).fetchall()
    return [dict(r) for r in rows]
