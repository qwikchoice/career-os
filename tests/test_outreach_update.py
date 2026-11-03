"""Plain-English outreach updates: "Sent the resume to Taylor from Harbor" logs an interaction."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from career_os import db  # noqa: E402
from career_os.services import applications as apps  # noqa: E402
from career_os.services import companies as companies_svc  # noqa: E402
from career_os.services import contacts as contacts_svc  # noqa: E402
from career_os.services import roles as roles_svc  # noqa: E402
from career_os.services import update as up  # noqa: E402


class TestOutreachUpdate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "t.db"
        db.init_db(path)
        self.conn = db.get_connection(path)
        c = self.conn
        self.agency = companies_svc.get_or_create_company(c, "Harbor Staffing")
        self.recruiter = contacts_svc.get_or_create_contact(c, "Taylor Brooks", company_id=self.agency, relationship_type="recruiter")
        # two open roles reachable through "Harbor": the hint is ambiguous, so no role may be linked
        self.r1 = roles_svc.add_job(c, "Harbor Client A", title="PM")["role_id"]
        self.r2 = roles_svc.add_job(c, "Harbor Client B", title="TPM")["role_id"]
        # a company with exactly one open role
        self.acme = companies_svc.get_or_create_company(c, "Acme")
        self.jordan = contacts_svc.get_or_create_contact(c, "Jordan Lee", company_id=self.acme)
        self.acme_role = roles_svc.add_job(c, "Acme", title="Senior TPM")["role_id"]
        apps.set_status(c, self.acme_role, "applied")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_first_name_and_company_hint_find_the_existing_contact(self):
        n_contacts = self.conn.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()["n"]
        r = up.apply_update(self.conn, "Sent the resume to Taylor from Harbor")
        self.assertEqual(r["kind"], "interaction")
        self.assertEqual((r["contact_id"], r["contact_name"]), (self.recruiter, "Taylor Brooks"))
        self.assertIsNone(r["role_id"])            # "Harbor" matches several companies: not guessed
        self.assertIn("for role", r["next_step"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()["n"], n_contacts)
        row = self.conn.execute("SELECT * FROM interactions WHERE id = ?", (r["interaction_id"],)).fetchone()
        self.assertEqual((row["contact_id"], row["direction"]), (self.recruiter, "outbound"))

    def test_explicit_role_is_linked_and_status_is_not_changed(self):
        r = up.apply_update(self.conn, f"Sent the resume to Taylor from Harbor for role {self.r1}")
        self.assertEqual((r["kind"], r["role_id"]), ("interaction", self.r1))
        self.assertNotIn("next_step", r)
        self.assertEqual(roles_svc.get_role(self.conn, self.r1)["status"], "new")

    def test_single_open_role_at_the_contacts_company_is_linked(self):
        r = up.apply_update(self.conn, "Emailed Jordan about next steps")
        self.assertEqual((r["kind"], r["contact_id"], r["role_id"]), ("interaction", self.jordan, self.acme_role))

    def test_new_person_with_company_hint_is_created_at_that_company(self):
        r = up.apply_update(self.conn, "Sent my resume to Maya Patel at Acme")
        self.assertEqual(r["kind"], "interaction")
        row = self.conn.execute("SELECT name, company_id FROM contacts WHERE id = ?", (r["contact_id"],)).fetchone()
        self.assertEqual((row["name"], row["company_id"]), ("Maya Patel", self.acme))
        self.assertEqual(r["role_id"], self.acme_role)

    def test_a_company_name_is_not_treated_as_a_person(self):
        r = up.apply_update(self.conn, "Sent the resume to Acme")
        self.assertEqual(r["kind"], "note_fallback")

    def test_ambiguous_first_name_falls_back_to_a_note(self):
        contacts_svc.get_or_create_contact(self.conn, "Taylor Reyes", company_id=self.acme)
        r = up.apply_update(self.conn, "Sent the resume to Taylor")
        self.assertEqual(r["kind"], "note_fallback")

    def test_old_verbs_still_work(self):
        r = up.apply_update(self.conn, "Contacted Jordan on LinkedIn")
        self.assertEqual((r["kind"], r["contact_id"]), ("interaction", self.jordan))


if __name__ == "__main__":
    unittest.main()
