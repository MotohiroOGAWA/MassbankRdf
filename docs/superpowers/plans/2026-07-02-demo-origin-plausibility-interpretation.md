# Demo Origin & Biological-Plausibility Interpretation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In a demo-local copy of the LLM interpretation code, extend the per-InChIKey interpretation with origin candidates and a sample-context biological-plausibility / false-positive assessment.

**Architecture:** Copy the production interpretation modules (`schemas`, `prompts`, `rehydrate`, `interpreter`) into a new `demo/llm_interpretation/` package, extend the schema and prompts there, and add a new CLI script `demo/demo-test/demo-interpret-origin.py` that renders the new fields. Production `massbank_rdf/` is never modified. Grounding stays KG-first with LLM knowledge tagged by provenance.

**Tech Stack:** Python, pydantic (structured output schema), openai (`AzureOpenAI` beta structured parse), unittest.

## Global Constraints

- **All code edits confined to `demo/` and `tests/`.** Never modify or import from `massbank_rdf/` in the new code (tests import demo code only).
- Keep the original approach: **single-pass** interpretation, **structured output**, **required** schema fields (no `Optional`/defaults in the LLM schema).
- Sample context stays **free text** via the existing `config.user_context` (`LLM_USER_CONTEXT` env var). No new function arguments.
- Identification is assumed correct; only **biological** false positives are judged (`plausibility == "implausible"`).
- Origin enum values, verbatim: `endogenous`, `dietary`, `drug`, `exogenous_other`.
- Provenance enum values, verbatim: `grounded_in_kg`, `model_knowledge`, `mixed`.
- Plausibility enum values, verbatim: `plausible`, `uncertain`, `implausible`.
- Run tests with the venv interpreter: `./.venv/Scripts/python.exe -m pytest ...` (bare `python` is a broken Store stub).

---

### Task 1: Demo package scaffold + rehydrate copy

**Files:**
- Create: `demo/llm_interpretation/__init__.py`
- Create: `demo/llm_interpretation/rehydrate.py`
- Create: `tests/demo_interpret_origin/__init__.py`
- Test: `tests/demo_interpret_origin/TestRehydrate.py`

**Interfaces:**
- Produces: `rehydrate_feature(feature: dict) -> dict`, `columnar_to_records(table: dict) -> list[dict]` in `demo.llm_interpretation.rehydrate`.

- [ ] **Step 1: Write the failing test**

Create `tests/demo_interpret_origin/__init__.py` as an empty file, then create `tests/demo_interpret_origin/TestRehydrate.py`:

```python
"""Offline tests for the demo-local rehydrate helper (copied from production)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from demo.llm_interpretation.rehydrate import (  # noqa: E402
    columnar_to_records,
    rehydrate_feature,
)


class RehydrateTests(unittest.TestCase):
    def test_columnar_to_records_zips_columns_and_rows(self) -> None:
        table = {"columns": ["a", "b"], "rows": [[1, 2], [3, 4]]}
        self.assertEqual(
            columnar_to_records(table),
            [{"a": 1, "b": 2}, {"a": 3, "b": 4}],
        )

    def test_rehydrate_feature_passes_through_nested_entities(self) -> None:
        feature = {
            "inchikey": "ABC",
            "summary": {"compounds": 1},
            "entities": {"compounds": {"pc": [{"id": "5"}]}},
        }
        result = rehydrate_feature(feature)
        self.assertEqual(result["inchikey"], "ABC")
        self.assertEqual(result["entities"]["compounds"], {"pc": [{"id": "5"}]})

    def test_rehydrate_feature_converts_columnar_entities(self) -> None:
        feature = {
            "inchikey": "XYZ",
            "entities": {"diseases": {"columns": ["id"], "rows": [["d1"]]}},
        }
        result = rehydrate_feature(feature)
        self.assertEqual(result["entities"]["diseases"], [{"id": "d1"}])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/demo_interpret_origin/TestRehydrate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'demo.llm_interpretation'`

- [ ] **Step 3: Write minimal implementation**

Create `demo/llm_interpretation/__init__.py`:

```python
from __future__ import annotations
```

Create `demo/llm_interpretation/rehydrate.py` (copied verbatim from `massbank_rdf/services/llm_interpretation/kg_evidence_builder.py:450-487`):

