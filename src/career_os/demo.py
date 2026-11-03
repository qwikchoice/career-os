"""Fictional demo data so a new install can show every screen (Action Center, Dashboard, tables).

Everything here is made up: invented companies, people and dates (relative to today so the
weekly views are populated). Run it on a throwaway database:

    CAREER_OS_DB=/tmp/demo.db python cli.py seed-demo     (macOS/Linux)
    set CAREER_OS_DB=demo.db && python cli.py seed-demo   (Windows cmd)

It refuses to run on a database that already has roles, so it can never mix into real data.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from career_os.services import applications as apps
from career_os.services import contacts as contacts_svc
from career_os.services import interactions as inter_svc
from career_os.services import interviews as iv_svc
from career_os.services import roles as roles_svc

JD_TPM = ("Technical Program Manager for ML platform. Own roadmap, release management, launch readiness, "
          "cross-functional engineering, reliability and latency targets, executive reporting.")
JD_SEARCH = ("Product Manager, search and discovery. Retrieval, ranking, relevance, personalization, "
             "A/B testing and NDCG; own the roadmap and user stories.")
JD_EVAL = ("Lead AI quality: evaluation frameworks, golden datasets, human-in-the-loop annotation, launch gates, "
           "thresholds, segmentation and regression detection for LLM features.")


def _d(offset_days: int) -> str:
    return (date.today() + timedelta(days=offset_days)).isoformat()


def run_demo(conn: sqlite3.Connection) -> dict:
    if conn.execute("SELECT COUNT(*) AS n FROM roles").fetchone()["n"]:
        raise RuntimeError("Refusing to add demo data: this database already has roles. "
                           "Point CAREER_OS_DB at a new file first.")

    def role(company, title, status, jd=None, applied=None, channel=None, next_action=None, next_date=None,
             location="Remote", source="LinkedIn"):
        r = roles_svc.add_job(conn, company, title=title, jd_text=jd, location=location, source=source)
        rid = r["role_id"]
        apps.set_status(conn, rid, status, date_applied=applied, channel=channel,
                        next_action=next_action, next_action_date=next_date)
        return rid

    acme = role("Acme Robotics", "Senior Technical Program Manager", "applied", JD_TPM, applied=_d(-1), channel="company_site",
                next_action="Follow up with the recruiter if no reply", next_date=_d(5))
    globex = role("Globex Systems", "Product Manager, AI Search", "recruiter_screen", JD_SEARCH, applied=_d(-8), channel="recruiter",
                  next_action="Prepare for the recruiter screen", next_date=_d(1))
    initech = role("Initech Cloud", "Principal Product Manager", "interview_loop", JD_SEARCH, applied=_d(-14), channel="referral",
                   next_action="Prep system-design and metrics stories for the loop", next_date=_d(2))
    hooli = role("Hooli Media", "Technical Program Manager", "rejected", JD_TPM, applied=_d(-12), channel="company_site",
                 next_action=f"None: rejected {_d(-2)} (form email)")
    stark = role("Stark Analytics", "Program Manager, Data Platform", "referred", JD_TPM, channel="referral",
                 next_action="Apply with the referral before the posting closes", next_date=_d(3))
    wayne = role("Wayne Logistics", "Senior Product Manager", "applied", JD_SEARCH, applied=_d(-11), channel="job board")
    pied = role("Pied Piper Labs", "Staff Product Manager, Search", "planned", JD_SEARCH)
    wonka = role("Wonka Games", "Product Manager", "applied", JD_SEARCH, applied=_d(-3), channel="company_site")
    soylent = role("Soylent Foods", "Technical Program Manager", "planned", JD_TPM)
    umbra = role("Gringotts Data", "AI Quality Lead", "applied", JD_EVAL, applied=_d(-5), channel="recruiter")

    iv_svc.add_interview(conn, globex, stage="Recruiter screen (30 min, phone)", date=_d(1), outcome="scheduled")
    iv_svc.add_interview(conn, initech, stage="Hiring manager interview (45 min, video)", date=_d(2), outcome="scheduled")
    iv_svc.add_interview(conn, initech, stage="Metrics and experimentation (45 min, video)", date=_d(3), outcome="scheduled")
    iv_svc.add_interview(conn, hooli, stage="Recruiter screen (completed)", date=_d(-9), outcome="completed")

    jordan = contacts_svc.get_or_create_contact(conn, "Jordan Lee")
    sam = contacts_svc.get_or_create_contact(conn, "Sam Rivera")
    stale_id = inter_svc.log_interaction(conn, jordan, "Intro chat; offered to refer me at Stark Analytics.", role_id=stark, channel="linkedin")
    old_id = inter_svc.log_interaction(conn, sam, "Recruiter confirmed the application was received.", role_id=wayne, channel="email")
    conn.execute("UPDATE interactions SET date = ? WHERE id = ?", (_d(-4), stale_id))
    conn.execute("UPDATE interactions SET date = ? WHERE id = ?", (_d(-10), old_id))
    conn.commit()
    return {"roles": 10, "interviews": 4, "contacts": 2}
