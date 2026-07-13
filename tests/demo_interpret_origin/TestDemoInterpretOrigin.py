"""Offline tests for demo-interpret-origin.py.

The script has a hyphenated filename, so it is loaded via importlib. These
tests inject a fake interpreter and never touch Azure, MassBank, or the network.
"""

from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "demo" / "demo-test" / "demo-interpret-origin.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("demo_interpret_origin", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


demo_origin = _load_module()


def _fake_result() -> dict:
    return {
        "metadata": {
            "deployment": "fake-deployment",
            "feature_count": 1,
            "succeeded": 1,
            "failed": 0,
            "usage_total": {},
        },
        "summary": {
            "overview": "fake overview",
            "likely_false_positives": ["FAKE2"],
            "origin_overview": "mostly dietary",
        },
        "features": [
            {
                "inchikey": "FAKE",
                "interpretation": {
                    "compound_summary": "caffeine",
                    "origin_candidates": [
                        {
                            "origin": "dietary",
                            "likelihood": 0.7,
                            "rationale": "coffee",
                            "provenance": "grounded_in_kg",
                            "supporting_evidence": ["Coffea"],
                        }
                    ],
                    "sample_context_assessment": {
                        "plausibility": "implausible",
                        "confidence": 0.6,
                        "is_biological_false_positive": True,
                        "rationale": "no dietary input in sterile culture",
                        "provenance": "mixed",
                    },
                },
            }
        ],
        "failures": [],
    }


class RenderTests(unittest.TestCase):
    def test_render_includes_origin_and_false_positive(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            demo_origin.render_text(_fake_result())
        out = buffer.getvalue()
        self.assertIn("Origin candidates", out)
        self.assertIn("dietary", out)
        self.assertIn("FALSE POSITIVE", out)
        self.assertIn("Likely false positives", out)
        self.assertIn("Origin overview", out)


class MainInjectionTests(unittest.TestCase):
    def test_main_offline_with_injected_interpreter(self) -> None:
        received: dict = {}

        class _FakeInterpreter:
            def interpret_kg_evidence(self, evidence):
                received["evidence"] = evidence
                return _fake_result()

        def _build_interpreter():
            config = types.SimpleNamespace(deployment="fake-deployment")
            return _FakeInterpreter(), config

        with tempfile.TemporaryDirectory() as tmp:
            evidence_path = Path(tmp) / "kg_evidence.json"
            evidence_path.write_text(
                json.dumps({"metadata": {}, "features": [{"inchikey": "X"}]}),
                encoding="utf-8",
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = demo_origin.main(
                    ["--evidence", str(evidence_path)],
                    build_interpreter=_build_interpreter,
                )

        self.assertEqual(code, 0)
        self.assertEqual(
            received["evidence"], {"metadata": {}, "features": [{"inchikey": "X"}]}
        )
        self.assertIn("LLM INTERPRETATION", buffer.getvalue())

    def test_main_interprets_shipped_demo_evidence_offline(self) -> None:
        received: dict = {}

        class _FakeInterpreter:
            def interpret_kg_evidence(self, evidence):
                received["evidence"] = evidence
                return _fake_result()

        def _build_interpreter():
            config = types.SimpleNamespace(deployment="fake-deployment")
            return _FakeInterpreter(), config

        evidence_path = (
            demo_origin.DEFAULT_OUTPUT_ROOT
            / "MSBNK-LCSB-LU119906"
            / demo_origin.EVIDENCE_FILENAME
        )
        self.assertTrue(
            evidence_path.is_file(),
            f"shipped demo evidence missing: {evidence_path}",
        )

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = demo_origin.main(
                ["--evidence", str(evidence_path)],
                build_interpreter=_build_interpreter,
            )

        self.assertEqual(code, 0)
        features = received["evidence"].get("features", [])
        self.assertEqual(len(features), 3)
        self.assertIn("LLM INTERPRETATION", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
