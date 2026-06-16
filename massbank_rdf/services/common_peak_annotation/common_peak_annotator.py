from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from massbank_rdf.db.massbank.database import MassBankDatabase


def normalize_optional_positive_int(
    value: int | float | str | None,
) -> int | None:
    """Normalize optional positive integer.

    None, empty string, and '-' mean no limit.
    """
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()

        if value == "" or value == "-":
            return None

    try:
        number = int(value)
    except (TypeError, ValueError):
        return None

    if number <= 0:
        return None

    return number


def annotate_common_peaks_with_massbank(
    common_peaks_df: pd.DataFrame,
    *,
    mz_tolerance: float,
    common_peak_n: int,
    max_massbank_inchikey: int | None = None,
    massbank_top_n: int = 50,
    min_matched_peaks: int = 1,
    ion_mode: str | None = None,
    precursor_mz: float | None = None,
    precursor_tolerance: float | None = None,
) -> dict[str, pd.DataFrame]:
    """Annotate common peaks using MassBank search hits.

    MassBank search is performed using top common_peak_n common m/z values.
    The final annotation uses MassBank records limited by max_massbank_inchikey.
    """
    if common_peaks_df is None or common_peaks_df.empty:
        return {
            "selected_common_peaks": pd.DataFrame(),
            "massbank_hits": pd.DataFrame(),
            "peak_annotations": pd.DataFrame(),
        }

    selected_common_peaks = common_peaks_df.head(
        int(common_peak_n)
    ).copy()

    mz_list = selected_common_peaks["mz_mean"].astype(float).to_numpy()

    # Use commonness as pseudo intensity for MassBank cosine search.
    if "record_count" in selected_common_peaks.columns:
        intensity_list = selected_common_peaks["record_count"].astype(float).to_numpy()
    else:
        intensity_list = np.ones_like(mz_list, dtype=float)

    db = MassBankDatabase()

    massbank_hits = db.search_record_ids_by_cosine_similarity_sql(
        mz_list=mz_list,
        intensity_list=intensity_list,
        top_n=int(massbank_top_n),
        mz_tolerance=float(mz_tolerance),
        min_matched_peaks=int(min_matched_peaks),
        ion_mode=ion_mode,
        precursor_mz=precursor_mz,
        precursor_tolerance=precursor_tolerance,
    )

    if massbank_hits is None or massbank_hits.empty:
        return {
            "selected_common_peaks": selected_common_peaks,
            "massbank_hits": pd.DataFrame(),
            "peak_annotations": pd.DataFrame(),
        }

    massbank_hits = _attach_massbank_records(
        massbank_hits,
        db=db,
    )

    massbank_hits = _limit_hits_by_unique_inchikey(
        massbank_hits,
        max_massbank_inchikey=max_massbank_inchikey,
    )

    peak_annotations = _build_peak_annotations(
        selected_common_peaks=selected_common_peaks,
        massbank_hits=massbank_hits,
    )

    return {
        "selected_common_peaks": selected_common_peaks,
        "massbank_hits": massbank_hits,
        "peak_annotations": peak_annotations,
    }


def _attach_massbank_records(
    hit_df: pd.DataFrame,
    *,
    db: MassBankDatabase,
) -> pd.DataFrame:
    """Attach MassBank record metadata to hit DataFrame."""
    if hit_df.empty:
        return hit_df

    if "id" not in hit_df.columns:
        return hit_df

    record_ids = (
        hit_df["id"]
        .dropna()
        .astype(int)
        .tolist()
    )

    record_df = db.get_records_by_ids_dataframe(record_ids)

    if record_df.empty:
        return hit_df

    merged_df = hit_df.merge(
        record_df,
        on="id",
        how="left",
    )

    if "cosine_score" in merged_df.columns:
        merged_df["cosine_score"] = (
            pd.to_numeric(merged_df["cosine_score"], errors="coerce")
            .round(4)
        )

    if "matched_peak_count" in merged_df.columns:
        merged_df["matched_peak_count"] = (
            pd.to_numeric(merged_df["matched_peak_count"], errors="coerce")
            .astype("Int64")
        )

    merged_df = merged_df.rename(
        columns={
            "cosine_score": "score",
            "matched_peak_count": "match",
        }
    )

    hidden_columns = [
        "id",
        "record_id",
        "massbank_record_id",
        "dot_product",
        "reference_norm_square",
    ]

    merged_df = merged_df.drop(
        columns=[col for col in hidden_columns if col in merged_df.columns],
        errors="ignore",
    )

    first_columns = [
        "score",
        "match",
        "accession_id",
        "name",
        "inchikey",
        "smiles",
        "formula",
        "precursor_mz",
        "precursor_type",
        "ion_mode",
    ]

    ordered_columns: list[str] = []

    for column in first_columns:
        if column in merged_df.columns:
            ordered_columns.append(column)

    for column in merged_df.columns:
        if column not in ordered_columns:
            ordered_columns.append(column)

    return merged_df[ordered_columns]


def _limit_hits_by_unique_inchikey(
    hit_df: pd.DataFrame,
    *,
    max_massbank_inchikey: int | None,
) -> pd.DataFrame:
    """Limit MassBank hits by unique InChIKey while preserving hit order."""
    if hit_df.empty:
        return hit_df

    if max_massbank_inchikey is None:
        return hit_df

    if "inchikey" not in hit_df.columns:
        return hit_df.head(max_massbank_inchikey)

    selected_inchikeys: list[str] = []
    selected_indices: list[int] = []

    for index, row in hit_df.iterrows():
        inchikey = row.get("inchikey")

        if not inchikey:
            continue

        inchikey = str(inchikey)

        if inchikey not in selected_inchikeys:
            if len(selected_inchikeys) >= max_massbank_inchikey:
                break

            selected_inchikeys.append(inchikey)

        if inchikey in selected_inchikeys:
            selected_indices.append(index)

    return hit_df.loc[selected_indices].reset_index(drop=True)


def _build_peak_annotations(
    *,
    selected_common_peaks: pd.DataFrame,
    massbank_hits: pd.DataFrame,
) -> pd.DataFrame:
    """Build annotation table for common peaks.

    This version annotates each selected common peak with the candidate
    MassBank records that were hit by the selected common peak set.

    If later MassBank peak-level match details become available, this function
    can be extended to annotate per matched fragment peak more strictly.
    """
    if selected_common_peaks.empty or massbank_hits.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []

    for _, peak_row in selected_common_peaks.iterrows():
        for _, hit_row in massbank_hits.iterrows():
            rows.append(
                {
                    "common_rank": peak_row.get("common_rank"),
                    "common_peak_id": peak_row.get("common_peak_id"),
                    "mz_mean": peak_row.get("mz_mean"),
                    "record_count": peak_row.get("record_count"),
                    "peak_count": peak_row.get("peak_count"),
                    "massbank_score": hit_row.get("score"),
                    "massbank_match": hit_row.get("match"),
                    "accession_id": hit_row.get("accession_id"),
                    "name": hit_row.get("name"),
                    "inchikey": hit_row.get("inchikey"),
                    "formula": hit_row.get("formula"),
                    "precursor_mz": hit_row.get("precursor_mz"),
                    "precursor_type": hit_row.get("precursor_type"),
                    "ion_mode": hit_row.get("ion_mode"),
                }
            )

    return pd.DataFrame(rows)