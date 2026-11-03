"""Application questions and answers, stored per role.

A role can have many (e.g. "Why Anthropic?", "Cover letter"). Saving the same question for the
same role again updates the stored answer instead of adding a second row, so the table never
holds two competing versions of one answer.
"""
from __future__ import annotations

import sqlite3
from typing import Optional


def _norm(q: str) -> str:
    return " ".join(q.lower().split()).rstrip("?:. ")


def save_answer(conn: sqlite3.Connection, role_id: int, question: str, answer: str,
                source_file: Optional[str] = None) -> dict:
    if not conn.execute("SELECT 1 FROM roles WHERE id = ?", (role_id,)).fetchone():
        raise ValueError(f"role {role_id} does not exist")
    question, answer = question.strip(), answer.strip()
    if not question or not answer:
        raise ValueError("question and answer are both required")
    for row in conn.execute("SELECT id, question FROM application_answers WHERE role_id = ?", (role_id,)):
        if _norm(row["question"]) == _norm(question):
            conn.execute(
                "UPDATE application_answers SET answer = ?, source_file = COALESCE(?, source_file), "
                "updated_at = datetime('now') WHERE id = ?", (answer, source_file, row["id"]))
            conn.commit()
            return {"id": row["id"], "action": "updated"}
    cur = conn.execute(
        "INSERT INTO application_answers (role_id, question, answer, source_file) VALUES (?, ?, ?, ?)",
        (role_id, question, answer, source_file))
    conn.commit()
    return {"id": cur.lastrowid, "action": "added"}


def list_answers(conn: sqlite3.Connection, role_id: Optional[int] = None) -> list[dict]:
    sql = ("SELECT a.*, c.name AS company, r.title AS role FROM application_answers a "
           "JOIN roles r ON r.id = a.role_id JOIN companies c ON c.id = r.company_id")
    params: tuple = ()
    if role_id is not None:
        sql += " WHERE a.role_id = ?"
        params = (role_id,)
    return [dict(r) for r in conn.execute(sql + " ORDER BY a.role_id, a.id", params)]
