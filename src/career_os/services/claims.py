"""Provenance ledger (spec section 15).

Any value that is a model guess rather than a supplied/verified fact must
get a row here. This is what lets us answer "is this a fact or a guess?"
for any field in the system, not just the ones with their own column.
"""
from __future__ import annotations

import sqlite3
from typing import Optional


def record_claim(
    conn: sqlite3.Connection,
    claim_text: str,
    subject_type: str,
    subject_id: int,
    source_type: str,  # 'raw_source' | 'extracted_fact' | 'model_inference' | 'user_confirmed'
    source_path: Optional[str] = None,
    raw_source_id: Optional[int] = None,
    verification_status: Optional[str] = None,
    confidence: Optional[str] = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO claims
           (claim_text, subject_type, subject_id, source_type, source_path,
            raw_source_id, verification_status, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            claim_text,
            subject_type,
            subject_id,
            source_type,
            source_path,
            raw_source_id,
            verification_status,
            confidence,
        ),
    )
    conn.commit()
    return cur.lastrowid


def claims_for(conn: sqlite3.Connection, subject_type: str, subject_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM claims WHERE subject_type = ? AND subject_id = ? ORDER BY created_at",
        (subject_type, subject_id),
    ).fetchall()
    return [dict(r) for r in rows]