```python
"""Feature rehydration helpers, copied from massbank_rdf for the demo.

Copied verbatim from
``massbank_rdf/services/llm_interpretation/kg_evidence_builder.py`` so the demo
interpreter has no import dependency on the production package.
"""

from __future__ import annotations

from typing import Any


def columnar_to_records(
    table: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert legacy columnar table to records."""
    columns = table.get("columns", [])
    rows = table.get("rows", [])

    return [
        dict(zip(columns, row))
        for row in rows
    ]


def rehydrate_feature(
    feature: dict[str, Any],
) -> dict[str, Any]:
    """Return feature entities as record-style JSON.

    Older payloads used columnar objects with columns/rows. New payloads store
    entities as nested JSON grouped by source. Both forms are accepted.
    """
    entities = feature.get("entities", {})
    rehydrated: dict[str, Any] = {}

    if not isinstance(entities, dict):
        entities = {}

    for name, value in entities.items():
        if isinstance(value, dict) and "columns" in value and "rows" in value:
            rehydrated[name] = columnar_to_records(value)
        else:
            rehydrated[name] = value

    return {
        "inchikey": feature.get("inchikey"),
        "summary": feature.get("summary"),
        "entities": rehydrated,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/demo_interpret_origin/TestRehydrate.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add demo/llm_interpretation/__init__.py demo/llm_interpretation/rehydrate.py tests/demo_interpret_origin/__init__.py tests/demo_interpret_origin/TestRehydrate.py
git commit -m "feat(demo): demo-local rehydrate copy for interpretation"
```

---

### Task 2: Extended schemas

**Files:**
- Create: `demo/llm_interpretation/schemas.py`
- Test: `tests/demo_interpret_origin/TestSchemas.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces in `demo.llm_interpretation.schemas`: `OriginCandidate`, `SampleContextAssessment`, `FeatureInterpretation`, `SampleInterpretationSummary`, `LlmInterpretationResult` (all pydantic `BaseModel`). `FeatureInterpretation` adds required fields `origin_candidates: list[OriginCandidate]` and `sample_context_assessment: SampleContextAssessment`. `SampleInterpretationSummary` adds required fields `likely_false_positives: list[str]` and `origin_overview: str`.

- [ ] **Step 1: Write the failing test**

Create `tests/demo_interpret_origin/TestSchemas.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/demo_interpret_origin/TestSchemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'demo.llm_interpretation.schemas'`

- [ ] **Step 3: Write minimal implementation**

Create `demo/llm_interpretation/schemas.py` (existing classes copied from `massbank_rdf/services/llm_interpretation/schemas.py`, new pieces added):

```python
"""Interpretation schemas for the demo, extended with origin & plausibility.

Base classes copied from
``massbank_rdf/services/llm_interpretation/schemas.py`` and extended with
origin candidates and a sample-context biological-plausibility assessment.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Origin = Literal["endogenous", "dietary", "drug", "exogenous_other"]
Provenance = Literal["grounded_in_kg", "model_knowledge", "mixed"]
Plausibility = Literal["plausible", "uncertain", "implausible"]


class OriginCandidate(BaseModel):
    """One candidate origin for a compound in the described sample."""

    origin: Origin = Field(description="Origin category")
    likelihood: float = Field(description="Likelihood of this origin, 0..1")
    rationale: str = Field(description="Why this origin is proposed")
    provenance: Provenance = Field(
        description="grounded_in_kg, model_knowledge, or mixed"
    )
    supporting_evidence: list[str] = Field(
        description="Labels of KG entities actually present that support this origin"
    )


class SampleContextAssessment(BaseModel):
    """Biological plausibility of the compound given the sample origin."""

    plausibility: Plausibility = Field(
        description="plausible, uncertain, or implausible"
    )
    confidence: float = Field(description="Confidence of the verdict, 0..1")
    is_biological_false_positive: bool = Field(
        description="True iff plausibility is implausible"
    )
    rationale: str = Field(description="Reasoning for the plausibility verdict")
    provenance: Provenance = Field(
        description="grounded_in_kg, model_knowledge, or mixed"
    )


class FeatureInterpretation(BaseModel):
    """LLM interpretation for one InChIKey."""

    inchikey: str = Field(description="Interpreted InChIKey")
    compound_summary: str = Field(description="Summary of the identified compound")
    biological_roles: list[str] = Field(description="Biological roles inferred from KG evidence")
    disease_associations: list[str] = Field(description="Disease-related evidence and interpretation")
    pathway_insights: list[str] = Field(description="Pathway-level interpretation")
    biospecimen_notes: str = Field(description="Notes about biospecimen-related evidence")
    caveats: list[str] = Field(description="Important limitations and interpretation caveats")
    overall_assessment: str = Field(description="Overall interpretation")
    origin_candidates: list[OriginCandidate] = Field(
        description="Candidate origins with likelihood and provenance"
    )
    sample_context_assessment: SampleContextAssessment = Field(
        description="Biological plausibility given the described sample origin"
    )


class SampleInterpretationSummary(BaseModel):
    """Cross-feature summary for the whole result."""

    overview: str = Field(description="Overall biological overview")
    shared_pathways: list[str] = Field(description="Pathways shared across multiple compounds")
    shared_disease_themes: list[str] = Field(description="Disease themes shared across multiple compounds")
    notable_findings: list[str] = Field(description="Notable findings")
    caveats: list[str] = Field(description="Caveats for the whole interpretation")
    likely_false_positives: list[str] = Field(
        description="InChIKeys judged implausible for the sample origin"
    )
    origin_overview: str = Field(
        description="Narrative of the origin distribution across compounds"
    )


class LlmInterpretationResult(BaseModel):
    """Combined interpretation result."""

    summary: SampleInterpretationSummary | None = None
    features: list[FeatureInterpretation] = Field(default_factory=list)
    failures: list[dict] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/demo_interpret_origin/TestSchemas.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add demo/llm_interpretation/schemas.py tests/demo_interpret_origin/TestSchemas.py
git commit -m "feat(demo): extend interpretation schema with origin & plausibility"
```

---

### Task 3: Extended prompts

**Files:**
- Create: `demo/llm_interpretation/prompts.py`
- Test: `tests/demo_interpret_origin/TestPrompts.py`

**Interfaces:**
- Produces in `demo.llm_interpretation.prompts`: `DEFAULT_FEATURE_SYSTEM_PROMPT: str`, `DEFAULT_SUMMARY_SYSTEM_PROMPT: str`, `build_feature_user_prompt(*, feature_payload: dict, user_context: str = "", output_language: str = "Japanese") -> str`, `build_summary_user_prompt(*, interpretations: list[dict], user_context: str = "", output_language: str = "Japanese") -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/demo_interpret_origin/TestPrompts.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/demo_interpret_origin/TestPrompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'demo.llm_interpretation.prompts'`

- [ ] **Step 3: Write minimal implementation**

Create `demo/llm_interpretation/prompts.py` (base copied from `massbank_rdf/services/llm_interpretation/prompts.py`, with the origin/plausibility additions):

```python
"""Interpretation prompts for the demo, extended for origin & plausibility.

