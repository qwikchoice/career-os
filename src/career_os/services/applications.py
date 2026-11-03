"""Application lifecycle, tracked independently from the role record."""
from __future__ import annotations

import sqlite3
from typing import Optional

VALID_STATUSES = [
    "planned", "referral_requested", "referred", "applied", "recruiter_screen",
    "hiring_manager", "interview_loop", "final_round", "offer", "rejected",
    "withdrawn", "closed",
]


def get_or_create_application(conn: sqlite3.Connection, role_id: int) -> int:
    row = conn.execute(
        "SELECT id FROM applications WHERE role_id = ?", (role_id,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO applications (role_id, status) VALUES (?, 'planned')", (role_id,)
    )
    conn.commit()
    return cur.lastrowid


def set_status(
    conn: sqlite3.Connection,
    role_id: int,
    status: str,
    *,
    date_applied: Optional[str] = None,
    channel: Optional[str] = None,
    referral_contact_id: Optional[int] = None,
    next_action: Optional[str] = None,
    next_action_date: Optional[str] = None,
) -> int:
    if status not in VALID_STATUSES:
        raise ValueError(f"Unknown application status: {status!r}")
    app_id = get_or_create_application(conn, role_id)
    fields = ["status = ?", "updated_at = datetime('now')"]
    params: list = [status]
    if date_applied is not None:
        fields.append("date_applied = ?")
        params.append(date_applied)
    if channel is not None:
        fields.append("channel = ?")
        params.append(channel)
    if referral_contact_id is not None:
        fields.append("referral_contact_id = ?")
        params.append(referral_contact_id)
    if next_action is not None:
        fields.append("next_action = ?")
        params.append(next_action)
    if next_action_date is not None:
        fields.append("next_action_date = ?")
        params.append(next_action_date)
    params.append(app_id)
    conn.execute(f"UPDATE applications SET {', '.join(fields)} WHERE id = ?", params)
    conn.execute(
        "UPDATE roles SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, role_id),
    )
    conn.commit()
    return app_id


def set_next_action(conn: sqlite3.Connection, role_id: int, text: Optional[str], date: Optional[str] = None) -> Optional[dict]:
    """Set (or clear with empty text) a role's next action and optional due date (YYYY-MM-DD).

    Status is left as it is. Returns None if the role does not exist.
    """
    if conn.execute("SELECT 1 FROM roles WHERE id = ?", (role_id,)).fetchone() is None:
        return None
    if date:
        from datetime import datetime
        datetime.strptime(date, "%Y-%m-%d")   # raises ValueError on a bad date
    app_id = get_or_create_application(conn, role_id)
    conn.execute(
        "UPDATE applications SET next_action = ?, next_action_date = ?, updated_at = datetime('now') WHERE id = ?",
        (text or None, (date or None) if text else None, app_id),
    )
    conn.commit()
    return get_application(conn, role_id)


def get_application(conn: sqlite3.Connection, role_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM applications WHERE role_id = ?", (role_id,)
    ).fetchone()
    return dict(row) if row else None
