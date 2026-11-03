"""Job-search metrics for the Dashboard (see docs/GUIDE.pdf).

Everything here is a count or a rate over stored rows; nothing is generated and
there are no numeric fit scores. Lane (archetype) is a model_inference label and
the dashboard shows it as such.

Contract: every metric that can be drilled carries a `drill` spec
    {"table": str, "filters": {column: [values]}, "range": {"column","from","to"} | None, "label": str}
whose semantics match the Data Browser table filters exactly (a row matches when
str(row[column]) is in the list; a range compares the first 10 characters of a date
cell, inclusive). `apply_drill` below implements those semantics so tests can prove
that every number on the dashboard equals the row count of its drill-down view.

This module must not import `export` (export imports this module for the derived
columns it adds to the application_status view).
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta
from typing import Optional

from career_os.services import pipeline as pipeline_svc
from career_os.services import roles as roles_svc

WEEKLY_TARGET = 10   # default weekly application target (Monday to Sunday); change to suit your search

# Statuses that mean an application was actually submitted.
SUBMITTED = {"applied", "referred", "recruiter_screen", "hiring_manager", "interview_loop",
             "final_round", "offer", "rejected", "withdrawn"}
NOT_SUBMITTED = {"planned", "referral_requested", "closed"}
IN_PROCESS = ("recruiter_screen", "hiring_manager", "interview_loop", "final_round")
STATUS_ORDER = ["offer", "final_round", "interview_loop", "hiring_manager", "recruiter_screen", "applied",
                "referred", "referral_requested", "planned", "rejected", "withdrawn", "closed"]

# Furthest stage reached, in order. The funnel counts rows at or beyond each stage.
STAGES = ["not submitted", "applied", "acknowledged", "heard back", "interview", "final round", "offer"]
FUNNEL_STAGES = ["applied", "acknowledged", "heard back", "interview", "final round", "offer"]
FUNNEL_LABELS = {"applied": "Applied", "acknowledged": "Acknowledged", "heard back": "Heard back",
                 "interview": "Interview", "final round": "Final round", "offer": "Offer"}

CHANNEL_GROUPS = ["Referral", "Company site", "Recruiter / agency", "Job board", "Other", "Unknown"]

_TAG_RE = re.compile(r"^\[snap:[^\]]+\]\s*\[(\w+)\]")
_REJECTED_ON_RE = re.compile(r"rejected[^0-9]{0,15}(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
_ACK_TYPES = {"application_ack"}


# ----------------------------------------------------------------------------------------------
# small pure helpers
# ----------------------------------------------------------------------------------------------
def channel_group(channel: Optional[str], found_via: Optional[str] = None) -> str:
    """Normalize free-text application channels into a few honest groups (no data is rewritten)."""
    text = (channel or "").strip().lower()
    if not text:
        text = (found_via or "").strip().lower()
        if text in ("", "manual", "none"):
            return "Unknown"
    if "referral" in text:
        return "Referral"
    if text in ("company_site", "company site", "company career pages") or "career" in text or "metacareers" in text:
        return "Company site"
    if text.startswith("recruiter") or text in ("email",) or "recruiter" in text:
        return "Recruiter / agency"
    if "flexjobs" in text or "jobright" in text or "job board" in text or "linkedin" in text or "indeed" in text:
        return "Job board"
    return "Other"


def activity_type(summary: Optional[str]) -> str:
    """Interaction type from the `[snap:key] [type]` tag the importer writes; older rows are 'note'."""
    m = _TAG_RE.match(summary or "")
    return m.group(1) if m else "note"


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _d(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def drill(table: str, label: str, filters: Optional[dict] = None, rng: Optional[dict] = None) -> dict:
    return {"table": table, "label": label,
            "filters": {k: [str(x) for x in v] for k, v in (filters or {}).items()}, "range": rng}


def apply_drill(rows: list[dict], spec: dict) -> list[dict]:
    """Same semantics as the Data Browser: AND across columns, OR within a column; blank -> ''."""
    def key(v):
        return "" if v is None else str(v)
    out = []
    for r in rows:
        ok = all(key(r.get(c)) in vals for c, vals in (spec.get("filters") or {}).items())
        rg = spec.get("range")
        if ok and rg:
            v = key(r.get(rg["column"]))[:10]
            ok = bool(v) and rg["from"] <= v <= rg["to"]
        if ok:
            out.append(r)
    return out


# ----------------------------------------------------------------------------------------------
# per-role facts (shared with export so the table and the dashboard cannot disagree)
# ----------------------------------------------------------------------------------------------
def role_facts(conn: sqlite3.Connection, today: Optional[date] = None) -> dict[int, dict]:
    today = today or date.today()
    acked = {r["role_id"] for r in conn.execute(
        "SELECT DISTINCT role_id FROM interactions WHERE role_id IS NOT NULL AND summary LIKE '%[application_ack]%'")}
    interview_counts: Counter = Counter()
    for r in conn.execute("SELECT role_id, date, outcome FROM interviews"):
        d = _d(r["date"])
        scheduled = str(r["outcome"] or "").lower().startswith("scheduled")
        if d and d <= today and not scheduled:
            interview_counts[r["role_id"]] += 1
    last_act: dict = {}
    for r in conn.execute("SELECT role_id, MAX(substr(date,1,10)) AS d FROM interactions WHERE role_id IS NOT NULL GROUP BY role_id"):
        last_act[r["role_id"]] = r["d"]

    # A rejection recorded by changing the status has no interaction row. Date it from the note ("rejected 2026-10-30")
    # when there is one, else from the day the status was last saved, so "rejections this week" is not blind to it.
    rejected_on: dict = {}
    for r in conn.execute("SELECT role_id, next_action, substr(updated_at, 1, 10) AS upd FROM applications WHERE status = 'rejected'"):
        m = _REJECTED_ON_RE.search(r["next_action"] or "")
        rejected_on[r["role_id"]] = m.group(1) if m else (r["upd"] or "")

    facts: dict[int, dict] = {}
    for p in pipeline_svc.get_pipeline(conn):
        rid = p["role_id"]
        status = p["application_status"] or "planned"
        n_int = interview_counts.get(rid, 0)
        if status in NOT_SUBMITTED:
            stage = "not submitted"
        elif status == "offer":
            stage = "offer"
        elif status == "final_round":
            stage = "final round"
        elif status in ("hiring_manager", "interview_loop") or n_int > 0:
            stage = "interview"
        elif status in ("rejected", "recruiter_screen", "withdrawn"):
            stage = "heard back"
        elif rid in acked:
            stage = "acknowledged"
        else:
            stage = "applied"
        da = p.get("date_applied")
        la = max([x for x in (last_act.get(rid), da, rejected_on.get(rid)) if x], default="")
        facts[rid] = {
            "status": status, "stage": stage, "interviews": n_int,
            "channel_group": channel_group(p.get("applied_via"), p.get("found_via")),
            "lane": p.get("archetype") or "Unrated", "date_applied": da or "",
            "last_activity": la, "company": p["company"], "title": p["title"],
            "priority": roles_svc.tier_label(p["role_tier"]),
        }
    return facts


# ----------------------------------------------------------------------------------------------
# the dashboard payload
# ----------------------------------------------------------------------------------------------
def compute_metrics(conn: sqlite3.Connection, today: Optional[date] = None, weekly_target: int = WEEKLY_TARGET,
                    weeks: int = 8) -> dict:
    today = today or date.today()
    facts = role_facts(conn, today)
    rows = list(facts.values())
    submitted = [f for f in rows if f["status"] in SUBMITTED]
    ap = "application_status"
    S = len(submitted)

    def stage_rank(f):
        return STAGES.index(f["stage"])

    # ---- weekly applications vs target ---------------------------------------------------------
    dated = [f for f in submitted if f["date_applied"]]
    this_monday = monday_of(today)
    weekly = []
    first = min((monday_of(_d(f["date_applied"])) for f in dated), default=this_monday)
    start = max(first, this_monday - timedelta(weeks=weeks - 1))
    wk = start
    while wk <= this_monday:
        end = wk + timedelta(days=6)
        n = sum(1 for f in dated if wk <= _d(f["date_applied"]) <= end)
        weekly.append({"week_start": wk.isoformat(), "week_end": end.isoformat(), "count": n,
                       "target": weekly_target, "met": n >= weekly_target, "current": wk == this_monday,
                       "drill": drill(ap, f"Applied {wk:%b %d} to {end:%b %d}", {"status": sorted(SUBMITTED)},
                                      {"column": "date_applied", "from": wk.isoformat(), "to": end.isoformat()})})
        wk += timedelta(days=7)
    this_week = weekly[-1]["count"] if weekly else 0
    quota = {"target": weekly_target, "count": this_week, "remaining": max(weekly_target - this_week, 0),
             "days_left": 6 - today.weekday(), "week_start": this_monday.isoformat(),
             "week_end": (this_monday + timedelta(days=6)).isoformat(),
             "drill": weekly[-1]["drill"] if weekly else None}

    # ---- KPIs ---------------------------------------------------------------------------------
    in_process = [f for f in rows if f["status"] in IN_PROCESS]
    rejected = [f for f in rows if f["status"] == "rejected"]
    heard = [f for f in submitted if stage_rank(f) >= STAGES.index("heard back")]
    interviewed = [f for f in submitted if f["interviews"] > 0 or stage_rank(f) >= STAGES.index("interview")]
    referral = [f for f in submitted if f["channel_group"] == "Referral"]
    last_app = max((_d(f["date_applied"]) for f in dated), default=None)

    def pct(a, b):
        return round(100 * a / b, 1) if b else 0.0

    kpis = OrderedDict([
        ("opportunities", {"value": len(rows), "label": "Opportunities", "drill": drill(ap, "All opportunities")}),
        ("submitted", {"value": S, "label": "Applications submitted",
                       "drill": drill(ap, "Submitted applications", {"status": sorted(SUBMITTED)})}),
        ("in_process", {"value": len(in_process), "label": "In process",
                        "drill": drill(ap, "In process (screen / interview)", {"status": list(IN_PROCESS)})}),
        ("interviewed", {"value": len(interviewed), "label": "Reached an interview",
                         "drill": drill(ap, "Reached an interview", {"stage": ["interview", "final round", "offer"]})}),
        ("rejected", {"value": len(rejected), "label": "Rejected",
                      "drill": drill(ap, "Rejected", {"status": ["rejected"]})}),
        ("response_rate", {"value": pct(len(heard), S), "unit": "%", "label": "Heard back (not just acknowledged)",
                           "numerator": len(heard), "denominator": S,
                           "drill": drill(ap, "Heard back", {"stage": ["heard back", "interview", "final round", "offer"],
                                                             "status": sorted(SUBMITTED)})}),
        ("interview_rate", {"value": pct(len(interviewed), S), "unit": "%", "label": "Interview rate",
                            "numerator": len(interviewed), "denominator": S,
                            "drill": drill(ap, "Reached an interview", {"stage": ["interview", "final round", "offer"]})}),
        ("referral_share", {"value": pct(len(referral), S), "unit": "%", "label": "Applied through a referral",
                            "numerator": len(referral), "denominator": S,
                            "drill": drill(ap, "Referral applications", {"channel_group": ["Referral"],
                                                                         "status": sorted(SUBMITTED)})}),
        ("days_since_last_application", {"value": (today - last_app).days if last_app else None,
                                         "label": "Days since last application", "drill": None}),
    ])
    # a few KPIs must filter on submitted status as well so the drill count equals the numerator
    kpis["interviewed"]["drill"]["filters"]["status"] = sorted(SUBMITTED)
    kpis["interview_rate"]["drill"]["filters"]["status"] = sorted(SUBMITTED)

    # ---- funnel (cumulative: rows at or beyond each stage) ----------------------------------------
    funnel = []
    for st in FUNNEL_STAGES:
        beyond = [s for s in STAGES if STAGES.index(s) >= STAGES.index(st)]
        n = sum(1 for f in submitted if f["stage"] in beyond)
        funnel.append({"stage": st, "label": FUNNEL_LABELS[st], "count": n,
                       "pct_of_applied": pct(n, S),
                       "drill": drill(ap, f"Reached: {FUNNEL_LABELS[st]}", {"stage": beyond, "status": sorted(SUBMITTED)})})

    # ---- status distribution -------------------------------------------------------------------
    sc = Counter(f["status"] for f in rows)
    status = [{"status": s, "count": sc[s], "drill": drill(ap, f"Status: {s}", {"status": [s]})}
              for s in STATUS_ORDER + sorted(set(sc) - set(STATUS_ORDER)) if sc.get(s)]

    # ---- channel x outcome ---------------------------------------------------------------------
    outcome_defs = [("No response yet", ["applied"], "applied"), ("In process", list(IN_PROCESS), "in_process"),
                    ("Rejected", ["rejected"], "rejected"), ("Withdrawn / other", ["withdrawn", "referred", "offer"], "other")]
    channels = []
    for g in CHANNEL_GROUPS:
        grp = [f for f in submitted if f["channel_group"] == g]
        if not grp:
            continue
        cells = []
        for name, sts, key in outcome_defs:
            c = sum(1 for f in grp if f["status"] in sts)
            cells.append({"outcome": name, "key": key, "count": c,
                          "drill": drill(ap, f"{g}: {name}", {"channel_group": [g], "status": sts})})
        heard_n = sum(1 for f in grp if stage_rank(f) >= STAGES.index("heard back"))
        int_n = sum(1 for f in grp if stage_rank(f) >= STAGES.index("interview") or f["interviews"] > 0)
        channels.append({"channel": g, "total": len(grp), "heard_back": heard_n, "interviews": int_n,
                         "heard_rate": pct(heard_n, len(grp)), "cells": cells,
                         "drill": drill(ap, f"Channel: {g}", {"channel_group": [g], "status": sorted(SUBMITTED)})})

    # ---- lanes (model inference) ---------------------------------------------------------------
    lane_names = {"A": "A: Technical program leadership", "B": "B: AI product (search, discovery)",
                  "C": "C: AI quality / evaluation", "Unrated": "Unrated"}
    lanes = []
    for ln in ("A", "B", "C", "Unrated"):
        grp = [f for f in submitted if f["lane"] == ln]
        if not grp:
            continue
        cells = []
        for name, sts, key in outcome_defs:
            c = sum(1 for f in grp if f["status"] in sts)
            cells.append({"outcome": name, "key": key, "count": c,
                          "drill": drill(ap, f"Lane {ln}: {name}", {"lane": [ln], "status": sts})})
        lanes.append({"lane": ln, "label": lane_names[ln], "total": len(grp), "cells": cells,
                      "note": "model inference (archetype), not a verified fact",
                      "drill": drill(ap, f"Lane {ln}", {"lane": [ln], "status": sorted(SUBMITTED)})})

    # ---- companies ------------------------------------------------------------------------------
    cc = Counter(f["company"] for f in submitted)
    companies = []
    for name, n in sorted(cc.items(), key=lambda kv: (-kv[1], kv[0]))[:10]:
        grp = [f for f in submitted if f["company"] == name]
        companies.append({"company": name, "count": n,
                          "rejected": sum(1 for f in grp if f["status"] == "rejected"),
                          "in_process": sum(1 for f in grp if f["status"] in IN_PROCESS),
                          "drill": drill(ap, f"Company: {name}", {"company": [name], "status": sorted(SUBMITTED)})})

    # ---- activity timeline (interactions by week x type) --------------------------------------------
    inter = [dict(r) for r in conn.execute("SELECT id, role_id, date, summary FROM interactions")]
    act_weeks: dict = {}
    type_counts: Counter = Counter()
    for r in inter:
        d = _d(r["date"])
        if not d:
            continue
        t = activity_type(r["summary"])
        type_counts[t] += 1
        act_weeks.setdefault(monday_of(d), Counter())[t] += 1
    activity = []
    for wk in sorted(act_weeks):
        end = wk + timedelta(days=6)
        activity.append({"week_start": wk.isoformat(), "by_type": dict(act_weeks[wk]), "total": sum(act_weeks[wk].values()),
                         "drill": drill("interactions", f"Activity {wk:%b %d} to {end:%b %d}", None,
                                        {"column": "date", "from": wk.isoformat(), "to": end.isoformat()})})
    activity_types = [{"type": t, "count": n, "drill": drill("interactions", f"Activity type: {t}", {"activity_type": [t]})}
                      for t, n in type_counts.most_common()]

    # ---- interviews -------------------------------------------------------------------------------
    iv_rows = conn.execute(
        """SELECT i.id, i.role_id, i.date, i.stage, i.outcome, c.name AS company, r.title,
                  (SELECT GROUP_CONCAT(dimension || ': ' || signal, '; ') FROM interview_signals s WHERE s.interview_id = i.id) AS signals
           FROM interviews i JOIN roles r ON r.id = i.role_id JOIN companies c ON c.id = r.company_id
           ORDER BY i.date DESC""").fetchall()
    interviews = []
    for r in iv_rows:
        d = _d(r["date"])
        upcoming = bool(d and d >= today) or str(r["outcome"] or "").lower().startswith("scheduled")
        interviews.append({"interview_id": r["id"], "role_id": r["role_id"], "date": r["date"] or "", "company": r["company"],
                           "title": r["title"], "stage": r["stage"] or "", "outcome": r["outcome"] or "",
                           "signals": r["signals"] or "", "upcoming": upcoming})

    # ---- needs attention ------------------------------------------------------------------------------
    stale_cut = today - timedelta(days=7)
    stale = [(rid, f) for rid, f in facts.items()
             if f["status"] == "applied" and _d(f["last_activity"]) and _d(f["last_activity"]) < stale_cut]
    tier_rank = {"Top priority": 0, "Medium priority": 1, "Low priority": 2}
    stale.sort(key=lambda x: (tier_rank.get(x[1]["priority"], 3), x[1]["last_activity"] or ""))
    ready = [(rid, f) for rid, f in facts.items() if f["status"] == "planned"]
    ready.sort(key=lambda x: (tier_rank.get(x[1]["priority"], 3), x[1]["company"]))

    def item(rid, f, why):
        return {"role_id": rid, "company": f["company"], "title": f["title"], "priority": f["priority"],
                "status": f["status"], "why": why, "last_activity": f["last_activity"]}

    attention = {
        "upcoming_interviews": [i for i in interviews if i["upcoming"]],
        "stale_applied": {"count": len(stale),
                          "items": [item(rid, f, f"no activity since {f['last_activity']}") for rid, f in stale[:10]],
                          "drill": drill(ap, "Applied, no activity for 7+ days", {"status": ["applied"]},
                                         {"column": "last_activity", "from": "2000-01-01",
                                          "to": (stale_cut - timedelta(days=1)).isoformat()})},
        "ready_to_apply": {"count": len(ready), "items": [item(rid, f, "planned, not applied") for rid, f in ready[:10]],
                           "drill": drill(ap, "Planned, not yet applied", {"status": ["planned"]})},
    }

    # ---- data quality -----------------------------------------------------------------------------------
    no_date = [f for f in submitted if not f["date_applied"]]
    unknown_ch = [f for f in submitted if f["channel_group"] == "Unknown"]
    quality = [
        {"issue": "Submitted applications with no date_applied", "count": len(no_date),
         "drill": drill(ap, "Submitted, no date applied", {"date_applied": [""], "status": sorted(SUBMITTED)})},
        {"issue": "Submitted applications with unknown channel", "count": len(unknown_ch),
         "drill": drill(ap, "Submitted, unknown channel", {"channel_group": ["Unknown"], "status": sorted(SUBMITTED)})},
        {"issue": "Roles shown as planned (no application yet)",
         "count": sum(1 for f in rows if f["status"] == "planned"),
         "drill": drill(ap, "Planned", {"status": ["planned"]})},
        {"issue": "Applied roles with no recorded activity or date",
         "count": sum(1 for f in rows if f["status"] == "applied" and not f["last_activity"]),
         "drill": drill(ap, "Applied, no activity or date", {"status": ["applied"], "last_activity": [""]})},
    ]

    return {
        "as_of": today.isoformat(), "weekly_target": weekly_target, "quota": quota, "kpis": kpis, "weekly": weekly,
        "funnel": funnel, "status": status, "channels": channels, "lanes": lanes, "companies": companies,
        "activity": activity, "activity_types": activity_types, "interviews": interviews, "attention": attention,
        "data_quality": quality,
    }
