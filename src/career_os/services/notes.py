"""Free-form notes (`add-note`). Preserve raw text always; link only when
confident, per spec section 26 ("If uncertain, preserve it without forcing
a bad relationship.").
"""
from __future__ import annotations

import sqlite3

from career_os.services import resolve
from career_os.services import sources as sources_svc


def add_note(conn: sqlite3.Connection, text: str) -> dict:
    src = sources_svc.create_raw_source(conn, source_type="note", content=text)

    role_id, role_conf = resolve.resolve_role(conn, text)
    contact_id, contact_conf = resolve.resolve_contact(conn, text)

    linked_type, linked_id, linked_conf = None, None, None
    if role_id:
        linked_type, linked_id, linked_conf = "role", role_id, role_conf
    elif contact_id:
        linked_type, linked_id, linked_conf = "contact", contact_id, contact_conf

    cur = conn.execute(
        """INSERT INTO notes_inbox (raw_text, linked_entity_type, linked_entity_id, linked_confidence, raw_source_id)
           VALUES (?, ?, ?, ?, ?)""",
        (text, linked_type, linked_id, linked_conf, src["id"]),
    )
    conn.commit()
    return {
        "note_id": cur.lastrowid,
        "raw_source_duplicate": src["duplicate"],
        "linked_entity_type": linked_type,
        "linked_entity_id": linked_id,
        "linked_confidence": linked_conf,
    }
