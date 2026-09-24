from __future__ import annotations

from typing import Any

import pandas as pd

from massbank_rdf.services.kg.common import extract_inchikey_value
from massbank_rdf.services.kg.metadata_score_service import KgMetadataScoreService


def filter_similarity_candidates(
    candidates: pd.DataFrame,
    minimum_similarity: float,
    *,
    score_column: str,
) -> pd.DataFrame:
    """Remove candidates at or below the configured similarity cutoff."""
    if candidates.empty or score_column not in candidates:
        return candidates.copy()
    scores = pd.to_numeric(candidates[score_column], errors="coerce")
    return candidates.loc[scores > float(minimum_similarity)].copy()


def rank_candidates_with_kg_metadata(
    candidates: pd.DataFrame,
    score_service: KgMetadataScoreService,
    *,
    score_column: str = "score",
    inchikey_column: str = "inchikey",
    use_kg_metadata_rank: bool = True,
) -> pd.DataFrame:
    """Rank candidates by similarity rank + KG metadata-count rank."""
    result = candidates.copy()
    if result.empty or score_column not in result or inchikey_column not in result:
        return result

    result["_normalized_inchikey"] = result[inchikey_column].apply(
        extract_inchikey_value
    )
    valid = result.dropna(subset=["_normalized_inchikey"]).copy()
    if valid.empty:
        result["massbank_similarity_rank"] = pd.NA
        result["kg_metadata_count"] = 0
        result["kg_metadata_rank"] = pd.NA
        result["combined_rank_sum"] = pd.NA
        result["combined_rank"] = pd.NA
        result["ranking_mode"] = (
            "massbank_similarity_plus_kg_metadata"
            if use_kg_metadata_rank
            else "massbank_similarity_only"
        )
        return result.drop(columns=["_normalized_inchikey"])

    by_key = (
        valid.groupby("_normalized_inchikey", sort=False)[score_column]
        .max()
        .rename("best_similarity")
        .reset_index()
    )
    by_key["massbank_similarity_rank"] = (
        pd.to_numeric(by_key["best_similarity"], errors="coerce")
        .rank(method="dense", ascending=False)
        .astype("Int64")
    )
    scores = score_service.scores_for_inchikeys(
        by_key["_normalized_inchikey"].tolist()
    ).rename(columns={"inchikey": "_normalized_inchikey"})
    by_key = by_key.merge(scores, on="_normalized_inchikey", how="left")
    count_columns = [
        column
        for column in scores.columns
        if column != "_normalized_inchikey"
    ]
    for column in count_columns:
        by_key[column] = (
            pd.to_numeric(by_key[column], errors="coerce").fillna(0).astype(int)
        )
    if "kg_metadata_count" not in by_key:
        by_key["kg_metadata_count"] = 0
    by_key["kg_metadata_rank"] = (
        by_key["kg_metadata_count"]
        .rank(method="dense", ascending=False)
        .astype("Int64")
    )
    by_key["combined_rank_sum"] = (
        by_key["massbank_similarity_rank"] + by_key["kg_metadata_rank"]
        if use_kg_metadata_rank
        else by_key["massbank_similarity_rank"]
    ).astype("Int64")
    by_key["ranking_mode"] = (
        "massbank_similarity_plus_kg_metadata"
        if use_kg_metadata_rank
        else "massbank_similarity_only"
    )
    by_key["combined_rank"] = (
        by_key["combined_rank_sum"]
        .rank(method="dense", ascending=True)
        .astype("Int64")
    )
    result = result.merge(
        by_key.drop(columns=["best_similarity"]),
        on="_normalized_inchikey",
        how="left",
    )
    for column in count_columns:
        result[column] = (
            pd.to_numeric(result[column], errors="coerce").fillna(0).astype(int)
        )
    result["kg_metadata_count"] = (
        pd.to_numeric(result["kg_metadata_count"], errors="coerce")
        .fillna(0)
        .astype(int)
    )
    sort_columns = ["combined_rank_sum", score_column]
    ascending = [True, False]
    if use_kg_metadata_rank:
        sort_columns.append("kg_metadata_count")
        ascending.append(False)
    result = result.sort_values(
        sort_columns,
        ascending=ascending,
        na_position="last",
        kind="stable",
    )
    return result.drop(columns=["_normalized_inchikey"]).reset_index(drop=True)