Base prompts copied from
``massbank_rdf/services/llm_interpretation/prompts.py`` and extended with a
sample-context plausibility and origin-classification task.
"""

from __future__ import annotations


DEFAULT_FEATURE_SYSTEM_PROMPT = """\
You are an expert in metabolomics, mass spectrometry, and cheminformatics.
You receive knowledge graph evidence linked to an identified compound by InChIKey.

Assumptions:
- Treat the compound identification by InChIKey as correct.
- Do not evaluate MS/MS identification confidence itself.
- Evidence may come from PubChem, HMDB, KNApSAcK, and other databases.
- Some fields may be missing.
- KNApSAcK activities may look abundant because category, function, and species
  can form many combinations. Do not treat row count alone as evidence strength.

Requirements:
- Interpret only what is supported by the provided evidence.
- Do not overclaim causality.
- Distinguish database associations from experimental validation.
- Include caveats about isomer ambiguity, missing database fields, KG evidence limitations,
  and the assumption that MS identification is correct.

Sample-context plausibility and origin task:
- You are also given a free-text "Sample origin / context" describing where the
  data came from (tissue, condition/disease, matrix, known dietary or drug exposure).
- For each compound, propose one or more origin candidates from this fixed set:
  - endogenous: produced by the host's own metabolism.
  - dietary: derived from food, plants, or beverages.
  - drug: pharmaceuticals or their administered metabolites.
  - exogenous_other: environmental contaminant, experimental artifact, microbial,
    or other exogenous source.
  Give each candidate a likelihood in 0..1 and a short rationale.
- Judge whether at least one plausible origin is consistent with the sample
  context. Report plausibility as one of: plausible, uncertain, implausible.
- If no origin is consistent with the sample context, set plausibility to
  implausible and set is_biological_false_positive to true. This is a biological
  false positive: the identification is still assumed correct, but the compound's
  presence in this sample origin is not plausible.

Grounding and provenance:
- Base judgments primarily on the provided KG evidence: diseases, biospecimens,
  organisms/species, activities, and pathways.
