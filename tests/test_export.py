"""export_all() tests: every table key present (including empty ones),
row counts match direct queries, and nested skill/evidence links work.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from career_os import db  # noqa: E402
from career_os.services import evidence as evidence_svc  # noqa: E402
from career_os.services import export  # noqa: E402
from career_os.services import applications as applications_svc  # noqa: E402
from career_os.services import roles as roles_svc  # noqa: E402
from career_os.services import update as update_svc  # noqa: E402


class TestExportAll(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_career.db"
        db.init_db(self.db_path)
        self.conn = db.get_connection(self.db_path)

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_every_table_key_present_even_when_empty(self):
        data = export.export_all(self.conn)
        for table in export.ALL_TABLES:
            self.assertIn(table, data)
            self.assertEqual(data[table], [])

    def test_groups_key_present(self):
        data = export.export_all(self.conn)
        self.assertIn("_groups", data)
        self.assertIn("Pipeline", data["_groups"])

    def test_row_counts_match_direct_query(self):
        roles_svc.add_job(self.conn, company="TestCo", title="TPM")
        roles_svc.add_job(self.conn, company="TestCo", title="Other TPM")
        data = export.export_all(self.conn)
        direct_count = self.conn.execute("SELECT COUNT(*) FROM roles").fetchone()[0]
        self.assertEqual(len(data["roles"]), direct_count)
        self.assertEqual(direct_count, 2)

    def test_roles_carry_matched_skills(self):
        result = roles_svc.add_job(
            self.conn, company="Databricks", title="TPM",
            jd_text="Must have RAG and LLM evaluation experience.",
        )
        data = export.export_all(self.conn)
        role_row = next(r for r in data["roles"] if r["id"] == result["role_id"])
        self.assertIn("matched_skills", role_row)
        self.assertTrue(len(role_row["matched_skills"]) > 0)

    def test_evidence_carries_linked_skills(self):
        evidence_svc.add_evidence(
            self.conn, company="TestCo", project="Test project",
            skill_names=["RAG"],
        )
        data = export.export_all(self.conn)
        self.assertEqual(len(data["evidence"]), 1)
        self.assertEqual(data["evidence"][0]["linked_skills"], ["RAG"])


class TestReadableViews(TestExportAll):
    def test_application_status_names_company_and_role(self):
        res = roles_svc.add_job(self.conn, company="Acme", title="Senior TPM", jd_text="x", source="LinkedIn",
                                applied_via="employee referral")
        applications_svc.set_status(self.conn, res["role_id"], "applied")
        row = export.export_all(self.conn)["application_status"][0]
        self.assertEqual((row["company"], row["role"], row["status"]), ("Acme", "Senior TPM", "applied"))
        self.assertEqual((row["found_via"], row["applied_via"]), ("LinkedIn", "referral"))
        self.assertEqual(row["id"], res["role_id"])

    def test_manual_source_is_not_shown_as_a_source(self):
        roles_svc.add_job(self.conn, company="Acme", title="PM", source="manual")
        self.assertIsNone(export.export_all(self.conn)["application_status"][0]["found_via"])

    def test_active_statuses_sort_before_rejected(self):
        a = roles_svc.add_job(self.conn, company="A", title="Rejected one")
        b = roles_svc.add_job(self.conn, company="B", title="Interviewing one")
        applications_svc.set_status(self.conn, a["role_id"], "rejected")
        applications_svc.set_status(self.conn, b["role_id"], "interview_loop")
        rows = export.export_all(self.conn)["application_status"]
        self.assertEqual([r["status"] for r in rows], ["interview_loop", "rejected"])

    def test_other_tables_get_names_and_keep_raw_ids(self):
        update_svc.apply_update(self.conn, "Dev said he can refer me at Google.")
        data = export.export_all(self.conn)
        ref = data["referrals"][0]
        self.assertEqual((ref["contact"], ref["company"]), ("Dev", "Google"))
        self.assertIn("contact_id", ref)
        self.assertIn("company_id", ref)
        res = roles_svc.add_job(self.conn, company="Acme", title="PM")
        applications_svc.set_status(self.conn, res["role_id"], "applied")
        app = data = export.export_all(self.conn)["applications"][0]
        self.assertEqual(app["role"], "Acme - PM")
        self.assertEqual(list(app)[0], "id")


class TestJobCode(TestExportAll):
    def test_same_title_different_job_codes_are_different_roles(self):
        a = roles_svc.add_job(self.conn, company="Super Micro Computer", title="Sr. Product Manager", job_code="29489")
        b = roles_svc.add_job(self.conn, company="Super Micro Computer", title="Sr. Product Manager", job_code="28389")
        self.assertFalse(a["duplicate"])
        self.assertFalse(b["duplicate"])
        self.assertNotEqual(a["role_id"], b["role_id"])

    def test_same_job_code_is_still_a_duplicate(self):
        a = roles_svc.add_job(self.conn, company="Super Micro Computer", title="Sr. Product Manager", job_code="29489")
        again = roles_svc.add_job(self.conn, company="Super Micro Computer", title="Sr. Product Manager", job_code="29489")
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["role_id"], a["role_id"])

    def test_no_job_code_keeps_old_duplicate_behavior(self):
        roles_svc.add_job(self.conn, company="Acme", title="PM")
        self.assertTrue(roles_svc.add_job(self.conn, company="Acme", title="PM")["duplicate"])

    def test_job_code_shows_in_application_view(self):
        roles_svc.add_job(self.conn, company="Acme", title="PM", job_code="J-77")
        self.assertEqual(export.export_all(self.conn)["application_status"][0]["job_code"], "J-77")


class TestSetRoleTier(TestExportAll):
    def test_user_tier_is_recorded_and_shown(self):
        res = roles_svc.add_job(self.conn, company="Acme", title="PM")
        out = roles_svc.set_role_tier(self.conn, res["role_id"], 1, "high priority")
        self.assertEqual((out["label"], out["was"]), ("Top priority", 3))
        self.assertEqual(roles_svc.get_role(self.conn, res["role_id"])["role_tier"], 1)
        self.assertEqual(export.export_all(self.conn)["application_status"][0]["priority"], "Top priority")
        claims = self.conn.execute("SELECT source_type FROM claims WHERE subject_id = ? AND claim_text LIKE 'role_tier=%'",
                                   (res["role_id"],)).fetchall()
        self.assertEqual([c["source_type"] for c in claims], ["user_confirmed"])
        with self.assertRaises(ValueError):
            roles_svc.set_role_tier(self.conn, res["role_id"], 5)
        self.assertIsNone(roles_svc.set_role_tier(self.conn, 9999, 1))


if __name__ == "__main__":
    unittest.main()
