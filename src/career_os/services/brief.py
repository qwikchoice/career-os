"""Combined query: for the top-N active roles, what is the referral path, where did the
role come from, what are the top learning gaps, which stored resources fit, and what
should happen next. One call, assembled from the same stored facts every other command uses.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from career_os.services import job_sources as job_sources_svc
from career_os.services import learning as learning_svc
from career_os.services import referrals as referrals_svc

_TERMINAL = ("rejected", "withdrawn", "closed", "offer")
_CTIER = {"A": 0, "B": 1, "C": 2, "Watchlist": 3}
_SHAPE = {"generalist_specialist": 0, "generalist": 1, None: 2, "unknown": 2, "specialist": 3}
_INTERVIEW_STAGES = ("recruiter_screen", "hiring_manager", "interview_loop", "final_round")


def priority_roles(conn: sqlite3.Connection, top: int = 5) -> list[dict]:
    rows = [dict(r) for r in conn.execute(
        """SELECT r.id, r.title, r.role_tier, r.problem_shape, r.source, r.updated_at,
                  c.name AS company, c.tier AS company_tier,
                  COALESCE(a.status, 'planned') AS application_status, a.channel AS application_channel
           FROM roles r JOIN companies c ON c.id = r.company_id LEFT JOIN applications a ON a.role_id = r.id
           WHERE r.status NOT IN ('rejected','withdrawn','closed','offer')""")]
    rows.sort(key=lambda r: (r["role_tier"] or 9, _CTIER.get(r["company_tier"], 4), _SHAPE.get(r["problem_shape"], 2)))
    return rows[:top]


def _next_action(r: dict, paths: list[dict], plan: dict) -> str:
    today = date.today().isoformat()
    if r["application_status"] in _INTERVIEW_STAGES:
        first = plan["highest_priority"][0]["resource"]["title"] if plan["highest_priority"] else "rehearse flagship stories"
        return f"Interview prep: {first}"
    for p in paths:
        who = p["contact_name"]
        if p["status"] == "submitted":
            return f"Referral submitted by {who}: wait; follow up if nothing by {p['follow_up_date'] or 'one week out'}"
        if p["status"] == "requested":
            due = p["follow_up_date"] and p["follow_up_date"] <= today
            return f"Follow up with {who} (referral requested)" if due else f"Waiting on {who} (referral requested)"
    unused = [p for p in paths if p["status"] in referrals_svc.UNUSED]
    if unused:
        return f"Ask {unused[0]['contact_name']} to refer you: career update \"Ask {unused[0]['contact_name']} to refer me for role {r['id']}\""
    if not paths and (r["role_tier"] == 1 or r["company_tier"] == "A"):
        return f"Find a referrer at {r['company']} (check LinkedIn connections) before applying"
    if r["application_status"] == "planned":
        return "Apply" + (" (referral channel)" if paths else "")
    if r["application_status"] in ("applied", "referred"):
        return "Track response; follow up if nothing in a week"
    return "Review status"


def brief(conn: sqlite3.Connection, top: int = 5, minutes: int = learning_svc.DEFAULT_BUDGET_MINUTES) -> list[dict]:
    out = []
    for r in priority_roles(conn, top):
        paths = referrals_svc.paths_for_role(conn, r["id"])
        plan = learning_svc.learning_plan(conn, r["id"], minutes)
        src = job_sources_svc.canonical_name(conn, r["source"]) or r["source"]
        out.append({
            **r,
            "referral_paths": [{"contact": p["contact_name"], "status": p["status"], "level": p["level"],
                                "priority": referrals_svc.priority_for(conn, p["id"])} for p in paths],
            "discovery_source": src if src and src != "manual" else None,
            "learning_gaps": ([x["topic"] for x in plan["highest_priority"]]
                              + [g["topic"] for g in plan["gaps_without_resource"]])[:3],
            "resources": [x["resource"]["title"] for x in plan["highest_priority"]],
            "next_action": _next_action(r, paths, plan),
        })
    return out
