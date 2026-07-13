# Demo: origin & biological-plausibility interpretation (design)

Date: 2026-07-02
Status: Approved (design). Implementation confined to `demo/`.

## Goal

Given a free-text description of a sample's origin (e.g. "colorectal cancer
patient inner-wall / mucosa sample"), let the LLM interpretation:

1. Judge the **biological plausibility** of each identified compound (InChIKey)
   being present in that sample.
2. Classify each compound's likely **origin(s)** with a likelihood and a
   provenance tag, allowing multiple candidates.
3. Flag **biological false positives** — compounds whose identification is
   assumed correct but whose presence in the stated sample origin is
   implausible.

The existing biological interpretation (compound summary, roles, pathways,
diseases, etc.) is **kept and extended**, not replaced.

## Constraints (important)

- **All code edits are confined to `demo/`.** The production package
  `massbank_rdf/` is not modified. The author is a sub-engineer; once the demo
  works it will be reviewed with the project lead before integration into the
  main system.
- Needed production code is **copied into `demo/`** (demo-local copy) and
  validated there.
- **Keep the original code's approach**: single-pass interpretation, structured
  output, required schema fields (no `Optional`/defaults in the LLM schema),
  free-text sample context via the existing `config.user_context`
  (`LLM_USER_CONTEXT` env var).

## Scope decisions (agreed)

- **False-positive meaning**: biological false positive only. The InChIKey
  identification is trusted; MS/DB-level misidentification is out of scope. The
  original "treat identification as correct" assumption is retained.
- **Origin taxonomy**: fixed enum, but **multiple candidates** per compound,
  each with a likelihood and provenance — not a single label.
- **Grounding policy**: KG evidence is primary, LLM parametric knowledge is a
  supplement; every claim carries a provenance tag so KG-grounded vs. model
  knowledge is separable and checkable.
- **Integration**: extend the existing `FeatureInterpretation` schema and the
  single-pass `interpret_kg_evidence` path. The stub
  `interpret_msp_massbank_kg_with_llm` is out of scope (left untouched).

## Architecture / file layout

The existing demo script `demo/demo-test/demo-interpret.py` imports the
production package. To leave production untouched, add a demo-local copy of the
interpretation modules and a new script that imports the copy. The existing
demo script is left unchanged.

```
demo/
  llm_interpretation/            # NEW: demo-local copy + extensions
    __init__.py
    schemas.py                   # copy of production schemas + origin/plausibility fields
    prompts.py                   # copy of production prompts + updated prompts
    rehydrate.py                 # minimal copy: rehydrate_feature + columnar_to_records
    interpreter.py               # copy of AzureOpenAIInterpreter/Config; imports demo modules
  demo-test/
    demo-interpret-origin.py     # NEW: derivative of demo-interpret.py using demo.llm_interpretation,
                                 #      renders origin/plausibility/false-positive
tests/
  demo_interpret_origin/         # NEW: offline tests, same style as tests/demo_interpret/
    __init__.py
    TestDemoInterpretOrigin.py
```

- Copy range is **minimal**: only `rehydrate_feature` / `columnar_to_records`
  are lifted from `kg_evidence_builder.py` (the interpreter's only dependency on
  it).
- Tests live under `tests/` per existing project convention
  (`tests/demo_interpret/`). They import **demo code only**; production
  `massbank_rdf/` is never imported or modified. This is the agreed boundary for
  "confined to demo".

## Schema (demo/llm_interpretation/schemas.py)

Extend the existing `FeatureInterpretation` without breaking existing fields.
New fields are **required** (mirroring the existing schema and the structured-
output strict contract — no `Optional`/defaults).

```python
Origin       = Literal["endogenous", "dietary", "drug", "exogenous_other"]
Provenance   = Literal["grounded_in_kg", "model_knowledge", "mixed"]
Plausibility = Literal["plausible", "uncertain", "implausible"]

class OriginCandidate(BaseModel):
    origin: Origin
    likelihood: float                 # 0..1
    rationale: str
    provenance: Provenance            # KG-grounded / model knowledge / mixed
    supporting_evidence: list[str]    # labels of KG entities actually present
                                      # (disease / biospecimen / species / pathway)

class SampleContextAssessment(BaseModel):
    plausibility: Plausibility
    confidence: float                 # 0..1
    is_biological_false_positive: bool  # true iff plausibility == "implausible"
    rationale: str
    provenance: Provenance

class FeatureInterpretation(BaseModel):
    # existing fields unchanged:
    #   inchikey, compound_summary, biological_roles, disease_associations,
    #   pathway_insights, biospecimen_notes, caveats, overall_assessment
    origin_candidates: list[OriginCandidate]
    sample_context_assessment: SampleContextAssessment
```

