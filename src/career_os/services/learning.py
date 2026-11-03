"""Learning resources and role-driven learning plans.

One generic resource table. The point is retrieval, not collection:
    Demand -> Retrieve -> Learn -> Apply -> Tag
A resource is recommended only when a role (or interview) demands its topic,
Career Evidence does not already cover it, and it fits the time budget.
Nothing is ever invented: a demanded topic with no stored resource is
reported as a gap, not filled with made-up content. Default budget keeps the
20% learning / 80% applying rule.
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Optional
from urllib.parse import urlparse

from career_os.services import claims as claims_svc
from career_os.services import sources as sources_svc

# Add a category by adding a line here (no schema change).
CATEGORIES = {
    "product_management": "Product Management (customer focused)",
    "program_management": "Program Management (process / execution)",
    "engineering": "Engineering (technical, deterministic)",
    "ai": "AI (technical, non-deterministic)",
    "high_stakes": "High-Stakes Skills (low prep time, high impact)",
}
USEFULNESS = ("useful", "neutral", "not_useful", "unknown")
DEFAULT_BUDGET_MINUTES = 90
MAX_ITEMS = 4
UNKNOWN_TIME_ASSUMPTION = 30  # used only for budgeting, never stored

# topic -> (category, keywords). Short keywords are matched on word boundaries.
TOPICS: dict[str, tuple[str, list[str]]] = {
    "product strategy": ("product_management", ["product strategy", "product vision", "go-to-market", "gtm"]),
    "customer discovery": ("product_management", ["customer discovery", "user research", "customer interview", "customer workflow"]),
    "prioritization": ("product_management", ["prioritiz", "roadmap", "backlog"]),
    "product metrics": ("product_management", ["product metrics", "north star", "kpi", "funnel", "retention", "a/b test", "experimentation"]),
    "product sense": ("product_management", ["product sense", "product judgment", "product design"]),
    "platform product": ("product_management", ["product lifecycle", "npi", "end of life", "developer ecosystem", "api product", "platform product", "hardware product", "reference architecture"]),
    "program planning": ("program_management", ["program planning", "project plan", "program management", "milestone"]),
    "dependency management": ("program_management", ["dependency", "dependencies"]),
    "risk management": ("program_management", ["risk management", "risk mitigation", "raid"]),
    "launch readiness": ("program_management", ["launch readiness", "release management", "go-live", "launch"]),
    "cross-functional execution": ("program_management", ["cross-functional", "cross functional", "stakeholder", "operating mechanism"]),
    "system design": ("engineering", ["system design", "architecture", "architectural"]),
    "distributed systems": ("engineering", ["distributed system", "distributed"]),
    "apis": ("engineering", ["api", "apis", "sdk"]),
    "databases": ("engineering", ["database", "sql", "nosql", "data model"]),
    "cloud infrastructure": ("engineering", ["cloud", "aws", "infrastructure", "kubernetes", "gcp", "azure"]),
    "reliability": ("engineering", ["reliability", "sla", "slo", "uptime", "incident", "availability"]),
    "scalability and performance": ("engineering", ["scalab", "latency", "throughput", "performance"]),
    "ci/cd": ("engineering", ["ci/cd", "deployment pipeline", "devops"]),
    "llm fundamentals": ("ai", ["llm", "large language model", "generative ai", "genai", "prompt"]),
    "rag and retrieval": ("ai", ["rag", "retrieval", "embedding", "reranking", "vector"]),
    "agents": ("ai", ["agent", "agentic", "tool use", "mcp"]),
    "search and ranking": ("ai", ["search", "ranking", "relevance", "recommendation", "ndcg"]),
    "evaluation": ("ai", ["evaluation", "evals", "benchmark", "golden dataset", "hitl", "human-in-the-loop", "annotation", "red team"]),
    "inference and serving": ("ai", ["inference", "serving", "model deployment", "gpu"]),
    "model lifecycle": ("ai", ["model lifecycle", "fine-tun", "training pipeline", "mlops", "model development"]),
    "ai failure modes": ("ai", ["hallucination", "failure mode", "guardrail"]),
    "ai product management": ("ai", ["ai product", "ai pm", "responsible ai", "ai governance", "ai roadmap"]),
    "architecture interview": ("high_stakes", ["architecture interview", "system design interview"]),
    "behavioral interview": ("high_stakes", ["behavioral", "star method", "tell me about a time"]),
    "technical storytelling": ("high_stakes", ["technical storytelling", "storytelling"]),
    "coding interview": ("high_stakes", ["coding interview", "live coding", "real-time coding", "leetcode"]),
    "executive communication": ("high_stakes", ["executive communication", "executive presence", "c-suite"]),
    "recruiter and hiring-manager screens": ("high_stakes", ["recruiter screen", "hiring manager screen"]),
    "offer negotiation": ("high_stakes", ["negotiat", "salary"]),
}
SPIKE_OF_TOPIC = {
    "search and ranking": "search", "rag and retrieval": "search", "evaluation": "eval",
    "reliability": "platform", "scalability and performance": "platform", "cloud infrastructure": "platform",
    "ci/cd": "platform", "launch readiness": "platform", "inference and serving": "platform",
}
# interview-signal dimension -> topics worth repairing
DIMENSION_TOPICS = {
    "system_design": ["system design", "architecture interview"],
    "metrics": ["evaluation", "product metrics"],
    "technical_ownership": ["technical storytelling"],
    "coding": ["coding interview"],
    "product_judgment": ["product sense"],
    "leadership": ["cross-functional execution"],
    "communication": ["executive communication"],
}
PRACTICE = {
    "architecture interview": "Walk one flagship story as SYSTEM -> LEVER -> MECHANISM -> DECISION -> OUTCOME out loud (use `career story-frame`).",
    "technical storytelling": "Rehearse one story as Metric -> Threshold -> Segmentation -> Decision -> Outcome, then check it with `career diagnose`.",
    "behavioral interview": "Prepare 3 stories with a personal decision stated explicitly (not 'we'); check with `career diagnose`.",
    "coding interview": "One timed practice problem; talk through tradeoffs aloud.",
    "executive communication": "Draft a 5-sentence executive summary of one program; cut it to 3.",
    "recruiter and hiring-manager screens": "Rehearse the 90-second positioning statement (see STRATEGY.md positioning).",
    "offer negotiation": "Write down range, priorities and walk-away before the offer call.",
}

_PROVIDERS = [  # (needle, provider, default category or None)
    ("educative", "Educative", None), ("tryexponent", "Exponent", "high_stakes"), ("exponent", "Exponent", "high_stakes"),
    ("coursera", "Coursera", None), ("udemy", "Udemy", None), ("youtube", "YouTube", None), ("youtu.be", "YouTube", None),
    ("github", "GitHub", None), ("deeplearning.ai", "DeepLearning.AI", "ai"), ("medium.com", "Medium", None),
    ("arxiv", "arXiv", "ai"), ("hellointerview", "Hello Interview", "high_stakes"), ("interviewing.io", "interviewing.io", "high_stakes"),
    ("leetcode", "LeetCode", "high_stakes"), ("bytebytego", "ByteByteGo", "engineering"), ("oreilly", "O'Reilly", None),
    ("chatgpt", "ChatGPT", None), ("chat.openai", "ChatGPT", None), ("claude.ai", "Claude", None), ("claude artifact", "Claude", None),
    ("anthropic.com", "Anthropic docs", "ai"), ("docs.", "Official docs", None), ("documentation", "Official docs", None),
]
_FORMATS = [  # (regex, format)
    (r"\bplaylist\b", "playlist"), (r"\b(video|youtube|youtu\.be)\b", "video"), (r"\bcourse\b", "course"),
    (r"\bbook\b", "book"), (r"\bchapter\b", "chapter"), (r"\b(article|blog|post)\b", "article"),
    (r"\b(repo|repository|github)\b", "repo"), (r"\b(docs|documentation)\b", "documentation"),
    (r"\b(practice|mock|problems)\b", "practice"), (r"\bquestions?\b", "question set"), (r"\bpdf\b", "pdf"),
    (r"\bnotes\b", "notes"), (r"\bartifact\b", "claude artifact"), (r"\bconversation\b|\bchat\b", "chat"),
    (r"\bproject\b|\bcode\b", "code project"),
]
_INTERVIEW_WORDS = re.compile(r"\b(interview|mock|behavioral|negotiat|whiteboard)", re.I)
_JOB_WORDS = re.compile(r"\b(job|role|recruiter|applied|referral|referred|rejected|hiring)\b", re.I)


# --------------------------------------------------------------------------
# Inference
# --------------------------------------------------------------------------
def _kw_hit(low: str, kw: str) -> int:
    if len(kw) <= 4:
        return len(re.findall(rf"\b{re.escape(kw)}\b", low))
    return low.count(kw)


def _topic_hits(text: str) -> dict[str, int]:
    low = text.lower().replace("-", " ")
    hits = {}
    for topic, (_, kws) in TOPICS.items():
        n = sum(_kw_hit(low, k.replace("-", " ")) for k in kws)
        if n:
            hits[topic] = n
    return hits


def infer_resource(text: str, *, title: Optional[str] = None, url_or_path: Optional[str] = None,
                   category: Optional[str] = None, topics: Optional[list[str]] = None,
                   minutes: Optional[int] = None) -> dict:
    """Infer what is reasonably inferable; leave the rest None. Returns fields + `inferred` list."""
    inferred: list[str] = []
    um = re.search(r"https?://\S+", text)
    link = url_or_path or (um.group(0).rstrip(".,)") if um else None)
    if not link:
        pm = re.search(r"(?:[A-Za-z]:[\\/]|/|~/|\.{1,2}/)[^\s\"']+\.[A-Za-z0-9]{2,5}", text)
        if pm and os.path.exists(os.path.expanduser(pm.group(0))):
            link = pm.group(0)
    body = re.sub(r"https?://\S+", " ", text).strip()
    low_all = (text + " " + (link or "")).lower()

    provider, prov_cat = None, None
    host = urlparse(link).netloc.lower() if link and link.startswith("http") else ""
    for needle, name, cat in _PROVIDERS:
        if needle in host or needle in low_all:
            provider, prov_cat = name, cat
            break
    if not provider and host:
        provider = host.removeprefix("www.").split(".")[0].capitalize()
    if provider:
        inferred.append("provider")

    fmt = None
    for rx, name in _FORMATS:
        if re.search(rx, low_all):
            fmt = name
            break
    if not fmt and link:
        fmt = "video" if "youtu" in host else "repo" if "github" in host else "pdf" if link.lower().endswith(".pdf") else None
    if fmt:
        inferred.append("format")

    hits = _topic_hits(body or low_all)
    chosen_topics = topics or [t for t, _ in sorted(hits.items(), key=lambda kv: -kv[1])[:6]]
    if not topics and chosen_topics:
        inferred.append("topics")

    cat = category
    if not cat:
        if prov_cat == "high_stakes" or _INTERVIEW_WORDS.search(body):
            cat = "high_stakes"
        elif chosen_topics:
            tally: dict[str, int] = {}
            for t in chosen_topics:
                tally[TOPICS[t][0]] = tally.get(TOPICS[t][0], 0) + hits.get(t, 1)
            cat = max(tally, key=tally.get)
        elif prov_cat:
            cat = prov_cat
        if cat:
            inferred.append("category")
    if cat and cat not in CATEGORIES:
        raise ValueError(f"category must be one of {sorted(CATEGORIES)}")

    mins = minutes
    if mins is None:
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|min)\b", body, re.I)
        if m:
            mins = round(float(m.group(1)) * (60 if m.group(2).lower().startswith("h") else 1))
            inferred.append("estimated_minutes")

    depth = None
    if re.search(r"\b(intro|beginner|basics?|101|overview)\b", body, re.I):
        depth = "intro"
    elif re.search(r"\b(advanced|deep dive|in-depth|expert)\b", body, re.I):
        depth = "deep"
    elif re.search(r"\bintermediate\b", body, re.I):
        depth = "working"
    if depth:
        inferred.append("depth")

    ttl = title
    if not ttl:
        parts = [p for p in (provider, chosen_topics[0] if chosen_topics else None, fmt) if p]
        ttl = " ".join(parts) if parts else (link or body[:60] or "Untitled resource")
        inferred.append("title")
    return {"title": ttl, "url_or_path": link, "provider": provider, "category": cat,
            "topics": chosen_topics, "format": fmt, "estimated_minutes": mins, "depth": depth,
            "notes": body or None, "inferred": inferred}


def add_resource(conn: sqlite3.Connection, text: str, *, source: str = "user", **overrides) -> dict:
    """Capture a resource from a URL/sentence. Preserves the raw text; infers the rest (as model_inference)."""
    info = infer_resource(text, **{k: v for k, v in overrides.items() if v is not None})
    if info["url_or_path"]:
        dup = conn.execute("SELECT id FROM learning_resources WHERE url_or_path = ?", (info["url_or_path"],)).fetchone()
        if dup:
            return {"resource_id": dup["id"], "duplicate": True, **info}
    src = sources_svc.create_raw_source(conn, "note", content=text)
    cur = conn.execute(
        """INSERT INTO learning_resources (title, url_or_path, provider, category, topics, format,
               estimated_minutes, depth, notes, source, raw_source_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (info["title"], info["url_or_path"], info["provider"], info["category"], ", ".join(info["topics"]) or None,
         info["format"], info["estimated_minutes"], info["depth"], info["notes"], source, src["id"]),
    )
    conn.commit()
    rid = cur.lastrowid
    if info["inferred"]:
        claims_svc.record_claim(
            conn, f"inferred fields {info['inferred']} for resource '{info['title']}' (heuristic)",
            "learning_resource", rid, "model_inference", raw_source_id=src["id"],
            verification_status="unverified", confidence="Low")
    return {"resource_id": rid, "duplicate": False, **info}


