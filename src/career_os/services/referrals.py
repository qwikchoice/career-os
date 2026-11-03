"""Referrals: a light link Contact -> Company -> Role -> Application.

Not a CRM. Company and role are optional ("Dev can refer me at Google" has
no role yet), and anything that does not resolve is preserved (role_hint,
raw source, interaction) rather than rejected. Every update also logs an
interaction and, when a role is known, nudges the existing application
(referral_contact_id / channel) instead of keeping a parallel record.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta
from typing import Optional

from career_os.services import applications as applications_svc
from career_os.services import contacts as contacts_svc
from career_os.services import interactions as interactions_svc

STATUSES = ["offered", "to_request", "requested", "submitted", "declined", "expired", "completed", "unknown"]
TERMINAL = ("declined", "expired", "completed")
UNUSED = ("offered", "to_request")
WAITING = ("requested", "submitted")
_ROLE_TERMINAL = ("rejected", "withdrawn", "closed")
STALE_DAYS = 7

_N = r"[A-Z][a-z]+(?:\s[A-Z][a-z]+){0,2}"  # up to three words: "Kartik Kumar Pillai"
_NOT_NAMES = {"Ask", "Follow", "Add", "The", "Applied", "Found", "I", "He", "She", "They", "My", "This", "That"}
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_CHANNELS = re.compile(r"\b(?:from|on|via|through|over)\s+(LinkedIn|email|Slack|WhatsApp|Twitter|Discord|Facebook|Teams)\b", re.I)

_OFFER = re.compile(
    rf"(?P<name>{_N})\b[^.]*?\b(?:can|could|will|would|'d|is willing to|are willing to|offered to|offering to|"
    rf"happy to|able to|volunteered to)\s+(?:be able to\s+)?refer\s+me\b(?P<rest>[^.]*)")
_ASK = re.compile(rf"(?i:\bask(?:ed)?)\s+(?P<name>{_N})\s+(?i:to\s+refer\s+me|for\s+(?:a\s+|the\s+)?referral)\b(?P<rest>[^.]*)")
_REQUESTED = re.compile(rf"\brequested\s+(?:a\s+)?referral\s+from\s+(?P<name>{_N})\b(?P<rest>[^.]*)")
_SUBMITTED = [
    re.compile(rf"\b(?P<name>{_N})\s+(?:has\s+|already\s+)?(?:submitted|filed|put\s+in|sent\s+in)\s+(?:the\s+|my\s+|a\s+)?referral\b(?P<rest>[^.]*)"),
    re.compile(rf"\breferral\s+(?:was\s+|has\s+been\s+)?submitted\s+by\s+(?P<name>{_N})\b(?P<rest>[^.]*)"),
    re.compile(rf"\b(?P<name>{_N})\s+referred\s+me\b(?P<rest>[^.]*)"),
]
_SUBMITTED_IT = re.compile(rf"\b(?P<name>{_N})\s+(?:has\s+)?submitted\s+it\b(?P<rest>[^.]*)")
_DECLINED = re.compile(
    rf"\b(?P<name>{_N})\s+(?:declined|said\s+(?:he|she|they)\s+(?:can'?t|cannot|won'?t)|can'?t|cannot|won'?t|isn'?t\s+able\s+to)\s+(?:to\s+)?refer\b(?P<rest>[^.]*)")
_EXPIRED = re.compile(rf"\b(?P<name>{_N})'?s?\s+referral\s+(?:has\s+|is\s+)?expired\b(?P<rest>[^.]*)")
_COMPLETED = re.compile(rf"\b(?P<name>{_N})'?s?\s+referral\s+(?:is\s+|was\s+)?(?:completed|done|went\s+through)\b(?P<rest>[^.]*)")
_FOLLOWUP = re.compile(rf"(?i:\bfollow(?:ed)?[\s-]?up\s+with)\s+(?P<name>{_N})\b(?P<rest>[^.]*)")


# --------------------------------------------------------------------------
# Parsing (pure; no database)
# --------------------------------------------------------------------------
def parse_when(text: str, today: Optional[date] = None) -> Optional[str]:
    today = today or date.today()
    low = text.lower()
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", low)
    if m:
        return m.group(1)
    if "tomorrow" in low:
        return (today + timedelta(days=1)).isoformat()
    m = re.search(r"\bin\s+(\d+)\s+(day|week)s?\b", low)
    if m:
        return (today + timedelta(days=int(m.group(1)) * (7 if m.group(2) == "week" else 1))).isoformat()
    if re.search(r"\bnext\s+week\b", low):
        return (today + timedelta(days=7)).isoformat()
    for i, wd in enumerate(_WEEKDAYS):
        if re.search(rf"\b{wd}\b", low):
            ahead = (i - today.weekday()) % 7 or 7  # "monday"/"next monday" -> the upcoming one
            return (today + timedelta(days=ahead)).isoformat()
    return None


def match_referral_update(text: str) -> Optional[dict]:
    """Return {action, name, rest, source, [follow_up_date]} or None when the text is not a referral update."""
    source = None
    sm = _CHANNELS.search(text)
    if sm:
        source = sm.group(1).capitalize() if sm.group(1).lower() != "linkedin" else "LinkedIn"

    def hit(pattern, action, **extra):
        m = pattern.search(text)
        if m and m.group("name") not in _NOT_NAMES:
            return {"action": action, "name": m.group("name"), "rest": m.group("rest"), "source": source, **extra}
        return None

    for pattern, action in ((_ASK, "requested"), (_REQUESTED, "requested")):
        r = hit(pattern, action)
        if r:
            return r
    fu = _FOLLOWUP.search(text)
    if fu and fu.group("name") not in _NOT_NAMES:
        return {"action": "follow_up", "name": fu.group("name"), "rest": fu.group("rest"), "source": source,
                "follow_up_date": parse_when(fu.group("rest"))}
    for pattern in _SUBMITTED:
        r = hit(pattern, "submitted")
        if r:
            return r
    r = hit(_SUBMITTED_IT, "submitted", needs_existing=True)
    if r:
        return r
    for pattern, action in ((_DECLINED, "declined"), (_EXPIRED, "expired"), (_COMPLETED, "completed")):
        r = hit(pattern, action, needs_existing=True)
        if r:
            return r
    r = hit(_OFFER, "offered")
    if r:
        r["follow_up_date"] = parse_when(r["rest"])
        return r
    return None


# --------------------------------------------------------------------------
# Resolution helpers
# --------------------------------------------------------------------------
def _find_contact(conn, name: str, company_id: Optional[int]) -> tuple[Optional[sqlite3.Row], bool]:
    rows = conn.execute(
        "SELECT * FROM contacts WHERE name = ? COLLATE NOCASE OR name LIKE ? COLLATE NOCASE ORDER BY id",
        (name, f"{name} %"),
    ).fetchall()
    if not rows:  # no exact/prefix hit: try a close spelling ("Kranti" vs "Kranthi") before creating a duplicate
        rows = [conn.execute("SELECT * FROM contacts WHERE id = ?", (m["id"],)).fetchone()
                for m in contacts_svc.find_similar_contacts(conn, name, company_id=company_id)]
    if not rows:
        return None, False
    if company_id:
        same = [r for r in rows if r["company_id"] == company_id]
        if same:
            return same[0], len(same) > 1
    return rows[0], len(rows) > 1


def _resolve_company(conn, rest: str, *, allow_create: bool) -> Optional[int]:
    from career_os.services import companies as companies_svc

    names = conn.execute("SELECT id, name FROM companies ORDER BY length(name) DESC").fetchall()
    for c in names:
        if re.search(rf"\b{re.escape(c['name'])}\b", rest, re.I):
            return c["id"]
    if allow_create:
        m = re.search(r"\b(?:at|to|in|with)\s+([A-Z][\w&.\-]*(?:\s[A-Z][\w&.\-]*)*)", rest)
        if m and m.group(1) not in _NOT_NAMES:
            return companies_svc.get_or_create_company(conn, m.group(1))
    return None


_GENERIC = {"manager", "technical", "program", "senior", "principal", "staff", "product", "the", "of", "and", "for", "a"}
_EXPAND = {"tpm": "technical program manager", "pm": "product manager"}


def _tokens(s: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", s.lower())
    words = [w2 for w in words for w2 in _EXPAND.get(w, w).split()]
    return {w for w in words if w not in _GENERIC and len(w) > 1}


def _resolve_role(conn, rest: str, company_id: Optional[int]) -> tuple[Optional[int], Optional[str]]:
    """Return (role_id, role_hint). Never guess between equally good candidates."""
    m = re.search(r"\b(?:job|role)\s*#?\s*(\d+)\b", rest, re.I)
    if m and conn.execute("SELECT 1 FROM roles WHERE id = ?", (int(m.group(1)),)).fetchone():
        return int(m.group(1)), None
    hint = None
    hm = re.search(r"\bfor\s+(?:the\s+|a\s+)?(.{3,80}?)(?:\s+(?:role|job|position|opening))?\s*$", rest.strip().rstrip("."), re.I)
    if hm:
        hint = hm.group(1).strip()
    if company_id:
        roles = conn.execute("SELECT id, title FROM roles WHERE company_id = ? AND status NOT IN ('rejected','withdrawn','closed')",
                             (company_id,)).fetchall()
    else:
        roles = []
        for c in conn.execute("SELECT id, name FROM companies").fetchall():
            if re.search(rf"\b{re.escape(c['name'])}\b", rest, re.I):
                roles += conn.execute("SELECT id, title FROM roles WHERE company_id = ?", (c["id"],)).fetchall()
    min_score = 1
    if not roles and not company_id:  # no company anywhere in the text: search every open role, but demand a stronger match
        roles = conn.execute("SELECT id, title FROM roles WHERE status NOT IN ('rejected','withdrawn','closed')").fetchall()
        min_score = 2
    want = _tokens(rest)
    scored = sorted(((len(_tokens(r["title"]) & want), r["id"]) for r in roles), reverse=True)
    if scored and scored[0][0] >= min_score and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1], None
    return None, hint


def _target_referral(conn, contact_id, company_id, role_id) -> Optional[sqlite3.Row]:
    open_ = "status NOT IN ('declined','expired','completed')"
    if role_id:
        row = conn.execute(f"SELECT * FROM referrals WHERE contact_id=? AND role_id=? AND {open_} ORDER BY id DESC",
                           (contact_id, role_id)).fetchone()
        if row:
            return row
        role_company = conn.execute("SELECT company_id FROM roles WHERE id=?", (role_id,)).fetchone()["company_id"]
        row = conn.execute(f"SELECT * FROM referrals WHERE contact_id=? AND company_id=? AND role_id IS NULL AND {open_} ORDER BY id DESC",
                           (contact_id, role_company)).fetchone()
        if row:
            return row
        return conn.execute(f"SELECT * FROM referrals WHERE contact_id=? AND company_id IS NULL AND role_id IS NULL AND {open_} ORDER BY id DESC",
                            (contact_id,)).fetchone()
    if company_id:
        return conn.execute(f"SELECT * FROM referrals WHERE contact_id=? AND company_id=? AND {open_} ORDER BY id DESC",
                            (contact_id, company_id)).fetchone()
    return conn.execute(f"SELECT * FROM referrals WHERE contact_id=? AND {open_} ORDER BY id DESC", (contact_id,)).fetchone()


# --------------------------------------------------------------------------
# Applying an update
# --------------------------------------------------------------------------
def _link_application(conn, role_id: int, contact_id: int, action: str) -> None:
    app_id = applications_svc.get_or_create_application(conn, role_id)
    app = conn.execute("SELECT status, channel FROM applications WHERE id = ?", (app_id,)).fetchone()
    conn.execute("UPDATE applications SET referral_contact_id = ?, updated_at = datetime('now') WHERE id = ?",
                 (contact_id, app_id))
    conn.commit()
    if action == "requested" and app["status"] == "planned":
        applications_svc.set_status(conn, role_id, "referral_requested", referral_contact_id=contact_id)
    elif action == "submitted":
        if app["status"] in ("planned", "referral_requested"):
            applications_svc.set_status(conn, role_id, "referred", channel="referral", referral_contact_id=contact_id)
        elif not app["channel"]:
            conn.execute("UPDATE applications SET channel = 'referral' WHERE id = ?", (app_id,))
            conn.commit()


def apply_referral_update(conn: sqlite3.Connection, text: str, parsed: dict, raw_source_id: Optional[int] = None) -> Optional[dict]:
    today = date.today().isoformat()
    action, name, rest, source = parsed["action"], parsed["name"], parsed["rest"], parsed.get("source")
    notes: list[str] = []

    company_id = _resolve_company(conn, rest, allow_create=(action == "offered"))
    contact, ambiguous = _find_contact(conn, name, company_id)
    if parsed.get("needs_existing"):
        if not contact or not conn.execute("SELECT 1 FROM referrals WHERE contact_id = ?", (contact["id"],)).fetchone():
            return None  # not clearly about a referral we know of: let the dispatcher keep looking
    if ambiguous:
        notes.append(f"more than one contact matches '{name}'; used the first. Add a last name to disambiguate.")
    if contact:
        contact_id = contact["id"]
        if action == "offered" and company_id and not contact["company_id"]:
            conn.execute("UPDATE contacts SET company_id = ?, updated_at = datetime('now') WHERE id = ?", (company_id, contact_id))
            conn.commit()
    else:
        contact_id = contacts_svc.get_or_create_contact(
            conn, name, company_id=company_id if action == "offered" else None, relationship_type="referral")

    if company_id is None and contact and action in ("requested", "submitted", "follow_up"):
        # "Ask Nina ... for the Senior TPM role": no company named, so use the one Nina already offered at
        cids = {r["company_id"] for r in conn.execute(
            "SELECT company_id FROM referrals WHERE contact_id = ? AND status NOT IN ('declined','expired','completed')",
            (contact["id"],)) if r["company_id"]}
        if len(cids) == 1:
            company_id = cids.pop()

    role_id, role_hint = (None, None)
    if action in ("requested", "submitted", "follow_up", "offered"):
        role_id, role_hint = _resolve_role(conn, rest, company_id)
    if role_id and not company_id:
        company_id = conn.execute("SELECT company_id FROM roles WHERE id = ?", (role_id,)).fetchone()["company_id"]

    existing = _target_referral(conn, contact_id, company_id, role_id)
    if existing and role_id is None and action in ("submitted", "follow_up", "declined", "expired", "completed"):
        role_id = existing["role_id"]  # "Nina submitted it": reuse the role already on file
        company_id = company_id or existing["company_id"]

    if action == "follow_up":
        when = parsed.get("follow_up_date")
        if existing:
            if when:
                conn.execute("UPDATE referrals SET follow_up_date = ?, updated_at = datetime('now') WHERE id = ?", (when, existing["id"]))
                conn.commit()
            referral_id = existing["id"]
        else:
            referral_id = None
            notes.append("no referral on file for this contact; follow-up saved as an interaction only")
        interactions_svc.log_interaction(conn, contact_id, text, role_id=role_id, direction="outbound",
                                         follow_up=when, raw_source_id=raw_source_id)
        return _result(conn, "follow_up", referral_id, contact_id, notes, follow_up_date=when)

    new_status = {"offered": "offered", "requested": "requested", "submitted": "submitted",
                  "declined": "declined", "expired": "expired", "completed": "completed"}[action]
    date_col = {"offered": "date_offered", "requested": "date_requested", "submitted": "date_submitted"}.get(action)

    if existing:
        if action == "offered" and existing["status"] != "offered":
            referral_id = existing["id"]  # a repeat offer must not downgrade a more advanced referral
            notes.append(f"existing referral already '{existing['status']}'; offer not re-recorded")
        else:
            sets = ["status = ?", "updated_at = datetime('now')"]
            params: list = [new_status]
            if date_col:
                sets.append(f"{date_col} = COALESCE({date_col}, ?)")
                params.append(today)
            if role_id and not existing["role_id"]:
                sets += ["role_id = ?", "role_hint = NULL"]
                params.append(role_id)
            elif role_hint and not existing["role_id"] and not existing["role_hint"]:
                sets.append("role_hint = ?")
                params.append(role_hint)
            if company_id and not existing["company_id"]:
                sets.append("company_id = ?")
                params.append(company_id)
            conn.execute(f"UPDATE referrals SET {', '.join(sets)} WHERE id = ?", (*params, existing["id"]))  # noqa: S608 - fixed fragments
            conn.commit()
            referral_id = existing["id"]
    else:
        cols = {"contact_id": contact_id, "company_id": company_id, "role_id": role_id, "role_hint": role_hint,
                "status": new_status, "source": source, "raw_source_id": raw_source_id,
                "follow_up_date": parsed.get("follow_up_date")}
        if date_col:
            cols[date_col] = today
        cur = conn.execute(f"INSERT INTO referrals ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(cols.values()))  # noqa: S608 - fixed keys
        conn.commit()
        referral_id = cur.lastrowid

    if source and existing and not existing["source"]:
        conn.execute("UPDATE referrals SET source = ? WHERE id = ?", (source, referral_id))
        conn.commit()
    final_role = conn.execute("SELECT role_id FROM referrals WHERE id = ?", (referral_id,)).fetchone()["role_id"]
    if final_role and action in ("requested", "submitted"):
        _link_application(conn, final_role, contact_id, action)
    if action in ("requested", "submitted") and not final_role:
        notes.append("no tracked role matched; saved the description as role_hint" if role_hint
                     else "no role specified yet; referral stays company-level")
    interactions_svc.log_interaction(
        conn, contact_id, text, role_id=final_role, channel=(source or "").lower() or None,
        direction="inbound" if action == "offered" else "outbound", raw_source_id=raw_source_id)
    return _result(conn, action, referral_id, contact_id, notes)


def _result(conn, action, referral_id, contact_id, notes, **extra) -> dict:
    out = {"kind": "referral", "action": action, "referral_id": referral_id,
           "contact": conn.execute("SELECT name FROM contacts WHERE id = ?", (contact_id,)).fetchone()["name"],
           "notes": notes, **extra}
    if referral_id:
        r = conn.execute(
            """SELECT r.status, r.role_id, r.role_hint, r.follow_up_date, c.name AS company
               FROM referrals r LEFT JOIN companies c ON c.id = r.company_id WHERE r.id = ?""", (referral_id,)).fetchone()
        out.update(status=r["status"], company=r["company"], role_id=r["role_id"], role_hint=r["role_hint"],
                   follow_up_date=r["follow_up_date"])
        out["priority"] = priority_for(conn, referral_id)
    return out


# --------------------------------------------------------------------------
# Priority + queries
# --------------------------------------------------------------------------
def priority_for(conn: sqlite3.Connection, referral_id: int) -> str:
    """High/Medium/Low from the opportunity (role tier, company tier, contact strength). No numeric score."""
    r = conn.execute(
        """SELECT r.role_id, r.company_id, c.tier AS ctier, ct.strength
           FROM referrals r LEFT JOIN companies c ON c.id = r.company_id
           JOIN contacts ct ON ct.id = r.contact_id WHERE r.id = ?""", (referral_id,)).fetchone()
    tier = None
    if r["role_id"]:
        tier = conn.execute("SELECT role_tier FROM roles WHERE id = ?", (r["role_id"],)).fetchone()["role_tier"]
    elif r["company_id"]:
        row = conn.execute("SELECT MIN(role_tier) AS t FROM roles WHERE company_id = ? AND status NOT IN ('rejected','withdrawn','closed')",
                           (r["company_id"],)).fetchone()
        tier = row["t"]
    strong = (r["strength"] or "").lower() in ("strong", "high")
    ctier = r["ctier"]
    if (tier == 1 and ctier == "A") or (tier == 1 and strong) or (ctier == "A" and strong):
        return "High"
    if tier == 3 and ctier in (None, "C", "Watchlist"):
        return "Low"
    if tier is None and ctier in (None, "C", "Watchlist"):
        return "Low"
    return "Medium"


_BASE = """SELECT r.*, ct.name AS contact_name, c.name AS company_name, c.tier AS company_tier,
                  ro.title AS role_title
           FROM referrals r JOIN contacts ct ON ct.id = r.contact_id
           LEFT JOIN companies c ON c.id = r.company_id
           LEFT JOIN roles ro ON ro.id = r.role_id"""
_PRIO_RANK = {"High": 0, "Medium": 1, "Low": 2}


def list_referrals(conn: sqlite3.Connection, view: str = "all", company: Optional[str] = None,
                   tier: Optional[str] = None) -> list[dict]:
    """view: unused | waiting | followup | active | all"""
    rows = [dict(r) for r in conn.execute(_BASE + " ORDER BY r.updated_at DESC")]
    today = date.today()
    out = []
    for r in rows:
        if company and (r["company_name"] or "").lower() != company.lower():
            continue
        if tier and r["company_tier"] != tier:
            continue
        age = (today - date.fromisoformat((r["updated_at"] or today.isoformat())[:10])).days
        r["days_since_update"] = age
        if view == "unused" and r["status"] not in UNUSED:
            continue
        if view == "waiting" and r["status"] not in WAITING:
            continue
        if view == "active" and r["status"] in TERMINAL:
            continue
        if view == "followup":
            due = r["follow_up_date"] and r["follow_up_date"] <= today.isoformat()
            stale = not r["follow_up_date"] and age >= STALE_DAYS
            if r["status"] not in WAITING or not (due or stale):
                continue
            r["follow_up_reason"] = "follow-up date reached" if due else f"no update in {age} days"
        r["priority"] = priority_for(conn, r["id"])
        out.append(r)
    out.sort(key=lambda r: (_PRIO_RANK[r["priority"]], r["updated_at"]))
    return out


def tier_a_referrers(conn: sqlite3.Connection) -> list[dict]:
    """Tier A companies that already have a potential referrer (any non-terminal referral)."""
    return [r for r in list_referrals(conn, "active", tier="A")]


def paths_for_role(conn: sqlite3.Connection, role_id: int) -> list[dict]:
    role = conn.execute("SELECT company_id FROM roles WHERE id = ?", (role_id,)).fetchone()
    if not role:
        return []
    paths = []
    for r in conn.execute(_BASE + " WHERE r.status NOT IN ('declined','expired') AND (r.role_id = ? OR (r.company_id = ? AND r.role_id IS NULL))",
                          (role_id, role["company_id"])):
        d = dict(r)
        d["level"] = "role" if d["role_id"] == role_id else "company"
        paths.append(d)
    return paths


def roles_without_referral_path(conn: sqlite3.Connection, tier: int = 1) -> dict:
    out = {"no_path": [], "company_level_only": []}
    for r in conn.execute(
        """SELECT r.id, r.title, c.name AS company, c.tier AS company_tier,
                  COALESCE(a.status, 'planned') AS application_status
           FROM roles r JOIN companies c ON c.id = r.company_id LEFT JOIN applications a ON a.role_id = r.id
           WHERE r.role_tier = ? AND r.status NOT IN ('rejected','withdrawn','closed')
           ORDER BY r.updated_at DESC""", (tier,)):
        paths = paths_for_role(conn, r["id"])
        d = dict(r)
        if not paths:
            out["no_path"].append(d)
        elif all(p["level"] == "company" for p in paths):
            out["company_level_only"].append(d)
    return out


def ensure_submitted(conn: sqlite3.Connection, contact_id: int, role_id: int, raw_source_id: Optional[int] = None) -> int:
    """An application that says "applied via referral from X" is itself a submitted referral: record it once."""
    role = conn.execute("SELECT company_id FROM roles WHERE id = ?", (role_id,)).fetchone()
    existing = _target_referral(conn, contact_id, role["company_id"], role_id)
    today = date.today().isoformat()
    if existing:
        conn.execute("UPDATE referrals SET status = 'submitted', role_id = COALESCE(role_id, ?), "
                     "date_submitted = COALESCE(date_submitted, ?), updated_at = datetime('now') WHERE id = ?",
                     (role_id, today, existing["id"]))
        conn.commit()
        return existing["id"]
    cur = conn.execute(
        "INSERT INTO referrals (contact_id, company_id, role_id, status, date_submitted, raw_source_id) "
        "VALUES (?, ?, ?, 'submitted', ?, ?)", (contact_id, role["company_id"], role_id, today, raw_source_id))
    conn.commit()
    return cur.lastrowid
