"""Executive career review (spec section 26/39).

Rule-based, not LLM-based, for V0.1: every section is a direct query result,
not a generated narrative, so nothing here can be a hallucinated claim.
Ends with exactly one Pipeline, one Conversion, one Proof action.
"""
from __future__ import annotations

import sqlite3
from collections import Counter

from career_os.services import interviews as interviews_svc
from career_os.services import job_sources as job_sources_svc
from career_os.services import learning as learning_svc
from career_os.services import pipeline as pipeline_svc
from career_os.services import referrals as referrals_svc
from career_os.services import problem_shape as problem_shape_svc


def generate_review(conn: sqlite3.Connection, period_days: int = 7) -> dict:
    pipeline_rows = conn.execute(
        """SELECT r.id, c.name AS company, r.title, r.role_tier, r.archetype,
                  a.status, r.updated_at
           FROM roles r
           JOIN companies c ON c.id = r.company_id
           LEFT JOIN applications a ON a.role_id = r.id
           WHERE julianday('now') - julianday(r.updated_at) <= ?
           ORDER BY r.updated_at DESC""",
        (period_days,),
    ).fetchall()
    pipeline_moved = [dict(r) for r in pipeline_rows]

    recent_signals = conn.execute(
        """SELECT isg.*, r.title, c.name AS company
           FROM interview_signals isg
           JOIN interviews iv ON iv.id = isg.interview_id
           JOIN roles r ON r.id = iv.role_id
           JOIN companies c ON c.id = r.company_id
           WHERE julianday('now') - julianday(isg.created_at) <= ?
           ORDER BY isg.created_at DESC""",
        (period_days,),
    ).fetchall()
    conversion_signals = [dict(r) for r in recent_signals]

    recent_evidence = conn.execute(
        """SELECT id, company, role, project, created_at FROM evidence
           WHERE julianday('now') - julianday(created_at) <= ?
           ORDER BY created_at DESC""",
        (period_days,),
    ).fetchall()
    proof_added = [dict(r) for r in recent_evidence]

    stalled = pipeline_svc.stalled(conn, days=14)

    archetype_counts = Counter(
        r["archetype"] for r in pipeline_svc.get_pipeline(conn) if r["archetype"]
    )
    continue_archetype = archetype_counts.most_common(1)[0][0] if archetype_counts else None

    gap_counts = Counter()
    for row in conn.execute(
        "SELECT primary_gap FROM roles WHERE primary_gap IS NOT NULL"
    ).fetchall():
        gap_counts[row["primary_gap"]] += 1
    start_gap = gap_counts.most_common(1)[0][0] if gap_counts else None

    double_down_skill = None
    row = conn.execute(
        """SELECT s.name, COUNT(DISTINCT es.evidence_id) AS evidence_count,
                  COUNT(DISTINCT rs.role_id) AS demand_count
           FROM skills s
           LEFT JOIN evidence_skills es ON es.skill_id = s.id
           LEFT JOIN role_skills rs ON rs.skill_id = s.id
           GROUP BY s.id
           HAVING evidence_count > 0
           ORDER BY evidence_count DESC, demand_count DESC
           LIMIT 1"""
    ).fetchone()
    if row:
        double_down_skill = row["name"]

    weak_signals = interviews_svc.recent_weak_signals(conn, limit=1)
    conversion_action = (
        f"Repair '{weak_signals[0]['dimension']}' signal from {weak_signals[0]['company']} "
        f"({weak_signals[0]['title']}): signal was {weak_signals[0]['signal']}."
        if weak_signals
        else "No weak/mixed signals recorded yet; capture interview feedback via `career update`."
    )

    pipeline_action = (
        f"Nudge stalled role: {stalled[0]['company']} - {stalled[0]['title']} (role {stalled[0]['role_id']}), "
        f"no movement in 14+ days."
        if stalled
        else "No stalled roles; add the next target-company role via `career add-job`."
    )

    proof_action = (
        f"Build evidence for recurring gap skill: {start_gap}."
        if start_gap
        else "No recurring gap identified yet; keep logging roles to surface one."
    )

    return {
        "period_days": period_days,
        "pipeline_moved": pipeline_moved,
        "conversion_signals": conversion_signals,
        "proof_added": proof_added,
        "stop": stalled,
        "continue_archetype": continue_archetype,
        "start_gap": start_gap,
        "double_down_skill": double_down_skill,
        "generalist_specialist_signal": problem_shape_svc.shape_signal(conn),
        "referral_signal": _referral_signal(conn),
        "source_signal": _source_signal(conn),
        "learning_signal": _learning_signal(conn),
        "next_actions": {
            "pipeline": pipeline_action,
            "conversion": conversion_action,
            "proof": proof_action,
        },
    }


# --- v3 signals: each returns None unless it can change a decision ------------------------------
def _referral_signal(conn: sqlite3.Connection):
    gaps = referrals_svc.roles_without_referral_path(conn, tier=1)
    due = referrals_svc.list_referrals(conn, "followup")
    unused = referrals_svc.list_referrals(conn, "unused")
    tier1 = conn.execute("SELECT COUNT(*) AS n FROM roles WHERE role_tier = 1 AND status NOT IN ('rejected','withdrawn','closed')").fetchone()["n"]
    if not (due or unused or gaps["no_path"]):
        return None
    with_path = tier1 - len(gaps["no_path"])
    return {"tier1_roles": tier1, "with_referral_path": with_path,
            "submitted": len([r for r in referrals_svc.list_referrals(conn, "waiting") if r["status"] == "submitted"]),
            "unused_offers": len(unused), "follow_ups_due": [f"{r['contact_name']} ({r['company_name'] or 'no company'})" for r in due[:5]]}


def _source_signal(conn: sqlite3.Connection):
    notable = [s for s in job_sources_svc.source_stats(conn) if s["suggestion"]]
    return notable or None


def _learning_signal(conn: sqlite3.Connection):
    rows = conn.execute(
        "SELECT dimension, COUNT(*) AS n FROM interview_signals WHERE signal IN ('Weak','Mixed') "
        "GROUP BY dimension ORDER BY n DESC").fetchall()
    if not rows or rows[0]["n"] < 2:
        return None  # one weak signal is an anecdote, not a pattern
    topics = learning_svc.DIMENSION_TOPICS.get(rows[0]["dimension"], [])
    cats = sorted({learning_svc.TOPICS[t][0] for t in topics})
    return {"recurring_gap": rows[0]["dimension"], "count": rows[0]["n"], "topics": topics, "categories": cats}
