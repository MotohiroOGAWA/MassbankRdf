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
from massbank_rdf.gui.workflows.msp_kg.result_chat_tab import (
    build_disease_analysis_handler,
    build_disease_options_loader,
    build_metadata_enrichment_handler,
    build_result_chat_handler,
    create_result_chat_tab,
)

def format_search_summary(payload: dict[str, Any]) -> str:
    """Format search condition summary."""
    summary = payload.get("summary", {})

    if not isinstance(summary, dict):
        summary = {}

    if summary.get("workflow") == "molecular_network":
        return (
            "MSP Molecular Network + KG\n"
            f"Readable spectra: {summary.get('readable_spectrum_count', '-')}\n"
            f"Clusters: {summary.get('cluster_count', '-')}\n"
            f"Clusters with MSP structure information: {summary.get('structure_annotated_cluster_count', '-')}\n"
            f"Common-peak MassBank candidates: {summary.get('common_peak_candidate_count', '-')}\n"
            f"Unique InChIKeys for KG: {summary.get('unique_kg_inchikey_count', '-')}\n"
            "Clustering: connected components, then Score-weighted Leiden.\n"
            "Primary annotation: existing MSP names and structure IDs.\n"
            "MassBank is searched only for cluster common peaks."
        )

    msp_header = ""
    if summary.get("workflow") in {"msp_kg", "molecular_network"}:
        msp_header = (
            "[MSP batch]\n"
            f"Records: {summary.get('record_count', '-')}\n"
            f"Readable spectra: {summary.get('readable_spectrum_count', '-')}\n"
            f"Skipped records: {summary.get('skipped_record_count', '-')}\n"
            f"Spectra with InChIKey annotation: "
            f"{summary.get('annotated_spectrum_count', '-')}\n"
            f"MassBank candidates: {summary.get('massbank_candidate_count', '-')}\n"
            f"Unique InChIKeys for KG: "
            f"{summary.get('unique_kg_inchikey_count', '-')}\n\n"
        )

    input_peak_summary = ""
    if summary.get("workflow") not in {"msp_kg", "molecular_network"}:
        input_peak_summary = (
            "[Input peaks]\n"
            f"Peak count: {summary.get('peak_count', '-')}\n"
            f"Min m/z: {summary.get('min_mz', '-')}\n"
            f"Max m/z: {summary.get('max_mz', '-')}\n"
            f"Max intensity: {summary.get('max_intensity', '-')}\n\n"
        )

    spectrum_filter_summary = (
        f"Precursor m/z filter: "
        f"{'enabled' if summary.get('use_precursor_mz', True) else 'disabled'}\n"
        f"Precursor m/z MSP column: "
        f"{summary.get('precursor_mz_column', 'PRECURSORMZ')}\n"
        f"Precursor tolerance: {summary.get('precursor_tolerance', '-')}\n"
        f"Ion mode filter: "
        f"{'enabled' if summary.get('use_ion_mode', True) else 'disabled'}\n"
        f"Ion mode MSP column: {summary.get('ion_mode_column', 'IONMODE')}\n"
        if summary.get("workflow") in {"msp_kg", "molecular_network"}
        else (
            f"Ion mode: {summary.get('ion_mode', '-')}\n"
            f"Precursor m/z: {summary.get('precursor_mz', '-')}\n"
            f"Precursor tolerance: {summary.get('precursor_tolerance', '-')}\n"
        )
    )

    return (
        "Search result was loaded from the current browser session.\n\n"
        f"{msp_header}"
        f"{input_peak_summary}"
        "[Search conditions]\n"
        f"Top N: {summary.get('top_n', '-')}\n"
        f"m/z tolerance: {summary.get('mz_tolerance', '-')}\n"
        f"Min matched peaks: {summary.get('min_matched_peaks', '-')}\n"
        f"Minimum cosine similarity: {summary.get('minimum_similarity', '-')}\n"
        f"KG metadata rank: "
        f"{'enabled' if summary.get('use_kg_metadata_rank', True) else 'disabled'}\n"
        f"{spectrum_filter_summary}"
        f"Max MassBank InChIKey for KG: {summary.get('max_massbank_inchikey', '-')}\n"
        f"KG InChIKey matching: "
        f"{'short (connectivity)' if summary.get('use_short_inchikey', False) else 'full'}\n"
    )


def build_summary_loader(
    session_store: TemporarySessionStore,
    *,
    session_cookie_name: str = "kg_session_id",
):
    """Build callback for loading search summary."""

    def _load_search_summary(
        request: gr.Request,
    ) -> str:
        session_id = (
            request.request.cookies.get(session_cookie_name)
            or request.request.query_params.get("job_id")
        )

        if not session_id:
            return "Session ID was not found. Please go back and run search again."

        payload = session_store.get(session_id)

        if payload is None:
            return "No result was found. Please go back and run search again."

        if not isinstance(payload, dict):
            return f"Unexpected payload type: {type(payload).__name__}"

        return format_search_summary(payload)

    return _load_search_summary


