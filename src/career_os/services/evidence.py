"""Career evidence database (spec section 12). Never fabricate missing
fields - use 'unknown' or 'needs_evidence', not an invented number.
"""
from __future__ import annotations

import sqlite3
from typing import Optional


def add_evidence(
    conn: sqlite3.Connection,
    *,
    company: Optional[str] = None,
    role: Optional[str] = None,
    project: Optional[str] = None,
    problem: Optional[str] = None,
    technical_context: Optional[str] = None,
    architecture: Optional[str] = None,
    scale: Optional[str] = None,
    ownership: Optional[str] = None,
    stakeholders: Optional[str] = None,
    decisions: Optional[str] = None,
    alternatives: Optional[str] = None,
    tradeoffs: Optional[str] = None,
    metrics: Optional[str] = None,
    thresholds: Optional[str] = None,
    segmentation: Optional[str] = None,
    business_impact: Optional[str] = None,
    technical_impact: Optional[str] = None,
    leadership_impact: Optional[str] = None,
    failure_modes: Optional[str] = None,
    lessons: Optional[str] = None,
    technologies: Optional[str] = None,
    archetypes: Optional[str] = None,
    source_type: str = "extracted_fact",
    confidence: Optional[str] = None,
    raw_source_id: Optional[int] = None,
    skill_names: Optional[list[str]] = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO evidence
           (company, role, project, problem, technical_context, architecture, scale,
            ownership, stakeholders, decisions, alternatives, tradeoffs, metrics,
            thresholds, segmentation, business_impact, technical_impact,
            leadership_impact, failure_modes, lessons, technologies, archetypes,
            source_type, confidence, raw_source_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            company, role, project, problem, technical_context, architecture, scale,
            ownership, stakeholders, decisions, alternatives, tradeoffs, metrics,
            thresholds, segmentation, business_impact, technical_impact,
            leadership_impact, failure_modes, lessons, technologies, archetypes,
            source_type, confidence, raw_source_id,
        ),
    )
    evidence_id = cur.lastrowid
    conn.commit()

    if skill_names:
        from career_os.services import skills as skills_svc
        for name in skill_names:
            skill_id = skills_svc.get_or_create_skill(conn, name)
            skills_svc.link_evidence_skill(conn, evidence_id, skill_id)

    return evidence_id


def list_evidence(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM evidence ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]
