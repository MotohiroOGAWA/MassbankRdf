from __future__ import annotations

from typing import Any

import gradio as gr

from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.services.result_chat import (
    answer_result_chat,
    retrieve_result_chat_evidence,
)


def create_result_chat_tab():
    gr.Markdown(
        "Questions are answered from a bounded deterministic search of this "
        "result. Broad requests are refused before an LLM call."
    )
    chatbot = gr.Chatbot(label="Ask your results", type="messages", height=480)
    question = gr.Textbox(
        label="Question",
        placeholder=(
            "Example: Are any candidates associated with Alzheimer's disease "
            "observed in these results?"
        ),
        lines=2,
    )
    with gr.Row():
        send = gr.Button("Ask", variant="primary")
        clear = gr.Button("Clear")
    status = gr.Textbox(label="Retrieval / safety status", interactive=False)
    evidence = gr.Dataframe(label="Answer evidence", interactive=False, wrap=True)
    scope = gr.State([])
    return chatbot, question, send, clear, status, evidence, scope


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
