from __future__ import annotations

from typing import Any

import gradio as gr

from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.gui.workflows.kg_search.result_tabs.massbank_tab import (
    build_massbank_loader,
    create_massbank_tab,
)
from massbank_rdf.gui.workflows.kg_search.result_tabs.sparql_tab import (
    build_sparql_loader,
    create_sparql_tab,
)
from massbank_rdf.gui.workflows.kg_search.result_tabs.kg_tab import (
    build_kg_display_loader,
    create_kg_tab,
)
from massbank_rdf.gui.workflows.kg_search.result_tabs.interpretation_tab import (
    build_interpretation_loader,
    create_interpretation_tab,
)

def format_search_summary(payload: dict[str, Any]) -> str:
    """Format search condition summary."""
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
        f"Precursor tolerance: {summary.get('precursor_tolerance', '-')}"
    )


def build_summary_loader(
    session_store: TemporarySessionStore,
):
    """Build callback for loading search summary."""

    def _load_search_summary(
        request: gr.Request,
    ) -> str:
        session_id = request.request.cookies.get("kg_session_id")

        if not session_id:
            return "Session ID was not found. Please go back and run search again."

        payload = session_store.get(session_id)

        if payload is None:
            return "No result was found. Please go back and run search again."

        if not isinstance(payload, dict):
            return f"Unexpected payload type: {type(payload).__name__}"

        return format_search_summary(payload)

    return _load_search_summary


def create_app(
    session_store: TemporarySessionStore,
    kg_lookup_service: Any | None = None,
) -> gr.Blocks:
    """Create KG search result page with separated result tabs."""

    load_search_summary = build_summary_loader(
        session_store=session_store,
    )

    load_massbank_result = build_massbank_loader(
        session_store=session_store,
    )

    load_sparql_result = build_sparql_loader(
        session_store=session_store,
        kg_lookup_service=kg_lookup_service,
        kg_n=3,
        limit=100,
    )

    load_kg_display_result = build_kg_display_loader(
        session_store=session_store,
    )

    load_interpretation_result = build_interpretation_loader(
        session_store=session_store,
    )

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
                        MassBank results, generated SPARQL queries, and
                        knowledge graph results are shown in separated tabs.
                    </p>
                </section>
                """
            )

            summary_text = gr.Textbox(
                label="Search summary",
                lines=12,
                interactive=False,
            )

            progress_text = gr.Textbox(
                label="Progress",
                value="Loading search summary...",
                lines=3,
                interactive=False,
            )

            with gr.Tabs(selected="massbank") as result_tabs:
                with gr.Tab("MassBank", id="massbank"):
                    massbank_result_table = create_massbank_tab()

                with gr.Tab("SPARQL", id="sparql"):
                    (
                        sparql_status_text,
                        pubchem_compound_query,
                        pubchem_pathway_query,
                        hmdb_query,
                        knapsack_activity_query,
                    ) = create_sparql_tab()

                with gr.Tab("KG", id="kg"):
                    (
                        kg_status_text,
                        pubchem_compound_table,
                        pubchem_pathway_table,
                        hmdb_table,
                        knapsack_activity_table,
                        kg_json_file,
                        kg_csv_zip_file,
                    ) = create_kg_tab()

                with gr.Tab("Interpretation", id="interpretation"):
                    (
                        interpretation_status_text,
                        interpretation_json,
                        interpretation_json_file,
                    ) = create_interpretation_tab()

            gr.HTML(
                """
                <div class="massbank-demo-box">
                    <a href="/kg/input/">Back to input page</a>
                </div>
                """
            )

            app.load(
                fn=load_search_summary,
                inputs=[],
                outputs=summary_text,
            ).then(
                fn=lambda: "Loading MassBank result...",
                inputs=[],
                outputs=progress_text,
            ).then(
                fn=load_massbank_result,
                inputs=[],
                outputs=[
                    massbank_result_table,
                    result_tabs,
                ],
            ).then(
                fn=lambda: "MassBank result loaded. Generating SPARQL queries...",
                inputs=[],
                outputs=progress_text,
            ).then(
                fn=load_sparql_result,
                inputs=[],
                outputs=[
                    sparql_status_text,
                    pubchem_compound_query,
                    pubchem_pathway_query,
                    hmdb_query,
                    knapsack_activity_query,
                    result_tabs,
                ],
            ).then(
                fn=lambda: "SPARQL queries generated. Loading KG result...",
                inputs=[],
                outputs=progress_text,
            ).then(
                fn=load_kg_display_result,
                inputs=[],
                outputs=[
                    kg_status_text,
                    pubchem_compound_table,
                    pubchem_pathway_table,
                    hmdb_table,
                    knapsack_activity_table,
                    kg_json_file,
                    kg_csv_zip_file,
                    result_tabs,
                ],
            ).then(
                fn=lambda: "KG result loaded. Running LLM interpretation...",
                inputs=[],
                outputs=progress_text,
            ).then(
                fn=load_interpretation_result,
                inputs=[],
                outputs=[
                    interpretation_status_text,
                    interpretation_json,
                    interpretation_json_file,
                    result_tabs,
                ],
            ).then(
                fn=lambda: "Finished.",
                inputs=[],
                outputs=progress_text,
            )

    return app