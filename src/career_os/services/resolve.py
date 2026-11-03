"""Best-effort free-text -> entity resolution, used by notes.py and update.py.

Never forces a wrong link. Returns (entity_id, confidence) where confidence
is 'High' (explicit id given), 'Medium' (single unambiguous name match),
or (None, None) if nothing resolves cleanly - callers must then fall back
to storing the text unlinked rather than guessing.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Optional


def resolve_role(conn: sqlite3.Connection, text: str) -> tuple[Optional[int], Optional[str]]:
    # Explicit: "role 17" / "role #17"
    m = re.search(r"\brole\s*#?\s*(\d+)\b", text, re.IGNORECASE)
    if m:
        role_id = int(m.group(1))
        row = conn.execute("SELECT id FROM roles WHERE id = ?", (role_id,)).fetchone()
        if row:
            return role_id, "High"

    # Fuzzy: a company name mentioned in the text, with exactly one open role.
    companies = conn.execute("SELECT id, name FROM companies").fetchall()
    matches = []
    lowered = text.lower()
    for c in companies:
        name = c["name"].lower()
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            matches.append(c["id"])

    if not matches:
        return None, None

    # Disambiguate: some portfolio company names collide with common words
    # used to describe a channel (e.g. "LinkedIn" the company vs. "via
    # LinkedIn" the channel). Prefer whichever matched company actually has
    # a tracked role over one that's just sitting in the portfolio list.
    candidates = matches
    if len(matches) > 1:
        with_roles = [
            cid
            for cid in matches
            if conn.execute(
                "SELECT 1 FROM roles WHERE company_id = ? LIMIT 1", (cid,)
            ).fetchone()
        ]
        if len(with_roles) == 1:
            candidates = with_roles
        else:
            return None, None  # still ambiguous, don't guess

    company_id = candidates[0]
    rows = conn.execute(
        """SELECT id FROM roles WHERE company_id = ?
           AND status NOT IN ('rejected','withdrawn','closed')
           ORDER BY updated_at DESC LIMIT 1""",
        (company_id,),
    ).fetchall()
    if not rows:
        rows = conn.execute(
            "SELECT id FROM roles WHERE company_id = ? ORDER BY updated_at DESC LIMIT 1",
            (company_id,),
        ).fetchall()
    if rows:
        return rows[0]["id"], "Medium"

    return None, None


def resolve_contact(conn: sqlite3.Connection, text: str) -> tuple[Optional[int], Optional[str]]:
    contacts = conn.execute("SELECT id, name FROM contacts").fetchall()
    lowered = text.lower()
    matches = [c["id"] for c in contacts if c["name"].lower() in lowered]
    if len(matches) == 1:
        return matches[0], "Medium"
    return None, None
