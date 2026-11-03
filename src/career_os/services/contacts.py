"""Contacts. Never infer private details not explicitly supplied (section 11)."""
from __future__ import annotations

import re
import sqlite3
from typing import Optional



def _norm_name(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (name or "").lower()))


def _norm_url(url: Optional[str]) -> str:
    return re.sub(r"^https?://(www\.)?", "", (url or "").strip().lower()).rstrip("/")


def _names_match(a: str, b: str) -> bool:
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return False
    if na == nb or sorted(na.split()) == sorted(nb.split()):
        return True
    ta, tb = na.split(), nb.split()
    if len(ta) < 2 or len(tb) < 2 or len(ta) != len(tb) or ta[-1] != tb[-1]:
        return False  # a bare first name ("Rohan") never fuzzy-matches: too ambiguous
    return all(x == y or _spelling_variant(x, y) for x, y in zip(ta, tb))


def _spelling_variant(x: str, y: str) -> bool:
    """One token is the other with 1-2 extra letters ("Kranti"/"Kranthi"). A substituted letter
    ("Amar"/"Amir") is a different name, so it does not count."""
    short, long_ = sorted((x, y), key=len)
    if len(short) < 4 or len(long_) - len(short) > 2:
        return False
    it = iter(long_)
    return all(ch in it for ch in short)  # short is a subsequence of long_


def find_similar_contacts(
    conn: sqlite3.Connection,
    name: str,
    *,
    company_id: Optional[int] = None,
    email: Optional[str] = None,
    linkedin_url: Optional[str] = None,
) -> list[dict]:
    """Existing contacts that are probably the same person. Same email or LinkedIn URL is
    decisive; otherwise the name must match (exact, reordered, or a close spelling with the
    same last name) and the companies must not conflict (either side unknown is fine)."""
    out = []
    em, li = (email or "").strip().lower(), _norm_url(linkedin_url)
    for r in conn.execute("SELECT * FROM contacts ORDER BY id").fetchall():
        if (em and (r["email"] or "").strip().lower() == em) or (li and _norm_url(r["linkedin_url"]) == li):
            out.append(dict(r))
        elif _names_match(name, r["name"]) and (not company_id or not r["company_id"] or r["company_id"] == company_id):
            out.append(dict(r))
    return out


def flag_duplicate_contacts(conn: sqlite3.Connection, id_a: int, id_b: int, reason: str, status: str = "flagged") -> None:
    lo, hi = sorted((id_a, id_b))
    if not conn.execute("SELECT 1 FROM duplicates WHERE entity_type='contact' AND entity_id_a=? AND entity_id_b=?", (lo, hi)).fetchone():
        conn.execute("INSERT INTO duplicates (entity_type, entity_id_a, entity_id_b, reason, status) VALUES ('contact', ?, ?, ?, ?)",
                     (lo, hi, reason, status))
        conn.commit()


def merge_contacts(conn: sqlite3.Connection, keep_id: int, drop_id: int, reason: str = "same person") -> None:
    """Fold `drop_id` into `keep_id`: repoint every reference, backfill blank fields, record the
    merge in `duplicates`, then remove the now-empty row. Call only when the match is unambiguous."""
    if keep_id == drop_id:
        return
    keep = conn.execute("SELECT * FROM contacts WHERE id = ?", (keep_id,)).fetchone()
    drop = conn.execute("SELECT * FROM contacts WHERE id = ?", (drop_id,)).fetchone()
    if not keep or not drop:
        raise ValueError("both contacts must exist")
    for table, col in (("referrals", "contact_id"), ("interactions", "contact_id"),
                       ("interviews", "interviewer_contact_id"), ("applications", "referral_contact_id")):
        conn.execute(f"UPDATE {table} SET {col} = ? WHERE {col} = ?", (keep_id, drop_id))  # noqa: S608 - fixed names
    for col in ("company_id", "title", "relationship_type", "linkedin_url", "email", "strength", "notes"):
        if keep[col] in (None, "") and drop[col] not in (None, ""):
            conn.execute(f"UPDATE contacts SET {col} = ? WHERE id = ?", (drop[col], keep_id))  # noqa: S608 - fixed names
    conn.execute("UPDATE contacts SET updated_at = datetime('now') WHERE id = ?", (keep_id,))
    flag_duplicate_contacts(conn, keep_id, drop_id, f"{reason}: '{drop['name']}' merged into '{keep['name']}'", status="merged")
    conn.execute("DELETE FROM contacts WHERE id = ?", (drop_id,))
    conn.commit()


def get_or_create_contact(
    conn: sqlite3.Connection,
    name: str,
    *,
    company_id: Optional[int] = None,
    title: Optional[str] = None,
    relationship_type: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    email: Optional[str] = None,
) -> int:
    matches = find_similar_contacts(conn, name, company_id=company_id, email=email, linkedin_url=linkedin_url)
    if matches:
        keep = matches[0]
        for other in matches[1:]:
            flag_duplicate_contacts(conn, keep["id"], other["id"], f"both match '{name}'")
        for col, val in (("company_id", company_id), ("title", title), ("linkedin_url", linkedin_url), ("email", email)):
            if val and not keep[col]:
                conn.execute(f"UPDATE contacts SET {col} = ?, updated_at = datetime('now') WHERE id = ?", (val, keep["id"]))  # noqa: S608 - fixed names
        conn.commit()
        return keep["id"]
    cur = conn.execute(
        """INSERT INTO contacts (name, company_id, title, relationship_type, linkedin_url, email)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, company_id, title, relationship_type, linkedin_url, email),
    )
    conn.commit()
    return cur.lastrowid


def find_contact_by_name(conn: sqlite3.Connection, name: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM contacts WHERE name LIKE ? COLLATE NOCASE", (f"%{name}%",)
    ).fetchone()
    return dict(row) if row else None


def list_contacts(conn: sqlite3.Connection, company_id: Optional[int] = None) -> list[dict]:
    if company_id:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE company_id = ? ORDER BY name", (company_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM contacts ORDER BY name").fetchall()
    return [dict(r) for r in rows]
