"""Action Center: what needs doing this week and what not to do
(see docs/GUIDE.pdf).

Everything is derived from stored rows; nothing is generated and there are no numeric fit scores.
Items link to a role (`role_id`, opens the role drawer) or carry a `drill` spec with the same
semantics as metrics.drill (opens a filtered Data Browser table).
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta
from typing import Optional

from career_os.services import metrics as metrics_svc
from career_os.services import pipeline as pipeline_svc
from career_os.services import roles as roles_svc

drill = metrics_svc.drill
AP = "application_status"

DONE = {"rejected", "withdrawn", "closed"}
IN_PROCESS = metrics_svc.IN_PROCESS
STALE_DAYS = 7
_RATE_CAP_RE = re.compile(r"max[^0-9$]*\$?\s*(\d+)", re.IGNORECASE)
_PENDING_WORDS = ("pending", "scheduled", "resched", "cancel", "hold")

# Curated guardrails. Each names where it comes from, so none is an unexplained rule.
STANDING_RULES = [
    {"rule": "Do not claim what your record does not support.",
     "why": "Only claim experience your record supports; keep a 'not claimed' list per application and state gaps plainly if asked.",
     "source": "standing rule"},
    {"rule": "Do not take over interviews or over-explain.",
     "why": "Common interviewer feedback: keep answers short, pause, and leave room for the interviewer to talk.",
     "source": "standing rule"},
    {"rule": "Do not send applications or outreach without review.",
     "why": "Check every application and message before it goes out.",
     "source": "standing rule"},
    {"rule": "Do not re-process roles that are not in status 'new'.",
     "why": "Roles that are already handled stay as they are.",
     "source": "standing rule"},
]


def _d(s: Optional[str]) -> Optional[date]:
    return metrics_svc._d(s)


def _rows(conn: sqlite3.Connection, today: date) -> list[dict]:
    """One row per role with application and role facts the rules need."""
    comp = {r["id"]: r for r in conn.execute("SELECT id, compensation_text, employment_type FROM roles")}
    facts = metrics_svc.role_facts(conn, today)
    out = []
    for p in pipeline_svc.get_pipeline(conn):
        rid = p["role_id"]
        f = facts[rid]
        c = comp.get(rid)
        out.append({
            "role_id": rid, "company": p["company"], "title": p["title"], "job_code": p["job_code"],
            "status": f["status"], "priority": f["priority"], "role_tier": p["role_tier"],
            "last_activity": f["last_activity"], "applied_via": p["applied_via"] or "",
            "found_via": p["found_via"] or "", "next_action": p["next_action"] or "",
            "next_action_date": p["next_action_date"] or "",
            "compensation_text": (c["compensation_text"] or "") if c else "",
        })
    return out


def _names(rows: list[dict], limit: int = 3) -> str:
    """Short company list for a card: first few, then '+N more' (the card links to the full table)."""
    names = sorted({r["company"].split(" (")[0] for r in rows})
    if not names:
        return "none"
    return ", ".join(names[:limit]) + (f" +{len(names) - limit} more" if len(names) > limit else "")


def _item(r: dict, why: str, **extra) -> dict:
    d = {"role_id": r["role_id"], "company": r["company"], "title": r["title"], "priority": r["priority"],
         "status": r["status"], "why": why}
    d.update(extra)
    return d


def _due_tag(due: Optional[date], today: date) -> tuple[str, str]:
    if due is None:
        return "no date", "none"
    n = (due - today).days
    if n < 0:
        return f"overdue by {-n} day{'s' if n != -1 else ''}", "overdue"
    if n == 0:
        return "due today", "urgent"
    if n == 1:
        return "due tomorrow", "urgent"
    if n <= 7:
        return f"due in {n} days", "soon"
    return f"due {due.isoformat()}", "later"


def compute_actions(conn: sqlite3.Connection, today: Optional[date] = None,
                    weekly_target: int = metrics_svc.WEEKLY_TARGET) -> dict:
    today = today or date.today()
    m = metrics_svc.compute_metrics(conn, today, weekly_target)
    rows = _rows(conn, today)
    active = [r for r in rows if r["status"] not in DONE]
    week_start = metrics_svc.monday_of(today)
    week_end = week_start + timedelta(days=6)
    last7 = (today - timedelta(days=7)).isoformat()

    # ---- top strip: where things stand ------------------------------------------------------------
    INTERVIEWING = ("hiring_manager", "interview_loop", "final_round")
    in_process = [r for r in rows if r["status"] in INTERVIEWING]
    leads = [r for r in rows if r["status"] in ("referred", "referral_requested", "recruiter_screen")]
    rejected_7 = [r for r in rows if r["status"] == "rejected" and last7 <= (r["last_activity"] or "") <= today.isoformat()]
    q = m["quota"]
    strip = [
        {"key": "in_process", "label": "In interview process", "value": len(in_process),
         "detail": _names(in_process),
         "drill": drill(AP, "In interview process", {"status": list(INTERVIEWING)})},
        {"key": "leads", "label": "Recruiter and referral leads", "value": len(leads),
         "detail": _names(leads),
         "drill": drill(AP, "Recruiter and referral leads", {"status": ["referred", "referral_requested", "recruiter_screen"]})},
        {"key": "quota", "label": "Applications this week", "value": f"{q['count']} of {q['target']}",
         "detail": "goal met" if q["count"] >= q["target"] else f"{q['remaining']} to go, {q['days_left']} days left",
         "drill": q["drill"]},
        {"key": "rejected", "label": "Rejections in the last 7 days", "value": len(rejected_7),
         "detail": _names(rejected_7),
         "drill": drill(AP, "Rejected, activity in the last 7 days", {"status": ["rejected"]},
                        {"column": "last_activity", "from": last7, "to": today.isoformat()})},
    ]

    # ---- do now: next actions with deadlines -------------------------------------------------------
    todo = []
    for r in active:
        if not r["next_action"]:
            continue
        due = _d(r["next_action_date"])
        tag, level = _due_tag(due, today)
        todo.append(_item(r, r["next_action"], due=due.isoformat() if due else None, tag=tag, level=level))
    order = {"overdue": 0, "urgent": 1, "soon": 2, "later": 3, "none": 4}
    tier = {"Top priority": 0, "Medium priority": 1, "Low priority": 2}
    todo.sort(key=lambda i: (order[i["level"]], i["due"] or "9999", tier.get(i["priority"], 3), i["company"]))
    do_now = {"count": len(todo), "items": todo[:15],
              "drill": drill(AP, "Roles with a next action",
                             {"id": [str(i["role_id"]) for i in todo]}) if todo else None}

    # ---- interviews and scheduling ----------------------------------------------------------------
    role_by_id = {r["role_id"]: r for r in rows}
    interviews = []
    for iv in conn.execute("SELECT id, role_id, stage, date, outcome FROM interviews ORDER BY id DESC"):
        r = role_by_id.get(iv["role_id"])
        if not r or r["status"] in DONE:
            continue
        d = _d(iv["date"])
        outcome = str(iv["outcome"] or "")
        low = outcome.lower()
        if "superseded" in low:
            continue   # replaced by a newer entry for the same interview
        if d is None:
            if not any(w in low for w in _PENDING_WORDS):
                continue
            interviews.append(_item(r, f"{iv['stage'] or 'interview'}", date=None, outcome=outcome))
        elif d >= today:
            interviews.append(_item(r, f"{iv['stage'] or 'interview'}", date=iv["date"], outcome=outcome or "pending"))
        elif low.startswith("scheduled"):
            interviews.append(_item(r, f"{iv['stage'] or 'interview'}: date passed, record the outcome",
                                    date=iv["date"], outcome="outcome needed"))
    interviews.sort(key=lambda i: (i["date"] or "9999", i["company"]))

    # ---- waiting on others: no activity for 7+ days ------------------------------------------------
    cut = today - timedelta(days=STALE_DAYS)
    waiting = []
    for r in active:
        if r["status"] not in ("applied", "referred", "recruiter_screen", "hiring_manager"):
            continue
        la = _d(r["last_activity"])
        if la and la < cut:
            waiting.append(_item(r, f"no activity since {la.isoformat()}; follow up or move on", last_activity=la.isoformat()))
    waiting.sort(key=lambda i: (tier.get(i["priority"], 3), i["last_activity"]))
    waiting_block = {"count": len(waiting), "items": waiting[:10],
                     "drill": drill(AP, "Waiting on others, no activity for 7+ days",
                                    {"status": ["applied", "referred", "recruiter_screen", "hiring_manager"]},
                                    {"column": "last_activity", "from": "2000-01-01",
                                     "to": (cut - timedelta(days=1)).isoformat()})}

    recent_rej = sorted(rejected_7, key=lambda r: r["last_activity"], reverse=True)
    rejections = {"count": len(recent_rej),
                  "items": [_item(r, f"rejected {r['last_activity']}", date=r["last_activity"]) for r in recent_rej[:10]],
                  "drill": strip[3]["drill"]}

    # ---- what not to do ----------------------------------------------------------------------------
    avoid = []
    for r in active:
        link = {"role_id": r["role_id"], "company": r["company"], "title": r["title"]}
        via_agency = bool(r["job_code"]) and ("recruiter" in r["applied_via"].lower() or " via " in r["company"].lower()
                                              or "(via" in r["company"].lower())
        if via_agency:
            avoid.append({**link, "rule": f"Do not submit {r['job_code']} through any other agency or channel.",
                          "why": "Dual submission from two sources can disqualify you; recruiters ask to avoid it.", "kind": "data"})
        cap = _RATE_CAP_RE.search(r["compensation_text"])
        if cap:
            avoid.append({**link, "rule": f"Do not quote a rate above ${cap.group(1)}/hr.",
                          "why": f"The posting states a maximum ({r['compensation_text']}).", "kind": "data"})
        if r["next_action"].upper().startswith("ON HOLD"):
            avoid.append({**link, "rule": "Do not chase this role while it is on hold.",
                          "why": r["next_action"], "kind": "data"})
        if r["status"] == "referred" and "google" in r["company"].lower() and "referral" in r["applied_via"].lower():
            avoid.append({**link, "rule": "Do not apply to more than 3 Google roles per 30 days on this referral.",
                          "why": "Google's referral invitation limit.", "kind": "data"})
    low = [r for r in rows if r["status"] == "planned" and r["role_tier"] == 3]
    if low:
        avoid.append({"rule": f"Do not spend this week's applications on the {len(low)} low-priority planned roles without a clear reason.",
                      "why": "Applying well below your level can cost an interview (overqualified feedback); apply only with a clear reason.",
                      "kind": "data",
                      "drill": drill(AP, "Planned, low priority", {"status": ["planned"], "priority": ["Low priority"]})})
    for s in STANDING_RULES:
        avoid.append({**s, "kind": "standing"})

    # ---- fix your data -------------------------------------------------------------------------------
    return {
        "as_of": today.isoformat(), "week_start": week_start.isoformat(), "week_end": week_end.isoformat(),
        "strip": strip, "do_now": do_now,
        "interviews": {"count": len(interviews), "items": interviews[:10],
                       "drill": drill("interviews", "All interviews")},
        "waiting": waiting_block, "rejections": rejections, "avoid": avoid, "data_quality": m["data_quality"],
    }
