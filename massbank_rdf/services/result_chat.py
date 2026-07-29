from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd


MAX_QUESTION_CHARS = 500
MAX_FEATURES = 20
MAX_CANDIDATE_ROWS = 60
MAX_CONTEXT_CHARS = 30_000

BROAD_PATTERNS = (
    "全データ",
    "すべて解析",
    "全部解析",
    "網羅的",
    "分子ネットワークを作",
    "エンリッチメント解析を実行",
    "all data",
    "analyze everything",
    "comprehensive analysis",
)

TERM_ALIASES = {
    "アルツハイマー": ("alzheimer", "alzheimer's"),
    "パーキンソン": ("parkinson", "parkinson's"),
    "がん": ("cancer", "carcinoma", "tumor", "neoplasm"),
    "癌": ("cancer", "carcinoma", "tumor", "neoplasm"),
    "糖尿病": ("diabetes", "diabetic"),
}

ENGLISH_STOP_WORDS = {
    "about", "also", "among", "and", "are", "associated", "data", "does",
    "disease", "from", "have", "observed", "result", "results", "show", "that", "the",
    "these", "this", "what", "which", "with",
}


@dataclass(frozen=True)
class ResultChatRetrieval:
    """Bounded deterministic evidence selected for one chat turn."""

    accepted: bool
    message: str
    context: dict[str, Any]
    evidence_table: pd.DataFrame
    scope_inchikeys: list[str]


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str).lower()


def _query_terms(question: str) -> list[str]:
    normalized = question.lower()
    terms: list[str] = []
    for source, aliases in TERM_ALIASES.items():
        if source in normalized:
            terms.extend(aliases)
    for token in re.findall(r"[a-z][a-z0-9'_-]{1,}", normalized):
        if token not in ENGLISH_STOP_WORDS:
            terms.append(token)
    for token in re.findall(r"[A-Z]{14}-[A-Z]{10}-[A-Z]", question.upper()):
        terms.append(token.lower())
    return list(dict.fromkeys(terms))


def _candidate_records(candidate_df: Any) -> list[dict[str, Any]]:
    if candidate_df is None:
        return []
    frame = candidate_df if isinstance(candidate_df, pd.DataFrame) else pd.DataFrame(candidate_df)
    if frame.empty:
        return []
    return frame.where(pd.notnull(frame), None).to_dict(orient="records")


