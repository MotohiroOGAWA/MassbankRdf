"""Offline tests for the extended demo interpretation schemas."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pydantic

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from demo.llm_interpretation.schemas import (  # noqa: E402
    FeatureInterpretation,
    OriginCandidate,
    SampleContextAssessment,
    SampleInterpretationSummary,
)


def _origin_candidate() -> dict:
    return {
        "origin": "dietary",
        "likelihood": 0.7,
        "rationale": "found in coffee",
        "provenance": "grounded_in_kg",
        "supporting_evidence": ["Coffea arabica"],
    }


def _assessment() -> dict:
    return {
        "plausibility": "plausible",
        "confidence": 0.8,
        "is_biological_false_positive": False,
        "rationale": "dietary caffeine is expected",
        "provenance": "mixed",
    }


def _feature() -> dict:
    return {
        "inchikey": "RYYVLZVUVIJVGH-UHFFFAOYSA-N",
        "compound_summary": "caffeine",
        "biological_roles": ["stimulant"],
        "disease_associations": [],
        "pathway_insights": [],
        "biospecimen_notes": "blood, urine",
        "caveats": ["isomer ambiguity"],
        "overall_assessment": "consistent",
        "origin_candidates": [_origin_candidate()],
        "sample_context_assessment": _assessment(),
    }


class OriginCandidateTests(unittest.TestCase):
    def test_valid_candidate_parses(self) -> None:
        candidate = OriginCandidate(**_origin_candidate())
        self.assertEqual(candidate.origin, "dietary")
        self.assertEqual(candidate.provenance, "grounded_in_kg")

    def test_invalid_origin_enum_rejected(self) -> None:
        bad = _origin_candidate()
        bad["origin"] = "cosmic_ray"
        with self.assertRaises(pydantic.ValidationError):
            OriginCandidate(**bad)

    def test_invalid_provenance_enum_rejected(self) -> None:
        bad = _origin_candidate()
        bad["provenance"] = "vibes"
        with self.assertRaises(pydantic.ValidationError):
            OriginCandidate(**bad)


class SampleContextAssessmentTests(unittest.TestCase):
    def test_invalid_plausibility_enum_rejected(self) -> None:
        bad = _assessment()
        bad["plausibility"] = "maybe"
        with self.assertRaises(pydantic.ValidationError):
            SampleContextAssessment(**bad)


class FeatureInterpretationTests(unittest.TestCase):
    def test_round_trip_with_new_fields(self) -> None:
        feature = FeatureInterpretation(**_feature())
        dumped = feature.model_dump()
        self.assertEqual(len(dumped["origin_candidates"]), 1)
        self.assertEqual(
            dumped["sample_context_assessment"]["plausibility"], "plausible"
        )

    def test_new_fields_are_required(self) -> None:
        incomplete = _feature()
        del incomplete["origin_candidates"]
        with self.assertRaises(pydantic.ValidationError):
            FeatureInterpretation(**incomplete)


class SampleInterpretationSummaryTests(unittest.TestCase):
    def test_summary_requires_new_fields(self) -> None:
        summary = SampleInterpretationSummary(
            overview="ov",
            shared_pathways=[],
            shared_disease_themes=[],
            notable_findings=[],
            caveats=[],
            likely_false_positives=["ABC"],
            origin_overview="mostly dietary",
        )
        self.assertEqual(summary.likely_false_positives, ["ABC"])


if __name__ == "__main__":
    unittest.main()
