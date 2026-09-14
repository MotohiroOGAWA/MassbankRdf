from __future__ import annotations

import json
from typing import Any

import pandas as pd


MAX_DISEASE_NAMES_FOR_LLM = 500
MAX_DISEASE_NAME_CHARS = 25_000
MAX_RELATED_DISEASES = 20

DISEASE_ALIASES = {
    "アルツハイマー": ("alzheimer",),
    "パーキンソン": ("parkinson",),
    "糖尿病": ("diabetes", "diabetic"),
    "がん": ("cancer", "carcinoma", "neoplasm", "tumor"),
    "癌": ("cancer", "carcinoma", "neoplasm", "tumor"),
}


def disease_inchikey_map(
    kg_evidence: dict[str, Any],
) -> dict[str, set[str]]:
    """Map each unique KG disease label to its connected InChIKeys."""
    result: dict[str, set[str]] = {}
    features = kg_evidence.get("features", []) if isinstance(kg_evidence, dict) else []
    for feature in features:
        if not isinstance(feature, dict) or not feature.get("inchikey"):
            continue
        inchikey = str(feature["inchikey"])
        entities = feature.get("entities", {})
        diseases = entities.get("diseases", {}) if isinstance(entities, dict) else {}
        groups = diseases.values() if isinstance(diseases, dict) else [diseases]
        for rows in groups:
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("label") or row.get("id") or "").strip()
                if name:
                    result.setdefault(name, set()).add(inchikey)
    return result


def local_related_disease_names(
    query: str,
    disease_names: list[str],
) -> list[str]:
    """Find direct and configured multilingual disease-name matches."""
    lowered = (query or "").strip().lower()
    terms = [lowered] if lowered else []
    for source, aliases in DISEASE_ALIASES.items():
        if source in query:
            terms.extend(aliases)
    terms = [term for term in terms if len(term) >= 3]
    return [
        name
        for name in disease_names
        if any(term in name.lower() or name.lower() in term for term in terms)
    ][:MAX_RELATED_DISEASES]


def select_related_disease_names(
    query: str,
    disease_names: list[str],
    llm_config: dict[str, Any],
) -> tuple[list[str], str]:
    """Select only names from the result's disease vocabulary."""
    local = local_related_disease_names(query, disease_names)
    required = ("endpoint", "api_key", "deployment")
    if local:
        return local, "Related disease names were selected by exact/alias matching."
    if not all(str(llm_config.get(key, "")).strip() for key in required):
        return [], "No direct disease-name match was found and LLM settings are incomplete."
    if (
        len(disease_names) > MAX_DISEASE_NAMES_FOR_LLM
        or len(json.dumps(disease_names, ensure_ascii=False))
        > MAX_DISEASE_NAME_CHARS
    ):
        raise ValueError(
            "The unique disease-name vocabulary is too large for bounded LLM selection."
        )

    from openai import AzureOpenAI

    client = AzureOpenAI(
        azure_endpoint=str(llm_config["endpoint"]),
        api_key=str(llm_config["api_key"]),
        api_version=str(llm_config.get("api_version", "2024-10-21")),
    )
    completion = client.chat.completions.create(
        model=str(llm_config["deployment"]),
        messages=[
            {
                "role": "system",
                "content": (
                    "Select disease names related to the user's term. You may "
                    "select only exact strings from the supplied vocabulary. "
                    "Return JSON only: {\"diseases\": [..]}. Select at most 20. "
                    "Return an empty list when none are related."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"query": query, "disease_vocabulary": disease_names},
                    ensure_ascii=False,
                ),
            },
        ],
        response_format={"type": "json_object"},
        max_tokens=500,
        temperature=0,
    )
    content = completion.choices[0].message.content or "{}"
    selected = json.loads(content).get("diseases", [])
    allowed = set(disease_names)
    result = [
        str(name)
        for name in selected
        if str(name) in allowed
    ][:MAX_RELATED_DISEASES]
    return result, "Related disease names were selected by the bounded LLM vocabulary method."


def sample_classes_from_results(
    annotation_df: Any,
    candidate_df: Any,
) -> list[str]:
    values: list[str] = []
    for value in (annotation_df, candidate_df):
        frame = value if isinstance(value, pd.DataFrame) else pd.DataFrame(value or [])
        if "sample_class" in frame:
            values.extend(frame["sample_class"].dropna().astype(str).tolist())
    return sorted(set(values))


