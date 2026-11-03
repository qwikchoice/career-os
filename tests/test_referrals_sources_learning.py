"""Tests for referrals, job sources and learning resources."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from career_os import db, seed  # noqa: E402
from career_os.services import brief as brief_svc  # noqa: E402
from career_os.services import evidence as evidence_svc  # noqa: E402
from career_os.services import job_sources as js  # noqa: E402
from career_os.services import learning as lr  # noqa: E402
from career_os.services import referrals as ref  # noqa: E402
from career_os.services import roles as roles_svc  # noqa: E402
from career_os.services import update as up  # noqa: E402

SD_JD = ("Technical Program Manager. System design and distributed systems; own API architecture, reliability "
         "and latency; define evaluation for LLM quality; cross-functional engineering and product partners.")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "t.db"
        db.init_db(self.path)
        self.conn = db.get_connection(self.path)
        seed.run_seed(self.conn)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()


class TestReferralParsing(unittest.TestCase):
    def test_offer(self):
        p = ref.match_referral_update("Dev from LinkedIn said he can refer me at Google.")
        self.assertEqual((p["action"], p["name"], p["source"]), ("offered", "Dev", "LinkedIn"))

    def test_request_name_does_not_swallow_following_word(self):
        p = ref.match_referral_update("Ask Dev to refer me for job 123")
        self.assertEqual((p["action"], p["name"]), ("requested", "Dev"))

    def test_follow_up_name_and_date(self):
        p = ref.match_referral_update("Follow up with Dev next Monday")
        self.assertEqual(p["name"], "Dev")
        d = date.fromisoformat(p["follow_up_date"])
        self.assertEqual(d.weekday(), 0)
        self.assertGreater(d, date.today())
        self.assertLessEqual(d - date.today(), timedelta(days=7))

    def test_three_word_name(self):
        p = ref.match_referral_update("Kartik Kumar Pillai referred me to Technical Program Manager, Ranking AI")
        self.assertEqual((p["action"], p["name"]), ("submitted", "Kartik Kumar Pillai"))

    def test_existing_application_phrases_are_not_hijacked(self):
        self.assertIsNone(ref.match_referral_update("Applied to OpenAI through referral from John."))
        self.assertIsNone(ref.match_referral_update("Amazon recruiter screen scheduled Tuesday."))


class TestReferralFlow(Base):
    def test_offer_then_query_unused(self):
        r = up.apply_update(self.conn, "Dev said he can refer me at Google.")
        self.assertEqual((r["kind"], r["status"], r["company"]), ("referral", "offered", "Google"))
        unused = ref.list_referrals(self.conn, "unused")
        self.assertEqual([(x["contact_name"], x["company_name"]) for x in unused], [("Dev", "Google")])

    def test_incomplete_offer_is_preserved(self):
        r = up.apply_update(self.conn, "John said he can refer me somewhere at Microsoft.")
        self.assertEqual(r["company"], "Microsoft")
        r2 = up.apply_update(self.conn, "Sam said he would refer me.")
        self.assertIsNone(r2["company"])
        self.assertEqual(r2["status"], "offered")

    def test_lifecycle_links_role_and_application(self):
        up.apply_update(self.conn, "Nina on LinkedIn said she can refer me at Databricks.")
        res = roles_svc.add_job(self.conn, company="Databricks", title="Senior TPM AI Platform", jd_text="AI platform")
        out = up.apply_update(self.conn, "Ask Nina for referral for the Senior TPM AI Platform role.")
        self.assertEqual((out["status"], out["role_id"]), ("requested", res["role_id"]))
        app = self.conn.execute("SELECT status FROM applications WHERE role_id = ?", (res["role_id"],)).fetchone()
        self.assertEqual(app["status"], "referral_requested")
        out = up.apply_update(self.conn, "Nina submitted it.")
        self.assertEqual(out["status"], "submitted")
        app = self.conn.execute("SELECT status, channel, referral_contact_id FROM applications WHERE role_id = ?",
                                (res["role_id"],)).fetchone()
        self.assertEqual((app["status"], app["channel"]), ("referred", "referral"))
        self.assertIsNotNone(app["referral_contact_id"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS n FROM referrals").fetchone()["n"], 1)  # one record, updated
        self.assertEqual([x["contact_name"] for x in ref.list_referrals(self.conn, "waiting")], ["Nina"])

    def test_unmatched_role_text_is_kept_as_hint(self):
        up.apply_update(self.conn, "Nina said she can refer me at Databricks.")
        out = up.apply_update(self.conn, "Ask Nina for referral for the Principal Quantum Basket Weaver role.")
        self.assertIsNone(out["role_id"])
        self.assertIn("Quantum Basket Weaver", out["role_hint"])

    def test_follow_up_sets_date_without_duplicating_contact(self):
        up.apply_update(self.conn, "Dev said he can refer me at Google.")
        out = up.apply_update(self.conn, "Follow up with Dev next Monday.")
        self.assertEqual(out["contact"], "Dev")
        self.assertIsNotNone(out["follow_up_date"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS n FROM contacts WHERE name LIKE 'Dev%'").fetchone()["n"], 1)

    def test_repeat_offer_does_not_downgrade(self):
        up.apply_update(self.conn, "Dev said he can refer me at Google.")
        self.conn.execute("UPDATE referrals SET status = 'submitted'")
        self.conn.commit()
        out = up.apply_update(self.conn, "Dev said he can refer me at Google.")
        self.assertEqual(out["status"], "submitted")

    def test_priority_is_qualitative_and_derived(self):
        up.apply_update(self.conn, "Dev said he can refer me at Google.")  # Tier A, no role
        up.apply_update(self.conn, "Zed said he can refer me at Watchco.")  # unknown company
        pri = {r["contact_name"]: r["priority"] for r in ref.list_referrals(self.conn)}
        self.assertEqual(pri["Dev"], "Medium")
        self.assertEqual(pri["Zed"], "Low")
        roles_svc.add_job(self.conn, company="Google", title="TPM Search", jd_text="search retrieval ranking relevance " * 3)
        self.conn.execute("UPDATE roles SET role_tier = 1")
        self.conn.commit()
        pri = {r["contact_name"]: r["priority"] for r in ref.list_referrals(self.conn)}
        self.assertEqual(pri["Dev"], "High")

    def test_tier1_roles_without_path(self):
        a = roles_svc.add_job(self.conn, company="OpenAI", title="TPM A", jd_text="x")
        b = roles_svc.add_job(self.conn, company="Meta", title="TPM B", jd_text="x")
        self.conn.execute("UPDATE roles SET role_tier = 1")
        self.conn.commit()
        up.apply_update(self.conn, "Dev said he can refer me at Meta.")
        g = ref.roles_without_referral_path(self.conn, 1)
        self.assertEqual([r["id"] for r in g["no_path"]], [a["role_id"]])
        self.assertEqual([r["id"] for r in g["company_level_only"]], [b["role_id"]])

    def test_followup_view(self):
        up.apply_update(self.conn, "Dev said he can refer me at Google.")
        self.conn.execute("UPDATE referrals SET status='requested', follow_up_date = ?",
                          ((date.today() - timedelta(days=1)).isoformat(),))
        self.conn.commit()
        self.assertEqual(len(ref.list_referrals(self.conn, "followup")), 1)


class TestDiscoveryVsChannel(Base):
    def test_add_job_keeps_both(self):
        res = roles_svc.add_job(self.conn, company="OpenAI", title="TPM", jd_text="x", source="LinkedIn",
                                applied_via="employee referral")
        row = self.conn.execute("SELECT r.source, a.channel FROM roles r JOIN applications a ON a.role_id = r.id WHERE r.id = ?",
                                (res["role_id"],)).fetchone()
        self.assertEqual((row["source"], row["channel"]), ("LinkedIn", "referral"))

    def test_free_text_does_not_overwrite_discovery_with_channel(self):
        res = roles_svc.add_job(self.conn, company="OpenAI", title="TPM", jd_text="x")
        rid = res["role_id"]
        up.apply_update(self.conn, f"I found this OpenAI job on LinkedIn, role {rid}.")
        out = up.apply_update(self.conn, f"Applied to role {rid} through an employee referral from Dev.")
        self.assertEqual(out["application_channel"], "referral")
        row = self.conn.execute("SELECT r.source, a.channel FROM roles r JOIN applications a ON a.role_id = r.id WHERE r.id = ?",
                                (rid,)).fetchone()
        self.assertEqual((row["source"], row["channel"]), ("LinkedIn", "referral"))
        self.assertEqual(self.conn.execute("SELECT status FROM referrals WHERE role_id = ?", (rid,)).fetchone()["status"], "submitted")

    def test_conflicting_discovery_is_reported_not_overwritten(self):
        res = roles_svc.add_job(self.conn, company="OpenAI", title="TPM", jd_text="x", source="Indeed")
        out = up.apply_update(self.conn, f"I found role {res['role_id']} on LinkedIn.")
        self.assertEqual(out["discovery_source"], "Indeed")
        self.assertIn("kept it", out["note"])

    def test_existing_applied_via_linkedin_still_works(self):
        res = roles_svc.add_job(self.conn, company="Cisco", title="TPM", jd_text="x")
        out = up.apply_update(self.conn, f"Applied to role {res['role_id']} via LinkedIn.")
        self.assertEqual(out["application_channel"], "linkedin")


class TestJobSources(Base):
    def test_seed_labels_priorities_as_hypotheses(self):
        rows = {s["name"]: s for s in js.list_sources(self.conn)}
        self.assertEqual(rows["LinkedIn"]["priority_basis"], "seed_hypothesis")
        self.assertIsNone(rows["CalCareers"]["priority"])  # special channel, not ranked
        self.assertEqual(js.seed_job_sources(self.conn), 0)  # idempotent

    def test_natural_language(self):
        self.assertEqual(up.apply_update(self.conn, "Add RemoteOK as a remote job source.")["source_type"], "remote_board")
        out = up.apply_update(self.conn, "I don't think Indeed is giving me good jobs anymore.")
        self.assertEqual((out["priority"], out["basis"]), ("Low", "user_stated"))
        self.assertEqual(self.conn.execute("SELECT priority FROM job_sources WHERE name='Indeed'").fetchone()["priority"], "Low")

    def test_unknown_source_is_captured_not_rejected(self):
        res = roles_svc.add_job(self.conn, company="OpenAI", title="TPM", jd_text="x", source="AI Jobs Board")
        self.assertEqual(self.conn.execute("SELECT source FROM roles WHERE id = ?", (res["role_id"],)).fetchone()["source"], "AI Jobs Board")
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM job_sources WHERE name='AI Jobs Board'").fetchone())

    def test_no_conclusion_without_enough_data(self):
        for i in range(3):
            roles_svc.add_job(self.conn, company="OpenAI", title=f"TPM {i}", jd_text="x", source="LinkedIn")
        s = next(x for x in js.source_stats(self.conn) if x["source"] == "LinkedIn")
        self.assertFalse(s["enough_data"])
        self.assertIsNone(s["suggestion"])


class TestLearning(Base):
    def test_inference_from_sentences(self):
        r = lr.infer_resource("Add this Educative course. It has good distributed-system design material.")
        self.assertEqual((r["provider"], r["category"], r["format"]), ("Educative", "engineering", "course"))
        self.assertIn("distributed systems", r["topics"])
        self.assertIsNone(r["estimated_minutes"])  # never guessed
        e = lr.infer_resource("Exponent system-design course")
        self.assertEqual((e["provider"], e["category"]), ("Exponent", "high_stakes"))

    def test_time_and_depth_only_when_stated(self):
        r = lr.infer_resource("Intro to RAG, a 45 min video https://youtu.be/abc")
        self.assertEqual((r["estimated_minutes"], r["depth"], r["format"], r["provider"]), (45, "intro", "video", "YouTube"))

    def test_nl_routing_and_duplicate(self):
        out = up.apply_update(self.conn, "This Coursera course seems useful for agentic AI. https://coursera.org/learn/agents")
        self.assertEqual((out["kind"], out["category"]), ("learning_resource", "ai"))
        again = up.apply_update(self.conn, "Add this Coursera course https://coursera.org/learn/agents")
        self.assertTrue(again["duplicate"])

    def test_job_text_is_not_mistaken_for_a_resource(self):
        self.assertFalse(lr.match_learning_update("Applied to the OpenAI role, the recruiter sent a course of action."))

    def test_plan_recommends_stored_resource_and_never_invents(self):
        res = roles_svc.add_job(self.conn, company="Databricks", title="TPM Platform", jd_text=SD_JD)
        plan = lr.learning_plan(self.conn, res["role_id"], 90)
        self.assertTrue(plan["gaps_without_resource"] or plan["highest_priority"])
        titles_before = {t["resource"]["title"] for t in plan["highest_priority"]}
        self.assertFalse(any("Exponent" in t or "Educative" in t for t in titles_before))  # nothing stored yet
        up.apply_update(self.conn, "Add this Educative course. It has good distributed-system design material.")
        up.apply_update(self.conn, "Add this Exponent system-design course.")
        plan = lr.learning_plan(self.conn, res["role_id"], 90)
        titles = [t["resource"]["title"] for t in plan["highest_priority"]]
        self.assertTrue(any("Educative" in t for t in titles))
        self.assertTrue(any("Exponent" in t for t in titles))
        self.assertLessEqual(len(titles), lr.MAX_ITEMS)

    def test_strong_evidence_skips_topic(self):
        for i in range(2):
            evidence_svc.add_evidence(self.conn, company=f"Co{i}", project="launch readiness release management go-live",
                                      metrics="12 releases", ownership="owned", skill_names=["Release Management"])
        res = roles_svc.add_job(self.conn, company="Cisco", title="TPM", jd_text="launch readiness and release management for go-live")
        plan = lr.learning_plan(self.conn, res["role_id"], 90)
        self.assertTrue(any(s["topic"] == "launch readiness" and "Evidence" in s["why"] for s in plan["skip_for_now"]))

    def test_budget_pushes_long_resources_to_later(self):
        res = roles_svc.add_job(self.conn, company="Databricks", title="TPM Platform", jd_text=SD_JD)
        up.apply_update(self.conn, "Add this Educative course. It has good distributed-system design material. 5 hours.")
        plan = lr.learning_plan(self.conn, res["role_id"], 60)
        self.assertTrue(any("over the 60-min budget" in (x.get("note") or "") for x in plan["later"]))

    def test_category_validation(self):
        with self.assertRaises(ValueError):
            lr.infer_resource("x course", category="cooking")

    def test_usefulness_filters_out_not_useful(self):
        up.apply_update(self.conn, "Add this Educative course. It has good distributed-system design material.")
        rid = self.conn.execute("SELECT id FROM learning_resources").fetchone()["id"]
        lr.set_usefulness(self.conn, rid, "not_useful")
        self.assertIsNone(lr._pick_resource(self.conn, "distributed systems", None, "engineering"))


class TestBrief(Base):
    def test_combined_query(self):
        up.apply_update(self.conn, "Nina said she can refer me at Databricks.")
        res = roles_svc.add_job(self.conn, company="Databricks", title="Senior TPM AI Platform", jd_text=SD_JD,
                                source="Company Career Pages")
        self.conn.execute("UPDATE roles SET role_tier = 1 WHERE id = ?", (res["role_id"],))
        self.conn.commit()
        rows = brief_svc.brief(self.conn, top=5)
        r = next(x for x in rows if x["id"] == res["role_id"])
        self.assertEqual(r["discovery_source"], "Company Career Pages")
        self.assertEqual(r["referral_paths"][0]["contact"], "Nina")
        self.assertIn("Ask Nina", r["next_action"])
        self.assertTrue(r["learning_gaps"])


if __name__ == "__main__":
    unittest.main()
