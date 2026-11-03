"""Heuristic (non-LLM) classification.

Deliberately NOT an LLM call: keeps Career OS runnable offline, free, and
model-agnostic from day one (spec section 24/32). Every result here is a
`model_inference` with source='heuristic' - it is a starting guess, not a
verified fact. A human or an LLM session can later overwrite it with a
`user_confirmed` claim via the same service functions.

This module intentionally has no dependency on any LLM provider. A future
LLMProvider abstraction (AnthropicProvider / OpenAIProvider / LocalProvider)
can call the same service-layer functions and write a stronger
`model_inference` on top of this one - this module is the default,
always-available fallback, not the final word.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Archetype keyword buckets (spec section 3)
# ---------------------------------------------------------------------------
ARCHETYPE_KEYWORDS = {
    "A": [  # AI/ML technical program leadership
        "technical program manager", "tpm", "program management",
        "ai platform", "model development", "model deployment",
        "ai infrastructure", "infrastructure", "release management",
        "branching strategy", "deployment", "reliability", "latency",
        "scalability", "production readiness", "engineering program manager",
        "epm", "cross-functional engineering", "applied ai program",
    ],
    "B": [  # AI product leadership: search, discovery, intelligence
        "product manager", "search", "discovery", "retrieval", "ranking",
        "relevance", "recommendation", "personalization", "conversational ai",
        "experimentation", "a/b testing", "ndcg", "genai experience",
        "product owner", "roadmap", "user stories", "acceptance criteria",
    ],
    "C": [  # AI Quality / Evaluation / Deployment Leader
        "evaluation", "eval framework", "golden dataset", "hitl",
        "human-in-the-loop", "annotation", "quality bar", "launch gate",
        "regression", "model readiness", "ai quality", "production decision",
        "threshold", "segmentation", "benchmark",
    ],
}

# ---------------------------------------------------------------------------
# Seed skill vocabulary used for requirement extraction (section 14).
# Kept small and tuned to AI/ML program and product roles + common JD asks seen in
# practice; extend via the `skills` table over time, no code change needed
# for new skills once seeded.
# ---------------------------------------------------------------------------
SEED_SKILLS = [
    "AI/ML Product Roadmaps", "Generative AI", "RAG", "LLM", "Agentic AI",
    "Prompt Engineering", "Search Ranking", "Relevance", "Retrieval",
    "Recommendation Systems", "Personalization", "NDCG", "A/B Testing",
    "ML Evaluation", "Golden Dataset", "HITL", "Annotation",
    "Voice AI", "Conversational AI", "Internationalization",
    "Release Management", "Branching Strategy", "Risk Mitigation",
    "Program Scheduling", "Executive Reporting", "Cross-functional Leadership",
    "Stakeholder Management", "User Stories", "Acceptance Criteria",
    "Backlog Grooming", "Agile", "Scrum", "Go-to-Market", "Pricing Strategy",
    "AWS", "Cloud Infrastructure", "Distributed Systems", "Python", "SQL",
    "Power BI", "Tableau", "Snowflake", "CRM",
    "Vendor Management", "QA", "Data Quality", "Latency", "Scalability",
    "Production Readiness",
]


def classify_archetype(text: str) -> tuple[str | None, str, dict]:
    """Return (archetype, confidence, scores). archetype in {'A','B','C',None}."""
    lowered = text.lower()
    scores = {}
    for archetype, keywords in ARCHETYPE_KEYWORDS.items():
        scores[archetype] = sum(lowered.count(kw) for kw in keywords)

    best = max(scores, key=lambda k: scores[k])
    best_score = scores[best]
    total = sum(scores.values())

    if best_score == 0:
        return None, "Low", scores

    # Confidence: how dominant is the top bucket relative to the rest?
    runner_up = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0
    if best_score >= 5 and best_score > runner_up * 1.5:
        confidence = "High"
    elif best_score >= 2:
        confidence = "Medium"
    else:
        confidence = "Low"

    return best, confidence, scores


def extract_skills(text: str, vocabulary: list[str] | None = None) -> list[str]:
    """Simple case-insensitive substring match against a skill vocabulary.

    Returns the subset of `vocabulary` whose name appears in `text`.
    No fabrication, no fuzzy guessing beyond plain substring containment.
    """
    vocab = vocabulary or SEED_SKILLS
    lowered = text.lower()
    found = []
    for skill in vocab:
        if skill.lower() in lowered:
            found.append(skill)
    return found


def guess_title(text: str) -> str | None:
    """Best-effort title guess from the first few non-empty lines of a JD.

    Looks for a line containing a common title keyword. Returns None rather
    than guessing wrong if nothing matches - callers must treat this as a
    suggestion, not a verified fact.
    """
    title_keywords = [
        "product manager", "program manager", "technical program manager",
        "engineering program manager", "tpm", "epm", "product owner",
    ]
    for line in text.splitlines()[:15]:
        stripped = line.strip().strip("#*- ").strip()
        if not stripped or len(stripped) > 120:
            continue
        lowered = stripped.lower()
        if any(kw in lowered for kw in title_keywords):
            return stripped
    return None


def canonical_key(company: str, title: str, job_code: str | None = None) -> str:
    """Normalize company+title (+ job code when known) for duplicate detection (section 17).

    Same company and title with different job codes are different roles.
    """
    def norm(s: str) -> str:
        s = s.lower().strip()
        s = re.sub(r"[^a-z0-9]+", " ", s)
        return re.sub(r"\s+", " ", s).strip()
    key = f"{norm(company)}::{norm(title)}"
    return f"{key}::{norm(job_code)}" if job_code else key


@dataclass
class RoleClassification:
    archetype: str | None
    archetype_confidence: str
    archetype_scores: dict
    matched_skills: list[str] = field(default_factory=list)
    guessed_title: str | None = None


def classify_role(text: str) -> RoleClassification:
    archetype, confidence, scores = classify_archetype(text)
    return RoleClassification(
        archetype=archetype,
        archetype_confidence=confidence,
        archetype_scores=scores,
        matched_skills=extract_skills(text),
        guessed_title=guess_title(text),
    )


# ---------------------------------------------------------------------------
# Problem-shape inference (see STRATEGY.md). Qualitative, rule-based, and
# deliberately conservative: low signal => 'unknown', never a guess. Results
# are model_inference about the JD, not facts about the role.
# ---------------------------------------------------------------------------
CHANGE_HIGH = [
    "generative ai", "genai", "llm", "agent", "agentic", "frontier", "foundation model",
    "large language model", "generative", "deep learning", "groundbreaking", "aggressive timeline",
    "rapidly", "fast-paced", "fast paced", "emerging", "evolving", "ambigu",
    "0 to 1", "0-to-1", "zero to one", "new models", "state of the art", "research",
    "startup", "scale-up", "reinvent",
]
CHANGE_LOW = ["mature", "legacy", "sustaining", "maintenance", "steady state", "steady-state", "run the business"]

FUNCTIONS = [
    "engineering", "product", "research", "infrastructure", "data science", "security",
    "privacy", "legal", "compliance", "customer", "operations", "finance", "partner",
    "go-to-market", "sales", "marketing", "design", "policy", "safety", "cross-functional",
    "stakeholder", "executive", "vendor",
]

# lever name -> (keywords, spike code or None, skill names used for evidence overlap when no spike)
LEVERS: dict[str, tuple[list[str], str | None, list[str]]] = {
    "Search relevance / retrieval quality": (
        ["search", "retrieval", "ranking", "relevance", "recommendation", "personalization",
         "ndcg", "rag", "reranking", "embedding", "discovery"], "search", []),
    "Evaluation methodology / quality gating": (
        ["evaluation", "evals", "eval ", "golden dataset", "hitl", "human-in-the-loop", "annotation",
         "quality bar", "launch gate", "regression", "benchmark", "model quality", "red team"], "eval", []),
    "Production reliability / deployment readiness": (
        ["reliability", "deployment", "production readiness", "release", "ci/cd", "observability",
         "slo", "incident", "launch readiness", "uptime", "orchestration", "mlops"], "platform", []),
    "Capacity economics / infrastructure cost": (
        ["capacity", "infrastructure cost", "unit economics", "cogs", "gpu capacity", "compute cost",
         "cloud cost", "region launch", "pricing", "gpu fleet", "fleet efficiency", "fleet", "gpu",
         "multi-node", "distributed computing", "inference and training"],
        "platform", ["Pricing Strategy", "Cloud Infrastructure"]),
    "Pricing / conversion / growth": (
        ["pricing", "conversion", "monetization", "growth", "funnel", "revenue"], None,
        ["Pricing Strategy", "Go-to-Market"]),
    "Safety / privacy / policy": (
        ["safety", "privacy", "policy", "trust and safety", "responsible ai", "compliance"], None,
        ["Internationalization"]),
    "Low-level performance (kernels / silicon / serving efficiency)": (
        ["cuda", "kernel", "compiler", "silicon", "rtl", "verilog", "tensorrt", "triton",
         "inference optimization", "model serving efficiency", "distributed training", "gpu architecture",
         "hbm", "dram"], None, []),
}
DEEP_SPECIALIST_LEVER = "Low-level performance (kernels / silicon / serving efficiency)"

JUDGMENT_HIGH = [
    "ambiguity", "ambiguous", "tradeoff", "trade-off", "strategy", "prioritiz", "roadmap",
    "0 to 1", "0-to-1", "define", "vision", "influence", "decision", "judgment", "framing",
]
JUDGMENT_SENIOR_TITLE = ["principal", "staff", "director", "head of", "vp", "senior director", "lead"]
COORDINATION_ONLY = [
    "status report", "status update", "dependency tracking", "track dependencies", "pmo",
    "schedule", "meeting cadence", "reporting", "coordinate", "project plan", "raid log", "milestones",
]


def _hits(lowered: str, words: list[str]) -> int:
    # Match at word starts only (prefix, so "recommendation(s)" and "ambigu-ous/-ity" still hit) so that
    # "search" does not fire inside "research". Text/keywords are lowercase.
    return sum(len(re.findall(r"(?<![a-z0-9])" + re.escape(w), lowered)) for w in words)


def _level(n: int, high: int, medium: int) -> str:
    return "high" if n >= high else "medium" if n >= medium else "low"


def infer_problem_shape(text: str, title: str | None = None) -> dict:
    """Return the problem-shape fields plus a `reasons` dict explaining each.

    Depth *match* is NOT computed here: it needs Career Evidence rows, so it
    lives in services/problem_shape.py. This function only reads the JD.
    """
    lowered = text.lower()
    title_l = (title or "").lower()
    reasons: dict[str, str] = {}

    # Rate of change
    up, down = _hits(lowered, CHANGE_HIGH), _hits(lowered, CHANGE_LOW)
    if up == 0 and down == 0:
        roc = "unknown"
        reasons["rate_of_change"] = "no change-rate language in JD"
    elif down > up:
        roc = "low"
        reasons["rate_of_change"] = f"stability language ({down}) outweighs change language ({up})"
    else:
        # 'low' needs stability language (handled above); a single change signal is weak but not 'low'
        roc = "high" if up >= 4 else "medium"
        reasons["rate_of_change"] = f"{up} change-rate signals (GenAI/LLM/agents/ambiguity/0-to-1 etc.)"

    # Interconnectedness: distinct functions named
    funcs = [f for f in FUNCTIONS if f in lowered]
    if not funcs:
        inter = "unknown"
        reasons["interconnectedness"] = "no cross-functional language in JD"
    else:
        inter = _level(len(funcs), 6, 3)
        reasons["interconnectedness"] = f"{len(funcs)} functions named: {', '.join(funcs[:8])}"

    # Critical depth lever
    lever_hits = {name: _hits(lowered, kws) + 2 * _hits(title_l, kws) for name, (kws, _, _) in LEVERS.items()}
    top_lever, top_n = max(lever_hits.items(), key=lambda kv: kv[1])
    if top_n == 0:
        lever, importance = None, "unknown"
        reasons["critical_depth_lever"] = "no lever vocabulary in JD"
    else:
        lever = top_lever
        importance = _level(top_n, 6, 3)
        reasons["critical_depth_lever"] = f"{top_n} weighted mentions (title counts double)"
        reasons["depth_lever_importance"] = f"lever vocabulary density={top_n}"

    # Judgment requirement
    j_hits = _hits(lowered, JUDGMENT_HIGH)
    senior = any(t in title_l for t in JUDGMENT_SENIOR_TITLE)
    coord = _hits(lowered, COORDINATION_ONLY)
    score = j_hits + (3 if senior else 0)
    if score == 0 and coord == 0:
        judgment = "unknown"
        reasons["judgment_requirement"] = "no framing/tradeoff/seniority signal"
    elif coord >= 3 and coord > j_hits and not senior:
        # TPM JDs routinely mention schedules/reporting; only call it low when coordination clearly dominates
        judgment = "low"
        reasons["judgment_requirement"] = f"coordination language ({coord}) outweighs framing language ({j_hits})"
    else:
        judgment = "high" if score >= 5 else "medium"
        reasons["judgment_requirement"] = f"{j_hits} framing/tradeoff signals" + (" + senior title" if senior else "")

    # Shape (qualitative rules, no formula)
    if lever == DEEP_SPECIALIST_LEVER and importance in ("high", "medium"):
        shape = "specialist"
        reasons["problem_shape"] = "low-level performance lever dominates; depth is the main differentiator"
    elif lever and importance in ("high", "medium") and inter in ("high", "medium") and roc != "low":
        shape = "generalist_specialist"
        reasons["problem_shape"] = f"cross-functional system plus an identifiable lever ({lever})"
    elif inter in ("high", "medium") and importance in ("low", "unknown"):
        shape = "generalist"
        reasons["problem_shape"] = "interconnected scope with no dominant depth lever"
    elif inter == "unknown" and lever is None:
        shape = "unknown"
        reasons["problem_shape"] = "insufficient JD signal"
    else:
        shape = "unknown"
        reasons["problem_shape"] = "signals conflict or are too thin to classify"

    return {
        "problem_shape": shape,
        "rate_of_change": roc,
        "interconnectedness": inter,
        "critical_depth_lever": lever,
        "depth_lever_importance": importance,
        "judgment_requirement": judgment,
        "reasons": reasons,
        "pmo_risk": coord >= 3 and judgment in ("low", "unknown"),
    }