def set_usefulness(conn: sqlite3.Connection, resource_id: int, usefulness: str) -> None:
    if usefulness not in USEFULNESS:
        raise ValueError(f"usefulness must be one of {USEFULNESS}")
    conn.execute("UPDATE learning_resources SET usefulness = ?, updated_at = datetime('now') WHERE id = ?",
                 (usefulness, resource_id))
    conn.commit()


def list_resources(conn: sqlite3.Connection, category: Optional[str] = None) -> list[dict]:
    q, p = "SELECT * FROM learning_resources", ()
    if category:
        q, p = q + " WHERE category = ?", (category,)
    return [dict(r) for r in conn.execute(q + " ORDER BY category, title", p)]


def match_learning_update(text: str) -> bool:
    """Conservative: only claim text that clearly adds/endorses a learning resource."""
    if _JOB_WORDS.search(text):
        return False
    low = text.lower()
    has_url = "http" in low
    provider = any(n in low for n, _, _ in _PROVIDERS if len(n) > 4 and n not in ("docs.", "documentation"))
    fmt = bool(re.search(r"\b(course|video|playlist|book|chapter|article|tutorial|repo|repository|pdf|notes|guide)\b", low))
    if re.search(r"\b(learning|study)\s+(sources?|resources?|materials?|list)\b", low):
        return True
    if re.match(r"\s*add\b", low) and (provider or fmt or has_url):
        return True
    return bool((provider or has_url) and fmt and re.search(r"\b(useful|good|great|helpful|recommend|worth)\b", low))