- You may use your own biological knowledge beyond the KG, but tag every claim's
  provenance: grounded_in_kg when supported by the provided evidence,
  model_knowledge when it relies on knowledge outside the evidence, mixed when both.
- Never fabricate KG citations. supporting_evidence must list only labels that
  actually appear in the provided KG evidence.
"""


DEFAULT_SUMMARY_SYSTEM_PROMPT = """\
You are an expert in metabolomics.
You receive multiple compound-level interpretations from one sample or result set.

Your task:
- Summarize the biological meaning across all interpreted compounds.
- Extract shared pathway themes and disease-related themes.
- Do not invent new facts not present in the compound-level interpretations.
- Include caveats about isomer ambiguity, missing database fields, KG limitations,
  and the assumption that MS identification is correct.
- Collect into likely_false_positives the InChIKeys whose plausibility was
  implausible for the sample origin.
- Summarize the distribution of origins across compounds in origin_overview.
"""


def build_feature_user_prompt(
    *,
    feature_payload: dict,
    user_context: str = "",
    output_language: str = "Japanese",
) -> str:
    """Build user prompt for one feature."""
    return (
        f"Output language: {output_language}\n\n"
        "Sample origin / context (tissue, condition/disease, matrix, "
        "known dietary or drug exposure):\n"
        f"{user_context or '-'}\n\n"
        "KG evidence JSON:\n"
        f"{feature_payload}"
    )


def build_summary_user_prompt(
    *,
    interpretations: list[dict],
    user_context: str = "",
    output_language: str = "Japanese",
) -> str:
    """Build user prompt for cross-feature summary."""
    return (
        f"Output language: {output_language}\n\n"
        "Sample origin / context:\n"
        f"{user_context or '-'}\n\n"
        "Compound-level interpretations JSON:\n"
        f"{interpretations}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/demo_interpret_origin/TestPrompts.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add demo/llm_interpretation/prompts.py tests/demo_interpret_origin/TestPrompts.py
git commit -m "feat(demo): extend prompts for origin & plausibility task"
```

---

### Task 4: Demo-local interpreter

**Files:**
- Create: `demo/llm_interpretation/interpreter.py`
- Modify: `demo/llm_interpretation/__init__.py`
- Test: `tests/demo_interpret_origin/TestInterpreter.py`

**Interfaces:**
- Consumes: `rehydrate_feature` (Task 1), prompts (Task 3), `FeatureInterpretation` / `SampleInterpretationSummary` (Task 2).
- Produces in `demo.llm_interpretation`: `AzureOpenAIInterpretationConfig` (frozen dataclass; fields `endpoint`, `api_key`, `deployment`, `api_version="2024-10-21"`, `output_language="Japanese"`, `user_context=""`, `feature_system_prompt`, `summary_system_prompt`) and `AzureOpenAIInterpreter` with `interpret_kg_evidence(kg_evidence: dict) -> dict` and `_accumulate_usage(total: dict, usage: dict) -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/demo_interpret_origin/TestInterpreter.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/demo_interpret_origin/TestInterpreter.py -v`
Expected: FAIL — `ImportError: cannot import name 'AzureOpenAIInterpreter' from 'demo.llm_interpretation'`

- [ ] **Step 3: Write minimal implementation**

Create `demo/llm_interpretation/interpreter.py` (copied verbatim from `massbank_rdf/services/llm_interpretation/azure_openai_interpreter.py`, with the import of `rehydrate_feature` changed from `.kg_evidence_builder` to `.rehydrate`):

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .rehydrate import (
    rehydrate_feature,
)
from .prompts import (
    DEFAULT_FEATURE_SYSTEM_PROMPT,
    DEFAULT_SUMMARY_SYSTEM_PROMPT,
    build_feature_user_prompt,
    build_summary_user_prompt,
)
from .schemas import (
    FeatureInterpretation,
    SampleInterpretationSummary,
)


@dataclass(frozen=True)
class AzureOpenAIInterpretationConfig:
    """Azure OpenAI configuration for GUI interpretation."""

    endpoint: str
    api_key: str
    deployment: str
    api_version: str = "2024-10-21"
    output_language: str = "Japanese"
    user_context: str = ""
    feature_system_prompt: str = DEFAULT_FEATURE_SYSTEM_PROMPT
    summary_system_prompt: str = DEFAULT_SUMMARY_SYSTEM_PROMPT


class AzureOpenAIInterpreter:
    """Run LLM interpretation using Azure OpenAI structured outputs."""

    def __init__(
        self,
        config: AzureOpenAIInterpretationConfig,
    ) -> None:
        self.config = config

    def _build_client(self):
        """Build Azure OpenAI client."""
        from openai import AzureOpenAI

        return AzureOpenAI(
            azure_endpoint=self.config.endpoint,
            api_key=self.config.api_key,
            api_version=self.config.api_version,
        )

    def _parse(
        self,
        *,
        client: Any,
        system_prompt: str,
        user_content: str,
        schema: Any,
    ) -> tuple[Any, dict[str, Any]]:
        """Call Azure OpenAI structured output API."""
        completion = client.beta.chat.completions.parse(
            model=self.config.deployment,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
            response_format=schema,
        )

        message = completion.choices[0].message

        if getattr(message, "refusal", None):
            raise RuntimeError(f"Model refused the request: {message.refusal}")

        if message.parsed is None:
            raise RuntimeError("Structured output parse failed: parsed=None")

        usage = completion.usage.model_dump() if completion.usage else {}

        return message.parsed, usage

    def interpret_kg_evidence(
        self,
        kg_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """Interpret all KG evidence features and summarize them."""
        client = self._build_client()

        usage_total: dict[str, int] = {}
        feature_records: list[dict[str, Any]] = []
        interpretations: list[FeatureInterpretation] = []
        failures: list[dict[str, str]] = []

        features = kg_evidence.get("features", [])

        for feature in features:
            inchikey = str(feature.get("inchikey", ""))
            payload = rehydrate_feature(feature)

            try:
                user_prompt = build_feature_user_prompt(
                    feature_payload=payload,
                    user_context=self.config.user_context,
                    output_language=self.config.output_language,
                )

                interpretation, usage = self._parse(
                    client=client,
                    system_prompt=self.config.feature_system_prompt,
                    user_content=user_prompt,
                    schema=FeatureInterpretation,
                )

                self._accumulate_usage(usage_total, usage)

                payload_bytes = json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")

                feature_records.append(
                    {
                        "inchikey": inchikey,
                        "interpretation": interpretation.model_dump(),
                        "input_sha256": hashlib.sha256(payload_bytes).hexdigest(),
                        "usage": usage,
                    }
                )
                interpretations.append(interpretation)

            except Exception as exc:
                failures.append(
                    {
                        "inchikey": inchikey,
                        "error": str(exc),
                    }
                )

        summary = None

        if interpretations:
            try:
                summary_prompt = build_summary_user_prompt(
                    interpretations=[
                        interpretation.model_dump()
                        for interpretation in interpretations
                    ],
                    user_context=self.config.user_context,
                    output_language=self.config.output_language,
                )

                sample_summary, usage = self._parse(
                    client=client,
                    system_prompt=self.config.summary_system_prompt,
                    user_content=summary_prompt,
                    schema=SampleInterpretationSummary,
                )

                self._accumulate_usage(usage_total, usage)
                summary = sample_summary.model_dump()

            except Exception as exc:
                failures.append(
                    {
                        "inchikey": "__summary__",
                        "error": str(exc),
                    }
                )

        return {
            "metadata": {
                "source": "massbank_rdf_demo",
                "deployment": self.config.deployment,
                "api_version": self.config.api_version,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "feature_count": len(features),
                "succeeded": len(feature_records),
                "failed": len(failures),
                "usage_total": usage_total,
            },
            "summary": summary,
            "features": feature_records,
            "failures": failures,
        }

    def _accumulate_usage(
        self,
        total: dict[str, int],
        usage: dict[str, Any],
    ) -> None:
        """Accumulate token usage."""
        for key in [
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        ]:
            value = usage.get(key)
            if value is not None:
                total[key] = total.get(key, 0) + int(value)
```

Replace the contents of `demo/llm_interpretation/__init__.py` with:

```python
from __future__ import annotations

from .interpreter import (
    AzureOpenAIInterpretationConfig,
    AzureOpenAIInterpreter,
)

__all__ = [
    "AzureOpenAIInterpretationConfig",
    "AzureOpenAIInterpreter",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/demo_interpret_origin/TestInterpreter.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add demo/llm_interpretation/interpreter.py demo/llm_interpretation/__init__.py tests/demo_interpret_origin/TestInterpreter.py
git commit -m "feat(demo): demo-local Azure interpreter using extended schema/prompts"
```

---

### Task 5: Demo CLI script with origin/plausibility rendering

**Files:**
- Create: `demo/demo-test/demo-interpret-origin.py`
- Test: `tests/demo_interpret_origin/TestDemoInterpretOrigin.py`

**Interfaces:**
- Consumes: `demo.llm_interpretation.AzureOpenAIInterpretationConfig` / `AzureOpenAIInterpreter` (Task 4); `demo.llm_interpretation_input.build_demo_input_from_msp.build_demo_data_from_msp_file` (existing).
- Produces: module-level `main(argv=None, *, build_interpreter=...) -> int`, `render_text(result: dict) -> None`, `resolve_evidence_path(args, *, builder=...) -> Path`, `default_output_dir(input_file: Path) -> Path`, `parse_args(argv) -> Namespace`, and constants `DEFAULT_INPUT_PATH`, `DEFAULT_OUTPUT_ROOT`, `EVIDENCE_FILENAME`.

- [ ] **Step 1: Write the failing test**

Create `tests/demo_interpret_origin/TestDemoInterpretOrigin.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/demo_interpret_origin/TestDemoInterpretOrigin.py -v`
Expected: FAIL — `FileNotFoundError` / import error because `demo/demo-test/demo-interpret-origin.py` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `demo/demo-test/demo-interpret-origin.py`:

```python
"""CLI demo: interpret demo MSP data with origin & plausibility judgment.

