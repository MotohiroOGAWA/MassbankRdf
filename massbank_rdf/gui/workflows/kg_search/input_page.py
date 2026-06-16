from __future__ import annotations

from typing import Any
from pathlib import Path

import gradio as gr
import numpy as np
import pandas as pd
import json

from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.db.massbank.database import MassBankDatabase


EXAMPLE_SEARCH_QUERY_PATH = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "single_record_peaks.json"
)

def _load_example_search_query() -> dict[str, Any]:
    """Load example search query JSON as dict."""
    with EXAMPLE_SEARCH_QUERY_PATH.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Example search query JSON must be an object.")

    return data


EXAMPLE_SEARCH_QUERY = _load_example_search_query()

def _peaks_to_text(peaks: list[dict[str, Any]]) -> str:
    """Convert peak objects to whitespace-separated mz intensity text."""
    lines: list[str] = []

    for index, peak in enumerate(peaks, start=1):
        if not isinstance(peak, dict):
            raise ValueError(f"Peak at index {index} must be an object.")

        if "mz" not in peak or "intensity" not in peak:
            raise ValueError(
                f"Peak at index {index} must contain 'mz' and 'intensity'."
            )

        lines.append(f"{peak['mz']} {peak['intensity']}")

    return "\n".join(lines)

def _load_example_search_query_values():
    """Return example values for Gradio input components."""
    data = EXAMPLE_SEARCH_QUERY

    peak_text = _peaks_to_text(data.get("peaks", []))

    return (
        peak_text,
        int(data.get("top_n", 10)),
        float(data.get("mz_tolerance", 0.01)),
        int(data.get("min_matched_peaks", 1)),
        data.get("ion_mode", ""),
        data.get("precursor_mz", None),
        data.get("precursor_tolerance", None),
        data.get("max_massbank_inchikey", None),
    )

EXAMPLE_PEAKS_TEXT = _peaks_to_text(EXAMPLE_SEARCH_QUERY.get("peaks", []))

def _parse_peak_text_to_numpy(text: str) -> np.ndarray:
    """Parse whitespace/tab-separated mz intensity text into a numpy array.

    Expected format:
        mz intensity
        mz intensity
        ...

    Returns
    -------
    np.ndarray
        Shape: [N, 2]
        Column 0: mz
        Column 1: intensity
    """
    if not text or not text.strip():
        raise gr.Error("Please paste peak text.")

    rows: list[list[float]] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()

        if not stripped:
            continue

        # Allow whitespace, tab, and comma-separated text.
        normalized = stripped.replace(",", " ")
        items = normalized.split()

        if len(items) < 2:
            raise gr.Error(
                f"Invalid peak line at line {line_number}.\n"
                f"Expected: mz intensity\n"
                f"Line: {line}"
            )

        try:
            mz = float(items[0])
            intensity = float(items[1])
        except ValueError as e:
            raise gr.Error(
                f"Failed to parse peak values at line {line_number}.\n"
                f"Expected numeric mz and intensity.\n"
                f"Line: {line}"
            ) from e

        rows.append([mz, intensity])

    if not rows:
        raise gr.Error("No valid peak rows were found.")

    peak_array = np.asarray(rows, dtype=np.float64)

    if peak_array.ndim != 2 or peak_array.shape[1] != 2:
        raise gr.Error(
            f"Invalid peak array shape: {peak_array.shape}. "
            "Expected shape is [N, 2]."
        )

    return peak_array


def _peak_array_to_dataframe(peak_array: np.ndarray) -> pd.DataFrame:
    """Convert peak numpy array to DataFrame for display."""
    return pd.DataFrame(
        {
            "peak_index": np.arange(len(peak_array), dtype=np.int64),
            "mz": peak_array[:, 0],
            "intensity": peak_array[:, 1],
        }
    )

def _normalize_ion_mode_for_db(ion_mode: str | None) -> str | None:
    """Convert UI ion mode label to database value."""
    if ion_mode is None:
        return None

    ion_mode = ion_mode.strip()

    if ion_mode == "":
        return None

    if ion_mode.lower() == "positive":
        return "POSITIVE"

    if ion_mode.lower() == "negative":
        return "NEGATIVE"

    return ion_mode

