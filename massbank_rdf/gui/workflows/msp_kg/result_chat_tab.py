from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any

import gradio as gr
import pandas as pd

from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.services.disease_analysis import (
    analyze_disease_class_enrichment,
    benjamini_hochberg,
    disease_inchikey_map,
    sample_classes_from_results,
    select_related_disease_names,
)
from massbank_rdf.services.result_chat import (
    answer_result_chat,
    is_kg_count_question,
    retrieve_result_chat_evidence,
    summarize_kg_result_counts,
)
from massbank_rdf.services.metadata_enrichment import (
    METADATA_TYPES,
    analyze_all_metadata_enrichment,
)


def write_disease_analysis_tsvs(
    related: Any,
    statistics: Any,
    spectra: Any,
) -> tuple[str, str, str]:
    """Write every Disease Analysis result table as a downloadable TSV."""
    output_dir = Path(tempfile.mkdtemp(prefix="massbank_rdf_disease_analysis_"))
    tables = [
        (
            "related_diseases.tsv",
            related,
            ["disease", "connected_inchikey_count"],
        ),
        (
            "disease_class_enrichment.tsv",
            statistics,
            [
                "disease", "sample_class", "connected_inchikey_count",
                "class_spectra", "class_total_spectra", "class_prevalence",
                "other_spectra", "other_total_spectra", "other_prevalence",
                "enrichment_ratio", "odds_ratio", "fisher_p_value",
                "fdr_bh", "significant_in_class",
            ],
        ),
        (
            "disease_connected_spectra.tsv",
            spectra,
            [
                "disease", "spectrum_uid", "source_file", "sample_class",
                "inchikey", "accession_id", "name", "score", "match",
                "kg_metadata_count", "combined_rank_sum",
            ],
        ),
    ]
    paths = []
    for file_name, value, empty_columns in tables:
        frame = value if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
        if frame.empty and not len(frame.columns):
            frame = pd.DataFrame(columns=empty_columns)
        path = output_dir / file_name
        frame.to_csv(path, sep="\t", index=False)
        paths.append(str(path))
    return tuple(paths)


def write_metadata_enrichment_tsvs(
    all_tests: pd.DataFrame,
    significant_tests: pd.DataFrame,
    entity_links: pd.DataFrame,
) -> tuple[str, str, str]:
    """Write full metadata enrichment outputs as TSV files."""
    output_dir = Path(tempfile.mkdtemp(prefix="massbank_rdf_metadata_enrichment_"))
    tables = (
        ("all_metadata_enrichment_tests.tsv", all_tests),
        ("significant_metadata_enrichment.tsv", significant_tests),
        ("metadata_entity_inchikey_links.tsv", entity_links),
    )
    paths = []
    for file_name, frame in tables:
        path = output_dir / file_name
        frame.to_csv(path, sep="\t", index=False)
        paths.append(str(path))
    return tuple(paths)


