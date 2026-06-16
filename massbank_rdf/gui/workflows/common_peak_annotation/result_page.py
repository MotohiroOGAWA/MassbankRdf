from __future__ import annotations

from typing import Any

import gradio as gr

from ...session_store import TemporarySessionStore
from .result_tabs import (
    build_annotation_loader,
    build_common_peak_loader,
    build_massbank_hit_loader,
    create_annotation_tab,
    create_common_peak_tab,
    create_massbank_hit_tab,
)
from ..kg_search.result_tabs.sparql_tab import (
    build_sparql_loader,
    create_sparql_tab,
)
from ..kg_search.result_tabs.kg_tab import (
    build_kg_display_loader,
    create_kg_tab,
)
from ..kg_search.result_tabs.interpretation_tab import (
    build_interpretation_loader,
    create_interpretation_tab,
)


COMMON_PEAK_SESSION_COOKIE_NAME = "common_peak_session_id"


def create_app(
    session_store: TemporarySessionStore,
    kg_lookup_service: Any | None = None,
) -> gr.Blocks:
    """Create common peak annotation result page."""

    load_common_peaks = build_common_peak_loader(
        session_store=session_store,
        session_cookie_name=COMMON_PEAK_SESSION_COOKIE_NAME,
    )

    load_massbank_hits = build_massbank_hit_loader(
        session_store=session_store,
        session_cookie_name=COMMON_PEAK_SESSION_COOKIE_NAME,
    )

    load_annotations = build_annotation_loader(
        session_store=session_store,
        session_cookie_name=COMMON_PEAK_SESSION_COOKIE_NAME,
    )

    load_sparql_result = build_sparql_loader(
        session_store=session_store,
        kg_lookup_service=kg_lookup_service,
        fallback_max_massbank_inchikey=None,
        limit=100,
        session_cookie_name=COMMON_PEAK_SESSION_COOKIE_NAME,
    )

    load_kg_display_result = build_kg_display_loader(
        session_store=session_store,
        session_cookie_name=COMMON_PEAK_SESSION_COOKIE_NAME,
    )

    load_interpretation_result = build_interpretation_loader(
        session_store=session_store,
        session_cookie_name=COMMON_PEAK_SESSION_COOKIE_NAME,
    )

    with gr.Blocks(title="Common Peak Annotation - Result") as app:
        with gr.Group(elem_classes="massbank-page massbank-common-peak-result-page"):
            gr.HTML(
                """
                <div class="massbank-link-nav">
                    <a href="/">Home</a>
                    <span>/</span>
                    <a href="/common-peak/input/">Common Peak Annotation</a>
                    <span>/</span>
                    <span>Result</span>
                </div>

                <section class="massbank-page-heading">
                    <h1>Common Peak Annotation Result</h1>
                    <p>
                        Common m/z peaks across multiple records are annotated
                        using MassBank hits. The hit InChIKeys are then used
                        for SPARQL, KG, and LLM interpretation.
                    </p>
                </section>
                """
            )

            progress_text = gr.Textbox(
                label="Progress",
                value="Waiting...",
                lines=3,
                interactive=False,
            )

            status_text = gr.Textbox(
                label="Common peak annotation status",
                lines=12,
                interactive=False,
            )

            with gr.Tabs(selected="common_peaks") as result_tabs:
                with gr.Tab("Common Peaks", id="common_peaks"):
                    common_peak_table = create_common_peak_tab()

                with gr.Tab("MassBank Hits", id="massbank_hits"):
                    massbank_hit_table = create_massbank_hit_tab()

                with gr.Tab("Annotations", id="annotations"):
                    annotation_table = create_annotation_tab()

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
                    <a href="/common-peak/input/">Back to input page</a>
                </div>
                """
            )

            app.load(
                fn=lambda: "Detecting common peaks...",
                inputs=[],
                outputs=progress_text,
            ).then(
                fn=load_common_peaks,
                inputs=[],
                outputs=[
                    status_text,
                    common_peak_table,
                    result_tabs,
                ],
            ).then(
                fn=lambda: "Searching MassBank using common peaks...",
                inputs=[],
                outputs=progress_text,
            ).then(
                fn=load_massbank_hits,
                inputs=[],
                outputs=[
                    massbank_hit_table,
                    result_tabs,
                ],
            ).then(
                fn=lambda: "Loading common peak annotations...",
                inputs=[],
                outputs=progress_text,
            ).then(
                fn=load_annotations,
                inputs=[],
                outputs=[
                    annotation_table,
                    result_tabs,
                ],
            ).then(
                fn=lambda: "Generating SPARQL queries and running KG lookup...",
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
                fn=lambda: "Loading KG result...",
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
                fn=lambda: "Running LLM interpretation...",
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