Derivative of ``demo-interpret.py`` that uses the demo-local interpretation
package (``demo.llm_interpretation``) instead of the production one, and renders
per-compound origin candidates and a sample-context biological-plausibility /
false-positive assessment.

Describe the sample origin via the ``LLM_USER_CONTEXT`` environment variable,
e.g. ``大腸がん患者の内壁（粘膜）由来サンプル``. Evidence building is cache-first,
identical to ``demo-interpret.py``.

Environment variables
---------------------
Required (always, for the LLM call):
    AZURE_OPENAI_ENDPOINT      e.g. https://<resource>.openai.azure.com
    AZURE_OPENAI_API_KEY       your Azure OpenAI API key
    AZURE_OPENAI_DEPLOYMENT    deployment name of a structured-output model
Optional:
    AZURE_OPENAI_API_VERSION   defaults to 2024-10-21
    LLM_OUTPUT_LANGUAGE        defaults to Japanese
    LLM_USER_CONTEXT           sample origin / context (defaults to empty)

Usage
-----
    python demo/demo-test/demo-interpret-origin.py
    python demo/demo-test/demo-interpret-origin.py --evidence path/to/kg_evidence.json
    python demo/demo-test/demo-interpret-origin.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Make the repository root importable when run as a script from anywhere.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from demo.llm_interpretation import (  # noqa: E402
    AzureOpenAIInterpretationConfig,
    AzureOpenAIInterpreter,
)
from demo.llm_interpretation_input.build_demo_input_from_msp import (  # noqa: E402
    build_demo_data_from_msp_file,
)