Cross-feature summary gains a light aggregation:

```python
class SampleInterpretationSummary(BaseModel):
    # existing fields unchanged
    likely_false_positives: list[str]   # InChIKeys judged implausible
    origin_overview: str                # narrative of the origin distribution
```

**False positive definition**: no separate boolean beyond the mirror field —
`plausibility == "implausible"` *is* the biological false positive.
`is_biological_false_positive` is an explicit mirror for convenient rendering.
The "identification assumed correct" assumption is retained.

## Prompts & grounding (demo/llm_interpretation/prompts.py)

Keep the original prompt skeleton (metabolomics expert; identification assumed
correct; no overclaiming; caveats required). Add:

**`DEFAULT_FEATURE_SYSTEM_PROMPT` additions**
- New task: using the provided sample origin/context, for each compound
  (a) list origin candidates from `endogenous / dietary / drug /
  exogenous_other` with likelihoods; (b) judge whether an origin is consistent
  with the sample context = biological plausibility (`plausible` / `uncertain` /
  `implausible`); (c) if no origin is consistent with the sample context, mark
  `implausible` = biological false positive.
- Define the origin enum: `endogenous` = host metabolism; `dietary` =
  food/plant/beverage derived; `drug` = pharmaceuticals and their administered
  metabolites; `exogenous_other` = environmental contaminant, experimental
  artifact, microbial, and other exogenous sources.
- Grounding policy: prefer KG evidence (diseases / biospecimens / organisms +
  species / activities / pathways). When using model knowledge beyond the KG,
  tag `provenance=model_knowledge`; KG-backed claims use `grounded_in_kg`; both
  use `mixed`. Never fabricate KG citations; `supporting_evidence` lists only
  labels actually present in the KG evidence.
- Re-affirm the identification-assumed-correct assumption (MS-level
  misidentification is not evaluated).

**`build_feature_user_prompt` change**
Elevate the sample context from the weak "User context" heading to an explicit
origin heading; keep the same input channel (`config.user_context`):

```
Sample origin / context (tissue, condition/disease, matrix, known dietary or drug exposure):
{user_context or '-'}
```

**`DEFAULT_SUMMARY_SYSTEM_PROMPT` additions**
Aggregate `likely_false_positives` (InChIKeys judged implausible) across
compounds and summarize the origin distribution in `origin_overview`.

## Rendering (demo-interpret-origin.py)

Per feature, in addition to existing output:
- `Plausibility: <verdict> (conf=..)` with `[FALSE POSITIVE]` emphasized when
  implausible.
- `Origin candidates:` each `origin  likelihood  provenance — rationale`.

In the summary block: `Likely false positives:` and `Origin overview:`.

## Testing (offline, deterministic — same style as tests/demo_interpret/)

1. **Schema tests**: `OriginCandidate` / `SampleContextAssessment` validate;
   enums reject invalid values; `FeatureInterpretation` round-trips with the new
   fields present.
2. **Prompt tests**: the feature system prompt mentions the origin enum,
   provenance rules, the plausibility instruction, and retains the
   identification-assumed-correct assumption; the user prompt embeds the sample
   context string.
3. **Demo main injection test**: mirror the existing pattern — inject a fake
   interpreter that returns the new fields, run offline against the shipped demo
   evidence (`MSBNK-LCSB-LU119906`), assert the origin/plausibility/false-
   positive sections render and the script exits 0.

**Manual live check (optional, not part of offline tests)**: set
`LLM_USER_CONTEXT="大腸がん患者の内壁（粘膜）由来サンプル"` and run
`demo-interpret-origin.py` to inspect real origin/plausibility judgments (e.g.
caffeine). Requires Azure credentials, so it is kept separate from the offline
suite.

## Out of scope

- Modifying any file under `massbank_rdf/`.
- Implementing the `interpret_msp_massbank_kg_with_llm` stub.
- MS/DB-level (identification) false-positive detection.
- Structured/parsed sample-context schema — the sample context stays free text.
