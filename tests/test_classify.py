"""Classifier orchestration tests. No real network calls — jev's module
functions are monkeypatched so these run offline and don't burn API calls
or depend on a key being present in the test environment.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from career_os import classify  # noqa: E402
from career_os.providers import jev  # noqa: E402


class TestClassifyFallback(unittest.TestCase):
    def test_uses_heuristic_when_jev_not_configured(self):
        original = jev.is_configured
        jev.is_configured = lambda: False
        try:
            result = classify.classify_role(
                "search retrieval ranking relevance recommendation personalization " * 3
            )
            self.assertEqual(result.provider, "heuristic")
            self.assertEqual(result.archetype, "B")
            self.assertIsNone(result.raw_confidence)
        finally:
            jev.is_configured = original

    def test_falls_back_to_heuristic_when_jev_call_raises(self):
        original_configured = jev.is_configured
        original_classify = jev.classify_archetype
        jev.is_configured = lambda: True
        jev.classify_archetype = lambda text: (_ for _ in ()).throw(RuntimeError("network down"))
        try:
            result = classify.classify_role(
                "technical program manager infrastructure deployment reliability " * 3
            )
            self.assertEqual(result.provider, "heuristic")
            self.assertEqual(result.archetype, "A")
        finally:
            jev.is_configured = original_configured
            jev.classify_archetype = original_classify

    def test_uses_jev_when_configured_and_successful(self):
        original_configured = jev.is_configured
        original_classify = jev.classify_archetype
        jev.is_configured = lambda: True
        jev.classify_archetype = lambda text: {
            "archetype": "C",
            "confidence": 0.91,
            "probabilities": {"A": 0.03, "B": 0.06, "C": 0.91},
            "model": "jev-latest",
        }
        try:
            result = classify.classify_role("evaluation golden dataset HITL launch gate")
            self.assertEqual(result.provider, "jev")
            self.assertEqual(result.archetype, "C")
            self.assertEqual(result.archetype_confidence, "High")
            self.assertAlmostEqual(result.raw_confidence, 0.91)
        finally:
            jev.is_configured = original_configured
            jev.classify_archetype = original_classify

    def test_use_jev_false_skips_provider_entirely(self):
        original_configured = jev.is_configured
        called = {"flag": False}

        def spy():
            called["flag"] = True
            return True

        jev.is_configured = spy
        try:
            classify.classify_role("search ranking relevance", use_jev=False)
            self.assertFalse(called["flag"])
        finally:
            jev.is_configured = original_configured


class TestConfidenceLabel(unittest.TestCase):
    def test_bucketing(self):
        self.assertEqual(jev.confidence_label(0.9), "High")
        self.assertEqual(jev.confidence_label(0.5), "Medium")
        self.assertEqual(jev.confidence_label(0.1), "Low")


if __name__ == "__main__":
    unittest.main()
