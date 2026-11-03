#!/usr/bin/env python3
"""Career OS CLI — thin wrapper over career_os.services.*

Business logic lives in the service layer (career_os/services/), not here,
so MCP/other clients can call the same functions later (spec section 28).

Usage:
    python cli.py init
    python cli.py seed
    python cli.py add-job --company "OpenAI" --title "Principal TPM" --jd-file jd.txt
    python cli.py add-job --company "OpenAI" --jd-text "paste full JD here"
    python cli.py add-note "Nina from Apple said he'd consider me for other roles."
    python cli.py update "Applied to role 3 through referral from John."
    python cli.py pipeline
    python cli.py role 3
    python cli.py review
    python cli.py analyze-shape [--role 3 | --all]
    python cli.py why 3
    python cli.py shape-set 3 problem_shape generalist_specialist
    python cli.py story-frame 1
    python cli.py diagnose "my interview answer text"
    python cli.py update "Dev from LinkedIn said he can refer me at Google."
    python cli.py referrals --unused | --waiting | --followup | --company Google | --tier A | --gaps
    python cli.py learn-add "https://... Exponent system design course" ; python cli.py learn --role 5
    python cli.py sources [--stats] ; python cli.py source-add CalCareers --type government
    python cli.py brief [--top 5]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC_ROOT))

from career_os import db  # noqa: E402
from career_os import seed as seed_mod  # noqa: E402
from career_os import demo as demo_mod  # noqa: E402
from career_os.services import answers as answers_svc  # noqa: E402
from career_os.services import dossier as dossier_svc  # noqa: E402
from career_os.services import metrics as metrics_svc  # noqa: E402
from career_os.services import actions as actions_svc  # noqa: E402
from career_os.services import applications as apps_svc  # noqa: E402
from career_os.services import brief as brief_svc  # noqa: E402
from career_os.services import export as export_svc  # noqa: E402
from career_os.services import job_sources as sources_svc  # noqa: E402
from career_os.services import learning as learning_svc  # noqa: E402
from career_os.services import referrals as referrals_svc  # noqa: E402
from career_os.services import interview_prep as prep_svc  # noqa: E402
from career_os.services import problem_shape as shape_svc  # noqa: E402
from career_os.services import notes as notes_svc  # noqa: E402
from career_os.services import pipeline as pipeline_svc  # noqa: E402
from career_os.services import review as review_svc  # noqa: E402
from career_os.services import roles as roles_svc  # noqa: E402
from career_os.services import update as update_svc  # noqa: E402


SHAPE_SHORT = {'generalist': 'G', 'generalist_specialist': 'G+S', 'specialist': 'S', 'unknown': '?'}


def cmd_init(args):
    path = db.init_db()
    print(f"Career OS DB ready at {path}")


def cmd_seed_demo(args):
    conn = db.get_connection()
    try:
        result = demo_mod.run_demo(conn)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
    finally:
        conn.close()
    print(f"Demo data added (fictional): {result['roles']} roles, {result['interviews']} interviews, {result['contacts']} contacts.")


def cmd_seed(args):
    conn = db.get_connection()
    try:
        result = seed_mod.run_seed(conn)
        print(f"Seeded {result['companies_seeded']} example company rows.")
        print(f"Seeded {result['evidence_seeded']} new EXAMPLE evidence rows (fictional; replace with your own).")
    finally:
        conn.close()


def cmd_add_job(args):
    conn = db.get_connection()
    try:
        result = roles_svc.add_job(
            conn,
            company=args.company,
            title=args.title,
            jd_text=args.jd_text,
            jd_file=args.jd_file,
            url=args.url,
            location=args.location,
            source=args.source,
            applied_via=args.applied_via,
            job_code=args.job_code,
        )
        if result.get("duplicate"):
            print(f"Duplicate of existing role {result['role_id']} (canonical_key={result['canonical_key']}).")
            print("No new row created. Use `career role <id>` to view it.")
            return
        print(f"Role {result['role_id']} created: {args.company}")
        print(f"  classifier: {result.get('classifier', 'heuristic')}")
        print(f"  archetype: {result['archetype']} (confidence: {result['fit_confidence']})")
        print(f"  priority: {roles_svc.tier_label(result['role_tier'])} (tier {result['role_tier']})")
        if result["matched_skills"]:
            print(f"  matched skills: {', '.join(result['matched_skills'])}")
        if result.get("discovery_source"):
            print(f"  discovery source: {result['discovery_source']}")
        if result.get("application_channel"):
            print(f"  application channel: {result['application_channel']}")
        if result.get("problem_shape"):
            print(f"  problem shape: {shape_svc.SHAPE_LABELS[result['problem_shape']]} (depth match: {result['depth_match']})")
        if result["primary_gap"]:
            print(f"  primary gap: {result['primary_gap']} (no linked evidence yet)")
        print(f"  NOTE: archetype/tier/problem shape are model_inference via {result.get('classifier', 'heuristic')}, not verified facts.")
    finally:
        conn.close()


def cmd_attach_jd(args):
    conn = db.get_connection()
    try:
        text = Path(args.jd_file).read_text(encoding="utf-8") if args.jd_file else (args.jd_text or sys.stdin.read())
        r = roles_svc.attach_jd(conn, args.role_id, text)
        if not r:
            print(f"No role with id {args.role_id}")
            return
        print(f"JD attached to role {r['role_id']} (classifier: {r['classifier']}); re-derived from the JD:")
        print(f"  archetype {r['archetype']} ({r['fit_confidence']}), priority {roles_svc.tier_label(r['role_tier'])}")
        print(f"  problem shape: {shape_svc.SHAPE_LABELS[r['problem_shape']]}, lever: {r['critical_depth_lever']}, depth match: {r['depth_match']}")
        print(f"  matched skills: {', '.join(r['matched_skills']) or '-'}; primary gap: {r['primary_gap'] or '-'}")
        print("  (all model_inference; override with `shape-set`)")
    finally:
        conn.close()


def cmd_set_tier(args):
    conn = db.get_connection()
    try:
        r = roles_svc.set_role_tier(conn, args.role_id, args.tier, args.note)
        print(f"No role with id {args.role_id}" if not r else
              f"Role {r['role_id']}: {r['label']} (tier {r['role_tier']}, was {r['was']}); recorded as your decision")
    finally:
        conn.close()


def cmd_next_action(args):
    conn = db.get_connection()
    try:
        try:
            app = apps_svc.set_next_action(conn, args.role_id, args.text, args.date)
        except ValueError:
            print("Error: --date must look like 2026-11-20")
            raise SystemExit(1)
        if app is None:
            print(f"No role with id {args.role_id}")
        elif not args.text:
            print(f"Role {args.role_id}: next action cleared")
        else:
            due = f" (due {app['next_action_date']})" if app["next_action_date"] else ""
            print(f"Role {args.role_id}: next action set{due}: {app['next_action']}")
    finally:
        conn.close()


def cmd_add_note(args):
    conn = db.get_connection()
    try:
        text = args.text or sys.stdin.read()
        result = notes_svc.add_note(conn, text)
        if result["linked_entity_type"]:
            print(
                f"Note saved (id={result['note_id']}), linked to "
                f"{result['linked_entity_type']} {result['linked_entity_id']} "
                f"(confidence: {result['linked_confidence']})."
            )
        else:
            print(f"Note saved (id={result['note_id']}), unlinked - no confident match found.")
    finally:
        conn.close()


def cmd_answer_add(args):
    from pathlib import Path
    conn = db.get_connection()
    try:
        if args.answer_file:
            answer = Path(args.answer_file).read_text(encoding="utf-8")
        else:
            answer = args.answer or sys.stdin.read()
        result = answers_svc.save_answer(conn, args.role, args.question, answer, source_file=args.answer_file)
        print(f"Answer {result['action']} (id={result['id']}) for role {args.role}.")
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    finally:
        conn.close()


def cmd_answers(args):
    conn = db.get_connection()
    try:
        rows = answers_svc.list_answers(conn, args.role)
        if not rows:
            print("No saved application answers.")
            return
        for r in rows:
            print(f"[role {r['role_id']}] {r['company']} - {r['role']}\n  Q: {r['question']}\n  ({len(r['answer'].split())} words"
                  f"{', ' + r['source_file'] if r['source_file'] else ''}, updated {r['updated_at']})")
            if args.full:
                print("  " + r["answer"].replace("\n", "\n  "))
            print()
    finally:
        conn.close()


def cmd_update(args):
    conn = db.get_connection()
    try:
        text = args.text or sys.stdin.read()
        result = update_svc.apply_update(conn, text)
        print(f"Interpreted as: {result['kind']}")
        for k, v in result.items():
            if k != "kind" and v not in (None, [], ""):
                print(f"  {k}: {v}")
    finally:
        conn.close()


def cmd_pipeline(args):
    conn = db.get_connection()
    try:
        rows = pipeline_svc.get_pipeline(conn, status=args.status)
        if not rows:
            print("Pipeline is empty.")
            return
        print(f"{'ID':<4} {'Priority':<16} {'Company':<22} {'Title':<40} {'Archetype':<10} {'Shape':<6} {'Depth':<8} {'Status':<18} {'Found via':<20} {'Applied via':<12}")
        print("-" * 160)
        for r in rows:
            print(
                f"{r['role_id']:<4} {roles_svc.tier_label(r['role_tier']):<16} "
                f"{(r['company'] or '')[:22]:<22} {((r['title'] or '') + (' [' + r['job_code'] + ']' if r['job_code'] else ''))[:40]:<40} "
                f"{(r['archetype'] or '-'):<10} {SHAPE_SHORT.get(r['problem_shape'], '-'):<6} "
                f"{(r['depth_match'] or '-'):<8} {(r['application_status'] or 'planned'):<18} "
                f"{(r['found_via'] or '-')[:20]:<20} {(r['applied_via'] or '-'):<12}"
            )
    finally:
        conn.close()


def cmd_role(args):
    conn = db.get_connection()
    try:
        d = dossier_svc.get_role_dossier(conn, args.role_id)
        if not d:
            print(f"No role with id {args.role_id}")
            return
        role = d["role"]
        print(f"=== Role {role['id']}: {role['company_name']} - {role['title']} ===")
        print(f"Location: {role.get('location') or '-'}  |  Priority: {roles_svc.tier_label(role.get('role_tier'))}  |  Archetype: {role.get('archetype') or '-'} ({role.get('fit_confidence') or '-'})")
        if role.get("fit_reason"):
            print(f"Fit reason: {role['fit_reason']}")
        app = d["application"]
        print(f"Application status: {app['status'] if app else 'planned'}")
        if app and app.get("next_action"):
            print(f"Next action: {app['next_action']} (by {app.get('next_action_date') or 'unset'})")
        print(f"\nRequirements ({len(d['requirements'])}):")
        for req in d["requirements"]:
            mark = "OK" if req["has_evidence"] else "GAP"
            print(f"  [{mark}] {req['name']} ({req['requirement_level']})")
        _print_shape(d["problem_shape"])
        if d["gaps"]:
            print(f"\nGaps (no linked evidence): {', '.join(d['gaps'])}")
        if d["interviews"]:
            print(f"\nInterviews ({len(d['interviews'])}):")
            for iv in d["interviews"]:
                print(f"  - {iv.get('stage') or 'unspecified'} on {iv.get('date') or '?'}: outcome={iv.get('outcome') or 'pending'}")
                for s in iv["signals"]:
                    print(f"      signal: {s['dimension']} = {s['signal']}")
        if d["interactions"]:
            print(f"\nInteractions ({len(d['interactions'])}):")
            for i in d["interactions"]:
                print(f"  - {i.get('contact_name') or 'unknown contact'}: {i['summary'][:80]}")
    finally:
        conn.close()


def _print_shape(w):
    if not w:
        return
    b, c = w["breadth_fit"], w["career_compounding"]
    print("\nProblem Shape (model_inference from JD; depth match from Career Evidence):")
    print(f"  Problem Shape:        {w['problem_shape_label']}")
    print(f"  Rate of Change:       {b['rate_of_change'] or 'unknown'}")
    print(f"  Interconnectedness:   {b['interconnectedness'] or 'unknown'}")
    print(f"  Critical Depth Lever: {w['critical_depth_lever'] or 'unknown'} (importance: {w['depth_lever_importance'] or 'unknown'})")
    print(f"  Judgment Requirement: {b['judgment_requirement'] or 'unknown'}")
    print(f"  Depth Match:          {w['depth_match'] or 'unknown'} - {w['depth_match_reason'] or ''}")
    if w["gaps"]:
        print(f"  Missing Evidence:     {w['gaps']}")
    print(f"  Judgment Surface Expansion: {c['judgment_surface_expansion'] or 'unknown'}")
    print(f"  Specialist Spike Deepening: {c['specialist_spike_deepening'] or 'unknown'}")
    print(f"  Interpretation: {w['interpretation']}")
    print(f"  Recommendation: {w['recommendation']}")
    for item in w["learning"]:
        print(f"  Learning [{item['kind']}]: {item['skill']} - {item['note']}")


def cmd_analyze_shape(args):
    conn = db.get_connection()
    try:
        if args.role:
            results = [shape_svc.analyze_role(conn, args.role)]
        else:
            results = shape_svc.analyze_all(conn, only_missing=not args.all)
        done = [r for r in results if r]
        for r in done:
            print(f"role {r['role_id']}: {shape_svc.SHAPE_LABELS[r['problem_shape']]} | lever={r['critical_depth_lever']} | depth={r['depth_match']}")
        print(f"Analyzed {len(done)} role(s). All values are model_inference; confirm with `shape-set`.")
    finally:
        conn.close()


def cmd_why(args):
    conn = db.get_connection()
    try:
        w = shape_svc.why_pursue(conn, args.role_id)
        if not w:
            print(f"No role with id {args.role_id}")
            return
        r = w["role"]
        print(f"=== Why pursue role {r['id']}: {r['company_name']} - {r['title']} ===")
        _print_shape(w)
        if w["supporting_evidence"]:
            print("  Supporting evidence: " + "; ".join(f"{e['company']}: {e['project']}" for e in w["supporting_evidence"]))
        print(f"  ({w['provenance']})")
    finally:
        conn.close()


def cmd_shape_set(args):
    conn = db.get_connection()
    try:
        shape_svc.confirm_field(conn, args.role_id, args.field, args.value)
        print(f"Role {args.role_id}: {args.field} = {args.value} (user_confirmed)")
    finally:
        conn.close()


def cmd_story_frame(args):
    conn = db.get_connection()
    try:
        f = prep_svc.story_frame(conn, args.evidence_id)
        if not f:
            print(f"No evidence with id {args.evidence_id}")
            return
        print(f"=== SYSTEM -> LEVER -> MECHANISM -> DECISION -> OUTCOME: {f['company']} / {f['project']} ===")
        for slot in prep_svc.SLOTS:
            print(f"\n{slot.upper()}")
            for k, v in f["frame"][slot].items():
                print(f"  {k}: {v}")
            if slot in f["missing"]:
                print(f"  [missing] {', '.join(f['missing'][slot])}")
        print(f"\nLever status: {f['lever_status']}")
        print(f"Next: {f['next_step']}")
    finally:
        conn.close()


def cmd_diagnose(args):
    text = args.text or sys.stdin.read()
    d = prep_svc.diagnose_answer(text)
    print("Slots: " + ", ".join(f"{s}={'yes' if v else 'NO'}" for s, v in d["slots_present"].items()))
    if d["team_language_warning"]:
        print("Warning: heavy 'we' language; make your personal decision explicit.")
    print(f"Diagnosis: {d['diagnosis'] or 'All five slots present.'}")
    for i, step in enumerate(d["repair"], 1):
        print(f"  {i}. {step}")
    print(d["note"])


def _fmt_ref(r):
    where = r.get("company_name") or "(no company yet)"
    role = f" / {r['role_title']}" if r.get("role_title") else (f" / ~{r['role_hint']}" if r.get("role_hint") else "")
    extra = f"  follow-up {r['follow_up_date']}" if r.get("follow_up_date") else ""
    why = f"  [{r['follow_up_reason']}]" if r.get("follow_up_reason") else ""
    return f"  [{r['priority']:<6}] {r['contact_name']:<18} {r['status']:<10} {where}{role}{extra}{why}"


def cmd_referrals(args):
    conn = db.get_connection()
    try:
        if args.gaps:
            g = referrals_svc.roles_without_referral_path(conn, tier=args.role_tier)
            print(f"Active {roles_svc.tier_label(args.role_tier).lower()} roles with NO referral path ({len(g['no_path'])}):")
            for r in g["no_path"]:
                print(f"  role {r['id']}: {r['company']} - {r['title']} [{r['application_status']}]")
            print(f"Company-level referral only, no role-specific one ({len(g['company_level_only'])}):")
            for r in g["company_level_only"]:
                print(f"  role {r['id']}: {r['company']} - {r['title']} [{r['application_status']}]")
            return
        view = "unused" if args.unused else "waiting" if args.waiting else "followup" if args.followup else "active" if args.active else "all"
        rows = referrals_svc.list_referrals(conn, view, company=args.company, tier=args.tier)
        label = {"unused": "Unused referral offers", "waiting": "Waiting on", "followup": "Need follow-up",
                 "active": "Active referrals", "all": "All referrals"}[view]
        print(f"{label}" + (f" at {args.company}" if args.company else "") + (f" (Tier {args.tier} companies)" if args.tier else "") + f": {len(rows)}")
        for r in rows:
            print(_fmt_ref(r))
    finally:
        conn.close()


def cmd_learn_add(args):
    conn = db.get_connection()
    try:
        text = args.text or sys.stdin.read()
        r = learning_svc.add_resource(conn, text, title=args.title, category=args.category,
                                      topics=[t.strip() for t in args.topics.split(",")] if args.topics else None,
                                      minutes=args.minutes)
        print(("Already stored" if r["duplicate"] else "Added") + f" resource {r['resource_id']}: {r['title']}")
        print(f"  provider={r['provider']}  category={r['category']}  format={r['format']}  minutes={r['estimated_minutes']}  depth={r['depth']}")
        print(f"  topics: {', '.join(r['topics']) or '-'}   (inferred: {', '.join(r['inferred']) or 'nothing'}; fix with flags)")
    finally:
        conn.close()


def cmd_learn(args):
    conn = db.get_connection()
    try:
        p = learning_svc.learning_plan(conn, args.role, minutes=args.minutes)
        r = p["role"]
        print(f"=== What to study for role {r['id']}: {r['company_name']} - {r['title']} "
              f"(budget {p['budget_minutes']} min{', interview in progress' if p['urgent'] else ''}) ===\n")
        print("HIGHEST PRIORITY")
        if not p["highest_priority"]:
            print("  (nothing: no demanded gap has a stored resource within budget)")
        for it in p["highest_priority"]:
            res = it["resource"]
            mins = f"{res['estimated_minutes']} min" if res.get("estimated_minutes") else "time unknown"
            print(f"  {learning_svc.CATEGORIES[it['category']].split(' (')[0]}: {res['title']} - {mins}")
            print(f"    Why: {it['why']} [{it['topic']}; {it['kind']}]")
            if res.get("note"):
                print(f"    Do: {res['note']}")
            if it.get("also_covers"):
                print(f"    Also covers: {', '.join(it['also_covers'])}")
        if p["gaps_without_resource"]:
            print("\nGAPS WITH NO STORED RESOURCE (do not hunt for content yet)")
            for g in p["gaps_without_resource"]:
                print(f"  {g['category']}: {g['topic']} - {g['note']}")
        if p["later"]:
            print("\nLATER (over budget or same category)")
            for it in p["later"]:
                print(f"  {it['topic']}: {it['resource']}" + (f"  ({it['note']})" if it.get("note") else ""))
        print("\nSKIP FOR NOW")
        for c in p["skip_categories"]:
            print(f"  {learning_svc.CATEGORIES[c['category']].split(' (')[0]}: {c['why']}")
        for t in p["skip_for_now"]:
            print(f"  {t['topic']}: {t['why']}")
        print(f"\n{p['budget_note']}")
    finally:
        conn.close()


def cmd_resources(args):
    conn = db.get_connection()
    try:
        for r in learning_svc.list_resources(conn, args.category):
            mins = f"{r['estimated_minutes']}m" if r["estimated_minutes"] else "?m"
            print(f"{r['id']:<4} {r['category'] or '-':<19} {r['provider'] or '-':<12} {mins:<6} {r['usefulness']:<10} {r['title']}")
    finally:
        conn.close()


def cmd_resource_rate(args):
    conn = db.get_connection()
    try:
        learning_svc.set_usefulness(conn, args.resource_id, args.usefulness)
        print(f"Resource {args.resource_id}: usefulness = {args.usefulness}")
    finally:
        conn.close()


def cmd_sources(args):
    conn = db.get_connection()
    try:
        if args.stats:
            print("By discovery source (conclusions need 10+ roles per source):")
            for s in sources_svc.source_stats(conn):
                sug = f"  -> suggest {s['suggestion']}" if s["suggestion"] else ("" if s["enough_data"] else "  (insufficient data)")
                print(f"  {s['source']:<22} roles={s['roles']:<3} high-fit={s['high_fit']:<3} pursued={s['pursued']:<3} "
                      f"responses={s['responses']:<3} interviews={s['interviews']:<3} priority={s['priority'] or '-'}{sug}")
            print("By application channel:")
            for c in sources_svc.channel_stats(conn):
                print(f"  {c['channel']:<18} applications={c['applications']:<3} responses={c['responses']:<3} interviews={c['interviews']:<3}"
                      + ("" if c["enough_data"] else "  (insufficient data)"))
            return
        for s in sources_svc.list_sources(conn):
            flag = "" if s["active"] else "  [inactive]"
            basis = f" ({s['priority_basis']})" if s["priority_basis"] else ""
            print(f"{s['name']:<22} {s['source_type']:<16} {s['priority'] or '-':<7}{basis}{flag}")
    finally:
        conn.close()


def cmd_source_add(args):
    conn = db.get_connection()
    try:
        r = sources_svc.add_source(conn, args.name, args.type, url=args.url, notes=args.notes)
        print(("Added" if r["created"] else "Updated") + f" job source: {r['name']}")
    finally:
        conn.close()


def cmd_source_set(args):
    conn = db.get_connection()
    try:
        r = sources_svc.set_priority(conn, args.name, args.priority, active=None if args.active is None else args.active == "yes")
        print(f"{r['name']}: priority={args.priority or 'unchanged'}")
    finally:
        conn.close()


def cmd_brief(args):
    conn = db.get_connection()
    try:
        rows = brief_svc.brief(conn, top=args.top)
        for i, r in enumerate(rows, 1):
            print(f"{i}. role {r['id']}: {r['company']} - {r['title']}  [{roles_svc.tier_label(r['role_tier'])}, {r['application_status']}]")
            paths = "; ".join(f"{p['contact']} ({p['status']}, {p['level']}-level, {p['priority']})" for p in r["referral_paths"]) or "none"
            print(f"   Referral path:    {paths}")
            print(f"   Found via:        {r['discovery_source'] or 'not recorded'}   Applied via: {r['application_channel'] or 'not yet / not recorded'}")
            print(f"   Learning gaps:    {', '.join(r['learning_gaps']) or 'none flagged'}")
            print(f"   Use resources:    {'; '.join(r['resources']) or 'none stored for these gaps'}")
            print(f"   Next:             {r['next_action']}\n")
    finally:
        conn.close()


def cmd_review(args):
    conn = db.get_connection()
    try:
        r = review_svc.generate_review(conn, period_days=args.days)
        print(f"=== Career Review (last {r['period_days']} days) ===\n")
        print(f"PIPELINE ({len(r['pipeline_moved'])} roles touched):")
        for row in r["pipeline_moved"][:10]:
            print(f"  - {row['company']} / {row['title']} -> {row['status'] or 'planned'}")
        print(f"\nCONVERSION ({len(r['conversion_signals'])} interview signals):")
        for s in r["conversion_signals"][:10]:
            print(f"  - {s['company']} / {s['title']}: {s['dimension']} = {s['signal']}")
        print(f"\nPROOF ({len(r['proof_added'])} evidence rows added):")
        for e in r["proof_added"][:10]:
            print(f"  - {e['company']}: {e['project']}")
        print(f"\nSTOP: {len(r['stop'])} stalled role(s)")
        for row in r["stop"][:5]:
            print(f"  - {row['company']} / {row['title']} (role {row['role_id']})")
        print(f"\nCONTINUE: archetype with most active pipeline activity = {r['continue_archetype'] or 'n/a'}")
        print(f"START: most common unresolved requirement gap = {r['start_gap'] or 'n/a'}")
        print(f"DOUBLE DOWN: strongest-evidence skill = {r['double_down_skill'] or 'n/a'}")
        sig = r.get("generalist_specialist_signal")
        if sig:
            print("\nGENERALIST-SPECIALIST SIGNAL:")
            for shape, d in sig["by_shape"].items():
                print(f"  {shape_svc.SHAPE_LABELS[shape]}: {d['roles']} role(s), {d['advanced']} past application")
            for n in sig["notes"]:
                print(f"  - {n}")
        rs = r.get("referral_signal")
        if rs:
            print(f"\nREFERRALS: {rs['with_referral_path']} of {rs['tier1_roles']} top-priority roles have a referral path; "
                  f"{rs['submitted']} submitted; {rs['unused_offers']} unused offer(s)")
            if rs["follow_ups_due"]:
                print("  follow up: " + ", ".join(rs["follow_ups_due"]))
        for s in r.get("source_signal") or []:
            print(f"\nSOURCES: {s['source']} has {s['roles']} roles, {int((s['high_fit_rate'] or 0) * 100)}% high-fit: consider priority {s['suggestion']}")
        ls = r.get("learning_signal")
        if ls:
            print(f"\nLEARNING: '{ls['recurring_gap']}' interview gap recurred {ls['count']}x; prioritize "
                  f"{', '.join(ls['categories'])} resources and pause generic coursework")
        print("\n--- Next actions ---")
        print(f"PIPELINE:   {r['next_actions']['pipeline']}")
        print(f"CONVERSION: {r['next_actions']['conversion']}")
        print(f"PROOF:      {r['next_actions']['proof']}")
    finally:
        conn.close()


def cmd_export_data(args):
    conn = db.get_connection()
    try:
        payload = export_svc.export_all(conn)
        text = json.dumps(payload, indent=2)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"Wrote {args.out}")
        else:
            print(text)
    finally:
        conn.close()


def cmd_metrics(args):
    conn = db.get_connection()
    try:
        m = metrics_svc.compute_metrics(conn)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(m, indent=2))
        return
    q = m["quota"]
    print(f"Job-search metrics as of {m['as_of']}")
    print(f"  This week ({q['week_start']} to {q['week_end']}): {q['count']} of {q['target']} applications; "
          f"{q['remaining']} to go, {q['days_left']} days left")
    for k, v in m["kpis"].items():
        val = "n/a" if v["value"] is None else f"{v['value']}{v.get('unit', '')}"
        extra = f" ({v['numerator']} of {v['denominator']})" if "numerator" in v else ""
        print(f"  {v['label']}: {val}{extra}")
    print("  Weekly applications: " + ", ".join(f"{w['week_start'][5:]}={w['count']}" for w in m["weekly"]))
    print("  Funnel: " + " > ".join(f"{f['label']} {f['count']}" for f in m["funnel"]))
    print("  Status: " + ", ".join(f"{s['status']} {s['count']}" for s in m["status"]))
    print("  Channels: " + ", ".join(f"{c['channel']} {c['total']} (heard back {c['heard_back']})" for c in m["channels"]))
    print("  Data quality: " + "; ".join(f"{d['issue']}: {d['count']}" for d in m["data_quality"]))
    print("  (open the Dashboard tab in `python cli.py serve` for charts and drill-down)")


def cmd_actions(args):
    conn = db.get_connection()
    try:
        a = actions_svc.compute_actions(conn)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(a, indent=2))
        return
    print(f"Action Center as of {a['as_of']} (week {a['week_start']} to {a['week_end']})")
    for s in a["strip"]:
        print(f"  {s['label']}: {s['value']} ({s['detail']})")
    print("  Do now:")
    for i in a["do_now"]["items"]:
        print(f"    [{i['tag']}] {i['company']} - {i['title']}: {i['why']}")
    print("  Interviews and scheduling:")
    for i in a["interviews"]["items"]:
        print(f"    {i['date'] or 'date pending'} {i['company']} - {i['title']}: {i['why']} ({i['outcome']})")
    print(f"  Waiting on others: {a['waiting']['count']}")
    print("  What not to do:")
    for i in a["avoid"]:
        print(f"    - {i['rule']}")
    print("  (open the Action Center tab in `python cli.py serve` for links)")


def cmd_serve(args):
    server_path = Path(__file__).resolve().parent / "server.py"
    sys.path.insert(0, str(server_path.parent))
    import server as server_mod  # noqa: PLC0415 - deliberate lazy import, keeps `serve` out of every other command's import cost

    server_mod.serve(args.port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="career", description="Career OS CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create the database if it doesn't exist")
    p_init.set_defaults(func=cmd_init)

    p_seed = sub.add_parser("seed", help="Load an example company portfolio + fictional example evidence rows")
    p_seed.set_defaults(func=cmd_seed)

    p_demo = sub.add_parser("seed-demo", help="Add fictional demo roles to an EMPTY database (try the UI without your own data)")
    p_demo.set_defaults(func=cmd_seed_demo)

    p_add_job = sub.add_parser("add-job", help="Add a role from a JD (text, file, or metadata)")
    p_add_job.add_argument("--company", required=True)
    p_add_job.add_argument("--title")
    p_add_job.add_argument("--jd-text")
    p_add_job.add_argument("--jd-file")
    p_add_job.add_argument("--url")
    p_add_job.add_argument("--location")
    p_add_job.add_argument("--source", help="Discovery source (where you found it), e.g. LinkedIn")
    p_add_job.add_argument("--job-code", help="Employer job/req ID; lets one company have several roles with the same title")
    p_add_job.add_argument("--applied-via", help="Application channel, e.g. referral (kept separate from --source)")
    p_add_job.set_defaults(func=cmd_add_job)

    p_jd = sub.add_parser("attach-jd", help="Attach/replace the JD on an existing role and re-derive tier, archetype, shape")
    p_jd.add_argument("role_id", type=int)
    p_jd.add_argument("--jd-file")
    p_jd.add_argument("--jd-text", help="omit both to read stdin")
    p_jd.set_defaults(func=cmd_attach_jd)

    p_tier = sub.add_parser("set-tier", help="Set a role's priority: 1 top, 2 medium, 3 low (your decision)")
    p_tier.add_argument("role_id", type=int)
    p_tier.add_argument("tier", type=int, choices=[1, 2, 3])
    p_tier.add_argument("--note")
    p_tier.set_defaults(func=cmd_set_tier)

    p_next = sub.add_parser("next-action", help="Set a role's next action and optional due date (feeds the Action Center); empty text clears it")
    p_next.add_argument("role_id", type=int)
    p_next.add_argument("text", nargs="?", default="")
    p_next.add_argument("--date", help="due date, YYYY-MM-DD")
    p_next.set_defaults(func=cmd_next_action)

    p_note = sub.add_parser("add-note", help="Add a free-form note")
    p_note.add_argument("text", nargs="?", help="Note text (omit to read from stdin)")
    p_note.set_defaults(func=cmd_add_note)

    p_aa = sub.add_parser("answer-add", help="Save an application question and your answer for a role (re-saving the same question updates it)")
    p_aa.add_argument("--role", type=int, required=True, help="Role id")
    p_aa.add_argument("--question", required=True, help='e.g. "Why Anthropic?" or "Cover letter"')
    p_aa.add_argument("--answer", help="Answer text (or use --answer-file, or pipe on stdin)")
    p_aa.add_argument("--answer-file", help="Path to a file holding the answer")
    p_aa.set_defaults(func=cmd_answer_add)

    p_ans = sub.add_parser("answers", help="List saved application questions and answers")
    p_ans.add_argument("--role", type=int, help="Only this role id")
    p_ans.add_argument("--full", action="store_true", help="Print the full answer text")
    p_ans.set_defaults(func=cmd_answers)

    p_update = sub.add_parser("update", help="Apply a free-text update")
    p_update.add_argument("text", nargs="?", help="Update text (omit to read from stdin)")
    p_update.set_defaults(func=cmd_update)

    p_pipeline = sub.add_parser("pipeline", help="Show the pipeline")
    p_pipeline.add_argument("--status", help="Filter by application status")
    p_pipeline.set_defaults(func=cmd_pipeline)

    p_role = sub.add_parser("role", help="Show a role dossier")
    p_role.add_argument("role_id", type=int)
    p_role.set_defaults(func=cmd_role)

    p_review = sub.add_parser("review", help="Generate the executive career review")
    p_review.add_argument("--days", type=int, default=7)
    p_review.set_defaults(func=cmd_review)

    p_an = sub.add_parser("analyze-shape", help="Classify problem shape (backfill or re-run)")
    p_an.add_argument("--role", type=int)
    p_an.add_argument("--all", action="store_true", help="Re-analyze roles that already have a shape")
    p_an.set_defaults(func=cmd_analyze_shape)

    p_why = sub.add_parser("why", help="Why pursue this role: breadth, lever, evidence, gaps, compounding")
    p_why.add_argument("role_id", type=int)
    p_why.set_defaults(func=cmd_why)

    p_set = sub.add_parser("shape-set", help="Confirm/override a problem-shape field (records user_confirmed)")
    p_set.add_argument("role_id", type=int)
    p_set.add_argument("field")
    p_set.add_argument("value")
    p_set.set_defaults(func=cmd_shape_set)

    p_sf = sub.add_parser("story-frame", help="Map an evidence row to SYSTEM->LEVER->MECHANISM->DECISION->OUTCOME")
    p_sf.add_argument("evidence_id", type=int)
    p_sf.set_defaults(func=cmd_story_frame)

    p_dg = sub.add_parser("diagnose", help="Check an interview answer for breadth-without-depth")
    p_dg.add_argument("text", nargs="?", help="Answer text (omit to read stdin)")
    p_dg.set_defaults(func=cmd_diagnose)

    p_ref = sub.add_parser("referrals", help="Query referral offers/requests (add them with `update`)")
    for flag in ("unused", "waiting", "followup", "active", "gaps"):
        p_ref.add_argument(f"--{flag}", action="store_true")
    p_ref.add_argument("--company")
    p_ref.add_argument("--tier", help="Company tier (A/B/C/Watchlist)")
    p_ref.add_argument("--role-tier", type=int, default=1, help="With --gaps: role tier to check (default 1)")
    p_ref.set_defaults(func=cmd_referrals)

    p_la = sub.add_parser("learn-add", help="Add a learning resource from a URL/sentence (fields are inferred)")
    p_la.add_argument("text", nargs="?")
    p_la.add_argument("--title")
    p_la.add_argument("--category", choices=sorted(learning_svc.CATEGORIES))
    p_la.add_argument("--topics", help="comma-separated override")
    p_la.add_argument("--minutes", type=int)
    p_la.set_defaults(func=cmd_learn_add)

    p_learn = sub.add_parser("learn", help="What to study for a role: smallest useful set within a time budget")
    p_learn.add_argument("--role", type=int, required=True)
    p_learn.add_argument("--minutes", type=int, default=learning_svc.DEFAULT_BUDGET_MINUTES)
    p_learn.set_defaults(func=cmd_learn)

    p_res = sub.add_parser("resources", help="List stored learning resources")
    p_res.add_argument("--category", choices=sorted(learning_svc.CATEGORIES))
    p_res.set_defaults(func=cmd_resources)

    p_rr = sub.add_parser("resource-rate", help="Mark a resource useful/neutral/not_useful")
    p_rr.add_argument("resource_id", type=int)
    p_rr.add_argument("usefulness", choices=list(learning_svc.USEFULNESS))
    p_rr.set_defaults(func=cmd_resource_rate)

    p_src = sub.add_parser("sources", help="List job sources (--stats for performance by source and channel)")
    p_src.add_argument("--stats", action="store_true")
    p_src.set_defaults(func=cmd_sources)

    p_sa = sub.add_parser("source-add", help="Add a job source")
    p_sa.add_argument("name")
    p_sa.add_argument("--type", default="other", choices=sorted(sources_svc.SOURCE_TYPES))
    p_sa.add_argument("--url")
    p_sa.add_argument("--notes")
    p_sa.set_defaults(func=cmd_source_add)

    p_ss = sub.add_parser("source-set", help="Set a source's priority and/or active flag")
    p_ss.add_argument("name")
    p_ss.add_argument("--priority", choices=["High", "Medium", "Low"])
    p_ss.add_argument("--active", choices=["yes", "no"])
    p_ss.set_defaults(func=cmd_source_set)

    p_brief = sub.add_parser("brief", help="Top priority roles: referral path, source, learning gaps, resources, next action")
    p_brief.add_argument("--top", type=int, default=5)
    p_brief.set_defaults(func=cmd_brief)

    p_export = sub.add_parser("export-data", help="Export every entity table as JSON")
    p_export.add_argument("--out", help="Write to this file instead of stdout")
    p_export.set_defaults(func=cmd_export_data)

    p_metrics = sub.add_parser("metrics", help="Job-search metrics (same numbers as the Dashboard tab)")
    p_metrics.add_argument("--json", action="store_true", help="Full metrics payload as JSON")
    p_metrics.set_defaults(func=cmd_metrics)

    p_actions = sub.add_parser("actions", help="Action Center: this week's actions and what not to do")
    p_actions.add_argument("--json", action="store_true", help="Full payload as JSON")
    p_actions.set_defaults(func=cmd_actions)

    p_serve = sub.add_parser("serve", help="Run the local Data Browser (127.0.0.1 only)")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
