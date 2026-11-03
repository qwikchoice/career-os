"""Full role dossier: everything known about one opportunity, one call."""
from __future__ import annotations

import sqlite3

from career_os.services import applications as applications_svc
from career_os.services import claims as claims_svc
from career_os.services import interactions as interactions_svc
from career_os.services import interviews as interviews_svc
from career_os.services import problem_shape as problem_shape_svc
from career_os.services import roles as roles_svc
from career_os.services import skills as skills_svc


def get_role_dossier(conn: sqlite3.Connection, role_id: int) -> dict | None:
    role = roles_svc.get_role(conn, role_id)
    if not role:
        return None

    requirements = skills_svc.role_requirements(conn, role_id)
    covered_skill_ids = skills_svc.skills_with_evidence(conn)
    for req in requirements:
        req["has_evidence"] = req["id"] in covered_skill_ids

    gaps = [r["name"] for r in requirements if not r["has_evidence"]]

    return {
        "role": role,
        "application": applications_svc.get_application(conn, role_id),
        "requirements": requirements,
        "gaps": gaps,
        "interviews": interviews_svc.interviews_for_role(conn, role_id),
        "interactions": interactions_svc.interactions_for_role(conn, role_id),
        "problem_shape": problem_shape_svc.why_pursue(conn, role_id),
        "claims": claims_svc.claims_for(conn, "role", role_id),
    }
