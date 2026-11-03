"""Dashboard metrics tests (designs/2026-10-21_job-search-dashboard.md).

The key invariant: every number on the dashboard equals the row count of its
drill-down view in the Data Browser export.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from career_os import db  # noqa: E402
from career_os.services import export, metrics  # noqa: E402

TODAY = date(2026, 10, 21)   # a Wednesday; Monday of that week is 2026-10-19


class TestMetrics(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = db.get_connection(db.init_db(Path(self._tmp.name) / "t.db") or Path(self._tmp.name) / "t.db")
        c = self.conn
        self.co = {n: c.execute("INSERT INTO companies(name) VALUES (?)", (n,)).lastrowid for n in ("Acme", "Beta", "Gamma")}

        def role(company, title, status, applied=None, channel=None, arch=None, tier=None):
            rid = c.execute("INSERT INTO roles(company_id,title,archetype,role_tier) VALUES (?,?,?,?)",
                            (self.co[company], title, arch, tier)).lastrowid
            if status:
                c.execute("INSERT INTO applications(role_id,status,date_applied,channel) VALUES (?,?,?,?)",
                          (rid, status, applied, channel))
            return rid

        # weeks (Mon-Sun): 2026-10-12..18 has 2 applications, 2026-10-19..25 has 3
        self.r1 = role("Acme", "TPM", "applied", "2026-10-13", "company_site", "A", 1)
        self.r2 = role("Acme", "PM", "applied", "2026-10-18", "referral", "B", 1)
        self.r3 = role("Beta", "TPM2", "applied", "2026-10-19", "recruiter: Taylor", "A", 2)
        self.r4 = role("Beta", "PM2", "rejected", "2026-10-21", "company_site", "B", 2)
        self.r5 = role("Gamma", "Lead", "recruiter_screen", "2026-10-20", "Jobright (x)", "C", 1)
        self.r6 = role("Gamma", "Planned one", "planned", None, None, None, 2)
        self.r7 = role("Gamma", "No app row", None)
        self.r8 = role("Gamma", "Undated", "applied", None, "", None, 3)
        c.execute("INSERT INTO interactions(role_id,date,summary) VALUES (?,?,?)", (self.r1, "2026-10-14", "[snap:a] [application_ack] ok"))
        c.execute("INSERT INTO interactions(role_id,date,summary) VALUES (?,?,?)", (self.r4, "2026-10-21", "[snap:b] [rejection] no"))
        c.execute("INSERT INTO interactions(role_id,date,summary) VALUES (?,?,?)", (self.r2, "2026-10-01", "plain older note"))
        c.execute("INSERT INTO interviews(role_id,stage,date,outcome) VALUES (?,?,?,?)", (self.r5, "hr", "2026-10-20", "completed"))
        c.execute("INSERT INTO interviews(role_id,stage,date,outcome) VALUES (?,?,?,?)", (self.r1, "next", "2026-10-22", "scheduled (as of x)"))
        c.commit()
        self.m = metrics.compute_metrics(c, TODAY)
        self.data = export.export_all(c)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    # ---- helpers -------------------------------------------------------------------------------
    def rows_for(self, spec):
        return metrics.apply_drill(self.data[spec["table"]], spec)

    # ---- unit tests ----------------------------------------------------------------------------
    def test_channel_group_mapping(self):
        g = metrics.channel_group
        self.assertEqual(g("referral"), "Referral")
        self.assertEqual(g("company_site"), "Company site")
        self.assertEqual(g("recruiter: Taylor"), "Recruiter / agency")
        self.assertEqual(g("email"), "Recruiter / agency")
        self.assertEqual(g("Jobright (Jane Doe)"), "Job board")
        self.assertEqual(g(None, "manual"), "Unknown")
        self.assertEqual(g("", None), "Unknown")
        self.assertEqual(g("carrier pigeon"), "Other")

    def test_activity_type_from_tag(self):
        self.assertEqual(metrics.activity_type("[snap:x] [rejection] hi"), "rejection")
        self.assertEqual(metrics.activity_type("plain"), "note")

    def test_week_is_monday_to_sunday(self):
        self.assertEqual(metrics.monday_of(date(2026, 10, 18)), date(2026, 10, 12))   # Sunday belongs to the prior Monday
        self.assertEqual(metrics.monday_of(date(2026, 10, 19)), date(2026, 10, 19))
        weeks = {w["week_start"]: w["count"] for w in self.m["weekly"]}
        self.assertEqual(weeks["2026-10-12"], 2)
        self.assertEqual(weeks["2026-10-19"], 3)

    def test_quota(self):
        q = self.m["quota"]
        self.assertEqual((q["target"], q["count"], q["remaining"], q["days_left"]), (10, 3, 7, 4))

    def test_submitted_excludes_planned_and_closed(self):
        self.assertEqual(self.m["kpis"]["submitted"]["value"], 6)   # r1 r2 r3 r4 r5 r8
        self.assertEqual(self.m["kpis"]["opportunities"]["value"], 8)

    def test_funnel_is_monotonic_and_stage_logic(self):
        counts = [f["count"] for f in self.m["funnel"]]
        self.assertEqual(counts, sorted(counts, reverse=True))
        facts = metrics.role_facts(self.conn, TODAY)
        self.assertEqual(facts[self.r1]["stage"], "acknowledged")    # ack interaction; interview is only scheduled
        self.assertEqual(facts[self.r4]["stage"], "heard back")      # rejected
        self.assertEqual(facts[self.r5]["stage"], "interview")       # completed interview
        self.assertEqual(facts[self.r6]["stage"], "not submitted")

    def test_scheduled_interview_is_upcoming_not_completed(self):
        ups = self.m["attention"]["upcoming_interviews"]
        self.assertEqual([i["company"] for i in ups], ["Acme"])
        self.assertEqual(metrics.role_facts(self.conn, TODAY)[self.r1]["interviews"], 0)

    def test_data_quality_counts(self):
        dq = {q["issue"]: q["count"] for q in self.m["data_quality"]}
        self.assertEqual(dq["Submitted applications with no date_applied"], 1)
        self.assertEqual(dq["Roles shown as planned (no application yet)"], 2)   # r6 + r7 (no application row)

    # ---- the invariant ---------------------------------------------------------------------------
    def test_every_drill_matches_its_number(self):
        m = self.m
        checks = []
        for k, v in m["kpis"].items():
            if v["drill"]:
                checks.append((f"kpi {k}", v.get("numerator", v["value"]), v["drill"]))
        for w in m["weekly"]:
            checks.append(("week " + w["week_start"], w["count"], w["drill"]))
        for f in m["funnel"]:
            checks.append(("funnel " + f["stage"], f["count"], f["drill"]))
        for s in m["status"]:
            checks.append(("status " + s["status"], s["count"], s["drill"]))
        for ch in m["channels"]:
            checks.append(("channel " + ch["channel"], ch["total"], ch["drill"]))
            checks += [(f"cell {ch['channel']}/{c['outcome']}", c["count"], c["drill"]) for c in ch["cells"]]
        for ln in m["lanes"]:
            checks.append(("lane " + ln["lane"], ln["total"], ln["drill"]))
            checks += [(f"cell {ln['lane']}/{c['outcome']}", c["count"], c["drill"]) for c in ln["cells"]]
        for co in m["companies"]:
            checks.append(("company " + co["company"], co["count"], co["drill"]))
        for a in m["activity"]:
            checks.append(("activity " + a["week_start"], a["total"], a["drill"]))
        for a in m["activity_types"]:
            checks.append(("type " + a["type"], a["count"], a["drill"]))
        for k in ("stale_applied", "ready_to_apply"):
            checks.append((k, m["attention"][k]["count"], m["attention"][k]["drill"]))
        for q in m["data_quality"]:
            checks.append(("dq " + q["issue"], q["count"], q["drill"]))
        checks.append(("quota", m["quota"]["count"], m["quota"]["drill"]))
        self.assertGreater(len(checks), 30)
        for label, n, spec in checks:
            self.assertEqual(len(self.rows_for(spec)), n, f"{label}: drill rows differ from the number shown")

    def test_export_has_derived_columns_and_dashboard_tab(self):
        self.assertEqual(self.data["_groups"]["Overview"][:2], ["action_center", "dashboard"])
        self.assertEqual(self.data["dashboard"], [])
        row = self.data["application_status"][0]
        for col in ("stage", "date_applied", "channel_group", "lane", "interviews", "last_activity"):
            self.assertIn(col, row)
        self.assertIn("activity_type", self.data["interactions"][0])


if __name__ == "__main__":
    unittest.main()
