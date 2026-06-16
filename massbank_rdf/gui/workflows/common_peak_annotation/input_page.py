from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gradio as gr

from ...session_store import TemporarySessionStore
from ..shared.llm_config_panel import (
    build_llm_config,
    create_llm_config_panel,
)
from ....services.common_peak_annotation.common_peak_annotator import (
    normalize_optional_positive_int,
)
from ..shared.llm_config_panel import (
    build_llm_config,
    create_llm_config_panel,
)

EXAMPLE_COMMON_PEAK_QUERY_PATH = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "common_peak_annotation_example.json"
)


def _load_example_common_peak_query() -> dict[str, Any]:
    """Load example common peak annotation query JSON."""
    if not EXAMPLE_COMMON_PEAK_QUERY_PATH.exists():
        raise FileNotFoundError(
            f"Example JSON was not found: {EXAMPLE_COMMON_PEAK_QUERY_PATH}"
        )

    with EXAMPLE_COMMON_PEAK_QUERY_PATH.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Example common peak query JSON must be an object.")

    return data


def _records_to_peak_text(
    records: list[dict[str, Any]],
) -> str:
    """Convert example records to peak text.

    A blank line separates records.
    Each peak line contains only:
        mz intensity
    """
    record_blocks: list[str] = []

    for record_index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(
                f"Record at index {record_index} must be an object."
            )

        peaks = record.get("peaks", [])

        if not isinstance(peaks, list):
            raise ValueError(
                f"Record at index {record_index} must contain a peaks list."
            )

        lines: list[str] = []

        for peak_index, peak in enumerate(peaks, start=1):
            if not isinstance(peak, dict):
                raise ValueError(
                    f"Peak at record {record_index}, peak {peak_index} "
                    "must be an object."
                )

            if "mz" not in peak or "intensity" not in peak:
                raise ValueError(
                    f"Peak at record {record_index}, peak {peak_index} "
                    "must contain 'mz' and 'intensity'."
                )

            lines.append(f"{peak['mz']} {peak['intensity']}")

        record_blocks.append("\n".join(lines))

    return "\n\n".join(record_blocks)


def _load_example_common_peak_values() -> tuple[
    str,
    float,
    int,
    int | None,
    int,
    int,
    str,
]:
    """Return example values for Gradio input components."""
    data = _load_example_common_peak_query()

    records = data.get("records", [])

    if not isinstance(records, list):
        raise gr.Error("Example JSON field 'records' must be a list.")

    peak_text = _records_to_peak_text(records)

    return (
        peak_text,
        float(data.get("mz_tolerance", 0.01)),
        int(data.get("common_peak_n", 10)),
        data.get("max_massbank_inchikey", None),
        int(data.get("massbank_top_n", 50)),
        int(data.get("min_matched_peaks", 1)),
        str(data.get("ion_mode", "")),
    )


def _normalize_ion_mode_for_db(
    ion_mode: str | None,
) -> str | None:
    """Normalize ion mode label for database search."""
    if ion_mode is None:
        return None

    value = ion_mode.strip()

    if not value:
        return None

    if value.lower() == "positive":
        return "POSITIVE"

    if value.lower() == "negative":
        return "NEGATIVE"

    return value


def _validate_peak_text(
    peak_text: str,
) -> None:
    """Validate peak text format.

    A blank line separates records.
    Each non-empty line must contain:
        mz intensity
    """
    if not peak_text or not peak_text.strip():
        raise gr.Error("Please paste peak text.")

    record_blocks = [
        block.strip()
        for block in peak_text.strip().split("\n\n")
        if block.strip()
    ]

    if not record_blocks:
        raise gr.Error("No records were found.")

    for record_index, block in enumerate(record_blocks, start=1):
        valid_peak_count = 0

        for line_index, line in enumerate(block.splitlines(), start=1):
            stripped = line.strip()

            if not stripped:
                continue

            items = stripped.replace(",", " ").split()

            if len(items) < 2:
                raise gr.Error(
                    f"Invalid peak line at record {record_index}, "
                    f"line {line_index}.\n"
                    "Expected: mz intensity\n"
                    f"Line: {line}"
                )

            try:
                float(items[0])
                float(items[1])
            except ValueError as e:
                raise gr.Error(
                    f"Failed to parse numeric peak values at record "
                    f"{record_index}, line {line_index}.\n"
                    "Expected: mz intensity\n"
                    f"Line: {line}"
                ) from e

            valid_peak_count += 1

        if valid_peak_count == 0:
            raise gr.Error(
                f"Record {record_index} does not contain any valid peaks."
            )