def rank_grouped_candidates_with_kg_metadata(
    candidates: pd.DataFrame,
    score_service: KgMetadataScoreService,
    *,
    group_column: str,
    score_column: str = "score",
    inchikey_column: str = "inchikey",
    use_kg_metadata_rank: bool = True,
) -> pd.DataFrame:
    """Rank every spectrum group with one batched KG-score lookup."""
    result = candidates.copy()
    required = {group_column, score_column, inchikey_column}
    if result.empty or not required.issubset(result.columns):
        return result

    result["_normalized_inchikey"] = result[inchikey_column].apply(
        extract_inchikey_value
    )
    valid = result.dropna(subset=["_normalized_inchikey"]).copy()
    if valid.empty:
        result["massbank_similarity_rank"] = pd.NA
        result["kg_metadata_count"] = 0
        result["kg_metadata_rank"] = pd.NA
        result["combined_rank_sum"] = pd.NA
        result["combined_rank"] = pd.NA
        result["ranking_mode"] = (
            "massbank_similarity_plus_kg_metadata"
            if use_kg_metadata_rank
            else "massbank_similarity_only"
        )
        return result.drop(columns=["_normalized_inchikey"])

    by_group_key = (
        valid.groupby(
            [group_column, "_normalized_inchikey"],
            sort=False,
            dropna=False,
        )[score_column]
        .max()
        .rename("best_similarity")
        .reset_index()
    )
    by_group_key["massbank_similarity_rank"] = (
        by_group_key.groupby(group_column)["best_similarity"]
        .rank(method="dense", ascending=False)
        .astype("Int64")
    )

    unique_keys = by_group_key["_normalized_inchikey"].drop_duplicates().tolist()
    scores = score_service.scores_for_inchikeys(unique_keys).rename(
        columns={"inchikey": "_normalized_inchikey"}
    )
    by_group_key = by_group_key.merge(
        scores,
        on="_normalized_inchikey",
        how="left",
    )
    score_columns = [
        column
        for column in scores.columns
        if column != "_normalized_inchikey"
    ]
    for column in score_columns:
        by_group_key[column] = (
            pd.to_numeric(by_group_key[column], errors="coerce")
            .fillna(0)
            .astype(int)
        )
    if "kg_metadata_count" not in by_group_key:
        by_group_key["kg_metadata_count"] = 0
    by_group_key["kg_metadata_rank"] = (
        by_group_key.groupby(group_column)["kg_metadata_count"]
        .rank(method="dense", ascending=False)
        .astype("Int64")
    )
    by_group_key["combined_rank_sum"] = (
        by_group_key["massbank_similarity_rank"]
        + by_group_key["kg_metadata_rank"]
        if use_kg_metadata_rank
        else by_group_key["massbank_similarity_rank"]
    ).astype("Int64")
    by_group_key["ranking_mode"] = (
        "massbank_similarity_plus_kg_metadata"
        if use_kg_metadata_rank
        else "massbank_similarity_only"
    )
    by_group_key["combined_rank"] = (
        by_group_key.groupby(group_column)["combined_rank_sum"]
        .rank(method="dense", ascending=True)
        .astype("Int64")
    )
    result = result.merge(
        by_group_key.drop(columns=["best_similarity"]),
        on=[group_column, "_normalized_inchikey"],
        how="left",
    )
    for column in score_columns:
        result[column] = (
            pd.to_numeric(result[column], errors="coerce").fillna(0).astype(int)
        )
    result["kg_metadata_count"] = (
        pd.to_numeric(result["kg_metadata_count"], errors="coerce")
        .fillna(0)
        .astype(int)
    )
    sort_columns = [
        column
        for column in [
            "msp_record_index",
            group_column,
            "combined_rank_sum",
            score_column,
            *(
                ["kg_metadata_count"]
                if use_kg_metadata_rank
                else []
            ),
        ]
        if column in result
    ]
    ascending = [
        column not in {score_column, "kg_metadata_count"}
        for column in sort_columns
    ]
    return (
        result.sort_values(
            sort_columns,
            ascending=ascending,
            na_position="last",
            kind="stable",
        )
        .drop(columns=["_normalized_inchikey"])
        .reset_index(drop=True)
    )
