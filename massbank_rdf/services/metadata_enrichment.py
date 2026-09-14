from __future__ import annotations

import json
from typing import Any

import pandas as pd
from scipy.stats import fisher_exact

from massbank_rdf.services.disease_analysis import benjamini_hochberg


METADATA_TYPES = (
    "compounds",
    "diseases",
    "pathways",
    "biospecimens",
    "organisms",
    "activities",
)


def _entity_label(row: dict[str, Any]) -> str:
    for key in (
        "label", "name", "accession", "id", "target_species",
        "category", "uri",
    ):
        value = row.get(key)
        if value not in (None, "", [], {}):
            if isinstance(value, list):
                return " | ".join(map(str, value))
            return str(value)
    return json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)


def extract_metadata_entities(
    kg_evidence: dict[str, Any],
    metadata_types: list[str] | None = None,
) -> tuple[dict[tuple[str, str, str], set[str]], pd.DataFrame]:
    """Extract unique source/entity records and their connected InChIKeys."""
    selected_types = set(metadata_types or METADATA_TYPES)
    entity_keys: dict[tuple[str, str, str], set[str]] = {}
    entity_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    features = kg_evidence.get("features", []) if isinstance(kg_evidence, dict) else []
    for feature in features:
        if not isinstance(feature, dict) or not feature.get("inchikey"):
            continue
        inchikey = str(feature["inchikey"])
        entities = feature.get("entities", {})
        if not isinstance(entities, dict):
            continue
        for metadata_type in selected_types:
            grouped = entities.get(metadata_type, {})
            grouped = grouped if isinstance(grouped, dict) else {"unknown": grouped}
            for source, rows in grouped.items():
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict) or not row:
                        continue
                    entity_json = json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    )
                    entity_id = json.dumps(
                        [metadata_type, str(source), entity_json],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    key = (metadata_type, str(source), entity_id)
                    entity_keys.setdefault(key, set()).add(inchikey)
                    entity_rows[key] = {
                        "metadata_type": metadata_type,
                        "source": str(source),
                        "entity_id": entity_id,
                        "entity_label": _entity_label(row),
                        "entity_json": entity_json,
                    }
    links = []
    for key, inchikeys in entity_keys.items():
        metadata = entity_rows[key]
        for inchikey in sorted(inchikeys):
            links.append({**metadata, "inchikey": inchikey})
    return entity_keys, pd.DataFrame(links)


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
    return frame.dropna(subset=["spectrum_uid", "inchikey"])


def analyze_all_metadata_enrichment(
    *,
    kg_evidence: dict[str, Any],
    annotation_df: Any,
    candidate_df: Any,
    metadata_types: list[str] | None = None,
    sample_classes: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run every selected entity × sample-class Fisher enrichment test."""
    annotations = (
        annotation_df
        if isinstance(annotation_df, pd.DataFrame)
        else pd.DataFrame(annotation_df)
    )
    candidates = _selected_candidates(candidate_df)
    entity_keys, links = extract_metadata_entities(kg_evidence, metadata_types)
    if annotations.empty or candidates.empty or not entity_keys:
        return pd.DataFrame(), links

    spectra = annotations[
        ["spectrum_uid", "source_file", "sample_class"]
    ].drop_duplicates("spectrum_uid")
    available_classes = sorted(
        spectra["sample_class"].dropna().astype(str).unique()
    )
    selected_classes = sample_classes or available_classes
    selected_classes = [
        sample_class
        for sample_class in selected_classes
        if sample_class in available_classes
    ]
    key_spectra = (
        candidates.groupby(candidates["inchikey"].astype(str))["spectrum_uid"]
        .agg(lambda values: set(values.astype(str)))
        .to_dict()
    )
    link_metadata = (
        links.drop_duplicates(
            ["metadata_type", "source", "entity_id"]
        ).set_index(["metadata_type", "source", "entity_id"])
    )
    rows: list[dict[str, Any]] = []

    for entity_key, inchikeys in entity_keys.items():
        linked_spectra: set[str] = set()
        for inchikey in inchikeys:
            linked_spectra.update(key_spectra.get(inchikey, set()))
        metadata = link_metadata.loc[entity_key].to_dict()
        for sample_class in selected_classes:
            class_mask = spectra["sample_class"].astype(str) == sample_class
            class_total = int(class_mask.sum())
            other_total = int((~class_mask).sum())
            in_class = int(
                spectra.loc[class_mask, "spectrum_uid"]
                .astype(str)
                .isin(linked_spectra)
                .sum()
            )
            outside = int(
                spectra.loc[~class_mask, "spectrum_uid"]
                .astype(str)
                .isin(linked_spectra)
                .sum()
            )
            prevalence = in_class / class_total if class_total else 0.0
            other_prevalence = outside / other_total if other_total else 0.0
            enrichment = (
                prevalence / other_prevalence
                if other_prevalence
                else (float("inf") if prevalence else 0.0)
            )
            fisher = fisher_exact(
                [
                    [in_class, max(0, class_total - in_class)],
                    [outside, max(0, other_total - outside)],
                ]
            )
            rows.append(
                {
                    "metadata_type": entity_key[0],
                    "source": entity_key[1],
                    "entity_id": entity_key[2],
                    "entity_label": metadata["entity_label"],
                    "entity_json": metadata["entity_json"],
                    "connected_inchikey_count": len(inchikeys),
                    "connected_spectrum_count": len(linked_spectra),
                    "sample_class": sample_class,
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

    result = pd.DataFrame(rows)
    if result.empty:
        return result, links
    result["fdr_bh_global"] = benjamini_hochberg(
        result["fisher_p_value"].tolist()
    )
    result["fdr_bh_by_metadata_type"] = 1.0
    for _, indexes in result.groupby("metadata_type").groups.items():
        index_list = list(indexes)
        result.loc[index_list, "fdr_bh_by_metadata_type"] = (
            benjamini_hochberg(
                result.loc[index_list, "fisher_p_value"].tolist()
            )
        )
    result["significant_global"] = (
        (result["fdr_bh_global"] < 0.05)
        & (result["enrichment_ratio"] > 1)
        & (result["class_spectra"] > 0)
    )
    result["significant_within_metadata_type"] = (
        (result["fdr_bh_by_metadata_type"] < 0.05)
        & (result["enrichment_ratio"] > 1)
        & (result["class_spectra"] > 0)
    )
    return result.sort_values(
        [
            "significant_global", "fdr_bh_global",
            "metadata_type", "enrichment_ratio",
        ],
        ascending=[False, True, True, False],
    ), links