_LLM_INPUT_ROOT = (
    REPO_ROOT / "massbank_rdf" / "data" / "llm_input_from_msp"
)

DEFAULT_INPUT_PATH = (
    _LLM_INPUT_ROOT / "input_files" / "MSBNK-LCSB-LU119906.msp"
)

DEFAULT_OUTPUT_ROOT = _LLM_INPUT_ROOT / "output_files"

EVIDENCE_FILENAME = "kg_evidence.json"

REQUIRED_ENV_VARS = (
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_DEPLOYMENT",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Interpret demo MSP data with origin & plausibility judgment: "
            "MSP -> KG evidence -> interpretation. Evidence building is cache-first."
        ),
    )
    parser.add_argument(
        "--input-file",
        dest="input_file",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"MSP input file to interpret (default: {DEFAULT_INPUT_PATH}).",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=None,
        help=(
            "Directory where KG evidence is cached/built "
            "(default: <output_files>/<msp-stem>)."
        ),
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force a fresh MassBank + KG lookup even if cached evidence exists.",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=None,
        help=(
            "Interpret this pre-built kg_evidence.json directly, skipping the "
            "MSP/build path. Overrides --input-file/--output-dir/--rebuild."
        ),
    )
    parser.add_argument("--top-n", dest="top_n", type=int, default=10)
    parser.add_argument("--kg-n", dest="kg_n", type=int, default=3)
    parser.add_argument("--kg-limit", dest="kg_limit", type=int, default=100)
    parser.add_argument(
        "--pathway-limit",
        dest="pathway_limit",
        type=int,
        default=100,
        help="Maximum number of PubChem pathways fetched per InChIKey.",
    )
    parser.add_argument(
        "--mz-tolerance", dest="mz_tolerance", type=float, default=0.01
    )
    parser.add_argument(
        "--min-matched-peaks", dest="min_matched_peaks", type=int, default=1
    )
    parser.add_argument(
        "--precursor-tolerance",
        dest="precursor_tolerance",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the raw interpretation result as JSON instead of text.",
    )
    return parser.parse_args(argv)


