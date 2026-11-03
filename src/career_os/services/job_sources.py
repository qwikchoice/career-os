"""Job sources: where roles are discovered, and which sources deserve attention.

Two facts are kept apart on purpose (they are not the same thing):
  * discovery source     -> roles.source (a job_sources name)
  * application channel  -> applications.channel (e.g. 'referral', 'company_site')

Priorities are qualitative (High/Medium/Low). Seeded ones are labelled
`seed_hypothesis`; a user statement is `user_stated`. Evidence-based
suggestions are computed live from pipeline data and only offered once a
source has enough roles to mean something.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

SOURCE_TYPES = {
    "company_careers", "linkedin", "aggregator", "remote_board", "startup_board",
    "government", "recruiter", "referral", "community", "other",
}
MIN_ROLES_FOR_CONCLUSION = 10

# name, type, priority, notes   (initial hypotheses, not permanent truth)
SEED_SOURCES = [
    ("Company Career Pages", "company_careers", "High",
     "Tier A target-company sites: authoritative roles, direct team access, less noise."),
    ("LinkedIn", "linkedin", "High",
     "Discovery plus recruiter, hiring-manager and referral/network discovery."),
    ("Referrals / Network", "referral", "High", "Improves access and conversion."),
    ("Google Search", "aggregator", "Medium", "Google Jobs / search discovery."),
    ("Indeed", "aggregator", "Medium", None),
    ("Dice", "aggregator", "Medium", None),
    ("Wellfound", "startup_board", "Medium", "Startup board."),
    ("Recruiter", "recruiter", "Medium", "Recruiter-sourced roles (inbound email/InMail)."),
    ("CalCareers", "government", None,
     "Special channel: government hiring differs from private-sector AI hiring. Track independently."),
]

# alias (lowercase) -> canonical seeded name
ALIASES = {
    "direct": "Company Career Pages", "company site": "Company Career Pages",
    "company careers": "Company Career Pages", "career page": "Company Career Pages",
    "career pages": "Company Career Pages", "careers page": "Company Career Pages",
    "email": "Recruiter", "recruiter": "Recruiter",
    "google": "Google Search", "google jobs": "Google Search", "google search": "Google Search",
    "referral": "Referrals / Network", "employee referral": "Referrals / Network",
    "network": "Referrals / Network", "referrals": "Referrals / Network",
}

_ADVANCED = {"recruiter_screen", "hiring_manager", "interview_loop", "final_round", "offer"}
_INTERVIEW = {"hiring_manager", "interview_loop", "final_round", "offer"}
_TYPE_WORDS = {
    "government": "government", "gov": "government", "remote": "remote_board",
    "startup": "startup_board", "aggregator": "aggregator", "recruiter": "recruiter",
    "referral": "referral", "community": "community", "career": "company_careers",
    "careers": "company_careers", "linkedin": "linkedin",
}


def seed_job_sources(conn: sqlite3.Connection) -> int:
    n = 0
    for name, stype, prio, notes in SEED_SOURCES:
        cur = conn.execute(
            """INSERT OR IGNORE INTO job_sources (name, source_type, priority, priority_basis, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (name, stype, prio, "seed_hypothesis" if prio else None, notes),
        )
        n += cur.rowcount
    conn.commit()
    return n


def _find(conn: sqlite3.Connection, raw: str) -> Optional[sqlite3.Row]:
    key = raw.strip().lower()
    canonical = ALIASES.get(key)
    if not canonical and ("careers" in key or "career" in key) and "." in key:
        canonical = "Company Career Pages"  # e.g. 'metacareers.com'
    return conn.execute(
        "SELECT * FROM job_sources WHERE name = ? COLLATE NOCASE", (canonical or raw.strip(),)
    ).fetchone()


def canonical_name(conn: sqlite3.Connection, raw: Optional[str]) -> Optional[str]:
    """Map a free-text source to a known source name, or None. 'manual' is not a source."""
    if not raw or raw.strip().lower() in ("manual", "unknown", ""):
        return None
    row = _find(conn, raw)
    return row["name"] if row else None


