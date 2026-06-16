from __future__ import annotations

from pydantic import BaseModel, Field


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


class SampleInterpretationSummary(BaseModel):
    """Cross-feature summary for the whole result."""

    overview: str = Field(description="Overall biological overview")
    shared_pathways: list[str] = Field(description="Pathways shared across multiple compounds")
    shared_disease_themes: list[str] = Field(description="Disease themes shared across multiple compounds")
    notable_findings: list[str] = Field(description="Notable findings")
    caveats: list[str] = Field(description="Caveats for the whole interpretation")


class LlmInterpretationResult(BaseModel):
    """Combined interpretation result."""

    summary: SampleInterpretationSummary | None = None
    features: list[FeatureInterpretation] = Field(default_factory=list)
    failures: list[dict] = Field(default_factory=list)