def default_output_dir(input_file: Path) -> Path:
    """Default cache/build directory for an MSP file: one dir per MSP stem."""
    return DEFAULT_OUTPUT_ROOT / Path(input_file).stem


def resolve_evidence_path(
    args: argparse.Namespace,
    *,
    builder=build_demo_data_from_msp_file,
) -> Path:
    """Return the KG evidence path to interpret, building it if needed."""
    if args.evidence is not None:
        return Path(args.evidence)

    input_file = Path(args.input_file)
    output_dir = (
        Path(args.output_dir)
        if args.output_dir is not None
        else default_output_dir(input_file)
    )
    evidence_path = output_dir / EVIDENCE_FILENAME

    if evidence_path.is_file() and not args.rebuild:
        print(f"Using cached KG evidence: {evidence_path}", file=sys.stderr)
        return evidence_path

    if not input_file.is_file():
        print(f"MSP input file not found: {input_file}", file=sys.stderr)
        raise SystemExit(1)

    print(
        f"Building KG evidence from MSP: {input_file} -> {output_dir} "
        f"(this runs MassBank search + KG/SPARQL lookup)...",
        file=sys.stderr,
    )
    builder(
        input_file=input_file,
        output_dir=output_dir,
        run_kg_lookup=True,
        top_n=args.top_n,
        mz_tolerance=args.mz_tolerance,
        min_matched_peaks=args.min_matched_peaks,
        kg_n=args.kg_n,
        kg_limit=args.kg_limit,
        precursor_tolerance=args.precursor_tolerance,
        pathway_per_inchikey_limit=args.pathway_limit,
    )
    return evidence_path


def load_config_from_env() -> AzureOpenAIInterpretationConfig:
    """Build the interpreter config from environment variables."""
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        _exit_missing_env(missing)

    return AzureOpenAIInterpretationConfig(
        endpoint=os.environ["AZURE_OPENAI_ENDPOINT"].strip(),
        api_key=os.environ["AZURE_OPENAI_API_KEY"].strip(),
        deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"].strip(),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21").strip(),
        output_language=os.environ.get("LLM_OUTPUT_LANGUAGE", "Japanese").strip()
        or "Japanese",
        user_context=os.environ.get("LLM_USER_CONTEXT", ""),
    )


def _exit_missing_env(missing: list[str]) -> None:
    lines = [
        "Missing required environment variable(s):",
        *(f"  - {name}" for name in missing),
        "",
        "Set them for the current PowerShell session, e.g.:",
    ]
    example = {
        "AZURE_OPENAI_ENDPOINT": "https://<your-resource>.openai.azure.com",
        "AZURE_OPENAI_API_KEY": "<your-api-key>",
        "AZURE_OPENAI_DEPLOYMENT": "<your-deployment-name>",
    }
    for name in missing:
        lines.append(f'  $env:{name} = "{example.get(name, "<value>")}"')
    print("\n".join(lines), file=sys.stderr)
    raise SystemExit(1)


def _default_build_interpreter():
    """Build the real Azure interpreter from environment configuration."""
    config = load_config_from_env()
    return AzureOpenAIInterpreter(config), config


def load_evidence(path: Path) -> dict[str, Any]:
    if not path.is_file():
        print(f"Evidence file not found: {path}", file=sys.stderr)
        raise SystemExit(1)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _print_list(title: str, items: Any, indent: str = "  ") -> None:
    if not items:
        return
    print(f"{indent}{title}:")
    if isinstance(items, list):
        for item in items:
            print(f"{indent}  - {item}")
    else:
        print(f"{indent}  {items}")


def _print_origin_candidates(candidates: Any, indent: str = "  ") -> None:
    if not candidates:
        return
    print(f"{indent}Origin candidates:")
    for candidate in candidates:
        origin = candidate.get("origin")
        likelihood = candidate.get("likelihood")
        provenance = candidate.get("provenance")
        rationale = candidate.get("rationale")
        print(
            f"{indent}  - {origin}  likelihood={likelihood}  "
            f"[{provenance}] — {rationale}"
        )
        _print_list("evidence", candidate.get("supporting_evidence"), indent + "    ")