# --------------------------------------------------------------------------
# Role-driven plan
# --------------------------------------------------------------------------
def _evidence_coverage(conn: sqlite3.Connection, topic: str) -> str:
    from career_os.services.problem_shape import _known

    kws = [k.replace("-", " ") for k in TOPICS[topic][1]]
    proven = hits = 0
    for e in conn.execute("SELECT * FROM evidence"):
        blob = " ".join(str(e[f] or "") for f in ("problem", "technical_context", "architecture", "ownership",
                                                     "decisions", "technologies", "project")).lower().replace("-", " ")
        if any(_kw_hit(blob, k) for k in kws):
            hits += 1
            proven += _known(e["metrics"]) and _known(e["ownership"])
    return "strong" if proven >= 2 else "some" if hits else "none"


def _interview_state(conn: sqlite3.Connection, role_id: int) -> dict:
    app = conn.execute("SELECT status FROM applications WHERE role_id = ?", (role_id,)).fetchone()
    in_loop = bool(app) and app["status"] in ("recruiter_screen", "hiring_manager", "interview_loop", "final_round")
    open_iv = conn.execute("SELECT 1 FROM interviews WHERE role_id = ? AND outcome IS NULL", (role_id,)).fetchone()
    gaps: dict[str, str] = {}
    for s in conn.execute(
            "SELECT dimension, signal FROM interview_signals WHERE signal IN ('Weak','Mixed')"):
        for t in DIMENSION_TOPICS.get(s["dimension"], []):
            gaps[t] = f"{s['signal']} interview signal on {s['dimension']}"
    return {"urgent": in_loop or bool(open_iv), "gaps": gaps}


