"""Role ingestion (`add-job`) and role queries.

Fit scoring is intentionally qualitative (role_tier 1-3, fit_confidence
High/Medium/Low) per spec section 11: never a fabricated numeric percentage.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from career_os import classify, heuristics
from career_os.services import claims as claims_svc
from career_os.services import companies as companies_svc
from career_os.services import skills as skills_svc
from career_os.services import sources as sources_svc


def normalize_channel(raw: str) -> str:
    """Canonical application-channel values; 'employee referral' and 'referral' are the same channel."""
    low = raw.strip().lower().replace("-", " ")
    if "referral" in low or "referred" in low:
        return "referral"
    if "linkedin" in low:
        return "linkedin"
    if "company" in low or "career" in low or "direct" in low:
        return "company_site"
    if "email" in low or "recruiter" in low:
        return "email"
    return low.replace(" ", "_")


def add_job(
    conn: sqlite3.Connection,
    company: str,
    *,
    title: Optional[str] = None,
    jd_text: Optional[str] = None,
    jd_file: Optional[str] = None,
    url: Optional[str] = None,
    location: Optional[str] = None,
    employment_type: Optional[str] = None,
    compensation_text: Optional[str] = None,
    source: Optional[str] = None,
    source_posted_date: Optional[str] = None,
    applied_via: Optional[str] = None,
    job_code: Optional[str] = None,
) -> dict:
    """Create (or detect duplicate of) a role. Returns a result dict.

    `company` is required and supplied by the caller rather than guessed -
    the heuristic title/archetype guesser is not trusted to extract the
    company name reliably, and a wrong company is worse than asking for it.
    """
    if source:
        # Discovery source: map to a known job source (or capture a new one); 'manual' is not a source.
        from career_os.services import job_sources as job_sources_svc
        source = job_sources_svc.canonical_name(conn, source) or (
            source if source.strip().lower() in ("manual", "unknown")
            else job_sources_svc.resolve_or_create(conn, source)["name"])

    full_text = jd_text
    if jd_file:
        file_path = Path(jd_file)
        full_text = file_path.read_text(encoding="utf-8")

    raw_source_id = None
    if full_text or jd_file:
        src = sources_svc.create_raw_source(
            conn,
            source_type="job_posting",
            content=full_text if not jd_file else None,
            content_path=jd_file,
            origin=url or source,
        )
        raw_source_id = src["id"]

    company_id = companies_svc.get_or_create_company(conn, company)

    classification = classify.classify_role(full_text) if full_text else None
    resolved_title = title or (classification.guessed_title if classification else None)
    if not resolved_title:
        resolved_title = "Unknown Title"

    canon_key = heuristics.canonical_key(company, resolved_title, job_code)

    dup = conn.execute(
        "SELECT id FROM roles WHERE canonical_key = ?", (canon_key,)
    ).fetchone()
    if dup:
        return {"role_id": dup["id"], "duplicate": True, "canonical_key": canon_key}

    archetype = classification.archetype if classification else None
    confidence = classification.archetype_confidence if classification else "Low"

    role_tier, fit_reason = _estimate_role_tier(conn, company_id, archetype, confidence)

    cur = conn.execute(
        """INSERT INTO roles
           (company_id, title, location, employment_type,
            compensation_text, job_url, source, source_posted_date,
            archetype, role_tier, fit_confidence, fit_reason, canonical_key, raw_source_id, job_code)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            company_id, resolved_title, location, employment_type,
            compensation_text, url, source, source_posted_date,
            archetype, role_tier, confidence, fit_reason, canon_key, raw_source_id, job_code,
        ),
    )
    role_id = cur.lastrowid
    conn.commit()

    if classification:
        claims_svc.record_claim(
            conn,
            claim_text=(
                f"archetype={archetype} via {classification.provider} "
                f"(scores={classification.archetype_scores})"
            ),
            subject_type="role",
            subject_id=role_id,
            source_type="model_inference",
            raw_source_id=raw_source_id,
            verification_status="unverified",
            confidence=confidence,
        )
        for skill_name in classification.matched_skills:
            skill_id = skills_svc.get_or_create_skill(conn, skill_name)
            skills_svc.link_role_skill(conn, role_id, skill_id, "mentioned")

    primary_gap = _compute_primary_gap(conn, role_id)
    if primary_gap:
        conn.execute(
            "UPDATE roles SET primary_gap = ?, updated_at = datetime('now') WHERE id = ?",
            (primary_gap, role_id),
        )
        conn.commit()

    if applied_via:
        # Application channel is separate from the discovery source and never overwrites it.
        from career_os.services import applications as applications_svc
        app_id = applications_svc.get_or_create_application(conn, role_id)
        conn.execute("UPDATE applications SET channel = ?, updated_at = datetime('now') WHERE id = ?",
                     (normalize_channel(applied_via), app_id))
        conn.commit()

    shape = None
    if full_text:
        from career_os.services import problem_shape as shape_svc  # local: avoids import cycle
        shape = shape_svc.analyze_role(conn, role_id, text=full_text)

    return {
        "role_id": role_id,
        "duplicate": False,
        "discovery_source": source,
        "application_channel": normalize_channel(applied_via) if applied_via else None,
        "problem_shape": shape["problem_shape"] if shape else None,
        "depth_match": shape["depth_match"] if shape else None,
        "archetype": archetype,
        "fit_confidence": confidence,
        "role_tier": role_tier,
        "primary_gap": primary_gap,
        "matched_skills": classification.matched_skills if classification else [],
        "classifier": classification.provider if classification else None,
    }