def create_result_chat_tab():
    gr.Markdown(
        "Questions are answered from a bounded deterministic search of this "
        "result. Broad requests are refused before an LLM call."
    )
    with gr.Tabs():
        with gr.Tab("Free chat"):
            chatbot = gr.Chatbot(
                label="Ask your results", type="messages", height=480
            )
            question = gr.Textbox(
                label="Question",
                placeholder=(
                    "Example: How many KG features are in these results?"
                ),
                lines=2,
            )
            with gr.Row():
                send = gr.Button("Ask", variant="primary")
                clear = gr.Button("Clear")
            status = gr.Textbox(
                label="Retrieval / safety status", interactive=False
            )
            evidence = gr.Dataframe(
                label="Answer evidence", interactive=False, wrap=True
            )
        with gr.Tab("Disease Analysis"):
            gr.Markdown(
                "Select related names only from the diseases stored in this "
                "result, then test their spectrum-level enrichment in a "
                "sample class."
            )
            with gr.Row():
                disease_query = gr.Textbox(
                    label="Disease name or related term",
                    placeholder="Example: Alzheimer's disease",
                )
                disease_class = gr.Dropdown(
                    label="Sample class for significance analysis",
                    choices=[],
                    value=None,
                    allow_custom_value=False,
                )
            disease_run = gr.Button(
                "Find diseases and analyze class",
                variant="primary",
            )
            disease_status = gr.Textbox(
                label="Disease analysis status",
                interactive=False,
                lines=5,
            )
            related_diseases = gr.Dataframe(
                label="Related disease names in this KG result",
                interactive=False,
                wrap=True,
            )
            disease_statistics = gr.Dataframe(
                label="Sample-class disease enrichment",
                interactive=False,
                wrap=True,
            )
            disease_spectra = gr.Dataframe(
                label="Connected spectrum evidence",
                interactive=False,
                wrap=True,
            )
            with gr.Row():
                related_diseases_tsv = gr.File(
                    label="Download related diseases TSV",
                    interactive=False,
                )
                disease_statistics_tsv = gr.File(
                    label="Download enrichment TSV",
                    interactive=False,
                )
                disease_spectra_tsv = gr.File(
                    label="Download connected spectra TSV",
                    interactive=False,
                )
        with gr.Tab("Metadata Enrichment"):
            gr.Markdown(
                "Run spectrum-level Fisher enrichment tests for every KG "
                "metadata entity and selected sample class."
            )
            metadata_types = gr.CheckboxGroup(
                label="KG metadata types",
                choices=list(METADATA_TYPES),
                value=list(METADATA_TYPES),
            )
            metadata_class = gr.Dropdown(
                label="Sample classes",
                choices=[],
                value=None,
                allow_custom_value=False,
            )
            metadata_run = gr.Button(
                "Run all metadata enrichment tests",
                variant="primary",
            )
            metadata_status = gr.Textbox(
                label="Metadata enrichment status",
                interactive=False,
                lines=5,
            )
            metadata_significant = gr.Dataframe(
                label="Significant metadata results",
                interactive=False,
                wrap=True,
            )
            with gr.Row():
                metadata_all_tsv = gr.File(
                    label="Download all tests TSV",
                    interactive=False,
                )
                metadata_significant_tsv = gr.File(
                    label="Download significant results TSV",
                    interactive=False,
                )
                metadata_links_tsv = gr.File(
                    label="Download entity-InChIKey links TSV",
                    interactive=False,
                )
    scope = gr.State([])
    return (
        chatbot, question, send, clear, status, evidence, scope,
        disease_query, disease_class, disease_run, disease_status,
        related_diseases, disease_statistics, disease_spectra,
        related_diseases_tsv, disease_statistics_tsv, disease_spectra_tsv,
        metadata_types, metadata_class, metadata_run, metadata_status,
        metadata_significant, metadata_all_tsv, metadata_significant_tsv,
        metadata_links_tsv,
    )


