from __future__ import annotations

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
    scope = gr.State([])
    return (
        chatbot, question, send, clear, status, evidence, scope,
        disease_query, disease_class, disease_run, disease_status,
        related_diseases, disease_statistics, disease_spectra,
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
            return gr.update(choices=[], value=None)
        classes = sample_classes_from_results(
            payload.get("spectrum_annotation_df"),
            payload.get("massbank_detail_df"),
        )
        return gr.update(
            choices=[("All sample classes", "__ALL__"), *classes],
            value="__ALL__",
        )

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
        session_id = (
            request.request.cookies.get(session_cookie_name)
            or request.request.query_params.get("job_id")
        )
        payload = session_store.get(session_id) if session_id else None
        if not isinstance(payload, dict):
            return "Result session was not found.", [], [], []
        query = (query or "").strip()
        if not query:
            return "Enter a disease name or related term.", [], [], []

        mapping = disease_inchikey_map(payload.get("kg_evidence", {}))
        if not mapping:
            return "No disease names were found in this KG result.", [], [], []
        try:
            selected, method_status = select_related_disease_names(
                query,
                sorted(mapping),
                payload.get("llm_config", {}),
            )
        except Exception as exc:
            return f"Disease-name selection failed: {exc}", [], [], []
        related_table = [
            {
                "disease": name,
                "connected_inchikey_count": len(mapping[name]),
            }
            for name in selected
        ]
        if not selected:
            return (
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
            return (
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
        return (
            f"{method_status}\n{conclusion}\n"
            "These are KG disease associations of spectral annotation "
            "candidates, not directly observed diseases.",
            related_table,
            statistics,
            spectra,
        )

    return analyze
