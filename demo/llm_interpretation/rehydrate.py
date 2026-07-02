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