def resolve_or_create(conn: sqlite3.Connection, raw: str, source_type: Optional[str] = None) -> dict:
    """Return the source for `raw`, creating an 'other' source if unseen (capture, never reject)."""
    row = _find(conn, raw)
    if row:
        return {"name": row["name"], "created": False}
    stype = source_type if source_type in SOURCE_TYPES else "other"
    conn.execute("INSERT INTO job_sources (name, source_type) VALUES (?, ?)", (raw.strip(), stype))
    conn.commit()
    return {"name": raw.strip(), "created": True}


def add_source(conn, name: str, source_type: str = "other", url: Optional[str] = None,
               notes: Optional[str] = None) -> dict:
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"source_type must be one of {sorted(SOURCE_TYPES)}")
    res = resolve_or_create(conn, name, source_type)
    if not res["created"] and (url or notes or source_type != "other"):
        conn.execute(
            """UPDATE job_sources SET url = COALESCE(?, url), notes = COALESCE(?, notes),
               source_type = CASE WHEN ? != 'other' THEN ? ELSE source_type END,
               updated_at = datetime('now') WHERE name = ? COLLATE NOCASE""",
            (url, notes, source_type, source_type, res["name"]),
        )
    elif res["created"] and (url or notes):
        conn.execute("UPDATE job_sources SET url = ?, notes = ? WHERE name = ? COLLATE NOCASE",
                     (url, notes, res["name"]))
    conn.commit()
    return res


def set_priority(conn, name: str, priority: Optional[str], *, basis: str = "user_stated",
                 note: Optional[str] = None, active: Optional[bool] = None) -> dict:
    if priority not in ("High", "Medium", "Low", None):
        raise ValueError("priority must be High, Medium or Low")
    res = resolve_or_create(conn, name)
    sets, params = ["updated_at = datetime('now')"], []
    if priority is not None:
        sets += ["priority = ?", "priority_basis = ?"]
        params += [priority, basis]
    if note:
        sets.append("notes = COALESCE(notes || ' | ', '') || ?")
        params.append(note)
    if active is not None:
        sets.append("active = ?")
        params.append(1 if active else 0)
    conn.execute(f"UPDATE job_sources SET {', '.join(sets)} WHERE name = ? COLLATE NOCASE",  # noqa: S608 - fixed fragments
                 (*params, res["name"]))
    conn.commit()
    return {"name": res["name"], "priority": priority, "created": res["created"]}


def list_sources(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM job_sources ORDER BY active DESC, "
        "CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 WHEN 'Low' THEN 2 ELSE 3 END, name")]


# --------------------------------------------------------------------------
# Analytics: counts first; a suggestion only when there is enough data
# --------------------------------------------------------------------------
def _rate(num: int, den: int) -> Optional[float]:
    return round(num / den, 2) if den else None


