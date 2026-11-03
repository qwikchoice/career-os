"""TypeSafe's Jev (System One) model as an optional archetype classifier.

Verified against the live docs (docs.typesafe.ai/api.md, /sdk/python.md,
/primitives/choice.md) and a real API call before being wired in here -
not guessed. This module is an *optional upgrade* over heuristics.py, not
a replacement: it requires the `typesafe-sdk` package and a
TYPESAFE_API_KEY. Both are checked by `is_configured()` before any call,
and every caller must be ready to fall back to the heuristic on any
exception (network error, rate limit, missing key, package not installed).

API contract (as documented when written):
  POST https://api.typesafe.ai/v1/systemone
  model: "jev-latest"
  Choice question -> {choice, probabilities, confidence (0-1, computed
  from how concentrated the probability distribution is)}.
"""
from __future__ import annotations

import os

ARCHETYPE_DESCRIPTIONS = {
    "A": (
        "AI/ML Technical Program Leader: architecture, execution, "
        "infrastructure, model lifecycle, evaluation, reliability, deployment, "
        "cross-functional engineering leadership."
    ),
    "B": (
        "AI Product Leader, Search Discovery and Intelligence: "
        "search, retrieval, ranking, recommendations, personalization, "
        "experimentation, relevance metrics, GenAI experiences."
    ),
    "C": (
        "AI Quality / Evaluation / Deployment Leader: eval frameworks, golden "
        "datasets, HITL, thresholds, segmentation, launch gates, regression "
        "detection, quality metrics, production decisions."
    ),
}


def is_configured() -> bool:
    """True if the SDK is installed and an API key is present in env."""
    if not os.environ.get("TYPESAFE_API_KEY"):
        return False
    try:
        import typesafe_sdk  # noqa: F401
    except ImportError:
        return False
    return True


def classify_archetype(text: str) -> dict:
    """Classify JD text into archetype A/B/C via the Jev model.

    Returns {'archetype': str, 'confidence': float, 'probabilities': dict,
    'model': str}. Raises on any failure (import, auth, network, rate
    limit) - callers must catch and fall back to the heuristic; this
    function never silently returns a guess of its own.
    """
    from typesafe_sdk import Choice, TypeSafeClient  # import here: optional dep

    with TypeSafeClient() as client:
        response = client.system_one(
            state={"job_description": text},
            questions={
                "archetype": Choice(
                    instructions="Which career archetype best fits this job description?",
                    criteria=ARCHETYPE_DESCRIPTIONS,
                ),
            },
        )
    answer = response.choices["archetype"]
    return {
        "archetype": answer.choice,
        "confidence": answer.confidence,
        "probabilities": dict(answer.probabilities),
        "model": "jev-latest",
    }


def confidence_label(confidence: float) -> str:
    """Map Jev's 0-1 confidence float to the system's High/Medium/Low label.

    Thresholds are a documented bucketing choice, not a claim about Jev's
    internal calibration - 0.75/0.4 split chosen to roughly mirror the
    heuristic's own High/Medium/Low bands.
    """
    if confidence >= 0.75:
        return "High"
    if confidence >= 0.4:
        return "Medium"
    return "Low"
