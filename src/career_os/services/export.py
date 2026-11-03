"""Export every browsable entity table as plain JSON-serializable data.

Used by the local Data Browser server (server.py) and available standalone
via `career-os/cli.py export-data` for ad hoc inspection or a cheap backup
snapshot. Join tables (role_skills, evidence_skills, story_evidence) and
schema_meta are intentionally excluded - they're relationships/internals,
not independently browsable entities. Their info is nested into the
parent row instead (e.g. a role's matched skill names).
"""
from __future__ import annotations

import sqlite3

from career_os.services import metrics as metrics_svc
from career_os.services import pipeline as pipeline_svc
from career_os.services import roles as roles_svc

TABLE_GROUPS = {
    "Overview": ["action_center", "dashboard", "application_status"],
    "Pipeline": ["companies", "roles", "applications", "application_answers", "referrals", "job_sources"],
    "People": ["contacts", "interactions", "interviews", "interview_signals"],
    "Evidence": ["evidence", "stories", "skills", "learning_resources"],
    "System": ["claims", "duplicates", "notes_inbox", "raw_sources"],
}

ALL_TABLES = [t for group in TABLE_GROUPS.values() for t in group]


# Active first, finished last. Anything unknown sorts between (never silently dropped).
STATUS_ORDER = ["offer", "final_round", "interview_loop", "hiring_manager", "recruiter_screen", "applied",
                "referred", "referral_requested", "planned", "rejected", "withdrawn", "closed"]


def _application_status(conn: sqlite3.Connection) -> list[dict]:
    """One readable row per role: company, role, current status, how it was found/applied, referrer.
    Derived from the pipeline join; nothing is stored. `id` (the role id) is last, for `career role <id>`.
    """
    rows = []
    facts = metrics_svc.role_facts(conn)   # derived, nothing stored: the dashboard and this table share one source
    for r in pipeline_svc.get_pipeline(conn):
        f = facts[r["role_id"]]
        rows.append({
            "company": r["company"], "role": r["title"], "job_code": r["job_code"], "priority": roles_svc.tier_label(r["role_tier"]),
            "status": r["application_status"] or "planned",
            "stage": f["stage"], "date_applied": f["date_applied"], "channel_group": f["channel_group"],
            "lane": f["lane"], "interviews": f["interviews"], "last_activity": f["last_activity"],
            "applied_via": r["applied_via"], "found_via": None if r["found_via"] == "manual" else r["found_via"],
            "referrer": r["referrer"],
            "next_action": r["next_action"], "next_action_date": r["next_action_date"],
            "last_updated": r["updated_at"], "id": r["role_id"],
        })

    def key(row):
        s = row["status"]
        return (STATUS_ORDER.index(s) if s in STATUS_ORDER else 6, raw_tier[row["id"]] or 9, row["company"] or "")

    raw_tier = {r["role_id"]: r["role_tier"] for r in pipeline_svc.get_pipeline(conn)}
    return sorted(rows, key=key)


def _lookups(conn: sqlite3.Connection) -> dict:
    companies = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM companies")}
    roles = {r["id"]: f"{companies.get(r['company_id'], '?')} - {r['title']}"
             for r in conn.execute("SELECT id, company_id, title FROM roles")}
    contacts = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM contacts")}
    evidence = {r["id"]: f"{r['company']}: {r['project']}" for r in conn.execute("SELECT id, company, project FROM evidence")}
    return {"company": companies, "role": roles, "contact": contacts, "evidence": evidence}


# raw foreign-key column -> (display column added next to the id, lookup name)
_FK_DISPLAY = {
    "company_id": ("company", "company"),
    "role_id": ("role", "role"),
    "contact_id": ("contact", "contact"),
    "referral_contact_id": ("referrer", "contact"),
    "interviewer_contact_id": ("interviewer", "contact"),
}


