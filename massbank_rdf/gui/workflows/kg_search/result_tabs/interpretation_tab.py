from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import gradio as gr

from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.services.llm_interpretation import (
    AzureOpenAIInterpretationConfig,
    AzureOpenAIInterpreter,
    build_kg_evidence_from_kg_data,
)


def make_empty_interpretation_json() -> dict[str, Any]:
    """Create empty interpretation JSON."""
    return {
        "metadata": {},
        "summary": None,
        "features": [],
        "failures": [],
    }


def _write_interpretation_json_file(
    interpretation_result: dict[str, Any],
) -> str:
    """Write interpretation result JSON file for download."""
    output_dir = Path(
        tempfile.mkdtemp(prefix="massbank_rdf_interpretation_")
    )

    output_path = output_dir / "llm_interpretation.json"

    output_path.write_text(
        json.dumps(
            interpretation_result,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return str(output_path)


def _format_status(
    interpretation_result: dict[str, Any],
) -> str:
    """Format interpretation status text."""
    metadata = interpretation_result.get("metadata", {})
    summary = interpretation_result.get("summary")
    failures = interpretation_result.get("failures", [])

    lines = [
        "LLM interpretation finished.",
        "",
        "[Metadata]",
        f"Deployment: {metadata.get('deployment', '-')}",
        f"API version: {metadata.get('api_version', '-')}",
        f"Feature count: {metadata.get('feature_count', '-')}",
        f"Succeeded: {metadata.get('succeeded', '-')}",
        f"Failed: {metadata.get('failed', '-')}",
        f"Total tokens: {metadata.get('usage_total', {}).get('total_tokens', '-')}",
    ]

    if summary:
        lines.extend(
            [
                "",
                "[Overall summary]",
                f"Overview: {summary.get('overview', '-')}",
            ]
        )

    if failures:
        lines.extend(
            [
                "",
                "[Failures]",
                *[
                    f"- {failure.get('inchikey')}: {failure.get('error')}"
                    for failure in failures
                ],
            ]
        )

    return "\n".join(lines)


def create_interpretation_tab() -> tuple[
    gr.Textbox,
    gr.JSON,
    gr.File,
]:
    """Create LLM interpretation tab."""
    status_text = gr.Textbox(
        label="LLM interpretation status",
        lines=12,
        interactive=False,
    )

    interpretation_json = gr.JSON(
        label="LLM interpretation JSON",
        value=make_empty_interpretation_json(),
    )

    interpretation_json_file = gr.File(
        label="Download interpretation JSON",
        interactive=False,
    )

    return (
        status_text,
        interpretation_json,
        interpretation_json_file,
    )


def build_interpretation_loader(
    session_store: TemporarySessionStore,
    *,
    session_cookie_name: str = "kg_session_id",
):
    """Build callback for LLM interpretation after KG lookup."""

    def _load_interpretation_result(
        request: gr.Request,
    ) -> tuple[
        str,
        dict[str, Any],
        str | None,
    ]:
        session_id = request.request.cookies.get(session_cookie_name)

        if not session_id:
            return (
                "Session ID was not found. Please go back and run search again.",
                make_empty_interpretation_json(),
                None,
                gr.update(selected="interpretation"),
            )

        payload = session_store.get(session_id)

        if payload is None or not isinstance(payload, dict):
            return (
                "No payload was found. Please run search again.",
                make_empty_interpretation_json(),
                None,
                gr.update(selected="interpretation"),
            )

        llm_config = payload.get("llm_config", {})

        if not isinstance(llm_config, dict):
            llm_config = {}

        if not llm_config.get("enabled", False):
            return (
                "LLM interpretation is disabled.",
                make_empty_interpretation_json(),
                None,
                gr.update(selected="interpretation"),
            )

        kg_evidence = payload.get("kg_evidence")
        kg_data = payload.get("kg_data", {})

        if not isinstance(kg_evidence, dict):
            if isinstance(kg_data, dict) and kg_data:
                kg_evidence = build_kg_evidence_from_kg_data(kg_data)
            else:
                return (
                    "No KG evidence was found. LLM interpretation was skipped.",
                    make_empty_interpretation_json(),
                    None,
                    gr.update(selected="interpretation"),
                )

        required_keys = [
            "endpoint",
            "api_key",
            "deployment",
        ]

        missing = [
            key
            for key in required_keys
            if not str(llm_config.get(key, "")).strip()
        ]

        if missing:
            return (
                f"LLM configuration is incomplete: {', '.join(missing)}",
                make_empty_interpretation_json(),
                None,
                gr.update(selected="interpretation"),
            )

        interpreter = AzureOpenAIInterpreter(
            AzureOpenAIInterpretationConfig(
                endpoint=str(llm_config["endpoint"]),
                api_key=str(llm_config["api_key"]),
                deployment=str(llm_config["deployment"]),
                api_version=str(
                    llm_config.get("api_version", "2024-10-21")
                ),
                output_language=str(
                    llm_config.get("output_language", "Japanese")
                ),
                user_context=str(
                    llm_config.get("user_context", "")
                ),
            )
        )

        interpretation_result = interpreter.interpret_kg_evidence(
            kg_evidence
        )

        payload["kg_evidence"] = kg_evidence
        payload["interpretation_result"] = interpretation_result
        session_store.set(session_id, payload)

        interpretation_file_path = _write_interpretation_json_file(
            interpretation_result
        )

        return (
            _format_status(interpretation_result),
            interpretation_result,
            interpretation_file_path,
            gr.update(selected="interpretation"),
        )

    return _load_interpretation_result