"""Tests for the cache-first evidence resolution in demo-interpret.py.

The demo script has a hyphenated filename, so it is loaded via importlib.
These tests exercise ``resolve_evidence_path`` only, with a stubbed builder --
no MassBank DB, SPARQL endpoints, Azure OpenAI, or network access.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "demo" / "demo-test" / "demo-interpret.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("demo_interpret", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


demo_interpret = _load_module()


def _make_args(**overrides) -> argparse.Namespace:
    defaults = dict(
        evidence=None,
        input_file=demo_interpret.DEFAULT_INPUT_PATH,
        output_dir=None,
        rebuild=False,
        top_n=10,
        kg_n=3,
        kg_limit=100,
        pathway_limit=100,
        mz_tolerance=0.01,
        min_matched_peaks=1,
        precursor_tolerance=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _make_builder(calls: list):
    """Return a stub builder that records its call and writes evidence."""

    def _builder(**kwargs):
        calls.append(kwargs)
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = output_dir / "kg_evidence.json"
        evidence_path.write_text(
            json.dumps({"features": [{"inchikey": "built"}]}),
            encoding="utf-8",
        )
        return {"kg_evidence": {"json": str(evidence_path)}}

    return _builder


class ResolveEvidencePathTests(unittest.TestCase):
    def test_explicit_evidence_short_circuits_builder(self) -> None:
        calls: list = []
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "custom.json"
            evidence.write_text("{}", encoding="utf-8")
            args = _make_args(evidence=evidence)

            result = demo_interpret.resolve_evidence_path(
                args, builder=_make_builder(calls)
            )

        self.assertEqual(result, evidence)
        self.assertEqual(calls, [])

    def test_cache_hit_reuses_existing_evidence(self) -> None:
        calls: list = []
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            existing = output_dir / "kg_evidence.json"
            existing.write_text('{"features": []}', encoding="utf-8")
            args = _make_args(output_dir=output_dir, rebuild=False)

            result = demo_interpret.resolve_evidence_path(
                args, builder=_make_builder(calls)
            )

        self.assertEqual(result, existing)
        self.assertEqual(calls, [], "builder must not run on a cache hit")

    def test_cache_miss_runs_builder(self) -> None:
        calls: list = []
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            args = _make_args(output_dir=output_dir, rebuild=False)

            result = demo_interpret.resolve_evidence_path(
                args, builder=_make_builder(calls)
            )

            self.assertEqual(result, output_dir / "kg_evidence.json")
            self.assertTrue(result.is_file())
            self.assertEqual(len(calls), 1)
            self.assertEqual(Path(calls[0]["output_dir"]), output_dir)

    def test_rebuild_forces_builder_despite_cache(self) -> None:
        calls: list = []
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "kg_evidence.json").write_text(
                '{"features": [{"inchikey": "stale"}]}', encoding="utf-8"
            )
            args = _make_args(output_dir=output_dir, rebuild=True)

            result = demo_interpret.resolve_evidence_path(
                args, builder=_make_builder(calls)
            )

            self.assertEqual(result, output_dir / "kg_evidence.json")
            self.assertEqual(len(calls), 1, "rebuild must run the builder")
            payload = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(payload["features"][0]["inchikey"], "built")

    def test_default_output_dir_derives_from_input_stem(self) -> None:
        input_file = Path("/data/input_files/MSBNK-XYZ-123.msp")
        output_dir = demo_interpret.default_output_dir(input_file)
        self.assertEqual(output_dir.name, "MSBNK-XYZ-123")


class MainInjectionTests(unittest.TestCase):
    def _fake_result(self) -> dict:
        return {
            "metadata": {
                "deployment": "fake-deployment",
                "feature_count": 1,
                "succeeded": 1,
                "failed": 0,
                "usage_total": {},
            },
            "summary": {"overview": "fake overview"},
            "features": [
                {"inchikey": "FAKE", "interpretation": {"compound_summary": "ok"}}
            ],
            "failures": [],
        }

    def test_main_uses_injected_interpreter_and_returns_zero(self) -> None:
        import types

        received: dict = {}

        class _FakeInterpreter:
            def interpret_kg_evidence(self, evidence):
                received["evidence"] = evidence
                return MainInjectionTests()._fake_result()

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
                code = demo_interpret.main(
                    ["--evidence", str(evidence_path)],
                    build_interpreter=_build_interpreter,
                )

        self.assertEqual(code, 0)
        self.assertEqual(
            received["evidence"], {"metadata": {}, "features": [{"inchikey": "X"}]}
        )
        self.assertIn("LLM INTERPRETATION", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