def build_result_chat_handler(
    session_store: TemporarySessionStore,
    *,
    session_cookie_name: str,
):
    def ask(
        question: str,
        history: list[dict[str, Any]] | None,
        previous_scope: list[str] | None,
        request: gr.Request,
    ):
        history = list(history or [])
        session_id = (
            request.request.cookies.get(session_cookie_name)
            or request.request.query_params.get("job_id")
        )
        payload = session_store.get(session_id) if session_id else None
        if not isinstance(payload, dict):
            answer = "Result session was not found. Please run the workflow again."
            return history + [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ], "", answer, [], previous_scope or []

        if is_kg_count_question(question):
            counts = summarize_kg_result_counts(
                payload.get("kg_evidence", {}),
                payload.get("massbank_detail_df"),
                payload.get("spectrum_annotation_df"),
            )
            unique = counts["unique_entity_counts"]
            associations = counts["entity_association_counts"]
            answer = (
                f"KG features: {counts['kg_feature_count']:,}\n\n"
                f"Unique KG InChIKeys: {counts['unique_kg_inchikey_count']:,}\n\n"
                f"Unique entities: {unique}\n\n"
                f"Entity associations: {associations}\n\n"
                f"MassBank candidate rows: "
                f"{counts['massbank_candidate_rows']:,}\n\n"
                f"Input spectra: {counts['input_spectrum_count']:,}"
            )
            return history + [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ], "", "Method: summarize_kg_result_counts (LLM was not called).", [], previous_scope or []

        llm_config = payload.get("llm_config", {})
        if not isinstance(llm_config, dict) or not llm_config.get("enabled", False):
            answer = "LLM is disabled. Enable LLM on the input page and run the workflow."
            return history + [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ], "", answer, [], previous_scope or []

        retrieval = retrieve_result_chat_evidence(
            question,
            kg_evidence=payload.get("kg_evidence", {}),
            candidate_df=payload.get("massbank_detail_df"),
            previous_scope=previous_scope,
        )
        if not retrieval.accepted:
            answer = retrieval.message
        elif not retrieval.context.get("kg_features") and not retrieval.context.get(
            "massbank_candidates"
        ):
            answer = (
                "この結果内では、質問に一致するKGまたはMassBank候補の根拠を"
                "確認できませんでした。外部知識による推測は行っていません。"
            )
        else:
            try:
                answer = answer_result_chat(
                    llm_config=llm_config,
                    question=question,
                    context=retrieval.context,
                    history=history,
                )
            except Exception as exc:
                answer = f"LLM request failed: {exc}"

        updated = history + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
        return (
            updated,
            "",
            retrieval.message,
            retrieval.evidence_table,
            retrieval.scope_inchikeys or previous_scope or [],
        )

    return ask


