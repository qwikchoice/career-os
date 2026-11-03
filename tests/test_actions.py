"""Action Center tests (designs/2026-11-02_action-center.md)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from career_os import db  # noqa: E402
from career_os.services import actions, export, metrics  # noqa: E402

TODAY = date(2026, 11, 2)   # a Monday


class TestActions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "t.db"
        db.init_db(path)
        self.conn = db.get_connection(path)
        c = self.conn

        def role(company, title, status, comp=None, code=None, tier=2, applied=None, channel=None,
                 next_action=None, next_date=None):
            cid = c.execute("INSERT INTO companies(name) VALUES (?)", (company,)).lastrowid
            rid = c.execute("INSERT INTO roles(company_id,title,compensation_text,job_code,role_tier) VALUES (?,?,?,?,?)",
                            (cid, title, comp, code, tier)).lastrowid
            c.execute("INSERT INTO applications(role_id,status,date_applied,channel,next_action,next_action_date) "
                      "VALUES (?,?,?,?,?,?)", (rid, status, applied, channel, next_action, next_date))
            return rid

        self.soon = role("Acme", "PM", "referred", next_action="Apply", next_date="2026-11-03")
        self.later = role("Beta", "TPM", "applied", applied="2026-11-02", next_action="Follow up", next_date="2026-11-20")
        self.undated = role("Gamma", "PM", "recruiter_screen", next_action="Send resume")
        self.agency = role("Delta (via Agency)", "SC", "recruiter_screen", code="REQ-1", channel="recruiter (Agency)")
        self.capped = role("Echo", "PgM", "recruiter_screen", comp="Max $55/hr W2")
        self.hold = role("Fox", "PM", "interview_loop", next_action="ON HOLD: waiting")
        self.lowplan = role("Golf", "PM", "planned", tier=3)
        self.done = role("Hotel", "PM", "rejected", next_action="old")
        self.rej_new = role("India", "PM", "rejected", next_action="None: rejected 2026-10-30 (form email)")
        self.rej_old = role("Juliet", "PM", "rejected")
        c.execute("UPDATE applications SET updated_at = '2026-10-31 10:00:00' WHERE role_id IN (?, ?)", (self.rej_new, self.done))
        c.execute("UPDATE applications SET updated_at = '2026-10-10 10:00:00' WHERE role_id = ?", (self.rej_old,))
        c.commit()
        self.a = actions.compute_actions(c, TODAY)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_do_now_sorted_by_due_and_skips_finished(self):
        ids = [i["role_id"] for i in self.a["do_now"]["items"]]
        self.assertEqual(ids[0], self.soon)          # due tomorrow first
        self.assertLess(ids.index(self.later), ids.index(self.undated))   # dated before undated
        self.assertNotIn(self.done, ids)             # rejected roles never listed
        self.assertEqual(self.a["do_now"]["items"][0]["tag"], "due tomorrow")

    def test_dual_submission_and_rate_cap_and_hold_rules(self):
        rules = [i["rule"] for i in self.a["avoid"]]
        self.assertTrue(any("REQ-1" in r and "any other agency" in r for r in rules))
        self.assertTrue(any("$55/hr" in r for r in rules))
        self.assertTrue(any("on hold" in r for r in rules))
        self.assertTrue(any("low-priority" in r for r in rules))

    def test_standing_rules_present(self):
        standing = [i for i in self.a["avoid"] if i["kind"] == "standing"]
        self.assertEqual(len(standing), len(actions.STANDING_RULES))

    def test_strip_counts_equal_drilled_rows(self):
        rows = export.export_all(self.conn)["application_status"]
        for s in self.a["strip"]:
            if s["key"] in ("in_process", "leads", "rejected"):
                self.assertEqual(s["value"], len(metrics.apply_drill(rows, s["drill"])), s["key"])

    def test_rejection_saved_by_status_change_is_counted(self):
        strip = {s["key"]: s for s in self.a["strip"]}
        rej = strip["rejected"]
        # India (note says rejected 2026-10-30) and Hotel (status saved 2026-10-31) are in the last 7 days; Juliet (Oct 10) is not
        self.assertEqual(rej["value"], 2)
        self.assertIn("India", rej["detail"])
        self.assertNotIn("Juliet", rej["detail"])

    def test_set_next_action_feeds_do_now_and_can_be_cleared(self):
        from career_os.services import applications as apps
        rid = self.conn.execute("SELECT id FROM roles WHERE title = 'PgM'").fetchone()["id"]
        app = apps.set_next_action(self.conn, rid, "Send thank-you note", "2026-11-04")
        self.assertEqual((app["next_action"], app["next_action_date"]), ("Send thank-you note", "2026-11-04"))
        self.assertEqual(app["status"], "recruiter_screen")   # status untouched
        a = actions.compute_actions(self.conn, TODAY)
        hit = [i for i in a["do_now"]["items"] if i["role_id"] == rid][0]
        self.assertEqual(hit["tag"], "due in 2 days")
        self.assertEqual(apps.set_next_action(self.conn, rid, "")["next_action"], None)
        self.assertIsNone(apps.set_next_action(self.conn, 99999, "x"))
        with self.assertRaises(ValueError):
            apps.set_next_action(self.conn, rid, "x", "11/04/2026")

    def test_week_bounds_are_monday_to_sunday(self):
        self.assertEqual(self.a["week_start"], "2026-11-02")
        self.assertEqual(self.a["week_end"], "2026-11-08")


if __name__ == "__main__":
    unittest.main()
