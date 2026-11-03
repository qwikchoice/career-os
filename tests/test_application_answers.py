"""Application questions and answers, stored per role."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from career_os import db  # noqa: E402
from career_os.services import answers as answers_svc  # noqa: E402
from career_os.services import export as export_svc  # noqa: E402
from career_os.services import roles as roles_svc  # noqa: E402


class TestApplicationAnswers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "t.db"
        db.init_db(path)
        self.conn = db.get_connection(path)
        self.role_a = roles_svc.add_job(self.conn, company="Acme", title="TPM, Launches", jd_text="Program manager launches.")["role_id"]
        self.role_b = roles_svc.add_job(self.conn, company="Acme", title="TPM, Platform", jd_text="Program manager platform.")["role_id"]

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_save_and_list_per_role(self):
        answers_svc.save_answer(self.conn, self.role_a, "Why Acme?", "Because launches.", source_file="a.md")
        answers_svc.save_answer(self.conn, self.role_b, "Why Acme?", "Because platform.")
        self.assertEqual(len(answers_svc.list_answers(self.conn)), 2)
        only_a = answers_svc.list_answers(self.conn, self.role_a)
        self.assertEqual([r["answer"] for r in only_a], ["Because launches."])
        self.assertEqual(only_a[0]["company"], "Acme")

    def test_same_question_updates_instead_of_duplicating(self):
        first = answers_svc.save_answer(self.conn, self.role_a, "Why Acme?", "v1")
        second = answers_svc.save_answer(self.conn, self.role_a, "  why acme  ", "v2")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["action"], "updated")
        rows = answers_svc.list_answers(self.conn, self.role_a)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["answer"], "v2")

    def test_unknown_role_and_blank_input_rejected(self):
        with self.assertRaises(ValueError):
            answers_svc.save_answer(self.conn, 9999, "Q?", "A")
        with self.assertRaises(ValueError):
            answers_svc.save_answer(self.conn, self.role_a, "Q?", "   ")

    def test_appears_in_export_with_role_name(self):
        answers_svc.save_answer(self.conn, self.role_a, "Cover letter", "Dear team")
        rows = export_svc.export_all(self.conn)["application_answers"]
        self.assertEqual(len(rows), 1)
        self.assertIn("TPM, Launches", rows[0]["role"])


if __name__ == "__main__":
    unittest.main()
