"""Interview prep: SYSTEM -> LEVER -> MECHANISM -> DECISION -> OUTCOME.

story_frame maps an evidence row onto the five slots and lists what is missing
(never filled with invented detail). diagnose_answer is a rule-based check for
the common failure: broad system explanation + thin depth + unclear personal
decision. Neither calls an LLM.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

SLOTS = ["system", "lever", "mechanism", "decision", "outcome"]

# slot -> evidence columns that feed it (reusing existing fields, no duplication)
SLOT_FIELDS = {
    "system": ["problem", "technical_context", "architecture", "stakeholders"],
    "lever": ["critical_lever"],
    "mechanism": ["metrics", "thresholds", "segmentation", "tradeoffs", "failure_modes", "technologies"],
    "decision": ["ownership", "decisions", "alternatives"],
    "outcome": ["business_impact", "technical_impact", "leadership_impact", "lessons"],
}


def _known(v: Optional[str]) -> bool:
    return bool(v) and v.strip().lower() not in ("unknown", "") and "needs_evidence" not in v.lower()


def story_frame(conn: sqlite3.Connection, evidence_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
    if not row:
        return None
    frame, missing = {}, {}
    for slot, fields in SLOT_FIELDS.items():
        frame[slot] = {f: row[f] for f in fields if _known(row[f])}
        lacking = [f for f in fields if not _known(row[f])]
        if lacking:
            missing[slot] = lacking
    lever_status = "hypothesis (not verified)" if _known(row["critical_lever"]) else "unknown"
    weakest = [s for s in ("lever", "mechanism", "decision") if not frame[s]]
    if weakest:
        next_step = ("Add the missing " + ", ".join(weakest)
                     + " details to this evidence row before using it as a flagship story.")
    elif missing.get("mechanism"):
        next_step = "Rehearse all five slots; thresholds/segmentation gaps may still draw follow-ups."
    else:
        next_step = "Story is complete across all five slots."
    return {
        "evidence_id": evidence_id, "company": row["company"], "project": row["project"],
        "frame": frame, "missing": missing, "lever_status": lever_status,
        "ready_for_depth_questions": not weakest, "next_step": next_step,
    }


_SYSTEM_WORDS = ["stakeholder", "cross-functional", "teams", "engineering", "product", "infrastructure",
                 "architecture", "partners", "markets", "customers", "organization", "ecosystem"]
_MECHANISM_WORDS = ["ndcg", "precision", "recall", "latency", "p95", "p99", "threshold", "segment", "baseline",
                    "regression", "a/b", "experiment", "golden", "annotation", "failure mode", "gate",
                    "cutoff", "index", "ranking", "embedding", "metric", "error rate", "false positive"]
_LEVER_WORDS = ["the key", "the constraint", "bottleneck", "what mattered", "the lever", "determined",
                "the real problem", "the deciding", "hinged on", "came down to"]
_DECISION_RE = re.compile(
    r"\bI (?:decided|chose|choose|rejected|prioriti[sz]ed|escalated|set|defined|killed|cut|pushed back|"
    r"made the call|owned the decision|insisted|blocked|approved)\b", re.I)
_OUTCOME_RE = re.compile(
    r"\d+\s?%|\$\s?\d|\b\d+\s?(?:x|ms|countries|markets|releases|million|mm|k)\b|\bresult(?:ed)?\b|\boutcome\b", re.I)

REPAIR = [
    "Identify the critical leverage point (what actually determined success).",
    "Go one layer deeper technically (how it worked, what failed).",
    "State the metric, threshold, and segmentation.",
    "State your personal decision (what you decided/changed/rejected, not 'we').",
    "State the outcome (technical, customer, business) and the lesson.",
]


def diagnose_answer(answer: str) -> dict:
    low = answer.lower()
    present = {
        "system": sum(low.count(w) for w in _SYSTEM_WORDS) >= 2,
        "lever": any(w in low for w in _LEVER_WORDS),
        "mechanism": sum(low.count(w) for w in _MECHANISM_WORDS) >= 2,
        "decision": bool(_DECISION_RE.search(answer)),
        "outcome": bool(_OUTCOME_RE.search(answer)),
    }
    we_count = len(re.findall(r"\bwe\b", low))
    i_count = len(re.findall(r"\bI\b", answer))
    missing = [s for s in SLOTS if not present[s]]
    breadth_only = present["system"] and (not present["mechanism"] or not present["decision"])
    diagnosis = None
    if breadth_only:
        diagnosis = "Breadth demonstrated; specialist credibility insufficiently visible."
    elif missing:
        diagnosis = f"Missing slot(s): {', '.join(missing)}."
    return {
        "slots_present": present, "missing": missing,
        "team_language_warning": we_count > max(1, 2 * i_count),
        "diagnosis": diagnosis,
        "repair": REPAIR if breadth_only or missing else [],
        "note": "Rule-based keyword check: a flag means 'look here', not a verdict on answer quality.",
    }