def source_stats(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT r.source, r.role_tier, COALESCE(a.status, 'planned') AS status
           FROM roles r LEFT JOIN applications a ON a.role_id = r.id"""
    ).fetchall()
    stats: dict[str, dict] = {}
    for r in rows:
        name = canonical_name(conn, r["source"]) or (r["source"] if r["source"] not in (None, "manual", "") else "(unknown)")
        d = stats.setdefault(name, {"source": name, "roles": 0, "high_fit": 0, "noise": 0,
                                    "pursued": 0, "responses": 0, "interviews": 0})
        d["roles"] += 1
        d["high_fit"] += r["role_tier"] == 1
        d["noise"] += r["role_tier"] == 3
        d["pursued"] += r["status"] != "planned"
        d["responses"] += r["status"] in _ADVANCED
        d["interviews"] += r["status"] in _INTERVIEW
    prio = {r["name"]: r for r in conn.execute("SELECT name, priority, priority_basis, active FROM job_sources")}
    out = []
    for d in sorted(stats.values(), key=lambda x: -x["roles"]):
        p = prio.get(d["source"])
        d["priority"] = p["priority"] if p else None
        d["priority_basis"] = p["priority_basis"] if p else None
        d["active"] = bool(p["active"]) if p else True
        d["high_fit_rate"] = _rate(d["high_fit"], d["roles"])
        d["enough_data"] = d["roles"] >= MIN_ROLES_FOR_CONCLUSION
        d["suggestion"] = None
        if d["enough_data"] and d["high_fit_rate"] is not None:
            if d["high_fit_rate"] >= 0.5 and d["priority"] != "High":
                d["suggestion"] = "High"
            elif d["high_fit_rate"] <= 0.2 and d["priority"] != "Low":
                d["suggestion"] = "Low"
        out.append(d)
    return out


def channel_stats(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT COALESCE(channel, '(not recorded)') AS channel, status FROM applications "
        "WHERE status != 'planned'").fetchall()
    stats: dict[str, dict] = {}
    for r in rows:
        d = stats.setdefault(r["channel"], {"channel": r["channel"], "applications": 0, "responses": 0, "interviews": 0})
        d["applications"] += 1
        d["responses"] += r["status"] in _ADVANCED
        d["interviews"] += r["status"] in _INTERVIEW
    for d in stats.values():
        d["enough_data"] = d["applications"] >= MIN_ROLES_FOR_CONCLUSION
    return sorted(stats.values(), key=lambda x: -x["applications"])


# --------------------------------------------------------------------------
# Natural-language input
# --------------------------------------------------------------------------
_NAME = r"[A-Z][\w.&]*(?:\s[A-Z][\w.&]*)*"
_ADD_AS = re.compile(rf"\badd\s+(?P<name>{_NAME})\s+as\s+(?:a|an)\s+(?P<type>[\w\s/-]+?)\s+(?:job\s+)?sources?\b", re.I)
_ADD_TO = re.compile(rf"\badd\s+(?P<name>{_NAME})\s+to\s+(?:my\s+)?job\s+sources?\b", re.I)
_NEG = [
    re.compile(rf"(?:don'?t|do not)\s+think\s+(?P<name>{_NAME})\s+is\s+giving\s+me\s+(?:any\s+)?(?:good|great|useful|relevant)"),
    re.compile(rf"(?P<name>{_NAME})\s+(?:is|has become|has been)\s+(?:mostly\s+|all\s+|just\s+|pure\s+)?noise"),
    re.compile(rf"(?P<name>{_NAME})\s+(?:is\s+)?not\s+worth\s+(?:my\s+)?(?:time|checking)"),
]
_STOP = re.compile(rf"\bstop\s+checking\s+(?P<name>{_NAME})")
_POS = re.compile(rf"(?P<name>{_NAME})\s+(?:is|has been)\s+giving\s+me\s+(?:really\s+|very\s+)?(?:good|great|strong|relevant)")


def match_source_update(text: str) -> Optional[dict]:
    m = _ADD_AS.search(text)
    if m:
        words = m.group("type").lower().replace("-", " ").split()
        stype = next((_TYPE_WORDS[w] for w in words if w in _TYPE_WORDS), "other")
        return {"action": "add", "name": m.group("name").strip(), "source_type": stype}
    m = _ADD_TO.search(text)
    if m:
        return {"action": "add", "name": m.group("name").strip(), "source_type": "other"}
    m = _STOP.search(text)
    if m:
        return {"action": "deprioritize", "name": m.group("name").strip(), "stop": True}
    for pat in _NEG:
        m = pat.search(text)
        if m:
            return {"action": "deprioritize", "name": m.group("name").strip(), "stop": False}
    m = _POS.search(text)
    if m:
        return {"action": "prioritize", "name": m.group("name").strip()}
    return None


def apply_source_update(conn: sqlite3.Connection, text: str, parsed: dict) -> dict:
    if parsed["action"] == "add":
        res = add_source(conn, parsed["name"], parsed["source_type"])
        return {"kind": "job_source_added", "name": res["name"], "created": res["created"],
                "source_type": parsed["source_type"]}
    from datetime import date
    note = f"user said {date.today().isoformat()}: {text.strip()[:140]}"
    if parsed["action"] == "deprioritize":
        res = set_priority(conn, parsed["name"], "Low", note=note, active=False if parsed.get("stop") else None)
        return {"kind": "job_source_priority", "name": res["name"], "priority": "Low",
                "basis": "user_stated", "created": res["created"]}
    res = set_priority(conn, parsed["name"], "High", note=note)
    return {"kind": "job_source_priority", "name": res["name"], "priority": "High",
            "basis": "user_stated", "created": res["created"]}
