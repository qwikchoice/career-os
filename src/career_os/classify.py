"""Classification orchestration: Jev (if configured) with a hard fallback
to the dependency-free heuristic in heuristics.py.

This is the one place that decides *which* classifier ran. Everything
downstream (roles.add_job, claims) just reads RoleClassification and
records whatever `provider` says - it never assumes which path produced
the result.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from career_os import heuristics
from career_os.providers import jev

logger = logging.getLogger(__name__)


@dataclass
class RoleClassification:
    archetype: str | None
    archetype_confidence: str          # High/Medium/Low — always qualitative
    archetype_scores: dict
    provider: str                      # 'jev' or 'heuristic'
    matched_skills: list[str] = field(default_factory=list)
    guessed_title: str | None = None
    raw_confidence: float | None = None  # Jev's actual 0-1 float, if that path ran


def classify_role(text: str, use_jev: bool = True) -> RoleClassification:
    matched_skills = heuristics.extract_skills(text)
    guessed_title = heuristics.guess_title(text)

    if use_jev and jev.is_configured():
        try:
            result = jev.classify_archetype(text)
            return RoleClassification(
                archetype=result["archetype"],
                archetype_confidence=jev.confidence_label(result["confidence"]),
                archetype_scores=result["probabilities"],
                provider="jev",
                matched_skills=matched_skills,
                guessed_title=guessed_title,
                raw_confidence=result["confidence"],
            )
        except Exception as exc:  # noqa: BLE001 - any failure, fall back, never crash add-job
            logger.warning("jev classification failed (%s); falling back to heuristic", exc)

    archetype, confidence, scores = heuristics.classify_archetype(text)
    return RoleClassification(
        archetype=archetype,
        archetype_confidence=confidence,
        archetype_scores=scores,
        provider="heuristic",
        matched_skills=matched_skills,
        guessed_title=guessed_title,
    )