def _print_plausibility(assessment: Any, indent: str = "  ") -> None:
    if not assessment:
        return
    verdict = assessment.get("plausibility")
    confidence = assessment.get("confidence")
    flag = " [FALSE POSITIVE]" if assessment.get("is_biological_false_positive") else ""
    print(f"{indent}Plausibility: {verdict} (conf={confidence}){flag}")
    if assessment.get("rationale"):
        print(f"{indent}  {assessment['rationale']}")


def render_text(result: dict[str, Any]) -> None:
    metadata = result.get("metadata", {})
    summary = result.get("summary")
    features = result.get("features", [])
    failures = result.get("failures", [])

    print("=" * 72)
    print("LLM INTERPRETATION")
    print("=" * 72)
    print(
        f"deployment={metadata.get('deployment')} "
        f"features={metadata.get('feature_count')} "
        f"succeeded={metadata.get('succeeded')} "
        f"failed={metadata.get('failed')}"
    )

    if summary:
        print("\n" + "-" * 72)
        print("SAMPLE SUMMARY")
        print("-" * 72)
        if summary.get("overview"):
            print(summary["overview"])
        _print_list("Shared pathways", summary.get("shared_pathways"))
        _print_list("Shared disease themes", summary.get("shared_disease_themes"))
        _print_list("Notable findings", summary.get("notable_findings"))
        _print_list("Likely false positives", summary.get("likely_false_positives"))
        if summary.get("origin_overview"):
            _print_list("Origin overview", summary["origin_overview"])
        _print_list("Caveats", summary.get("caveats"))

    for record in features:
        interpretation = record.get("interpretation", {})
        print("\n" + "-" * 72)
        print(f"FEATURE  {record.get('inchikey')}")
        print("-" * 72)
        if interpretation.get("compound_summary"):
            print(interpretation["compound_summary"])
        _print_plausibility(interpretation.get("sample_context_assessment"))
        _print_origin_candidates(interpretation.get("origin_candidates"))
        _print_list("Biological roles", interpretation.get("biological_roles"))
        _print_list("Pathway insights", interpretation.get("pathway_insights"))
        _print_list("Disease associations", interpretation.get("disease_associations"))
        if interpretation.get("biospecimen_notes"):
            _print_list("Biospecimen notes", interpretation["biospecimen_notes"])
        _print_list("Caveats", interpretation.get("caveats"))
        if interpretation.get("overall_assessment"):
            _print_list("Overall assessment", interpretation["overall_assessment"])

    if failures:
        print("\n" + "-" * 72)
        print("FAILURES")
        print("-" * 72)
        for failure in failures:
            print(f"  - {failure.get('inchikey')}: {failure.get('error')}")

    usage = metadata.get("usage_total") or {}
    if usage:
        print("\n" + "-" * 72)
        print(
            "Token usage: "
            f"prompt={usage.get('prompt_tokens')} "
            f"completion={usage.get('completion_tokens')} "
            f"total={usage.get('total_tokens')}"
        )


def main(argv: list[str] | None = None, *, build_interpreter=_default_build_interpreter) -> int:
    args = parse_args(argv)
    evidence_path = resolve_evidence_path(args)
    evidence = load_evidence(evidence_path)

    interpreter, config = build_interpreter()

    print(
        f"Interpreting {len(evidence.get('features', []))} feature(s) "
        f"from {evidence_path} using deployment '{config.deployment}'...",
        file=sys.stderr,
    )

    result = interpreter.interpret_kg_evidence(evidence)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        render_text(result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/demo_interpret_origin/TestDemoInterpretOrigin.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the whole new offline suite**

Run: `./.venv/Scripts/python.exe -m pytest tests/demo_interpret_origin/ -v`
Expected: PASS (all tasks' tests, 20 total)

- [ ] **Step 6: Commit**

```bash
git add demo/demo-test/demo-interpret-origin.py tests/demo_interpret_origin/TestDemoInterpretOrigin.py
git commit -m "feat(demo): CLI script rendering origin & plausibility interpretation"
```

---

## Manual live check (optional, not part of the offline suite)

Requires Azure credentials. Confirms real judgments end-to-end.

```powershell
$env:AZURE_OPENAI_ENDPOINT = "https://<resource>.openai.azure.com"
$env:AZURE_OPENAI_API_KEY = "<key>"
$env:AZURE_OPENAI_DEPLOYMENT = "<deployment>"
$env:LLM_USER_CONTEXT = "大腸がん患者の内壁（粘膜）由来サンプル"
./.venv/Scripts/python.exe demo/demo-test/demo-interpret-origin.py
```

Inspect that each feature reports origin candidates, a plausibility verdict, and that implausible compounds are flagged as biological false positives.
