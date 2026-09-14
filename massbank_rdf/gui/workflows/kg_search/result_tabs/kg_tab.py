from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import gradio as gr

from massbank_rdf.gui.session_store import TemporarySessionStore


def make_empty_kg_evidence() -> dict[str, Any]:
    return {
        "metadata": {
            "feature_count": 0,
        },
        "features": [],
    }


def _write_kg_json_file(
    kg_evidence: dict[str, Any],
) -> str:
    output_dir = Path(
        tempfile.mkdtemp(prefix="massbank_rdf_kg_")
    )
    json_path = output_dir / "kg_evidence.json"
    json_path.write_text(
        json.dumps(kg_evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(json_path)


def _format_kg_status(
    kg_evidence: dict[str, Any],
    *,
    inchikeys: list[str],
) -> str:
    features = kg_evidence.get("features", [])
    if not isinstance(features, list):
        features = []

    entity_counts = {
        "compounds": 0,
        "pathways": 0,
        "diseases": 0,
        "biospecimens": 0,
        "organisms": 0,
        "activities": 0,
    }

    for feature in features:
        if not isinstance(feature, dict):
            continue
        entities = feature.get("entities", {})
        if not isinstance(entities, dict):
            continue
        for key in entity_counts:
            value = entities.get(key, [])
            if isinstance(value, list):
                entity_counts[key] += len(value)
            elif isinstance(value, dict):
                entity_counts[key] += sum(
                    len(rows)
                    for rows in value.values()
                    if isinstance(rows, list)
                )

    return (
        "KG evidence JSON was loaded from the current browser session.\n\n"
        f"InChIKeys: {', '.join(inchikeys) if inchikeys else '-'}\n"
        f"Feature count: {len(features)}\n"
        f"Compounds: {entity_counts['compounds']}\n"
        f"Pathways: {entity_counts['pathways']}\n"
        f"Diseases: {entity_counts['diseases']}\n"
        f"Biospecimens: {entity_counts['biospecimens']}\n"
        f"Organisms: {entity_counts['organisms']}\n"
        f"Activities: {entity_counts['activities']}"
    )


def create_kg_tab() -> tuple[
    gr.Textbox,
    gr.JSON,
    gr.File,
]:
    """Create KG tab components."""
    status_text = gr.Textbox(
        label="KG status",
        lines=8,
        interactive=False,
    )

    kg_evidence_json = gr.JSON(
        label="KG evidence JSON",
        value=make_empty_kg_evidence(),
    )

    kg_json_file = gr.File(
        label="Download KG evidence JSON",
        interactive=False,
    )

    return (
        status_text,
        kg_evidence_json,
        kg_json_file,
    )


def build_kg_display_loader(
    session_store: TemporarySessionStore,
    *,
    session_cookie_name: str = "kg_session_id",
):
    """Build callback for displaying saved KG evidence JSON."""

    def _load_saved_kg_result(
        request: gr.Request,
    ) -> tuple[
        str,
        dict[str, Any],
        str | None,
        gr.update,
    ]:
        session_id = (
            request.request.cookies.get(session_cookie_name)
            or request.request.query_params.get("job_id")
        )

        if not session_id:
            return (
                "Session ID was not found. Please go back and run search again.",
                make_empty_kg_evidence(),
                None,
                gr.update(selected="kg"),
            )

        payload = session_store.get(session_id)

        if payload is None or not isinstance(payload, dict):
            return (
                "No KG evidence was found. Please run search again.",
                make_empty_kg_evidence(),
                None,
                gr.update(selected="kg"),
            )

        kg_evidence = payload.get("kg_evidence", make_empty_kg_evidence())
        inchikeys = payload.get("kg_inchikeys", [])

        if not isinstance(kg_evidence, dict):
            kg_evidence = make_empty_kg_evidence()

        if not isinstance(inchikeys, list):
            inchikeys = []

        kg_json_file_path = _write_kg_json_file(kg_evidence)

        return (
            _format_kg_status(kg_evidence, inchikeys=inchikeys),
            kg_evidence,
            kg_json_file_path,
            gr.update(selected="kg"),
        )

    return _load_saved_kg_result