def build_class_analysis_loader(
    session_store: TemporarySessionStore,
    *,
    session_cookie_name: str,
):
    def load(request: gr.Request):
        session_id = (
            request.request.cookies.get(session_cookie_name)
            or request.request.query_params.get("job_id")
        )
        payload = session_store.get(session_id) if session_id else None
        if not isinstance(payload, dict):
            return []
        return payload.get("class_analysis_df", [])

    return load


def build_output_archive_loader(
    session_store: TemporarySessionStore,
    *,
    session_cookie_name: str,
):
    def load(request: gr.Request):
        session_id = (
            request.request.cookies.get(session_cookie_name)
            or request.request.query_params.get("job_id")
        )
        payload = session_store.get(session_id) if session_id else None
        if not isinstance(payload, dict):
            return "Output archive was not found.", None
        archive = payload.get("output_archive")
        if not archive:
            return "This workflow did not create an output archive.", None
        return (
            "Download the ZIP and save/extract it in the desired folder on your PC.",
            archive,
        )

    return load


def build_network_result_loader(
    session_store: TemporarySessionStore,
    *,
    session_cookie_name: str,
):
    def load(request: gr.Request):
        session_id = (
            request.request.cookies.get(session_cookie_name)
            or request.request.query_params.get("job_id")
        )
        payload = session_store.get(session_id) if session_id else None
        if not isinstance(payload, dict):
            return [], [], []
        return (
            payload.get("network_statistics_df", []),
            payload.get("network_nodes_df", []),
            payload.get("network_edges_df", []),
        )

    return load


