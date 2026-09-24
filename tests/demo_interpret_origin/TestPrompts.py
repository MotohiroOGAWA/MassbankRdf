"""Offline tests for the extended demo prompts."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from demo.llm_interpretation.prompts import (  # noqa: E402
    DEFAULT_FEATURE_SYSTEM_PROMPT,
    build_feature_user_prompt,
)


class FeatureSystemPromptTests(unittest.TestCase):
    def test_mentions_origin_enum_values(self) -> None:
        for value in ["endogenous", "dietary", "drug", "exogenous_other"]:
            self.assertIn(value, DEFAULT_FEATURE_SYSTEM_PROMPT)

    def test_mentions_provenance_and_plausibility(self) -> None:
        for value in [
            "grounded_in_kg",
            "model_knowledge",
            "plausible",
            "implausible",
        ]:
            self.assertIn(value, DEFAULT_FEATURE_SYSTEM_PROMPT)

    def test_retains_identification_correct_assumption(self) -> None:
        self.assertIn("InChIKey", DEFAULT_FEATURE_SYSTEM_PROMPT)
        self.assertIn("correct", DEFAULT_FEATURE_SYSTEM_PROMPT)


class FeatureUserPromptTests(unittest.TestCase):
    def test_embeds_sample_context(self) -> None:
        prompt = build_feature_user_prompt(
            feature_payload={"inchikey": "X"},
            user_context="colorectal cancer mucosa sample",
        )
        self.assertIn("colorectal cancer mucosa sample", prompt)
        self.assertIn("Sample origin", prompt)

    def test_blank_context_renders_placeholder(self) -> None:
        prompt = build_feature_user_prompt(feature_payload={"inchikey": "X"})
        self.assertIn("Sample origin", prompt)
        self.assertIn("-", prompt)


if __name__ == "__main__":
    unittest.main()
