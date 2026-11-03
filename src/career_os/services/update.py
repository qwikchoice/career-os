"""Free-text update dispatcher (`career update "..."`).

Tries, in order: application status change -> interaction log ->
interview/signal note -> falls back to notes.add_note if nothing matches
with reasonable confidence. Never guesses a role/company it can't resolve;
an unresolved update is preserved as a note rather than mis-filed.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

from career_os.services import applications as applications_svc
from career_os.services import contacts as contacts_svc
from career_os.services import interactions as interactions_svc
from career_os.services import interviews as interviews_svc
from career_os.services import job_sources as job_sources_svc
from career_os.services import learning as learning_svc
from career_os.services import referrals as referrals_svc
from career_os.services import notes as notes_svc
from career_os.services import resolve
from career_os.services import sources as sources_svc

_STATUS_PATTERNS: list[tuple[str, str]] = [
    (r"\brejected\b|not selected|position (was )?filled", "rejected"),
    (r"withdr(aw|ew|awn)", "withdrawn"),
    (r"\boffer\b", "offer"),
    (r"final round", "final_round"),
    (r"hiring manager", "hiring_manager"),
    (r"recruiter screen", "recruiter_screen"),
    (r"interview (scheduled|loop|round)", "interview_loop"),
    (r"\breferred\b", "referred"),
    (r"referral request(ed)?", "referral_requested"),
    (r"\bapplied\b", "applied"),
]

_SIGNAL_KEYWORDS = {
    "metrics": ["metric", "threshold", "evaluation", "kpi", "baseline"],
    "system_design": ["architecture", "latency", "tradeoff", "scalability", "system design"],
    "coding": ["coding", "code", "algorithm"],
    "product_judgment": ["product sense", "prioritiz", "product judgment"],
    "leadership": ["leadership", "influence", "stakeholder"],
    "communication": ["communicat", "presentation", "explain"],
    "technical_ownership": ["ownership", "personally drove", "decided", "owned"],
}
_WEAK_HINTS = ["too high-level", "struggled", "weak", "couldn't", "didn't know", "stayed too"]
_STRONG_HINTS = ["strong", "nailed", "went well", "confident"]


def apply_update(conn: sqlite3.Connection, text: str) -> dict:
    # Referral, job-source and learning-resource updates are recognised first; each matcher is
    # conservative and returns None when unsure, so everything else flows to the original logic.
    ref = referrals_svc.match_referral_update(text)
    if ref:
        src = sources_svc.create_raw_source(conn, source_type="note", content=text)
        result = referrals_svc.apply_referral_update(conn, text, ref, raw_source_id=src["id"])
        if result:
            return result
    src_update = job_sources_svc.match_source_update(text)
    if src_update:
        return job_sources_svc.apply_source_update(conn, text, src_update)
    if learning_svc.match_learning_update(text):
        added = learning_svc.add_resource(conn, text, source="user")
        return {"kind": "learning_resource", "resource_id": added["resource_id"], "duplicate": added["duplicate"],
                "title": added["title"], "category": added["category"], "provider": added["provider"],
                "topics": ", ".join(added["topics"]), "inferred": ", ".join(added["inferred"])}

    role_id, role_conf = resolve.resolve_role(conn, text)

    status = _match_status(text)
    discovery = _extract_discovery(text)
    if status and role_id:
        channel, referral_contact_id = _extract_channel_and_referral(conn, text)
        app_id = applications_svc.set_status(
            conn, role_id, status, channel=channel, referral_contact_id=referral_contact_id
        )
        out = {
            "kind": "application_status",
            "role_id": role_id,
            "role_confidence": role_conf,
            "status": status,
            "application_id": app_id,
        }
        if channel:
            out["application_channel"] = channel
        if referral_contact_id:
            src = sources_svc.create_raw_source(conn, source_type="note", content=text)
            out["referral_id"] = referrals_svc.ensure_submitted(conn, referral_contact_id, role_id, src["id"])
        if discovery:
            out.update(_record_discovery(conn, role_id, discovery))
        return out
    if discovery and role_id:
        return {"kind": "role_source", "role_id": role_id, "role_confidence": role_conf,
                **_record_discovery(conn, role_id, discovery)}

    interaction_match = _match_interaction(conn, text, role_id)
    if interaction_match:
        return interaction_match

    interview_match = _match_interview_signal(conn, text, role_id)
    if interview_match:
        return interview_match

    # Nothing matched confidently -> preserve as a note, never force a guess.
    note = notes_svc.add_note(conn, text)
    note["kind"] = "note_fallback"
    return note


def _match_status(text: str) -> Optional[str]:
    lowered = text.lower()
    for pattern, status in _STATUS_PATTERNS:
        if re.search(pattern, lowered):
            return status
    return None


_DISCOVERY_RE = re.compile(
    r"\b(?:found|saw|spotted|discovered|came across)\b[^.]*?\b(?:on|via|through|at|from)\s+"
    r"(?P<src>[A-Z][\w.&]*(?:\s[A-Z][\w.&]*)*)")


def _extract_discovery(text: str) -> Optional[str]:
    m = _DISCOVERY_RE.search(text)
    return m.group("src") if m else None


def _record_discovery(conn: sqlite3.Connection, role_id: int, discovery: str) -> dict:
    """Set the discovery source only when the role has none; never overwrite a recorded one."""
    name = job_sources_svc.resolve_or_create(conn, discovery)["name"]
    current = conn.execute("SELECT source FROM roles WHERE id = ?", (role_id,)).fetchone()["source"]
    if current in (None, "", "manual"):
        conn.execute("UPDATE roles SET source = ?, updated_at = datetime('now') WHERE id = ?", (name, role_id))
        conn.commit()
        return {"discovery_source": name}
    if (job_sources_svc.canonical_name(conn, current) or current).lower() == name.lower():
        return {"discovery_source": current}
    return {"discovery_source": current,
            "note": f"role already has discovery source '{current}'; kept it (you mentioned '{name}')"}


def _extract_channel_and_referral(
    conn: sqlite3.Connection, text: str
) -> tuple[Optional[str], Optional[int]]:
    """Application channel only. Where the role was *found* is handled by _extract_discovery."""
    lowered = text.lower()
    channel = None
    if re.search(r"\b(employee\s+)?referral\b|\breferred\b", lowered):
        channel = "referral"  # outranks the platform: "found on LinkedIn, applied via employee referral"
    elif re.search(r"\b(?:applied|submitted)\b[^.]*\b(?:on|via|through|using|at)\s+(?:the\s+)?linkedin", lowered):
        channel = "linkedin"
    elif re.search(r"\b(?:company|careers?)\s+(?:site|page|website)\b|\bdirectly\b", lowered):
        channel = "company_site"
    elif "email" in lowered:
        channel = "email"
    elif "linkedin" in lowered and not _extract_discovery(text):
        channel = "linkedin"

    referral_contact_id = None
    m = re.search(r"referral from (\w+)", text, re.IGNORECASE) or re.search(
        r"referred (?:me )?by (\w+)", text, re.IGNORECASE
    )
    if m:
        name = m.group(1)
        referral_contact_id = contacts_svc.get_or_create_contact(
            conn, name, relationship_type="referral"
        )
    return channel, referral_contact_id


_OUTREACH_RE = re.compile(
    r"\b(?i:contacted|spoke with|talked to|messaged|emailed|called|followed up with|replied to|thanked"
    r"|(?:sent|shared|forwarded|submitted|gave)\b[^.;]{0,60}?\b(?:to|with))\s+"
    r"([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)"
)
_COMPANY_HINT_RE = re.compile(r"\b(?i:from|at|of|with)\s+([A-Z][A-Za-z&.'-]+(?:\s[A-Z][A-Za-z&.'-]+){0,2})")


def _companies_matching(conn: sqlite3.Connection, hint: Optional[str]) -> list[dict]:
    """Companies whose name contains the hint as a whole word ("Harbor" -> "Harbor Staffing")."""
    if not hint:
        return []
    pat = re.compile(rf"\b{re.escape(hint.lower())}\b")
    return [dict(c) for c in conn.execute("SELECT id, name FROM companies") if pat.search(c["name"].lower())]


def _resolve_person(conn: sqlite3.Connection, name: str, hint: Optional[str]) -> tuple[str, Optional[dict]]:
    """Existing contact by full or first name; narrowed by the company hint. Returns (state, contact):
    'found' | 'ambiguous' | 'new' | 'company' (the "name" is really a company, so it is not a person)."""
    rows = conn.execute(
        "SELECT c.id, c.name, c.company_id, co.name AS company FROM contacts c "
        "LEFT JOIN companies co ON co.id = c.company_id").fetchall()
    tok = name.lower().split()
    cands = [dict(r) for r in rows if r["name"].lower().split()[:len(tok)] == tok]
    if hint:
        narrowed = [r for r in cands if r["company"] and hint.lower() in r["company"].lower()]
        cands = narrowed or cands
    if len(cands) == 1:
        return "found", cands[0]
    if len(cands) > 1:
        return "ambiguous", None
    if conn.execute("SELECT 1 FROM companies WHERE lower(name) = ?", (name.lower(),)).fetchone():
        return "company", None
    return "new", None


def _match_interaction(
    conn: sqlite3.Connection, text: str, role_id: Optional[int]
) -> Optional[dict]:
    """Outreach to a person ("emailed Dev", "Sent the resume to Taylor from Harbor"): log an interaction.

    Reuses an existing contact when the name (or first name) matches exactly one, narrowed by a
    "from/at <Company>" hint. A role is linked only when it is unambiguous; otherwise the result says so.
    Status is never changed from here: say "Applied to ..." for that."""
    m = _OUTREACH_RE.search(text)
    if not m:
        return None
    name = m.group(1)
    hm = _COMPANY_HINT_RE.search(text[m.end():])
    hint = hm.group(1) if hm else None
    lowered = text.lower()
    relationship_type = None
    for kw in ("recruiter", "hiring manager", "referral", "interviewer"):
        if kw in lowered:
            relationship_type = kw.replace(" ", "_")
            break
    channel = "linkedin" if "linkedin" in lowered else ("email" if "email" in lowered else None)

    state, existing = _resolve_person(conn, name, hint)
    if state in ("ambiguous", "company"):
        return None   # not sure who this is: keep it as a note instead of guessing
    hint_companies = _companies_matching(conn, hint)
    if state == "found":
        contact_id, contact_name, company_id = existing["id"], existing["name"], existing["company_id"]
    else:
        company_id = hint_companies[0]["id"] if len(hint_companies) == 1 else None
        contact_id = contacts_svc.get_or_create_contact(
            conn, name, company_id=company_id, relationship_type=relationship_type)
        contact_name = name

    if role_id is None:   # link a role only when exactly one active role fits the contact's company or the hint
        cids = [company_id] if company_id else [c["id"] for c in hint_companies]
        if cids:
            marks = ",".join("?" * len(cids))
            rows = conn.execute(
                f"SELECT id FROM roles WHERE company_id IN ({marks}) AND status NOT IN ('rejected','withdrawn','closed')",  # noqa: S608
                cids).fetchall()
            if len(rows) == 1:
                role_id = rows[0]["id"]

    src = sources_svc.create_raw_source(conn, source_type="note", content=text)
    interaction_id = interactions_svc.log_interaction(
        conn, contact_id, text, role_id=role_id, channel=channel,
        direction="outbound", raw_source_id=src["id"],
    )
    out = {
        "kind": "interaction",
        "contact_id": contact_id,
        "contact_name": contact_name,
        "role_id": role_id,
        "interaction_id": interaction_id,
    }
    if hint:
        out["company_hint"] = hint
    if role_id is None:
        out["next_step"] = ("Logged against the contact only. To tie it to a role, add 'for role N' "
                            "(for example: 'Sent the resume to Taylor for role 12').")
    return out


def _match_interview_signal(
    conn: sqlite3.Connection, text: str, role_id: Optional[int]
) -> Optional[dict]:
    lowered = text.lower()
    if "interview" not in lowered and "interviewer" not in lowered:
        return None
    if not role_id:
        return None  # can't attach a signal without knowing which role

    # Find or create an open interview for this role.
    existing = conn.execute(
        "SELECT id FROM interviews WHERE role_id = ? ORDER BY created_at DESC LIMIT 1",
        (role_id,),
    ).fetchone()
    src = sources_svc.create_raw_source(conn, source_type="interview_notes", content=text)
    if existing and not conn.execute(
        "SELECT outcome FROM interviews WHERE id = ?", (existing["id"],)
    ).fetchone()["outcome"]:
        interview_id = existing["id"]
        conn.execute(
            "UPDATE interviews SET notes = COALESCE(notes || ' | ', '') || ?, updated_at = datetime('now') WHERE id = ?",
            (text, interview_id),
        )
        conn.commit()
    else:
        interview_id = interviews_svc.add_interview(
            conn, role_id, notes=text, raw_source_id=src["id"]
        )

    dimension = "technical_ownership"
    for dim, keywords in _SIGNAL_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            dimension = dim
            break

    if any(h in lowered for h in _WEAK_HINTS):
        signal = "Weak"
    elif any(h in lowered for h in _STRONG_HINTS):
        signal = "Strong"
    else:
        signal = "Unknown"

    signal_id = interviews_svc.add_signal(conn, interview_id, dimension, signal, root_cause=None)

    return {
        "kind": "interview_signal",
        "role_id": role_id,
        "interview_id": interview_id,
        "dimension": dimension,
        "signal": signal,
        "signal_id": signal_id,
    }