def attach_jd(conn: sqlite3.Connection, role_id: int, jd_text: str) -> Optional[dict]:
    """Attach (or replace) the JD on an existing role and re-derive everything that came from JD text.

    For roles added before the JD was available. The original text is preserved as a raw source; the
    archetype, role tier, skills, gap and problem shape are re-inferred (model_inference claims). A
    previously stored raw source is never deleted, only superseded as the role's current one.
    """
    role = get_role(conn, role_id)
    if not role:
        return None
    src = sources_svc.create_raw_source(conn, source_type="job_posting", content=jd_text, origin=role.get("job_url") or role.get("source"))
    classification = classify.classify_role(jd_text)
    confidence = classification.archetype_confidence
    role_tier, fit_reason = _estimate_role_tier(conn, role["company_id"], classification.archetype, confidence)
    conn.execute(
        """UPDATE roles SET raw_source_id = ?, archetype = ?, role_tier = ?, fit_confidence = ?, fit_reason = ?,
           updated_at = datetime('now') WHERE id = ?""",
        (src["id"], classification.archetype, role_tier, confidence, fit_reason, role_id),
    )
    conn.commit()
    claims_svc.record_claim(
        conn, claim_text=f"archetype={classification.archetype} via {classification.provider} from attached JD "
                         f"(scores={classification.archetype_scores})",
        subject_type="role", subject_id=role_id, source_type="model_inference", raw_source_id=src["id"],
        verification_status="unverified", confidence=confidence)
    for skill_name in classification.matched_skills:
        skills_svc.link_role_skill(conn, role_id, skills_svc.get_or_create_skill(conn, skill_name), "mentioned")
    gap = _compute_primary_gap(conn, role_id)
    conn.execute("UPDATE roles SET primary_gap = ? WHERE id = ?", (gap, role_id))
    conn.commit()
    from career_os.services import problem_shape as shape_svc
    shape = shape_svc.analyze_role(conn, role_id, text=jd_text)
    return {"role_id": role_id, "archetype": classification.archetype, "fit_confidence": confidence,
            "role_tier": role_tier, "classifier": classification.provider,
            "matched_skills": classification.matched_skills, "primary_gap": gap,
            "problem_shape": shape["problem_shape"], "depth_match": shape["depth_match"],
            "critical_depth_lever": shape["critical_depth_lever"], "raw_source_duplicate": src["duplicate"]}


# role_tier is stored as 1/2/3 (see _estimate_role_tier for why); people read these words instead.
TIER_LABELS = {1: "Top priority", 2: "Medium priority", 3: "Low priority"}
COMPANY_TIER_LABELS = {"A": "A: top target", "B": "B: good target", "C": "C: lower target"}


def set_role_tier(conn: sqlite3.Connection, role_id: int, tier: int, note: Optional[str] = None) -> Optional[dict]:
    """User override of a role's priority tier (1 top, 2 medium, 3 low). Recorded as a user_confirmed claim,
    so a later JD attach or re-analysis does not silently undo it."""
    if tier not in TIER_LABELS:
        raise ValueError("tier must be 1, 2 or 3")
    role = get_role(conn, role_id)
    if not role:
        return None
    reason = "Set by user" + (f": {note}" if note else "")
    conn.execute("UPDATE roles SET role_tier = ?, fit_reason = ?, updated_at = datetime('now') WHERE id = ?",
                 (tier, reason, role_id))
    conn.commit()
    claims_svc.record_claim(
        conn, f"role_tier={tier} ({TIER_LABELS[tier]}); {reason}", "role", role_id, "user_confirmed",
        verification_status="user_confirmed", confidence="High")
    return {"role_id": role_id, "role_tier": tier, "label": TIER_LABELS[tier], "was": role["role_tier"]}


def tier_label(tier) -> str:
    return TIER_LABELS.get(tier, "Not rated")


def _estimate_role_tier(
    conn: sqlite3.Connection, company_id: int, archetype: Optional[str], confidence: str
) -> tuple[Optional[int], str]:
    row = conn.execute("SELECT tier FROM companies WHERE id = ?", (company_id,)).fetchone()
    company_tier = row["tier"] if row else None

    if company_tier == "A" and archetype and confidence in ("High", "Medium"):
        return 1, "Tier-A company target + clear archetype match"
    if company_tier in ("A", "B") and archetype:
        return 2, "Target-tier company + archetype signal present"
    if archetype is None:
        return 3, "No clear archetype signal from JD text (needs_evidence)"
    return 2, "Default: some signal, not yet confirmed"


def _compute_primary_gap(conn: sqlite3.Connection, role_id: int) -> Optional[str]:
    """First required/mentioned skill on this role with zero linked evidence."""
    covered = skills_svc.skills_with_evidence(conn)
    reqs = skills_svc.role_requirements(conn, role_id)
    for req in reqs:
        if req["id"] not in covered:
            return req["name"]
    return None


def get_role(conn: sqlite3.Connection, role_id: int) -> Optional[dict]:
    row = conn.execute(
        """SELECT r.*, c.name AS company_name, c.tier AS company_tier
           FROM roles r
           JOIN companies c ON c.id = r.company_id
           WHERE r.id = ?""",
        (role_id,),
    ).fetchone()
    return dict(row) if row else None


def list_roles(conn: sqlite3.Connection, status: Optional[str] = None) -> list[dict]:
    if status:
        rows = conn.execute(
            """SELECT r.*, c.name AS company_name FROM roles r
               JOIN companies c ON c.id = r.company_id
               WHERE r.status = ? ORDER BY r.updated_at DESC""",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT r.*, c.name AS company_name FROM roles r
               JOIN companies c ON c.id = r.company_id
               ORDER BY r.updated_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]
