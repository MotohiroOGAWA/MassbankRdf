from __future__ import annotations

import unittest

from massbank_rdf.services.llm_interpretation.prompts import (
    build_feature_user_prompt,
)
from massbank_rdf.services.llm_interpretation.schemas import (
    FeatureInterpretation,
    SampleInterpretationSummary,
)


class TestGuiLlmInterpretation(unittest.TestCase):
    """Tests for the origin/plausibility foundation used by the GUI."""

    def test_feature_schema_exposes_origin_and_plausibility(self) -> None:
        fields = FeatureInterpretation.model_fields

        self.assertIn("origin_candidates", fields)
        self.assertIn("sample_context_assessment", fields)

    def test_summary_schema_exposes_false_positive_fields(self) -> None:
        fields = SampleInterpretationSummary.model_fields

        self.assertIn("likely_false_positives", fields)
        self.assertIn("origin_overview", fields)

    def test_feature_prompt_labels_sample_origin_context(self) -> None:
        prompt = build_feature_user_prompt(
            feature_payload={"inchikey": "X"},
            user_context="colon mucosa",
        )

        self.assertIn("Sample origin / context", prompt)
        self.assertIn("colon mucosa", prompt)


if __name__ == "__main__":
    unittest.main()
