from __future__ import annotations

from typing import Any

import pandas as pd
import gradio as gr

from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.db.massbank.database import MassBankDatabase

def _make_empty_result_dataframe() -> pd.DataFrame:
    """Create an empty result table."""
    return pd.DataFrame(
        columns=[
            "score",
            "match",
            "accession_id",
            "name",
            "inchikey",
            "smiles",
            "formula",
            "precursor_mz",
            "precursor_type",
            "ion_mode",
            "ms_type",
            "collision_energy",
            "retention_time",
            "instrument_type",
            "ionization",
            "ionization_voltage",
            "fragmentation_mode",
            "ac_instrument",
            "splash",
        ]
    )


def _format_summary(payload: dict[str, Any]) -> str:
    """Format a simple result summary."""
    summary = payload.get("summary", {})

    if not isinstance(summary, dict):
        summary = {}

    return (
        "Search result was loaded from the current browser session.\n\n"
        "[Input peaks]\n"
        f"Peak count: {summary.get('peak_count', '-')}\n"
        f"Min m/z: {summary.get('min_mz', '-')}\n"
        f"Max m/z: {summary.get('max_mz', '-')}\n"
        f"Max intensity: {summary.get('max_intensity', '-')}\n\n"
        "[Search conditions]\n"
        f"Top N: {summary.get('top_n', '-')}\n"
        f"m/z tolerance: {summary.get('mz_tolerance', '-')}\n"
        f"Min matched peaks: {summary.get('min_matched_peaks', '-')}\n"
        f"Ion mode: {summary.get('ion_mode', '-')}\n"
        f"Precursor m/z: {summary.get('precursor_mz', '-')}\n"
        f"Precursor tolerance: {summary.get('precursor_tolerance', '-')}\n"
    )

def _format_result_dataframe(result_df: pd.DataFrame) -> pd.DataFrame:
    """Attach MassBank record information and format result table.

    Input result_df is expected to contain:
        id
        cosine_score
        matched_peak_count

    The local id is used only for joining and is not shown.
    """
    if result_df is None or result_df.empty:
        return _make_empty_result_dataframe()

    if "id" not in result_df.columns:
        return result_df

    score_df = result_df.copy()

    record_ids = (
        score_df["id"]
        .dropna()
        .astype(int)
        .tolist()
    )

    if not record_ids:
        return _make_empty_result_dataframe()

    db = MassBankDatabase()
    record_df = db.get_records_by_ids_dataframe(record_ids)

    if record_df.empty:
        return _make_empty_result_dataframe()

    merged_df = score_df.merge(
        record_df,
        on="id",
        how="left",
    )

    # Hide local/internal database IDs and debug columns.
    hidden_columns = {
        "id",
        "record_id",
        "massbank_record_id",
        "dot_product",
        "reference_norm_square",
    }

    merged_df = merged_df.drop(
        columns=[col for col in hidden_columns if col in merged_df.columns],
        errors="ignore",
    )

    # Format score columns for UI.
    if "cosine_score" in merged_df.columns:
        merged_df["cosine_score"] = (
            pd.to_numeric(merged_df["cosine_score"], errors="coerce")
            .round(3)
        )

    if "matched_peak_count" in merged_df.columns:
        merged_df["matched_peak_count"] = (
            pd.to_numeric(merged_df["matched_peak_count"], errors="coerce")
            .astype("Int64")
        )

    # Short display names for UI.
    merged_df = merged_df.rename(
        columns={
            "cosine_score": "score",
            "matched_peak_count": "match",
        }
    )

    first_columns = [
        "score",
        "match",
    ]

    record_columns = [
        "accession_id",
        "name",
        "inchikey",
        "smiles",
        "formula",
        "precursor_mz",
        "precursor_type",
        "ion_mode",
        "ms_type",
        "collision_energy",
        "retention_time",
        "instrument_type",
        "ionization",
        "ionization_voltage",
        "fragmentation_mode",
        "ac_instrument",
        "splash",
    ]

    ordered_columns: list[str] = []

    for col in first_columns:
        if col in merged_df.columns:
            ordered_columns.append(col)

    for col in record_columns:
        if col in merged_df.columns and col not in ordered_columns:
            ordered_columns.append(col)

    for col in merged_df.columns:
        if col not in ordered_columns:
            ordered_columns.append(col)

    return merged_df[ordered_columns]

def create_app(
    session_store: TemporarySessionStore,
) -> gr.Blocks:
    """Create the KG search result page."""

    def _load_result_from_session(
        request: gr.Request,
    ) -> tuple[str, pd.DataFrame]:
        """Load the latest result from temporary session store."""
        session_id = request.request.cookies.get("kg_session_id")

        if not session_id:
            return (
                "Session ID was not found. Please go back and run the search again.",
                _make_empty_result_dataframe(),
            )

        payload = session_store.get(session_id)

        if payload is None:
            return (
                "No result was found for this session. Please go back and run the search again.",
                _make_empty_result_dataframe(),
            )

        if not isinstance(payload, dict):
            return (
                f"Unexpected payload type: {type(payload).__name__}",
                _make_empty_result_dataframe(),
            )

        result_df = payload.get("result_df")

        if result_df is None:
            result_df = _make_empty_result_dataframe()
        elif not isinstance(result_df, pd.DataFrame):
            result_df = pd.DataFrame(result_df)

        result_df = _format_result_dataframe(result_df)

        summary_text = _format_summary(payload)
        summary_text += f"Results: {len(result_df)}"

        return summary_text, result_df

    with gr.Blocks(title="Knowledge Graph Search - Result") as app:
        with gr.Group(elem_classes="massbank-page massbank-kg-result-page"):
            gr.HTML(
                """
                <div class="massbank-link-nav">
                    <a href="/">Home</a>
                    <span>/</span>
                    <a href="/kg/input/">Knowledge Graph Search</a>
                    <span>/</span>
                    <span>Result</span>
                </div>

                <section class="massbank-page-heading">
                    <h1>Search Result</h1>
                    <p>
                        The result stored in the current browser session is shown here.
                    </p>
                </section>
                """
            )

            summary_text = gr.Textbox(
                label="Summary",
                lines=6,
                interactive=False,
            )

            result_table = gr.Dataframe(
                label="MassBank search results",
                value=_make_empty_result_dataframe(),
                interactive=False,
                wrap=True,
            )

            with gr.Row():
                gr.HTML(
                    """
                    <div class="massbank-demo-box">
                        <a href="/kg/input/">Back to input page</a>
                    </div>
                    """
                )

            app.load(
                fn=_load_result_from_session,
                inputs=[],
                outputs=[
                    summary_text,
                    result_table,
                ],
            )

    return app