def _normalize_optional_positive_int(
    value: int | float | str | None,
) -> int | None:
    """Normalize optional positive integer value.

    None, empty string, or NaN-like values are treated as None.
    """
    if value is None:
        return None

    if isinstance(value, str) and not value.strip():
        return None

    try:
        number = int(value)
    except (TypeError, ValueError):
        return None

    if number <= 0:
        return None

    return number

def create_app(
    session_store: TemporarySessionStore,
) -> gr.Blocks:

    def _run_search_and_save_to_session(
        spectrum_text: str,
        top_n: int,
        mz_tolerance: float,
        min_matched_peaks: int,
        ion_mode: str,
        precursor_mz: float | None,
        precursor_tolerance: float | None,
        max_massbank_inchikey: int | float | None,
        llm_enabled: bool,
        llm_output_language: str,
        azure_openai_endpoint: str,
        azure_openai_deployment: str,
        azure_openai_api_version: str,
        azure_openai_api_key: str,
        llm_user_context: str,
        request: gr.Request,
    ) -> str:
        """Parse peak text, run MassBank search, and save result DataFrame."""
        session_id = request.request.cookies.get("kg_session_id")

        if not session_id:
            raise gr.Error("Session ID was not found. Please reload the page.")

        peak_array = _parse_peak_text_to_numpy(spectrum_text)

        mz_list = peak_array[:, 0]
        intensity_list = peak_array[:, 1]

        normalized_ion_mode = _normalize_ion_mode_for_db(ion_mode)
        normalized_max_massbank_inchikey = _normalize_optional_positive_int(
            max_massbank_inchikey
        )
        
        if precursor_mz is not None and precursor_tolerance is None:
            raise gr.Error(
                "Precursor tolerance is required when precursor m/z is specified."
            )

        db = MassBankDatabase()

        result_df = db.search_record_ids_by_cosine_similarity_sql(
            mz_list=mz_list,
            intensity_list=intensity_list,
            top_n=int(top_n),
            mz_tolerance=float(mz_tolerance),
            min_matched_peaks=int(min_matched_peaks),
            ion_mode=normalized_ion_mode,
            precursor_mz=precursor_mz,
            precursor_tolerance=precursor_tolerance,
        )


        payload = {
            "result_df": result_df,
            "summary": {
                "peak_count": int(len(peak_array)),
                "min_mz": float(peak_array[:, 0].min()),
                "max_mz": float(peak_array[:, 0].max()),
                "max_intensity": float(peak_array[:, 1].max()),
                "top_n": int(top_n),
                "mz_tolerance": float(mz_tolerance),
                "min_matched_peaks": int(min_matched_peaks),
                "ion_mode": normalized_ion_mode or "-",
                "precursor_mz": precursor_mz if precursor_mz is not None else "-",
                "precursor_tolerance": (
                    precursor_tolerance
                    if precursor_tolerance is not None
                    else "-"
                ),
                "max_massbank_inchikey": (
                    normalized_max_massbank_inchikey
                    if normalized_max_massbank_inchikey is not None
                    else "-"
                ),
            },
            "llm_config": {
                "enabled": bool(llm_enabled),
                "provider": "azure_openai",
                "endpoint": azure_openai_endpoint.strip(),
                "deployment": azure_openai_deployment.strip(),
                "api_version": azure_openai_api_version.strip() or "2024-10-21",
                "api_key": azure_openai_api_key.strip(),
                "output_language": llm_output_language or "Japanese",
                "user_context": llm_user_context or "",
            },
        }

        session_store.set(
            session_id=session_id,
            value=payload,
        )

        return "OK"

    with gr.Blocks(title="Knowledge Graph Search - Input") as app:
        with gr.Group(elem_classes="massbank-page massbank-kg-input-page"):
            gr.HTML(
                """
                <div class="massbank-link-nav">
                    <a href="/">Home</a>
                    <span>/</span>
                    <span>Knowledge Graph Search</span>
                </div>

                <section class="massbank-page-heading">
                    <h1>Knowledge Graph Search</h1>
                    <p>
                        Upload or paste peak data as whitespace-separated
                        m/z and intensity pairs.
                    </p>
                </section>
                """
            )

            with gr.Group(elem_classes="massbank-form-panel"):
                gr.HTML("<h3>Input Peaks</h3>")

                example_button = gr.Button(
                    "Load Example",
                    elem_id="massbank-example-button",
                )

                spectrum_text = gr.Textbox(
                    label="Peak text",
                    lines=16,
                    placeholder=EXAMPLE_PEAKS_TEXT,
                )

                gr.HTML("<h3>Search Conditions</h3>")

                with gr.Row():
                    top_n = gr.Number(
                        label="Top N",
                        value=10,
                        precision=0,
                        minimum=1,
                    )

                    mz_tolerance = gr.Number(
                        label="m/z tolerance",
                        value=0.01,
                        precision=None,
                        minimum=0,
                    )

                    min_matched_peaks = gr.Number(
                        label="Min matched peaks",
                        value=1,
                        precision=0,
                        minimum=1,
                    )

                with gr.Row():
                    ion_mode = gr.Dropdown(
                        label="Ion mode",
                        choices=[
                            "",
                            "Positive",
                            "Negative",
                        ],
                        value="",
                    )

                    precursor_mz = gr.Number(
                        label="Precursor m/z",
                        value=None,
                        precision=None,
                    )

                    precursor_tolerance = gr.Number(
                        label="Precursor tolerance",
                        value=None,
                        precision=None,
                        minimum=0,
                    )

                with gr.Row():
                    max_massbank_inchikey = gr.Number(
                        label="Max MassBank InChIKey for KG",
                        value=None,
                        precision=0,
                        minimum=1,
                        info=(
                            "Maximum number of unique MassBank InChIKeys used for KG lookup. "
                            "Blank means all unique InChIKeys."
                        ),
                    )



                gr.HTML("<h3>LLM Interpretation</h3>")

                with gr.Row():
                    llm_enabled = gr.Checkbox(
                        label="Run LLM interpretation after KG lookup",
                        value=False,
                    )

                    llm_output_language = gr.Dropdown(
                        label="Output language",
                        choices=[
                            "English",
                            "Japanese",
                        ],
                        value="English",
                    )

                with gr.Row():
                    azure_openai_endpoint = gr.Textbox(
                        label="Azure OpenAI endpoint",
                        placeholder="https://xxxxx.openai.azure.com/",
                    )

                    azure_openai_deployment = gr.Textbox(
                        label="Azure OpenAI deployment",
                        placeholder="gpt-4.1-mini",
                    )

                with gr.Row():
                    azure_openai_api_version = gr.Textbox(
                        label="Azure OpenAI API version",
                        value="2024-10-21",
                    )

                    azure_openai_api_key = gr.Textbox(
                        label="Azure OpenAI API key",
                        type="password",
                    )

                llm_user_context = gr.Textbox(
                    label="Interpretation context",
                    lines=5,
                    placeholder=(
                        "Example: This sample is from palm oil oxidation experiment. "
                        "Focus on odor-related metabolites and lipid oxidation."
                    ),
                )


                run_button = gr.Button(
                    "Run",
                    elem_id="massbank-basic-search-button",
                )

            status_box = gr.Textbox(
                visible=False,
            )

            example_button.click(
                fn=_load_example_search_query_values,
                inputs=[],
                outputs=[
                    spectrum_text,
                    top_n,
                    mz_tolerance,
                    min_matched_peaks,
                    ion_mode,
                    precursor_mz,
                    precursor_tolerance,
                    max_massbank_inchikey,
                ],
            )

            run_button.click(
                fn=_run_search_and_save_to_session,
                inputs=[
                    spectrum_text,
                    top_n,
                    mz_tolerance,
                    min_matched_peaks,
                    ion_mode,
                    precursor_mz,
                    precursor_tolerance,
                    max_massbank_inchikey,
                    llm_enabled,
                    llm_output_language,
                    azure_openai_endpoint,
                    azure_openai_deployment,
                    azure_openai_api_version,
                    azure_openai_api_key,
                    llm_user_context,
                ],
                outputs=status_box,
            ).then(
                fn=None,
                inputs=status_box,
                outputs=[],
                js="""
                (status) => {
                    if (status === "OK") {
                        window.location.href = "/kg/result/";
                    }
                }
                """,
            )

    return app