def create_app(
    session_store: TemporarySessionStore,
    kg_lookup_service: Any | None = None,
    *,
    session_cookie_name: str = "kg_session_id",
    workflow_title: str = "Knowledge Graph Search",
    input_path: str = "/kg/input/",
    preload_fn: Any | None = None,
) -> gr.Blocks:
    """Create KG search result page with separated result tabs."""

    load_search_summary = build_summary_loader(
        session_store=session_store,
        session_cookie_name=session_cookie_name,
    )

    load_massbank_result = build_massbank_loader(
        session_store=session_store,
        session_cookie_name=session_cookie_name,
    )

    load_sparql_result = build_sparql_loader(
        session_store=session_store,
        kg_lookup_service=kg_lookup_service,
        fallback_max_massbank_inchikey=None,
        limit=100,
        session_cookie_name=session_cookie_name,
    )

    load_kg_display_result = build_kg_display_loader(
        session_store=session_store,
        session_cookie_name=session_cookie_name,
    )

    load_interpretation_result = build_interpretation_loader(
        session_store=session_store,
        session_cookie_name=session_cookie_name,
    )
    load_class_analysis = build_class_analysis_loader(
        session_store,
        session_cookie_name=session_cookie_name,
    )
    load_output_archive = build_output_archive_loader(
        session_store,
        session_cookie_name=session_cookie_name,
    )
    is_msp_workflow = session_cookie_name == "msp_kg_session_id"
    is_batch_workflow = preload_fn is not None
    is_network_workflow = session_cookie_name == "molecular_network_session_id"
    load_network_result = (
        build_network_result_loader(
            session_store, session_cookie_name=session_cookie_name
        )
        if is_network_workflow
        else None
    )
    ask_result = (
        build_result_chat_handler(
            session_store,
            session_cookie_name=session_cookie_name,
        )
        if is_msp_workflow
        else None
    )
    load_disease_options = (
        build_disease_options_loader(
            session_store,
            session_cookie_name=session_cookie_name,
        )
        if is_msp_workflow
        else None
    )
    analyze_diseases = (
        build_disease_analysis_handler(
            session_store,
            session_cookie_name=session_cookie_name,
        )
        if is_msp_workflow
        else None
    )
    analyze_metadata = (
        build_metadata_enrichment_handler(
            session_store,
            session_cookie_name=session_cookie_name,
        )
        if is_msp_workflow
        else None
    )

    def load_massbank_without_tab_switch(request: gr.Request):
        table, _ = load_massbank_result(request)
        return table, gr.update()

    def load_sparql_without_tab_switch(request: gr.Request):
        values = list(load_sparql_result(request))
        values[-1] = gr.update()
        return tuple(values)

    def load_kg_without_tab_switch(request: gr.Request):
        values = list(load_kg_display_result(request))
        values[-1] = gr.update()
        return tuple(values)

    def verify_processing_completed(request: gr.Request) -> str:
        session_id = (
            request.request.cookies.get(session_cookie_name)
            or request.request.query_params.get("job_id")
        )
        payload = session_store.get(session_id) if session_id else None
        if not isinstance(payload, dict) or not payload.get("kg_precomputed"):
            raise gr.Error(
                "Batch processing is not complete. Result tabs were not loaded."
            )
        if is_batch_workflow and not payload.get("output_archive"):
            raise gr.Error(
                "Batch processing finished without an output archive."
            )
        return "Finished."

    with gr.Blocks(title=f"{workflow_title} - Result") as app:
        with gr.Group(elem_classes="massbank-page massbank-kg-result-page"):
            gr.HTML(
                """
                <div class="massbank-link-nav">
                    <a href="/">Home</a>
                    <span>/</span>
                    <a href="{input_path}">{workflow_title}</a>
                    <span>/</span>
                    <span>Result</span>
                </div>

                <section class="massbank-page-heading">
                    <h1>Search Result</h1>
                    <p>
                        Annotations, generated SPARQL queries, and
                        knowledge graph results are shown in separate tabs.
                    </p>
                </section>
                """.format(input_path=input_path, workflow_title=workflow_title)
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
            if is_network_workflow:
                from massbank_rdf.gui.workflows.molecular_network.processor import StageProgress

                _, initial_progress = StageProgress().update("input", 0, "Waiting")
            else:
                initial_progress = (
                    '<div style="display:flex;align-items:center;gap:12px;">'
                    '<progress style="width:100%;height:24px;" '
                    'value="0" max="100"></progress><strong>0.0%</strong></div>'
                )
            progress_bar = gr.HTML(initial_progress)

            with gr.Tabs(selected="massbank") as result_tabs:
                with gr.Tab("Cluster annotations" if is_network_workflow else "MassBank", id="massbank"):
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
                        kg_evidence_json,
                        kg_json_file,
                    ) = create_kg_tab()

                with gr.Tab("Class Analysis", id="class-analysis"):
                    class_analysis_table = gr.Dataframe(
                        label="Class-specific InChIKey / KG analysis",
                        interactive=False,
                        wrap=True,
                    )

                with gr.Tab("Output", id="output"):
                    output_status = gr.Textbox(
                        label="Local PC output",
                        interactive=False,
                    )
                    output_archive = gr.File(
                        label="Download all results (ZIP)",
                        interactive=False,
                    )

                if is_network_workflow:
                    with gr.Tab("Network conditions", id="network-conditions"):
                        network_statistics = gr.Dataframe(
                            label="Network condition comparison",
                            interactive=False,
                            wrap=True,
                        )
                    with gr.Tab("Cytoscape nodes", id="cytoscape-nodes"):
                        network_nodes = gr.Dataframe(
                            label="node.tsv preview",
                            interactive=False,
                            wrap=True,
                        )
                    with gr.Tab("Cytoscape edges", id="cytoscape-edges"):
                        network_edges = gr.Dataframe(
                            label="edge.tsv preview",
                            interactive=False,
                            wrap=True,
                        )

                with gr.Tab("Interpretation", id="interpretation"):
                    (
                        interpretation_status_text,
                        interpretation_json,
                        interpretation_json_file,
                    ) = create_interpretation_tab()

                if is_msp_workflow:
                    with gr.Tab("Ask your results", id="result-chat"):
                        (
                            result_chatbot,
                            result_question,
                            result_send,
                            result_clear,
                            result_chat_status,
                            result_chat_evidence,
                            result_chat_scope,
                            disease_query,
                            disease_class,
                            disease_run,
                            disease_status,
                            related_diseases,
                            disease_statistics,
                            disease_spectra,
                            related_diseases_tsv,
                            disease_statistics_tsv,
                            disease_spectra_tsv,
                            metadata_types,
                            metadata_class,
                            metadata_run,
                            metadata_status,
                            metadata_significant,
                            metadata_all_tsv,
                            metadata_significant_tsv,
                            metadata_links_tsv,
                        ) = create_result_chat_tab()

            gr.HTML(
                """
                <div class="massbank-demo-box">
                    <a href="{input_path}">Back to input page</a>
                </div>
                """.format(input_path=input_path)
            )

            if is_batch_workflow:
                load_event = app.load(
                    fn=preload_fn,
                    inputs=[],
                    outputs=[progress_text, progress_bar],
                    show_progress="hidden",
                )
            else:
                load_event = app.load(
                    fn=lambda: "Loading saved search result...",
                    inputs=[],
                    outputs=progress_text,
                )

            result_load_event = load_event.success(
                fn=load_search_summary,
                inputs=[],
                outputs=summary_text,
                show_progress="hidden",
            ).success(
                fn=lambda: "Loading MassBank result...",
                inputs=[],
                outputs=progress_text,
                show_progress="hidden",
            ).success(
                fn=(
                    load_massbank_without_tab_switch
                    if is_batch_workflow
                    else load_massbank_result
                ),
                inputs=[],
                outputs=[
                    massbank_result_table,
                    result_tabs,
                ],
                show_progress="hidden",
            ).success(
                fn=lambda: "MassBank result loaded. Generating SPARQL queries...",
                inputs=[],
                outputs=progress_text,
                show_progress="hidden",
            ).success(
                fn=load_class_analysis,
                inputs=[],
                outputs=class_analysis_table,
                show_progress="hidden",
            ).success(
                fn=load_output_archive,
                inputs=[],
                outputs=[output_status, output_archive],
                show_progress="hidden",
            )
            if is_network_workflow:
                result_load_event = result_load_event.success(
                    fn=load_network_result,
                    inputs=[],
                    outputs=[
                        network_statistics,
                        network_nodes,
                        network_edges,
                    ],
                    show_progress="hidden",
                )
            result_load_event = result_load_event.success(
                fn=(
                    load_sparql_without_tab_switch
                    if is_batch_workflow
                    else load_sparql_result
                ),
                inputs=[],
                outputs=[
                    sparql_status_text,
                    pubchem_compound_query,
                    pubchem_pathway_query,
                    hmdb_query,
                    knapsack_activity_query,
                    result_tabs,
                ],
                show_progress="hidden",
            ).success(
                fn=lambda: "SPARQL queries generated. Loading KG result...",
                inputs=[],
                outputs=progress_text,
                show_progress="hidden",
            ).success(
                fn=(
                    load_kg_without_tab_switch
                    if is_batch_workflow
                    else load_kg_display_result
                ),
                inputs=[],
                outputs=[
                    kg_status_text,
                    kg_evidence_json,
                    kg_json_file,
                    result_tabs,
                ],
                show_progress="hidden",
            ).success(
                fn=lambda: "KG result loaded. Running LLM interpretation...",
                inputs=[],
                outputs=progress_text,
                show_progress="hidden",
            )

            if is_msp_workflow:
                result_load_event.success(
                    fn=lambda: (
                        "Interactive result chat is ready. Automatic full-result "
                        "LLM interpretation is skipped to limit token usage."
                    ),
                    inputs=[],
                    outputs=interpretation_status_text,
                    show_progress="hidden",
                ).success(
                    fn=load_disease_options,
                    inputs=[],
                    outputs=[disease_class, metadata_class],
                    show_progress="hidden",
                ).success(
                    fn=verify_processing_completed,
                    inputs=[],
                    outputs=progress_text,
                    show_progress="hidden",
                )
                result_send.click(
                    fn=ask_result,
                    inputs=[result_question, result_chatbot, result_chat_scope],
                    outputs=[
                        result_chatbot,
                        result_question,
                        result_chat_status,
                        result_chat_evidence,
                        result_chat_scope,
                    ],
                )
                result_question.submit(
                    fn=ask_result,
                    inputs=[result_question, result_chatbot, result_chat_scope],
                    outputs=[
                        result_chatbot,
                        result_question,
                        result_chat_status,
                        result_chat_evidence,
                        result_chat_scope,
                    ],
                )
                result_clear.click(
                    fn=lambda: ([], "", "", [], []),
                    inputs=[],
                    outputs=[
                        result_chatbot,
                        result_question,
                        result_chat_status,
                        result_chat_evidence,
                        result_chat_scope,
                    ],
                )
                disease_run.click(
                    fn=analyze_diseases,
                    inputs=[disease_query, disease_class],
                    outputs=[
                        disease_status,
                        related_diseases,
                        disease_statistics,
                        disease_spectra,
                        related_diseases_tsv,
                        disease_statistics_tsv,
                        disease_spectra_tsv,
                    ],
                )
                metadata_run.click(
                    fn=analyze_metadata,
                    inputs=[metadata_types, metadata_class],
                    outputs=[
                        metadata_status,
                        metadata_significant,
                        metadata_all_tsv,
                        metadata_significant_tsv,
                        metadata_links_tsv,
                    ],
                )
            else:
                result_load_event.success(
                    fn=load_interpretation_result,
                    inputs=[],
                    outputs=[
                        interpretation_status_text,
                        interpretation_json,
                        interpretation_json_file,
                        result_tabs,
                    ],
                ).success(
                    fn=verify_processing_completed,
                    inputs=[],
                    outputs=progress_text,
                )

    return app
