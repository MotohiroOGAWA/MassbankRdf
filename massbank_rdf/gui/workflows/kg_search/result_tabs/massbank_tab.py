from __future__ import annotations

import pandas as pd
import gradio as gr

from massbank_rdf.db.massbank.database import MassBankDatabase
from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.services.kg.candidate_ranking import (
    rank_candidates_with_kg_metadata,
)
from massbank_rdf.services.kg.metadata_score_service import KgMetadataScoreService


def make_empty_massbank_dataframe() -> pd.DataFrame:
    """Create an empty MassBank result table."""
    return pd.DataFrame(
        columns=[
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
            "ms_type",
            "collision_energy",
            "retention_time",
            "instrument_type",
            "ionization",
            "ionization_voltage",
            "fragmentation_mode",
            "ac_instrument",
            "splash",
        ]
    )


def format_massbank_result_dataframe(
    result_df: pd.DataFrame,
) -> pd.DataFrame:
    """Attach MassBank record information and format result table.

    Input result_df is expected to contain internal id, cosine_score,
    and matched_peak_count.
    """
    if result_df is None or result_df.empty:
        return make_empty_massbank_dataframe()

    if "id" not in result_df.columns:
        return result_df

    score_df = result_df.copy()

    record_ids = (
        score_df["id"]
        .dropna()
        .astype(int)
        .tolist()
    )

    if not record_ids:
        return make_empty_massbank_dataframe()

    db = MassBankDatabase()
    record_df = db.get_records_by_ids_dataframe(record_ids)

    if record_df.empty:
        return make_empty_massbank_dataframe()

    merged_df = score_df.merge(
        record_df,
        on="id",
        how="left",
    )

    hidden_columns = {
        "id",
        "record_id",
        "massbank_record_id",
        "dot_product",
        "reference_norm_square",
    }

    merged_df = merged_df.drop(
        columns=[col for col in hidden_columns if col in merged_df.columns],
        errors="ignore",
    )

    if "cosine_score" in merged_df.columns:
        merged_df["cosine_score"] = (
            pd.to_numeric(merged_df["cosine_score"], errors="coerce")
            .round(3)
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

    first_columns = [
        "score",
        "match",
    ]

    record_columns = [
        "accession_id",
        "name",
        "inchikey",
        "smiles",
        "formula",
        "precursor_mz",
        "precursor_type",
        "ion_mode",
        "ms_type",
        "collision_energy",
        "retention_time",
        "instrument_type",
        "ionization",
        "ionization_voltage",
        "fragmentation_mode",
        "ac_instrument",
        "splash",
    ]

    ordered_columns: list[str] = []

    for col in first_columns:
        if col in merged_df.columns:
            ordered_columns.append(col)

    for col in record_columns:
        if col in merged_df.columns and col not in ordered_columns:
            ordered_columns.append(col)

    for col in merged_df.columns:
        if col not in ordered_columns:
            ordered_columns.append(col)

    return merged_df[ordered_columns]


def create_massbank_tab() -> gr.Dataframe:
    """Create MassBank tab components."""
    result_table = gr.Dataframe(
        label="MassBank search results",
        value=make_empty_massbank_dataframe(),
        interactive=False,
        wrap=True,
    )

    return result_table


def build_massbank_loader(
    session_store: TemporarySessionStore,
    *,
    session_cookie_name: str = "kg_session_id",
):
    """Build callback for loading MassBank result."""

    def _load_massbank_result(
        request: gr.Request,
    ) -> tuple[pd.DataFrame, gr.update]:
        session_id = (
            request.request.cookies.get(session_cookie_name)
            or request.request.query_params.get("job_id")
        )

        if not session_id:
            return (
                make_empty_massbank_dataframe(),
                gr.update(selected="massbank"),
            )

        payload = session_store.get(session_id)

        if payload is None:
            return (
                make_empty_massbank_dataframe(),
                gr.update(selected="massbank"),
            )

        if not isinstance(payload, dict):
            return (
                make_empty_massbank_dataframe(),
                gr.update(selected="massbank"),
            )

        result_df = payload.get("result_df")

        if result_df is None:
            result_df = make_empty_massbank_dataframe()
        elif not isinstance(result_df, pd.DataFrame):
            result_df = pd.DataFrame(result_df)

        formatted_df = format_massbank_result_dataframe(result_df)
        formatted_df = rank_candidates_with_kg_metadata(
            formatted_df,
            KgMetadataScoreService(),
        )

        payload["massbank_display_df"] = formatted_df
        session_store.set(session_id, payload)

        return formatted_df, gr.update(selected="massbank")

    return _load_massbank_result