def build_disease_options_loader(
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
            update = gr.update(choices=[], value=None)
            return update, update
        classes = sample_classes_from_results(
            payload.get("spectrum_annotation_df"),
            payload.get("massbank_detail_df"),
        )
        update = gr.update(
            choices=[("All sample classes", "__ALL__"), *classes],
            value="__ALL__",
        )
        return update, update

    return load


def build_disease_analysis_handler(
    session_store: TemporarySessionStore,
    *,
    session_cookie_name: str,
):
    def analyze(
        query: str,
        sample_class: str | None,
        request: gr.Request,
    ):
        def package(status: str, related: Any, statistics: Any, spectra: Any):
            paths = write_disease_analysis_tsvs(
                related,
                statistics,
                spectra,
            )
            return status, related, statistics, spectra, *paths

        session_id = (
            request.request.cookies.get(session_cookie_name)
            or request.request.query_params.get("job_id")
        )
        payload = session_store.get(session_id) if session_id else None
        if not isinstance(payload, dict):
            return package("Result session was not found.", [], [], [])
        query = (query or "").strip()
        if not query:
            return package("Enter a disease name or related term.", [], [], [])

        mapping = disease_inchikey_map(payload.get("kg_evidence", {}))
        if not mapping:
            return package(
                "No disease names were found in this KG result.", [], [], []
            )
        try:
            selected, method_status = select_related_disease_names(
                query,
                sorted(mapping),
                payload.get("llm_config", {}),
            )
        except Exception as exc:
            return package(
                f"Disease-name selection failed: {exc}", [], [], []
            )
        related_table = [
            {
                "disease": name,
                "connected_inchikey_count": len(mapping[name]),
            }
            for name in selected
        ]
        if not selected:
            return package(
                f"{method_status}\nNo related disease names were selected "
                "from this result.",
                related_table,
                [],
                [],
            )
        try:
            target_classes = (
                sample_classes_from_results(
                    payload.get("spectrum_annotation_df"),
                    payload.get("massbank_detail_df"),
                )
                if sample_class in (None, "", "__ALL__")
                else [str(sample_class)]
            )
            statistic_parts = []
            spectrum_parts = []
            for target in target_classes:
                class_statistics, class_spectra = analyze_disease_class_enrichment(
                    disease_names=selected,
                    target_class=target,
                    disease_to_inchikeys=mapping,
                    annotation_df=payload.get("spectrum_annotation_df"),
                    candidate_df=payload.get("massbank_detail_df"),
                )
                if not class_statistics.empty:
                    statistic_parts.append(class_statistics)
                if not class_spectra.empty:
                    spectrum_parts.append(class_spectra)
            statistics = (
                pd.concat(statistic_parts, ignore_index=True)
                if statistic_parts else pd.DataFrame()
            )
            spectra = (
                pd.concat(spectrum_parts, ignore_index=True).drop_duplicates()
                if spectrum_parts else pd.DataFrame()
            )
            if not statistics.empty:
                statistics["fdr_bh"] = benjamini_hochberg(
                    statistics["fisher_p_value"].astype(float).tolist()
                )
                statistics["significant_in_class"] = (
                    (statistics["fdr_bh"] < 0.05)
                    & (statistics["enrichment_ratio"] > 1)
                    & (statistics["class_spectra"] > 0)
                )
                statistics = statistics.sort_values(
                    ["significant_in_class", "fdr_bh", "enrichment_ratio"],
                    ascending=[False, True, False],
                )
        except Exception as exc:
            return package(
                f"Disease enrichment failed: {exc}",
                related_table,
                [],
                [],
            )
        significant = (
            statistics.loc[
                statistics["significant_in_class"],
                ["disease", "sample_class"],
            ].apply(
                lambda row: f"{row['disease']} [{row['sample_class']}]",
                axis=1,
            ).tolist()
            if not statistics.empty
            else []
        )
        analyzed_label = (
            "all sample classes"
            if sample_class in (None, "", "__ALL__")
            else str(sample_class)
        )
        conclusion = (
            f"Significant in {analyzed_label} "
            "(BH FDR < 0.05 and enrichment > 1): "
            + (", ".join(significant) if significant else "none")
        )
        return package(
            f"{method_status}\n{conclusion}\n"
            "These are KG disease associations of spectral annotation "
            "candidates, not directly observed diseases.",
            related_table,
            statistics,
            spectra,
        )

    return analyze


def build_metadata_enrichment_handler(
    session_store: TemporarySessionStore,
    *,
    session_cookie_name: str,
):
    def analyze(
        metadata_types: list[str] | None,
        sample_class: str | None,
        request: gr.Request,
    ):
        session_id = (
            request.request.cookies.get(session_cookie_name)
            or request.request.query_params.get("job_id")
        )
        payload = session_store.get(session_id) if session_id else None
        if not isinstance(payload, dict):
            return "Result session was not found.", [], None, None, None
        selected_types = [
            value for value in (metadata_types or [])
            if value in METADATA_TYPES
        ]
        if not selected_types:
            return "Select at least one KG metadata type.", [], None, None, None
        selected_classes = (
            None
            if sample_class in (None, "", "__ALL__")
            else [str(sample_class)]
        )
        try:
            all_tests, links = analyze_all_metadata_enrichment(
                kg_evidence=payload.get("kg_evidence", {}),
                annotation_df=payload.get("spectrum_annotation_df"),
                candidate_df=payload.get("massbank_detail_df"),
                metadata_types=selected_types,
                sample_classes=selected_classes,
            )
        except Exception as exc:
            return f"Metadata enrichment failed: {exc}", [], None, None, None
        significant = (
            all_tests[all_tests["significant_global"]].copy()
            if not all_tests.empty
            else pd.DataFrame(columns=all_tests.columns)
        )
        paths = write_metadata_enrichment_tsvs(
            all_tests,
            significant,
            links,
        )
        display = (
            significant.head(1_000)
            if not significant.empty
            else all_tests.head(1_000)
        )
        status = (
            f"Completed {len(all_tests):,} Fisher tests across "
            f"{all_tests['metadata_type'].nunique() if not all_tests.empty else 0:,} "
            f"metadata types. Global-FDR significant results: "
            f"{len(significant):,}. The browser table is limited to 1,000 rows; "
            "the TSV files contain all rows."
        )
        return status, display, *paths

    return analyze
