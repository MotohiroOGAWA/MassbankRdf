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
        f"User context:\n{user_context or '-'}\n\n"
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
        f"User context:\n{user_context or '-'}\n\n"
        "Compound-level interpretations JSON:\n"
        f"{interpretations}"
    )