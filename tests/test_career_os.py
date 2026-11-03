"""Career OS tests. Stdlib unittest only — no new dependency to install.

Run from career-os/:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from career_os import db  # noqa: E402
from career_os.services import applications as applications_svc  # noqa: E402
from career_os.services import claims as claims_svc  # noqa: E402
from career_os.services import companies as companies_svc  # noqa: E402
from career_os.services import evidence as evidence_svc  # noqa: E402
from career_os.services import notes as notes_svc  # noqa: E402
from career_os.services import pipeline as pipeline_svc  # noqa: E402
from career_os.services import roles as roles_svc  # noqa: E402
from career_os.services import skills as skills_svc  # noqa: E402
from career_os.services import sources as sources_svc  # noqa: E402
from career_os.services import update as update_svc  # noqa: E402


class CareerOSTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_career.db"
        db.init_db(self.db_path)
        self.conn = db.get_connection(self.db_path)

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()


class TestDbInit(CareerOSTestCase):
    def test_schema_version_set(self):
        self.assertEqual(db.schema_version(self.conn), "5")

    def test_init_is_idempotent(self):
        # Calling init_db again must not raise or wipe data.
        companies_svc.get_or_create_company(self.conn, "TestCo")
        db.init_db(self.db_path)
        row = self.conn.execute("SELECT name FROM companies WHERE name='TestCo'").fetchone()
        self.assertIsNotNone(row)


class TestAddJobAndDuplicates(CareerOSTestCase):
    def test_add_job_creates_role(self):
        result = roles_svc.add_job(
            self.conn,
            company="OpenAI",
            title="Principal TPM",
            jd_text="We need a Principal Technical Program Manager for our AI platform and evaluation framework.",
        )
        self.assertFalse(result["duplicate"])
        self.assertIsNotNone(result["role_id"])
        role = roles_svc.get_role(self.conn, result["role_id"])
        self.assertEqual(role["company_name"], "OpenAI")
        self.assertEqual(role["title"], "Principal TPM")

    def test_duplicate_role_detected(self):
        first = roles_svc.add_job(self.conn, company="Apple", title="EPM, Siri", jd_text="evaluation framework")
        second = roles_svc.add_job(self.conn, company="Apple", title="EPM, Siri", jd_text="a different JD body")
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["role_id"], second["role_id"])

    def test_archetype_classification_is_a_claim_not_a_fact(self):
        result = roles_svc.add_job(
            self.conn, company="Google", title="Search PM",
            jd_text="search retrieval ranking relevance recommendation personalization " * 3,
        )
        role = roles_svc.get_role(self.conn, result["role_id"])
        self.assertEqual(role["archetype"], "B")
        recorded = claims_svc.claims_for(self.conn, "role", result["role_id"])
        self.assertTrue(any(c["source_type"] == "model_inference" for c in recorded))


class TestApplicationUpdates(CareerOSTestCase):
    def test_set_status_updates_role_and_application(self):
        result = roles_svc.add_job(self.conn, company="Anthropic", title="TPM")
        role_id = result["role_id"]
        applications_svc.set_status(self.conn, role_id, "applied", channel="referral")
        app = applications_svc.get_application(self.conn, role_id)
        self.assertEqual(app["status"], "applied")
        self.assertEqual(app["channel"], "referral")
        role = roles_svc.get_role(self.conn, role_id)
        self.assertEqual(role["status"], "applied")

    def test_rejects_unknown_status(self):
        result = roles_svc.add_job(self.conn, company="Meta", title="PM")
        with self.assertRaises(ValueError):
            applications_svc.set_status(self.conn, result["role_id"], "not_a_real_status")

    def test_free_text_update_sets_application_status(self):
        result = roles_svc.add_job(self.conn, company="NVIDIA", title="TPM")
        role_id = result["role_id"]
        outcome = update_svc.apply_update(self.conn, "Applied to NVIDIA role through referral from John.")
        self.assertEqual(outcome["kind"], "application_status")
        self.assertEqual(outcome["role_id"], role_id)
        self.assertEqual(outcome["status"], "applied")

    def test_free_text_update_falls_back_to_note_when_unresolved(self):
        outcome = update_svc.apply_update(self.conn, "Some totally unrelated company rejected me.")
        # "SomeCorp" was never created as a company, so this cannot resolve to
        # a role; it must be preserved as a note, not silently dropped.
        self.assertIn(outcome["kind"], ("note_fallback",))


class TestRawSourceDedup(CareerOSTestCase):
    def test_duplicate_content_returns_same_id(self):
        first = sources_svc.create_raw_source(self.conn, "note", content="hello world")
        second = sources_svc.create_raw_source(self.conn, "note", content="hello world")
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["id"], second["id"])


class TestEvidenceLinking(CareerOSTestCase):
    def test_evidence_links_to_skill_and_closes_gap(self):
        result = roles_svc.add_job(
            self.conn, company="Databricks", title="TPM",
            jd_text="Must have RAG and LLM evaluation experience.",
        )
        role_id = result["role_id"]
        dossier_gaps_before = skills_svc.role_requirements(self.conn, role_id)
        self.assertTrue(any(not False for _ in dossier_gaps_before))  # requirements extracted

        evidence_svc.add_evidence(
            self.conn, company="Lumen Labs", project="RAG platform",
            metrics="accuracy/latency/adoption tracked", thresholds="needs_evidence",
            skill_names=["RAG", "LLM"],
        )
        covered = skills_svc.skills_with_evidence(self.conn)
        rag_skill_id = skills_svc.get_or_create_skill(self.conn, "RAG")
        self.assertIn(rag_skill_id, covered)


class TestPipelineQuery(CareerOSTestCase):
    def test_pipeline_lists_roles(self):
        roles_svc.add_job(self.conn, company="Cisco", title="TPM")
        rows = pipeline_svc.get_pipeline(self.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["company"], "Cisco")


class TestAddNote(CareerOSTestCase):
    def test_note_preserved_even_when_unlinked(self):
        result = notes_svc.add_note(self.conn, "Random thought with no company or contact mentioned.")
        self.assertIsNone(result["linked_entity_type"])
        row = self.conn.execute(
            "SELECT raw_text FROM notes_inbox WHERE id = ?", (result["note_id"],)
        ).fetchone()
        self.assertEqual(row["raw_text"], "Random thought with no company or contact mentioned.")


if __name__ == "__main__":
    unittest.main()
