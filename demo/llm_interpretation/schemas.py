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