def retrieve_result_chat_evidence(
    question: str,
    *,
    kg_evidence: dict[str, Any],
    candidate_df: Any,
    previous_scope: list[str] | None = None,
) -> ResultChatRetrieval:
    """Select a small evidence set without asking an LLM to search the result."""
    question = (question or "").strip()
    empty_table = pd.DataFrame()
    if not question:
        return ResultChatRetrieval(False, "質問を入力してください。", {}, empty_table, [])
    if len(question) > MAX_QUESTION_CHARS:
        return ResultChatRetrieval(
            False,
            "質問が長すぎるため処理しません。対象の疾患、pathway、class、InChIKeyなどを1つに絞ってください。",
            {},
            empty_table,
            [],
        )
    lowered = question.lower()
    if any(pattern in lowered for pattern in BROAD_PATTERNS):
        return ResultChatRetrieval(
            False,
            "全結果をLLMへ渡す必要がある広範な解析は、トークン消費が大きいため実行しません。対象を1つの疾患、pathway、class、InChIKeyなどに絞ってください。",
            {},
            empty_table,
            [],
        )

    features = kg_evidence.get("features", []) if isinstance(kg_evidence, dict) else []
    features = [feature for feature in features if isinstance(feature, dict)]
    candidates = _candidate_records(candidate_df)
    terms = _query_terms(question)
    previous = set(previous_scope or [])
    follow_up_markers = (
        "その中", "それら", "その候補", "上記", "先ほど",
        "among them", "those", "these candidates",
    )
    use_previous_scope = bool(previous) and (
        not terms or any(marker in lowered for marker in follow_up_markers)
    )
    searchable_features = (
        [
            feature
            for feature in features
            if str(feature.get("inchikey")) in previous
        ]
        if use_previous_scope
        else features
    )
    searchable_candidates = (
        [
            row
            for row in candidates
            if str(row.get("inchikey")) in previous
        ]
        if use_previous_scope
        else candidates
    )

    matched_features = [
        feature
        for feature in searchable_features
        if terms and any(term in _json_text(feature) for term in terms)
    ]
    matched_candidates = [
        row
        for row in searchable_candidates
        if terms and any(term in _json_text(row) for term in terms)
    ]

    matched_keys = {
        str(feature.get("inchikey"))
        for feature in matched_features
        if feature.get("inchikey")
    }
    matched_keys.update(
        str(row.get("inchikey"))
        for row in matched_candidates
        if row.get("inchikey")
    )

    if not matched_keys and previous:
        matched_keys = previous
        matched_features = [
            feature
            for feature in features
            if str(feature.get("inchikey")) in matched_keys
        ]

    if not terms and not previous:
        return ResultChatRetrieval(
            False,
            "結果から決定論的に検索できる語を特定できませんでした。疾患名、pathway名、class名、MassBank accession、InChIKeyのいずれかを含めてください。",
            {},
            empty_table,
            [],
        )

    if matched_keys:
        matched_features = [
            feature
            for feature in features
            if str(feature.get("inchikey")) in matched_keys
        ]
        matched_candidates = [
            row for row in candidates if str(row.get("inchikey")) in matched_keys
        ]

    if not matched_features and not matched_candidates:
        context = {
            "question": question,
            "deterministic_search_terms": terms,
            "matched_features": [],
            "matched_massbank_candidates": [],
        }
        return ResultChatRetrieval(
            True,
            "一致する根拠はありませんでした。",
            context,
            empty_table,
            [],
        )

    if len(matched_features) > MAX_FEATURES or len(matched_candidates) > MAX_CANDIDATE_ROWS:
        return ResultChatRetrieval(
            False,
            (
                "該当範囲が広すぎるためLLMを呼び出しません "
                f"(KG features={len(matched_features)}, MassBank rows={len(matched_candidates)})。"
                "疾患名、class、InChIKeyなどでさらに絞ってください。"
            ),
            {},
            empty_table,
            sorted(matched_keys),
        )

    compact_rows = [
        {
            key: row.get(key)
            for key in (
                "inchikey", "accession_id", "name", "spectrum_uid",
                "source_file", "sample_class", "score", "match",
                "kg_metadata_count", "combined_rank_sum",
            )
            if key in row
        }
        for row in matched_candidates
    ]
    context = {
        "question": question,
        "deterministic_search_terms": terms,
        "kg_features": matched_features,
        "massbank_candidates": compact_rows,
        "important_note": (
            "A MassBank candidate is a spectral annotation candidate, not a "
            "confirmed compound identification."
        ),
    }
    if len(json.dumps(context, ensure_ascii=False, default=str)) > MAX_CONTEXT_CHARS:
        return ResultChatRetrieval(
            False,
            "抽出された根拠が大きすぎるためLLMを呼び出しません。対象をさらに絞ってください。",
            {},
            empty_table,
            sorted(matched_keys),
        )

    evidence_rows = [
        {
            "inchikey": row.get("inchikey"),
            "massbank_accession": row.get("accession_id"),
            "spectrum_uid": row.get("spectrum_uid"),
            "file": row.get("source_file"),
            "sample_class": row.get("sample_class"),
            "cosine_similarity": row.get("score"),
            "kg_metadata_count": row.get("kg_metadata_count"),
        }
        for row in compact_rows
    ]
    return ResultChatRetrieval(
        True,
        (
            f"Deterministic retrieval: {len(matched_features)} KG features, "
            f"{len(compact_rows)} MassBank candidate rows."
        ),
        context,
        pd.DataFrame(evidence_rows),
        sorted(matched_keys),
    )


def answer_result_chat(
    *,
    llm_config: dict[str, Any],
    question: str,
    context: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Ask Azure OpenAI to explain only the bounded retrieved evidence."""
    from openai import AzureOpenAI

    required = ("endpoint", "api_key", "deployment")
    missing = [key for key in required if not str(llm_config.get(key, "")).strip()]
    if missing:
        raise ValueError(f"LLM configuration is incomplete: {', '.join(missing)}")

    language = str(llm_config.get("output_language", "Japanese"))
    user_context = str(llm_config.get("user_context", ""))[:2_000]
    prior = (history or [])[-4:]
    prior_text = json.dumps(prior, ensure_ascii=False, default=str)
    if len(prior_text) > 6_000:
        prior_text = prior_text[-6_000:]

    system_prompt = f"""
You answer questions about one MassBank/KG workflow result.
Answer in {language}. Use only the supplied deterministic evidence.
Never claim confirmed compound identification from a spectral candidate.
Clearly distinguish observed input spectra, MassBank candidate annotations,
and KG associations. If evidence is empty, say that no matching association
was found in this result; do not use outside knowledge. Cite relevant
InChIKeys, accessions, files/classes, and scores present in the evidence.
Keep the answer concise. User analysis context: {user_context}
""".strip()
    user_prompt = (
        f"Conversation context:\n{prior_text}\n\n"
        f"Question:\n{question}\n\n"
        "Deterministically retrieved evidence:\n"
        + json.dumps(context, ensure_ascii=False, default=str)
    )
    client = AzureOpenAI(
        azure_endpoint=str(llm_config["endpoint"]),
        api_key=str(llm_config["api_key"]),
        api_version=str(llm_config.get("api_version", "2024-10-21")),
    )
    completion = client.chat.completions.create(
        model=str(llm_config["deployment"]),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=800,
        temperature=0,
    )
    answer = completion.choices[0].message.content
    if not answer:
        raise RuntimeError("The LLM returned an empty answer.")
    return answer
