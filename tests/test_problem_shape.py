"""Tests for the Generalist + Specialist Spike (problem-shape) framework."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from career_os import db, heuristics, seed  # noqa: E402
from career_os.services import claims as claims_svc  # noqa: E402
from career_os.services import interview_prep as prep_svc  # noqa: E402
from career_os.services import problem_shape as shape_svc  # noqa: E402
from career_os.services import roles as roles_svc  # noqa: E402

GS_JD = ("Technical Program Manager, Search. Drive search relevance, retrieval and ranking quality across "
         "engineering, product, research, infrastructure, legal and partner teams. Navigate ambiguity and "
         "tradeoffs in a fast-paced GenAI environment; own the roadmap and prioritization decisions.")
SPECIALIST_JD = ("Product Manager, GPU Kernels. CUDA kernel optimization, compiler and TensorRT work, "
                 "inference optimization, distributed training and GPU architecture. Deep CUDA expertise required.")
PMO_JD = ("Program Manager. Maintain the project plan, RAID log, milestones and schedule. Status report and "
          "status update to leadership, track dependencies, run meeting cadence, coordinate reporting.")


class ShapeTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "t.db"
        db.init_db(self.path)
        self.conn = db.get_connection(self.path)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()


class TestMigration(unittest.TestCase):
    def test_v1_database_gains_columns_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.db"
            db.init_db(path)
            conn = db.get_connection(path)
            # Rebuild a v1-shaped database: drop the v2 columns, keep a real row.
            for table, cols in db._V2_COLUMNS.items():
                for col in cols:
                    conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
            conn.execute("UPDATE schema_meta SET value = '1' WHERE key = 'schema_version'")
            conn.execute("INSERT INTO companies (name) VALUES ('Co')")
            conn.execute("INSERT INTO roles (company_id, title) VALUES (1, 'Keep me')")
            conn.commit()
            conn.close()
            db.init_db(path)
            conn = db.get_connection(path)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(roles)")}
            self.assertIn("problem_shape", cols)
            self.assertEqual(conn.execute("SELECT title FROM roles").fetchone()["title"], "Keep me")
            self.assertEqual(db.schema_version(conn), "5")
            db.init_db(path)  # idempotent
            conn.close()


class TestOrganizationsRemoval(unittest.TestCase):
    def _old_shape_db(self, d, with_org_row=False):
        path = Path(d) / "old.db"
        db.init_db(path)
        conn = db.get_connection(path)
        # recreate the pre-v5 shape: an organizations table and roles.organization_id referencing it
        conn.execute("CREATE TABLE organizations (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, name TEXT)")
        conn.execute("ALTER TABLE roles ADD COLUMN organization_id INTEGER REFERENCES organizations(id)")
        conn.execute("INSERT INTO companies (name) VALUES ('Co')")
        conn.execute("INSERT INTO roles (company_id, title) VALUES (1, 'Keep me')")
        conn.execute("INSERT INTO applications (role_id, status) VALUES (1, 'applied')")
        if with_org_row:
            conn.execute("INSERT INTO organizations (company_id, name) VALUES (1, 'Team')")
        conn.commit()
        conn.close()
        return path

    def test_unused_organizations_are_removed_and_roles_keep_working(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._old_shape_db(d)
            db.init_db(path)
            conn = db.get_connection(path)
            tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertNotIn("organizations", tables)
            self.assertNotIn("organization_id", {r["name"] for r in conn.execute("PRAGMA table_info(roles)")})
            self.assertEqual(conn.execute("SELECT title FROM roles").fetchone()["title"], "Keep me")
            self.assertEqual(conn.execute("SELECT status FROM applications WHERE role_id = 1").fetchone()["status"], "applied")
            conn.execute("INSERT INTO roles (company_id, title) VALUES (1, 'New role works')")  # FK no longer dangling
            conn.commit()
            self.assertEqual(list(conn.execute("PRAGMA foreign_key_check")), [])
            self.assertTrue(conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_roles_company'").fetchone())
            conn.close()
            db.init_db(path)  # idempotent

    def test_organization_data_is_never_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._old_shape_db(d, with_org_row=True)
            db.init_db(path)
            conn = db.get_connection(path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0], 1)
            conn.close()


class TestHeuristics(unittest.TestCase):
    def test_gs_role(self):
        r = heuristics.infer_problem_shape(GS_JD, "Technical Program Manager, Search")
        self.assertEqual(r["problem_shape"], "generalist_specialist")
        self.assertEqual(r["interconnectedness"], "high")

    def test_specialist_role(self):
        r = heuristics.infer_problem_shape(SPECIALIST_JD, "Product Manager, GPU Kernels")
        self.assertEqual(r["problem_shape"], "specialist")

    def test_low_signal_is_unknown_not_guessed(self):
        r = heuristics.infer_problem_shape("We are hiring. Apply now.", "Manager")
        self.assertEqual(r["problem_shape"], "unknown")
        self.assertEqual(r["rate_of_change"], "unknown")

    def test_pmo_flag(self):
        r = heuristics.infer_problem_shape(PMO_JD, "Program Manager")
        self.assertTrue(r["pmo_risk"])


class TestSpikeStrength(ShapeTestCase):
    def test_strength_is_derived_from_evidence_not_stored(self):
        from career_os.services import evidence as evidence_svc
        self.assertEqual(shape_svc.spike_strength(self.conn, "eval")["strength"], "weak")
        e1 = evidence_svc.add_evidence(self.conn, company="A", project="p1", metrics="+10 NDCG",
                                       ownership="owned", thresholds="needs_evidence")
        e2 = evidence_svc.add_evidence(self.conn, company="B", project="p2", metrics="-5% errors",
                                       ownership="owned", thresholds="needs_evidence")
        spike_id = self.conn.execute("SELECT id FROM depth_spikes WHERE code='eval'").fetchone()["id"]
        for e in (e1, e2):
            self.conn.execute("INSERT INTO evidence_spikes VALUES (?, ?)", (e, spike_id))
        self.conn.commit()
        # proven rows exist, but thresholds (the eval marker) are unknown -> cannot be 'strong'
        self.assertEqual(shape_svc.spike_strength(self.conn, "eval")["strength"], "partial")
        self.conn.execute("UPDATE evidence SET thresholds = 'ship if NDCG >= +5' WHERE id = ?", (e1,))
        self.conn.commit()
        self.assertEqual(shape_svc.spike_strength(self.conn, "eval")["strength"], "strong")

    def test_seed_links_are_hypotheses_with_claims(self):
        seed.run_seed(self.conn)
        again = seed.run_seed(self.conn)  # idempotent
        self.assertEqual(again["spike_links_added"], 0)
        ev = self.conn.execute("SELECT id FROM evidence WHERE company='Northwind Commerce'").fetchone()["id"]
        claims = claims_svc.claims_for(self.conn, "evidence", ev)
        self.assertTrue(claims and all(c["source_type"] == "model_inference" for c in claims))
        # eval spike has no known thresholds in seed evidence, so it must not read as strong
        self.assertNotEqual(shape_svc.spike_strength(self.conn, "eval")["strength"], "strong")


class TestRoleAnalysis(ShapeTestCase):
    def test_add_job_populates_shape_and_records_claim(self):
        seed.run_seed(self.conn)
        res = roles_svc.add_job(self.conn, company="OpenAI", title="TPM, Search", jd_text=GS_JD)
        self.assertEqual(res["problem_shape"], "generalist_specialist")
        self.assertEqual(res["depth_match"], "strong")
        claims = claims_svc.claims_for(self.conn, "role", res["role_id"])
        self.assertTrue(any(c["claim_text"].startswith("problem_shape analysis") and
                            c["source_type"] == "model_inference" for c in claims))

    def test_specialist_depth_is_weak_without_evidence(self):
        seed.run_seed(self.conn)
        res = roles_svc.add_job(self.conn, company="NVIDIA", title="PM, GPU Kernels", jd_text=SPECIALIST_JD)
        self.assertEqual(res["problem_shape"], "specialist")
        self.assertEqual(res["depth_match"], "weak")

    def test_user_confirmed_field_survives_reanalysis(self):
        res = roles_svc.add_job(self.conn, company="OpenAI", title="TPM, Search", jd_text=GS_JD)
        rid = res["role_id"]
        shape_svc.confirm_field(self.conn, rid, "problem_shape", "generalist")
        shape_svc.analyze_role(self.conn, rid)
        self.assertEqual(roles_svc.get_role(self.conn, rid)["problem_shape"], "generalist")
        with self.assertRaises(ValueError):
            shape_svc.confirm_field(self.conn, rid, "problem_shape", "nonsense")

    def test_attach_jd_reclassifies_a_titles_only_role(self):
        seed.run_seed(self.conn)
        res = roles_svc.add_job(self.conn, company="Apple", title="EPM, AI/ML")
        before = roles_svc.get_role(self.conn, res["role_id"])
        self.assertEqual(before["role_tier"], 3)  # no JD: honest fallback
        out = roles_svc.attach_jd(self.conn, res["role_id"], GS_JD + " program manager machine learning.")
        after = roles_svc.get_role(self.conn, res["role_id"])
        self.assertEqual(out["role_tier"], 1)  # Tier-A company + clear archetype
        self.assertEqual(after["problem_shape"], "generalist_specialist")
        self.assertIsNotNone(after["raw_source_id"])
        self.assertIsNone(roles_svc.attach_jd(self.conn, 9999, "x"))

    def test_no_jd_text_stays_unknown(self):
        res = roles_svc.add_job(self.conn, company="Cisco", title="TPM")
        a = shape_svc.analyze_role(self.conn, res["role_id"])
        self.assertEqual(a["problem_shape"], "unknown")
        self.assertEqual(a["depth_match"], "unknown")

    def test_why_pursue_has_required_sections(self):
        seed.run_seed(self.conn)
        res = roles_svc.add_job(self.conn, company="OpenAI", title="TPM, Search", jd_text=GS_JD)
        w = shape_svc.why_pursue(self.conn, res["role_id"])
        for key in ("breadth_fit", "critical_depth_lever", "supporting_evidence", "gaps",
                    "career_compounding", "recommendation"):
            self.assertIn(key, w)


class TestInterviewPrep(ShapeTestCase):
    def test_story_frame_reports_missing_instead_of_inventing(self):
        seed.run_seed(self.conn)
        ev = self.conn.execute("SELECT id FROM evidence WHERE company='Northwind Commerce'").fetchone()["id"]
        f = prep_svc.story_frame(self.conn, ev)
        self.assertIn("thresholds", f["missing"]["mechanism"])
        self.assertEqual(f["lever_status"], "hypothesis (not verified)")

    def test_diagnose_breadth_without_depth(self):
        answer = ("We worked with engineering, product, infrastructure and many partner teams across markets "
                  "to coordinate the program and align stakeholders.")
        d = prep_svc.diagnose_answer(answer)
        self.assertEqual(d["diagnosis"], "Breadth demonstrated; specialist credibility insufficiently visible.")
        self.assertEqual(len(d["repair"]), 5)

    def test_diagnose_complete_answer(self):
        answer = ("The key lever was ranking relevance across engineering and product teams and markets. "
                  "I decided to gate launch on a ranking NDCG threshold per segment against the baseline metric. "
                  "Result: +20% impressions.")
        d = prep_svc.diagnose_answer(answer)
        self.assertEqual(d["missing"], [])


if __name__ == "__main__":
    unittest.main()
