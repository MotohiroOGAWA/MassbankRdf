from __future__ import annotations

from typing import Any

import pandas as pd
import gradio as gr

from massbank_rdf.gui.session_store import TemporarySessionStore


def _make_empty_result_dataframe() -> pd.DataFrame:
    """Create an empty result table."""
    return pd.DataFrame(
        columns=[
            "rank",
            "accession_id",
            "name",
            "formula",
            "precursor_mz",
            "ion_mode",
            "cosine_score",
            "matched_peak_count",
        ]
    )


def _format_summary(payload: dict[str, Any]) -> str:
    """Format a simple result summary."""
    summary = payload.get("summary", {})

    if not isinstance(summary, dict):
        summary = {}

    return (
        "Search result was loaded from the current browser session.\n\n"
        f"Peak count: {summary.get('peak_count', '-')}\n"
        f"Ion mode: {summary.get('ion_mode', '-')}\n"
        f"Precursor m/z: {summary.get('precursor_mz', '-')}\n"
    )


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