def _with_names(rows: list[dict], lk: dict) -> list[dict]:
    """Add readable name columns for every foreign key. Raw *_id keys are kept (other clients may use them)."""
    out = []
    for row in rows:
        named = {}
        for col, (label, lookup) in _FK_DISPLAY.items():
            if col in row and label not in row:
                named[label] = lk[lookup].get(row[col]) if row[col] is not None else None
        # polymorphic references (claims, notes, duplicates): resolve by the row's own type column
        for type_col, id_col, label in (("subject_type", "subject_id", "subject"),
                                        ("linked_entity_type", "linked_entity_id", "linked_to"),
                                        ("entity_type", "entity_id_a", "entity_a"),
                                        ("entity_type", "entity_id_b", "entity_b")):
            if type_col in row and id_col in row and row[id_col] is not None:
                named[label] = lk.get(row[type_col], {}).get(row[id_col])
        if not named:
            out.append(row)
            continue
        merged = {"id": row["id"]} if "id" in row else {}
        merged.update(named)
        merged.update({k: v for k, v in row.items() if k not in merged})
        out.append(merged)
    return out


def _rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    cur = conn.execute(f"SELECT * FROM {table} ORDER BY rowid")  # noqa: S608 - table name is from our own fixed allowlist, never user input
    return [dict(r) for r in cur.fetchall()]


def _roles_with_skills(conn: sqlite3.Connection) -> list[dict]:
    rows = _rows(conn, "roles")
    for row in rows:
        skill_rows = conn.execute(
            """SELECT s.name FROM role_skills rs JOIN skills s ON s.id = rs.skill_id
               WHERE rs.role_id = ? ORDER BY s.name""",
            (row["id"],),
        ).fetchall()
        row["matched_skills"] = [r["name"] for r in skill_rows]
        row["priority"] = roles_svc.tier_label(row.get("role_tier"))
    return rows


def _evidence_with_skills(conn: sqlite3.Connection) -> list[dict]:
    rows = _rows(conn, "evidence")
    for row in rows:
        skill_rows = conn.execute(
            """SELECT s.name FROM evidence_skills es JOIN skills s ON s.id = es.skill_id
               WHERE es.evidence_id = ? ORDER BY s.name""",
            (row["id"],),
        ).fetchall()
        row["linked_skills"] = [r["name"] for r in skill_rows]
    return rows


def _stories_with_evidence(conn: sqlite3.Connection) -> list[dict]:
    rows = _rows(conn, "stories")
    for row in rows:
        ev_rows = conn.execute(
            "SELECT evidence_id FROM story_evidence WHERE story_id = ?", (row["id"],)
        ).fetchall()
        row["evidence_ids"] = [r["evidence_id"] for r in ev_rows]
    return rows


def export_all(conn: sqlite3.Connection) -> dict:
    """Return {table_name: [rows...]} for every browsable entity table,
    plus a `_groups` key describing how to organize them in a UI.
    """
    data: dict = {"_groups": TABLE_GROUPS}
    lk = _lookups(conn)
    for table in ALL_TABLES:
        if table in ("dashboard", "action_center"):
            data[table] = []   # a computed view (GET /api/metrics), not a table
            continue
        if table == "application_status":
            data[table] = _application_status(conn)
            continue
        if table == "roles":
            data[table] = _roles_with_skills(conn)
        elif table == "evidence":
            data[table] = _evidence_with_skills(conn)
        elif table == "stories":
            data[table] = _stories_with_evidence(conn)
        elif table == "companies":
            data[table] = _rows(conn, table)
            for row in data[table]:
                row["target_level"] = roles_svc.COMPANY_TIER_LABELS.get(row.get("tier"), "Not rated")
        else:
            data[table] = _rows(conn, table)
            if table == "interactions":
                for row in data[table]:
                    row["activity_type"] = metrics_svc.activity_type(row.get("summary"))
        data[table] = _with_names(data[table], lk)
    return data