def role_demand(conn: sqlite3.Connection, role_id: int) -> dict:
    from career_os.services import problem_shape as shape_svc
    from career_os.services import roles as roles_svc
    from career_os.services import skills as skills_svc

    role = roles_svc.get_role(conn, role_id)
    if not role:
        raise ValueError(f"no role {role_id}")
    if role.get("problem_shape") is None:
        shape_svc.analyze_role(conn, role_id)
        role = roles_svc.get_role(conn, role_id)
    text = " ".join([role["title"], shape_svc.role_text(conn, role) or "",
                     " ".join(r["name"] for r in skills_svc.role_requirements(conn, role_id))])
    hits = _topic_hits(text)
    state = _interview_state(conn, role_id)
    demand = {t: {"hits": n, "reason": f"mentioned {n}x in the JD/requirements"} for t, n in hits.items()}
    if any(t in demand for t in ("system design", "distributed systems", "apis")):
        demand.setdefault("architecture interview", {"hits": 1, "reason": "technical role: architecture round is a likely gate"})
    if role.get("problem_shape") == "generalist_specialist" or role.get("judgment_requirement") == "high":
        demand.setdefault("technical storytelling", {"hits": 1, "reason": "judgment-heavy role: depth stories decide the loop"})
    if state["urgent"]:
        demand.setdefault("behavioral interview", {"hits": 1, "reason": "interview in progress"})
    for t, why in state["gaps"].items():
        demand.setdefault(t, {"hits": 0, "reason": why})["interview_gap"] = why
    return {"role": role, "demand": demand, "urgent": state["urgent"]}


