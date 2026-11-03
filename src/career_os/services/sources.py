"""Raw source retention (spec sections 15/16/17).

Every ingested thing keeps its original form, forever. We never store only
the extracted fields. Dedup is by content hash, never by silent delete -
a duplicate is flagged and the existing raw_source id is returned.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

CAREER_OS_ROOT = Path(__file__).resolve().parents[3]
INBOX_ROOT = CAREER_OS_ROOT / "inbox"

INBOX_SUBDIRS = {
    "job_posting": "jobs",
    "recruiter_message": "recruiter_messages",
    "interview_notes": "interviews",
    "note": "notes",
}


def _hash_text(text: str) -> str:
    normalized = text.strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_raw_source(
    conn: sqlite3.Connection,
    source_type: str,
    content: Optional[str] = None,
    content_path: Optional[str] = None,
    origin: Optional[str] = None,
    persist_text_to_inbox: bool = True,
) -> dict:
    """Store a raw source. Returns {'id': int, 'duplicate': bool}.

    If `content` is given (no `content_path`) and `persist_text_to_inbox`
    is True, the raw text is also written to a timestamped file under
    career-os/inbox/<kind>/ so it survives independently of the database.
    """
    if content is None and content_path is None:
        raise ValueError("create_raw_source requires content or content_path")

    if content_path:
        file_path = Path(content_path)
        content_hash = _hash_file(file_path)
    else:
        content_hash = _hash_text(content)

    existing = conn.execute(
        "SELECT id FROM raw_sources WHERE content_hash = ?", (content_hash,)
    ).fetchone()
    if existing:
        return {"id": existing["id"], "duplicate": True}

    stored_path = content_path
    if content is not None and content_path is None and persist_text_to_inbox:
        subdir = INBOX_SUBDIRS.get(source_type, "misc")
        target_dir = INBOX_ROOT / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{ts}_{content_hash[:8]}.txt"
        target_file = target_dir / fname
        target_file.write_text(content, encoding="utf-8")
        stored_path = str(target_file.relative_to(CAREER_OS_ROOT))

    cur = conn.execute(
        """INSERT INTO raw_sources (source_type, content, content_path, origin, content_hash)
           VALUES (?, ?, ?, ?, ?)""",
        (source_type, content, stored_path, origin, content_hash),
    )
    conn.commit()
    return {"id": cur.lastrowid, "duplicate": False}
