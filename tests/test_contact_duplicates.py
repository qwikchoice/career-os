"""Contact duplicate detection and merge."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from career_os import db  # noqa: E402
from career_os.services import companies as companies_svc  # noqa: E402
from career_os.services import contacts as contacts_svc  # noqa: E402


class TestContactDuplicates(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "t.db"
        db.init_db(path)
        self.conn = db.get_connection(path)
        self.meta = companies_svc.get_or_create_company(self.conn, "Meta")
        self.other = companies_svc.get_or_create_company(self.conn, "Microsoft")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def count(self, like):
        return self.conn.execute("SELECT COUNT(*) AS n FROM contacts WHERE name LIKE ?", (like,)).fetchone()["n"]

    def test_spelling_variant_reuses_contact(self):
        a = contacts_svc.get_or_create_contact(self.conn, "Karthik Kumar Pillai", company_id=self.meta)
        b = contacts_svc.get_or_create_contact(self.conn, "Kartik Kumar Pillai", email="k@example.com")
        self.assertEqual(a, b)
        self.assertEqual(self.count("%Pillai"), 1)
        self.assertEqual(self.conn.execute("SELECT email FROM contacts WHERE id=?", (a,)).fetchone()["email"], "k@example.com")

    def test_same_email_is_decisive(self):
        a = contacts_svc.get_or_create_contact(self.conn, "Nina S", email="p@example.com")
        b = contacts_svc.get_or_create_contact(self.conn, "Nina Shah", email="P@Example.com")
        self.assertEqual(a, b)

    def test_different_people_stay_separate(self):
        a = contacts_svc.get_or_create_contact(self.conn, "Amar Rao", company_id=self.meta)
        b = contacts_svc.get_or_create_contact(self.conn, "Amir Rao", company_id=self.meta)
        c = contacts_svc.get_or_create_contact(self.conn, "Rohan")
        d = contacts_svc.get_or_create_contact(self.conn, "Rohan Kapoor")
        self.assertEqual(len({a, b}), 2)
        self.assertNotEqual(c, d)

    def test_conflicting_companies_stay_separate(self):
        a = contacts_svc.get_or_create_contact(self.conn, "Casey Park", company_id=self.meta)
        b = contacts_svc.get_or_create_contact(self.conn, "Casey Park", company_id=self.other)
        self.assertNotEqual(a, b)

    def test_merge_repoints_references(self):
        a = contacts_svc.get_or_create_contact(self.conn, "Kartik Kumar Pillai", email="k@example.com")
        b = self.conn.execute("INSERT INTO contacts (name, company_id) VALUES ('Karthik Kumar Pillai', ?)",
                              (self.meta,)).lastrowid
        self.conn.execute("INSERT INTO interactions (contact_id, summary) VALUES (?, 'x')", (b,))
        self.conn.commit()
        contacts_svc.merge_contacts(self.conn, a, b)
        self.assertEqual(self.count("%Pillai"), 1)
        self.assertEqual(self.conn.execute("SELECT contact_id FROM interactions").fetchone()["contact_id"], a)
        self.assertEqual(self.conn.execute("SELECT company_id FROM contacts WHERE id=?", (a,)).fetchone()["company_id"], self.meta)
        self.assertEqual(self.conn.execute("SELECT status FROM duplicates").fetchone()["status"], "merged")


if __name__ == "__main__":
    unittest.main()
