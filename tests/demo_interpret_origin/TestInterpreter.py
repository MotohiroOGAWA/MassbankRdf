"""Offline tests for the demo-local interpreter wiring (no Azure calls)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from demo.llm_interpretation import (  # noqa: E402
    AzureOpenAIInterpretationConfig,
    AzureOpenAIInterpreter,
)
from demo.llm_interpretation.prompts import (  # noqa: E402
    DEFAULT_FEATURE_SYSTEM_PROMPT,
)


class ConfigTests(unittest.TestCase):
    def test_config_defaults_use_demo_feature_prompt(self) -> None:
        config = AzureOpenAIInterpretationConfig(
            endpoint="e", api_key="k", deployment="d"
        )
        self.assertEqual(config.feature_system_prompt, DEFAULT_FEATURE_SYSTEM_PROMPT)
        self.assertEqual(config.api_version, "2024-10-21")


class AccumulateUsageTests(unittest.TestCase):
    def test_accumulate_sums_known_keys(self) -> None:
        config = AzureOpenAIInterpretationConfig(
            endpoint="e", api_key="k", deployment="d"
        )
        interpreter = AzureOpenAIInterpreter(config)
        total: dict = {}
        interpreter._accumulate_usage(total, {"prompt_tokens": 3, "total_tokens": 5})
        interpreter._accumulate_usage(total, {"prompt_tokens": 2, "completion_tokens": 4})
        self.assertEqual(total["prompt_tokens"], 5)
        self.assertEqual(total["completion_tokens"], 4)
        self.assertEqual(total["total_tokens"], 5)


if __name__ == "__main__":
    unittest.main()