def create_app(
    session_store: TemporarySessionStore,
) -> gr.Blocks:
    """Create common peak annotation input page."""

    def _run_and_save(
        peak_text: str,
        mz_tolerance: float,
        common_peak_n: int,
        max_massbank_inchikey: int | float | None,
        massbank_top_n: int,
        min_matched_peaks: int,
        ion_mode: str,
        llm_enabled: bool,
        llm_output_language: str,
        azure_openai_endpoint: str,
        azure_openai_deployment: str,
        azure_openai_api_version: str,
        azure_openai_api_key: str,
        llm_user_context: str,
        request: gr.Request,
    ) -> str:
        session_id = request.request.cookies.get("common_peak_session_id")

        if not session_id:
            raise gr.Error("Session ID was not found.")

        _validate_peak_text(peak_text)

        max_massbank_inchikey_value = normalize_optional_positive_int(
            max_massbank_inchikey
        )

        normalized_ion_mode = _normalize_ion_mode_for_db(
            ion_mode
        )

        payload = {
            "input": {
                "peak_text": peak_text,
            },
            "summary": {
                "mz_tolerance": float(mz_tolerance),
                "common_peak_n": int(common_peak_n),
                "max_massbank_inchikey": (
                    max_massbank_inchikey_value
                    if max_massbank_inchikey_value is not None
                    else "-"
                ),
                "massbank_top_n": int(massbank_top_n),
                "min_matched_peaks": int(min_matched_peaks),
                "ion_mode": normalized_ion_mode or "-",
            },
            "llm_config": build_llm_config(
                enabled=llm_enabled,
                output_language=llm_output_language,
                azure_openai_endpoint=azure_openai_endpoint,
                azure_openai_deployment=azure_openai_deployment,
                azure_openai_api_version=azure_openai_api_version,
                azure_openai_api_key=azure_openai_api_key,
                user_context=llm_user_context,
            ),
        }

        session_store.set(
            session_id=session_id,
            value=payload,
        )

        return "OK"

    with gr.Blocks(title="Common Peak Annotation") as app:
        with gr.Group(elem_classes="massbank-page massbank-common-peak-page"):
            gr.HTML(
                """
                <div class="massbank-link-nav">
                    <a href="/">Home</a>
                    <span>/</span>
                    <span>Common Peak Annotation</span>
                </div>

                <section class="massbank-page-heading">
                    <h1>Common Peak Annotation</h1>
                    <p>
                        Extract common MS/MS product-ion peaks across multiple
                        records and annotate shared m/z values using MassBank
                        search hits.
                    </p>
                </section>
                """
            )
            
            example_button = gr.Button(
                "Load Example",
                elem_id="common-peak-example-button",
            )

            gr.HTML("<h3>Input records</h3>")

            peak_text = gr.Textbox(
                label="Peak text",
                lines=22,
                placeholder=(
                    "Input only mz and intensity.\n"
                    "A blank line separates records.\n\n"
                    "Example:\n"
                    "55.0524 21\n"
                    "67.01821 20\n"
                    "68.99649 29\n\n"
                    "55.0531 20\n"
                    "67.01736 20\n"
                    "68.99583 20"
                ),
            )

            gr.HTML("<h3>Common peak annotation conditions</h3>")

            with gr.Row():
                mz_tolerance = gr.Number(
                    label="m/z tolerance",
                    value=0.01,
                    precision=None,
                    minimum=0,
                )

                common_peak_n = gr.Number(
                    label="Common peak N",
                    value=10,
                    precision=0,
                    minimum=1,
                )

                max_massbank_inchikey = gr.Number(
                    label="Max MassBank InChIKey",
                    value=None,
                    precision=0,
                    minimum=1,
                    info="Blank means all unique InChIKeys from MassBank hits.",
                )

            with gr.Row():
                massbank_top_n = gr.Number(
                    label="MassBank top N",
                    value=50,
                    precision=0,
                    minimum=1,
                )

                min_matched_peaks = gr.Number(
                    label="Min matched peaks",
                    value=3,
                    precision=0,
                    minimum=1,
                )

                ion_mode = gr.Dropdown(
                    label="Ion mode",
                    choices=[
                        "",
                        "Positive",
                        "Negative",
                    ],
                    value="Positive",
                )

            llm_config_components = create_llm_config_panel()

            run_button = gr.Button(
                "Run Common Peak Annotation",
                elem_id="common-peak-run-button",
            )

            status_box = gr.Textbox(
                label="Status",
                visible=False,
            )

            example_button.click(
                fn=_load_example_common_peak_values,
                inputs=[],
                outputs=[
                    peak_text,
                    mz_tolerance,
                    common_peak_n,
                    max_massbank_inchikey,
                    massbank_top_n,
                    min_matched_peaks,
                    ion_mode,
                ],
            )

            run_button.click(
                fn=_run_and_save,
                inputs=[
                    peak_text,
                    mz_tolerance,
                    common_peak_n,
                    max_massbank_inchikey,
                    massbank_top_n,
                    min_matched_peaks,
                    ion_mode,
                    *llm_config_components.inputs,
                ],
                outputs=status_box,
            ).then(
                fn=None,
                inputs=status_box,
                outputs=[],
                js="""
                (status) => {
                    if (status === "OK") {
                        window.location.href = "/common-peak/result/";
                    }
                }
                """,
            )

    return app