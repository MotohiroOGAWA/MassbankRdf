from __future__ import annotations

from typing import Any

import pandas as pd

from massbank_rdf.models import MSPRecord


def interpret_msp_massbank_kg_with_llm(
    *,
    msp_records: list[MSPRecord],
    massbank_records: pd.DataFrame,
    kg_evidence: dict[str, Any],
    prompt_text: str = "",
) -> dict[str, Any]:
    """Interpret MSP, MassBank, and KG evidence with an LLM.

    This function defines the intended interface only. The implementation will
    call an LLM later and return its structured JSON result.
    """
    raise NotImplementedError
