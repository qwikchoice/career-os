"""Problem-shape analysis (Generalist + Specialist Spike framework; see STRATEGY.md).

Two kinds of data meet here, and they are kept apart on purpose:
  * JD-derived classification (rate of change, interconnectedness, lever,
    judgment, shape). That is a `model_inference` about the JD, recorded in
    `claims`. A `user_confirmed` claim for a field is never overwritten.
  * User-specific depth match. That comes from linked Career Evidence rows
    (evidence_spikes), never from resume keywords.

Everything is qualitative. No numeric scores.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from career_os import heuristics
from career_os.services import claims as claims_svc

CAREER_OS_ROOT = Path(__file__).resolve().parents[3]

SPIKES = {
    "search": ("Search / Retrieval / Relevance",
               "Retrieval, ranking, recommendations, personalization, relevance, RAG retrieval",
               "metrics"),
    "eval": ("AI Evaluation / Quality",
             "Human evaluation, HITL, golden datasets, experimentation, launch thresholds, regression, LLM evals",
             "thresholds"),
    "platform": ("Production AI / Platform",
                 "Cloud infrastructure, deployment, launch readiness, reliability, latency, cost, observability",
                 "failure_modes"),
}
# Evidence field that must be known before a spike can read as 'strong'.
# Chosen per spike so e.g. evaluation depth cannot be claimed without thresholds.

# (company, project) -> spike codes. HYPOTHESES from the framework brief, recorded
# as model_inference claims; the user can confirm or unlink.
SPIKE_LINK_HYPOTHESES = {
    ("Northwind Commerce", "Marketplace Search Relevance"): ["search", "eval"],
    ("Contoso Retail", "Multi-country Search Optimization"): ["search", "eval"],
    ("Contoso Retail", "Voice Assistant International Launch"): ["eval"],
    ("Fabrikam Cloud", "Regional Capacity Launches"): ["platform"],
    ("Lumen Labs", "Enterprise RAG Platform"): ["search", "eval", "platform"],
    ("Tailspin Apps", "Release Process and Personalization"): ["platform"],
    ("Adatum Systems", "Account Release Management"): ["platform"],
}
LEVER_HYPOTHESES = {
    ("Fabrikam Cloud", "Regional Capacity Launches"): "Capacity economics / automation",
    ("Contoso Retail", "Voice Assistant International Launch"): "Eligibility / evaluation",
    ("Contoso Retail", "Multi-country Search Optimization"): "Relevance / evaluation",
    ("Northwind Commerce", "Marketplace Search Relevance"): "Relevance / ranking metrics",
    ("Lumen Labs", "Enterprise RAG Platform"): "Retrieval / evaluation",
}

SHAPE_FIELDS = [
    "problem_shape", "rate_of_change", "interconnectedness", "critical_depth_lever",
    "depth_lever_importance", "judgment_requirement",
]
CONFIRMABLE = SHAPE_FIELDS + [
    "depth_match", "judgment_surface_expansion", "specialist_spike_deepening",
]
ALLOWED = {
    "problem_shape": {"generalist", "generalist_specialist", "specialist", "unknown"},
    "depth_match": {"strong", "partial", "weak", "unknown"},
}
for _f in ("rate_of_change", "interconnectedness", "depth_lever_importance", "judgment_requirement",
           "judgment_surface_expansion", "specialist_spike_deepening"):
    ALLOWED[_f] = {"high", "medium", "low", "unknown"}

SHAPE_LABELS = {
    "generalist": "Generalist",
    "generalist_specialist": "Generalist + Specialist",
    "specialist": "Specialist",
    "unknown": "Unknown",
}


# --------------------------------------------------------------------------
# Spikes and evidence
# --------------------------------------------------------------------------
def ensure_spikes(conn: sqlite3.Connection) -> None:
    for code, (name, desc, _) in SPIKES.items():
        conn.execute(
            "INSERT OR IGNORE INTO depth_spikes (code, name, description) VALUES (?, ?, ?)",
            (code, name, desc),
        )
    conn.commit()


def seed_spike_links(conn: sqlite3.Connection) -> dict:
    """Link existing evidence rows to spikes and set lever hypotheses.

    Idempotent. Only fills `critical_lever` when it is empty, and records every
    link/lever as a model_inference claim so none reads as verified.
    """
    ensure_spikes(conn)
    spike_ids = {r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM depth_spikes")}
    links = levers = 0
    for (company, project), codes in SPIKE_LINK_HYPOTHESES.items():
        row = conn.execute(
            "SELECT id, critical_lever FROM evidence WHERE company = ? AND project = ?", (company, project)
        ).fetchone()
        if not row:
            continue
        for code in codes:
            cur = conn.execute(
                "INSERT OR IGNORE INTO evidence_spikes (evidence_id, spike_id) VALUES (?, ?)",
                (row["id"], spike_ids[code]),
            )
            if cur.rowcount:
                links += 1
                claims_svc.record_claim(
                    conn, f"evidence supports depth spike '{code}' (hypothesis from framework brief)",
                    "evidence", row["id"], "model_inference", verification_status="unverified",
                    confidence="Low",
                )
        lever = LEVER_HYPOTHESES.get((company, project))
        if lever and not row["critical_lever"]:
            conn.execute("UPDATE evidence SET critical_lever = ? WHERE id = ?", (lever, row["id"]))
            levers += 1
            claims_svc.record_claim(
                conn, f"critical_lever='{lever}' (hypothesis; not verified)", "evidence", row["id"],
                "model_inference", verification_status="unverified", confidence="Low",
            )
    conn.commit()
    return {"spike_links_added": links, "lever_hypotheses_set": levers}


def _known(value: Optional[str]) -> bool:
    if value is None:
        return False
    v = value.strip().lower()
    return bool(v) and v != "unknown" and "needs_evidence" not in v


def spike_strength(conn: sqlite3.Connection, code: str) -> dict:
    """Derive a spike's strength from linked evidence. Never stored.

    strong  = >=2 'proven' rows (metrics + ownership known) AND at least one row
              where this spike's marker field is known
    partial = at least one linked row
    weak    = no linked evidence
    """
    ensure_spikes(conn)
    marker = SPIKES[code][2]
    rows = conn.execute(
        """SELECT e.* FROM evidence e
           JOIN evidence_spikes es ON es.evidence_id = e.id
           JOIN depth_spikes s ON s.id = es.spike_id
           WHERE s.code = ?""",
        (code,),
    ).fetchall()
    proven = [r for r in rows if _known(r["metrics"]) and _known(r["ownership"])]
    marker_known = [r for r in rows if _known(r[marker])]
    if len(proven) >= 2 and marker_known:
        strength = "strong"
    elif rows:
        strength = "partial"
    else:
        strength = "weak"
    missing = None
    if strength != "strong" and rows:
        missing = f"'{marker}' is unknown/needs_evidence on all {len(rows)} linked evidence row(s)" \
            if not marker_known else f"only {len(proven)} proven evidence row(s) (need 2)"
    elif strength == "weak":
        missing = "no linked evidence"
    return {
        "code": code, "name": SPIKES[code][0], "strength": strength,
        "linked": [{"id": r["id"], "company": r["company"], "project": r["project"]} for r in rows],
        "proven_count": len(proven), "marker": marker, "missing": missing,
    }


# --------------------------------------------------------------------------
# Role analysis
# --------------------------------------------------------------------------
def role_text(conn: sqlite3.Connection, role: dict) -> Optional[str]:
    if not role.get("raw_source_id"):
        return None
    row = conn.execute(
        "SELECT content, content_path FROM raw_sources WHERE id = ?", (role["raw_source_id"],)
    ).fetchone()
    if not row:
        return None
    if row["content"]:
        return row["content"]
    if row["content_path"]:
        p = Path(row["content_path"])
        if not p.is_absolute():
            p = CAREER_OS_ROOT / p
        if p.exists():
            return p.read_text(encoding="utf-8", errors="replace")
    return None


def _confirmed_fields(conn: sqlite3.Connection, role_id: int) -> set[str]:
    out = set()
    for c in claims_svc.claims_for(conn, "role", role_id):
        if c["source_type"] == "user_confirmed" and c["claim_text"].startswith("problem_shape."):
            out.add(c["claim_text"].split("=", 1)[0].split(".", 1)[1])
    return out


def _lever_spike(lever: Optional[str]) -> Optional[str]:
    return heuristics.LEVERS[lever][1] if lever in heuristics.LEVERS else None


def _depth_match(conn: sqlite3.Connection, lever: Optional[str]) -> dict:
    if not lever or lever not in heuristics.LEVERS:
        return {"depth_match": "unknown", "reason": "no critical depth lever identified",
                "spikes": [], "missing": None}
    _, spike_code, skills = heuristics.LEVERS[lever]
    if spike_code:
        s = spike_strength(conn, spike_code)
        names = ", ".join(f"{e['company']}: {e['project']}" for e in s["linked"]) or "none"
        return {
            "depth_match": s["strength"],
            "reason": f"lever maps to spike '{s['name']}' ({s['strength']}); evidence: {names}",
            "spikes": [s], "missing": s["missing"],
        }
    if lever == heuristics.DEEP_SPECIALIST_LEVER:
        return {"depth_match": "weak",
                "reason": "low-level performance depth; no Career Evidence rows support it",
                "spikes": [], "missing": "no evidence of kernel/silicon/serving-efficiency depth"}
    covered = []
    for skill in skills:
        for r in conn.execute(
            """SELECT DISTINCT e.company, e.project FROM evidence e
               JOIN evidence_skills es ON es.evidence_id = e.id
               JOIN skills s ON s.id = es.skill_id WHERE s.name = ? COLLATE NOCASE""", (skill,),
        ).fetchall():
            covered.append(f"{r['company']}: {r['project']}")
    if covered:
        return {"depth_match": "partial",
                "reason": f"no durable spike for this lever; skill-linked evidence: {', '.join(sorted(set(covered)))}",
                "spikes": [], "missing": "lever is not one of the three durable spikes"}
    return {"depth_match": "weak", "reason": "no evidence linked to this lever",
            "spikes": [], "missing": "no linked evidence"}


def _compounding(inter: str, judgment: str, importance: str, depth: dict) -> tuple[str, str]:
    if inter == "high" and judgment == "high":
        surface = "high"
    elif inter == "unknown" and judgment == "unknown":
        surface = "unknown"
    elif judgment == "low" or inter == "low":
        surface = "low"
    else:
        surface = "medium"
    if depth["spikes"] and importance == "high":
        deepening = "high"
    elif depth["spikes"] and importance == "medium":
        deepening = "medium"
    elif importance == "unknown":
        deepening = "unknown"
    else:
        deepening = "low"
    return surface, deepening


def analyze_role(conn: sqlite3.Connection, role_id: int, text: Optional[str] = None) -> Optional[dict]:
    """Classify problem shape for one role and persist it. Returns the analysis dict.

    Skips any field the user has confirmed. With no JD text available,
    everything stays 'unknown' (never guessed from the title alone).
    """
    from career_os.services import roles as roles_svc  # local: roles imports this module

    role = roles_svc.get_role(conn, role_id)
    if not role:
        return None
    ensure_spikes(conn)
    text = text if text is not None else role_text(conn, role)
    if not text:
        shape = {f: "unknown" for f in SHAPE_FIELDS}
        shape["critical_depth_lever"] = None
        shape["reasons"] = {"problem_shape": "no JD text stored for this role"}
        shape["pmo_risk"] = False
    else:
        shape = heuristics.infer_problem_shape(text, role["title"])

    confirmed = _confirmed_fields(conn, role_id)
    for f in SHAPE_FIELDS:
        if f in confirmed:
            shape[f] = role.get(f)  # user's value wins

    depth = _depth_match(conn, shape["critical_depth_lever"])
    surface, deepening = _compounding(
        shape["interconnectedness"], shape["judgment_requirement"], shape["depth_lever_importance"], depth
    )
    values = {
        **{f: shape[f] for f in SHAPE_FIELDS},
        "depth_match": role["depth_match"] if "depth_match" in confirmed else depth["depth_match"],
        "depth_match_reason": depth["reason"],
        "missing_depth_evidence": depth["missing"],
        "judgment_surface_expansion": role["judgment_surface_expansion"] if "judgment_surface_expansion" in confirmed else surface,
        "specialist_spike_deepening": role["specialist_spike_deepening"] if "specialist_spike_deepening" in confirmed else deepening,
    }
    sets = ", ".join(f"{k} = ?" for k in values)
    conn.execute(
        f"UPDATE roles SET {sets}, updated_at = datetime('now') WHERE id = ?",  # noqa: S608 - fixed keys
        (*values.values(), role_id),
    )
    conn.commit()

    claims_svc.record_claim(
        conn,
        claim_text=("problem_shape analysis (heuristic, from JD): "
                    + "; ".join(f"{k}={values[k]}" for k in SHAPE_FIELDS)
                    + f"; depth_match={values['depth_match']}; reasons={shape['reasons']}"),
        subject_type="role", subject_id=role_id, source_type="model_inference",
        raw_source_id=role.get("raw_source_id"), verification_status="unverified",
        confidence="Low" if shape["problem_shape"] == "unknown" else "Medium",
    )
    return {"role_id": role_id, **values, "reasons": shape["reasons"], "pmo_risk": shape["pmo_risk"],
            "spikes": depth["spikes"]}


def analyze_all(conn: sqlite3.Connection, only_missing: bool = True) -> list[dict]:
    q = "SELECT id FROM roles" + (" WHERE problem_shape IS NULL" if only_missing else "")
    return [analyze_role(conn, r["id"]) for r in conn.execute(q).fetchall()]


def confirm_field(conn: sqlite3.Connection, role_id: int, field: str, value: str) -> None:
    """Record a user override. Writes the column and a user_confirmed claim."""
    if field not in CONFIRMABLE and field != "critical_depth_lever":
        raise ValueError(f"cannot confirm '{field}'")
    if field in ALLOWED and value not in ALLOWED[field]:
        raise ValueError(f"{field} must be one of {sorted(ALLOWED[field])}")
    conn.execute(
        f"UPDATE roles SET {field} = ?, updated_at = datetime('now') WHERE id = ?",  # noqa: S608 - allowlisted
        (value, role_id),
    )
    conn.commit()
    claims_svc.record_claim(
        conn, f"problem_shape.{field}={value}", "role", role_id, "user_confirmed",
        verification_status="user_confirmed", confidence="High",
    )


# --------------------------------------------------------------------------
# Interpretation: why pursue, recommendation, learning
# --------------------------------------------------------------------------
def recommend(r: dict) -> str:
    shape, depth, judgment = r.get("problem_shape"), r.get("depth_match"), r.get("judgment_requirement")
    if shape == "generalist_specialist":
        if depth in ("strong", "partial"):
            return "Prioritize: broad systems role with a lever that maps to your evidence."
        return "Pursue selectively: right shape, but the depth lever lacks supporting evidence. Close that gap first."
    if shape == "generalist":
        if judgment == "low":
            return "Deprioritize: pure-generalist risk (coordination-heavy, no depth lever, little framing judgment)."
        return ("Lower priority unless a real technical lever surfaces: ask in the screen which technical/product "
                "decisions the role owns. It broadens judgment surface but will not deepen a spike.")
    if shape == "specialist":
        return "Deprioritize: depth is the main differentiator and you would compete with long-practice specialists."
    return "Hold: not enough JD signal to classify. Add the full JD or confirm fields with `career shape-set`."


def interpretation(r: dict) -> str:
    shape = r.get("problem_shape")
    if shape == "generalist_specialist":
        return ("Needs whole-system judgment and credibility on one lever: the target role shape. "
                f"Lever: {r.get('critical_depth_lever')}. Depth match: {r.get('depth_match')}.")
    if shape == "generalist":
        return ("Broad and interconnected, but the JD shows no dominant depth lever. Risk: it could reduce to "
                "coordination, executive reporting and dependency tracking if no real technical/product decision rights exist.")
    if shape == "specialist":
        return ("Narrow problem where one technical lever decides outcomes. Risk: directly competing with "
                "specialists who have spent years in the domain; breadth is secondary here.")
    return "Unclassified (confidence too low)."


def learning_recommendations(conn: sqlite3.Connection, role_id: int) -> list[dict]:
    """Split a role's evidence gaps into generalist literacy vs specialist depth.

    A gap is 'specialist depth' only if it sits on one of the three spikes
    AND the role's lever importance is high; everything else is literacy or backlog.
    Callers should still run the six-question learning check (STRATEGY.md).
    """
    from career_os.services import roles as roles_svc, skills as skills_svc  # noqa: PLC0415

    role = roles_svc.get_role(conn, role_id)
    covered = skills_svc.skills_with_evidence(conn)
    spike_skill_names = {
        "search": {"search ranking", "relevance", "retrieval", "ndcg", "rag", "recommendation systems", "personalization"},
        "eval": {"ml evaluation", "golden dataset", "hitl", "annotation", "a/b testing"},
        "platform": {"aws", "cloud infrastructure", "latency", "scalability", "production readiness", "release management"},
    }
    lever_spike = _lever_spike(role.get("critical_depth_lever"))
    out = []
    for req in skills_svc.role_requirements(conn, role_id):
        if req["id"] in covered:
            continue
        name = req["name"].lower()
        on_spike = next((c for c, names in spike_skill_names.items() if name in names), None)
        if on_spike and on_spike == lever_spike and role.get("depth_lever_importance") == "high":
            kind, note = "specialist_depth", "maps to a spike and the role's lever: invest if it matters within ~6 weeks"
        elif on_spike:
            kind, note = "specialist_depth_backlog", "maps to a spike but not this role's main lever: backlog unless it recurs"
        else:
            kind, note = "generalist_literacy", "learn enough to ask good questions and spot bad assumptions"
        out.append({"skill": req["name"], "kind": kind, "note": note})
    return out


def why_pursue(conn: sqlite3.Connection, role_id: int) -> Optional[dict]:
    from career_os.services import roles as roles_svc  # noqa: PLC0415

    role = roles_svc.get_role(conn, role_id)
    if not role:
        return None
    if role.get("problem_shape") is None:
        analyze_role(conn, role_id)
        role = roles_svc.get_role(conn, role_id)
    lever = role.get("critical_depth_lever")
    spike_code = _lever_spike(lever)
    spike = spike_strength(conn, spike_code) if spike_code else None
    return {
        "role": role,
        "problem_shape_label": SHAPE_LABELS.get(role.get("problem_shape"), "Unknown"),
        "breadth_fit": {"rate_of_change": role.get("rate_of_change"),
                        "interconnectedness": role.get("interconnectedness"),
                        "judgment_requirement": role.get("judgment_requirement")},
        "critical_depth_lever": lever,
        "depth_lever_importance": role.get("depth_lever_importance"),
        "depth_match": role.get("depth_match"),
        "depth_match_reason": role.get("depth_match_reason"),
        "supporting_evidence": spike["linked"] if spike else [],
        "gaps": role.get("missing_depth_evidence"),
        "career_compounding": {"judgment_surface_expansion": role.get("judgment_surface_expansion"),
                               "specialist_spike_deepening": role.get("specialist_spike_deepening")},
        "interpretation": interpretation(role),
        "recommendation": recommend(role),
        "learning": learning_recommendations(conn, role_id),
        "provenance": "model_inference from the JD; depth match derived from linked Career Evidence",
    }


def shape_signal(conn: sqlite3.Connection) -> Optional[dict]:
    """Weekly-review input. Counts only; returns None when it would not change a decision."""
    rows = conn.execute(
        """SELECT r.problem_shape, COALESCE(a.status, 'planned') AS status
           FROM roles r LEFT JOIN applications a ON a.role_id = r.id
           WHERE r.problem_shape IS NOT NULL"""
    ).fetchall()
    if not rows:
        return None
    advanced = {"recruiter_screen", "hiring_manager", "interview_loop", "final_round", "offer"}
    by_shape: dict[str, dict] = {}
    for r in rows:
        d = by_shape.setdefault(r["problem_shape"], {"roles": 0, "advanced": 0})
        d["roles"] += 1
        d["advanced"] += r["status"] in advanced
    total = sum(d["roles"] for d in by_shape.values())
    notes = []
    if by_shape.get("generalist", {}).get("roles", 0) * 2 > total:
        notes.append("More than half of tracked roles are pure-generalist: check for PMO drift.")
    if sum(d["advanced"] for d in by_shape.values()) == 0:
        notes.append("No role has advanced past application yet, so no shape-vs-conversion conclusion is supported.")
    drift_or_conflict = [n for n in notes if "PMO drift" in n]
    if not drift_or_conflict and total < 3:
        return None
    return {"by_shape": by_shape, "notes": notes}