# a high-stakes topic can also be served by a resource tagged with these topics
_RELATED_TOPICS = {"architecture interview": ["system design", "distributed systems"]}


def _pick_resource(conn, topic: str, want_depth: Optional[str], category: str) -> Optional[dict]:
    topics = [topic] + _RELATED_TOPICS.get(topic, [])
    clause = " OR ".join("topics LIKE ?" for _ in topics)
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM learning_resources WHERE usefulness != 'not_useful' AND ({clause})",  # noqa: S608 - fixed fragments
        tuple(f"%{t}%" for t in topics))]
    if not rows:
        return None
    use_rank = {"useful": 0, "unknown": 1, "neutral": 2}
    rows.sort(key=lambda r: (r["category"] != category,
                             use_rank.get(r["usefulness"], 1),
                             0 if want_depth and r["depth"] == want_depth else 1,
                             r["estimated_minutes"] is None, r["estimated_minutes"] or 0))
    return rows[0]


def learning_plan(conn: sqlite3.Connection, role_id: int, minutes: int = DEFAULT_BUDGET_MINUTES) -> dict:
    """Smallest useful set of stored resources/practice for one role, within a time budget."""
    from career_os.services import problem_shape as shape_svc

    d = role_demand(conn, role_id)
    role, urgent = d["role"], d["urgent"]
    lever_spike = shape_svc._lever_spike(role.get("critical_depth_lever"))
    lever_important = role.get("depth_lever_importance") == "high"

    ranked, skipped = [], []
    for topic, info in d["demand"].items():
        cat = TOPICS[topic][0]
        cov = "n/a" if cat == "high_stakes" else _evidence_coverage(conn, topic)
        gap = info.get("interview_gap")
        spike = SPIKE_OF_TOPIC.get(topic)
        depth_kind = "specialist_depth" if spike and spike == lever_spike and lever_important else "generalist_literacy"
        if cov == "strong" and not gap:
            skipped.append({"topic": topic, "category": cat, "why": "existing Career Evidence already strong"})
            continue
        if gap or info["hits"] >= 3 or (cat == "high_stakes" and urgent) or depth_kind == "specialist_depth":
            prio = "high"
        elif info["hits"] >= 1 or cat == "high_stakes":
            prio = "medium"
        else:
            prio = "low"
        why = [info["reason"]]
        if cov == "some":
            why.append("only partial evidence")
        if depth_kind == "specialist_depth":
            why.append(f"strengthens the '{spike}' spike this role turns on")
        ranked.append({"topic": topic, "category": cat, "priority": prio, "kind": depth_kind, "why": "; ".join(why),
                       "urgent": urgent and cat == "high_stakes"})
    order = {"high": 0, "medium": 1, "low": 2}
    ranked.sort(key=lambda x: (not x["urgent"], order[x["priority"]], x["category"]))

    chosen, gaps_no_resource, later, used, cats_used = [], [], [], 0, set()
    for item in ranked:
        if item["priority"] == "low":
            skipped.append({"topic": item["topic"], "category": item["category"], "why": "weak demand; revisit if it recurs"})
            continue
        res = _pick_resource(conn, item["topic"], "deep" if item["kind"] == "specialist_depth" else "intro", item["category"])
        if res is None:
            if item["category"] == "high_stakes" and item["topic"] in PRACTICE:
                res = {"id": None, "title": f"Practice: {item['topic']}", "estimated_minutes": 30,
                       "provider": None, "format": "practice", "note": PRACTICE[item["topic"]]}
            else:
                if item["priority"] == "high":
                    gaps_no_resource.append({"topic": item["topic"], "category": item["category"],
                                             "note": "no stored resource; add one only if the gap persists after practicing"})
                continue
        same = next((c for c in chosen if res.get("id") and c["resource"].get("id") == res["id"]), None)
        if same:  # one resource already covers this topic: do not recommend it twice
            same.setdefault("also_covers", []).append(item["topic"])
            continue
        cost = res["estimated_minutes"] or UNKNOWN_TIME_ASSUMPTION
        if item["category"] in cats_used or len(chosen) >= MAX_ITEMS or used + cost > minutes:
            later.append({**item, "resource": res["title"],
                          "note": (f"needs ~{cost} min, over the {minutes}-min budget: do one section now" if used + cost > minutes else None)})
            continue
        chosen.append({**item, "resource": res})
        cats_used.add(item["category"])
        used += cost

    covered_cats = {c["category"] for c in chosen} | {g["category"] for g in gaps_no_resource}
    skip_cats = []
    for cat in CATEGORIES:
        if cat in covered_cats:
            continue
        topics = [s for s in skipped if s["category"] == cat]
        pending_later = [x for x in later if x["category"] == cat]
        if pending_later:
            continue  # has a recommendation, just over budget: reported under LATER, not skipped
        skip_cats.append({"category": cat, "why": topics[0]["why"] if topics else "no meaningful gap for this role"})

    pending = conn.execute(
        "SELECT COUNT(*) AS n FROM roles r LEFT JOIN applications a ON a.role_id = r.id "
        "WHERE r.role_tier = 1 AND COALESCE(a.status,'planned') = 'planned' AND r.id != ?", (role_id,)).fetchone()["n"]
    return {
        "role": role, "urgent": urgent, "budget_minutes": minutes, "planned_minutes": used,
        "highest_priority": chosen, "gaps_without_resource": gaps_no_resource,
        "later": later, "skip_for_now": skipped, "skip_categories": skip_cats,
        "budget_note": ("Default split is 20% learning / 80% applying and practicing."
                        + (f" {pending} other Tier 1 role(s) are still unapplied; apply first if the gap is not blocking." if pending else "")),
    }