def _selected_candidates(candidate_df: Any) -> pd.DataFrame:
    frame = candidate_df if isinstance(candidate_df, pd.DataFrame) else pd.DataFrame(candidate_df)
    if frame.empty:
        return frame
    if "selected_for_kg" in frame:
        selected = frame["selected_for_kg"].apply(
            lambda value: value is True
            or str(value).strip().lower() in {"true", "1", "yes"}
        )
        frame = frame.loc[selected].copy()
    return frame.dropna(subset=["spectrum_uid", "sample_class", "inchikey"])


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    count = len(p_values)
    if not count:
        return []
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [1.0] * count
    running = 1.0
    for rank_index in range(count - 1, -1, -1):
        original_index = order[rank_index]
        rank = rank_index + 1
        running = min(running, p_values[original_index] * count / rank)
        adjusted[original_index] = min(1.0, running)
    return adjusted


def analyze_disease_class_enrichment(
    *,
    disease_names: list[str],
    target_class: str,
    disease_to_inchikeys: dict[str, set[str]],
    annotation_df: Any,
    candidate_df: Any,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Test spectrum-level disease associations in one class versus all others."""
    annotations = (
        annotation_df
        if isinstance(annotation_df, pd.DataFrame)
        else pd.DataFrame(annotation_df)
    )
    candidates = _selected_candidates(candidate_df)
    if annotations.empty or candidates.empty:
        return pd.DataFrame(), pd.DataFrame()
    canonical_classes = {
        value.lower(): value
        for value in annotations["sample_class"].dropna().astype(str).unique()
    }
    selected_class = canonical_classes.get((target_class or "").strip().lower())
    if not selected_class:
        raise ValueError(f"Sample class was not found: {target_class}")

    spectra = annotations[
        ["spectrum_uid", "source_file", "sample_class"]
    ].drop_duplicates("spectrum_uid")
    class_mask = spectra["sample_class"].astype(str) == selected_class
    class_total = int(class_mask.sum())
    other_total = int((~class_mask).sum())
    rows: list[dict[str, Any]] = []
    evidence_parts: list[pd.DataFrame] = []

    for disease_name in disease_names:
        keys = disease_to_inchikeys.get(disease_name, set())
        linked = candidates[candidates["inchikey"].astype(str).isin(keys)].copy()
        linked_spectra = set(linked["spectrum_uid"].astype(str))
        in_class = int(
            spectra.loc[class_mask, "spectrum_uid"].astype(str).isin(linked_spectra).sum()
        )
        outside = int(
            spectra.loc[~class_mask, "spectrum_uid"].astype(str).isin(linked_spectra).sum()
        )
        prevalence = in_class / class_total if class_total else 0.0
        other_prevalence = outside / other_total if other_total else 0.0
        enrichment = (
            prevalence / other_prevalence
            if other_prevalence
            else (float("inf") if prevalence else 0.0)
        )
        from scipy.stats import fisher_exact

        fisher = fisher_exact(
            [
                [in_class, max(0, class_total - in_class)],
                [outside, max(0, other_total - outside)],
            ]
        )
        rows.append(
            {
                "disease": disease_name,
                "sample_class": selected_class,
                "connected_inchikey_count": len(keys),
                "class_spectra": in_class,
                "class_total_spectra": class_total,
                "class_prevalence": prevalence,
                "other_spectra": outside,
                "other_total_spectra": other_total,
                "other_prevalence": other_prevalence,
                "enrichment_ratio": enrichment,
                "odds_ratio": float(fisher.statistic),
                "fisher_p_value": float(fisher.pvalue),
            }
        )
        if not linked.empty:
            linked.insert(0, "disease", disease_name)
            evidence_parts.append(linked)

    statistics = pd.DataFrame(rows)
    if statistics.empty:
        return statistics, pd.DataFrame()
    statistics["fdr_bh"] = benjamini_hochberg(
        statistics["fisher_p_value"].tolist()
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
    evidence = (
        pd.concat(evidence_parts, ignore_index=True)
        if evidence_parts
        else pd.DataFrame()
    )
    evidence_columns = [
        column
        for column in (
            "disease", "spectrum_uid", "source_file", "sample_class",
            "inchikey", "accession_id", "name", "score", "match",
            "kg_metadata_count", "combined_rank_sum",
        )
        if column in evidence
    ]
    return statistics, evidence[evidence_columns].drop_duplicates()
